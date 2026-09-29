"""
Research Agent Swarm — Orchestrator (Python + Microsoft Agent Framework).

A FastAPI app that:
- Serves the DevUI from wwwroot/
- Accepts research topics over WebSocket /ws/agents
- Runs a MAF Workflow (lead → parallel research → review/handoff → report)
- Streams workflow events to the UI in real time
- Each researcher branch provisions an Azure Container Apps Sandbox via
  the `run_in_sandbox` tool

Run locally:
    uvicorn orchestrator:app --host 0.0.0.0 --port 5000
"""
from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from agent_framework import WorkflowEvent
from dotenv import load_dotenv
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

# Load .env if present (env vars set by the platform always win)
load_dotenv(override=False)

from agents import (                            # noqa: E402
    MAX_RESEARCHERS,
    MAX_RESEARCH_WAVES,
    ResearchInput,
    build_research_workflow,
)
from sandbox_manager import (                   # noqa: E402
    REGIONS,
    SandboxManager,
    region_to_sandbox_group_name,
    validate_region,
)

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("orchestrator")


def _extract_text(value: object) -> str | None:
    """Best-effort extraction of text from workflow event payloads."""
    if value is None:
        return None

    if isinstance(value, str):
        s = value.strip()
        return s or None

    if isinstance(value, dict):
        # Common shapes from agent / workflow wrappers.
        for key in ("markdown", "report", "text", "answer", "content"):
            if key in value:
                extracted = _extract_text(value.get(key))
                if extracted:
                    return extracted
        return None

    if isinstance(value, list):
        parts: list[str] = []
        for item in value:
            extracted = _extract_text(item)
            if extracted:
                parts.append(extracted)
        joined = "\n\n".join(parts).strip()
        return joined or None

    # AgentExecutorResponse-like shape: .agent_response.text
    agent_response = getattr(value, "agent_response", None)
    if agent_response is not None:
        extracted = _extract_text(getattr(agent_response, "text", None))
        if extracted:
            return extracted

    # Generic object with a .text field.
    extracted = _extract_text(getattr(value, "text", None))
    if extracted:
        return extracted

    return None


# ── App + lifespan ──────────────────────────────────────────────────────────

async def _prewarm_disk_image(mgr: SandboxManager) -> None:
    """
    Background pre-warm: ensure the sandbox group is reachable and the disk
    image is built (or matches the current ACR digest) so the first user
    request doesn't pay the ~25 s creation cost. Failures are logged and do
    not block app startup — the user-facing path will surface the same error
    if/when it's exercised.
    """
    try:
        region = validate_region(os.environ.get("DEFAULT_REGION"))
        await mgr.ensure_sandbox_group(region)
        await mgr.prepare_disk_image(
            status_cb=lambda msg, lvl="info": _log_status(lvl, msg),
        )
    except Exception as ex:
        logger.warning("[Prewarm] Disk image pre-warm failed: %s", ex)


async def _log_status(level: str, msg: str) -> None:
    getattr(logger, level if level in ("info", "warning", "error") else "info")(
        "[Prewarm] %s", msg,
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.sandbox_mgr = SandboxManager()
    # Kick off disk-image pre-warm in the background. Skip when explicitly
    # disabled (e.g. for fast unit tests or local dev without Azure access).
    if os.environ.get("DISK_IMAGE_PREWARM", "true").lower() in ("1", "true", "yes"):
        app.state.prewarm_task = asyncio.create_task(
            _prewarm_disk_image(app.state.sandbox_mgr)
        )
    try:
        yield
    finally:
        task: asyncio.Task | None = getattr(app.state, "prewarm_task", None)
        if task and not task.done():
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass
        await app.state.sandbox_mgr.aclose()


app = FastAPI(title="Research Agent Swarm Orchestrator", lifespan=lifespan)

# Wire OpenTelemetry → Application Insights before serving any requests, so
# agent runs, tool calls, and sandbox spans are captured from the first request.
from observability import setup_observability  # noqa: E402

setup_observability(app)


# ── REST endpoints ──────────────────────────────────────────────────────────

@app.get("/health")
async def health() -> dict:
    return {"status": "healthy"}


@app.get("/regions")
async def regions() -> list[dict]:
    return [{"id": k, "name": v} for k, v in REGIONS.items()]


@app.get("/diag")
async def diag() -> dict:
    return {
        "hasOpenAiEndpoint": bool(os.environ.get("AZURE_OPENAI_ENDPOINT")),
        "openAiAuth":        "managed-identity",
        "openAiDeployment":  os.environ.get("AZURE_OPENAI_DEPLOYMENT"),
        "diskImageId":       os.environ.get("DISK_IMAGE_ID"),
        "defaultRegion":     os.environ.get("DEFAULT_REGION", "westus2"),
        "maxResearchers":    MAX_RESEARCHERS,
        "maxResearchWaves":  MAX_RESEARCH_WAVES,
    }


# ── Disk image management (used by the Sandbox Management panel) ───────────────

async def _ensure_sg(mgr: SandboxManager) -> None:
    region = validate_region(os.environ.get("DEFAULT_REGION"))
    await mgr.ensure_sandbox_group(region)


@app.get("/api/sandbox/info")
async def sandbox_info() -> dict:
    mgr: SandboxManager = app.state.sandbox_mgr
    return {
        "disk_image": mgr.disk_image_info(),
        "stats":      mgr.stats(),
    }


async def _run_with_collector(coro_fn) -> dict:
    """
    Helper: run a SandboxManager method that takes a status_cb, collect the
    log lines, and return them along with the post-action info snapshot.
    """
    logs: list[dict] = []

    async def collect(msg: str, level: str = "info") -> None:
        logs.append({"message": msg, "level": level})

    error: str | None = None
    try:
        await coro_fn(collect)
    except Exception as ex:
        error = str(ex)
        logs.append({"message": f"Operation failed: {ex}", "level": "error"})

    mgr: SandboxManager = app.state.sandbox_mgr
    return {
        "logs":       logs,
        "error":      error,
        "disk_image": mgr.disk_image_info(),
        "stats":      mgr.stats(),
    }


@app.post("/api/sandbox/disk-image/recreate")
async def recreate_disk_image() -> dict:
    mgr: SandboxManager = app.state.sandbox_mgr
    await _ensure_sg(mgr)
    return await _run_with_collector(
        lambda cb: mgr.prepare_disk_image(cb, force=True)
    )


@app.post("/api/sandbox/egress-probe")
async def egress_probe(wait: int = 120) -> dict:
    """Diagnostic: spin up a throwaway sandbox, let the research agent make its
    outbound calls, and report the stored egress policy plus which hosts were
    actually allowed/denied. Confirms default-deny + Foundry/AOAI-only egress.

    The sandbox stays alive for `wait` seconds (default 120) so you can inspect
    it in the portal or curl it while it runs.
    """
    mgr: SandboxManager = app.state.sandbox_mgr
    await _ensure_sg(mgr)
    logs: list[dict] = []

    async def collect(msg: str, level: str = "info") -> None:
        logs.append({"message": msg, "level": level})

    error: str | None = None
    probe: dict = {}
    try:
        probe = await mgr.probe_egress(wait_seconds=wait, status_cb=collect)
    except Exception as ex:
        error = str(ex)
        logs.append({"message": f"Egress probe failed: {ex}", "level": "error"})

    return {"logs": logs, "error": error, "probe": probe}


@app.delete("/api/sandbox/disk-image")
async def delete_disk_image() -> dict:
    mgr: SandboxManager = app.state.sandbox_mgr
    await _ensure_sg(mgr)
    return await _run_with_collector(mgr.delete_current_disk_image)


@app.post("/api/sandbox/disk-image/prune-all")
async def prune_all_disk_images() -> dict:
    """Delete every managed disk image — cleanup utility."""
    mgr: SandboxManager = app.state.sandbox_mgr
    await _ensure_sg(mgr)
    return await _run_with_collector(mgr.prune_managed_disk_images)


# ── WebSocket pipeline ──────────────────────────────────────────────────────

@app.websocket("/ws/agents")
async def ws_agents(ws: WebSocket) -> None:
    await ws.accept()
    try:
        while True:
            message = await ws.receive_json()
            if message.get("type") == "research":
                topic  = message["topic"]
                asyncio.create_task(_run_research_pipeline(ws, topic))
    except WebSocketDisconnect:
        return
    except Exception as ex:
        logger.exception("[WS] Unexpected error: %s", ex)


async def _run_research_pipeline(ws: WebSocket, topic: str) -> None:
    """Run the MAF workflow and stream its events to the WebSocket."""
    sandbox_mgr: SandboxManager = app.state.sandbox_mgr

    ws_lock = asyncio.Lock()

    async def emit(payload: dict) -> None:
        async with ws_lock:
            try:
                await ws.send_json(payload)
            except Exception:
                pass

    try:
        await emit({"type": "log", "message": f"Received topic: {topic}", "level": "info"})

        # 0. Ensure sandbox group is reachable. The region is always the one the
        # infrastructure was provisioned in (DEFAULT_REGION) — the sandbox group
        # only exists there — so we ignore any client-supplied region.
        region = validate_region(os.environ.get("DEFAULT_REGION"))
        region_display = REGIONS.get(region, region)
        group_name = (
            os.environ.get("SANDBOX_GROUP")
            or region_to_sandbox_group_name(region)
        )
        await emit({
            "type": "log",
            "message": f"Region: {region_display} — verifying sandbox group '{group_name}'...",
            "level": "info",
        })
        try:
            await sandbox_mgr.ensure_sandbox_group(region)
        except Exception as ex:
            await emit({
                "type": "log",
                "message": f"Failed to reach sandbox group: {ex}",
                "level": "error",
            })
            return

        await emit({
            "type": "log",
            "message": f"Sandbox group '{group_name}' ready in {region_display}",
            "level": "success",
        })

        # Pre-warm the disk image once. All researcher sandboxes share it.
        async def disk_status_cb(msg: str, level: str = "info") -> None:
            await emit({"type": "log", "message": msg, "level": level})

        try:
            await sandbox_mgr.prepare_disk_image(disk_status_cb)
        except Exception as ex:
            await emit({
                "type": "log",
                "message": f"Failed to prepare disk image: {ex}",
                "level": "error",
            })
            return

        await emit({
            "type": "log",
            "message": "Starting MAF workflow (lead → parallel wave → review → report)...",
            "level": "info",
        })

        # Per-researcher state (sandbox_mgr + emit + index) is bound via
        # closure inside build_research_workflow, so we build the workflow
        # fresh each request.
        workflow = build_research_workflow(sandbox_mgr, emit)

        # Run the workflow streaming. The events we map to UI messages:
        #   - executor lifecycle for mesh agents             → {type: stage}
        #   - WorkflowEvent(type="output") from research lead → {type: questions}
        #   - WorkflowEvent(type="output") from reviewer      → {type: review}
        #   - WorkflowEvent(type="output") from report writer → {type: report}
        #   - WorkflowEvent(type="executor_failed")          → log error
        #   (per-agent {type: "agent"|"result"|"log"} are emitted directly by
        #    the researcher tool through the `emit` callback above.)
        final_report: str | None = None

        stream = workflow.run(
            ResearchInput(topic=topic),
            stream=True,
        )

        async for event in stream:
            if not isinstance(event, WorkflowEvent):
                continue

            etype = event.type

            if etype == "executor_invoked":
                source = event.executor_id or ""
                if source in {"research_lead", "reviewer", "report_writer"}:
                    await emit({
                        "type": "stage",
                        "stage": source,
                        "status": "active",
                    })

            elif etype in ("output", "data"):
                source = event.executor_id or ""
                data = event.data
                if (
                    source == "research_lead"
                    and isinstance(data, dict)
                    and data.get("kind") == "questions"
                ):
                    questions = data.get("questions") or []
                    wave = int(data.get("wave") or 1)
                    await emit({
                        "type": "questions",
                        "questions": questions,
                        "wave": wave,
                    })
                    await emit({
                        "type": "log",
                        "message": (
                            f"Research Lead dispatched wave {wave} "
                            f"with {len(questions)} questions"
                        ),
                        "level": "success",
                    })
                elif (
                    source == "reviewer"
                    and isinstance(data, dict)
                    and data.get("kind") == "review"
                ):
                    await emit({
                        "type": "review",
                        "status": data.get("status"),
                        "rationale": data.get("rationale"),
                        "wave": data.get("wave"),
                        "followUpQuestions": data.get("follow_up_questions") or [],
                    })
                    destination = (
                        "Research Lead"
                        if data.get("status") == "needs_more_research"
                        else "Report Writer"
                    )
                    await emit({
                        "type": "log",
                        "message": f"Reviewer handed off to {destination}: {data.get('rationale')}",
                        "level": "info",
                    })
                elif source == "report_writer":
                    extracted = _extract_text(data)
                    if extracted:
                        final_report = extracted

            elif etype == "executor_completed":
                source = event.executor_id or ""
                if source in {"research_lead", "reviewer", "report_writer"}:
                    await emit({
                        "type": "stage",
                        "stage": source,
                        "status": "complete",
                    })
                if source == "report_writer" and not final_report:
                    extracted = _extract_text(event.data)
                    if extracted:
                        final_report = extracted

            elif etype == "executor_failed":
                source = event.executor_id or "?"
                err = event.details or event.data or ""
                await emit({
                    "type": "log",
                    "message": f"Executor '{source}' failed: {err}",
                    "level": "error",
                })

            # Other event types (executor_invoked, executor_completed,
            # superstep_*, status, data, ...) are intentionally ignored:
            # the per-researcher tool already emits richer UI updates.

        if final_report:
            await emit({"type": "report", "markdown": final_report})
            await emit({"type": "log", "message": "Research complete!", "level": "success"})
        else:
            raise RuntimeError("Workflow completed without a synthesized report")

        # Notify the UI that disk-image / stats panels should refresh.
        # NOTE: We deliberately do NOT delete the disk image here — it is
        # cached across runs and only rebuilt when the ACR digest changes
        # or the user clicks "Re-create disk image".
        await emit({"type": "sandbox_info_changed"})

    except Exception as ex:
        logger.exception("[Pipeline] %s", ex)
        await emit({"type": "pipeline_error", "message": f"Pipeline error: {ex}"})


# ── Static UI (mounted last) ────────────────────────────────────────────────

WWWROOT = Path(__file__).parent / "wwwroot"
if WWWROOT.is_dir():
    app.mount("/", StaticFiles(directory=str(WWWROOT), html=True), name="wwwroot")
else:
    @app.get("/")
    async def index() -> JSONResponse:  # pragma: no cover
        return JSONResponse({"error": "wwwroot not found"}, status_code=500)


# ── Entry point ─────────────────────────────────────────────────────────────
# Run with `python orchestrator.py`. Honors PORT, HOST, and RELOAD env vars.

if __name__ == "__main__":
    import uvicorn

    host   = os.environ.get("HOST", "0.0.0.0")
    port   = int(os.environ.get("PORT", "5000"))
    reload = os.environ.get("RELOAD", "true").lower() in ("1", "true", "yes")

    uvicorn.run(
        "orchestrator:app",
        host=host,
        port=port,
        reload=reload,
    )

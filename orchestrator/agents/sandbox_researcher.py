"""
Sandbox research runner, called directly by each researcher executor in the workflow.

Each parallel branch provisions an Azure Container Apps sandbox, polls the research
agent running inside it, and returns the sandbox's JSON result. There's no LLM on
this side: the research agent (model calls and web search) runs in the sandbox.

`sandbox_mgr`, the per-WebSocket `emit` callable, and the branch `index` are bound
via closure when the runner is built.
"""
import asyncio
import json
import logging
import uuid
from typing import Awaitable, Callable

from sandbox_manager import AgentResult, SandboxManager

logger = logging.getLogger(__name__)


EmitFn = Callable[[dict], Awaitable[None]]

# Poll-loop resilience: a single transient error (e.g. a 502 from the sandbox
# egress proxy while the sandbox port warms up) must not kill a researcher.
POLL_TIMEOUT_SECONDS = 360
MAX_CONSECUTIVE_POLL_ERRORS = 8


def build_sandbox_researcher(
    agent_id: str,
    sandbox_mgr: SandboxManager,
    emit: EmitFn,
    index: int,
) -> Callable[[str], Awaitable[str]]:
    """Bind one branch's sandbox lifecycle and progress reporting."""
    async def run_in_sandbox(question: str) -> str:
        """Provision an ACA Sandbox, run the research agent, return JSON results."""
        sandbox_id = f"agent-{index}-{uuid.uuid4().hex[:8]}"

        async def log(msg: str, level: str = "info") -> None:
            await emit({"type": "log", "message": msg, "level": level})

        async def agent_status(status: str) -> None:
            await emit({
                "type": "agent",
                "index": index,
                "question": question,
                "status": status,
                "sandboxId": sandbox_id,
            })

        await agent_status("provisioning")
        try:
            await sandbox_mgr.create_sandbox(sandbox_id, question)
        except Exception as ex:
            logger.exception("[%s] create_sandbox failed", agent_id)
            await agent_status("error")
            await log(f"Failed to create sandbox: {ex}", "error")
            raise RuntimeError(f"Sandbox creation failed: {ex}") from ex

        await agent_status("researching")
        await log(f"Sandbox {sandbox_id} running", "success")

        # Poll until done/error. Tolerate transient errors (e.g. the sandbox port
        # proxy occasionally returns 502 on /status while the sandbox port warms
        # up). A single transient failure must NOT kill the researcher, otherwise
        # its executor fails, never delivers to the fan-in, and the reviewer
        # receives partial results while the UI is stuck on "researching".
        result: AgentResult | None = None
        poll_deadline = asyncio.get_event_loop().time() + POLL_TIMEOUT_SECONDS
        consecutive_errors = 0
        try:
            heartbeat = 0
            while True:
                await asyncio.sleep(2)
                if asyncio.get_event_loop().time() > poll_deadline:
                    await agent_status("error")
                    await log(
                        f"Agent {index + 1} timed out after {POLL_TIMEOUT_SECONDS}s", "error"
                    )
                    raise TimeoutError(
                        f"Research timed out after {POLL_TIMEOUT_SECONDS}s"
                    )
                try:
                    status = await sandbox_mgr.get_status(sandbox_id)
                    consecutive_errors = 0
                except Exception as ex:
                    consecutive_errors += 1
                    logger.warning(
                        "[%s] get_status transient error %d/%d: %s",
                        agent_id, consecutive_errors, MAX_CONSECUTIVE_POLL_ERRORS, ex,
                    )
                    if consecutive_errors >= MAX_CONSECUTIVE_POLL_ERRORS:
                        await agent_status("error")
                        await log(
                            f"Agent {index + 1} error: sandbox unreachable ({ex})", "error"
                        )
                        raise RuntimeError(f"Sandbox became unreachable: {ex}") from ex
                    continue
                if status.status == "done":
                    try:
                        result = await sandbox_mgr.get_result(sandbox_id)
                        break
                    except Exception as ex:
                        consecutive_errors += 1
                        logger.warning("[%s] get_result transient error: %s", agent_id, ex)
                        if consecutive_errors >= MAX_CONSECUTIVE_POLL_ERRORS:
                            await agent_status("error")
                            await log(
                                f"Agent {index + 1} error: result unreachable ({ex})", "error"
                            )
                            raise RuntimeError(f"Sandbox result unreachable: {ex}") from ex
                        continue
                if status.status == "error":
                    await agent_status("error")
                    await log(f"Agent {index + 1} error: {status.progress}", "error")
                    raise RuntimeError(
                        f"Sandbox research failed: {status.error or status.progress}"
                    )
                heartbeat += 1
                if heartbeat % 5 == 0:
                    await log(f"Agent {index + 1} still researching...", "info")
        finally:
            try:
                await sandbox_mgr.delete_sandbox(sandbox_id)
            except Exception:
                pass

        await agent_status("done")
        await emit({
            "type": "result",
            "index": index,
            "answer": result.answer,
            "sources": result.sources,
        })
        await log(f"Agent {index + 1} completed research", "success")

        return json.dumps({
            "question": result.question,
            "answer": result.answer,
            "sources": result.sources,
            "confidence": result.confidence,
        })

    return run_in_sandbox

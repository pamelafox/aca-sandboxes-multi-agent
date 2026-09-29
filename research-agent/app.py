"""
Research Agent — runs inside an ACA Sandbox.

Uses Microsoft Agent Framework with Foundry's hosted web-search tool to research
a question from the RESEARCH_QUESTION env var. Exposes results via Flask API.

Web search runs server-side in the Foundry project, so this sandbox only needs
egress to the Foundry endpoint (no search-engine egress). Research fails
explicitly if grounded Foundry search is unavailable.
"""

import asyncio
import json
import os
import ssl
import threading
import time
import traceback

import requests
from flask import Flask, jsonify

# Sandbox egress proxy does TLS interception — disable SSL verification
os.environ.setdefault("CURL_CA_BUNDLE", "")
os.environ.setdefault("REQUESTS_CA_BUNDLE", "")
os.environ.setdefault("SSL_CERT_FILE", "")
# For httpx (used by openai SDK)
os.environ.setdefault("SSL_VERIFY", "0")

import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# The sandbox egress proxy does TLS interception. The Azure Monitor exporter
# talks to App Insights through `requests` (via azure-core), which does not honor
# the *_CA_BUNDLE env vars the same way, so force-disable verification for every
# requests Session. This is safe here: all egress is already restricted to an
# allow-list by the sandbox's default-deny egress policy.
try:
    import requests as _rq

    _orig_merge = _rq.sessions.Session.merge_environment_settings

    def _merge_no_verify(self, url, proxies, stream, verify, cert):
        settings = _orig_merge(self, url, proxies, stream, verify, cert)
        settings["verify"] = False
        return settings

    _rq.sessions.Session.merge_environment_settings = _merge_no_verify
except Exception:
    pass


def _setup_observability():
    """Export OpenTelemetry traces to App Insights and join the orchestrator's
    trace via the forwarded W3C trace context. No-op without a connection string.

    Returns the extracted parent context (or None) so the research span can be
    linked to the orchestrator's ``sandbox.create`` span.
    """
    conn = os.environ.get("APPLICATIONINSIGHTS_CONNECTION_STRING")
    if not conn:
        return None
    try:
        from azure.monitor.opentelemetry import configure_azure_monitor

        configure_azure_monitor(connection_string=conn)
    except Exception as ex:
        print(f"[observability] configure_azure_monitor failed: {ex}", flush=True)
        return None
    try:
        from agent_framework.observability import enable_instrumentation

        enable_instrumentation()
    except Exception as ex:
        print(f"[observability] enable_instrumentation failed: {ex}", flush=True)
    try:
        from opentelemetry.propagate import extract

        return extract(
            {
                "traceparent": os.environ.get("TRACEPARENT", ""),
                "tracestate": os.environ.get("TRACESTATE", ""),
            }
        )
    except Exception:
        return None


_PARENT_CTX = _setup_observability()

app = Flask(__name__)

# ── shared state ────────────────────────────────────────────────────────
state = {
    "status": "starting",   # starting | working | done | error
    "progress": "Initializing...",
    "question": os.environ.get("RESEARCH_QUESTION", ""),
    "answer": None,
    "sources": [],
    "confidence": 0.0,
    "error": None,
}
state_lock = threading.Lock()


# ── Agent Framework research (Foundry hosted web search) ───────────────
async def _run_agent_research(question: str) -> dict:
    """Use Microsoft Agent Framework + Foundry's hosted web-search tool.

    The search executes server-side in the Foundry project, so this sandbox
    never calls a search engine directly — it only talks to the Foundry endpoint.
    """
    import time as _time

    import httpx
    from agent_framework import Agent
    from agent_framework.foundry import FoundryChatClient
    from azure.ai.projects.aio import AIProjectClient
    from azure.core.credentials import AccessToken
    from azure.core.pipeline.transport import AioHttpTransport

    project_endpoint = os.environ["FOUNDRY_PROJECT_ENDPOINT"]
    model = os.environ.get("AZURE_OPENAI_DEPLOYMENT", "gpt-5.6-luna")

    # No credential lives in this sandbox. The SDK requires one, so hand it a
    # placeholder; the egress proxy replaces the Authorization header with an
    # Entra token for the sandbox group's managed identity.
    class _ProxyInjectedCredential:
        async def get_token(self, *scopes: str, **kwargs: object) -> AccessToken:
            return AccessToken("injected-by-egress-proxy", int(_time.time()) + 3600)

        async def close(self) -> None:
            return None

        async def __aenter__(self) -> "_ProxyInjectedCredential":
            return self

        async def __aexit__(self, *exc: object) -> None:
            return None

    # Sandbox egress proxy does TLS interception — disable cert verification on both
    # the AIProjectClient transport and the OpenAI (Responses) client it builds.
    project_client = AIProjectClient(
        endpoint=project_endpoint,
        credential=_ProxyInjectedCredential(),
        transport=AioHttpTransport(connection_verify=False),
    )
    _orig_get_openai_client = project_client.get_openai_client

    def _get_openai_client(**kwargs: object):  # type: ignore[no-untyped-def]
        kwargs.setdefault("http_client", httpx.AsyncClient(verify=False))
        return _orig_get_openai_client(**kwargs)

    project_client.get_openai_client = _get_openai_client  # type: ignore[assignment]

    client = FoundryChatClient(project_client=project_client, model=model)

    agent = Agent(
        client=client,
        name="ResearchAgent",
        instructions=(
            "You are a thorough research agent. For the given question:\n"
            "1. Use web search to find current, factual information\n"
            "2. Synthesize findings into a comprehensive answer\n"
            "3. Return your answer as JSON with these fields:\n"
            '   "answer": "<detailed markdown answer with key findings>",\n'
            '   "sources": ["<url1>", "<url2>", ...],\n'
            '   "confidence": <float 0-1>\n'
            "Return ONLY valid JSON, no extra text or code fences."
        ),
        tools=[FoundryChatClient.get_web_search_tool()],
        default_options={"reasoning": {"effort": "low"}},
    )

    response = await agent.run(question)
    raw = str(response).strip()

    # Strip markdown code fences if present
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
        if raw.endswith("```"):
            raw = raw[:-3]
        raw = raw.strip()

    result = json.loads(raw)
    if not isinstance(result, dict):
        raise ValueError("Research agent response must be a JSON object")
    if not isinstance(result.get("answer"), str) or not result["answer"].strip():
        raise ValueError("Research agent response is missing a non-empty answer")
    if not isinstance(result.get("sources"), list):
        raise ValueError("Research agent response is missing a sources array")
    return result


# ── network connectivity test ──────────────────────────────────────────
def _test_connectivity(endpoint: str) -> str:
    """Test DNS resolution and TCP connectivity to endpoint."""
    import socket
    from urllib.parse import urlparse
    results = []
    parsed = urlparse(endpoint)
    host = parsed.hostname or endpoint
    port = parsed.port or 443

    # DNS test
    try:
        addrs = socket.getaddrinfo(host, port, socket.AF_INET, socket.SOCK_STREAM)
        ip = addrs[0][4][0] if addrs else "?"
        results.append(f"DNS:{host}->{ip}")
    except Exception as e:
        results.append(f"DNS_FAIL:{host}:{e}")
        return "; ".join(results)

    # TCP test
    try:
        sock = socket.create_connection((host, port), timeout=5)
        sock.close()
        results.append(f"TCP:{host}:{port}->OK")
    except Exception as e:
        results.append(f"TCP_FAIL:{host}:{port}:{e}")

    # HTTPS test (skip SSL verification — sandbox egress proxy uses self-signed certs)
    try:
        resp = requests.get(f"https://{host}/", timeout=5, verify=False)
        results.append(f"HTTPS:{resp.status_code}")
    except Exception as e:
        results.append(f"HTTPS_FAIL:{type(e).__name__}")

    return "; ".join(results)


# ── background research thread ─────────────────────────────────────────
def _research_worker():
    global state
    question = state["question"]

    if not question:
        with state_lock:
            state["status"] = "error"
            state["progress"] = "No research question provided"
            state["error"] = "RESEARCH_QUESTION env var is empty"
        return

    # Wrap the whole run in a span that joins the orchestrator's trace, so the
    # in-sandbox agent run and its tool calls appear under the same end-to-end
    # transaction in Application Insights.
    try:
        from opentelemetry import trace as _trace

        tracer = _trace.get_tracer("research-agent")
        span_cm = tracer.start_as_current_span(
            "research-agent.run", context=_PARENT_CTX
        )
    except Exception:
        import contextlib

        span_cm = contextlib.nullcontext()

    with span_cm as _sp:
        if _sp is not None:
            try:
                _sp.set_attribute("research.question", question[:200])
            except Exception:
                pass
        _do_research(question)


def _do_research(question: str):
    endpoint = os.environ.get("AZURE_OPENAI_ENDPOINT", "")

    with state_lock:
        state["status"] = "working"
        state["progress"] = "Waiting for network egress..."

    # Wait for egress policy to be applied, then test connectivity
    conn_info = "no endpoint"
    if endpoint:
        time.sleep(5)
        conn_info = _test_connectivity(endpoint)
        with state_lock:
            state["progress"] = f"Connectivity: {conn_info}"

    try:
        result = _run_research_with_retries(question, conn_info=conn_info)

        with state_lock:
            state["status"] = "done"
            state["progress"] = "Research complete"
            state["answer"] = result.get("answer", "")
            state["sources"] = result.get("sources", [])
            state["confidence"] = result.get("confidence", 0.0)

    except Exception as exc:
        with state_lock:
            state["status"] = "error"
            state["progress"] = f"Error: {exc}"
            state["error"] = traceback.format_exc()


def _run_research_with_retries(question: str, max_retries: int = 3, conn_info: str = "") -> dict:
    """Run grounded Foundry research, retrying transient failures."""
    if not os.environ.get("FOUNDRY_PROJECT_ENDPOINT"):
        raise RuntimeError("FOUNDRY_PROJECT_ENDPOINT is missing in the sandbox environment")

    errors = [f"CONNECTIVITY: {conn_info}"]
    for attempt in range(max_retries):
        with state_lock:
            state["progress"] = f"Research attempt {attempt + 1}/{max_retries}..."

        try:
            return asyncio.run(_run_agent_research(question))
        except Exception as foundry_error:
            errors.append(
                f"Foundry attempt {attempt + 1}: "
                f"{type(foundry_error).__name__}: {foundry_error}"
            )

        # Wait before retry (egress might not be ready yet)
        if attempt < max_retries - 1:
            delay = 5 * (attempt + 1)
            with state_lock:
                state["progress"] = f"Retrying in {delay}s (attempt {attempt + 1} failed)..."
            time.sleep(delay)

    raise RuntimeError("Grounded Foundry research failed:\n" + "\n".join(errors))


# ── Flask routes ────────────────────────────────────────────────────────
@app.route("/health")
def health():
    return jsonify({"status": "healthy"})


@app.route("/debug")
def debug():
    """Debug endpoint showing detailed error info and environment."""
    with state_lock:
        return jsonify({
            "status": state["status"],
            "progress": state["progress"],
            "error": state.get("error"),
            "has_openai_endpoint": bool(os.environ.get("AZURE_OPENAI_ENDPOINT")),
            "has_openai_deployment": bool(os.environ.get("AZURE_OPENAI_DEPLOYMENT")),
            "question": state["question"][:50] if state["question"] else None,
        })


@app.route("/status")
def status():
    with state_lock:
        return jsonify({
            "status": state["status"],
            "progress": state["progress"],
            "error": state.get("error"),
            "has_openai": bool(os.environ.get("AZURE_OPENAI_ENDPOINT")),
        })


@app.route("/result")
def result():
    with state_lock:
        if state["status"] != "done":
            return jsonify({
                "status": state["status"],
                "message": "Research not yet complete",
            }), 202

        return jsonify({
            "question": state["question"],
            "answer": state["answer"],
            "sources": state["sources"],
            "confidence": state["confidence"],
        })


# ── start background thread on module load ──────────────────────────────
_worker_started = False


def _ensure_worker():
    global _worker_started
    if not _worker_started:
        _worker_started = True
        t = threading.Thread(target=_research_worker, daemon=True)
        t.start()


_ensure_worker()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)

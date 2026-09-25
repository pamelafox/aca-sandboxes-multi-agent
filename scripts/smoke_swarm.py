"""Exercise the deployed research swarm; requires --run and incurs Azure usage."""

import argparse
import asyncio
import json
import os
import tempfile
from pathlib import Path
from urllib.parse import urlparse, urlunparse

from dotenv_azd import load_azd_env
from websockets.asyncio.client import connect


async def smoke(url: str, topic: str, timeout: int, artifacts: Path) -> None:
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("Provide the deployed orchestrator HTTPS URL without credentials.")
    websocket_url = urlunparse(("wss", parsed.netloc, "/ws/agents", "", "", ""))
    questions = []
    results = {}
    statuses = {}
    errors = []
    async with asyncio.timeout(timeout):
        async with connect(websocket_url, open_timeout=30, close_timeout=10, max_size=4 * 1024 * 1024) as socket:
            await socket.send(json.dumps({"type": "research", "topic": topic}))
            print(f"Research submitted to {parsed.hostname}", flush=True)
            with (artifacts / "events.jsonl").open("w") as events:
                async for message in socket:
                    event = json.loads(message)
                    events.write(json.dumps(event) + "\n")
                    events.flush()
                    kind = event.get("type")
                    if kind == "questions":
                        questions = event["questions"]
                        print(f"Decomposed into {len(questions)} questions", flush=True)
                    elif kind == "agent":
                        statuses[event["index"]] = event["status"]
                        print(f"Researcher {event['index']}: {event['status']} ({event.get('sandboxId', 'unknown')})", flush=True)
                        if event["status"] == "error":
                            errors.append(f"Researcher {event['index']} failed")
                    elif kind == "result":
                        results[event["index"]] = event
                    elif kind == "log" and event.get("level") == "error":
                        errors.append(event.get("message", "Server error"))
                    elif kind == "pipeline_error":
                        raise RuntimeError(event.get("message", "Pipeline failed"))
                    elif kind == "report":
                        report = event.get("markdown", "")
                        (artifacts / "report.md").write_text(report)
                        if errors:
                            raise RuntimeError("Pipeline reported errors: " + "; ".join(errors))
                        if not isinstance(questions, list) or len(questions) < 2:
                            raise RuntimeError("Expected at least two decomposed questions to exercise fan-out")
                        expected = set(range(len(questions)))
                        if set(results) != expected or any(statuses.get(index) != "done" for index in expected):
                            raise RuntimeError("Report arrived without successful results from every researcher")
                        for index, result in results.items():
                            if not result.get("answer", "").strip() or not result.get("sources"):
                                raise RuntimeError(f"Researcher {index} returned no answer or sources")
                        if not report.strip():
                            raise RuntimeError("Synthesizer returned an empty report")
                        print(f"PASS: {len(results)} researchers returned answers and sources; synthesis completed.", flush=True)
                        return
    raise RuntimeError("WebSocket closed before a final report")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", action="store_true", help="Confirm a real deployed run and Azure/model charges.")
    parser.add_argument("--url", help="Deployed orchestrator URL; defaults to azd orchestratorUrl.")
    parser.add_argument("--timeout", type=int, default=900, help="Total WebSocket deadline in seconds.")
    parser.add_argument("--topic", default="Compare Azure Blob Storage and Azure Files for sharing application data. Use official Microsoft documentation and cite sources. Keep the research brief.")
    args = parser.parse_args()
    if not args.run:
        parser.error("Pass --run to invoke the deployed swarm and incur Azure/model usage.")
    if args.timeout <= 0:
        parser.error("--timeout must be positive")
    load_azd_env(override=False, quiet=True)
    url = args.url or os.environ.get("orchestratorUrl")
    if not url:
        parser.error("Set --url or select an azd environment with orchestratorUrl")
    artifacts = Path(tempfile.mkdtemp(prefix="swarm-smoke-"))
    print(f"Artifacts: {artifacts}", flush=True)
    print("The server owns researcher cleanup. Disconnecting does not cancel server work.", flush=True)
    try:
        asyncio.run(smoke(url, args.topic, args.timeout, artifacts))
    except (Exception, KeyboardInterrupt) as error:
        print(f"FAIL: {type(error).__name__}: {error}", flush=True)
        print("Check events.jsonl and deployed logs for this run; server cleanup may still be running.", flush=True)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
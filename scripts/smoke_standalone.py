"""Run the real sandbox agent and independently verify its filesystem output."""

import argparse
import csv
import io
import json
import os
import sys
import tempfile
import uuid
from pathlib import Path
from azure.containerapps.sandbox import endpoint_for_region
from azure.identity import DefaultAzureCredential

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from create_sandbox import RegistryIdentitySandboxGroupClient, agent_egress_policy, parse_args, prepare_disk_image


def verify_csv(text: str) -> None:
    rows = list(csv.reader(io.StringIO(text)))
    expected = [["number", "square"]] + [[str(number), str(number * number)] for number in range(1, 11)]
    if rows != expected:
        raise RuntimeError(f"CSV mismatch: expected header and squares 1..10, received {rows!r}")


def smoke(args, artifacts: Path, workdir: str) -> None:
    with DefaultAzureCredential() as credential:
        with RegistryIdentitySandboxGroupClient(
            endpoint_for_region(args.region), credential,
            subscription_id=args.subscription_id, resource_group=args.resource_group,
            sandbox_group=args.sandbox_group,
        ) as group:
            disk_id = args.disk_id
            if args.image:
                print("Stage: prepare published image", flush=True)
                disk_id = prepare_disk_image(
                    group, args.image, args.image_identity_resource_id, args.image_identity_client_id,
                )
            metadata = {
                "subscription_id": args.subscription_id, "resource_group": args.resource_group,
                "sandbox_group": args.sandbox_group, "region": args.region,
                "disk_image_id": disk_id, "workdir": workdir,
            }
            (artifacts / "resources.json").write_text(json.dumps(metadata, indent=2))
            endpoint = os.environ["AZURE_OPENAI_ENDPOINT"]
            print("Stage: create sandbox", flush=True)
            labels = {"demo": "standalone-smoke", "run": workdir.rsplit("/", 1)[-1]}
            metadata["labels"] = labels
            (artifacts / "resources.json").write_text(json.dumps(metadata, indent=2))
            sandbox = None
            try:
                sandbox = group.begin_create_sandbox(
                    disk=None, disk_id=disk_id, cpu="500m", memory="1Gi", auto_suspend_seconds=300,
                    labels=labels, polling_timeout=180, polling_interval=2,
                    egress_policy=agent_egress_policy(endpoint, args.image_identity_resource_id),
                    environment={
                        "AGENT_PROMPT": args.prompt,
                        "AZURE_OPENAI_ENDPOINT": endpoint,
                        "AZURE_OPENAI_DEPLOYMENT": os.environ["AZURE_OPENAI_DEPLOYMENT"],
                    },
                ).result()
                metadata["sandbox_id"] = sandbox.sandbox_id
                (artifacts / "resources.json").write_text(json.dumps(metadata, indent=2))
                print(f"Sandbox: {sandbox.sandbox_id}", flush=True)
                print("Stage: execute real agent (330-second remote deadline)", flush=True)
                result = sandbox.exec("timeout 330 /usr/local/bin/python /app/sandbox_agent.py")
                (artifacts / "agent.stdout.txt").write_text(result.stdout or "")
                (artifacts / "agent.stderr.txt").write_text(result.stderr or "")
                if result.exit_code:
                    raise RuntimeError(f"Agent exited with code {result.exit_code}; see agent.stderr.txt")
                print("Stage: read and validate the agent-created CSV", flush=True)
                result = sandbox.exec(f"cat {workdir}/squares.csv")
                if result.exit_code:
                    raise RuntimeError("Agent did not create a readable squares.csv")
                (artifacts / "squares.csv").write_text(result.stdout)
                verify_csv(result.stdout)
                script = sandbox.exec(f"cat {workdir}/squares.sh")
                if script.exit_code or not script.stdout.strip():
                    raise RuntimeError("Agent did not create a nonempty squares.sh")
                (artifacts / "squares.sh").write_text(script.stdout)
                print("Stage: rerun the generated Bash script and verify its output", flush=True)
                result = sandbox.exec(
                    f"rm {workdir}/squares.csv && timeout 30 bash {workdir}/squares.sh && cat {workdir}/squares.csv",
                    working_directory=workdir,
                )
                if result.exit_code:
                    raise RuntimeError(f"Generated script failed with code {result.exit_code}")
                verify_csv(result.stdout)
            finally:
                try:
                    sandbox_ids = [sandbox.sandbox_id] if sandbox else [
                        item.id for item in group.list_sandboxes(labels=labels)
                        if all(item.labels.get(key) == value for key, value in labels.items())
                    ]
                    metadata["cleanup_sandbox_ids"] = sandbox_ids
                    (artifacts / "resources.json").write_text(json.dumps(metadata, indent=2))
                    for sandbox_id in sandbox_ids:
                        print(f"Stage: delete smoke sandbox {sandbox_id}", flush=True)
                        group.begin_delete_sandbox(sandbox_id, polling_timeout=120, polling_interval=2).result()
                    metadata["deleted_sandbox_ids"] = sandbox_ids
                    (artifacts / "resources.json").write_text(json.dumps(metadata, indent=2))
                finally:
                    if sandbox:
                        sandbox.close()
    print("PASS: real agent created correct CSV and a working Bash script; sandbox deletion confirmed.", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, epilog="Additional options are passed to create_sandbox.py (for example --disk-id).")
    parser.add_argument("--run", action="store_true", help="Confirm creation of real Azure resources and model usage.")
    options, launcher_args = parser.parse_known_args()
    if not options.run:
        parser.error("Pass --run to create a sandbox and incur Azure/model usage.")
    workdir = "/workspace/smoke-" + uuid.uuid4().hex
    prompt = (
        f"Create directory {workdir}. Write a Bash script at {workdir}/squares.sh that writes "
        f"{workdir}/squares.csv with header number,square and exactly 10 rows for integers 1 through 10 "
        "and their squares. The script must not print anything to stdout. Run the script, inspect the CSV, "
        "and report the result. Use the shell tool to create actual files."
    )
    args = parse_args([*launcher_args, "--prompt", prompt])
    artifacts = Path(tempfile.mkdtemp(prefix="standalone-smoke-"))
    print(f"Artifacts: {artifacts}", flush=True)
    try:
        smoke(args, artifacts, workdir)
    except (Exception, KeyboardInterrupt) as error:
        print(f"FAIL: {type(error).__name__}: {error}", flush=True)
        print("Check resources.json for this run's IDs if cleanup failed. Prepared disk images are retained.", flush=True)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
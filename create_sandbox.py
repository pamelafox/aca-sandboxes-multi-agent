"""Create one ACA sandbox without running the orchestrator."""

import argparse
import json
import os
import re
import shlex
import sys
import time
from contextlib import ExitStack
from datetime import datetime, timezone
from urllib.parse import urlparse

from azure.containerapps.sandbox import (
    DiskImage,
    EgressHeader,
    EgressHeaderValueRef,
    EgressManagedIdentityRef,
    EgressPolicy,
    EgressRule,
    EgressRuleAction,
    EgressRuleMatch,
    SandboxGroupClient,
    SandboxVolume,
    endpoint_for_region,
)
from azure.core.exceptions import ResourceNotFoundError
from azure.identity import DefaultAzureCredential
from dotenv_azd import load_azd_env


class RegistryIdentitySandboxGroupClient(SandboxGroupClient):
    """Create disk images through the v2 endpoint, which accepts a managed identity for the registry pull.

    The SDK's create_disk_image targets the legacy endpoint, which rejects managed-identity pulls.
    """

    def create_disk_image(self, base_image: str, *, managed_identity_client_id: str | None = None, **kwargs) -> DiskImage:
        if not managed_identity_client_id or kwargs.get("registry_credentials"):
            return super().create_disk_image(base_image, **kwargs)
        body = {
            "source": {
                "kind": "registry",
                "imageUrl": base_image,
                "managedIdentityClientId": managed_identity_client_id,
            },
        }
        if kwargs.get("name"):
            body["labels"] = {"name": kwargs["name"]}
        return DiskImage._from_dict(self._dp_put(f"{self._group_path}/diskimages/v2", body))


def prepare_disk_image(
    group: SandboxGroupClient, image_ref: str, identity_resource_id: str | None = None,
    identity_client_id: str | None = None,
) -> str:
    if re.search(r"@sha256:[0-9a-fA-F]{64}$", image_ref):
        for image in group.list_disk_images():
            if (
                image.image and image.image.base == image_ref
                and image.status and image.status.state == "Ready"
            ):
                print(f"Reusing disk image: {image.id}", file=sys.stderr, flush=True)
                return image.id

    print(f"Preparing disk image from {image_ref}...", file=sys.stderr, flush=True)
    auth = {"managed_identity_resource_id": identity_resource_id}
    if identity_client_id:
        auth["managed_identity_client_id"] = identity_client_id
    image = group.begin_create_disk_image(
        base_image=image_ref,
        name="standalone-sandbox-agent",
        **auth,
        polling_timeout=240,
        polling_interval=2,
    ).result()
    if not image.id or not image.status or image.status.state != "Ready":
        raise RuntimeError("Disk-image preparation did not return a Ready image with an ID.")
    print(f"Disk image ready: {image.id}", file=sys.stderr, flush=True)
    return image.id


def agent_egress_policy(endpoint: str, identity_resource_id: str) -> EgressPolicy:
    """Deny by default; allow the model (signed by the proxy) and read-only GitHub.

    The model rule is a Transform: the proxy sets ``Authorization`` to an Entra token
    for the sandbox group's managed identity, so the sandbox never holds a model credential.
    Method matches need full traffic inspection.
    """
    group_identity_token = EgressHeaderValueRef(managed_identity_ref=EgressManagedIdentityRef(
        identity_type="UserAssigned",
        identity_resource_id=identity_resource_id,
        resource="https://cognitiveservices.azure.com",
        format="Bearer {value}",
    ))
    return EgressPolicy(
        default_action="Deny",
        traffic_inspection="Full",
        rules=[
            EgressRule(
                name="model-with-group-identity",
                match=EgressRuleMatch(host=urlparse(endpoint).hostname),
                action=EgressRuleAction(type="Transform", headers=[
                    EgressHeader(operation="Set", name="Authorization", value_ref=group_identity_token),
                ]),
            ),
            EgressRule(
                name="github-read-only",
                match=EgressRuleMatch(host="api.github.com", methods=["GET"]),
                action=EgressRuleAction(type="Allow"),
            ),
        ],
    )


def print_egress_decisions(sandbox, since: datetime, timeout: int = 90) -> None:
    """Print the proxy's audit log for this sandbox: every outbound request it allowed or denied.

    The log is refreshed periodically, so wait for an update newer than the run.
    """
    print("Waiting for the egress audit log to refresh...", file=sys.stderr, flush=True)
    deadline = time.monotonic() + timeout
    while True:
        decisions = sandbox.get_egress_decisions()
        updated = decisions.last_updated if decisions else None
        if updated and datetime.fromisoformat(updated) > since or time.monotonic() > deadline:
            break
        time.sleep(5)
    network = decisions.network_egress if decisions else None
    print("Egress decisions:", file=sys.stderr, flush=True)
    for kind in ("allowed", "denied"):
        for entry in getattr(network, kind, None) or []:
            print(
                f"  {kind.upper():8} {entry.method or '':6} {entry.scheme or 'https'}://{entry.host}{entry.path or ''}",
                file=sys.stderr, flush=True,
            )


OUTPUT_MOUNT = "/workspace/out"


def ensure_volume(group: SandboxGroupClient, name: str) -> SandboxVolume:
    """Create the group's Azure Blob volume on first use; its files outlive every sandbox that mounts it."""
    try:
        group.get_volume(name)
    except ResourceNotFoundError:
        print(f"Creating volume {name}...", file=sys.stderr, flush=True)
        group.create_volume(name, labels={"demo": "standalone"})
    return SandboxVolume(volume_name=name, mountpoint=OUTPUT_MOUNT)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    load_azd_env(override=False, quiet=True)
    for variable, aliases in (
        ("SUBSCRIPTION_ID", ("AZURE_SUBSCRIPTION_ID", "subscriptionId")),
        ("RESOURCE_GROUP", ("AZURE_RESOURCE_GROUP", "resourceGroupName")),
        ("SANDBOX_GROUP", ("sandboxGroupName",)),
        ("DEFAULT_REGION", ("AZURE_LOCATION",)),
        ("AZURE_OPENAI_ENDPOINT", ("openAiEndpoint",)),
        ("AZURE_OPENAI_DEPLOYMENT", ("openAiDeployment",)),
    ):
        for alias in aliases:
            if os.environ.get(alias):
                os.environ.setdefault(variable, os.environ[alias])
                break
    parser = argparse.ArgumentParser(description=__doc__)
    for option, variable in (
        ("subscription-id", "SUBSCRIPTION_ID"),
        ("resource-group", "RESOURCE_GROUP"),
        ("sandbox-group", "SANDBOX_GROUP"),
    ):
        default = os.environ.get(variable)
        parser.add_argument(
            f"--{option}", default=default, required=not default,
            help=f"Defaults to {variable}.",
        )
    parser.add_argument("--region", default=os.environ.get("DEFAULT_REGION", "westus2"))
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--disk", help="Built-in image (default: ubuntu when no image is configured).")
    source.add_argument("--disk-id", help="Existing sandbox disk-image ID, not an OCI image reference.")
    source.add_argument("--image", help="Published OCI image; defaults to SANDBOX_AGENT_IMAGE when no source is specified.")
    source.add_argument(
        "--snapshot-id",
        help="Start from a snapshot (files, memory, and environment of the source sandbox) instead of an image.",
    )
    parser.add_argument(
        "--image-identity-client-id",
        default=os.environ.get("SANDBOX_GROUP_UAMI_CLIENT_ID"),
        help="Sandbox group identity client ID for registry pulls; defaults to SANDBOX_GROUP_UAMI_CLIENT_ID.",
    )
    parser.add_argument(
        "--image-identity-resource-id",
        default=os.environ.get("SANDBOX_GROUP_UAMI_RESOURCE_ID"),
        help=(
            "Sandbox group managed identity: pulls the image (AcrPull) and signs model calls "
            "(Cognitive Services OpenAI User); defaults to SANDBOX_GROUP_UAMI_RESOURCE_ID."
        ),
    )
    task = parser.add_mutually_exclusive_group()
    task.add_argument("--command", help="Optional shell command to execute in the new sandbox.")
    task.add_argument("--prompt", help="Run an autonomous harness inside a prepared sandbox-agent disk image.")
    parser.add_argument(
        "--delete-after-run", action="store_true",
        help="Delete the sandbox before exiting, including if command execution fails.",
    )
    parser.add_argument(
        "--volume",
        help=f"Mount this sandbox group volume at {OUTPUT_MOUNT} (created if missing); files there outlive the sandbox.",
    )
    parser.add_argument(
        "--name", help="Add a name label, which shows in the portal's sandbox list.",
    )
    parser.add_argument(
        "--suspend-mode", choices=["Memory", "Disk"], default="Memory",
        help="What survives stop and resume: Memory (default) keeps running processes, Disk keeps only files.",
    )
    parser.add_argument(
        "--show-egress", action="store_true",
        help="After the run, print the egress proxy's allowed and denied requests for this sandbox.",
    )
    parser.add_argument(
        "--snapshot-after-run", metavar="NAME",
        help="Snapshot the sandbox after the command or prompt finishes, and print the snapshot ID.",
    )
    args = parser.parse_args(argv)
    if args.snapshot_id and args.volume:
        parser.error("--volume can't be combined with --snapshot-id; a restored sandbox keeps the source's configuration")
    if not (args.disk or args.disk_id or args.image or args.snapshot_id):
        args.image = os.environ.get("SANDBOX_AGENT_IMAGE")
        if not args.image:
            args.disk = "ubuntu"
    if args.prompt:
        if not (args.disk_id or args.image or args.snapshot_id):
            parser.error("--prompt requires --image, --disk-id, or --snapshot-id built from sandbox-agent/Dockerfile")
        for variable in ("AZURE_OPENAI_ENDPOINT", "AZURE_OPENAI_DEPLOYMENT"):
            if not os.environ.get(variable):
                parser.error(f"--prompt requires {variable} to be set")
        endpoint = urlparse(os.environ["AZURE_OPENAI_ENDPOINT"])
        if endpoint.scheme != "https" or not endpoint.hostname:
            parser.error("AZURE_OPENAI_ENDPOINT must be an HTTPS endpoint")
        if not args.image_identity_resource_id:
            parser.error("--prompt requires the sandbox group identity (SANDBOX_GROUP_UAMI_RESOURCE_ID)")
    return args


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    with ExitStack() as stack:
        credential = DefaultAzureCredential()
        stack.callback(credential.close)
        environment = {}
        egress_policy = EgressPolicy(default_action="Deny")
        endpoint = os.environ.get("AZURE_OPENAI_ENDPOINT")
        # Commands get the same policy as the agent when it's configured, so you can
        # try the rules with curl: the model host answers with no key, GitHub allows GET.
        if endpoint and args.image_identity_resource_id:
            egress_policy = agent_egress_policy(endpoint, args.image_identity_resource_id)
        if args.prompt:
            environment = {
                "AGENT_PROMPT": args.prompt,
                "AZURE_OPENAI_ENDPOINT": endpoint,
                "AZURE_OPENAI_DEPLOYMENT": os.environ["AZURE_OPENAI_DEPLOYMENT"],
            }
        group = RegistryIdentitySandboxGroupClient(
            endpoint_for_region(args.region),
            credential,
            subscription_id=args.subscription_id,
            resource_group=args.resource_group,
            sandbox_group=args.sandbox_group,
        )
        stack.callback(group.close)
        disk_id = args.disk_id
        if args.image:
            disk_id = prepare_disk_image(
                group, args.image, args.image_identity_resource_id, args.image_identity_client_id,
            )
        if args.snapshot_id:
            # A restore replays the captured sandbox as-is and accepts no configuration,
            # and the egress policy isn't part of the snapshot: reapply it right away.
            sandbox = group.begin_create_sandbox(snapshot_id=args.snapshot_id).result()
            sandbox.set_egress_policy(egress_policy)
        else:
            volumes = [ensure_volume(group, args.volume)] if args.volume else None
            sandbox = group.begin_create_sandbox(
                disk=None if disk_id else args.disk,
                disk_id=disk_id,
                cpu="500m",
                memory="1Gi",
                auto_suspend_seconds=300,
                auto_suspend_mode=args.suspend_mode,
                labels={"demo": "standalone", **({"name": args.name} if args.name else {})},
                egress_policy=egress_policy,
                volumes=volumes,
                **({"environment": environment} if args.prompt else {}),
            ).result()
        stack.callback(sandbox.close)
        if args.delete_after_run:
            stack.callback(sandbox.delete)
        print(json.dumps({
            "sandbox_id": sandbox.sandbox_id,
            "disk_image_id": disk_id,
            "snapshot_id": args.snapshot_id,
            "volume": args.volume,
            "subscription_id": args.subscription_id,
            "resource_group": args.resource_group,
            "sandbox_group": args.sandbox_group,
            "region": args.region,
        }, indent=2), flush=True)
        if args.command:
            print(sandbox.exec(args.command))
        if args.prompt:
            # Passed on the command line too, because a restored sandbox keeps the source's environment.
            result = sandbox.exec(
                f"AGENT_PROMPT={shlex.quote(args.prompt)} /usr/local/bin/python /app/sandbox_agent.py"
            )
            print(result.stdout, end="", flush=True)
            print(result.stderr, end="", file=sys.stderr, flush=True)
            if result.exit_code:
                raise SystemExit(result.exit_code)
        if args.show_egress:
            print_egress_decisions(sandbox, since=datetime.now(timezone.utc))
        if args.snapshot_after_run:
            snapshot = sandbox.begin_create_snapshot(name=args.snapshot_after_run).result()
            print(json.dumps({"snapshot_id": snapshot.id, "name": args.snapshot_after_run}), flush=True)


if __name__ == "__main__":
    main()
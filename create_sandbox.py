"""Create one ACA sandbox without running the orchestrator."""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from contextlib import ExitStack
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
    RegistryCredentials,
    SandboxGroupClient,
    endpoint_for_region,
)
from azure.identity import DefaultAzureCredential
from dotenv_azd import load_azd_env


class RegistryIdentitySandboxGroupClient(SandboxGroupClient):
    """Bridge the SDK's missing disk-image managed-identity client-ID field."""

    def create_disk_image(self, base_image: str, *, managed_identity_client_id: str | None = None, **kwargs) -> DiskImage:
        if not managed_identity_client_id or kwargs.get("registry_credentials"):
            return super().create_disk_image(base_image, **kwargs)
        body = {
            "image": {"base": base_image},
            "managedIdentityClientId": managed_identity_client_id,
        }
        if kwargs.get("name"):
            body["labels"] = {"name": kwargs["name"]}
        return DiskImage._from_dict(self._dp_put(f"{self._group_path}/diskimages", body))


def get_acr_credentials(image_ref: str, subscription_id: str) -> RegistryCredentials:
    registry_host, separator, repository = image_ref.partition("/")
    if not separator or not repository or not re.fullmatch(r"[a-zA-Z0-9-]+\.azurecr\.io", registry_host):
        raise ValueError("--registry-auth azure-cli requires an image hosted at <registry>.azurecr.io")
    executable = shutil.which("az.cmd") or shutil.which("az.exe") or shutil.which("az")
    if not executable:
        raise RuntimeError("Azure CLI is required for --registry-auth azure-cli. Install it and run az login.")
    try:
        result = subprocess.run(
            [executable, "acr", "login", "--name", registry_host.split(".")[0],
             "--subscription", subscription_id, "--expose-token", "--output", "json"],
            capture_output=True, text=True, timeout=60, check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        raise RuntimeError("Unable to obtain an ACR token from Azure CLI. Check az login and registry permissions.") from None
    if result.returncode:
        raise RuntimeError("ACR token acquisition failed. Check az login, the subscription, and registry pull permissions.")
    try:
        payload = json.loads(result.stdout)
        token = payload["accessToken"]
        login_server = payload["loginServer"]
        if not isinstance(token, str) or not token or login_server.lower() != registry_host.lower():
            raise ValueError()
    except (ValueError, KeyError, TypeError, AttributeError):
        raise RuntimeError("Azure CLI did not return a valid token for the requested registry.") from None
    return RegistryCredentials(username="00000000-0000-0000-0000-000000000000", token=token)


def prepare_disk_image(
    group: SandboxGroupClient, image_ref: str, identity_resource_id: str | None = None,
    identity_client_id: str | None = None,
    *, registry_auth: str = "managed-identity", subscription_id: str = "",
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
    if registry_auth == "azure-cli":
        auth = {"registry_credentials": get_acr_credentials(image_ref, subscription_id)}
    elif identity_client_id:
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


def model_egress_policy(endpoint: str, identity_resource_id: str) -> EgressPolicy:
    """Allow only the model endpoint, and have the proxy sign each request.

    The Transform rule sets ``Authorization`` to an Entra token for the sandbox
    group's managed identity, so the sandbox never holds a model credential.
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
        rules=[EgressRule(
            name="model-with-group-identity",
            match=EgressRuleMatch(host=urlparse(endpoint).hostname),
            action=EgressRuleAction(type="Transform", headers=[
                EgressHeader(operation="Set", name="Authorization", value_ref=group_identity_token),
            ]),
        )],
    )


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
    parser.add_argument(
        "--registry-auth", choices=("managed-identity", "azure-cli"),
        default="managed-identity",
        help="Registry pull authentication; azure-cli obtains an ACR token without storing it in azd.",
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
    args = parser.parse_args(argv)
    if not (args.disk or args.disk_id or args.image):
        args.image = os.environ.get("SANDBOX_AGENT_IMAGE")
        if not args.image:
            args.disk = "ubuntu"
    if args.prompt:
        if not (args.disk_id or args.image):
            parser.error("--prompt requires --image or --disk-id built from sandbox-agent/Dockerfile")
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
        if args.prompt:
            endpoint = os.environ["AZURE_OPENAI_ENDPOINT"]
            environment = {
                "AGENT_PROMPT": args.prompt,
                "AZURE_OPENAI_ENDPOINT": endpoint,
                "AZURE_OPENAI_DEPLOYMENT": os.environ["AZURE_OPENAI_DEPLOYMENT"],
            }
            egress_policy = model_egress_policy(endpoint, args.image_identity_resource_id)
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
                registry_auth=args.registry_auth, subscription_id=args.subscription_id,
            )
        sandbox = group.begin_create_sandbox(
            disk=None if disk_id else args.disk,
            disk_id=disk_id,
            cpu="500m",
            memory="1Gi",
            auto_suspend_seconds=300,
            labels={"demo": "standalone"},
            egress_policy=egress_policy,
            **({"environment": environment} if args.prompt else {}),
        ).result()
        stack.callback(sandbox.close)
        if args.delete_after_run:
            stack.callback(sandbox.delete)
        print(json.dumps({
            "sandbox_id": sandbox.sandbox_id,
            "disk_image_id": disk_id,
            "subscription_id": args.subscription_id,
            "resource_group": args.resource_group,
            "sandbox_group": args.sandbox_group,
            "region": args.region,
        }, indent=2), flush=True)
        if args.command:
            print(sandbox.exec(args.command))
        if args.prompt:
            result = sandbox.exec("/usr/local/bin/python /app/sandbox_agent.py")
            print(result.stdout, end="", flush=True)
            print(result.stderr, end="", file=sys.stderr, flush=True)
            if result.exit_code:
                raise SystemExit(result.exit_code)


if __name__ == "__main__":
    main()
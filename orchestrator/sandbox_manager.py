"""
Sandbox Manager — Async wrapper around the public ACA Sandboxes SDK
(`azure-containerapps-sandbox`) for managing the research-agent sandbox
group and per-question sandboxes.

Mirrors agents/orchestrator.net/Services/SandboxManager.cs.

The SDK is synchronous (azure-core sync pipeline). All calls are wrapped
with ``asyncio.to_thread()`` so they don't block the FastAPI event loop.

SDK API surface used:
    - SandboxGroupClient(endpoint_for_region(region), credential, ...)
        .list_disk_images() / .create_disk_image() / .get_disk_image() / .delete_disk_image()
        .begin_create_sandbox(...).result()  →  returns SandboxClient
    - SandboxClient (sandbox-scoped instance returned by the LRO poller)
        .get() / .delete() / .exec()
    - Models: DiskImage, Sandbox, EgressPolicy, AddPortRequest, PortAuthConfig,
      endpoint_for_region.

Tested against ``azure-containerapps-sandbox 0.1.0b1``
(release ``python-sdk-v0.1.0b1-early-access``).
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

import httpx
from azure.core.credentials import TokenCredential
from azure.core.credentials_async import AsyncTokenCredential

from azure.containerapps.sandbox import (
    AddPortRequest,
    DiskImage,
    EgressHeader,
    EgressHeaderValueRef,
    EgressHostRule,
    EgressManagedIdentityRef,
    EgressPolicy,
    EgressRule,
    EgressRuleAction,
    EgressRuleMatch,
    PortAuthConfig,
    Sandbox,
    SandboxClient,
    SandboxGroupClient,
    endpoint_for_region,
)
from azure_credentials import build_async_credential, build_sync_credential

logger = logging.getLogger(__name__)

# OpenTelemetry is optional: present in the container image (pulled by
# azure-monitor-opentelemetry) but harmless if missing locally. All span usage
# goes through `_span`, which no-ops when tracing is unavailable.
try:  # pragma: no cover - import guard
    from opentelemetry import propagate as _otel_propagate
    from opentelemetry import trace as _otel_trace

    _tracer = _otel_trace.get_tracer("orchestrator.sandbox")
except Exception:  # pragma: no cover
    _otel_propagate = None
    _tracer = None


@contextmanager
def _span(name: str, **attributes: Any):
    """Start an OTEL span, or no-op if tracing isn't configured."""
    if _tracer is None:
        yield None
        return
    with _tracer.start_as_current_span(name) as sp:
        for key, value in attributes.items():
            if value is not None:
                sp.set_attribute(key, value)
        yield sp


def _traceparent_env() -> dict[str, str]:
    """W3C trace-context carrier for the current span, to forward into a
    sandbox so its in-VM spans join the same end-to-end trace."""
    if _otel_propagate is None:
        return {}
    carrier: dict[str, str] = {}
    _otel_propagate.inject(carrier)
    env: dict[str, str] = {}
    if carrier.get("traceparent"):
        env["TRACEPARENT"] = carrier["traceparent"]
    if carrier.get("tracestate"):
        env["TRACESTATE"] = carrier["tracestate"]
    return env


# ── Region map (parity with the .NET version) ──────────────────────────────

REGIONS: dict[str, str] = {
    "westus":         "West US",
    "westus2":        "West US 2",
    "westus3":        "West US 3",
    "westcentralus":  "West Central US",
    "canadacentral":  "Canada Central",
    "swedencentral":  "Sweden Central",
    "northeurope":    "North Europe",
}
DEFAULT_REGION = "westus2"


def validate_region(region: str | None) -> str:
    return region if region in REGIONS else DEFAULT_REGION


def region_to_sandbox_group_name(region: str) -> str:
    return f"sg-demo-swarm-{region}"


# ── Label conventions for managed disk images ──────────────────────────────
LABEL_DEMO         = "demo"
LABEL_DEMO_VALUE   = "agents"
LABEL_IMAGE_REF    = "image-ref"
LABEL_OCI_DIGEST   = "oci-digest"


# ── Models ──────────────────────────────────────────────────────────────────

@dataclass
class SandboxStatus:
    status: str
    progress: str
    error: str | None = None
    has_openai: bool = False


@dataclass
class AgentResult:
    question: str
    answer: str
    sources: list[str] = field(default_factory=list)
    confidence: float = 0.0


# ── SandboxManager ──────────────────────────────────────────────────────────

class SandboxManager:
    """Manages the lifecycle of the sandbox group, disk images, and sandboxes."""

    def __init__(self) -> None:
        # Required
        self.subscription_id = _required("SUBSCRIPTION_ID")
        self.resource_group  = _required("RESOURCE_GROUP")

        # Defaults (env overrideable)
        self.current_region = os.environ.get("DEFAULT_REGION", DEFAULT_REGION)
        self.current_sandbox_group_name = (
            os.environ.get("SANDBOX_GROUP")
            or region_to_sandbox_group_name(self.current_region)
        )
        self.container_image = os.environ.get("DISK_IMAGE_ID", "")

        # clientId of the sandbox group's user-assigned identity, which holds
        # AcrPull. The v2 disk-image API authenticates the ACR pull with it (keyless).
        self.sandbox_group_uami_client_id = os.environ.get("SANDBOX_GROUP_UAMI_CLIENT_ID")
        # Resource ID of the same identity. The egress proxy mints model/Foundry
        # tokens for it and injects them into researcher requests.
        self.sandbox_group_uami_resource_id = os.environ.get("SANDBOX_GROUP_UAMI_RESOURCE_ID")

        # Azure OpenAI passthrough for the research agent.
        self.openai_endpoint   = os.environ.get("AZURE_OPENAI_ENDPOINT")
        self.openai_deployment = os.environ.get("AZURE_OPENAI_DEPLOYMENT", "gpt-5.6-luna")

        # Foundry project endpoint (for the researcher's hosted web search tool).
        self.foundry_project_endpoint = os.environ.get("FOUNDRY_PROJECT_ENDPOINT")

        # Application Insights connection string. When set, it is forwarded into
        # each sandbox (so the in-VM research agent reports to the same trace)
        # and its ingestion endpoints are added to the sandbox egress allow-list.
        self.appinsights_conn = os.environ.get("APPLICATIONINSIGHTS_CONNECTION_STRING")

        # Concurrency throttle (max 10 concurrent sandbox creates)
        self._throttle = asyncio.Semaphore(10)

        # Caches
        self._provisioned_groups: set[str] = set()
        self._current_disk_image_id: str | None = None
        self._current_disk_image_digest: str | None = None
        self._current_disk_image_created_at: str | None = None
        self._sandbox_endpoints: dict[str, str] = {}  # logical id -> external URL
        self._sbx_clients: dict[str, SandboxClient] = {}  # logical id -> SDK client
        self._sandbox_started_at: dict[str, float] = {}
        self._total_sandbox_seconds: float = 0.0
        self._total_sandbox_runs: int = 0
        self._prepare_lock = asyncio.Lock()

        # Long-lived credentials + group client (lazy; closed on shutdown).
        # The SDK's SandboxGroupClient is bound to a single (region, group),
        # so we rebuild it when the active region/group changes.
        self._sync_credential: TokenCredential | None = None
        self._async_credential: AsyncTokenCredential | None = None
        self._group_client: SandboxGroupClient | None = None
        self._group_client_key: tuple[str, str] | None = None  # (region, group)

        # HTTP client for polling research-agent /status & /result endpoints
        self._http = httpx.AsyncClient(timeout=httpx.Timeout(120.0))

    async def aclose(self) -> None:
        await self._http.aclose()
        # Close any cached sandbox-scoped clients
        for sbx in list(self._sbx_clients.values()):
            try:
                await asyncio.to_thread(sbx.close)
            except Exception:
                pass
        self._sbx_clients.clear()
        if self._group_client is not None:
            await asyncio.to_thread(self._group_client.close)
            self._group_client = None
        if self._async_credential is not None:
            await self._async_credential.close()
        # Sync credential has no close method we need to call.

    # ── Lazy client init ───────────────────────────────────────────────────

    def _get_group_client(self) -> SandboxGroupClient:
        """Return (and lazily build/rebuild) a SandboxGroupClient bound to
        the current region + sandbox group."""
        key = (self.current_region, self.current_sandbox_group_name)
        if self._group_client is not None and self._group_client_key == key:
            return self._group_client

        # Region/group changed — close the previous client.
        if self._group_client is not None:
            try:
                self._group_client.close()
            except Exception:
                pass

        if self._sync_credential is None:
            self._sync_credential = build_sync_credential()

        self._group_client = SandboxGroupClient(
            endpoint_for_region(self.current_region),
            self._sync_credential,
            subscription_id=self.subscription_id,
            resource_group=self.resource_group,
            sandbox_group=self.current_sandbox_group_name,
        )
        self._group_client_key = key
        return self._group_client

    # ── Sandbox group ──────────────────────────────────────────────────────

    async def ensure_sandbox_group(self, region: str) -> None:
        """
        Verify the sandbox group exists in the requested region. The group itself
        is provisioned by the Bicep template (with managed identity + AcrPull),
        so this just validates and caches the result.
        """
        region = validate_region(region)
        group_name = (
            os.environ.get("SANDBOX_GROUP")
            or region_to_sandbox_group_name(region)
        )

        # Update the active (region, group) so _get_group_client picks them up.
        self.current_sandbox_group_name = group_name
        self.current_region = region

        if group_name in self._provisioned_groups:
            return

        client = self._get_group_client()
        try:
            # Iterating ItemPaged forces the first page request, which validates
            # both connectivity and RBAC on the data plane.
            await asyncio.to_thread(lambda: list(client.list_disk_images()))
        except Exception as ex:
            raise RuntimeError(
                f"Cannot reach sandbox group '{group_name}' in {region}. "
                "Ensure it was provisioned via infra/main.bicep and that this "
                "principal has 'Container Apps SandboxGroup Data Owner' on it. "
                f"Underlying error: {ex}"
            ) from ex

        self._provisioned_groups.add(group_name)
        logger.info("[EnsureSG] Active group: '%s' in %s", group_name, region)

    # ── ACR digest resolution ───────────────────────────────────────────────

    @staticmethod
    def _parse_image_ref(image_ref: str) -> tuple[str, str, str]:
        """Parse `registry/repo:tag` into (registry, repo, tag)."""
        if "/" not in image_ref:
            raise ValueError(f"Image ref missing registry: {image_ref}")
        registry, rest = image_ref.split("/", 1)
        if "@" in rest:
            repo, tag = rest.split("@", 1)
        elif ":" in rest:
            repo, tag = rest.rsplit(":", 1)
        else:
            repo, tag = rest, "latest"
        return registry, repo, tag

    async def _acr_bearer_via_aad(self, registry: str, repo: str) -> str | None:
        """Exchange an AAD access token for an ACR bearer scoped to repo:pull.

        Returns None on failure.
        """
        try:
            if self._async_credential is None:
                self._async_credential = build_async_credential()
            aad = await self._async_credential.get_token(
                "https://management.azure.com/.default"
            )
            # Step 1: exchange AAD token for ACR refresh token
            r = await self._http.post(
                f"https://{registry}/oauth2/exchange",
                data={
                    "grant_type": "access_token",
                    "service": registry,
                    "access_token": aad.token,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            r.raise_for_status()
            refresh = r.json()["refresh_token"]
            # Step 2: exchange refresh token for access token scoped to repo:pull
            r = await self._http.post(
                f"https://{registry}/oauth2/token",
                data={
                    "grant_type": "refresh_token",
                    "service": registry,
                    "scope": f"repository:{repo}:pull",
                    "refresh_token": refresh,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            r.raise_for_status()
            return r.json()["access_token"]
        except Exception as ex:
            logger.warning("[Digest] AAD->ACR token exchange failed: %s", ex)
            return None

    async def resolve_oci_digest(self, image_ref: str | None = None) -> str:
        """
        Resolve `registry/repo:tag` to the current `sha256:<hex>` manifest digest,
        authenticating with the orchestrator's Entra credential.
        """
        ref = image_ref or self.container_image
        registry, repo, tag = self._parse_image_ref(ref)

        if "@sha256:" in ref:
            return ref.split("@", 1)[1]

        # The orchestrator's managed identity has AcrPull on the registry (bicep).
        token = await self._acr_bearer_via_aad(registry, repo)

        accept = ", ".join([
            "application/vnd.oci.image.manifest.v1+json",
            "application/vnd.docker.distribution.manifest.v2+json",
            "application/vnd.oci.image.index.v1+json",
            "application/vnd.docker.distribution.manifest.list.v2+json",
        ])
        headers = {"Accept": accept}
        if token:
            headers["Authorization"] = f"Bearer {token}"

        manifest_url = f"https://{registry}/v2/{repo}/manifests/{tag}"
        r = await self._http.head(manifest_url, headers=headers)
        r.raise_for_status()
        digest = r.headers.get("Docker-Content-Digest")
        if not digest:
            raise RuntimeError(
                f"Registry did not return Docker-Content-Digest for {ref}"
            )
        return digest

    # ── Disk image (digest-cached, persistent across runs) ────────────────────

    def _create_disk_image_with_labels(self, labels: dict[str, str]) -> DiskImage:
        """Create a disk image carrying our full label dict.

        The SDK's ``create_disk_image()`` targets the legacy endpoint, which
        rejects managed-identity pulls, and only encodes ``labels.name``. Use the
        v2 endpoint's ``source.managedIdentityClientId`` for the sandbox group's
        AcrPull identity, keeping our image-ref, oci-digest, and demo labels.
        """
        client = self._get_group_client()
        body: dict[str, Any] = {
            "labels": labels,
            "source": {
                "kind": "registry",
                "imageUrl": self.container_image,
                "managedIdentityClientId": self.sandbox_group_uami_client_id,
            },
        }
        # SDK private API — needed because the public method targets the legacy endpoint.
        raw = client._dp_put(f"{client._group_path}/diskimages/v2", body)  # type: ignore[attr-defined]
        return DiskImage._from_dict(raw)

    async def _wait_until_ready(
        self,
        image: DiskImage,
        status_cb,
    ) -> DiskImage:
        client = self._get_group_client()
        for i in range(120):  # up to ~4 minutes
            image = await asyncio.to_thread(client.get_disk_image, image.id)
            state = getattr(image.status, "state", None) if image.status else None
            if state == "Ready":
                return image
            if state == "Failed":
                err = (
                    getattr(image.status, "message", None) or "unknown"
                    if image.status else "unknown"
                )
                if status_cb:
                    await status_cb(f"Disk image build failed: {err}", "error")
                raise RuntimeError(f"Disk image build failed: {err}")
            if i and i % 5 == 0 and status_cb:
                await status_cb(f"Disk image building... ({state or 'pending'})")
            await asyncio.sleep(2)
        if status_cb:
            await status_cb("Disk image build timed out", "error")
        raise TimeoutError("Disk image build timed out")

    async def prepare_disk_image(
        self,
        status_cb=None,
        force: bool = False,
    ) -> str:
        """
        Ensure a Ready disk image exists for the current `DISK_IMAGE_ID` and
        matches the current ACR manifest digest. Persistent across runs.
        """
        if not self.container_image:
            raise RuntimeError("DISK_IMAGE_ID env var is required (full image reference).")

        async def _say(msg: str, level: str = "info") -> None:
            if status_cb:
                await status_cb(msg, level)

        async with self._prepare_lock:
            client = self._get_group_client()

            # 1) Resolve current digest (best-effort — fall back to "always rebuild")
            current_digest: str | None = None
            await _say(f"Resolving current digest for {self.container_image}...")
            try:
                current_digest = await self.resolve_oci_digest(self.container_image)
                await _say(f"Current ACR digest: {current_digest[:19]}...")
            except Exception as ex:
                logger.warning("[Digest] resolve failed; will skip cache match: %s", ex)
                await _say(
                    "Could not resolve ACR digest — will rebuild disk image.",
                    "info",
                )

            # 2) Look for an existing matching disk image
            existing_all = await asyncio.to_thread(
                lambda: list(client.list_disk_images())
            )
            # Filter client-side to our image-ref label.
            existing = [
                img for img in existing_all
                if (img.labels or {}).get(LABEL_IMAGE_REF) == self.container_image
            ]
            ready_match: DiskImage | None = None
            stale: list[DiskImage] = []
            for img in existing:
                img_labels = img.labels or {}
                state = getattr(img.status, "state", None) if img.status else None
                if (
                    not force
                    and current_digest is not None
                    and state == "Ready"
                    and img_labels.get(LABEL_OCI_DIGEST) == current_digest
                    and ready_match is None
                ):
                    ready_match = img
                else:
                    stale.append(img)

            if ready_match is not None:
                self._current_disk_image_id = ready_match.id
                self._current_disk_image_digest = current_digest
                self._current_disk_image_created_at = None
                await _say(
                    f"Reusing disk image {ready_match.id} — digest matches ACR",
                    "success",
                )
                if stale:
                    asyncio.create_task(self._delete_images_quietly(stale))
                return ready_match.id

            # 3) Build a new one
            if force:
                await _say("Force-rebuilding disk image (Re-create requested)", "info")
            elif existing:
                await _say(
                    f"ACR has changed (or {len(existing)} stale image(s) present). Rebuilding...",
                    "info",
                )
            else:
                await _say("No existing disk image found. Creating one...", "info")

            await _say(f"Pulling container image from ACR: {self.container_image}")
            await _say("Creating disk image in sandbox group...")

            labels = {
                LABEL_DEMO:       LABEL_DEMO_VALUE,
                LABEL_IMAGE_REF:  self.container_image,
            }
            if current_digest:
                labels[LABEL_OCI_DIGEST] = current_digest
            try:
                image = await asyncio.to_thread(
                    self._create_disk_image_with_labels, labels
                )
            except Exception as ex:
                await _say(f"Disk image creation failed: {ex}", "error")
                raise

            image = await self._wait_until_ready(image, status_cb)

            self._current_disk_image_id = image.id
            self._current_disk_image_digest = current_digest
            self._current_disk_image_created_at = None
            await _say(f"Disk image ready: {image.id}", "success")
            logger.info("[DiskImage] Ready: %s", image.id)

            to_prune = [s for s in (stale or []) if s.id != image.id]
            if to_prune:
                await _say(
                    f"Pruning {len(to_prune)} stale disk image(s) for {self.container_image}",
                    "info",
                )
                asyncio.create_task(self._delete_images_quietly(to_prune))

            return image.id

    async def _delete_images_quietly(self, images: list[DiskImage]) -> None:
        client = self._get_group_client()
        for img in images:
            try:
                await asyncio.to_thread(client.delete_disk_image, img.id)
                logger.info("[DiskImage] Pruned %s", img.id)
            except Exception as ex:
                logger.warning("[DiskImage] Prune failed for %s: %s", img.id, ex)

    async def delete_current_disk_image(self, status_cb=None) -> None:
        """Delete the currently cached disk image (used by the UI button)."""
        async def _say(msg: str, level: str = "info") -> None:
            if status_cb:
                await status_cb(msg, level)

        async with self._prepare_lock:
            client = self._get_group_client()
            disk_image_id = self._current_disk_image_id
            if not disk_image_id:
                # Nothing cached; try to find one by image-ref label.
                all_images = await asyncio.to_thread(
                    lambda: list(client.list_disk_images())
                )
                existing = [
                    img for img in all_images
                    if (img.labels or {}).get(LABEL_IMAGE_REF) == self.container_image
                ]
                if not existing:
                    await _say("No disk image to delete.", "info")
                    return
                await _say(
                    f"Deleting {len(existing)} disk image(s) for {self.container_image}...",
                    "info",
                )
                await self._delete_images_quietly(existing)
                await _say("Disk image(s) deleted.", "success")
                return

            self._current_disk_image_id = None
            self._current_disk_image_digest = None
            self._current_disk_image_created_at = None
            try:
                await asyncio.to_thread(client.delete_disk_image, disk_image_id)
                await _say(f"Disk image deleted: {disk_image_id}", "success")
            except Exception as ex:
                await _say(f"Delete failed: {ex}", "error")

    async def prune_managed_disk_images(self, status_cb=None) -> int:
        """Delete every disk image carrying our `demo=agents` label."""
        async def _say(msg: str, level: str = "info") -> None:
            if status_cb:
                await status_cb(msg, level)

        client = self._get_group_client()
        all_images = await asyncio.to_thread(
            lambda: list(client.list_disk_images())
        )
        managed = [
            img for img in all_images
            if (img.labels or {}).get(LABEL_DEMO) == LABEL_DEMO_VALUE
        ]
        if not managed:
            # Fall back: prune everything if nothing is labelled yet.
            managed = all_images

        if not managed:
            await _say("No disk images to prune.", "info")
            return 0

        await _say(f"Pruning {len(managed)} disk image(s)...", "info")
        self._current_disk_image_id = None
        self._current_disk_image_digest = None
        self._current_disk_image_created_at = None
        await self._delete_images_quietly(managed)
        await _say(f"Pruned {len(managed)} disk image(s).", "success")
        return len(managed)

    def disk_image_info(self) -> dict:
        """Snapshot of the current disk image for the UI panel."""
        return {
            "image_ref":     self.container_image,
            "disk_image_id": self._current_disk_image_id,
            "oci_digest":    self._current_disk_image_digest,
            "created_at":    self._current_disk_image_created_at,
        }

    def stats(self) -> dict:
        """Aggregated runtime stats for the UI panel."""
        now = time.monotonic()
        live_seconds = sum(now - t for t in self._sandbox_started_at.values())
        return {
            "total_sandbox_seconds":  round(self._total_sandbox_seconds + live_seconds, 1),
            "total_sandbox_runs":     self._total_sandbox_runs,
            "live_sandboxes":         len(self._sandbox_started_at),
        }

    # ── Sandbox lifecycle ──────────────────────────────────────────────────

    def _build_egress_policy(self) -> EgressPolicy:
        """Default-deny egress; the model hosts are reachable only with proxy-injected auth.

        Every research sandbox starts fully network-isolated. For the Foundry
        project and AOAI hosts, a Transform rule lets the request through and has
        the egress proxy set ``Authorization`` to an Entra token for the sandbox
        group's managed identity, so no token is ever placed inside the sandbox.
        Web search runs server-side in Foundry, so no search-engine egress is needed.
        Application Insights ingestion is a plain allow (it authenticates with the
        connection string).
        """
        rules: list[EgressRule] = []

        def _sign_with_group_identity(url: str | None, audience: str, name: str) -> None:
            host = urlparse(url).hostname if url else None
            if not host or not self.sandbox_group_uami_resource_id:
                return
            token = EgressHeaderValueRef(managed_identity_ref=EgressManagedIdentityRef(
                identity_type="UserAssigned",
                identity_resource_id=self.sandbox_group_uami_resource_id,
                resource=audience,
                format="Bearer {value}",
            ))
            rules.append(EgressRule(
                name=name,
                match=EgressRuleMatch(host=host),
                action=EgressRuleAction(type="Transform", headers=[
                    EgressHeader(operation="Set", name="Authorization", value_ref=token),
                ]),
            ))

        # Foundry project host (hosted web search / grounding via FoundryChatClient).
        _sign_with_group_identity(self.foundry_project_endpoint, "https://ai.azure.com", "foundry-with-group-identity")
        # AOAI data-plane host for model inference.
        _sign_with_group_identity(self.openai_endpoint, "https://cognitiveservices.azure.com", "aoai-with-group-identity")

        host_rules: list[EgressHostRule] = []
        seen: set[str] = set()
        # Application Insights ingestion (so the in-sandbox agent can export
        # OpenTelemetry traces). Parsed from the connection string's
        # Ingestion/Live endpoints; falls back to the public ingestion domains.
        for endpoint in self._appinsights_egress_endpoints():
            host = urlparse(endpoint).hostname if endpoint else None
            if not host:
                continue
            for pattern in (host, f"*.{host.split('.', 1)[1]}" if "." in host else host):
                if pattern not in seen:
                    seen.add(pattern)
                    host_rules.append(EgressHostRule(pattern=pattern, action="Allow"))
        return EgressPolicy(
            default_action="Deny",
            traffic_inspection="Full",
            host_rules=host_rules,
            rules=rules,
        )

    def _appinsights_egress_endpoints(self) -> list[str]:
        """Endpoints the in-sandbox OTEL exporter must reach, derived from the
        Application Insights connection string (Ingestion + Live)."""
        if not self.appinsights_conn:
            return []
        parts = dict(
            kv.split("=", 1)
            for kv in self.appinsights_conn.split(";")
            if "=" in kv
        )
        endpoints: list[str] = []
        for key in ("IngestionEndpoint", "LiveEndpoint"):
            url = parts.get(key)
            if url:
                endpoints.append(url)
        # Fallbacks in case the connection string omits explicit endpoints.
        if not endpoints:
            endpoints = [
                "https://dc.services.visualstudio.com",
                "https://westus3-0.in.applicationinsights.azure.com",
            ]
        return endpoints

    def _create_sandbox_sync(
        self,
        disk_image_id: str,
        environment: dict[str, str],
        labels: dict[str, str],
    ) -> tuple[SandboxClient, Sandbox]:
        """Create a sandbox via the LRO API and return (client, info).

        Blocks until the sandbox reaches the ``Running`` state.
        """
        client = self._get_group_client()
        poller = client.begin_create_sandbox(
            disk_id=disk_image_id,
            cpu="500m",
            memory="1Gi",
            ports=[AddPortRequest(port=8080, auth=PortAuthConfig(anonymous=True))],
            environment=environment,
            labels=labels,
            egress_policy=self._build_egress_policy(),
        )
        sandbox_client: SandboxClient = poller.result()
        # Fetch the full Sandbox resource (includes the issued port URLs).
        info = sandbox_client.get()
        return sandbox_client, info

    async def create_sandbox(self, sandbox_id: str, question: str) -> None:
        """Create a sandbox running the research agent for the given question."""
        if not self._current_disk_image_id:
            raise RuntimeError(
                "prepare_disk_image() must be called before create_sandbox()."
            )

        environment: dict[str, str] = {"RESEARCH_QUESTION": question}
        if self.openai_endpoint:
            environment["AZURE_OPENAI_ENDPOINT"] = self.openai_endpoint
        if self.openai_deployment:
            environment["AZURE_OPENAI_DEPLOYMENT"] = self.openai_deployment
        # Foundry project for the hosted web-search tool. No token is passed:
        # the egress proxy signs these requests with the sandbox group's identity.
        if self.foundry_project_endpoint:
            environment["FOUNDRY_PROJECT_ENDPOINT"] = self.foundry_project_endpoint

        labels = {
            "demo": "agents",
            "question": question[:50],
        }

        with _span(
            "sandbox.create",
            **{"sandbox.id": sandbox_id, "sandbox.region": self.current_region},
        ):
            # Forward telemetry config + trace context so the in-VM research
            # agent exports to the same App Insights trace as this span.
            if self.appinsights_conn:
                environment["APPLICATIONINSIGHTS_CONNECTION_STRING"] = self.appinsights_conn
                environment["OTEL_SERVICE_NAME"] = "research-agent"
                environment["ENABLE_INSTRUMENTATION"] = "true"
                environment["ENABLE_SENSITIVE_DATA"] = os.environ.get(
                    "ENABLE_SENSITIVE_DATA", "true"
                )
                environment.update(_traceparent_env())

            async with self._throttle:
                sandbox_client, info = await asyncio.to_thread(
                    self._create_sandbox_sync,
                    self._current_disk_image_id,
                    environment,
                    labels,
                )

                external_url = ""
                ports = getattr(info, "ports", None) or []
                if ports:
                    external_url = getattr(ports[0], "url", "") or ""

                self._sandbox_endpoints[sandbox_id] = external_url
                self._sbx_clients[sandbox_id] = sandbox_client
            self._sandbox_started_at[sandbox_id] = time.monotonic()

    async def delete_sandbox(self, sandbox_id: str) -> None:
        sbx_client = self._sbx_clients.pop(sandbox_id, None)
        self._sandbox_endpoints.pop(sandbox_id, None)
        started = self._sandbox_started_at.pop(sandbox_id, None)
        if started is not None:
            self._total_sandbox_seconds += time.monotonic() - started
            self._total_sandbox_runs += 1
        if sbx_client is None:
            return
        try:
            await asyncio.to_thread(sbx_client.delete)
        except Exception as ex:
            logger.warning("[Delete] %s — %s", sbx_client.sandbox_id, ex)
        finally:
            try:
                await asyncio.to_thread(sbx_client.close)
            except Exception:
                pass

    # ── HTTP polling against the research agent inside the sandbox ─────────

    def _agent_base_url(self, sandbox_id: str) -> str:
        url = self._sandbox_endpoints.get(sandbox_id)
        if not url:
            raise RuntimeError(f"No endpoint known for sandbox {sandbox_id}")
        return url.rstrip("/")

    async def get_status(self, sandbox_id: str) -> SandboxStatus:
        url = f"{self._agent_base_url(sandbox_id)}/status"
        r = await self._http.get(url)
        r.raise_for_status()
        d: dict[str, Any] = r.json()
        return SandboxStatus(
            status=d["status"],
            progress=d.get("progress", ""),
            error=d.get("error"),
            has_openai=bool(d.get("has_openai", False)),
        )

    async def get_result(self, sandbox_id: str) -> AgentResult:
        url = f"{self._agent_base_url(sandbox_id)}/result"
        r = await self._http.get(url)
        r.raise_for_status()
        d: dict[str, Any] = r.json()
        return AgentResult(
            question=d["question"],
            answer=d["answer"],
            sources=list(d.get("sources", []) or []),
            confidence=float(d.get("confidence", 0.0)),
        )

    # ── Egress diagnostics ────────────────────────────────────────────────
    async def probe_egress(
        self,
        question: str = "What is Azure Container Apps?",
        wait_seconds: int = 120,
        status_cb=None,
    ) -> dict[str, Any]:
        """Create a throwaway sandbox, let the research agent make its outbound
        calls, then read back the *stored* egress policy and the egress-decision
        audit log (which hosts were actually Allowed vs Denied). Useful to verify
        the default-deny + Foundry/AOAI-only policy is applied and matches the
        endpoints the researcher really talks to. The sandbox is always deleted.
        """
        async def _emit(msg: str, level: str = "info") -> None:
            if status_cb:
                await status_cb(msg, level)

        if not self._current_disk_image_id:
            await _emit("Preparing disk image for probe...")
            await self.prepare_disk_image(status_cb)

        sent_policy = self._build_egress_policy()._to_dict()
        sandbox_id = f"egress-probe-{uuid.uuid4().hex[:8]}"
        await _emit(f"Creating probe sandbox {sandbox_id}...")
        await self.create_sandbox(sandbox_id, question)

        try:
            client = self._sbx_clients[sandbox_id]
            await _emit(
                f"Holding probe sandbox alive for {wait_seconds}s so you can "
                "inspect/curl it (agent runs in parallel)..."
            )
            agent_status: dict[str, Any] | None = None
            agent_done_at: float | None = None
            deadline = time.monotonic() + wait_seconds
            while time.monotonic() < deadline:
                await asyncio.sleep(5)
                try:
                    st = await self.get_status(sandbox_id)
                    agent_status = {"status": st.status, "progress": st.progress}
                    if st.status in ("done", "error") and agent_done_at is None:
                        agent_done_at = time.monotonic()
                        await _emit(
                            f"Agent {st.status}; keeping sandbox {sandbox_id} "
                            "alive for the rest of the window."
                        )
                except Exception:
                    pass

            stored_policy = await asyncio.to_thread(
                lambda: client.get_egress_policy()._to_dict()
            )
            decisions = await asyncio.to_thread(client.get_egress_decisions)

            def _entries(items) -> list[dict[str, Any]]:
                return [
                    {"host": e.host, "scheme": e.scheme, "method": e.method, "path": e.path}
                    for e in (items or [])
                ]

            ne = getattr(decisions, "network_egress", None)
            allowed = _entries(getattr(ne, "allowed", None)) if ne else []
            denied = _entries(getattr(ne, "denied", None)) if ne else []

            # In-sandbox connectivity test: prove default-deny is enforced by
            # hitting an allowed host (Foundry/AOAI) vs disallowed hosts, from
            # *inside* the sandbox VM via the SDK exec API.
            connectivity = await self._exec_connectivity_test(client)

            agent_result: dict[str, Any] | None = None
            try:
                res = await self.get_result(sandbox_id)
                agent_result = {
                    "sources": res.sources[:5],
                    "answer_preview": (res.answer or "")[:200],
                }
            except Exception as ex:
                agent_result = {"note": f"result not ready: {ex}"}

            return {
                "sandbox_id": sandbox_id,
                "sent_policy": sent_policy,
                "stored_policy": stored_policy,
                "egress_decisions": {
                    "allowed_hosts": sorted({e["host"] for e in allowed if e["host"]}),
                    "denied_hosts": sorted({e["host"] for e in denied if e["host"]}),
                    "allowed": allowed,
                    "denied": denied,
                },
                "connectivity_test": connectivity,
                "agent_status": agent_status,
                "agent_result": agent_result,
            }
        finally:
            await _emit("Deleting probe sandbox...")
            await self.delete_sandbox(sandbox_id)

    async def _exec_connectivity_test(self, client) -> dict[str, Any]:
        """Run a tiny Python script *inside* the sandbox (via the SDK exec API)
        that tries HTTPS GETs to allowed hosts (Foundry/AOAI) and denied hosts
        (example.com, bing.com). Proves the default-deny egress policy is
        actually enforced at the network layer, not just stored.
        """
        allowed_hosts = [
            h
            for h in (
                urlparse(self.foundry_project_endpoint).hostname
                if self.foundry_project_endpoint
                else None,
                urlparse(self.openai_endpoint).hostname
                if self.openai_endpoint
                else None,
            )
            if h
        ]
        targets: dict[str, str] = {}
        for h in allowed_hosts:
            targets[f"allowed:{h}"] = f"https://{h}/"
        targets["denied:example.com"] = "https://example.com/"
        targets["denied:bing.com"] = "https://www.bing.com/"

        script = (
            "import json,ssl,urllib.request\n"
            "ctx=ssl.create_default_context();ctx.check_hostname=False;"
            "ctx.verify_mode=ssl.CERT_NONE\n"
            f"targets={targets!r}\n"
            "out={}\n"
            "for k,u in targets.items():\n"
            "    try:\n"
            "        r=urllib.request.urlopen(u,timeout=8,context=ctx)\n"
            "        out[k]={'result':'REACHABLE','status':getattr(r,'status',None)}\n"
            "    except Exception as e:\n"
            "        out[k]={'result':'BLOCKED','error':type(e).__name__+': '+str(e)[:120]}\n"
            "print(json.dumps(out))\n"
        )
        b64 = base64.b64encode(script.encode()).decode()
        cmd = f"python -c \"import base64;exec(base64.b64decode('{b64}'))\""
        try:
            res = await asyncio.to_thread(lambda: client.exec(cmd))
            raw = (res.stdout or "").strip()
            try:
                return {"targets": targets, "results": json.loads(raw)}
            except Exception:
                return {
                    "targets": targets,
                    "raw_stdout": raw[:500],
                    "stderr": (res.stderr or "")[:500],
                    "exit_code": res.exit_code,
                }
        except Exception as ex:
            return {"targets": targets, "error": f"{type(ex).__name__}: {ex}"}


# ── Helpers ─────────────────────────────────────────────────────────────────

def _required(name: str) -> str:
    val = os.environ.get(name)
    if not val:
        raise RuntimeError(
            f"{name} is required (set via env var or .env). See .env.example."
        )
    return val

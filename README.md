# Your Agent Swarm Needs More Than a Loop

One agent is easy to picture. Give it a prompt. Let it call a tool. Read the answer.

Then you add five more.

Now the real questions show up. Do they actually run concurrently? Where does their code execute? What can each agent reach on the network? How do you preload your frameworks and proprietary code without installing everything six times? And when one branch fails, can you trace the request from the original topic to the exact sandbox that went sideways?

We built a research swarm to work through those questions with real infrastructure. Not a diagram that stops at the model call. A deployable workflow built with Microsoft Agent Framework, an orchestrator running as an Azure Container Apps application, and isolated researchers running inside Azure Container Apps Sandboxes.

That distinction matters. Azure Container Apps hosts the long-running web application and workflow orchestrator. ACA Sandboxes provide the separate, ephemeral execution environments where individual researchers do their work.

## The Architecture

The application accepts a research topic, asks a research lead to produce sub-questions, and fans those questions out to as many as six researcher agents. A reviewer then decides whether to hand the accumulated evidence back to the research lead for a bounded follow-up wave or forward to a report writer. Every researcher gets its own ACA Sandbox, its own question, and a tightly restricted network boundary.

**Who this is for:** teams building agents that need parallel execution, custom code, strong isolation, controlled egress, keyless Azure access where supported, and one observable path across the full workflow.

![Research agent swarm architecture](images/architecture.png)

The flow of information is simple:

```text
You provide a topic
  |
  v
Research Lead plans a parallel research wave
  |
  +--> researcher 1 --> ACA Sandbox 1 --+
  +--> researcher 2 --> ACA Sandbox 2 --+
  +--> researcher 3 --> ACA Sandbox 3 --+--> Reviewer
  +--> researcher 4 --> ACA Sandbox 4 --+       |
  +--> researcher 5 --> ACA Sandbox 5 --+       +-- gaps --> Research Lead
  +--> researcher 6 --> ACA Sandbox 6 --+       |
                                                  +-- approved --> Report Writer --> Final report
```

The diagram is simple. Making each branch truly concurrent, isolated, and observable takes a few deliberate design choices.

The web UI presents both views of the same run. A branched architecture minimap
highlights the currently active owner or parallel wave and shows the Reviewer's
two conditional routes: evidence gaps return to the Research Lead, while
approved evidence advances to the Report Writer. An append-only execution
history gives every Research Lead, research wave, Reviewer, and Report Writer
invocation its own node. Handoffs appear as labeled edges between those nodes,
and a follow-up wave never replaces evidence from an earlier wave.

## 1. Real concurrency needs separate workflow edges

Microsoft Agent Framework gives us the agents and the workflow graph. The research lead returns the initial list of questions. The workflow caps that list at six, creates a fixed pool of researcher executors, and targets one researcher for each question.

The collector assembles the responses into a dossier. The reviewer makes an agent-directed routing decision: approve the dossier for the report writer, or return 2-4 focused questions to the research lead for one more parallel wave. The two-wave cap prevents an unattended review loop.

The surprising part was the fan-out.

It is tempting to express all researchers as one fan-out edge group. That looks correct on a whiteboard. In this implementation, however, one fan-out runner would deliver targeted messages sequentially. The graph would look parallel while the researcher model calls were serialized inside that runner.

So the workflow creates an individual edge for every researcher:

```python
builder = WorkflowBuilder(start_executor=research_lead)
for researcher in researchers:
    builder = builder.add_edge(research_lead, researcher)

builder = builder.add_edge(collector, reviewer)
builder = builder.add_edge(reviewer, research_lead)
workflow = builder.add_edge(reviewer, report_writer).build()
```

That is intentional. Separate edge runners let Microsoft Agent Framework schedule the researcher branches concurrently instead of putting six calls behind one delivery loop.

Each researcher agent stays deliberately thin. It has one tool, `run_in_sandbox`. The tool creates the sandbox, waits for the in-sandbox research process, retrieves the structured result, and deletes the sandbox. The researcher returns that result verbatim rather than asking another model call to rewrite it.

The workflow coordinates reasoning. The sandbox tool owns isolated execution.

Container Apps orchestrates. Sandboxes execute.

The names are close enough to create confusion, so let us make the boundary explicit.

| Component | Azure service | Responsibility |
|---|---|---|
| Orchestrator | Azure Container Apps | Hosts FastAPI, the UI, WebSocket progress, Microsoft Agent Framework workflow, and sandbox lifecycle code |
| Researcher runtime | ACA Sandboxes | Runs one research question inside a separate isolated environment |
| Sandbox group | ACA Sandboxes resource | Provides the control boundary used to create disk images and sandboxes |

The orchestrator is a normal Azure Container App. It remains available, accepts topics, builds the workflow, manages each fan-out, and carries the reviewer handoff between research waves and final writing.

The researcher is not another Container App replica. It runs from a disk image inside a newly created ACA Sandbox. One question goes in. One research result comes out. The sandbox is removed after the branch completes.

That separation gives every researcher its own execution boundary while keeping orchestration in a familiar web application.

## 2. Give every researcher a locked-down workspace

Compute isolation is only half the boundary. An autonomous researcher should not inherit unrestricted internet access just because it needs web search.

Every sandbox starts with default-deny egress. The orchestrator adds allow rules only for the endpoints required by the workload:

- Azure OpenAI for the direct model path
- Microsoft Foundry for the hosted research path
- Application Insights ingestion endpoints for telemetry

The policy is built with `default_action="Deny"`:

```python
_allow(self.openai_endpoint)
_allow(self.foundry_project_endpoint)

for endpoint in self._appinsights_egress_endpoints():
    _allow(endpoint)

return EgressPolicy(
    default_action="Deny",
    host_rules=host_rules,
)
```

There is no search-engine allow rule.

That is not an omission. The researcher uses Foundry hosted web search, and the search runs server-side in Foundry. From inside the sandbox, the agent calls the Foundry project endpoint. Foundry performs the search. The sandbox does not need direct access to Bing or another public search engine.

This is a useful pattern beyond research. Put broad external capability behind a service endpoint you trust, then give the sandbox access to that endpoint instead of opening the internet.

Authentication follows the same boundary.

The Bicep deployment creates user-assigned managed identities for the orchestrator and sandbox group, then grants scoped roles. The orchestrator identity gets Azure OpenAI (for its planner) and the sandbox group data plane. The sandbox group identity gets ACR pull, Azure OpenAI, and Foundry.

No token is ever placed inside a sandbox. Both the swarm researchers and the standalone agent ([create_sandbox.py](create_sandbox.py)) rely on egress `Transform` rules: for each model host, the proxy sets `Authorization` to an Entra token for the sandbox group's managed identity (audience `https://ai.azure.com` for the Foundry project, `https://cognitiveservices.azure.com` for Azure OpenAI). The in-sandbox code hands its SDK a placeholder credential, and the proxy replaces it on the way out.

No model API key needs to be baked into the researcher image.

## 3. Bake the researcher once

You can start from a public or base image and bootstrap the environment after the sandbox starts. Install packages. Pull frameworks. Download tools. Clone code. Then run the researcher.

That path is valid for small experiments.

It is rarely the shape customers want for a real agent workload. Their researchers need specific Python packages, agent frameworks, diagnostic tooling, security controls, and proprietary code. Reassembling that environment for every question adds moving parts to the hottest path in the system.

This sample builds the researcher as an OCI container image in Azure Container Registry, then creates a custom sandbox disk image from it. The researcher code and dependencies are already present when the sandbox starts.

The next challenge is freshness. A cached disk image is useful only if it matches the code you intended to run.

The orchestrator handles that with an ACR digest cache:

1. Resolve the current manifest digest for the configured ACR image.
2. List disk images associated with that image reference.
3. Reuse a matching disk image only when its state is `Ready` and its stored OCI digest matches ACR.
4. Build a new disk image when the digest changed or no usable match exists.
5. Delete stale images after selecting or creating the current one.

The image labels store both the source image reference and its OCI digest. A tag such as `research-agent:latest` can move, but the digest tells the orchestrator whether the underlying content changed.

There is one more practical step. The FastAPI lifespan hook starts disk-image preparation when the orchestrator starts. That prewarm resolves the digest and either reuses or builds the disk image before a user submits a topic. If prewarm fails, the application still starts and the normal request path can report the same problem.

Push new researcher code to ACR. The digest changes. The next preparation cycle rebuilds once. Later requests reuse the matching `Ready` image.

## 4. Connect the swarm with one distributed trace

Parallel systems fail in parallel too. A log line that says "research failed" is not enough when six sandboxes, several model calls, and a synthesis step are active.

The sample configures OpenTelemetry and exports supported telemetry to Application Insights. Microsoft Agent Framework instrumentation adds spans for agent runs and tool calls. FastAPI is instrumented in the orchestrator. The sandbox manager adds a `sandbox.create` span, and the Azure Monitor OpenTelemetry setup instruments supported outbound HTTP libraries used by the application.

The researcher process inside each sandbox configures the same telemetry destination.

The connection happens through W3C trace context. Before sandbox creation, the orchestrator injects `traceparent` and, when present, `tracestate` into the sandbox environment. The researcher extracts that context and starts its `research-agent.run` span under the same distributed trace.

The result is one trace path designed to connect:

- Topic decomposition
- Researcher agent and `run_in_sandbox` tool activity
- Sandbox creation and instrumented lifecycle or network operations
- In-sandbox Microsoft Agent Framework research and Foundry calls
- Fan-in, reviewer routing, and final report writing

Application Insights is provisioned in Bicep as a workspace-based resource backed by Log Analytics. The orchestrator and researchers receive the same connection string, and the sandbox egress policy allows the required ingestion endpoints.

That gives us a shared place to inspect the parts the code actually instruments, without claiming signals the sample does not emit.

## 5. Deploy the whole system

The infrastructure is Bicep. The deployment provisions the Container Apps environment, orchestrator Container App, sandbox group, Azure Container Registry, Foundry resources, managed identities, role assignments, Log Analytics workspace, and workspace-based Application Insights.

The entry point is deliberately short:

```bash
azd up
```

`azd` provisions the Bicep template, remotely builds and pushes the orchestrator image, builds and pushes the research-agent image through the post-provision hook, and deploys the orchestrator to Azure Container Apps.

After that, the orchestrator prepares the digest-cached researcher disk image and starts accepting topics.

The lesson for me was simple. A swarm is not six copies of the same prompt. It is a workflow, an execution boundary, an image lifecycle, an identity path, a network policy, and a trace that survives the fan-out.

Build those pieces together and the concurrency becomes the easy part.

## Model Deployment Quota

The model deployment defaults to capacity `750`. The requested capacity must fit
the available quota for the model, SKU, subscription, and region. Configure it
for the selected azd environment before provisioning:

```bash
azd env set AZURE_OPENAI_CAPACITY 750
azd up
```

If less quota is available, select a lower supported capacity. Higher capacity
requires sufficient quota; lower capacity may cause throttling during parallel
research runs. The model region is controlled by `AZURE_OPENAI_LOCATION`, not
`AZURE_LOCATION`, which controls the other resources. Only change the model
region after checking model availability and quota there.

## Create a Single Sandbox

Use [create_sandbox.py](create_sandbox.py) to create one sandbox directly through
the SDK, without starting the orchestrator or research workflow. It requires an
existing sandbox group and an identity with permission to create sandboxes in it.

Install the launcher dependencies in your Python environment:

```bash
python -m pip install azure-containerapps-sandbox==0.1.0b4 azure-identity dotenv-azd==0.3.0
```

For local CLI authentication, use an isolated Azure CLI profile:

```bash
export AZURE_CONFIG_DIR="$HOME/.local/state/aca-sandbox-cli"
az login

export SUBSCRIPTION_ID="<subscription-id>"
export RESOURCE_GROUP="<resource-group>"
export SANDBOX_GROUP="<sandbox-group-name>"
export DEFAULT_REGION="westus2"

python create_sandbox.py
```

Use the sandbox group name from the deployment's `sandboxGroupName` output and
its region. These settings can also be supplied with `--subscription-id`,
`--resource-group`, `--sandbox-group`, and `--region`.

The launcher uses `dotenv-azd` to load the selected azd environment from the
current project before parsing arguments. After `azd up`, you can omit the
manual exports above: it recognizes `AZURE_SUBSCRIPTION_ID` (or `subscriptionId`),
`AZURE_RESOURCE_GROUP` (or `resourceGroupName`), `sandboxGroupName`, and
`AZURE_LOCATION`. It also maps `openAiEndpoint` and `openAiDeployment` to the
agent's model settings. Explicit CLI arguments take precedence over environment
defaults; existing exported values are not overwritten by the loader. If azd
is unavailable or no environment is selected, manual configuration still works.
It does not load the orchestrator's `.env` file.

With no image configured, it uses the built-in `ubuntu` image, 0.5 vCPU, 1 GiB memory, no
exposed ports, and deny-all egress. It prints the sandbox ID and connection
settings and leaves the sandbox available, with auto-suspend set to 300 seconds.
**Auto-suspend is not deletion.** For a disposable command run, request cleanup:

```bash
python create_sandbox.py --command "uname -a" --delete-after-run
```

To use an existing custom disk image:

```bash
python create_sandbox.py --disk-id "<sandbox-disk-image-id>"
```

`--disk-id` must be an actual sandbox disk-image ID, not the ACR image reference
stored in the orchestrator's `DISK_IMAGE_ID` setting. To prepare a disk image
from a published OCI reference instead, pass `--image`. Without `--prompt`,
the script does not forward model credentials. A custom
image still runs its own configured startup command.

### Run a Single Agent With Sandbox Tools

The same script can run an autonomous [harness agent](https://learn.microsoft.com/en-us/agent-framework/concepts/harness?pivots=programming-language-python)
entirely inside ACA. It uses `LocalShellTool` through `shell_executor`, with
`ShellEnvironmentProviderOptions(probe_tools=("git", "python"))`. "Local" here
means local to the sandbox, not your computer. No commands require approval.

The runtime is in [sandbox-agent/](sandbox-agent/), with its own Dockerfile and
requirements. The `postprovision` hook builds and pushes both the research-agent
and sandbox-agent images during `azd up` or `azd provision`. It uses
[sandbox-agent/build.sh](sandbox-agent/build.sh) on macOS/Linux and
[sandbox-agent/build.ps1](sandbox-agent/build.ps1) on Windows. The scripts need
an authenticated Azure CLI, but not local Docker. Windows uses PowerShell and
does not require Bash.

To rebuild only the sandbox-agent after changing its code, run from the
repository root on macOS/Linux:

```bash
bash sandbox-agent/build.sh
```

On Windows:

```powershell
pwsh -NoProfile -File sandbox-agent/build.ps1
```

The research-agent build is also available independently through
[research-agent/build.sh](research-agent/build.sh) on macOS/Linux or
[research-agent/build.ps1](research-agent/build.ps1) on Windows:

```bash
bash research-agent/build.sh
```

```powershell
pwsh -NoProfile -File research-agent/build.ps1
```

Both research-agent scripts read the selected azd environment and build
`research-agent:latest`. The postprovision hook runs the research-agent build
first and stops if either image build fails.

After a successful build, the script stores `SANDBOX_AGENT_IMAGE` in the selected
azd environment. The launcher loads it automatically through `dotenv-azd`.

The script uses `azd env get-value` to read each missing
setting from the selected azd environment (`AZURE_SUBSCRIPTION_ID`,
`AZURE_RESOURCE_GROUP`, and `acrName`). Explicit `SUBSCRIPTION_ID`,
`RESOURCE_GROUP`, and `ACR_NAME` values take precedence. The lookup uses your
current directory's azd project context.

To override the deployment settings, or run without azd, supply all three:

```bash
export SUBSCRIPTION_ID="<subscription-id>"
export RESOURCE_GROUP="<resource-group>"
export ACR_NAME="<registry-name>"

SANDBOX_AGENT_IMAGE=$(bash sandbox-agent/build.sh)
echo "$SANDBOX_AGENT_IMAGE"
```

The script sends build logs to stderr and prints the image reference to stdout
only after a successful build and, when an azd environment is selected, a
successful save. A failed build leaves the stored image unchanged. Without azd
or a selected environment, it prints a notice to stderr and you can pass the
returned image to `--image`. Set `IMAGE_TAG` to override the default `latest`
tag. It resolves the registry login server from Azure and builds for Linux amd64.
With all three settings supplied explicitly, it can be invoked from any directory
using its full path.

The returned reference identifies an OCI image. Pass it to the launcher's
`--image` option to prepare a sandbox disk image automatically.
To build with local Docker instead:

```bash
docker build --platform linux/amd64 \
  -t <registry>/sandbox-agent:latest ./sandbox-agent
docker push <registry>/sandbox-agent:latest
```

The launcher prepares a disk image and waits up to four minutes for `Ready`
before creating a sandbox. For private ACR, the sandbox group's managed identity
pulls the image: Bicep grants it `AcrPull`, and the launcher passes its client ID
(`SANDBOX_GROUP_UAMI_CLIENT_ID` or `--image-identity-client-id`) to the disk-image
API's v2 endpoint as `source.managedIdentityClientId`. The installed SDK targets the
legacy endpoint, which rejects managed-identity pulls, so the launcher calls v2
directly while keeping the SDK's readiness poller. Public images need no identity.

The infrastructure outputs `SANDBOX_GROUP_UAMI_RESOURCE_ID` and
`SANDBOX_GROUP_UAMI_CLIENT_ID`, so `azd up` or
`azd provision` stores the existing sandbox group identity in the azd environment.
For an environment provisioned before this output was added, rerun provisioning
to populate it. No manual identity lookup or environment-variable export is needed:

```bash
azd provision
```

If the resource ID is already stored, populate just the client ID without
reprovisioning or rebuilding images:

```bash
IDENTITY_CLIENT_ID=$(az identity show \
  --ids "$(azd env get-value SANDBOX_GROUP_UAMI_RESOURCE_ID)" \
  --query clientId --output tsv) && \
azd env set SANDBOX_GROUP_UAMI_CLIENT_ID "$IDENTITY_CLIENT_ID"
```

Use the sandbox subscription, resource group, group name, and region configured
above. With the image and identity stored in azd, and the model outputs from
`azd up`, run without manual exports:

```bash
python -m pip install -r sandbox-agent/requirements.txt

python create_sandbox.py --prompt \
  "Create a Bash script in /workspace that writes a CSV of the squares of 1 through 10. Run it, inspect the CSV, and report its contents." \
  --delete-after-run
```

Progress goes to stderr, and the launcher prints `disk_image_id` alongside
`sandbox_id`. A later run can pass that ID via `--disk-id` to skip preparation.
`--disk`, `--disk-id`, `--image`, and `--snapshot-id` are mutually exclusive.
Any explicit source overrides `SANDBOX_AGENT_IMAGE`; use `--disk ubuntu` to
create a plain sandbox even when an agent image is configured. Without azd,
export the launcher and model settings and pass `--image "$SANDBOX_AGENT_IMAGE"`
as before.

Digest-pinned references (`registry/image@sha256:...`) reuse a matching `Ready`
disk image. Mutable tags, including `latest`, create a new disk image on every
launch so a rebuilt image is not silently ignored. Unlike the orchestrator, this
launcher does not resolve tags to ACR digests or prune old disk images.
`--delete-after-run` deletes only the sandbox, not its prepared disk image.
The plain Ubuntu disk and research-agent disk do not contain this harness runtime.

Use the sandbox configuration and authentication from the preceding section.

The launcher passes the task into the sandbox and invokes the agent there.
**The harness, model connection, shell, and filesystem operations all run inside
the sandbox.** No model credential goes into the sandbox. The sandbox's egress
policy denies everything except read-only (`GET`) requests to `api.github.com` and the
model endpoint, which goes through a `Transform` rule that sets the
`Authorization` header to an Entra token for the sandbox group's managed identity
(`SANDBOX_GROUP_UAMI_RESOURCE_ID`, which Bicep grants Cognitive Services OpenAI User).
The agent sends requests with a placeholder key, and the egress proxy replaces it
on the way out, so code inside the sandbox never sees a token.

- The agent uses Bash to list, read, create, and edit files and run installed programs.
- `LocalShellTool` uses `approval_mode="never_require"` and `acknowledge_unsafe=True`.
  There is no interactive input loop; ACA provides the execution isolation.
- The persistent Bash session starts in `/workspace`. Shell state persists across
  calls, subject to the shell tool's working-directory confinement behavior.
  Commands have a 30-second timeout and a 64-KiB output cap; the agent run has a
  five-minute timeout.
- Egress is denied except for the model endpoint and `GET https://api.github.com`.
  Blocked requests get a fast HTTP 403 from the proxy. Package downloads and other
  external HTTP calls remain blocked; bake dependencies into the image.
- `--show-egress` prints the proxy's audit log (allowed and denied requests) after
  the run. The log lags, so later requests can take minutes to appear; the portal's
  Egress Network Traffic panel shows the same data.
- File memory, hosted web search, and plan/execute mode switching are disabled.
  The harness retains todo tracking and session history.
- `--delete-after-run` removes the sandbox and its files when the run finishes or
  raises an error. Omit it to keep the sandbox and artifacts for inspection.

### Keep the agent's work: volumes and snapshots

Files in `/workspace` are private to the sandbox and are gone when it's deleted.
Two options keep them:

```bash
# Mount a group volume at /workspace/out and snapshot the sandbox after the run.
python create_sandbox.py --volume agent-output --snapshot-after-run first-draft \
  --delete-after-run \
  --prompt "Write report.md: three bullets on why agents need sandboxes. Keep your outline in notes.md."

# Continue from the snapshot (prints snapshot_id above).
python create_sandbox.py --snapshot-id <snapshot-id> --delete-after-run \
  --prompt "Add a fourth bullet about cost to the report."

# Read the volume from a plain sandbox.
python create_sandbox.py --disk ubuntu --volume agent-output --delete-after-run \
  --command "cat /workspace/out/report.md"
```

- `--volume NAME` creates the Azure Blob volume in the sandbox group if it's
  missing and mounts it at `/workspace/out`. When that mount exists, the agent is
  told to save final deliverables there. Volume files outlive every sandbox.
- `--snapshot-after-run NAME` captures the sandbox after the command or prompt
  finishes, including files, running processes, memory, and environment variables.
- `--snapshot-id ID` creates a sandbox from a snapshot. A restore accepts no
  configuration (labels, environment, egress policy, volumes, or ports) and uses
  the snapshot's CPU and memory. The egress policy isn't part of the snapshot, so a
  restored sandbox starts with unrestricted egress; the launcher reapplies the
  policy immediately. Volumes mounted at snapshot time stay mounted.
- Snapshots and volumes belong to the sandbox group and aren't deleted with the
  sandbox. Clean them up with the SDK (`delete_snapshot`, `delete_volume`) or the portal.

Because the proxy mints tokens as needed, long-running agents don't hit token
expiry. `--prompt` and `--command` are mutually exclusive. No orchestrator
or researcher service is started. Do not run the agent module directly on your
computer; its entry point checks the sandbox-image runtime marker.

## Production Smoke Tests

These opt-in scripts call your deployed services, real models, and real sandbox
tools. They replace the mock-heavy launcher, harness, and build-script tests.
They do not run during `azd up`, ordinary test discovery, or with `--help`.
Each requires `--run` to acknowledge Azure/model usage and resource creation.
Use the intended Azure CLI profile and selected azd environment from the
repository root. Prefer a dedicated validation environment when available.

```bash
python -m pip install -r scripts/requirements-smoke.txt

python scripts/smoke_standalone.py --run
python scripts/smoke_swarm.py --run
```

The standalone smoke uses the launcher's configuration and image-preparation
helpers. It runs the packaged agent in a fresh sandbox and unique workspace,
reads back the actual CSV, checks every square from 1 through 10, then removes
the CSV and reruns the agent-written Bash script to verify it recreates the
correct output. An agent claiming success is not enough. Pass `--disk-id`
to test an already-prepared image (which skips registry-pull coverage).

The standalone script allows four minutes for image preparation, three minutes
for sandbox readiness, 330 seconds for the remote agent process, and two minutes
for deletion polling. These are stage deadlines, not a hard wall-clock deadline
for all SDK networking and retries. It attempts sandbox deletion in `finally`
and waits for the sandbox to disappear. If creation fails before returning an
ID, it looks up only sandboxes with this run's unique labels for cleanup.
Prepared disk images are retained, never pruned; the recorded disk ID can be
reused. If the process is killed, a network call fails, or a resource appears
after the failure lookup, cleanup may require manual attention.

The swarm smoke connects to `orchestratorUrl` from azd (override with `--url`),
submits a brief research task, and requires at least two questions in every
research wave, a successful answer with sources from every researcher, reviewer
approval, and a nonempty final report with no reported pipeline errors. It
checks the operational workflow, not factual correctness or citation quality.
Its default WebSocket deadline is 900 seconds (`--timeout` overrides it). The
server owns researcher cleanup;
disconnecting or timing out does not cancel server work. The smoke script does
not delete shared disk images or other users' sandboxes, and does not claim to
verify server-side deletion. Inspect deployed logs if the run fails or times out.

Both scripts print a temporary artifacts directory and exit nonzero on failure.
Standalone artifacts include resource IDs/labels, agent stdout/stderr, the CSV,
and the generated Bash script. Swarm artifacts include streamed events (with
researcher sandbox IDs) and the final report when available. Treat these as
potentially sensitive application outputs; credentials are not deliberately
recorded. A successful CLI/syntax check is not a successful production smoke run.

The local workflow tests under `orchestrator/tests` cover collector ordering,
review-decision validation, and a complete two-wave handoff path with fake
model and researcher responses.

## Next Steps

1. **Try it:** Deploy the sample with `azd up`.
2. **Learn more:** Review the [Azure Container Apps Sandboxes documentation](https://sandboxes.azure.com) and map the egress policy to your own agent dependencies.
3. **Go deeper:** Explore the [Microsoft Agent Framework repository](https://github.com/microsoft/agent-framework) and compare its workflow graph to the individual-edge fan-out used here.

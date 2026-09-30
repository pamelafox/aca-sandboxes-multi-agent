<!--
---
name: Multi-agent research swarm on Azure Container Apps Sandboxes
description: A parallel research swarm and a standalone coding agent that run in isolated Azure Container Apps Sandboxes, built with Microsoft Agent Framework.
languages:
- python
- bicep
products:
- azure-container-apps
- azure-openai
- ai-services
page_type: sample
urlFragment: aca-sandboxes-multi-agent
---
-->

# Multi-agent research swarm on Azure Container Apps Sandboxes

This is the code companion for the talk **When One Agent Isn't Enough: Orchestrating Secure Parallel Agent Swarms**.

This repository includes two [Microsoft Agent Framework](https://learn.microsoft.com/agent-framework/) examples that run agents inside [Azure Container Apps Sandboxes](https://learn.microsoft.com/azure/container-apps/sandboxes-overview):

* **A research swarm:** an orchestrator web app on Azure Container Apps breaks a topic into questions and fans them out to up to six researcher agents. Each researcher runs in its own sandbox with locked-down network access, and a reviewer decides whether to run a follow-up wave or write the final report.
* **A standalone agent:** a script that creates one sandbox and runs an autonomous shell agent inside it. It's the simplest way to try sandbox egress rules, credential injection, volumes, and snapshots.

All of the infrastructure for deployment is included in the repository, using the [Azure Developer CLI](https://learn.microsoft.com/azure/developer/azure-developer-cli/). The infrastructure-as-code (Bicep files) will create a sandbox group, a Container Apps environment with the orchestrator app, Azure Container Registry, a Microsoft Foundry project with a `gpt-5.6-luna` deployment, managed identities with scoped role assignments, and Application Insights. Post-provision hooks build the researcher and standalone agent images in the registry.

* [Azure account requirements](#azure-account-requirements)
* [Getting started](#getting-started)
* [Deploying to Azure](#deploying-to-azure)
* [Run the research swarm](#run-the-research-swarm)
  * [How the swarm works](#how-the-swarm-works)
* [Run the standalone agent](#run-the-standalone-agent)
  * [Egress rules and credential injection](#egress-rules-and-credential-injection)
  * [Keep the agent's work: volumes and snapshots](#keep-the-agents-work-volumes-and-snapshots)
  * [Rebuild the agent images](#rebuild-the-agent-images)
* [Run the smoke tests](#run-the-smoke-tests)
* [View the slides](#view-the-slides)
* [Resources](#resources)

## Azure account requirements

* An Azure subscription with permission to create resources and role assignments, such as Owner, or Contributor plus User Access Administrator.
* Quota for the `gpt-5.6-luna` model (GlobalStandard) in the model region. The deployment requests 750K tokens per minute by default; see [Deploying to Azure](#deploying-to-azure) to change it.
* A region where Azure Container Apps Sandboxes are available. Check the [Sandboxes overview](https://learn.microsoft.com/azure/container-apps/sandboxes-overview) for current regions.

## Getting started

1. Make sure the following tools are installed:

    * [Python 3.12+](https://www.python.org/downloads/)
    * [Azure Developer CLI](https://learn.microsoft.com/azure/developer/azure-developer-cli/install-azd)
    * [Azure CLI](https://learn.microsoft.com/cli/azure/install-azure-cli), used by the image build scripts
    * Git

    Docker isn't required: images are built remotely in Azure Container Registry.

2. Clone the repository:

    ```shell
    git clone https://github.com/pamelafox/aca-sandboxes-multi-agent
    cd aca-sandboxes-multi-agent
    ```

3. Create a virtual environment and install the dependencies for the local scripts:

    ```shell
    python -m venv .venv
    source .venv/bin/activate
    python -m pip install -r scripts/requirements-smoke.txt
    ```

    That installs the Sandboxes SDK, Agent Framework, and `dotenv-azd`, which the standalone agent launcher and the smoke tests use.

## Deploying to Azure

1. Log in to Azure with both CLIs:

    ```shell
    azd auth login
    az login
    ```

2. Create an `azd` environment:

    ```shell
    azd env new
    ```

    It will prompt you for an environment name (like "aca-swarm"), a subscription, and a location for the sandbox group and the other resources.

3. Optionally, change the model region or capacity before provisioning:

    ```shell
    azd env set AZURE_OPENAI_LOCATION westus3
    azd env set AZURE_OPENAI_CAPACITY 750
    ```

    `AZURE_OPENAI_LOCATION` controls only the model region; the location you picked in the previous step controls everything else. Lower capacity needs less quota, but may cause throttling when six researchers run in parallel.

4. Provision the resources and deploy the orchestrator:

    ```shell
    azd up
    ```

    This provisions [infra/main.bicep](infra/main.bicep), builds the `research-agent` and `sandbox-agent` images in the registry, then builds and deploys the orchestrator app. It also grants your own account the roles needed to run the standalone agent from your machine.

5. Once it finishes, the output includes the orchestrator's URL. You can also get it later:

    ```shell
    azd env get-value orchestratorUrl
    ```

6. To delete the resources, run:

    ```shell
    azd down
    ```

    Sandboxes, snapshots, and volumes are deleted along with their sandbox group.

## Run the research swarm

Open the orchestrator URL in your browser. Type a research topic, or select one of the sample topics, such as:

```text
Optimal tree to plant for a native California garden for a lawn that faces north, has tough soil,
and is near oak tree roots. Tree can't grow more than 15 feet tall. Tree is NOT shaded.
```

The UI shows each research wave, researcher progress, the reviewer's decision, and the final report. The first run after a deployment can take longer while the orchestrator prepares the researcher's sandbox disk image.

![Research agent swarm architecture](images/architecture.png)

### How the swarm works

```text
You provide a topic
  |
  v
Planner creates a parallel research wave
  |
  +--> researcher 1 --> Sandbox 1 --+
  +--> researcher 2 --> Sandbox 2 --+--> Reviewer --+-- gaps --> Planner (one more wave)
  +--> researcher N --> Sandbox N --+               |
                                                    +-- approved --> Report Writer --> Final report
```

| Component | Runs on | Responsibility |
|---|---|---|
| Orchestrator | Azure Container Apps | FastAPI app, web UI, the Agent Framework workflow, and sandbox lifecycle code |
| Researcher | Azure Container Apps Sandboxes | Answers one question with Foundry hosted web search, in its own sandbox |
| Sandbox group | Azure Container Apps Sandboxes | Holds the disk images, the managed identity, and the sandboxes |

* **Structured outputs:** the planner, reviewer, and in-sandbox researcher each pass a Pydantic model as `response_format` ([planner_agent.py](orchestrator/agents/planner_agent.py), [reviewer_agent.py](orchestrator/agents/reviewer_agent.py), [research-agent/app.py](research-agent/app.py)), so their replies are typed objects instead of JSON text to parse.
* **Parallel fan-out:** [orchestrator/agents/workflow.py](orchestrator/agents/workflow.py) creates a separate workflow edge from the Planner to each researcher, so Agent Framework runs the researchers concurrently. A single fan-out edge group would deliver the messages one after another. The reviewer can send the lead back for at most one follow-up wave.
* **One sandbox per question:** each research question goes to a plain workflow executor that calls `run_in_sandbox` directly ([orchestrator/agents/sandbox_researcher.py](orchestrator/agents/sandbox_researcher.py)). It creates a sandbox, waits for the research result, and deletes the sandbox. There's no LLM on the orchestrator side of a branch; the research agent runs inside the sandbox. A failed branch still reports an error finding, so the reviewer sees what's missing.
* **Locked-down network access:** [orchestrator/sandbox_manager.py](orchestrator/sandbox_manager.py) creates every sandbox with a default-deny egress policy. The only destinations are the Foundry project and Azure OpenAI hosts, through `Transform` rules, and the Application Insights ingestion endpoints. Web search runs inside Foundry, so the sandbox never talks to a search engine.
* **Keyless model access:** no key or token is ever placed in a sandbox. The `Transform` rules have the egress proxy set the `Authorization` header to a Microsoft Entra token for the sandbox group's managed identity, which has the Foundry User and Cognitive Services OpenAI User roles. The researcher code in [research-agent/app.py](research-agent/app.py) hands its SDK a placeholder credential.
* **Baked researcher image:** the researcher code and dependencies are built into the `research-agent` image in the registry, then turned into a sandbox disk image. The orchestrator reuses a disk image only when its stored digest matches the registry's current digest, and prepares it at startup so the first request doesn't wait.
* **One distributed trace:** the orchestrator passes its W3C `traceparent` into each sandbox's environment, and the researcher starts its spans under it. Application Insights shows the whole run, from topic planning through each sandbox to the final report.

## Run the standalone agent

[create_sandbox.py](create_sandbox.py) creates one sandbox with the Sandboxes SDK, without the orchestrator. It reads its settings (subscription, resource group, sandbox group, region, model endpoint, and agent image) from your `azd` environment. Command-line options such as `--sandbox-group` and `--region` override them.

Create a plain Ubuntu sandbox and run a command in it:

```shell
python create_sandbox.py --disk ubuntu --command "uname -a" --delete-after-run
```

Run the autonomous agent from [sandbox-agent/](sandbox-agent/) inside a sandbox:

```shell
python create_sandbox.py --delete-after-run --prompt \
  "Create a Bash script in /workspace that writes a CSV of the squares of 1 through 10. Run it, inspect the CSV, and report its contents."
```

The agent is an Agent Framework [harness agent](https://learn.microsoft.com/agent-framework/concepts/harness?pivots=programming-language-python) with a shell tool. The harness, model calls, shell commands, and files all live in the sandbox, not on your machine. Commands don't need approval, since the sandbox is the isolation boundary.

Useful options:

| Option | What it does |
|---|---|
| `--delete-after-run` | Deletes the sandbox when the run finishes or fails. Without it, the sandbox stays available and auto-suspends after 5 idle minutes. |
| `--disk ubuntu` | Uses the built-in Ubuntu image instead of the agent image. |
| `--disk-id <id>` | Reuses a prepared disk image (the launcher prints `disk_image_id`), skipping preparation. |
| `--name <name>` | Adds a `name` label, so you can find the sandbox in the portal. |
| `--suspend-mode Disk` | Keeps only files across stop and resume. The default, `Memory`, also keeps running processes. |
| `--show-egress` | Prints the egress proxy's allowed and denied requests after the run. |
| `--volume <name>` | Mounts a sandbox group volume at `/workspace/out`, creating it if needed. |
| `--snapshot-after-run <name>` | Snapshots the sandbox after the run and prints the snapshot ID. |
| `--snapshot-id <id>` | Starts from a snapshot instead of an image. |

### Egress rules and credential injection

The standalone agent's egress policy (`agent_egress_policy` in [create_sandbox.py](create_sandbox.py)) denies everything except:

* **The model endpoint**, through a `Transform` rule: the egress proxy sets `Authorization` to an Entra token for the sandbox group's managed identity. The agent sends a placeholder key, so it never holds a credential.
* **Read-only GitHub**: `GET` requests to `api.github.com`, with no token.

To see the rules in action, ask the agent to make requests, then print the proxy's decisions:

```shell
python create_sandbox.py --show-egress --prompt \
  "Use Python to try these requests and report each HTTP status code in a table: GET https://api.github.com/zen, POST https://api.github.com/markdown with JSON {\"text\": \"hi\"}, GET https://pypi.org/simple/requests/, and GET https://example.com."
```

The GitHub `GET` returns 200. The GitHub `POST`, pypi.org, and example.com get a fast HTTP 403 from the proxy. `--command` runs get the same policy, and the agent image includes curl, so you can also try the rules directly. The model call works even though the sandbox has no key:

```shell
MODEL_HOST=$(azd env get-value openAiEndpoint | sed -E 's#https://([^/]+)/?#\1#')
python create_sandbox.py --delete-after-run --command "curl -s -o /dev/null -w '%{http_code}\n' https://api.github.com/zen; \
  curl -s -o /dev/null -w '%{http_code}\n' https://example.com; \
  curl -s https://$MODEL_HOST/openai/v1/responses -H 'Content-Type: application/json' \
    -d '{\"model\": \"gpt-5.6-luna\", \"input\": \"Say hi in five words.\"}'"
```
 The audit log lags, so `--show-egress` may not show every request yet; the sandbox's **Egress Network Traffic** panel in the Azure portal fills in within a few minutes. The log is only readable while the sandbox is running.

### Keep the agent's work: volumes and snapshots

Files in `/workspace` are private to the sandbox and are deleted with it. Volumes and snapshots keep them:

```shell
# Mount a volume at /workspace/out, and snapshot the sandbox after the run.
python create_sandbox.py --volume agent-output --snapshot-after-run first-draft --delete-after-run \
  --prompt "Write report.md: three bullets on why agents need sandboxes. Keep your outline in notes.md."

# Continue from the snapshot, using the snapshot_id printed above.
python create_sandbox.py --snapshot-id <snapshot-id> --delete-after-run \
  --prompt "Add a fourth bullet about cost to the report."

# Read the volume from a plain sandbox.
python create_sandbox.py --disk ubuntu --volume agent-output --delete-after-run \
  --command "cat /workspace/out/report.md"
```

* **Volumes** are Azure Blob storage owned by the sandbox group, and they outlive every sandbox that mounts them. When `/workspace/out` is mounted, the agent is told to save its final deliverables there.
* **Snapshots** capture files, running processes, memory, and environment variables. A restore can't change the configuration, and the egress policy isn't part of the snapshot, so a restored sandbox starts with unrestricted egress. The launcher reapplies the policy right away.
* Snapshots and volumes aren't deleted with the sandbox. Delete them in the portal or with the SDK (`delete_snapshot`, `delete_volume`).

### Rebuild the agent images

`azd up` and `azd provision` build both images. To rebuild one after changing its code, run from the repository root:

```shell
bash sandbox-agent/build.sh
bash research-agent/build.sh
```

On Windows, use `pwsh -NoProfile -File sandbox-agent/build.ps1` and `pwsh -NoProfile -File research-agent/build.ps1`.

The sandbox-agent script stores the new image reference as `SANDBOX_AGENT_IMAGE` in your `azd` environment. Because it uses the `latest` tag, the launcher prepares a fresh disk image on each run. The orchestrator picks up a new `research-agent` image the next time it prepares a disk image; to force that, call `POST /api/sandbox/disk-image/recreate` on the orchestrator.

## Run the smoke tests

These scripts call your deployed resources and real models, so each one requires `--run`:

```shell
python scripts/smoke_standalone.py --run
python scripts/smoke_swarm.py --run
```

* [scripts/smoke_standalone.py](scripts/smoke_standalone.py) runs the standalone agent in a fresh sandbox, then checks the CSV it wrote and reruns its script, rather than trusting the agent's own report. It deletes the sandbox afterward.
* [scripts/smoke_swarm.py](scripts/smoke_swarm.py) submits a short topic to the deployed orchestrator and checks that every researcher returns an answer with sources, the reviewer approves, and the final report isn't empty.

Both print a temporary artifacts directory and exit nonzero on failure. The workflow unit tests in [orchestrator/tests](orchestrator/tests) use fake model and researcher responses and don't need Azure.

## View the slides

The talk's slides are a [reveal.js](https://revealjs.com/) deck in [docs/](docs/), published with GitHub Pages at [pamelafox.github.io/aca-sandboxes-multi-agent](https://pamelafox.github.io/aca-sandboxes-multi-agent/). To view them locally, serve the folder and open it in a browser:

```shell
python -m http.server 8765 --directory docs
```

Then open `http://localhost:8765/index.html`. The talk plan, including timing and open questions, is in [talk.md](talk.md).

## Resources

Azure Container Apps Sandboxes:

* [Sandboxes overview](https://learn.microsoft.com/azure/container-apps/sandboxes-overview)
* [Sandboxes documentation](https://sandboxes.azure.com/docs/sandboxes)
* [Control egress](https://sandboxes.azure.com/docs/sandboxes/sandbox/egress)
* [Sandbox identity](https://sandboxes.azure.com/docs/sandboxes/identity)
* [Lifecycle, suspend, and snapshots](https://learn.microsoft.com/azure/container-apps/sandboxes-snapshots-state-management)

Building the agents:

* [Microsoft Agent Framework](https://learn.microsoft.com/agent-framework/)
* [Agent Framework workflows](https://learn.microsoft.com/agent-framework/workflows/)
* [Azure Developer CLI](https://learn.microsoft.com/azure/developer/azure-developer-cli/)

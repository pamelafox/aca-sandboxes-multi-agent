# Talk plan

We are building a talk based on this example.

## Talk title

When One Agent Isn't Enough: Orchestrating Secure Parallel Agent Swarms

## Talk description

AI agents need to run code, call APIs, and fan out in parallel - but doing that safely at scale is hard.

This session shows how to build agentic workloads on hardware-isolated, sub-second, disposable compute that agents can provision themselves. Watch a live research-agent swarm spin up a fleet of secure sandboxes in parallel, run real work in true isolation, and tear it down automatically - with keyless auth throughout.

Powered by Azure Container Apps Sandboxes. You'll learn
• Why untrusted agent code and multi-agent fan-out break traditional container/VM approaches
• The pattern for safe, ephemeral, per-agent compute: isolation, instant start, scale-to-zero, snapshot/resume
• How agents can self-provision compute as a tool to extend their own capabilities
• Controlling blast radius with hardware isolation, egress policies, and keyless managed identity
• A working orchestration pattern for parallel agent swarms you can adapt to your own workloads

## Demo ideas

* Show the orchestration demo
* Open the Azure portal (portal.azure.com)
* Open Azure Monitor
* Create a standalone sandbox to dig into sandbox internals - prove it can't bust out, ala https://simonwillison.net/2026/Sep/4/rogue-agent-wikis/

## Demo prompt ideas

Good demo prompts have several constraints that split into independent research questions, and they need current web information. The same prompts are sample buttons in the orchestrator UI ([orchestrator/wwwroot/index.html](orchestrator/wwwroot/index.html)).

**Gardening:**

> optimal tree to plant for a native california garden for a lawn that faces north, has tough soil, and is near oak tree roots. tree cant grow more than 15 feet tall. tree is NOT shaded.

**Car upgrade** (recovered from the swarm's Application Insights traces, run on Sept 25):

> My family of four in California is deciding whether to replace our gas car (Subaru Forester 2001) with a hybrid version of the Forester in 2026. Compare the total five-year cost, charging practicality, winter range, reliability, insurance, and available incentives. Include the strongest reasons not to switch, identify assumptions that could change the recommendation, and produce a decision checklist.

An earlier run asked about "an electric version of the Forester" instead. That version is a good reviewer-loop demo: the first wave reported that Subaru doesn't sell an electric Forester, and the follow-up wave compared the 2001, a 2026 Forester Hybrid, a gas Forester, and Subaru's actual EV.

**Home heating:**

> Should I replace the gas furnace in my 1950s San Francisco Bay Area home with a heat pump? Compare upfront and installation costs, available rebates and tax credits, yearly operating costs, comfort in mild winters, and what electrical panel upgrades might be needed.

**Family travel:**

> Plan a 5-day trip to Kyoto in early April with a toddler. Cover cherry blossom timing and crowds, stroller-friendly sights, family-friendly places to stay, getting around without a car, and toddler-friendly food.

**Developer tooling:**

> Which Python project and dependency manager should a team of five adopt for a new web app: pip with venv, Poetry, or uv? Compare install speed, lockfile support, Python version management, Docker friendliness, and ecosystem maturity.

## Slide ideas

* Diagram of demo
* Section about sandboxing technology
* Network egress: Layer 7 firewall

## Proposed outline

Core story: **Agents need somewhere safe to act. ACA Sandboxes make that execution environment programmable, so a swarm can create one workspace per task and dispose of it when the work is done.**

**Current count: 38 slides in the deck, including 4 section slides, 4 demo slides (one optional), and Q&A.** The slide numbers in the headings below predate the latest reordering; the deck is the source of truth for order. Each numbered heading below represents exactly one slide. Reveals/fragments do not add to the count. Speaker notes, code sources, and ASCII prototypes describe the slide; they are not additional slides.

Use the research swarm as the running example, but make Sandboxes the subject. Connect architecture and security concepts to infrastructure definitions, SDK calls, and observed runtime behavior. Keep agent-framework mechanics brief.

**Hour budget:** Slides 1-2: 3 minutes; 3-4: 7 minutes; 5: 2 minutes; 6-14: 12 minutes; 15-21: 13 minutes; 22-23: 5 minutes; 24-25: 4 minutes; 26-30: 6 minutes. Reserve 3 minutes for demo delays or optional slide B1, and 5 minutes for Q&A on slide 31. These are rehearsal targets, including live demo time, not equal time per slide.

**Demo slide convention:** Slides 3, 16, 25, and optional B1 each show a large screenshot of the actual demo, with a short title. The screenshot is the presenter cue to switch to the live application, terminal, or portal. Keep the runbook in speaker notes. Screenshot descriptions below are capture requirements, not claims that assets already exist.

**Section slides:** Four centered transition slides, each with "Part N of 4", a title, a one-line subtitle, and a roadmap of all four sections with the current one highlighted. Speaker notes hold the verbal transition.

1. **Introducing the swarm** (after the title slide): one question, many parallel researchers.
2. **Sandboxes 101** (before "What is a sandbox?"): create, configure, secure, and keep state.
3. **Back to the swarm** (before "Swarm architecture on Azure"): sandboxes as a tool for parallel agents.
4. **Wrapping up** (before the recap): recap, where else sandboxes fit, and takeaways.

### Slide 1. When One Agent Isn't Enough

**On slide:** Full talk title, presenter name, and a visual of parallel isolated workspaces. Briefly state that the session will go from a working swarm to the infrastructure and code behind it.

### Slide 2. One question, several independent research tasks

**Slides / main idea:** Introduce a research question with independent sub-questions. Fan-out helps, but now several agents need compute, permissions, and cleanup at once.

**Demo beat:** Preview the Forester question and the work it can split into.

### Slide 3. Demo: the research swarm

**On slide:** Screenshot of the swarm UI running the Forester question, after a second research wave.

**Demo 1: End-to-end swarm.** Submit the question. Use the architecture minimap to show ownership moving from Planner to a parallel research wave to Reviewer, then point to the append-only history when the Reviewer requests another wave. The earlier prompts and results remain visible rather than being replaced. Inspect the resulting report, and briefly show the live sandboxes in the Azure portal while they exist.

**Speaker notes:** Start the run early and explain progress while it works. Keep a completed report and captured sandbox list ready rather than waiting silently for the live run.

### Slide 4. Swarm architecture: how the work flows and where it runs

**Slides / main idea:** One combined diagram answers "how does the work flow?" and "where does it run?" Reveal the hosting boundaries after introducing the agent workflow. Keep the hosting labels vendor-neutral (container versus sandbox); Azure services are named starting on slide 6.

**ASCII prototype:** Three branches shown for readability; the sample supports up to six. Each research question goes to an executor that calls `run_in_sandbox`; the actual research process runs across that boundary in a separate sandbox.

```text
				 User question
					 |
					 v
+------------------------------------------+   +-------------------------------+
| CONTAINER                                |   | SANDBOXES                     |
| Orchestrator                             |   | One per task                  |
|                                          |   |                               |
| Planner                                   |   | +---------------------------+ |
|   |                                      |   | | Sandbox 1                 | |
|   +--> Researcher agent 1 --tool call-----|-->| | Research process          | |
|   |                       <--result------|---| +---------------------------+ |
|   |                                      |   |                               |
|   |                                      |   | +---------------------------+ |
|   +--> Researcher agent 2 --tool call-----|-->| | Sandbox 2                 | |
|   |                       <--result------|---| | Research process          | |
|   |                                      |   | +---------------------------+ |
|   |                                      |   |                               |
|   |                                      |   | +---------------------------+ |
|   +--> Researcher agent 3 --tool call-----|-->| | Sandbox 3                 | |
|                           <--result------|---| | Research process          | |
|                                          |   | +---------------------------+ |
| Returned researcher results              |   |                               |
|   |                                      |   | Each sandbox has its own      |
|   v                                      |   | execution boundary.           |
| Collector (fan-in) --> Reviewer           |   |                               |
|        ^                |                 |   |                               |
|        | gaps           +--> Report Writer   |                               |
|        +-- Planner            |           |   |                               |
+--------------------------------|---------+   +-------------------------------+
                                 |
                                 v
                            Final report

Tool-call lifecycle: create sandbox -> run research -> collect result -> delete
```

The three branches run concurrently. Results return to their researcher agents, then flow through the collector to the reviewer. The reviewer either hands specific gaps back to the planner for one bounded follow-up wave or hands the approved dossier to the report writer. Tool-call arrows summarize the SDK lifecycle, not a direct model-to-sandbox connection.

**Possible progressive reveal (or Reveal.js fragments):**

1. **The work:** Question, planner, parallel research branches, fan-in, reviewer handoff, and report writer. Introduce the problem before naming supporting Azure services.
2. **Where it runs:** Add the container and sandbox outlines, individual sandbox boundaries, and the researcher-agent versus research-process labels. This is the combined view to walk through right after the live demo.
3. **How it is supplied and connected:** Reuse the same layout later with the supporting relationships below. Distinguish image preparation, service calls, and telemetry from the main task-flow arrows.

```text
ACR OCI image --> sandbox disk image --> new researcher sandboxes

Orchestrator -------- model calls --------> Azure OpenAI / Foundry
Sandbox researchers - model/search calls -> Foundry
							 |
							 +--> hosted web search

Orchestrator + sandbox researchers -- telemetry --> Application Insights
```

Keep the supporting-services layer out of the initial reveal. On slides 15 and 19, highlight egress and identity on the service-call arrows; on slides 21 and 22, map the tool lifecycle to SDK code; on slides 23 and 24, trace the same route in Application Insights. Keep component positions stable across these versions so the audience can follow the additions.

### Slide 5. What is a sandbox?

**On slide:** Define a sandbox conceptually, before any Azure specifics. One large diagram builds in three steps, and a compact row below adds each property's card as its step appears:

1. **Isolated (initial view):** Sandbox 3 with its own processes, memory, and filesystem, beside faded Sandboxes 1 and 2 on a shared host.
2. **Fast & disposable (click 1):** Staggered lifetime bars under the host, one per sandbox, each starting within seconds and ending in "deleted."
3. **Bounded (click 2):** Outbound arrows from Sandbox 3 reach the model API and telemetry, while "any other site" is blocked. CPU and memory caps ("CPU ≤ 2 cores", "RAM ≤ 4 GiB") appear on the matching layers. These values are examples of limits you set, not defaults.

Card text:

| Property | On slide |
|---|---|
| **Isolated** | Its own processes, memory, and filesystem. Code inside can't see or change the host or other sandboxes. Don't claim a dedicated kernel here: that's true of microVM sandboxes, not containers or gVisor. |
| **Fast & disposable** | Starts in seconds or less for one task, then gets deleted when the task is done. |
| **Bounded** | Gets only the network endpoints, credentials, and CPU and memory you allow for its task. |

**Speaker notes:** Each property explains a design choice in the demo: model-driven code can't reach the host or other branches; six branches can start at once and nothing lingers; a misbehaving branch has limited blast radius. Then transition to how Azure Container Apps provides this.

### Slide 6. Meet ACA Sandboxes

**Slides / main idea:** The product introduction. Name the service, give its one-line definition, and show three value pillars before any mechanics.

**On slide:**

```text
                 Azure Container Apps Sandboxes
                  [ Now generally available ]
                     portal.azure.com

     Fast, isolated, and stateful compute infrastructure on demand

  Execute securely by     |  Resume instantly        |  Burst to hyperscale
  default                 |                          |
  Sandbox isolation for   |  Preserve state across   |  Sub-second start,
  any untrusted workload  |  stop and resume, with   |  zero to thousands,
                          |  enterprise controls     |  no compute cost idle

  ---------------------- Foundation layer in ----------------------
  [GitHub Copilot cloud sandboxes] [Microsoft Foundry hosted agents]
  [Azure Container Apps Express]   [Azure SRE Agent]
  [Microsoft Copilot Studio]
```

**Foundation strip:** Use the product logos. The same primitive powers Microsoft's own services, which sets up the "Platform building" use case on slide 28.

**Speaker notes: how each product uses Sandboxes** (for questions; end customers never see Sandboxes directly):

| Product | How it uses Sandboxes |
|---|---|
| GitHub Copilot | Copilot's [cloud sandbox](https://docs.github.com/en/copilot/concepts/security-governance-and-network-settings/about-cloud-and-local-sandboxes), for example `copilot --cloud` in the CLI, is an ACA Sandbox internally. |
| Microsoft Foundry | Hosted agents run on Sandboxes. *(Pamela to fill in.)* |
| Azure Container Apps Express | Express apps run on Sandboxes, which cut provisioning from 14-20 minutes to under a minute and cold start from about 20 seconds to sub-second. |
| Azure SRE Agent | [Python tools](https://learn.microsoft.com/azure/sre-agent/python-code-execution) and other [hosted tools](https://learn.microsoft.com/azure/sre-agent/global-tools-page) run in Sandboxes; the core agent is a regular Container App, with more parts moving to Sandboxes. |
| Copilot Studio | The [new agent harness](https://techcommunity.microsoft.com/blog/copilot-studio-blog/more-powerful-agents-and-workflows-for-autonomous-business-processes-introducing/4542969) runs each custom agent, including workflow-triggered runs, in its own sandbox, with data disk volumes storing agent memory. |

Don't demo `copilot --cloud`; the team reports it's currently unreliable. It's unconfirmed whether Copilot triggered from Teams uses the cloud sandbox, so don't claim it. Copilot Studio's pattern (one sandbox per agent, a data disk volume for memory, re-run on a workflow trigger) is a useful real-world example of the "Agent workflows" use case on slide 28. Copilot Studio's workflow triggers are a Copilot Studio feature; don't present them as the Sandboxes triggers feature from question 3.

**Speaker notes:** Each pillar previews later slides: isolation (slide 11), resume (slides 14 and 26), and burst/scale-to-zero (slides 14 and 21). Introduce the mental model in one sentence: a sandbox group holds sandboxes, and each sandbox boots from a disk image, which can come from your own OCI image. Slide 7 unpacks those resources. Sub-second start comes from prewarmed pools; it does not mean first-time custom image preparation is sub-second, and restoring from a snapshot "needs a short warm-up." "No compute cost idle" is precise: stopped sandboxes have no vCPU or memory charges, but storage for custom disk images, snapshots, and volumes will be billed (billing "coming soon" per the [cost docs](https://sandboxes.azure.com/docs/sandboxes/cost)).

### Slide 7. Architecture: Sandbox groups and sandboxes

**On slide:** Introduce the sandbox group before creating a sandbox, since it's a prerequisite. A nested diagram: an Azure resource group contains a regional sandbox group; the group shows its shared configuration (identity, disk images, volumes, secrets, VNet, connectors) and contains Sandboxes 1-3. Beside it, four points from the [sandbox groups docs](https://sandboxes.azure.com/docs/sandboxes/sandbox-groups):

* A regional Azure resource that contains your sandboxes
* The security and configuration boundary for every sandbox inside it
* Create it once, then create and delete sandboxes inside it
* Using its sandboxes needs the **Container Apps SandboxGroup Data Owner** role on the group

Footer: no Container Apps environment, deployed Container App, or swarm orchestrator is required.

**Speaker notes:** The sandbox group is the ARM management scope (control plane: portal, CLI, Bicep, or Terraform). Sandboxes are group-scoped data-plane objects, not Bicep-declared child resources. In the swarm, one group holds every researcher's sandbox. Leave model services, monitoring, and detailed RBAC for their own slides.

### Slide 8. Create a sandbox group

**On slide:** Two code boxes, each linked to its quickstart. Both create the regional sandbox group and grant the **Container Apps SandboxGroup Data Owner** role on it, which data-plane calls need.

* **Bicep** ([setup-bicep](https://sandboxes.azure.com/docs/sandboxes/quickstart/setup-bicep)): a `Microsoft.App/sandboxGroups@2026-02-01-preview` resource plus a role assignment scoped to the group.
* **Azure CLI + `aca` CLI** ([setup-cli](https://sandboxes.azure.com/docs/sandboxes/quickstart/setup-cli)): `az group create`, then `aca sandboxgroup create ... --set-config` and `aca sandboxgroup role create`. There's no `az` command for sandbox groups yet.

**Speaker notes:** `--set-config` saves the group, subscription, and region so later `aca` commands don't need them; `aca doctor` verifies setup. RBAC can take a minute to propagate. The portal can also create a group. Later slides extend this Bicep to pull images from ACR.

### Slide 9. Create a sandbox from the portal

**On slide:** A screenshot of the [Azure portal](https://portal.azure.com) **Create Sandbox** form in simple and quick mode ([slides/images/create-sandbox-portal.png](docs/images/create-sandbox-portal.png)): source set to the `ubuntu` public disk image and resource tier M. The screenshot is the cue to demo the portal flow live. Caption: the portal URL and the prerequisites (a Microsoft Entra account and the **Container Apps SandboxGroup Data Owner** role). Capture the screenshot from portal.azure.com (see open question 15). The [Learn portal quickstart](https://learn.microsoft.com/azure/container-apps/sandboxes-quickstart-portal) is written for sandboxes.azure.com, but the steps are the same.

**Demo (portal quickstart):** Create a sandbox group (subscription, resource group, name, region). Then **+ Create sandbox**, choose the **Ubuntu** disk image, and keep the default 1 vCPU and 2 GiB. Open the sandbox to attach the browser terminal, then run (verified on the `ubuntu` image):

1. Its own Linux machine: `whoami`, `uname -a`, `cat /etc/os-release`
2. Its own kernel: `dmesg | head -2` shows `[0.000000] Linux version 6.12.8+ ...`, the boot log of a kernel that started seconds ago just for this sandbox. A container never sees its own kernel boot. Matches the docs: "each sandbox runs in its own secure boundary with its own kernel." Optional extras: `grep -m1 -o hypervisor /proc/cpuinfo`, `cat /proc/cmdline` (`root=/dev/vda`, `console=hvc0`).
3. The size you picked (M = 1 core / 2 GiB / 20 GiB): `nproc`, `free -h`, `df -h /`
4. Internet access (egress is open with no policy): `curl -s https://api.github.com/zen`, or `python3 -c "import urllib.request; print(urllib.request.urlopen('https://api.github.com/zen').read().decode())"`. This sets up the later allowed/blocked demo.
5. Run code: `python3 -c "import platform, os; print(platform.python_version(), os.cpu_count(), 'cores')"`
6. Optional, not yet verified: ingress. `python3 -m http.server 8080 --bind 0.0.0.0`, then add port 8080 under the sandbox's **Ports** and open the generated URL.

Stop or delete it from the toolbar. Create the sandbox group ahead of time so provisioning isn't live waiting time.

**Speaker notes:** Besides the standard sandbox, the Create menu offers **GitHub Copilot** and **Claude** templates, which inject a stored GitHub PAT or Anthropic key into the sandbox at start. Mention them in one sentence; unlike egress injection (slide 19), those credentials land inside the sandbox. SDK availability: Python and TypeScript SDKs (beta) today, .NET beta soon, stable SDKs by Ignite (source: [microsoft/azure-container-apps#1839](https://github.com/microsoft/azure-container-apps/issues/1839#issuecomment-5821874629)). The Python SDK appears in the swarm code later; save `azd up` and the full swarm deployment for slide 23.

### Slide 10. Create a sandbox programmatically

**On slide:** Four boxes, each with a short snippet of the same create, run, delete flow and a link to its quickstart:

| Option | Snippet | Quickstart |
|---|---|---|
| `aca` CLI | `aca sandbox create --disk ubuntu --label name=demo`, then `exec -l name=demo -c "uname -a"` and `delete` | [setup-cli](https://sandboxes.azure.com/docs/sandboxes/quickstart/setup-cli) |
| Python SDK | `client.begin_create_sandbox(disk="ubuntu").result()`, `sandbox.exec(...)`, `sandbox.delete()` | [setup-python-sdk](https://sandboxes.azure.com/docs/sandboxes/quickstart/setup-python-sdk) |
| TypeScript SDK | `groupClient.sandboxes.beginCreate(...)`, `.exec(...)`, `.delete(...)` | [setup-typescript-sdk](https://sandboxes.azure.com/docs/sandboxes/quickstart/setup-typescript-sdk) |
| Agent Skill (Copilot CLI) | `/plugin install sandboxes@Azure-Container-Apps`, then ask the agent in natural language | [agent-skills](https://sandboxes.azure.com/docs/sandboxes/quickstart/agent-skills) |

Snippets are trimmed from the quickstarts and assume the sandbox group already exists. Bicep and Terraform quickstarts create the group; sandboxes are data-plane objects, not ARM resources.

### Slide 11. Inside a sandbox

**On slide:** Reinforce what the portal demo's `dmesg` just showed. Lead sentence: each sandbox runs as a hardware-isolated microVM with its own Linux kernel, own virtual hardware, and memory separation enforced by CPU virtualization. Two bullets (your container runs the way it always has, and this is a stronger boundary than a container runtime that shares the host kernel) beside a layer stack: your code, your container image, and its own Linux kernel, each per sandbox, on a hardware-isolated microVM boundary.

**Speaker notes:** The top two layers are yours. So far the demo used the built-in ubuntu image, which leads into bringing your own on the next slide. The notes carry the "boundary, not a guarantee" caveat.

### Slide 12. Bring your agent image

**On slide:** Custom-image path for sandbox-agent, with a short excerpt from [sandbox-agent/Dockerfile](sandbox-agent/Dockerfile) alongside the diagram. Public images remain an alternative, not a prerequisite for this path.

```text
Dockerfile + agent code
	   |
	   v
ACR: sandbox-agent OCI image                    [build and push]
	   |
	   v
Sandbox group: prepared custom disk image       [data plane]
	   |
	   v
The same one sandbox                           [SDK: select disk_id]
```

ACR is an optional registry choice for bringing your own image, not a prerequisite for trying a public image. It stores the OCI image; it does not run the agent. Building and pushing an OCI image, preparing a sandbox disk image, and creating the sandbox are separate steps. Use [sandbox-agent/Dockerfile](sandbox-agent/Dockerfile) for the custom-image example, not the swarm's research-agent image.

### Slide 13. Sandbox configuration

**On slide:** One `begin_create_sandbox(...)` call, annotated line by line: each parameter points to what it configures and to the slide that covers it. It maps the rest of the talk and replaces the two earlier SDK slides, since create/run/delete is already on slide 10.

| Parameter | Configures | Covered in |
|---|---|---|
| `disk_id=disk.id` | What it boots | ✓ Bring your agent image (slide 12) |
| `cpu`, `memory` | How big it is | Resource limits |
| `auto_suspend_seconds` | When it goes idle | ✓ Sandbox lifecycle (slide 14) |
| `egress_policy` | Where it can connect | Network egress |
| `ports` | Who can reach it | Network ingress |
| `volumes` | What data it keeps | Workspace data |

All parameters are real `begin_create_sandbox` keywords in `azure-containerapps-sandbox` (checked against the installed SDK). Defaults: `cpu="1000m"`, `memory="2048Mi"`, `auto_suspend_seconds=300`, `auto_suspend_mode="Memory"`. Other options if asked: `disk_size`, `labels`, `environment`, `connections`, `entrypoint`/`cmd`.

**Speaker notes:** Client setup isn't shown: `SandboxGroupClient(endpoint_for_region(region), credential, subscription_id=..., resource_group=..., sandbox_group=...)`. Creating a client doesn't create a sandbox. `begin_create_sandbox` is a long-running operation; `.result()` waits until it's running. With no egress policy, outbound access is unrestricted, which is why the example sets one.

### Slide 14. Sandbox lifecycle

**Slides / main idea:** Explicit lifecycle control: a sandbox is either running or stopped, and policies move it between states without the application polling.

**On slide:** A compact lifecycle visual, not a live demo yet.

```text
                  +------------- lifecycle policy -------------+
                  |    idle timeout or stop command            |
                  |    (snapshot disk, optionally memory)      |
Create ---------> |  Running  ------------------->  Stopped    | --auto-delete--> Delete
                  |           <-------------------             |
                  |    network traffic or start command        |
                  |    (resume in under a second)              |
                  +--------------------------------------------+

Disabled: a third state; the sandbox cannot start until re-enabled.
```

Source: [portal lifecycle docs](https://sandboxes.azure.com/docs/sandboxes/sandbox/lifecycle), whose diagram shows the same transitions, including network traffic resuming a stopped sandbox. Stopped sandboxes incur no compute charges and don't count against the Sandbox Cores quota. Call back to this diagram on slide 21 (auto-delete as a cleanup backstop) and slide 26 (memory snapshots).

**Speaker notes:** The lifecycle policy has two parts: auto-suspend (idle timeout plus a suspend mode, `Memory` or `Disk`) and auto-delete, which removes sandboxes that have stayed stopped. Sandboxes with a data-disk volume can only use `Disk` mode. Set it with `sandbox.set_lifecycle_policy(LifecyclePolicy(auto_suspend=AutoSuspendPolicy(...), auto_delete=AutoDeletePolicy(...)))` in the SDK or `aca sandbox lifecycle set` in the CLI; `stop()` and `resume()` are explicit alternatives. Don't explain what causes the Disabled state; the docs only say a disabled sandbox can't start until it's re-enabled.

### Slide 15. Network egress: where can this code connect?

* Dedicate this slide to outbound traffic. Egress policies are **opt-in**: with no policy, a sandbox has unrestricted outbound access. Default-deny is something you set, then you allow only the destinations the workload needs.
* Outbound traffic is enforced by a Layer 7 egress proxy. Rules match on **host, path, and HTTP method**; the first matching rule wins, otherwise the default action applies. Actions are `Allow`, `Deny`, `Transform` (modify headers, such as injecting a token; slide 19), and `Rewrite` (change destination). CIDR-based network rules also exist, and a policy can be updated on a running sandbox.
* Traffic inspection modes: `Full` inspects all traffic and blocks non-HTTP; `Partial` inspects only rule-matching traffic and allows non-HTTP; `None` turns inspection off. Path and method rules need `Full`.
* Show the actual policy for model/service endpoints and Application Insights telemetry; distinguish these from unrestricted internet access.
* Foundry-hosted search happens outside the sandbox. The sandbox contacts Foundry, not each website being searched.
* An allowed destination is still a possible path for data to leave. Egress restrictions do not validate every request or make every allowed service safe.

**Speaker notes:** Explain the policy here; switch to the live test on slide 16. The same policy can be set from the CLI (`aca sandbox egress set -l <selector> --default Deny --rule "*.github.com:Allow" --traffic-inspection Full`) or as a YAML file (`aca sandbox egress apply --file egress.yaml`), which is the only documented way to write path, method, and transform rules today. For per-request decisions, an egress webhook (`hookRef`) can allow, deny, or transform based on the `sandboxId`. If asked why [research-agent/app.py](research-agent/app.py) disables TLS verification: the proxy intercepts TLS with a certificate the sandbox doesn't trust by default. Don't recommend `verify=False` as a pattern; say it's a sample shortcut.

**Code slide:** Extract `_build_egress_policy` from [orchestrator/sandbox_manager.py](orchestrator/sandbox_manager.py), focusing on `EgressHostRule`, the allowed endpoint hosts, and `EgressPolicy(default_action="Deny", host_rules=host_rules)`. Show where that policy is attached during sandbox creation. Keep the longer telemetry-endpoint parsing logic in the editor, not on the slide.

### Slide 15b. Outbound calls with credential injection

**Main point:** A sandbox group can have a managed identity, just like other Azure resources, and its sandboxes can call Azure services with Entra tokens for that identity. You grant it roles with normal Azure RBAC.

**On slide:** Code on the left, request flow on the right (same layout as the egress slide).

* **Code:** The swarm's actual policy from [orchestrator/sandbox_manager.py](orchestrator/sandbox_manager.py): a `Transform` rule on the Foundry host whose `Authorization` header comes from `EgressManagedIdentityRef(identity_type="UserAssigned", resource="https://ai.azure.com", format="Bearer {value}")`. The orchestrator adds a second rule for the Azure OpenAI host (audience `https://cognitiveservices.azure.com`), and the standalone agent ([create_sandbox.py](create_sandbox.py)) uses the same pattern.
* **Flow:** Sandbox (agent calls Foundry with a placeholder token) → egress proxy (match the Transform rule, get an Entra token for the group identity, set `Authorization`) → Foundry project (checks RBAC: the identity has Foundry User). Footer: "No key in the image, no token in the environment."

**Speaker notes:**

* Code inside the sandbox still needs an SDK credential object, so [research-agent/app.py](research-agent/app.py) hands it a placeholder; the proxy replaces the header after the request leaves the sandbox. The real token never exists inside the VM, and the proxy mints tokens as needed, so long-running agents don't hit expiry.
* The group identity's roles in this repo: AcrPull (image pulls), Cognitive Services OpenAI User, and Foundry User. Separately, whoever creates sandboxes needs **Container Apps SandboxGroup Data Owner** on the group; that's management, not model access.
* Identity exists only at the **sandbox group** level, so every sandbox in the group gets the same access. For narrower access, use separate sandbox groups per trust level, or an egress webhook that decides per `sandboxId` (webhooks can only return literal header values).
* Header values can also come from a group [secret](https://sandboxes.azure.com/docs/sandboxes/secrets) (`secretRef`); group secrets are never exposed as environment variables.
* Network rules decide reachability; authorization decides operations. You need both.
* Contrast with the portal's Copilot and Claude templates, whose provider credentials do land inside the sandbox.

### Slide 16. Demo: allowed and blocked network requests

**On slide:** Screenshot of the sandbox's **Network Audit** panel in the Azure portal, showing timestamped requests with their destination hosts marked ALLOWED or DENIED, next to the terminal that issued them. Include at least one denied request. No credentials visible.

**Speaker notes:** Reuse the ubuntu sandbox from the portal demo (slide 9): the curl that succeeded there fails after adding a deny-by-default policy. Run both requests under the egress policy, then show the Network Audit panel updating live with the allowed and denied entries. Tie each entry back to the rule on slide 15 that explains it. Capture the expected results ahead of time, including a panel screenshot. This demonstrates those rules, not universal protection against exfiltration or sandbox escape. The same decisions are available outside the portal: `aca sandbox egress decisions -l <selector> -o json` in the CLI, `sandbox.get_egress_decisions()` in the SDK (separate allowed and denied lists with host, method, and path), or exported continuously as `NetworkEgressDecisions` through the sandbox's `telemetryConfig` (slide 24).

### Slide 17. Network ingress: who can reach a service inside?

* Ingress is **off by default** and opt-in per sandbox and per port. Running a server inside a sandbox and exposing its port are separate decisions. Outbound permission does not imply inbound access.
* Publishing a port gives it an HTTPS URL. The documented mode is an **anonymous** port: a public URL (`*.{region}.adcproxy.io`) routed to a process listening on `0.0.0.0` inside the sandbox. Anyone with the URL can reach it, so the application listening on the port owns authentication.
* For private access, link the sandbox group to a Container Apps environment in Express mode and add a private endpoint. Port URLs then resolve to a private IP reachable from your VNet, peered networks, VPN, or ExpressRoute. This changes ingress only; egress policy is unchanged.
* Expose only what the workflow needs, and remove the port when done: removing it stops the URL immediately.

**Visual / demo beat:** Trace a caller through an exposed port to the sandbox process, with two paths: public anonymous URL, and private endpoint from a VNet. Mark "closed" as the default state. Keep this diagram-only unless an interactive server is part of the standalone demo.

**Code excerpt (optional):** `sandbox.add_port(8080, anonymous=True)` and `sandbox.remove_port(8080)`, or `aca sandbox port add -l <selector> --port 8080 --anonymous`.

**Speaker notes:** Don't describe non-anonymous port authentication; it isn't documented yet (open question 7). Incoming traffic also resumes a stopped sandbox (slide 14).

### Slide 18. Identity and RBAC: who can manage sandboxes?

**On slide:** Separate the caller's sandbox-management permission from the group's registry-pull identity. Show the `orchestratorSandboxDataOwner` role assignment from [infra/main.bicep](infra/main.bicep), highlighting principal, role (the built-in **Container Apps SandboxGroup Data Owner**), and `scope: sandboxGroup`. For the standalone script, explain that its caller also needs sandbox-management authorization; outside Bicep, `aca sandboxgroup role create` grants the same role. Mention AcrPull only briefly; the registry Bicep was cut from the deck.

### Slide 19b. Suspend and resume: same sandbox, later

**Main point:** Resume continues the same sandbox; a snapshot (next slide) creates a new one. The suspend mode decides what survives.

**On slide:** One code strip (`begin_create_sandbox(..., auto_suspend_mode="Memory")`, `begin_stop()`, `begin_resume()`), then two panels. **Disk:** files ✓, running processes ✗ (restart them); resumed in 0.9 s; required with a data-disk volume. **Memory:** files ✓, running processes and memory ✓; resumed in 0.6 s; keeps in-process credentials too. Footer: stopped sandboxes have no compute charges and don't count against the cores quota. It's followed by a demo slide with three portal screenshots: running, stopped, and resumed.

**Verified September 28 (westus group):** a background counter plus a file, then `begin_stop` and `begin_resume`. Memory mode: the counter continued from where it stopped. Disk mode: the file survived, the process didn't. Stopping in Memory mode took about 8 s versus about 1 s for Disk.

**Speaker notes:** The mode is set per sandbox (`auto_suspend_mode`) or in the lifecycle policy (`AutoSuspendPolicy(mode=...)`). The swarm never suspends; every researcher sandbox is deleted after its result is collected. Suspend fits long-lived agents that wait on people or events. CLI: `aca sandbox stop` / `aca sandbox start`.

### Slide 20. Snapshots: new sandboxes from saved state

**Main point:** Suspend and resume continues the same sandbox. A snapshot captures that state (files, memory, running processes) so you can create new sandboxes from it.

**On slide:** Code on the left (`begin_create_snapshot(name="first-draft")`, delete, `begin_create_sandbox(snapshot_id=...)`, `set_egress_policy(policy)`). Flow on the right: Sandbox → Snapshot "first-draft" (owned by the group) → two new sandboxes. Results: ✓ files, running processes, memory, env vars; ✗ egress policy: set it again.

**Verified September 28:** the snapshot took about 1.6 s and a restore about 0.4 s. A background counter kept counting after restore. A restore accepts no configuration and uses the snapshot's CPU and memory. **The egress policy isn't restored:** the restored sandbox reported `default_action='Allow'` and reached bing.com until `set_egress_policy` ran.

**Ask the ACA team:** Is dropping the egress policy on restore intended?

### Slide 20b. Volumes: storage that outlives sandboxes

**Main point:** Files in a sandbox are private and deleted with it. A volume is the deliberate way to keep files and share them across sandboxes.

**On slide:** Code on the left (`create_volume("agent-output")`, a writer sandbox mounting it at `/workspace/out`, a reader mounting it read-only at `/data`). Flow on the right: Writer sandbox → Volume "agent-output" (Azure Blob, owned by the group) → Reader sandbox. Results: ✓ reads `/data/report.md`; ✗ writes to `/data` fail (read-only file system).

**Verified September 28:** the volume is Azure Blob mounted with blobfuse2; files survived deleting the writer; a read-only mount rejected writes; a volume mount survived a snapshot restore.

**Speaker notes:** Unlike a snapshot, a volume holds only the files you put in it. Other types: DataDisk (Disk suspend mode only) and AzureBlobByo (your own container). Disk images should hold code and dependencies, not credentials or task data. Snapshots and volumes aren't deleted with the sandbox; retained storage will be billed at Premium Blob ZRS rates (coming soon).

### Slide 21b. Swarm architecture on Azure

**On slide:** The slide 4 architecture diagram again, now with callouts that build one at a time beside the sandboxes: **Disk image** (research-agent, built from ACR), **Egress** (Deny, except Foundry + App Insights), **Identity** (group identity signs Foundry calls), **Lifecycle** (one per question, deleted after), and **No volumes or snapshots** (results return via the tool call).

**Speaker notes:** Same picture as the start; now every piece on the right has a name. This is the transition from the Sandboxes deep dive back to the orchestration code.

### Slide 21c. Microsoft Agent Framework

**On slide:** Right after the Azure architecture. Tagline "Open-source SDK for building AI agents and multi-agent workflows" with Python, .NET, and Go (preview) pills, then four feature cards from the [overview](https://learn.microsoft.com/agent-framework/overview/), each with where this repo uses it:

* **🤖 Agents** (LLM plus tools and MCP servers, many providers): planner, researcher, reviewer, report writer.
* **🔀 Workflows** (graph-based paths connecting agents and functions): the swarm's parallel research waves.
* **🧰 Harness agent** (planning, todos, context compaction, file access, memory, tool approval): the standalone sandbox agent.
* **🔌 Integrations** (providers, services, tools, context providers, middleware, evaluation, observability): Foundry web search, OpenTelemetry tracing.

Links: [aka.ms/AgentFramework](https://aka.ms/AgentFramework) (redirects to the GitHub repo) and the overview. Deliberately leaves out the Semantic Kernel and AutoGen lineage.

### Slide 22. The swarm as a workflow graph

**Main point:** The whole swarm is one Agent Framework workflow. Show the graph first, then zoom into its parts.

**On slide:** Left, the `WorkflowBuilder` code from [orchestrator/agents/workflow.py](orchestrator/agents/workflow.py) (planner → each researcher → collector → reviewer, reviewer → planner or report_writer). Right, an SVG of the same graph: 🤖 planner, three `researcher_i` nodes marked "📦 in a sandbox", collector, 🤖 reviewer, 🤖 report_writer, with labels for fan-out, fan-in, the dashed plan edge to the collector, "gaps: one more wave", and "approved". Caption: one edge per researcher, so the branches run concurrently.

**Speaker notes:** Agent Framework's fan-out edge runner delivers messages one after another, so separate edges keep the branches concurrent. The planner → collector edge carries a `ResearchPlan` with the expected answer count.

### Slide 22b. Planner agent

**On slide:** Minimap with the planner highlighted, an abridged `PLANNER_INSTRUCTIONS` from [orchestrator/agents/planner_agent.py](orchestrator/agents/planner_agent.py), and the `Agent(...)` that uses it. Caption: each researcher only sees its own question, so every question has to stand on its own.

**Speaker notes:** The prompt also bans references like "the shortlist" or "the options". The output shape comes from a `ResearchQuestions` Pydantic model passed as `response_format` (structured outputs), so the prompt has no JSON instructions and `validate_questions` only checks the 4-6 count.

### Slide 22b2. Fan-out planned questions to research nodes

**On slide:** Minimap with the planner highlighted, and simplified `PlannerExecutor` code: run the agent, `self.agent.run(topic, options={"response_format": ResearchQuestions})` and `validate_questions(result.value)`, send a `ResearchPlan` to the collector, then one `AgentExecutorRequest` per question with `target_id=f"researcher_{i}"`.

**Speaker notes:** `ctx.send_message` sends a typed message along one of the executor's edges; `target_id` picks the connected executor, and the runtime calls that executor's handler whose parameter type matches (`ResearchPlan` → collector, `AgentExecutorRequest` → researcher). Messages sent in one step are delivered together in the next superstep, so all researcher branches start at once. On a follow-up wave the reviewer supplies the questions and the planner skips its agent.

### Slide 22c. Send each question to a sandbox

**On slide:** Minimap with the researcher row highlighted. Intro line: each researcher node passes the question directly to a sandbox and returns either the response or an error. Code: simplified `ResearcherExecutor` from [orchestrator/agents/workflow.py](orchestrator/agents/workflow.py).

**Speaker notes:** No LLM on the orchestrator side of a branch. An earlier version used a dispatcher agent whose only tool was `run_in_sandbox`; that cost a model call per question and could garble the JSON, so this repo (like upstream jkalis-MS/Agent-Fan-Out-ACA-Sandboxes) calls it directly.

### Slide 22d. Start sandbox with research agent and tools

**On slide:** Minimap with the researcher row highlighted, and the simplified `run_in_sandbox` lifecycle from [orchestrator/agents/sandbox_researcher.py](orchestrator/agents/sandbox_researcher.py): create, poll until done, collect, always delete.

**Speaker notes:** Inside the sandbox, `research-agent/app.py` runs the researcher agent with Foundry's hosted web search, reaching Foundry only through the egress rules and proxy-injected token. Real code tolerates transient poll errors and times out after 360 s. To let an agent decide when to use a sandbox, make `run_in_sandbox` an agent tool, or use the Sandboxes Agent Skill.

### Slide 22e. Research agent inside the sandbox

**On slide:** Minimap with the researcher row highlighted. The `ResearchFinding` Pydantic model (answer, sources, confidence) and the `Agent(...)` from [research-agent/app.py](research-agent/app.py): `FoundryChatClient`, short research instructions, the web search tool, and `run(question, options={"response_format": ResearchFinding})`.

**Speaker notes:** Search runs inside Foundry. The project client gets a placeholder credential that the egress proxy replaces. The Flask wrapper reports status and the result that `run_in_sandbox` polls for.

### Slide 22f. Collect answers for each wave

**On slide:** Minimap with the collector highlighted. Simplified `ResearchCollector`: a `set_plan` handler (from the planner) and a `collect_response` handler (from each researcher), both calling `release_if_ready`, which sends one `ResearchDossier` to the reviewer once every expected answer is in.

**Speaker notes:** Handlers are picked by message type; the plan and answers can arrive in either order. The dossier includes findings from earlier waves.

### Slide 22g. Reviewer agent: approve or research more

**On slide:** Minimap with the reviewer highlighted. The `ReviewDecision` Pydantic model (`status: Literal["approved", "needs_more_research"]`, rationale, follow-up questions), passed as `response_format`, then `validate_review_decision` and the routing: `FollowUpResearch` to the planner if more research is needed and waves remain, otherwise `ApprovedDossier` to the report writer.

**Speaker notes:** The agent decides; the code enforces `MAX_RESEARCH_WAVES = 2`, so after the second wave it always approves and notes limitations.

### Slide 22h. Report writer agent

**On slide:** Minimap with the report writer highlighted. `REPORT_WRITER_INSTRUCTIONS` (executive summary, themed findings, limitations, conclusion, cite sources, don't invent evidence) and `ctx.yield_output(result.text)`.

**Speaker notes:** `yield_output` returns results to the workflow's caller; the orchestrator streams the report (and the planner's questions and reviewer decisions) to the web UI.

### Slide 23b. Observability with OpenTelemetry (OTel)

**On slide:** Intro (OTel standardizes traces, metrics, and logs across languages and vendors), then three cards with examples from this swarm: **Traces** (`sandbox.create` → `research-agent.run` → `invoke_agent ResearchAgent`), **Metrics** (Agent Framework's `gen_ai.client.operation.duration` and `gen_ai.client.token.usage`, shortened), **Logs** (real orchestrator log lines).

### Slide 23c. OpenTelemetry GenAI semantic conventions

**On slide:** A real span from Application Insights for this swarm, `invoke_agent ResearchAgent` (26.6 s), with its `gen_ai.*` attributes: operation name, agent name, request model, tool definitions (web search), input tokens (22518), output tokens (2450). Link to [semantic-conventions-genai](https://github.com/open-telemetry/semantic-conventions-genai).

**Speaker notes:** The span also records system instructions and input/output messages (including web search calls) because `ENABLE_SENSITIVE_DATA` is on. Other operation names: `chat`, `execute_tool`.

### Slide 23d. Using OpenTelemetry with Agent Framework

**On slide:** `configure_azure_monitor(connection_string=...)` plus `enable_instrumentation()`, with two bullets: the same two calls run in the orchestrator and every sandbox; sandboxes need the connection string in their environment and the Application Insights endpoints in their egress policy.

**Speaker notes:** The orchestrator also instruments FastAPI and adds a custom `sandbox.create` span. `research-agent/app.py` disables certificate verification for `requests` because the egress proxy intercepts TLS (sample shortcut). Next slide: joining the two sides into one trace.

### Slide 24. Carry a trace across the sandbox boundary

**Slides / main idea:** Follow one request across the fan-out. Separate provisioning time from research/model time; show how to locate a slow or failed branch and verify cleanup.

**Code slide:** Show `_traceparent_env` from [orchestrator/sandbox_manager.py](orchestrator/sandbox_manager.py) and the corresponding trace-context extraction in [research-agent/app.py](research-agent/app.py). Explain how context crosses a sandbox boundary, then map the code to the parent/child spans in the captured trace. Keep exporter configuration in [orchestrator/observability.py](orchestrator/observability.py) available for the editor walkthrough.

**Speaker notes: the platform option.** This sample passes trace context and the Application Insights connection string into each sandbox itself. Sandboxes also offer a per-sandbox `telemetryConfig`, set at creation, that exports stdout/stderr, OpenTelemetry signals, metrics, and `NetworkEgressDecisions` to Log Analytics, Application Insights, or any OTLP backend, and injects `OTEL_EXPORTER_OTLP_ENDPOINT` into the sandbox. Mention it as the way to get sandbox logs and egress decisions into the same backend without wiring it yourself; don't claim the sample uses it.

### Slide 25. Demo: follow the distributed trace

**On slide:** Screenshot of an Application Insights transaction trace with overlapping researcher spans and a sandbox span expanded.

**Speaker notes:** Open Azure Monitor / Application Insights for the swarm run, inspect parallel branches and one sandbox's work, then verify deletion of the ephemeral sandboxes. Use a captured trace when telemetry ingestion is delayed. Optionally show the sandbox group's `RunningCores` metric in Azure Monitor rising during the fan-out and dropping back to zero after cleanup.

### Slide 27. Takeaways

**On slide:** Four cards, each with an icon and a red "Without" / green "With sandboxes" pair: **⚡ On-demand compute** (sub-second start, zero idle cost), **Explicit boundaries** (isolation, egress, identity, data), **Explicit lifecycle** (create, stop, resume, delete), **One trace** (across every sandbox). Replaces the old "Recap: where agent runtimes break" slide, which covered the same ground.

**Speaker notes:** Tie each card back to the runtime problems from the start: untrusted code, cold starts, runaway budgets, workspaces that vanish on restart, tooling stitched together by hand.

### Slide 28. Scenarios for sandboxes

**On slide:** Six use cases, one line each. Highlight the two this talk demonstrated (agent workflows and AI code execution) so the audience can map the rest to their own workloads.

| Use case | What Sandboxes provide |
|---|---|
| **Agent workflows** | Persistent, isolated workspaces that survive across task boundaries |
| **AI code execution** | Safely run LLM-generated code in isolated environments with instant startup |
| **Platform building** | Build your own platform on the same primitive powering Microsoft services (slide 6) |
| **Burst workloads** | Scale from zero to thousands of sandboxes in response to demand |
| **Secure multi-tenant compute** | Strong isolation for untrusted workloads from multiple tenants |
| **Interactive user sessions** | Give each user their own isolated compute environment |

**Speaker notes:** Keep this brisk (under a minute). The swarm is one instance of the first two rows; the same lifecycle, egress, and identity patterns carry over to the others.

### Slide 26b. Connecting sandboxes to your systems

**Why:** ACA team feedback. The swarm only sends results back over HTTP; connectors and triggers are the integrations that let sandboxes react to events and take actions. Present as a "you can also" in the wrap-up, right after "Scenarios for sandboxes": that slide covers which workloads fit, this one covers how sandboxes connect to events and services.

**On slide:** A flow: 📬 Event (new email or SharePoint upload) → ⚡ Trigger (runs a command or calls a port) → 📦 Sandbox (your agent does the work) → 🔌 Connector (Teams, SharePoint, Jira, GitHub, 100+ more). Two cards underneath:

* **Connectors:** attach once to the sandbox group; each sandbox opts in at create time. MCP connectors give agents tools to discover; API connectors give app code REST endpoints. The group's identity authorizes calls, so there are no OAuth flows or tokens in the sandbox.
* **Triggers (preview):** watch a connector event by polling on a schedule or by webhook; run a command in a sandbox or POST to a port on a long-lived sandbox; authenticate with a managed identity.

**Speaker notes:** Swarm idea: a Teams trigger could start a research run and a Teams or SharePoint connector could post the report back. Docs scenarios: email triage to a Teams channel, invoice extraction from SharePoint, an hourly SharePoint audit, a daily email digest. Not tried in this repo. Sources: [connectors](https://sandboxes.azure.com/docs/sandboxes/connectors), [triggers](https://sandboxes.azure.com/docs/sandboxes/triggers).

### Slide 29. Choose the execution surface

**On slide:** Compare ACA Apps, Jobs, dynamic sessions, and Sandboxes by workload and lifecycle, following the [Sandboxes overview](https://learn.microsoft.com/azure/container-apps/sandboxes-overview). Emphasize that the swarm uses an App for orchestration and Sandboxes for isolated research; a standalone sandbox does not require an ACA environment.

| Surface | Best for | Lifecycle |
|---|---|---|
| Apps | Long-running services and APIs | Continuous |
| Jobs | Scheduled or event-driven tasks | Run to completion |
| Dynamic sessions | Managed code execution; the platform hides the infrastructure | Pool-managed, ephemeral |
| Sandboxes | Programmable isolated compute that you control | Stateful: create, stop, resume, snapshot, delete |

**Speaker notes:** Rule of thumb from the docs: pick dynamic sessions for a managed experience that hides infrastructure, and Sandboxes when you need programmable control over images, networking, storage, and state. The docs have a longer dynamic sessions vs. Sandboxes table (access pattern, state, control, image model, storage, networking, SDKs) for questions.

The orchestrator stays a standard Container App, not a Container Apps Express app, because Express isn't compatible with `azd` yet. If asked why not Express, say so, and mention Express's own gains (under-a-minute provisioning, sub-second cold start) as one of the products built on Sandboxes (slide 6).

### Slide 30. Keep learning

**On slide:** Links: these slides (pamelafox.github.io/aca-sandboxes-multi-agent), the sample repo, the Sandboxes docs (Learn overview and sandboxes.azure.com/docs), the Sandboxes Agent Skill quickstart, Microsoft Agent Framework (aka.ms/AgentFramework), the OpenTelemetry GenAI semantic conventions, and the Azure portal.

**Speaker notes:** Start with one sandbox from the portal, CLI, or SDK without deploying the swarm; `create_sandbox.py` is the quickest path, and `azd up` deploys the whole swarm.

### Slide 31. Q&A

**On slide:** Questions, repo link, and portal URL. Reserve the final five minutes; do not spend Q&A time waiting for a demo to complete.

### Optional Slide B1. Demo: suspend and resume

**On slide:** Screenshot of the same small stateful process before suspension and after resuming, with visible continuity of state.

**Speaker notes:** Prepare and verify this demonstration separately. Show what memory-preserving resume adds beyond retaining files. Use up to the four-minute flex budget only if no earlier delays consumed it. This slide is not part of the 31-slide main count.

## Presenter notes

### Demo priorities

* **Must-have:** The working swarm, a close-up of one sandbox with a visible network boundary, and a distributed trace. These show the feature, explain it, and make its behavior inspectable.
* **Optional:** Suspend/resume a small stateful process to show what persistence adds beyond this repo's create-and-delete workflow. Cut this live segment first if time is tight.
* **Backup:** Capture the swarm run, active sandbox list, egress results, and trace ahead of time. Keep the same research question throughout so the audience follows one story.
* **Screenshots:** The first deck draft uses labeled placeholders for demo slides 3, 16, 25, and B1. Capture the real screenshots from portal.azure.com and Application Insights later.

### Code presentation guidelines

* Aim for roughly 8-15 readable lines per code slide, with one implementation decision to explain. Split initialization, execution, and cleanup instead of shrinking a complete function onto one slide.
* Use excerpts from the repo and link to their source. Label shortened snippets and name omitted setup; do not present fragments as standalone runnable examples.
* Alternate code with architecture, policy outcomes, or traces. Execution isolation, ingress, and snapshot concepts can stay diagram-led unless code materially clarifies them.
* Validate final excerpts and setup commands against the installed SDK version (`azure-containerapps-sandbox` 0.1.0b4) and deployed environment before the talk. Label SDK code slides "Python SDK (beta)", since stable SDKs arrive by Ignite (November 2026), after the service GA. Avoid showing private SDK calls such as `_dp_put` on slides; they may change before SDK GA. Do not imply that planned boundary demos or optional persistence examples already exist in the sample.

### Framing notes

* Sandboxes are generally available, except the [triggers](https://sandboxes.azure.com/docs/sandboxes/triggers) feature, which remains in preview. Triggers wake or invoke a sandbox when a connector event fires, such as a new email or a SharePoint upload. Present the service as GA; the Python SDK is still beta (see question 12). If triggers come up (for example in Q&A), label them preview. Don't confuse triggers with the network-traffic resume on slide 14, which is part of the GA lifecycle. Treat the [current Sandboxes overview](https://learn.microsoft.com/en-us/azure/container-apps/sandboxes-overview) as the source for limitations, and recheck feature status before presenting.
* Sub-second provisioning from prewarmed pools is not a promise of a sub-second research answer or first-time custom image preparation. Stopped sandboxes have no CPU/memory fees; avoid implying all storage or supporting services are free.
* Keyless here means no credential inside the sandbox at all: both the swarm and the standalone agent get Entra tokens for the sandbox group's managed identity injected by the egress proxy. Every sandbox in a group shares that identity's access.
* Borrow the runtime requirements and lifecycle demonstrations from the BRK221 talk, but leave its broader ACA/GPU tour and customer case study out of this talk. The swarm is the through-line here.
* "ADC" is the old name for Sandboxes. Say "Sandboxes" or "Sandboxes data plane" on slides and in speaker notes, even where older code, docs, or package names still use ADC.

## Open questions for the ACA team

Record each answer under its question, then update the affected slide and remove the matching "verify" note. **Status** is one of: Answered (docs or repo settle it), Partly answered (still needs team confirmation), or Open. As of September 25, all answers below are folded into the slide sections; remaining "Still ask" items are phrased conservatively on the slides and don't block slide creation.

Docs checked (September 2026): [overview](https://learn.microsoft.com/azure/container-apps/sandboxes-overview), [egress policies](https://learn.microsoft.com/azure/container-apps/sandboxes-egress-policies), [lifecycle](https://learn.microsoft.com/azure/container-apps/sandboxes-snapshots-state-management), [Bicep quickstart](https://learn.microsoft.com/azure/container-apps/sandboxes-quickstart-bicep), [CLI quickstart](https://learn.microsoft.com/azure/container-apps/sandboxes-quickstart-cli), [Python SDK quickstart](https://learn.microsoft.com/azure/container-apps/sandboxes-quickstart-python-sdk), [agent skill quickstart](https://learn.microsoft.com/azure/container-apps/sandboxes-quickstart-agent-skills), [get started](https://learn.microsoft.com/azure/container-apps/sandboxes-get-started). Portal docs at sandboxes.azure.com/docs (more detailed than Learn): [triggers](https://sandboxes.azure.com/docs/sandboxes/triggers), [lifecycle](https://sandboxes.azure.com/docs/sandboxes/sandbox/lifecycle), [sandboxes](https://sandboxes.azure.com/docs/sandboxes/sandboxes), [sandbox groups](https://sandboxes.azure.com/docs/sandboxes/sandbox-groups), [disk images](https://sandboxes.azure.com/docs/sandboxes/disk-images), [quotas and limits](https://sandboxes.azure.com/docs/sandboxes/limits), [ports](https://sandboxes.azure.com/docs/sandboxes/sandbox/ports), [egress](https://sandboxes.azure.com/docs/sandboxes/sandbox/egress), [egress webhook](https://sandboxes.azure.com/docs/sandboxes/sandbox/egress/webhook), [identity](https://sandboxes.azure.com/docs/sandboxes/identity), [secrets](https://sandboxes.azure.com/docs/sandboxes/secrets), [AI provider credentials](https://sandboxes.azure.com/docs/sandboxes/credentials), [snapshots](https://sandboxes.azure.com/docs/sandboxes/snapshots), [cost](https://sandboxes.azure.com/docs/sandboxes/cost), [logging](https://sandboxes.azure.com/docs/sandboxes/telemetry), [metrics](https://sandboxes.azure.com/docs/sandboxes/metrics). Repo checked: [infra/main.bicep](infra/main.bicep), [orchestrator/sandbox_manager.py](orchestrator/sandbox_manager.py), [create_sandbox.py](create_sandbox.py), [research-agent/app.py](research-agent/app.py).

### Highest priority (changes slide content)

1. **Credential injection (slide 19):** Does egress-proxy credential injection support short-lived Entra bearer tokens (as used for Foundry calls), or only stored secrets? Is there a sample? This decides whether the slide presents it as "the alternative" or "what we'd do next."
   * **Status:** Answered ([portal egress docs](https://sandboxes.azure.com/docs/sandboxes/sandbox/egress), [egress webhook docs](https://sandboxes.azure.com/docs/sandboxes/sandbox/egress/webhook), [identity docs](https://sandboxes.azure.com/docs/sandboxes/identity)).
   * **Answer:** Yes, injection supports Entra tokens. A `Transform` rule's header value can come from a static value, a group secret (`secretRef`), or a `managedIdentityRef` with a `resource` (token audience) and `type` (for example `SystemAssigned`). The token comes from the **sandbox group's** managed identity, so the sandbox code never holds it. Advanced rules (path/method matches, transforms, rewrites) are written as a YAML policy file and applied with `aca sandbox egress apply --file egress.yaml`. The SDK example only shows `EgressHostRule(pattern=..., action=...)`.
   * **Beyond static rules:** An egress **webhook** (`hookRef` on a rule) lets your own endpoint decide, transform, or rewrite each matching request at runtime. It receives the `sandboxId`, so it can do "runtime token minting" per sandbox or tenant. Note that a webhook response can only return literal header values, not secret or identity references.
   * **Slide 19 impact:** The repo now uses injection for both the swarm and the standalone agent. The group identity has the Foundry User and Cognitive Services OpenAI User roles; Transform rules on the Foundry and Azure OpenAI hosts add `Authorization` from a `managedIdentityRef` token; the orchestrator no longer forwards tokens.
   * **Verified in this repo:** The Python SDK supports `Transform` rules and `EgressManagedIdentityRef` directly (no YAML policy needed), and `identity_type="UserAssigned"` works with `identity_resource_id`.
2. **Per-sandbox managed identity (slide 19):** Can an individual sandbox get its own identity, or is identity only at the sandbox-group level? The plan currently says each researcher does not get a separate, less-privileged identity.
   * **Status:** Answered ([identity docs](https://sandboxes.azure.com/docs/sandboxes/identity)).
   * **Answer:** Identity is per sandbox group only: "Managed identity is the Azure trust anchor for a sandbox group." A group can have a system-assigned identity and user-assigned identities (`aca sandboxgroup identity assign --system-assigned` / `--user-assigned <id>`). There is no per-sandbox identity, so every sandbox in a group can obtain tokens with the group identity's permissions (through injection, not directly).
   * **Slide 19 impact:** State this plainly. The options for narrower access are separate sandbox groups per trust level, or an egress webhook that decides per `sandboxId`.
3. **Triggers:** What exactly is the triggers feature (still preview)? Is the "network traffic wakes a stopped sandbox" behavior on slide 14 part of triggers or part of GA ingress?
   * **Status:** Answered ([portal triggers docs](https://sandboxes.azure.com/docs/sandboxes/triggers), [portal lifecycle docs](https://sandboxes.azure.com/docs/sandboxes/sandbox/lifecycle)).
   * **What triggers are:** A trigger watches a connector event (a new Outlook email, a SharePoint upload, a Teams message, a GitHub PR) and wakes or invokes a sandbox when it fires. It either runs a command in the sandbox or calls a port on a long-lived sandbox. Triggers are created on a connector namespace (`az connector-namespace trigger create`). The namespace's managed identity authenticates the call to the sandbox, so there are no shared secrets. Triggers can be polling (with a recurrence schedule), webhook, or notification based. Runs are visible in the portal's Triggers tab or via `az connector-namespace trigger run list`.
   * **Network-traffic resume is not a trigger:** The portal lifecycle diagram shows "Network traffic or start command" resuming a stopped sandbox as part of the core lifecycle. Keep that arrow on slide 14 as GA.
   * **Not in this talk's scope:** Triggers could fit a Q&A answer about event-driven agents. The portal docs list samples such as per-email triage and SharePoint document automation. Always label triggers preview.
4. **Sub-second claims (slides 6 and 14):** What is the precise claim for create versus resume? Does it apply to prepared custom disk images, or only to public images like `ubuntu`?
   * **Status:** Partly answered.
   * **Docs:** "Sub-second startup: Sandboxes are provisioned from prewarmed pools" and "resume later with sub-second restore times." Nothing says whether prewarmed pools cover custom disk images.
   * **Portal docs add:** The [snapshot docs](https://sandboxes.azure.com/docs/sandboxes/snapshots) say "a restore needs a short warm-up," so don't claim create-from-snapshot is sub-second.
   * **Still ask:** Does sub-second start apply to sandboxes created from a prepared custom disk image? How long is the snapshot-restore warm-up?

### Networking

5. **Egress rule matching (slide 15):** How does the Layer 7 firewall match HTTPS hosts (SNI, or TLS inspection)? Can rules match paths or methods, or only hosts?
   * **Status:** Answered, plus a follow-up.
   * **Docs:** Rules match on **host, path, and HTTP method**. Actions are `Allow`, `Deny`, `Transform` (modify headers, such as injecting a token), and `Rewrite` (change destination scheme, host, or path). The first matching rule wins; otherwise the default action applies. Traffic inspection modes are `Full` (all traffic inspected, non-HTTP blocked), `Partial` (only rule-matching traffic inspected, non-HTTP allowed), `None`, and `Legacy`. CIDR-based network rules and VNet integration are also available. Policies can be updated on a running sandbox; the change applies to later requests.
   * **Repo:** [research-agent/app.py](research-agent/app.py) disables TLS certificate verification because the egress proxy intercepts TLS with a certificate the sandbox doesn't trust.
   * **Portal docs add:** [Egress policies are opt-in](https://sandboxes.azure.com/docs/sandboxes/sandbox/egress): "If no egress policy is specified, the sandbox has unrestricted outbound access." Slide 15 must say this, because default-deny is something you set, not the default. The portal and CLI set the policy with `aca sandbox egress set -l <selector> --default Deny --rule "*.github.com:Allow" --traffic-inspection Full`, or at create time with `--egress-default`, `--egress-rule`, and `--traffic-inspection`. Path/method rules need `Full` inspection.
   * **Follow-up:** Is there a proxy CA certificate to install in the disk image so code can keep TLS verification on? Otherwise a slide 15 audience member may ask why the sample uses `verify=False`. (The webhook's `trustedCa` field only adds trust for the proxy's connection to an upstream; it doesn't help code inside the sandbox trust the proxy.) Also reconcile wording: the source deck's anatomy slide labels the egress proxy "default on," but the docs say policies are opt-in. Presumably the proxy is always present and allows everything until a policy is set.
   * **Slide impact:** Slide 15 currently says "host-based rules." Update it to host, path, and method matching, and mention the inspection modes.
6. **Network Audit (slide 16):** Is the Network Audit data available via API or Azure Monitor logs, or only in the portal?
   * **Status:** Answered ([egress docs](https://sandboxes.azure.com/docs/sandboxes/sandbox/egress), [logging docs](https://sandboxes.azure.com/docs/sandboxes/telemetry), [metrics docs](https://sandboxes.azure.com/docs/sandboxes/metrics)).
   * **Answer:** The Azure portal's **Network audit** view shows each decision with host, timestamp, and outcome. The CLI returns the same data with `aca sandbox egress decisions -l <selector> [-o json]`, and the SDK with `sandbox.get_egress_decisions()` (separate `allowed` and `denied` lists with host, method, and path). For export, a sandbox's `telemetryConfig` can send `NetworkEgressDecisions` (plus stdout/stderr, OpenTelemetry signals, and metrics) to Log Analytics, Application Insights, or any OTLP backend. Telemetry is opt-in and set per sandbox at creation.
   * **Slide impact:** Slide 16 can show the portal view and mention the CLI/SDK call. Slide 24 (tracing) can mention `telemetryConfig` as the platform option. With it, the sandbox gets `OTEL_EXPORTER_OTLP_ENDPOINT` injected, so the repo wouldn't need to pass the Application Insights connection string into each sandbox. Azure Monitor also has group metrics (`SandboxGroup.RunningCores`, `SandboxGroup.RunningMemoryGiB`) and optional per-sandbox metrics (`properties.enableDetailedMetrics`), which help show the fan-out on slide 25.
7. **Ingress (slide 17):** What authentication options exist for an exposed port? Confirm that ports are off by default, and whether an exposed port is public or private.
   * **Status:** Mostly answered ([ports docs](https://sandboxes.azure.com/docs/sandboxes/sandbox/ports), plus the source deck's anatomy diagram).
   * **Answer:** Ingress is off by default and opt-in per sandbox and per port. Publishing a port gives it an HTTPS URL. The documented mode is an **anonymous** port, a public HTTPS route to a process listening inside the sandbox (bind to `0.0.0.0`). Commands: `aca sandbox port add -l <selector> --port 8080 --anonymous` and `aca sandbox port remove -l <selector> --port 8080`, or `sandbox.add_port(8080, anonymous=True)` and `sandbox.remove_port(8080)` in the SDK. Removing a port stops its URL immediately. The deck's diagram also shows ingress waking a stopped sandbox on request.
   * **Private ingress ([private endpoint docs](https://sandboxes.azure.com/docs/sandboxes/private-endpoints)):** Link the sandbox group to a Container Apps environment in `mode=Express` and add a private endpoint on that environment. Exposed port FQDNs then resolve to a private IP from your VNet, peered networks, VPN, or ExpressRoute. This changes ingress only; the group's `vnetConnections` still control egress. Default port URLs use `*.{region}.adcproxy.io`; linked groups use `*.{region}.azurecontainerapps.io`.
   * **Still ask:** The portal offers "Anonymous" as one access choice. What are the other choices, and how do callers authenticate to a non-anonymous port (Entra ID, the data-owner role)?
### Lifecycle, limits, and cost

8. **Disabled state (slide 14):** What causes a sandbox to become disabled (admin action, policy violation, quota)?
   * **Status:** Partly answered. The [portal docs](https://sandboxes.azure.com/docs/sandboxes/sandboxes) list three states: Running, Stopped, and Disabled ("Disabled sandboxes can't be started unless enabled"). Slide 14 can keep its Disabled line.
   * **Still ask:** What puts a sandbox into Disabled? Is reaching the "Sandbox Cores" quota one cause (see question 9)? The Learn lifecycle page also says Stopped "is distinct from **Suspended**" without defining Suspended. Ask the team to reconcile that wording.
   * **Checked September 29 (live API, westus group):** all 7 stopped sandboxes, including auto-suspended ones, reported `state: Stopped` with `stateDetails.stoppedReason: Idle`. None reported `Suspended`. The SDK (0.1.0b4) still lists `Suspended` in its state type hints (with transitional `Stopping`, `Resuming`, `Creating`, `Deleting`), and its `begin_stop()` poller accepts `Stopped`, `Suspended`, or `Idle`. It models `Disabled` as a stop reason (`Idle`, `UserStopped`, `Disabled`), not a separate state. Slide 16 now lists the stop reasons.
9. **Limits (slides 6 and 21):** What are the current size tiers (S/M/L) and the maximum sandboxes per group? Is there a per-subscription quota to cite alongside "zero to thousands"?
   * **Status:** Partly answered.
   * **Docs:** Five tiers: XS (0.25 cores, 0.5 GB, 20 GB disk), S (0.5, 1 GB, 20 GB), M default (1, 2 GB, 20 GB), L (2, 4 GB, 40 GB), XL (4, 8 GB, 80 GB). A group can set `maxSandboxCount`, `defaultTimeoutSeconds`, and default CPU/memory/disk in Bicep. That gives slide 21 a platform-level cap on fan-out.
   * **Quota ([portal docs](https://sandboxes.azure.com/docs/sandboxes/limits)):** The quota is **Sandbox Cores**: concurrent active cores per subscription and region, visible under Azure Container Apps in My quotas. An XS sandbox counts 0.25 cores and an XL counts 4. Stopped sandboxes don't count. Hitting the quota blocks creating new sandboxes or starting existing ones. API rate limits also apply (HTTP 429) and are raised through support. Slide 21 can cite the core quota as a platform backstop, alongside `maxSandboxCount` per group and the application's own fan-out cap.
   * **Still ask:** The typical default Sandbox Cores quota, so "zero to thousands" can be framed against it.
10. **Cost when stopped (slides 6 and 14):** What are the charges for stopped sandboxes, snapshots, and volumes beyond "no compute charges"?
    * **Status:** Answered ([cost docs](https://sandboxes.azure.com/docs/sandboxes/cost)).
    * **Answer:** Charges are vCPU per core-second and memory per GiB-second **while running** (rates on the Container Apps pricing page), plus storage per GB for as long as it's kept. Storage billing is "coming soon," at Premium Azure Blob ZRS rates. It covers custom disk images (one stored copy, however many sandboxes boot from it; the OS disk each sandbox runs on isn't billed), snapshots (including the ones taken automatically when a sandbox stops), and data disk and Blob volumes.
    * **Framing:** "No compute charges when stopped" is accurate. Don't say stopped sandboxes are free, because their automatic snapshots will be billed as storage.
11. **Snapshots (slides 20 and 26):** What are the retention and deletion rules? Does deleting a sandbox delete its snapshots? Can one memory snapshot be forked into many sandboxes?
    * **Status:** Mostly answered.
    * **Docs:** Snapshots are scoped to the sandbox group and its region, and exist independently of the source sandbox ("keep state after deleting the source sandbox"). One snapshot can fan out many new sandboxes, which inherit its CPU, memory, and disk (they can't be changed). Memory snapshots aren't available when a data-disk volume is attached (disk mode only). Auto-delete applies to stopped sandboxes. The docs tell you to clean up stale snapshots on a schedule, so there's no automatic snapshot retention. Deleting the sandbox group removes everything in it.
    * **Portal docs add ([snapshots](https://sandboxes.azure.com/docs/sandboxes/snapshots)):** Deleting a snapshot doesn't delete sandboxes already restored from it. Snapshots depend on the disk image they were created from. `aca sandbox snapshot -l <selector> --name <name>` and `aca sandbox create --snapshot <name>` are documented; so is `aca sandboxgroup snapshot list/get/delete`.
    * **Still ask:** Is there any snapshot retention policy or limit on snapshots per group? Can you delete a disk image that snapshots still depend on?

### Tooling and naming

12. **SDK (slides 10 and 13):** What is the GA SDK package name and version? Are `SandboxGroupClient`, `begin_create_sandbox`, and `EgressPolicy` unchanged from preview? Does the package still use "ADC" in any names?
    * **Status:** Answered (except the ADC naming question).
    * **Docs:** The package is `azure-containerapps-sandbox` (Python 3.13+ in the quickstart). The quickstart uses `SandboxGroupClient(endpoint_for_region(region), credential, subscription_id=..., resource_group=..., sandbox_group=...)`, `begin_create_sandbox(disk="ubuntu").result()`, `sandbox.exec(...)`, and `sandbox.delete()`. `SandboxGroupManagementClient` creates and deletes groups. `EgressPolicy` isn't in the quickstart.
    * **Naming:** The overview still labels the data plane "**ADC data plane**" (endpoint `management.azuredevcompute.io`), so ADC remains in public docs.
    * **Portal docs add:** An async client (`azure.containerapps.sandbox.aio.SandboxGroupClient`) with an `asyncio.gather` fan-out example. Lifecycle APIs: `sandbox.set_lifecycle_policy(LifecyclePolicy(auto_suspend=AutoSuspendPolicy(...), auto_delete=AutoDeletePolicy(...)))`, `sandbox.stop()`, `sandbox.resume()`, `sandbox.wait_for_running()`, and `sandbox.ensure_running()`. Also `begin_create_sandbox(..., labels=..., environment=...)`, `list_sandboxes(selector=...)`, and `list_public_disk_images()`. These support optional demo B1 (suspend and resume) and slide 21's auto-delete backstop.
    * **Repo gaps to raise:** (a) `create_disk_image()` doesn't expose `managedIdentityClientId`, and it drops labels other than `name`. [create_sandbox.py](create_sandbox.py) and [orchestrator/sandbox_manager.py](orchestrator/sandbox_manager.py) work around this with the private `_dp_put`. (b) Per the repo comments, group-level `imageRegistryCredentials` aren't applied automatically to disk-image pulls.
    * **Version (confirmed):** The Python SDK is [`azure-containerapps-sandbox` 0.1.0b4](https://pypi.org/project/azure-containerapps-sandbox/0.1.0b4/), a beta. Stable SDKs arrive by Ignite (November 2026), after the talk. The service is GA; the SDK isn't yet. The repo pins `==0.1.0b4`.
    * **Team guidance (confirmed):** Today there are Python and TypeScript beta SDKs, both updated in July. They target the `2026-02-01-preview` data plane, and they're the recommended path for now. A .NET beta SDK on the `2026-09-01-preview` data plane ships in a few weeks. By Ignite (November 2026), stable Python, JS/TS, .NET, and likely Java SDKs arrive, with migration guidance and a Copilot skill. The control plane (stable) and data plane (preview) ship as separate SDKs. Follow the [portal docs](https://sandboxes.azure.com/docs/sandboxes/) for the latest. Source: [microsoft/azure-container-apps#1839](https://github.com/microsoft/azure-container-apps/issues/1839#issuecomment-5821874629).
    * **Slide impact:** Slide 9 or 13 can say "Python and TypeScript SDKs (beta) today; .NET beta soon; stable SDKs by Ignite." Keep the Python excerpts on 0.1.0b4. Don't pass `api_version="2026-09-01-preview"` to the 0.1.0b4 client: several calls (create sandbox, write file, egress decisions, disk-image create) no longer match that spec.
    * **Still ask (low priority):** Whether the docs will drop "ADC."
13. **CLI (slide 9):** Are the `aca` CLI install URL and `sandboxgroup` / `sandbox` flags final for GA?
    * **Status:** Mostly answered.
    * **Docs:** Install with `curl -fsSL https://aka.ms/aca-cli-install | sh`, or `irm https://aka.ms/aca-cli-install-ps | iex` on Windows. Then run `aca sandboxgroup create -g <rg> --name <group> --location <region> -s <sub> --set-config`, check the setup with `aca doctor`, and use `aca sandbox create --disk ubuntu --label name=<name>`, `aca sandbox exec -l name=<name> -c "..."`, and `aca sandbox delete -l name=<name> --yes`.
    * **Portal docs add:** `aca sandbox lifecycle set --id <id> --auto-suspend enable --mode Memory --idle-timeout-seconds 60`, `aca sandbox stop`, `aca sandbox resume`, `aca sandbox list -l <selector>`, `aca sandbox init` / `aca sandbox apply --file sandbox.yaml` for YAML specs, `aca sandboxgroup disk create --image <oci-image>`, and `aca sandboxgroup role create` to grant the data-owner role. The docs also show parallel creation with background `aca sandbox create ... &` calls and `wait`.
    * **Still ask:** The quickstart shows version `1.0.0-preview.1`. What's the GA version? (`aca sandbox snapshot` is documented in the [snapshot docs](https://sandboxes.azure.com/docs/sandboxes/snapshots).)
14. **Agent Skill (slide 22):** What does the Agent Skill cover, and where do people get it?
    * **Status:** Answered ([quickstart](https://learn.microsoft.com/azure/container-apps/sandboxes-quickstart-agent-skills?tabs=copilot)).
    * **Install:** In GitHub Copilot CLI, `/plugin marketplace add microsoft/azure-container-apps` then `/plugin install sandboxes@Azure-Container-Apps`. Also available for Claude Code, or copy it into any agent's skills folder.
    * **Coverage:** Sandbox groups and sandboxes, exec and shell, egress policies, snapshot/stop/resume/commit, volumes, disk images, secrets and managed identity, and YAML sandbox specs.
    * **Source:** [microsoft/azure-container-apps/plugin](https://github.com/microsoft/azure-container-apps/tree/main/plugin).
15. **Portal screenshots:** Does sandboxes.azure.com still show a "PUBLIC PREVIEW" label? When is the GA UI live, so screenshots are captured from the right version?
    * **Status:** Answered. The talk uses the Azure portal (portal.azure.com), which now has the same Sandboxes features as sandboxes.azure.com. Capture all portal screenshots there. Still worth asking separately: the Learn lifecycle page is titled "(preview)" and says Sandboxes "are currently in preview." When will the docs be updated for GA?

### Positioning

16. **Execution surfaces (slide 29):** What is the official guidance on dynamic sessions versus Sandboxes? Is dynamic sessions being folded into Sandboxes?
    * **Status:** Mostly answered.
    * **Docs:** The overview compares Apps (long-running, continuous), Jobs (run-to-completion), dynamic sessions (managed code execution, pool-managed, ephemeral), and Sandboxes (programmable isolated compute that you manage, stateful). A separate table contrasts dynamic sessions and Sandboxes on access pattern, state, control, image model, storage, networking, and SDKs. The guidance: choose dynamic sessions for a managed experience that hides infrastructure, and Sandboxes for programmable control with state. Slide 29 can reuse this table.
    * **Still ask:** The docs position the two as separate products. Confirm nothing is changing.
17. **Foundation products (slide 6):** Are there approved one-line descriptions of how GitHub Copilot, Microsoft Foundry, Azure Container Apps Express, Azure SRE Agent, and Copilot Studio each use Sandboxes, in case of questions?
    * **Status:** Answered by the team, except Foundry (Pamela to write). The one-liners are in slide 6's speaker notes. Remaining unknown: whether Copilot triggered from Teams runs in the cloud sandbox.

### New questions from the docs and repo

18. **Keyless registry pulls for disk images (slide 12 notes):** [infra/main.bicep](infra/main.bicep) grants `AcrPull` to the sandbox group identity. But it also passes ACR admin credentials (`ACR_USERNAME` / `ACR_PASSWORD`) to the orchestrator, with a comment saying the compute plane "cannot yet authenticate ACR pulls with a managed identity." [orchestrator/sandbox_manager.py](orchestrator/sandbox_manager.py) tries admin credentials first, so the deployed swarm never takes its keyless path. [create_sandbox.py](create_sandbox.py) defaults to managed identity. At GA, can disk-image creation reliably pull from ACR with the group's managed identity, so the admin credentials can go? Until this is settled, don't claim the swarm's image pulls are keyless.
    * **Update:** The [portal disk-image docs](https://sandboxes.azure.com/docs/sandboxes/disk-images) list **Managed identity** as a registry authentication option, alongside no authentication and username/token. So managed-identity pulls are supported by the service.
    * **Update ([microsoft/azure-container-apps#1839](https://github.com/microsoft/azure-container-apps/issues/1839)):** On the `2026-02-01-preview` data plane that the SDK uses, managed-identity disk-image conversion (`managedIdentityClientId` / `managedIdentityResourceId`) still returns 401 `RegistryAuthFailed`. Only `2026-09-01-preview` (`POST {group}/diskimages` with `source.authentication.identity {type: UserAssigned, identityResourceId}`) honors a user-assigned identity, and no Python SDK targets that version yet. So the Bicep comment is accurate for SDK users today, and the admin-credential fallback has to stay until a newer SDK ships (or the repo calls the `2026-09-01-preview` REST API directly). Slide 14 should present keyless pulls as the target design, with admin credentials as a temporary fallback.
    * **Resolved (from Jan's upstream fix):** The disk-image API's **v2** endpoint (`PUT {group}/diskimages/v2` with `source: {kind: "registry", imageUrl, managedIdentityClientId}`) accepts managed-identity pulls. The repo now uses it in both the orchestrator and `create_sandbox.py`, and ACR admin credentials are disabled. Verified with a full swarm run and a standalone agent run.
    * **Still ask:** Whether group-level `imageRegistryCredentials` should apply to disk-image pulls automatically.
19. **GA API version (slides 8 and 18):** Both the repo and the docs use `Microsoft.App/sandboxGroups@2026-02-01-preview`. Is there a GA API version to switch to before the talk?
    * **Status:** Answered. Per [microsoft/azure-container-apps#1839](https://github.com/microsoft/azure-container-apps/issues/1839), the ARM control plane is stable at `Microsoft.App/sandboxGroups@2026-07-01`. The data plane is at `2026-09-01-preview`, but the SDKs still target `2026-02-01-preview`.
    * **Repo follow-up:** Decision: stay on `@2026-02-01-preview` for the talk, since upgrading requires re-verifying the deployment. Revisit after the talk.
20. **Role naming (slide 18):** The docs name role `c24cf47c-5077-412d-a19c-45202126392c` the built-in **Container Apps SandboxGroup Data Owner**. The Bicep comment calls it "Custom role: Dev Compute SandboxGroup Data Owner." Confirm the docs name is final. The repo comments and error message now use the docs name.

### Other doc findings useful for slides (not questions)

* **Copilot and Claude sandbox templates (slides 9, 15):** The portal's Create menu has **GitHub Copilot Sandbox** and **Claude Sandbox** templates besides **Standard Sandbox**. [AI provider credentials](https://sandboxes.azure.com/docs/sandboxes/credentials) (a GitHub fine-grained PAT or an Anthropic key) are stored on the group and injected when a sandbox starts. Unlike egress injection, these tokens land *inside* the sandbox, so slide 11's caveat applies to them.
* **Secrets aren't environment variables:** Group [secrets](https://sandboxes.azure.com/docs/sandboxes/secrets) are referenced from egress header transforms and telemetry authentication; they aren't injected as environment variables. This supports slide 19's "credentials stay outside the sandbox" story.
* **Documented fan-out pattern (slide 23):** The [sandboxes docs](https://sandboxes.azure.com/docs/sandboxes/sandboxes) show parallel creation with the async client and `asyncio.gather`, the same pattern this sample uses.
* **YAML specs:** `aca sandbox init` / `aca sandbox apply --file sandbox.yaml` for sandboxes, and `aca sandbox egress init/apply/export` for egress policies. These are useful if you want a declarative excerpt instead of SDK code.

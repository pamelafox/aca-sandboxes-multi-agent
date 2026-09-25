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
* Open sandboxes.azure.com
* Open Azure Monitor
* Create a standalone sandbox to dig into sandbox internals - prove it can't bust out, ala https://simonwillison.net/2026/Sep/4/rogue-agent-wikis/

## Demo prompt ideas

Gardening:

 optimal tree to plant for a native california garden for a lawn that faces north, has tough soil, and is near oak tree roots. tree cant grow more than 15 feet tall. tree is NOT shaded.

## Slide ideas

* Diagram of demo
* Section about sandboxing technology
* Network egress: Layer 7 firewall

## Proposed outline

Core story: **Agents need somewhere safe to act. ACA Sandboxes make that execution environment programmable, so a swarm can create one workspace per task and dispose of it when the work is done.**

**Current count: 29 main slides, including 4 demo screenshot slides and Q&A, plus 1 optional demo slide (B1).** Each numbered heading below represents exactly one slide. Reveals/fragments do not add to the count. Speaker notes, code sources, and ASCII prototypes describe the slide; they are not additional slides.

Use the research swarm as the running example, but make Sandboxes the subject. Connect architecture and security concepts to infrastructure definitions, SDK calls, and observed runtime behavior. Keep agent-framework mechanics brief.

**Hour budget:** Slides 1-2: 3 minutes; 3-4: 7 minutes; 5-6: 4 minutes; 7-14: 12 minutes; 15-22: 13 minutes; 23-24: 5 minutes; 25-26: 4 minutes; 27-28: 2 minutes. Reserve 5 minutes for demo delays or optional slide B1, and 5 minutes for Q&A on slide 29. These are rehearsal targets, including live demo time, not equal time per slide.

**Demo slide convention:** Slides 4, 14, 17, 26, and optional B1 each show a large screenshot of the actual demo, with a short title. The screenshot is the presenter cue to switch to the live application, terminal, or portal. Keep the runbook in speaker notes. Screenshot descriptions below are capture requirements, not claims that assets already exist.

### Slide 1. When One Agent Isn't Enough

**On slide:** Full talk title, presenter name, and a visual of parallel isolated workspaces. Briefly state that the session will go from a working swarm to the infrastructure and code behind it.

### Slide 2. One question, several independent research tasks

**Slides / main idea:** Introduce a research question with independent sub-questions. Fan-out helps, but now several agents need compute, permissions, and cleanup at once.

**Demo beat:** Preview the gardening question and the work it can split into.

### Slide 3. Swarm architecture: how the work flows and where it runs

**Slides / main idea:** One combined diagram answers "how does the work flow?" and "where does it run?" Reveal the hosting boundaries after introducing the agent workflow.

**ASCII prototype:** Three branches shown for readability; the sample supports up to six. Each researcher agent calls `run_in_sandbox`; the actual research process runs across that boundary in a separate sandbox.

```text
				 User question
					 |
					 v
+------------------------------------------+   +-------------------------------+
| AZURE CONTAINER APP                      |   | SANDBOX GROUP                 |
| Orchestrator                             |   | Management scope              |
|                                          |   |                               |
| Decomposer                               |   | +---------------------------+ |
|   |                                      |   | | ACA Sandbox 1             | |
|   +--> Researcher agent 1 --tool call-----|-->| | Research process          | |
|   |                       <--result------|---| +---------------------------+ |
|   |                                      |   |                               |
|   |                                      |   | +---------------------------+ |
|   +--> Researcher agent 2 --tool call-----|-->| | ACA Sandbox 2             | |
|   |                       <--result------|---| | Research process          | |
|   |                                      |   | +---------------------------+ |
|   |                                      |   |                               |
|   |                                      |   | +---------------------------+ |
|   +--> Researcher agent 3 --tool call-----|-->| | ACA Sandbox 3             | |
|                           <--result------|---| | Research process          | |
|                                          |   | +---------------------------+ |
| Returned researcher results              |   |                               |
|   |                                      |   | Each sandbox has its own      |
|   v                                      |   | execution boundary.           |
| Collector (fan-in) --> Synthesizer        |   |                               |
+-----------------------------|------------+   +-------------------------------+
					|
					v
				 Final report

Tool-call lifecycle: create sandbox -> run research -> collect result -> delete
```

The three branches run concurrently. Results return to their researcher agents, then flow through the collector to the synthesizer. The sandbox group is a management scope, not a shared execution environment or a network hop. Tool-call arrows summarize the SDK lifecycle, not a direct model-to-sandbox connection.

**Possible progressive reveal (or Reveal.js fragments):**

1. **The work:** Question, decomposer, parallel research branches, fan-in, and report. Introduce the problem before naming supporting Azure services.
2. **Where it runs:** Add the Container App and sandbox group outlines, individual sandbox boundaries, and the researcher-agent versus research-process labels. This is the combined view to leave visible before the live demo.
3. **How it is supplied and connected:** Reuse the same layout later with the supporting relationships below. Distinguish image preparation, service calls, and telemetry from the main task-flow arrows.

```text
ACR OCI image --> sandbox disk image --> new researcher sandboxes

Orchestrator -------- model calls --------> Azure OpenAI / Foundry
Sandbox researchers - model/search calls -> Foundry
							 |
							 +--> hosted web search

Orchestrator + sandbox researchers -- telemetry --> Application Insights
```

Keep the supporting-services layer out of the initial reveal. On slides 16 and 20, highlight egress and identity on the service-call arrows; on slides 23-24, map the tool lifecycle to SDK code; on slides 25-26, trace the same route in Application Insights. Keep component positions stable across these versions so the audience can follow the additions.

### Slide 4. Demo: the research swarm

**On slide:** Screenshot of the swarm UI with the gardening question and parallel researcher progress visible.

**Demo 1: End-to-end swarm.** Submit the question, show concurrent progress, and inspect the resulting report. Briefly show the live sandboxes in the portal while they exist.

**Speaker notes:** Start the run early and explain progress while it works. Keep a completed report and captured sandbox list ready rather than waiting silently for the live run.

### Slide 5. Why give an agent a sandbox?

**On slide:** Untrusted code needs a boundary beyond a prompt. Contrast shared-process/container execution with hardware-isolated compute, and explain the operational work of managing a VM per task.

**Demo beat:** Transition from the finished report to the question: where did that work actually run?

### Slide 6. Choose the execution surface

**On slide:** Compare ACA Apps, Jobs, dynamic sessions, and Sandboxes by workload and lifecycle. Emphasize that the swarm uses an App for orchestration and Sandboxes for isolated research; a standalone sandbox does not require an ACA environment.

### Slide 7. Meet ACA Sandboxes

**Slides / main idea:** A compact mental model: sandbox group, disk image, sandbox. Cover prewarmed startup, explicit lifecycle control, and scale-out. OCI images let you bring the code and dependencies your agent needs.

**On slide:** A compact lifecycle visual, not a live demo yet. The standalone demo follows the resource and SDK slides on slide 14.

### Slide 8. Two ways to try one sandbox

**Quick-start option:** Go to [sandboxes.azure.com](https://sandboxes.azure.com) for a quick, one-click setup experience to try Sandboxes. Mention the Entra sign-in and Azure access prerequisites; verify the current portal flow before the talk rather than implying the click bypasses authentication or permissions.

**Code slide:** For programmatic control, show the standalone setup steps from [README.md](README.md) and [create_sandbox.py](create_sandbox.py): install the SDK dependencies, authenticate, and select the subscription, resource group, sandbox group, and region. Use isolated Azure CLI configuration for the local demo. A public image is enough to create a sandbox and run a command; no swarm deployment is required.

**Speaker notes:** This is a setup slide, not a separate portal demo. The actual standalone demo is slide 14. Keep image preparation out of the live waiting time. Save `azd up` and the full swarm deployment in [azure.yaml](azure.yaml) for slide 24.

### Slide 9. Resource diagram: one group, one sandbox

**On slide:** The opening diagram explains the swarm; this resource diagram deliberately strips that away to explain general sandbox setup.

```text
Azure resource group
|
+-- Sandbox group                              [ARM: portal or Bicep]
	|
	+-- One sandbox                          [data plane: portal or SDK]
		Files, processes, and commands
		Optional: sandbox-agent harness

Local script -- SDK create / execute / delete --> One sandbox
Image source: public image OR a prepared custom disk image
```

No Container Apps environment, deployed Container App, or swarm orchestrator is required for this standalone setup. The sandbox group is the ARM management scope; the sandbox is a group-scoped data-plane object, not a Bicep-declared child resource. Leave model services, monitoring, and detailed RBAC off this resource map until their slides; running an AI agent adds its own model-access requirements.

### Slide 10. Bring your agent image

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

### Slide 11. Bicep: Sandbox group <-> ACR

**Layout:** A small Sandbox group <-> ACR relationship diagram above two code columns, with an RBAC excerpt revealed below them. This slide covers the custom private-image path; ACR remains optional for public-image experiments.

```text
					Sandbox group <---------- image pull ----------> ACR

	LEFT: sandboxGroup Bicep                 RIGHT: acr Bicep
	Name and region                         Name and region
	Attached managed identity               Registry SKU
	Registry server + pull identity         Registry configuration

	BELOW: sandboxGroupAcrPull role-assignment Bicep
	Principal: sandboxGroupUami.properties.principalId
	Role: AcrPull                           Scope: acr
```

**Left column:** Show `sandboxGroup` from [infra/main.bicep](infra/main.bicep), including its user-assigned identity and `imageRegistryCredentials`. Highlight `acr.properties.loginServer` and `sandboxGroupUami.id`. Identify `sandboxGroupUami` as a separately declared managed identity; keep its declaration available in the editor rather than silently implying the group creates it.

**Right column:** Show the `acr` resource from the same template. Line up the registry name/configuration with the left column's registry reference. Omit unrelated template resources, and label the snippets as excerpts rather than a complete deployment.

**RBAC reveal:** Show `sandboxGroupAcrPull` beneath the columns. Highlight `scope: acr`, `principalId: sandboxGroupUami.properties.principalId`, and the role definition referenced by `acrPullRoleId` (AcrPull). Explain that attaching an identity and configuring a registry reference do not grant access by themselves; this assignment authorizes the image pull. The diagram's two-way connector represents a pull request and image response, not mutual permissions.

**Presentation pacing:** Reveal the two resource declarations first, then replace the code area with an enlarged RBAC excerpt while retaining the diagram. Count this as one slide with builds, not an unnumbered extra slide. Do not include the ACA environment here.

The caller's separate permission to create/manage sandboxes is a different role assignment, covered on slide 19. These excerpts come from the larger swarm template, but the relationship applies equally to one sandbox running the standalone agent.

**Speaker notes: provisioning versus runtime operations**

**Key distinction:** In the current preview, the declarative ARM resource is `Microsoft.App/sandboxGroups`. Individual sandboxes are managed through the ADC data plane, not declared as individual Bicep resources. This is a platform API distinction, not just our choice to create them dynamically. See the [documented two-plane architecture](https://learn.microsoft.com/en-us/azure/container-apps/sandboxes-overview#architecture).

**Bicep / ARM:** Provision the group and role assignments, plus registry and identity resources when needed for the custom-image path.

**SDK / ADC data plane:** Select a public image or prepare a custom disk image, create one sandbox with its resources and policies, execute work, retrieve output, and delete it. The SDK caller can be a local script; it does not have to be a hosted orchestrator. Snapshots, volumes, files, and ports also belong to the data plane.

**Transition:** "We have provisioned the group and authorized its private-image pulls. With our caller's sandbox-management permission in place, let's create one with the SDK." Revisit caller authorization on slide 19, separately from the AcrPull assignment shown here. A deployment script could invoke data-plane operations during deployment, but that would still be imperative API work, not a native sandbox resource declaration.

### Slide 12. SDK: connect to the sandbox group

**Code:** Show `DefaultAzureCredential` and `SandboxGroupClient` initialization from [create_sandbox.py](create_sandbox.py). Identify the regional endpoint, subscription, resource group, and sandbox group. Explain that creating a client does not create a sandbox.

### Slide 13. SDK: create a sandbox and execute a command

**Code:** Shortened creation excerpt; `group` is the client initialized on slide 12:

```python
sandbox = group.begin_create_sandbox(
	disk="ubuntu",
	cpu="500m",
	memory="1Gi",
	auto_suspend_seconds=300,
	egress_policy=EgressPolicy(default_action="Deny"),
).result()
```

Explain the long-running operation's `.result()`, the built-in disk image, resource allocation, and explicit default-deny policy. Then show the script's `sandbox.exec(args.command)` call and its optional `--delete-after-run` cleanup. This is a creation excerpt, not a complete runnable script; show client lifetime management in the source walkthrough.

### Slide 14. Demo: one sandbox, one agent

**On slide:** Screenshot of the standalone sandbox's terminal with sandbox-agent output and its sandbox identifier visible. Do not include credentials.

**Speaker notes:** Create a sandbox through the SDK, inspect it at sandboxes.azure.com, run a command, and inspect files and processes. Use the prepared sandbox-agent disk image to run the agent. Keep the workspace available for the egress demo on slide 17; demonstrate cleanup after the last use. Have a captured terminal session ready if the live run fails.

### Slide 15. Execution isolation: what can this code affect?

**Section approach:** The next slides answer separate boundary questions. Reuse the architecture diagram, highlighting the relevant boundary. Slide 22 covers operational limits, not another isolation mechanism.

* Explain the hardware-isolated execution boundary between the researcher, other sandboxes, and the host. Contrast it with processes sharing a kernel in ordinary containers.
* Keep the trusted orchestrator outside the researcher's execution environment. One task gets one workspace rather than sharing the orchestrator's filesystem and process space.
* Isolation does not make generated code correct or harmless to files and credentials deliberately placed inside its own sandbox.

**Visual / demo beat:** Show two sandboxes with separate files and processes. Treat this as an illustration of separation, not proof that escape is impossible.

### Slide 16. Network egress: where can this code connect?

* Dedicate this slide to outbound traffic: start with default-deny, then allow only the destinations the workload needs.
* Explain the Layer 7 firewall and host-based rules. Show the actual policy for model/service endpoints and Application Insights telemetry; distinguish these from unrestricted internet access.
* Foundry-hosted search happens outside the sandbox. The sandbox contacts Foundry, not each website being searched.
* An allowed destination is still a possible path for data to leave. Egress restrictions do not validate every request or make every allowed service safe.

**Speaker notes:** Explain the policy here; switch to the live test on slide 17.

**Code slide:** Extract `_build_egress_policy` from [orchestrator/sandbox_manager.py](orchestrator/sandbox_manager.py), focusing on `EgressHostRule`, the allowed endpoint hosts, and `EgressPolicy(default_action="Deny", host_rules=host_rules)`. Show where that policy is attached during sandbox creation. Keep the longer telemetry-endpoint parsing logic in the editor, not on the slide.

### Slide 17. Demo: allowed and blocked network requests

**On slide:** Screenshot of terminal output showing an allowed request and a blocked request, with the destination hosts visible and no credentials.

**Speaker notes:** Run both requests in the standalone sandbox under the prepared egress policy and inspect the rules that explain the outcomes. Capture the expected results ahead of time. This demonstrates those rules, not universal protection against exfiltration or sandbox escape.

### Slide 18. Network ingress: who can reach a service inside?

* Running a server inside a sandbox and exposing its port are separate decisions. Outbound permission does not imply inbound access.
* Explain explicit port exposure and the authentication configured for that endpoint. Do not equate "has a URL" with "publicly accessible" or "authenticated."
* Expose only what the workflow needs, and treat the application listening on the port as an additional security responsibility.

**Visual / demo beat:** Trace a caller through an exposed port to the sandbox process, showing where authentication is enforced. Keep this diagram-only unless an interactive server is part of the standalone demo.

### Slide 19. Identity and RBAC: who can manage sandboxes?

**On slide:** Separate the caller's sandbox-management permission from the group's registry-pull identity. Show the `orchestratorSandboxDataOwner` role assignment from [infra/main.bicep](infra/main.bicep), highlighting principal, role, and `scope: sandboxGroup`. For the standalone script, explain that its caller also needs sandbox-management authorization. Refer back to AcrPull on slide 11 without repeating that code.

### Slide 20. Keyless model access: what may the agent do?

* Separate permission to manage sandboxes from permission to call a model or access data. Explain Entra ID, managed identity, and scoped Azure RBAC assignments.
* Show this repo's actual credential flow: the orchestrator acquires short-lived bearer tokens and forwards them into the researcher sandbox. Keyless does not mean credential-free.
* Tokens carry the issuing identity's granted access; creating a separate sandbox does not automatically create a separate, less-privileged identity for each researcher.
* Network rules decide whether a service is reachable. Authorization decides which operations the caller may perform there. Both are needed.

**Visual / demo beat:** Draw the token flow and permission scopes without displaying token values. Emphasize that code inside the sandbox can use credentials supplied to it.

**Code:** Show token acquisition in `get_foundry_token` and the environment-variable handoff in `create_sandbox` from [orchestrator/sandbox_manager.py](orchestrator/sandbox_manager.py) as successive builds on this slide. Keep management permission and downstream service permission visually separate; show code, never token values.

### Slide 21. Workspace data: what is private, shared, or retained?

* Start with a task-local filesystem. Mounting a shared volume or copying results out deliberately crosses that boundary.
* Treat disk images as trusted starting points: preload code and dependencies, not credentials or another task's private data.
* Snapshots and persistent volumes can retain sensitive state beyond a process's lifetime. Memory snapshots can also preserve in-process credentials.
* Stopping or deleting a sandbox is not a blanket retention policy for separately retained snapshots, volumes, exported results, or logs.

**Visual / demo beat:** Label task-local files, explicitly shared storage, and exported research results. Mark volumes and snapshots as platform options, not features demonstrated by the current disposable swarm.

**Speaker notes:** Refer back to the image pipeline on slide 10 rather than adding another Dockerfile slide. Keep [research-agent/Dockerfile](research-agent/Dockerfile) and `prepare_disk_image` in [orchestrator/sandbox_manager.py](orchestrator/sandbox_manager.py) available for questions about the swarm's image caching.

### Slide 22. Resource and lifecycle limits: how much can it consume?

* Bound CPU, memory, and disk allocations per sandbox; separately bound fan-out, execution time, and retries in the application.
* Explain cleanup on success and failure, plus lifecycle policies as a backstop. Distinguish auto-suspend from a hard execution deadline.
* Compute isolation and scale-to-zero do not cap model tokens, external API spending, or the total number of sandboxes an authorized orchestrator can create.

**Visual / demo beat:** Show the lifecycle with its concurrency cap, timeout, and cleanup points. Return to actual deletion and timing evidence in the observability section.

**Code excerpt:** Reuse the SDK resource and auto-suspend arguments from slide 13, then show the cleanup path in [create_sandbox.py](create_sandbox.py). Explain the distinction between closing the client and deleting the remote sandbox. Verify the current script's cleanup options before finalizing the excerpt.

### Slide 23. Turn compute into an agent tool

**Slides / main idea:** Return to the architecture with the trust boundaries labeled: ACA hosts the orchestrator; Sandboxes host researchers. Show the small lifecycle behind `run_in_sandbox`: create -> execute -> collect result -> delete.

**Demo beat:** Brief code walkthrough of the tool and custom disk image setup. Explain how Foundry-hosted search works without opening sandbox egress to the whole internet.

**Code reveal 1: Define the Agent Framework agent.** Show the `Agent(...)` construction in [orchestrator/agents/researcher_agent.py](orchestrator/agents/researcher_agent.py), highlighting `client=build_chat_client()`, `instructions=RESEARCHER_INSTRUCTIONS`, `name=agent_id`, and `tools=[run_in_sandbox]`. Explain how the model client, instructions, and registered tool come together: the agent can request sandbox execution because the application explicitly exposes that capability as a tool. Registering the tool does not itself create a sandbox.

**Code reveal 2: Implement the tool.** Replace the agent-definition excerpt with successive lifecycle-sized excerpts of `run_in_sandbox`: create -> execute -> collect result -> delete. Connect the registered tool name to the implementation and show how its result returns to the agent. Keep full error-handling and cleanup paths in speaker notes or the editor. Refer back to the image and egress slides instead of explaining those again.

**Presentation pacing:** Both reveals belong to slide 23; no additional slide. Keep the researcher agent in the orchestrator visually distinct from the research process it launches inside the sandbox. Slide 24 then shows how these agents are wired into the workflow.

### Slide 24. Wire the parallel swarm

**Code:** Show the fan-out and collector/fan-in construction in [orchestrator/agents/workflow.py](orchestrator/agents/workflow.py), mapping the code to the architecture arrows from slide 3. Explain how concurrent branches return results for synthesis.

**Speaker notes:** This is where the full deployment adds an ACA environment and orchestrator Container App. Briefly point to `azd up` and [azure.yaml](azure.yaml) for provisioning, image builds, and deployment; do not run a deployment on stage. The standalone setup remains independent of that larger stack.

### Slide 25. Carry a trace across the sandbox boundary

**Slides / main idea:** Follow one request across the fan-out. Separate provisioning time from research/model time; show how to locate a slow or failed branch and verify cleanup.

**Code slide:** Show `_traceparent_env` from [orchestrator/sandbox_manager.py](orchestrator/sandbox_manager.py) and the corresponding trace-context extraction in [research-agent/app.py](research-agent/app.py). Explain how context crosses a sandbox boundary, then map the code to the parent/child spans in the captured trace. Keep exporter configuration in [orchestrator/observability.py](orchestrator/observability.py) available for the editor walkthrough.

### Slide 26. Demo: follow the distributed trace

**On slide:** Screenshot of an Application Insights transaction trace with overlapping researcher spans and a sandbox span expanded.

**Speaker notes:** Open Azure Monitor / Application Insights for the swarm run, inspect parallel branches and one sandbox's work, then verify deletion of the ephemeral sandboxes. Use a captured trace when telemetry ingestion is delayed.

### Slide 27. Beyond disposable tasks: suspend and resume

**On slide:** A before/after visual explaining disk-only versus memory-and-disk suspend, resume, and snapshots for reusable starting points. This is a platform capability beyond the current create-and-delete swarm.

**Speaker notes:** Stay conceptual in the main deck. Only jump to optional demo slide B1 if time remains; return to slide 28 afterward.

### Slide 28. Takeaways and getting started

**On slide:** One task, one bounded workspace, explicit lifecycle, one trace. Link to the repo, [Sandboxes docs](https://learn.microsoft.com/en-us/azure/container-apps/sandboxes-overview), and [sandboxes.azure.com](https://sandboxes.azure.com). Remind the audience they can start with one sandbox without deploying the swarm.

### Slide 29. Q&A

**On slide:** Questions, repo link, and portal URL. Reserve the final five minutes; do not spend Q&A time waiting for a demo to complete.

### Optional Slide B1. Demo: suspend and resume

**On slide:** Screenshot of the same small stateful process before suspension and after resuming, with visible continuity of state.

**Speaker notes:** Prepare and verify this demonstration separately. Show what memory-preserving resume adds beyond retaining files. Use up to the five-minute flex budget only if no earlier delays consumed it. This slide is not part of the 29-slide main count.

## Presenter notes

### Demo priorities

* **Must-have:** The working swarm, a close-up of one sandbox with a visible network boundary, and a distributed trace. These show the feature, explain it, and make its behavior inspectable.
* **Optional:** Suspend/resume a small stateful process to show what persistence adds beyond this repo's create-and-delete workflow. Cut this live segment first if time is tight.
* **Backup:** Capture the swarm run, active sandbox list, egress results, and trace ahead of time. Keep the same research question throughout so the audience follows one story.

### Code presentation guidelines

* Aim for roughly 8-15 readable lines per code slide, with one implementation decision to explain. Split initialization, execution, and cleanup instead of shrinking a complete function onto one slide.
* Use excerpts from the repo and link to their source. Label shortened snippets and name omitted setup; do not present fragments as standalone runnable examples.
* Alternate code with architecture, policy outcomes, or traces. Execution isolation, ingress, and snapshot concepts can stay diagram-led unless code materially clarifies them.
* Validate final excerpts and setup commands against the installed preview SDK and deployed environment before the talk. Do not imply that planned boundary demos or optional persistence examples already exist in the sample.

### Framing notes

* Treat the [current Sandboxes overview](https://learn.microsoft.com/en-us/azure/container-apps/sandboxes-overview) as the source for feature status and limitations. The service is documented as preview; recheck before presenting.
* Sub-second provisioning from prewarmed pools is not a promise of a sub-second research answer or first-time custom image preparation. Stopped sandboxes have no CPU/memory fees; avoid implying all storage or supporting services are free.
* Keyless does not mean credential-free: this repo's orchestrator forwards short-lived Azure bearer tokens into the researcher sandbox. Explain the scope and exposure rather than suggesting every sandbox directly authenticates through managed identity.
* Borrow the runtime requirements and lifecycle demonstrations from the [annotated BRK221 talk](presentations/BRK221/outputs/writeup.md), but leave its broader ACA/GPU tour and customer case study out of this talk. The swarm is the through-line here.
## Slide 1

![Slide 1](slide_images/slide_1.png)

```
Idea to Production-Ready Agent in
Seconds on AI-native Runtime
   Devanshi Joshi
   Senior Product Marketing Manager, Azure
   Simon Jakesch
   Principal Product Manager, Azure Container Apps
   Gopi Prashanth
   Chief AI & Agents Office, Auger
```

## Slide 2

![Slide 2](slide_images/slide_2.png)

```
Why agents break between demo and
         production



         Live demo: Code to production-ready
         agent in seconds


Agenda   How Azure Container Apps delivers the
         agent runtime



         Customer spotlight: Auger’s autonomous
         supply chain on Azure
```

## Slide 3

![Slide 3](slide_images/slide_3.png)

```
40%
                        of agentic AI projects
                           will be canceled
                                by 2027.
                           Source: Gartner, June 2025




Not because the models can’t reason. Because the runtime can’t keep up.
```

## Slide 4

![Slide 4](slide_images/slide_4.png)

```
40%
                        of agentic AI projects
                           will be canceled
                                by 2027.
                           Source: Gartner, June 2025




Not because the models can’t reason. Because the runtime can’t keep up.
```

## Slide 5

![Slide 5](slide_images/slide_5.png)

```
Five Places The Runtime Breaks




  Budgets      Untrusted    Cold starts that   Workspaces      Tooling stitched
 that burn     code on a     throttle the       that die on      together by
unattended    developer’s        loop          every restart         hand
                 laptop
```

## Slide 6

![Slide 6](slide_images/slide_6.png)

```
Five Places The Runtime Breaks




  Budgets      Untrusted    Cold starts that   Workspaces      Tooling stitched
 that burn     code on a     throttle the       that die on      together by
unattended    developer’s        loop          every restart         hand
                 laptop
```

## Slide 7

![Slide 7](slide_images/slide_7.png)

```
Five Things The Runtime Has To Do




Fast startup        Execute agent      Persist and       Strong isolation        Secure by
and resume           tool calling     restore state       per agent task          default



Agents remain       And untrusted        Support         Prevent cross-task     Enforced at the
responsive and       code, safely   long-running agent      data leakage      runtime boundary
    reliable                            workflows
```

## Slide 8

![Slide 8](slide_images/slide_8.png)

```
Five Things The Runtime Has To Do




Fast startup        Execute agent      Persist and       Strong isolation        Secure by
and resume           tool calling     restore state       per agent task          default



Agents remain       And untrusted        Support         Prevent cross-task     Enforced at the
responsive and       code, safely   long-running agent      data leakage      runtime boundary
    reliable                            workflows
```

## Slide 9

![Slide 9](slide_images/slide_9.png)

```
Demo Scenario
                                                                                       aka.ms/aca/build2026-brk221




        Container Apps
        Environment



                                                     Whisper                      Kokoro
                         Multi Agent Broker



        Container Apps                                         Sandbox Group
        Express
                                                                               Sandbox: Aria
                                        Agent Aria
                                         Bridge                                      Copilot CLI


                                       Agent Nova                              Sandbox: Nova
                                         Bridge
                                                                                     Copilot CLI

Phone

          Call Gateway                                                         Azure SRE Agent
```

## Slide 10

![Slide 10](slide_images/slide_10.png)

```
Demo

How Container Apps Cleared
Every Runtime Hurdle                                                                        aka.ms/aca/build2026-brk221




Summary
                    One platform for apps, MCP tools, and ephemeral compute

            Sub-second cold start                                       Express & Sandbox prewarmed pools

           Strong per-task isolation                                         Code execution in Sandbox

          Persistent agent workspace                                             Sandbox snapshots

                Massive burst                                  Auto scale-out to thousands of concurrent sandboxes

                Cost effective                                                 Scale to zero when idle

               GPU on demand                                               Serverless GPUs for inferencing

             Zero infra decisions                                        Opinionated defaults with Express

                              One platform for apps, MCP tools, and ephemeral compute
```

## Slide 11

![Slide 11](slide_images/slide_11.png)

```
Demo

How Container Apps Cleared
Every Runtime Hurdle                                                                        aka.ms/aca/build2026-brk221




Summary
                    One platform for apps, MCP tools, and ephemeral compute

            Sub-second cold start                                       Express & Sandbox prewarmed pools

           Strong per-task isolation                                         Code execution in Sandbox

          Persistent agent workspace                                             Sandbox snapshots

                Massive burst                                  Auto scale-out to thousands of concurrent sandboxes

                Cost effective                                                 Scale to zero when idle

               GPU on demand                                               Serverless GPUs for inferencing

             Zero infra decisions                                        Opinionated defaults with Express

                              One platform for apps, MCP tools, and ephemeral compute
```

## Slide 12

![Slide 12](slide_images/slide_12.png)

```
Introducing in Public Preview



      Azure Container Apps Sandboxes
      Fast, isolated and stateful compute infrastructure on demand
Execute Securely by Default                Resume Instantly                            Burst to hyperscale
    Sandbox isolation for any       Preserve every interaction with trusted   Spin up in sub-second time, scale from zero to
      untrusted workload                      enterprise controls                   thousands, pay nothing when idle



                                        Foundation layer for




                                         aka.ms/aca/sandboxes
```

## Slide 13

![Slide 13](slide_images/slide_13.png)

```
With Azure Container Apps sandboxes, SitecoreAI can safely enable agents to take real action. The combination of multi-tenant
isolation, rapid scale-out, and full automation allows Sitecore to run long-lived, autonomous agents that securely execute code,
manage workflows, and interact with enterprise systems within secure, governed environments.
With this foundation, we can build agents that do real work – assembling content, personalizing experiences, and optimizing
campaigns in production. Agents that operate continuously, learn from results, and improve over time, so our customers get
better outcomes without giving up control."
                                                                                                        Mo Cherif
                                                                                    VP of AI and Innovation, Sitecore




EdChat is an education AI platform where students learn safely with AI through coding, data analysis, and exploration. Azure
Container Apps sandboxes would add built-in multi-tenant isolation and scale-to-zero, so each student could run in a cost-efficient,
isolated environment with strong filesystem and network guardrails. Persistence and snapshots would let students resume work
with files, code, and execution context intact -supporting longer-running tasks like notebooks and data exploration.”


                                                                                                       Cody Little
                                                         AI Technical Lead, Department for Education, South Australia
```

## Slide 14

![Slide 14](slide_images/slide_14.png)

```
Use Cases for Sandboxes

   Agent Workflows                                  Burst Workloads
   Give AI agents persistent, isolated workspaces   Scale from zero to thousands of sandboxes
   that survive across task boundaries              in response to demand


   AI Code Execution                                Secure Multi-Tenant Compute
   Safely run LLM-generated code in isolated        Strong isolation guarantees for running
   environments with instant startup                untrusted workloads from multiple tenants


   Platform Building                                Interactive User Sessions
   Build your own platforms on top of the same      Provide each user with their own isolated
   primitive powering Microsoft services            compute environment
```

## Slide 15

![Slide 15](slide_images/slide_15.png)

```
Customer Highlight
   Gopi Prashanth
   Chief Scientist - AI & Agents
   Auger Inc
```

## Slide 16

![Slide 16](slide_images/slide_16.png)

```
Customer Highlight
   Gopi Prashanth
   Chief Scientist - AI & Agents
   Auger Inc
```

## Slide 17

![Slide 17](slide_images/slide_17.png)

```
01 THE SUPPLY CHAIN PROBLEM


One Pen. Fifty Actors. Most Are Invisible.
     Raw Mat.           Processing       Components             Assembly             Shipping           Warehouse         Transport               Retail

 Oil wells           Plastic Resin      Barrel Molder       Sub-Assembly         Export Port         Regional DC       LTL Trucking      Office Depot
 Saudi Arabia        China              China               Vietnam              Veracruz            Texas             US Network        Retail

 Tungsten Mine       Carbide Mill       Ball Tip            Final Assembly       Customs Mexico      Amazon FC         Amazon Delivery   Amazon.com
 Vietnam             Japan              China               Mexico               Clearance           New Jersey        Same Day          Online

 Copper Mine         Brass Foundry      Ink Cartridge       Quality Control      Ocean Freight       West Coast DC     B2B Freight       Walmart
 Chile               Taiwan             Mexico              Mexico               30 days             California        Bulk              Mass Market

 Carbon Black        Ink Chemicals      Clip & Spring       ISO Compliance       Air Freight         Cross-Dock        Air Express       Staples
 Germany             India              Vietnam             Certification        Urgent              Chicago           Overnight         Specialty

 Natural Gas         Polymer Plant      Cap Molder          Packaging Line       Import Port         3PL Provider      Rail Transport    Consumer
 Qatar               South Korea        Malaysia            Mexico               Long Beach          Ohio              Midwest           End User

 Rare Earth          Solvent Refinery   Ink Tube                                 US Customs          Cold Storage      Last Mile 3PL     Corporate B2B
 China               Netherlands        Germany                                  Clearance           New York          Urban             Bulk Buyer

 Nickel Mine         Steel Wire Mill    Label Printer
 Indonesia           Germany            Vietnam

                                           50 ACTORS · 8 TIERS · 17 COUNTRIES · MOST ERP SYSTEMS SEE ONLY THE LAST 3



                WHEN A TUNGSTEN MINE IN VIETNAM FLOODS, YOUR ERP DOESN’T KNOW. AUGER HAS ALREADY MITIGATED THE IMPACT.
```

## Slide 18

![Slide 18](slide_images/slide_18.png)

```
Auger: The Autonomous Supply Chain
Models commoditize. The context layer that compounds across every deployment,
interaction and decision.




       Built On Ausco                     AI-native                  Context Driven




     Domain ontology as the        Agents that share a world     The right knowledge at the
       semantic substrate          model with the business         right moment, always
```

## Slide 19

![Slide 19](slide_images/slide_19.png)

```
02 THE DATA INTEGRATION PROBLEM


Data Integration: Expensive & Error Prone
No Reuse. No Scale. Bespoke Every Time.


                       Data Lives In Silos
                       ERP, WMS, TMS, Kafka streams, email attachments, all with conflicting representations and schemas.



                       Unstructured Knowledge Lost
                       Supplier confirmations, SOPs, expedite requests, passed in email, never integrated into any system.



                       Bespoke Every Deployment
                       Each new customer requires months of custom integration work. No reuse, no compounding.



                       Edge Cases Found Too Late
                       Fields populated only under certain conditions, system disagreements, aliasing, discovered after go-live.

The cost curve goes the wrong direction, quality degrades as the platform scales.
```

## Slide 20

![Slide 20](slide_images/slide_20.png)

```
03 AGENTIC DATA INTEGRATION (ADI)


ADI is Agentic, Iterative & Self-learning.

  1       Understand                2     Map To Ontology        3      Design & Build   4      Deploy



       Profile schema &                 Apply customer                  Architect ETL        Push to Microsoft
          cardinality                    business rules                     DAG                    Fabric

      AI enriches business              Map entities &               Generate PySpark          Run pipelines
            meaning                       functions                     on Fabric               end-to-end

      Discover joins & FK                Mass-balance                  Customer signs        Mass-balance gate
           inference                    coherence gate                   off (HITL)             + monitor




                                                          Foundation

                                    Agent Service
```

## Slide 21

![Slide 21](slide_images/slide_21.png)

```
04 THE MODELING PROBLEM


Without World Model: Agents Break.

              No Shared           Every agent builds custom logic. ’Order’ means something different to
              World Model         every integration. Nothing composes. Nothing audits consistently.




              Schema is           Patterns, KPIs, and learnings from one customer are locked in their schema,
              Customer-specific   they cannot transfer to the next deployment.




              Terminology is      ’DC’ vs ’Fulfillment Center’. ’OTW’ vs ’In Transit’. The same concept exists
              Fragmented          under dozens of names, breaking every analysis.
```

## Slide 22

![Slide 22](slide_images/slide_22.png)

```
05 THE ONTOLOGY SOLUTION


Ausco: World Supply Chain Model
No Schema Rebuild. One Source Of Truth. Agents Compose Rather Than Rebuild.




                              Entities                                                                        Actions                      Functions
                               the things                                                                     mutations                    queries + KPIs


    SKUs, Locations, Orders, Suppliers, base                                             Place PO, release shipment, adjust   Days of supply, fill rate, OTIF, defined
            objects + role instances                                                       forecast, governed, auditable,        once, consistent across every
             + plan-vs-actual pairs                                                            reversible write-backs                   agent and screen




                              Models                                                                      Workflows                       Knowledge
                         optimization + ML                                                              multi-step stateful                text + signals


        Demand forecast, allocation, N-tier                                               S&OP cycles, exception triage,       SOPs, contracts, transcripts + live
         inference, first-class assets any                                              scenario reviews, Temporal-backed      disruption signals, all in the same
                 agent can call                                                               durable orchestration                    ontological frame

Aliasing Layer · "Dc" → Fulfillment_center · "Otw" → Status.In_transit · Customer Terminology Preserved End-to-end
```

## Slide 23

![Slide 23](slide_images/slide_23.png)

```
06 THE CONTEXT PROBLEM


Without Context, Reasoning is Inconsistent.
Context Quality is the Performance Multiplier, not the Model.



                           Without Grounded Context                                                                   With The Context Layer

           Agent improvises KPI logic, inconsistent answers                                                 AUSCO Functions invoked, same answer, every agent

           No memory of terminology resolutions made before                                                 Validated terminology retrieved from tenant memory

           Context window fills with irrelevant history                                                     Bounded context packet: only the
                                                                                                            relevant AUSCO slice
           Month 1 performance ≈ Month 12: Zero learning
                                                                                                            Queries compound, fast path widens
           New tenants start from scratch every time                                                        with every query

                                                                                                            New tenants inherit cross-tenant base from day one




Two systems with the same model and the same data will perform very differently based on context quality.
```

## Slide 24

![Slide 24](slide_images/slide_24.png)

```
07 THE CONTEXT SOLUTION


Accurate, Grounded & Compounding
Context Wins.
Ausco-grounded · Model-agnostic · Compounds With Every Query


     Natural Language                              Context                                  Skills                           Reason

       Query Arrives                              Retrieve                                  Route                           Answer

      From user, agent, or                 Multi-hop over AUSCO                Fast path (known pattern) or            Response + traceable
        another product                    + STM + LTM + Skills                 Reasoning Path (discovery)             provenance, grounded



                                             RESOURCES THE CONTEXT LAYER RETRIEVES OVER


     Query Arrives             Short-term Memory              Long-term Memory                       Skills Library          Global Signals

   6 first-class concepts ·   Working state · turn ledger ·   Validated patterns · KPIs ·       Code methodologies        Live disruptions, weather,
  structural grounding for       resolved entities per         decision rationales per         graduated from proven      sanctions, market events
         every query                   session                         tenant                     real-world usage
```

## Slide 25

![Slide 25](slide_images/slide_25.png)

```
08 THE DIFFERENCE


Auger: Autonomy That Compounds.
Four Self-learning Loops, All Converge On AUSCO.




ADI Loop                   Context Loop            Execution Loop          Global Signals
Onboarding compounds       Usage compounds         Outcomes compound       The world compounds


Each new                   Every query refines     Agent actions,          Disruptions,
tenant contributes         retrieval, promotes     approvals, and          market moves, and
integration patterns,      patterns, and widens    predictions feed        geopolitical events
entity archetypes,         the fast path for all   back to refine          continuously enrich
and skills back to the     tenants on the          context, skills, and    every tenant’s
base platform.             platform.               autonomous policies.    context layer.




 50%                Faster executions
                                                   85%              Autonomous decisions
```

## Slide 26

![Slide 26](slide_images/slide_26.png)

```
1   Azure Container Apps delivers a cohesive
                agent runtime today – Apps, Sandboxes,
                Express, and serverless GPUs.



Key         2   Azure Container Apps Sandboxes are in public
                preview – fast, isolated, stateful compute to
Takeaways       untrusted code securely by default.



            3   Proven in production today – GitHub Copilot,
                Foundry Agent Service, SitecoreAI, EdChat,
                Auger and more.
```

## Slide 27

![Slide 27](slide_images/slide_27.png)

```
1   Azure Container Apps delivers a cohesive
                agent runtime today – Apps, Sandboxes,
                Express, and serverless GPUs.



Key         2   Azure Container Apps Sandboxes are in public
                preview – fast, isolated, stateful compute to
Takeaways       untrusted code securely by default.



            3   Proven in production today – GitHub Copilot,
                Foundry Agent Service, SitecoreAI, EdChat,
                Auger and more.
```

## Slide 28

![Slide 28](slide_images/slide_28.png)

```
Session Resources




    QR code
  Placeholder




Product Blog                            Code Sample
 aka.ms/aca/build                   aca/build2026-brk221
```

## Slide 29

![Slide 29](slide_images/slide_29.png)

```
Get Started Today!


                                       Azure Container
                                       Apps Express
                                       aka.ms/aca/express




                                       Azure Container Apps
Azure Container                        Sandboxes Portal
Apps Sandboxes                         aka.ms/aca/sandboxes/portal

 aka.ms/aca/sandboxes
```

## Slide 30

![Slide 30](slide_images/slide_30.png)

```
Explore the session details page
to take action with tutorials,
                                          QR code will go
resources and code
                                               here
Visit aka.ms/build/evals or scan the QR
code to fill out a session survey
```

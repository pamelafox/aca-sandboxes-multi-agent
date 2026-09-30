"""Agent-directed research workflow with parallel, sandboxed research waves.

Shape::

    [PlannerExecutor]
            ↓
    [Researcher_0..N]  ← parallel fan-out
            ↓
    [ResearchCollector]
            ↓
       [ReviewerExecutor] ── approved ──> [ReportWriterExecutor]
            │
            └── gaps ──> [PlannerExecutor]  (one bounded follow-up wave)
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Awaitable, Callable

from agent_framework import (
    AgentExecutorRequest,
    AgentExecutorResponse,
    AgentResponse,
    Executor,
    Message,
    Workflow,
    WorkflowBuilder,
    WorkflowContext,
    handler,
)
from typing_extensions import Never

from sandbox_manager import SandboxManager

from .planner_agent import ResearchQuestions, build_planner_agent
from .sandbox_researcher import build_sandbox_researcher
from .reviewer_agent import ReviewDecision, build_reviewer_agent
from .report_writer_agent import build_report_writer_agent

logger = logging.getLogger(__name__)

EmitFn = Callable[[dict], Awaitable[None]]

# A workflow with too many parallel researchers is expensive and may hit AOAI
# rate limits. Cap the fan-out width here.
MAX_RESEARCHERS = 6
MAX_RESEARCH_WAVES = 2


@dataclass
class ResearchInput:
    """Input passed to the workflow start executor."""
    topic: str


@dataclass
class ResearchPlan:
    """Description of one parallel research wave."""
    topic: str
    expected_responses: int
    previous_findings: list[dict]
    wave: int


@dataclass
class FollowUpResearch:
    """Reviewer-requested questions for another parallel research wave."""
    topic: str
    questions: list[str]
    previous_findings: list[dict]
    wave: int


@dataclass
class ResearchDossier:
    """Accumulated findings passed from the collector to the reviewer."""
    topic: str
    findings: list[dict]
    wave: int


@dataclass
class ApprovedDossier:
    """Reviewed evidence passed to the final report writer."""
    topic: str
    findings: list[dict]
    review_rationale: str
    wave: int


# ── Stage 1: Planner ──────────────────────────────────────────────────

class PlannerExecutor(Executor):
    """Plan initial research and dispatch initial or reviewer-requested waves."""

    def __init__(self, id: str = "planner"):
        super().__init__(id=id)
        self.agent = build_planner_agent()

    @handler
    async def start_research(
        self,
        payload: ResearchInput,
        ctx: WorkflowContext[AgentExecutorRequest | ResearchPlan, dict[str, object]],
    ) -> None:
        result = await self.agent.run(payload.topic, options={"response_format": ResearchQuestions})
        questions = validate_questions(result.value)
        await self._dispatch_wave(
            topic=payload.topic,
            questions=questions,
            previous_findings=[],
            wave=1,
            ctx=ctx,
        )

    @handler
    async def continue_research(
        self,
        payload: FollowUpResearch,
        ctx: WorkflowContext[AgentExecutorRequest | ResearchPlan, dict[str, object]],
    ) -> None:
        await self._dispatch_wave(
            topic=payload.topic,
            questions=payload.questions,
            previous_findings=payload.previous_findings,
            wave=payload.wave,
            ctx=ctx,
        )

    async def _dispatch_wave(
        self,
        *,
        topic: str,
        questions: list[str],
        previous_findings: list[dict],
        wave: int,
        ctx: WorkflowContext[AgentExecutorRequest | ResearchPlan, dict[str, object]],
    ) -> None:
        questions = questions[:MAX_RESEARCHERS]
        await ctx.yield_output({
            "kind": "questions",
            "wave": wave,
            "questions": questions,
        })
        await ctx.send_message(
            ResearchPlan(
                topic=topic,
                expected_responses=len(questions),
                previous_findings=previous_findings,
                wave=wave,
            ),
            target_id="research_collector",
        )
        for i, q in enumerate(questions):
            await ctx.send_message(
                AgentExecutorRequest(
                    messages=[Message("user", [q])],
                    should_respond=True,
                ),
                target_id=f"researcher_{i}",
            )


# ── Stage 2: Researchers (one deterministic executor per parallel branch) ──

class ResearcherExecutor(Executor):
    """Run one question in a sandbox directly, with no LLM dispatch step.

    Failures become an error finding, so the branch still reaches the collector
    and the reviewer sees what's missing.
    """

    def __init__(self, sandbox_mgr: SandboxManager, emit: EmitFn, index: int):
        super().__init__(id=f"researcher_{index}")
        self.run_in_sandbox = build_sandbox_researcher(self.id, sandbox_mgr, emit, index)

    @handler
    async def run(
        self,
        request: AgentExecutorRequest,
        ctx: WorkflowContext[AgentExecutorResponse],
    ) -> None:
        question = request.messages[-1].text if request.messages else ""
        try:
            text = await self.run_in_sandbox(question)
        except Exception as ex:
            logger.exception("[%s] sandbox research failed", self.id)
            text = json.dumps({
                "question": question,
                "answer": f"Research failed: {ex}",
                "sources": [],
                "confidence": 0.0,
                "error": str(ex),
            })
        reply = Message("assistant", [text])
        await ctx.send_message(AgentExecutorResponse(
            executor_id=self.id,
            agent_response=AgentResponse(messages=[reply]),
            full_conversation=[*request.messages, reply],
        ))


def _build_researcher_executors(
    sandbox_mgr: SandboxManager,
    emit: EmitFn,
) -> list[ResearcherExecutor]:
    """Build a fixed pool of researcher executors, `researcher_0` to `researcher_5`."""
    return [ResearcherExecutor(sandbox_mgr, emit, i) for i in range(MAX_RESEARCHERS)]


# ── Stage 3: Collect dynamically ────────────────────────────────────────────

class ResearchCollector(Executor):
    """Collect each wave and release an accumulated research dossier."""

    def __init__(self, id: str = "research_collector"):
        super().__init__(id=id)
        self.plan: ResearchPlan | None = None
        self.responses: list[AgentExecutorResponse] = []
        self.pending_responses: list[AgentExecutorResponse] = []
        self.released = False

    async def release_if_ready(
        self,
        ctx: WorkflowContext[ResearchDossier],
    ) -> None:
        if (
            not self.released
            and self.plan is not None
            and len(self.responses) >= self.plan.expected_responses
        ):
            self.released = True
            findings = [
                *copy_findings(self.plan.previous_findings),
                *[parse_research_response(response) for response in self.responses],
            ]
            await ctx.send_message(ResearchDossier(
                topic=self.plan.topic,
                findings=findings,
                wave=self.plan.wave,
            ))

    @handler
    async def set_plan(
        self,
        plan: ResearchPlan,
        ctx: WorkflowContext[ResearchDossier],
    ) -> None:
        if self.plan is not None and not self.released:
            raise RuntimeError("Cannot start a research wave before the current wave completes")
        self.plan = plan
        self.responses = self.pending_responses
        self.pending_responses = []
        self.released = False
        await self.release_if_ready(ctx)

    @handler
    async def collect_response(
        self,
        response: AgentExecutorResponse,
        ctx: WorkflowContext[ResearchDossier],
    ) -> None:
        if self.plan is None or self.released:
            self.pending_responses.append(response)
        else:
            self.responses.append(response)
        await self.release_if_ready(ctx)


# ── Stage 4: Review and route ───────────────────────────────────────────────

class ReviewerExecutor(Executor):
    """Review evidence and choose the next owner of the task."""

    def __init__(self, id: str = "reviewer"):
        super().__init__(id=id)
        self.agent = build_reviewer_agent()

    @handler
    async def review(
        self,
        dossier: ResearchDossier,
        ctx: WorkflowContext[FollowUpResearch | ApprovedDossier, dict],
    ) -> None:
        waves_remaining = MAX_RESEARCH_WAVES - dossier.wave
        prompt = format_dossier(
            dossier.topic,
            dossier.findings,
            heading="Research dossier to review",
        )
        prompt += (
            f"\n\nResearch wave: {dossier.wave} of {MAX_RESEARCH_WAVES}. "
            f"Additional research waves remaining: {waves_remaining}."
        )
        result = await self.agent.run(prompt, options={"response_format": ReviewDecision})
        decision = validate_review_decision(result.value)

        if decision.status == "needs_more_research" and waves_remaining > 0:
            await ctx.yield_output({
                "kind": "review",
                "status": decision.status,
                "rationale": decision.rationale,
                "wave": dossier.wave,
                "follow_up_questions": decision.follow_up_questions,
            })
            await ctx.send_message(
                FollowUpResearch(
                    topic=dossier.topic,
                    questions=decision.follow_up_questions,
                    previous_findings=dossier.findings,
                    wave=dossier.wave + 1,
                ),
                target_id="planner",
            )
            return

        rationale = decision.rationale
        if decision.status == "needs_more_research":
            rationale += " No research waves remained, so the report uses the best available evidence."
        await ctx.yield_output({
            "kind": "review",
            "status": "approved",
            "rationale": rationale,
            "wave": dossier.wave,
            "follow_up_questions": [],
        })
        await ctx.send_message(
            ApprovedDossier(
                topic=dossier.topic,
                findings=dossier.findings,
                review_rationale=rationale,
                wave=dossier.wave,
            ),
            target_id="report_writer",
        )


# ── Stage 5: Write final report ─────────────────────────────────────────────

class ReportWriterExecutor(Executor):
    """Turn the reviewer-approved dossier into the final markdown report."""

    def __init__(self, id: str = "report_writer"):
        super().__init__(id=id)
        self.agent = build_report_writer_agent()

    @handler
    async def write_report(
        self,
        dossier: ApprovedDossier,
        ctx: WorkflowContext[Never, str],
    ) -> None:
        prompt = format_dossier(
            dossier.topic,
            dossier.findings,
            heading="Reviewer-approved research dossier",
        )
        prompt += (
            f"\n\n## Reviewer assessment\n{dossier.review_rationale}\n\n"
            f"The dossier was approved after research wave {dossier.wave}."
        )
        result = await self.agent.run(prompt)
        await ctx.yield_output(result.text or "")


# ── Build & expose ──────────────────────────────────────────────────────────

def build_research_workflow(
    sandbox_mgr: SandboxManager,
    emit: EmitFn,
) -> Workflow:
    """
    Construct the agent-directed workflow:
        planner → parallel researchers → collector → reviewer
        reviewer → planner (gaps) OR report writer (approved)

    The workflow is built per request so each researcher closes over the
    right WebSocket emit callback.
    """
    planner = PlannerExecutor()
    researchers = _build_researcher_executors(sandbox_mgr, emit)
    collector = ResearchCollector()
    reviewer = ReviewerExecutor()
    report_writer = ReportWriterExecutor()

    # NOTE: We use individual edges (planner → researcher_i) instead of a
    # single `add_fan_out_edges` group on purpose. MAF's fan-out edge runner
    # delivers the N targeted messages sequentially within a single edge
    # runner (`for message in source_messages: await deliver(...)`), which
    # serializes all 6 researcher branches. Using 6 separate edge
    # runners lets MAF parallelize them via `asyncio.gather` in the runner.
    builder = WorkflowBuilder(start_executor=planner)
    builder = builder.add_edge(planner, collector)
    for r in researchers:
        builder = builder.add_edge(planner, r)
        builder = builder.add_edge(r, collector)
    builder = builder.add_edge(collector, reviewer)
    builder = builder.add_edge(reviewer, planner)
    wf = builder.add_edge(reviewer, report_writer).build()
    return wf


# ── helpers ─────────────────────────────────────────────────────────────────

def validate_questions(plan: ResearchQuestions | None) -> list[str]:
    """Check the rules the planner's output schema can't express."""
    if plan is None:
        raise ValueError("Planner returned no structured output")
    questions = [question.strip() for question in plan.questions if question.strip()]
    if not 4 <= len(questions) <= MAX_RESEARCHERS:
        raise ValueError("Planner must return 4-6 questions")
    return questions


def validate_review_decision(decision: ReviewDecision | None) -> ReviewDecision:
    """Check the rules the reviewer's output schema can't express."""
    if decision is None:
        raise ValueError("Reviewer returned no structured output")
    if not decision.rationale.strip():
        raise ValueError("Reviewer rationale must be non-empty")
    if decision.status == "approved" and decision.follow_up_questions:
        raise ValueError("Approved reviewer decisions cannot include follow-up questions")
    if decision.status == "needs_more_research" and not 2 <= len(decision.follow_up_questions) <= 4:
        raise ValueError("Reviewer must provide 2-4 follow-up questions")
    return decision


def parse_research_response(response: AgentExecutorResponse) -> dict:
    text = (response.agent_response.text or "").strip()
    try:
        finding = json.loads(text)
    except json.JSONDecodeError:
        return {
            "question": "(unparsed)",
            "answer": text,
            "sources": [],
            "confidence": 0.0,
        }
    if not isinstance(finding, dict):
        return {
            "question": "(unparsed)",
            "answer": text,
            "sources": [],
            "confidence": 0.0,
        }
    return finding


def copy_findings(findings: list[dict]) -> list[dict]:
    return [dict(finding) for finding in findings]


def format_dossier(topic: str, findings: list[dict], *, heading: str) -> str:
    prompt_lines = [
        f"# {heading}",
        "",
        "## Original topic",
        topic,
        "",
        "## Individual agent findings",
        "",
    ]
    for i, finding in enumerate(findings, start=1):
        prompt_lines.append(f"### Finding {i}: {finding.get('question', '')}")
        try:
            confidence = float(finding.get("confidence", 0))
        except (TypeError, ValueError):
            confidence = 0.0
        prompt_lines.append(f"**Confidence:** {confidence:.0%}\n")
        prompt_lines.append(str(finding.get("answer", "")))
        sources = finding.get("sources") or []
        if sources:
            prompt_lines.append("\n**Sources:** " + ", ".join(map(str, sources)))
        prompt_lines.append("")
    return "\n".join(prompt_lines)

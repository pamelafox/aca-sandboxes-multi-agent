"""Agent-directed research workflow with parallel, sandboxed research waves.

Shape::

    [ResearchLeadExecutor]
            ↓
    [Researcher_0..N]  ← parallel fan-out
            ↓
    [ResearchCollector]
            ↓
       [ReviewerExecutor] ── approved ──> [ReportWriterExecutor]
            │
            └── gaps ──> [ResearchLeadExecutor]  (one bounded follow-up wave)
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Awaitable, Callable

from agent_framework import (
    AgentExecutor,
    AgentExecutorRequest,
    AgentExecutorResponse,
    Executor,
    Message,
    Workflow,
    WorkflowBuilder,
    WorkflowContext,
    handler,
)
from typing_extensions import Never

from sandbox_manager import SandboxManager

from .decomposer_agent import build_decomposer_agent
from .researcher_agent import build_researcher_agent
from .reviewer_agent import build_reviewer_agent
from .synthesizer_agent import build_report_writer_agent

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


@dataclass
class ReviewDecision:
    """Structured routing decision returned by the reviewer agent."""
    status: str
    rationale: str
    follow_up_questions: list[str]


# ── Stage 1: Research lead ──────────────────────────────────────────────────

class ResearchLeadExecutor(Executor):
    """Plan initial research and dispatch initial or reviewer-requested waves."""

    def __init__(self, id: str = "research_lead"):
        super().__init__(id=id)
        self._agent = build_decomposer_agent()

    @handler
    async def start_research(
        self,
        payload: ResearchInput,
        ctx: WorkflowContext[AgentExecutorRequest | ResearchPlan, dict[str, object]],
    ) -> None:
        result = await self._agent.run(payload.topic)
        questions = _parse_questions((result.text or "").strip())
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


# ── Stage 2: Researchers (one AgentExecutor per parallel branch) ────────────

def _build_researcher_executors(
    sandbox_mgr: SandboxManager,
    emit: EmitFn,
) -> list[AgentExecutor]:
    """
    Build a fixed pool of MAX_RESEARCHERS researcher AgentExecutors. Each one
    has a unique id (`researcher_0`, `researcher_1`, ...) so DecomposeExecutor
    can target by index. The sandbox manager + emit callback are bound via
    closure on each researcher's tool.
    """
    pool: list[AgentExecutor] = []
    for i in range(MAX_RESEARCHERS):
        agent_id = f"researcher_{i}"
        agent = build_researcher_agent(agent_id, sandbox_mgr, emit, i)
        pool.append(AgentExecutor(agent=agent, id=agent_id))
    return pool


# ── Stage 3: Collect dynamically ────────────────────────────────────────────

class ResearchCollector(Executor):
    """Collect each wave and release an accumulated research dossier."""

    def __init__(self, id: str = "research_collector"):
        super().__init__(id=id)
        self._plan: ResearchPlan | None = None
        self._responses: list[AgentExecutorResponse] = []
        self._pending_responses: list[AgentExecutorResponse] = []
        self._released = False

    async def _release_if_ready(
        self,
        ctx: WorkflowContext[ResearchDossier],
    ) -> None:
        if (
            not self._released
            and self._plan is not None
            and len(self._responses) >= self._plan.expected_responses
        ):
            self._released = True
            findings = [
                *_copy_findings(self._plan.previous_findings),
                *[_parse_research_response(response) for response in self._responses],
            ]
            await ctx.send_message(ResearchDossier(
                topic=self._plan.topic,
                findings=findings,
                wave=self._plan.wave,
            ))

    @handler
    async def set_plan(
        self,
        plan: ResearchPlan,
        ctx: WorkflowContext[ResearchDossier],
    ) -> None:
        if self._plan is not None and not self._released:
            raise RuntimeError("Cannot start a research wave before the current wave completes")
        self._plan = plan
        self._responses = self._pending_responses
        self._pending_responses = []
        self._released = False
        await self._release_if_ready(ctx)

    @handler
    async def collect_response(
        self,
        response: AgentExecutorResponse,
        ctx: WorkflowContext[ResearchDossier],
    ) -> None:
        if self._plan is None or self._released:
            self._pending_responses.append(response)
        else:
            self._responses.append(response)
        await self._release_if_ready(ctx)


# ── Stage 4: Review and route ───────────────────────────────────────────────

class ReviewerExecutor(Executor):
    """Review evidence and choose the next owner of the task."""

    def __init__(self, id: str = "reviewer"):
        super().__init__(id=id)
        self._agent = build_reviewer_agent()

    @handler
    async def review(
        self,
        dossier: ResearchDossier,
        ctx: WorkflowContext[FollowUpResearch | ApprovedDossier, dict],
    ) -> None:
        waves_remaining = MAX_RESEARCH_WAVES - dossier.wave
        prompt = _format_dossier(
            dossier.topic,
            dossier.findings,
            heading="Research dossier to review",
        )
        prompt += (
            f"\n\nResearch wave: {dossier.wave} of {MAX_RESEARCH_WAVES}. "
            f"Additional research waves remaining: {waves_remaining}."
        )
        result = await self._agent.run(prompt)
        decision = _parse_review_decision((result.text or "").strip())

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
                target_id="research_lead",
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
        self._agent = build_report_writer_agent()

    @handler
    async def write_report(
        self,
        dossier: ApprovedDossier,
        ctx: WorkflowContext[Never, str],
    ) -> None:
        prompt = _format_dossier(
            dossier.topic,
            dossier.findings,
            heading="Reviewer-approved research dossier",
        )
        prompt += (
            f"\n\n## Reviewer assessment\n{dossier.review_rationale}\n\n"
            f"The dossier was approved after research wave {dossier.wave}."
        )
        result = await self._agent.run(prompt)
        await ctx.yield_output(result.text or "")


# ── Build & expose ──────────────────────────────────────────────────────────

def build_research_workflow(
    sandbox_mgr: SandboxManager,
    emit: EmitFn,
) -> Workflow:
    """
    Construct the agent-directed workflow:
        research lead → parallel researchers → collector → reviewer
        reviewer → research lead (gaps) OR report writer (approved)

    The workflow is built per request so each researcher's tool closes over
    the right WebSocket emit callback.
    """
    research_lead = ResearchLeadExecutor()
    researchers = _build_researcher_executors(sandbox_mgr, emit)
    collector = ResearchCollector()
    reviewer = ReviewerExecutor()
    report_writer = ReportWriterExecutor()

    # NOTE: We use individual edges (research lead → researcher_i) instead of a
    # single `add_fan_out_edges` group on purpose. MAF's fan-out edge runner
    # delivers the N targeted messages sequentially within a single edge
    # runner (`for message in source_messages: await deliver(...)`), which
    # serializes the LLM calls for all 6 researchers. Using 6 separate edge
    # runners lets MAF parallelize them via `asyncio.gather` in the runner.
    builder = WorkflowBuilder(start_executor=research_lead)
    builder = builder.add_edge(research_lead, collector)
    for r in researchers:
        builder = builder.add_edge(research_lead, r)
        builder = builder.add_edge(r, collector)
    builder = builder.add_edge(collector, reviewer)
    builder = builder.add_edge(reviewer, research_lead)
    wf = builder.add_edge(reviewer, report_writer).build()
    return wf


def per_agent_kwargs_for_run(
    sandbox_mgr: SandboxManager,
    emit,  # async callable taking a dict
) -> dict[str, dict]:
    """
    Per-researcher kwargs supplied via `function_invocation_kwargs`. Each
    branch gets its index injected so the tool can correlate WebSocket events.
    """
    out: dict[str, dict] = {}
    for i in range(MAX_RESEARCHERS):
        out[f"researcher_{i}"] = {
            "sandbox_mgr": sandbox_mgr,
            "emit": emit,
            "index": i,
        }
    return out


# ── helpers ─────────────────────────────────────────────────────────────────

_FENCE_RE = re.compile(r"^```(?:json)?\s*\n?|\n?```$", re.MULTILINE)


def _strip_code_fences(text: str) -> str:
    return _FENCE_RE.sub("", text).strip()


def _parse_questions(raw: str) -> list[str]:
    raw = _strip_code_fences(raw)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError("Decomposer returned invalid JSON") from exc
    if not isinstance(data, list) or not 4 <= len(data) <= MAX_RESEARCHERS:
        raise ValueError("Decomposer must return an array of 4-6 questions")
    if not all(isinstance(question, str) and question.strip() for question in data):
        raise ValueError("Decomposer questions must be non-empty strings")
    return data


def _parse_review_decision(raw: str) -> ReviewDecision:
    raw = _strip_code_fences(raw)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError("Reviewer returned invalid JSON") from exc
    if not isinstance(data, dict):
        raise ValueError("Reviewer decision must be a JSON object")

    status = data.get("status")
    rationale = data.get("rationale")
    follow_up_questions = data.get("follow_up_questions")
    if status not in {"approved", "needs_more_research"}:
        raise ValueError("Reviewer status must be 'approved' or 'needs_more_research'")
    if not isinstance(rationale, str) or not rationale.strip():
        raise ValueError("Reviewer rationale must be a non-empty string")
    if not isinstance(follow_up_questions, list) or not all(
        isinstance(question, str) and question.strip()
        for question in follow_up_questions
    ):
        raise ValueError("Reviewer follow_up_questions must be an array of non-empty strings")
    if status == "approved" and follow_up_questions:
        raise ValueError("Approved reviewer decisions cannot include follow-up questions")
    if status == "needs_more_research" and not 2 <= len(follow_up_questions) <= 4:
        raise ValueError("Reviewer must provide 2-4 follow-up questions")

    return ReviewDecision(
        status=status,
        rationale=rationale.strip(),
        follow_up_questions=follow_up_questions,
    )


def _parse_research_response(response: AgentExecutorResponse) -> dict:
    text = _strip_code_fences((response.agent_response.text or "").strip())
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


def _copy_findings(findings: list[dict]) -> list[dict]:
    return [dict(finding) for finding in findings]


def _format_dossier(topic: str, findings: list[dict], *, heading: str) -> str:
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

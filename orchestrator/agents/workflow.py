"""
Research Workflow — MAF Workflow that orchestrates the swarm pipeline.

Shape::

    [DecomposeExecutor]
            ↓
       (1 message per question)
            ↓
    [Researcher_0] [Researcher_1] ... [Researcher_N]   ← fan-out
            ↓        ↓                    ↓
            └────────┴── dynamic collector ───────────┘
                            ↓
                  [SynthesizeExecutor]
                            ↓
                       final markdown
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
from .synthesizer_agent import build_synthesizer_agent

logger = logging.getLogger(__name__)

EmitFn = Callable[[dict], Awaitable[None]]

# A workflow with too many parallel researchers is expensive and may hit AOAI
# rate limits. Cap the fan-out width here.
MAX_RESEARCHERS = 6


@dataclass
class ResearchInput:
    """Input passed to the workflow start executor."""
    topic: str


@dataclass
class ResearchPlan:
    """Number of researcher responses the collector should await."""
    expected_responses: int


# ── Stage 1: Decompose ──────────────────────────────────────────────────────

class DecomposeExecutor(Executor):
    """
    Asks the decomposer agent for sub-questions, then dispatches one
    AgentExecutorRequest per question to the parallel researcher executors.
    """

    def __init__(self, id: str = "decomposer"):
        super().__init__(id=id)
        self._agent = build_decomposer_agent()

    @handler
    async def decompose(
        self,
        payload: ResearchInput,
        ctx: WorkflowContext[AgentExecutorRequest | ResearchPlan, list[str]],
    ) -> None:
        # 1) Ask the LLM to decompose
        result = await self._agent.run(payload.topic)
        raw = (result.text or "").strip()
        questions = _parse_questions(raw)
        # Cap at MAX_RESEARCHERS; researchers list is built to match this size
        questions = questions[:MAX_RESEARCHERS]

        # Surface the questions as a workflow output (events) so the UI gets them
        await ctx.yield_output(questions)

        # Tell the collector how many branches were actually dispatched. This
        # avoids a fixed fan-in barrier when the decomposer returns fewer than
        # MAX_RESEARCHERS questions.
        await ctx.send_message(
            ResearchPlan(expected_responses=len(questions)),
            target_id="research_collector",
        )

        # 2) Dispatch one request per question. The framework will route
        # successive sends in the same handler invocation across the fan-out
        # edges round-robin / by index, so we attach the index in metadata
        # via a structured user message.
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
    """Release researcher responses once the dispatched branch count arrives."""

    def __init__(self, id: str = "research_collector"):
        super().__init__(id=id)
        self._expected_responses: int | None = None
        self._responses: list[AgentExecutorResponse] = []
        self._released = False

    async def _release_if_ready(
        self,
        ctx: WorkflowContext[list[AgentExecutorResponse]],
    ) -> None:
        if (
            not self._released
            and self._expected_responses is not None
            and len(self._responses) >= self._expected_responses
        ):
            self._released = True
            await ctx.send_message(list(self._responses))

    @handler
    async def set_plan(
        self,
        plan: ResearchPlan,
        ctx: WorkflowContext[list[AgentExecutorResponse]],
    ) -> None:
        self._expected_responses = plan.expected_responses
        await self._release_if_ready(ctx)

    @handler
    async def collect_response(
        self,
        response: AgentExecutorResponse,
        ctx: WorkflowContext[list[AgentExecutorResponse]],
    ) -> None:
        self._responses.append(response)
        await self._release_if_ready(ctx)


# ── Stage 4: Synthesize ─────────────────────────────────────────────────────

class SynthesizeExecutor(Executor):
    """
    Aggregates all researcher AgentExecutorResponses, asks the synthesizer
    agent to produce a markdown report, then yields it as the workflow output.
    """

    def __init__(self, id: str = "synthesizer"):
        super().__init__(id=id)
        self._agent = build_synthesizer_agent()

    @handler
    async def synthesize(
        self,
        responses: list[AgentExecutorResponse],
        ctx: WorkflowContext[Never, str],
    ) -> None:
        # Each response.text from a researcher is the JSON our researcher tool
        # returned. Parse them back into structured findings.
        findings: list[dict] = []
        for r in responses:
            text = (r.agent_response.text or "").strip()
            text = _strip_code_fences(text)
            try:
                findings.append(json.loads(text))
            except json.JSONDecodeError:
                findings.append({
                    "question": "(unparsed)",
                    "answer": text,
                    "sources": [],
                    "confidence": 0.0,
                })

        # Build the synthesis prompt
        prompt_lines: list[str] = ["## Individual Agent Findings\n"]
        for i, f in enumerate(findings, start=1):
            prompt_lines.append(f"### Agent {i}: {f.get('question', '')}")
            prompt_lines.append(f"**Confidence:** {float(f.get('confidence', 0)):.0%}\n")
            prompt_lines.append(str(f.get("answer", "")))
            srcs = f.get("sources") or []
            if srcs:
                prompt_lines.append("\n**Sources:** " + ", ".join(srcs))
            prompt_lines.append("")

        result = await self._agent.run("\n".join(prompt_lines))
        await ctx.yield_output(result.text or "")


# ── Build & expose ──────────────────────────────────────────────────────────

def build_research_workflow(
    sandbox_mgr: SandboxManager,
    emit: EmitFn,
) -> Workflow:
    """
    Construct the full fan-out/dynamic-collection workflow:
        decomposer → [researcher_0..N-1] → collector → synthesizer

    The workflow is built per request so each researcher's tool closes over
    the right WebSocket emit callback.
    """
    decomposer  = DecomposeExecutor()
    researchers = _build_researcher_executors(sandbox_mgr, emit)
    collector   = ResearchCollector()
    synthesizer = SynthesizeExecutor()

    # NOTE: We use individual edges (decomposer → researcher_i) instead of a
    # single `add_fan_out_edges` group on purpose. MAF's fan-out edge runner
    # delivers the N targeted messages sequentially within a single edge
    # runner (`for message in source_messages: await deliver(...)`), which
    # serializes the LLM calls for all 6 researchers. Using 6 separate edge
    # runners lets MAF parallelize them via `asyncio.gather` in the runner.
    builder = WorkflowBuilder(start_executor=decomposer)
    builder = builder.add_edge(decomposer, collector)
    for r in researchers:
        builder = builder.add_edge(decomposer, r)
        builder = builder.add_edge(r, collector)
    wf = builder.add_edge(collector, synthesizer).build()
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

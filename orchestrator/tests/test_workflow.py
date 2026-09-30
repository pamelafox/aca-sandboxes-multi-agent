import json
import unittest
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

from agent_framework import (
    AgentExecutorRequest,
    AgentExecutorResponse,
    AgentResponse,
    Executor,
    Message,
    WorkflowContext,
    handler,
)
from agents import workflow as workflow_module
from agents.planner_agent import ResearchQuestions
from agents.reviewer_agent import ReviewDecision
from agents.workflow import (
    MAX_RESEARCHERS,
    ResearchCollector,
    ResearchDossier,
    ResearchInput,
    ResearchPlan,
    ResearcherExecutor,
    parse_research_response,
    validate_questions,
    validate_review_decision,
    build_research_workflow,
)


class FakeContext:
    def __init__(self) -> None:
        self.sent: list[Any] = []

    async def send_message(self, value: Any) -> None:
        self.sent.append(value)


@dataclass
class FakeAgentResponse:
    text: str


@dataclass
class FakeExecutorResponse:
    agent_response: FakeAgentResponse


def make_response(index: int) -> FakeExecutorResponse:
    return FakeExecutorResponse(FakeAgentResponse(json.dumps({
        "question": f"Question {index}?",
        "answer": f"Answer {index}",
        "sources": [f"https://example.com/{index}"],
        "confidence": 0.8,
    })))


class FakeAgent:
    """Returns each output in turn: structured outputs as .value, strings as .text."""

    def __init__(self, outputs: list[Any]) -> None:
        self._outputs = iter(outputs)

    async def run(self, prompt: str, options: dict | None = None) -> SimpleNamespace:
        output = next(self._outputs)
        if isinstance(output, str):
            return SimpleNamespace(text=output, value=None)
        return SimpleNamespace(text=output.model_dump_json(), value=output)


class FakeResearcher(Executor):
    @handler
    async def research(
        self,
        payload: AgentExecutorRequest,
        ctx: WorkflowContext[AgentExecutorResponse],
    ) -> None:
        question = payload.messages[-1].text
        text = json.dumps({
            "question": question,
            "answer": f"Answer for {question}",
            "sources": [],
            "confidence": 0.8,
        })
        response = AgentResponse(messages=[Message("assistant", [text])])
        await ctx.send_message(AgentExecutorResponse(
            executor_id=self.id,
            agent_response=response,
            full_conversation=[*payload.messages, *response.messages],
        ))


class ResearcherExecutorTests(unittest.IsolatedAsyncioTestCase):
    def make_executor(self, run_in_sandbox: Any) -> ResearcherExecutor:
        with patch.object(workflow_module, "build_sandbox_researcher", return_value=run_in_sandbox):
            return ResearcherExecutor(sandbox_mgr=None, emit=None, index=2)  # type: ignore[arg-type]

    def make_request(self, question: str) -> AgentExecutorRequest:
        return AgentExecutorRequest(messages=[Message("user", [question])], should_respond=True)

    async def test_passes_sandbox_result_through_without_an_llm(self) -> None:
        questions: list[str] = []

        async def run_in_sandbox(question: str) -> str:
            questions.append(question)
            return json.dumps({"question": question, "answer": "Found it", "sources": ["https://example.com"], "confidence": 0.9})

        executor = self.make_executor(run_in_sandbox)
        context = FakeContext()
        await executor.run(self.make_request("What is a sandbox?"), context)  # type: ignore[arg-type]

        self.assertEqual(executor.id, "researcher_2")
        self.assertEqual(questions, ["What is a sandbox?"])
        finding = parse_research_response(context.sent[0])
        self.assertEqual(finding["answer"], "Found it")
        self.assertEqual(finding["sources"], ["https://example.com"])

    async def test_failed_branch_still_reports_an_error_finding(self) -> None:
        async def run_in_sandbox(question: str) -> str:
            raise RuntimeError("Sandbox creation failed")

        executor = self.make_executor(run_in_sandbox)
        context = FakeContext()
        await executor.run(self.make_request("What is a sandbox?"), context)  # type: ignore[arg-type]

        finding = parse_research_response(context.sent[0])
        self.assertEqual(finding["question"], "What is a sandbox?")
        self.assertEqual(finding["error"], "Sandbox creation failed")
        self.assertEqual(finding["sources"], [])


class ResearchCollectorTests(unittest.IsolatedAsyncioTestCase):
    async def test_releases_once_for_supported_researcher_counts(self) -> None:
        for expected in (4, 5, 6):
            with self.subTest(expected=expected):
                collector = ResearchCollector()
                context = FakeContext()

                await collector.set_plan(
                    ResearchPlan("Topic", expected, [], 1),
                    context,  # type: ignore[arg-type]
                )
                for index in range(expected - 1):
                    await collector.collect_response(
                        make_response(index), context  # type: ignore[arg-type]
                    )
                    self.assertEqual(context.sent, [])

                await collector.collect_response(
                    make_response(expected - 1), context  # type: ignore[arg-type]
                )
                self.assertEqual(len(context.sent), 1)
                dossier = context.sent[0]
                self.assertIsInstance(dossier, ResearchDossier)
                self.assertEqual(dossier.topic, "Topic")
                self.assertEqual(dossier.wave, 1)
                self.assertEqual(len(dossier.findings), expected)

                await collector.collect_response(
                    make_response(99), context  # type: ignore[arg-type]
                )
                self.assertEqual(len(context.sent), 1)

    async def test_releases_when_plan_arrives_after_responses(self) -> None:
        collector = ResearchCollector()
        context = FakeContext()

        for index in range(5):
            await collector.collect_response(
                make_response(index), context  # type: ignore[arg-type]
            )
        self.assertEqual(context.sent, [])

        await collector.set_plan(
            ResearchPlan("Topic", 5, [], 1),
            context,  # type: ignore[arg-type]
        )
        self.assertEqual(len(context.sent), 1)
        self.assertEqual(len(context.sent[0].findings), 5)

    async def test_accumulates_findings_across_research_waves(self) -> None:
        collector = ResearchCollector()
        context = FakeContext()
        existing = [{
            "question": "Initial?",
            "answer": "Initial answer",
            "sources": [],
            "confidence": 0.7,
        }]

        await collector.set_plan(
            ResearchPlan("Topic", 2, existing, 2),
            context,  # type: ignore[arg-type]
        )
        await collector.collect_response(
            make_response(1), context  # type: ignore[arg-type]
        )
        await collector.collect_response(
            make_response(2), context  # type: ignore[arg-type]
        )

        dossier = context.sent[0]
        self.assertEqual(dossier.wave, 2)
        self.assertEqual(len(dossier.findings), 3)
        self.assertEqual(dossier.findings[0]["answer"], "Initial answer")

    async def test_accepts_next_wave_response_before_next_plan(self) -> None:
        collector = ResearchCollector()
        context = FakeContext()

        await collector.set_plan(
            ResearchPlan("Topic", 1, [], 1),
            context,  # type: ignore[arg-type]
        )
        await collector.collect_response(
            make_response(0), context  # type: ignore[arg-type]
        )
        await collector.collect_response(
            make_response(1), context  # type: ignore[arg-type]
        )
        await collector.set_plan(
            ResearchPlan("Topic", 1, context.sent[0].findings, 2),
            context,  # type: ignore[arg-type]
        )

        self.assertEqual(len(context.sent), 2)
        self.assertEqual(context.sent[1].wave, 2)
        self.assertEqual(len(context.sent[1].findings), 2)


class ValidateQuestionsTests(unittest.TestCase):
    def test_accepts_valid_questions(self) -> None:
        questions = [f"Question {index}?" for index in range(4)]

        self.assertEqual(validate_questions(ResearchQuestions(questions=questions)), questions)

    def test_rejects_missing_structured_output(self) -> None:
        with self.assertRaisesRegex(ValueError, "no structured output"):
            validate_questions(None)

    def test_rejects_wrong_question_count(self) -> None:
        with self.assertRaisesRegex(ValueError, "4-6 questions"):
            validate_questions(ResearchQuestions(questions=["Only one?"]))


class ValidateReviewDecisionTests(unittest.TestCase):
    def test_accepts_approved_decision(self) -> None:
        decision = validate_review_decision(ReviewDecision(
            status="approved",
            rationale="Coverage is sufficient.",
            follow_up_questions=[],
        ))

        self.assertEqual(decision.status, "approved")
        self.assertEqual(decision.follow_up_questions, [])

    def test_accepts_follow_up_decision(self) -> None:
        decision = validate_review_decision(ReviewDecision(
            status="needs_more_research",
            rationale="Two material gaps remain.",
            follow_up_questions=["Question one?", "Question two?"],
        ))

        self.assertEqual(decision.status, "needs_more_research")
        self.assertEqual(len(decision.follow_up_questions), 2)

    def test_rejects_invalid_follow_up_count(self) -> None:
        with self.assertRaisesRegex(ValueError, "2-4 follow-up"):
            validate_review_decision(ReviewDecision(
                status="needs_more_research",
                rationale="A gap remains.",
                follow_up_questions=["Only one?"],
            ))


class ResearchWorkflowTests(unittest.IsolatedAsyncioTestCase):
    async def test_routes_follow_up_wave_then_writes_report(self) -> None:
        initial_questions = ResearchQuestions(questions=[
            "Question one?",
            "Question two?",
            "Question three?",
            "Question four?",
        ])
        review_decisions = [
            ReviewDecision(
                status="needs_more_research",
                rationale="Two gaps remain.",
                follow_up_questions=["Follow-up one?", "Follow-up two?"],
            ),
            ReviewDecision(
                status="approved",
                rationale="The dossier now covers the material questions.",
                follow_up_questions=[],
            ),
        ]
        researchers = [
            FakeResearcher(id=f"researcher_{index}")
            for index in range(MAX_RESEARCHERS)
        ]

        async def emit(payload: dict) -> None:
            return None

        with (
            patch.object(
                workflow_module,
                "build_planner_agent",
                return_value=FakeAgent([initial_questions]),
            ),
            patch.object(
                workflow_module,
                "build_reviewer_agent",
                return_value=FakeAgent(review_decisions),
            ),
            patch.object(
                workflow_module,
                "build_report_writer_agent",
                return_value=FakeAgent(["# Final report"]),
            ),
            patch.object(
                workflow_module,
                "_build_researcher_executors",
                return_value=researchers,
            ),
        ):
            workflow = build_research_workflow(object(), emit)  # type: ignore[arg-type]
            outputs: list[tuple[str, object]] = []
            async for event in workflow.run(ResearchInput("Topic"), stream=True):
                if event.type == "output":
                    outputs.append((event.executor_id or "", event.data))

        self.assertEqual(
            [executor_id for executor_id, _ in outputs],
            [
                "planner",
                "reviewer",
                "planner",
                "reviewer",
                "report_writer",
            ],
        )
        self.assertEqual(outputs[0][1]["wave"], 1)  # type: ignore[index]
        self.assertEqual(outputs[2][1]["wave"], 2)  # type: ignore[index]
        self.assertEqual(outputs[-1][1], "# Final report")


if __name__ == "__main__":
    unittest.main()
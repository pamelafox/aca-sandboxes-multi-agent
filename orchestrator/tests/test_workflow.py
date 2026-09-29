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
from agents.workflow import (
    MAX_RESEARCHERS,
    ResearchCollector,
    ResearchDossier,
    ResearchInput,
    ResearchPlan,
    _parse_questions,
    _parse_review_decision,
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
    def __init__(self, outputs: list[str]) -> None:
        self._outputs = iter(outputs)

    async def run(self, prompt: str) -> SimpleNamespace:
        return SimpleNamespace(text=next(self._outputs))


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


class ParseQuestionsTests(unittest.TestCase):
    def test_parses_valid_questions(self) -> None:
        questions = [f"Question {index}?" for index in range(4)]

        self.assertEqual(_parse_questions(json.dumps(questions)), questions)

    def test_rejects_invalid_json_instead_of_falling_back(self) -> None:
        with self.assertRaisesRegex(ValueError, "invalid JSON"):
            _parse_questions("not json")

    def test_rejects_wrong_question_count(self) -> None:
        with self.assertRaisesRegex(ValueError, "4-6 questions"):
            _parse_questions(json.dumps(["Only one?"]))


class ParseReviewDecisionTests(unittest.TestCase):
    def test_parses_approved_decision(self) -> None:
        decision = _parse_review_decision(json.dumps({
            "status": "approved",
            "rationale": "Coverage is sufficient.",
            "follow_up_questions": [],
        }))

        self.assertEqual(decision.status, "approved")
        self.assertEqual(decision.follow_up_questions, [])

    def test_parses_follow_up_decision(self) -> None:
        decision = _parse_review_decision(json.dumps({
            "status": "needs_more_research",
            "rationale": "Two material gaps remain.",
            "follow_up_questions": ["Question one?", "Question two?"],
        }))

        self.assertEqual(decision.status, "needs_more_research")
        self.assertEqual(len(decision.follow_up_questions), 2)

    def test_rejects_invalid_follow_up_count(self) -> None:
        with self.assertRaisesRegex(ValueError, "2-4 follow-up"):
            _parse_review_decision(json.dumps({
                "status": "needs_more_research",
                "rationale": "A gap remains.",
                "follow_up_questions": ["Only one?"],
            }))


class ResearchWorkflowTests(unittest.IsolatedAsyncioTestCase):
    async def test_routes_follow_up_wave_then_writes_report(self) -> None:
        initial_questions = json.dumps([
            "Question one?",
            "Question two?",
            "Question three?",
            "Question four?",
        ])
        review_decisions = [
            json.dumps({
                "status": "needs_more_research",
                "rationale": "Two gaps remain.",
                "follow_up_questions": ["Follow-up one?", "Follow-up two?"],
            }),
            json.dumps({
                "status": "approved",
                "rationale": "The dossier now covers the material questions.",
                "follow_up_questions": [],
            }),
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
                "build_decomposer_agent",
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
                "research_lead",
                "reviewer",
                "research_lead",
                "reviewer",
                "report_writer",
            ],
        )
        self.assertEqual(outputs[0][1]["wave"], 1)  # type: ignore[index]
        self.assertEqual(outputs[2][1]["wave"], 2)  # type: ignore[index]
        self.assertEqual(outputs[-1][1], "# Final report")


if __name__ == "__main__":
    unittest.main()
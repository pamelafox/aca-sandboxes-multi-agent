import json
import unittest
from typing import Any

from agents.workflow import ResearchCollector, ResearchPlan, _parse_questions


class FakeContext:
    def __init__(self) -> None:
        self.sent: list[Any] = []

    async def send_message(self, value: Any) -> None:
        self.sent.append(value)


class ResearchCollectorTests(unittest.IsolatedAsyncioTestCase):
    async def test_releases_once_for_supported_researcher_counts(self) -> None:
        for expected in (4, 5, 6):
            with self.subTest(expected=expected):
                collector = ResearchCollector()
                context = FakeContext()

                await collector.set_plan(ResearchPlan(expected), context)  # type: ignore[arg-type]
                for index in range(expected - 1):
                    await collector.collect_response(f"response-{index}", context)  # type: ignore[arg-type]
                    self.assertEqual(context.sent, [])

                await collector.collect_response(f"response-{expected - 1}", context)  # type: ignore[arg-type]
                self.assertEqual(
                    context.sent,
                    [[f"response-{index}" for index in range(expected)]],
                )

                await collector.collect_response("late-response", context)  # type: ignore[arg-type]
                self.assertEqual(len(context.sent), 1)

    async def test_releases_when_plan_arrives_after_responses(self) -> None:
        collector = ResearchCollector()
        context = FakeContext()

        for index in range(5):
            await collector.collect_response(f"response-{index}", context)  # type: ignore[arg-type]
        self.assertEqual(context.sent, [])

        await collector.set_plan(ResearchPlan(5), context)  # type: ignore[arg-type]
        self.assertEqual(
            context.sent,
            [[f"response-{index}" for index in range(5)]],
        )


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


if __name__ == "__main__":
    unittest.main()
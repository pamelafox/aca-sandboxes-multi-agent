"""Reviewer agent that decides whether research is ready for final writing."""

from typing import Literal

from agent_framework import Agent
from pydantic import BaseModel, Field

from .chat_client import build_chat_client


REVIEWER_INSTRUCTIONS = (
    "You are the evidence reviewer in a research swarm. Evaluate whether the "
    "research dossier adequately answers the original topic. Check coverage, "
    "source support, contradictions, and whether important constraints were "
    "missed.\n\n"
    "Use status 'approved' when the evidence is sufficient for a responsible "
    "report. Use status 'needs_more_research' only for material gaps, and then "
    "provide 2-4 independently answerable follow-up questions. Each follow-up "
    "question must include all context an isolated researcher needs. When the "
    "prompt says no research waves remain, approve the best available dossier "
    "and explain any limitations in the rationale. For approved dossiers, "
    "leave follow_up_questions empty."
)


class ReviewDecision(BaseModel):
    """Structured routing decision returned by the reviewer agent."""
    status: Literal["approved", "needs_more_research"]
    rationale: str
    follow_up_questions: list[str] = Field(
        description="2-4 standalone questions when more research is needed, otherwise empty"
    )


def build_reviewer_agent() -> Agent:
    return Agent(
        client=build_chat_client(),
        instructions=REVIEWER_INSTRUCTIONS,
        name="reviewer",
        default_options={"reasoning": {"effort": "medium"}},
    )

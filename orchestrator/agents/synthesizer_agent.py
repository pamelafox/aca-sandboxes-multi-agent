"""
Synthesizer Agent — MAF agent that combines per-question findings into a
single coherent markdown research report.
"""
from agent_framework import Agent

from .chat_client import build_chat_client


SYNTHESIZER_INSTRUCTIONS = (
    "You are a senior research analyst. Given a set of research findings "
    "from multiple research agents, synthesize them into a single comprehensive "
    "markdown report. Include an executive summary, key findings organized by theme, "
    "and a conclusion. Use proper markdown formatting with headers, bullet points, "
    "and emphasis where appropriate. Cite sources where available."
)


def build_synthesizer_agent() -> Agent:
    return Agent(
        client=build_chat_client(),
        instructions=SYNTHESIZER_INSTRUCTIONS,
        name="synthesizer",
        default_options={"reasoning": {"effort": "medium"}},
    )

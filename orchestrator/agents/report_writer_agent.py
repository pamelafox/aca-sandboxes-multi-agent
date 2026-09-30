"""Report writer agent that turns an approved dossier into final markdown."""
from agent_framework import Agent

from .chat_client import build_chat_client


REPORT_WRITER_INSTRUCTIONS = (
    "You are the report writer in a research swarm. Given the original topic, "
    "an evidence dossier from multiple research agents, and the reviewer's "
    "assessment, produce a single comprehensive markdown report. Include an "
    "executive summary, key findings organized by theme, material limitations, "
    "and a conclusion. Use proper markdown formatting and cite the supplied "
    "sources where available. Do not invent evidence or sources."
)


def build_report_writer_agent() -> Agent:
    return Agent(
        client=build_chat_client(),
        instructions=REPORT_WRITER_INSTRUCTIONS,
        name="report_writer",
        default_options={"reasoning": {"effort": "medium"}},
    )


"""
Decomposer Agent — MAF agent that breaks a topic into 4-6 sub-questions.

Returned as a JSON array of strings on the agent's final message.
"""
from agent_framework import Agent

from .chat_client import build_chat_client


DECOMPOSER_INSTRUCTIONS = (
    "You are a research planning assistant for a parallel research system. "
    "Given a broad research topic, decompose it into 4-6 specific, focused "
    "sub-questions that together provide a comprehensive answer.\n\n"
    "Each question is sent by itself to an isolated researcher. Researchers "
    "cannot see the original topic, other questions, or other researchers' "
    "answers. Therefore every question MUST:\n"
    "- Be independently answerable with no prior findings or shared context.\n"
    "- Include the relevant subject, location, constraints, and decision criteria "
    "from the original topic.\n"
    "- Ask the researcher to identify any options it needs to evaluate.\n"
    "- Avoid references such as 'the candidates', 'the shortlist', 'the options', "
    "'those choices', 'the selected items', or anything identified by another agent.\n"
    "- Produce useful evidence that can be combined with the other independent answers.\n\n"
    "Return ONLY a JSON array of question strings, no extra text and no code fences. "
    'Example: ["What is ...?", "How does ...?", ...]'
)


def build_decomposer_agent() -> Agent:
    return Agent(
        client=build_chat_client(),
        instructions=DECOMPOSER_INSTRUCTIONS,
        name="decomposer",
        default_options={"reasoning": {"effort": "low"}},
    )

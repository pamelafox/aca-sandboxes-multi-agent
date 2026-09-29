"""Orchestrator agents: MAF agents + Workflow that drive the research swarm."""
from .workflow import (
    MAX_RESEARCHERS,
    MAX_RESEARCH_WAVES,
    ResearchInput,
    build_research_workflow,
)

__all__ = [
    "MAX_RESEARCHERS",
    "MAX_RESEARCH_WAVES",
    "ResearchInput",
    "build_research_workflow",
]

"""Insight — SBAgent + DB persistence.

:class:`InsightAgent` is the LLM authoring primitive (single-call
SBAgent that produces user-facing prose); :class:`InsightGenerator`
(re-exported from :mod:`.persistence`) keeps the orchestration logic
— when to surface which insight, which domain, which trigger — and
owns the ``_insights`` table.

sensitivity_tier: 2
"""

from src.agents.insight.agent import (
    DEFAULT_SYSTEM_PROMPT,
    InsightAgent,
    register_insight_agent,
)
from src.agents.insight.persistence import (
    Insight,
    InsightGenerator,
)

__all__ = [
    "DEFAULT_SYSTEM_PROMPT",
    "Insight",
    "InsightAgent",
    "InsightGenerator",
    "register_insight_agent",
]

"""Pydantic AI weekly digest author.

Takes an already-assembled summary of the week's messages, events,
and notes; returns a :class:`DigestSummary` with named sections.
The legacy ``WeeklyDigestAgent`` (subclassing ``BrainAgent``)
keeps the DB scans + persistence; this agent is the LLM step it
delegates to.

sensitivity_tier: 2
"""

from __future__ import annotations

import logging

from src.agents.core.agent_base import SBAgent
from src.agents.core.output_types import DigestSummary
from src.agents.core.scheduler import Tier
from src.models.prompt_cache import PROMPTS_DIR, FrozenPromptTemplate

logger = logging.getLogger(__name__)

_TEMPLATE = FrozenPromptTemplate(PROMPTS_DIR / "weekly_digest_v1.txt")
DEFAULT_SYSTEM_PROMPT = _TEMPLATE.prefix


class WeeklyDigestAgent(SBAgent[str, DigestSummary]):
    """Author a structured weekly digest from a prepared data summary.

    sensitivity_tier: 2
    """

    agent_id = "weekly_digest"
    output_type = DigestSummary
    tier = Tier.BACKGROUND
    system_prompt = DEFAULT_SYSTEM_PROMPT

    def author(self, data_summary: str) -> DigestSummary | None:
        """Convenience wrapper returning the digest or None on failure.

        sensitivity_tier: 2
        """
        if not data_summary or not data_summary.strip():
            return None
        record = self.run(data_summary)
        if record.output is None or record.error is not None:
            return None
        return record.output


def register_weekly_digest_agent() -> None:
    """Register the weekly digest agent in the registry.

    sensitivity_tier: 1
    """
    from src.agents.core.config_store import AgentConfig
    from src.agents.core.registry import (
        AgentDefinition,
        get_agent,
        register_agent,
    )

    if get_agent("weekly_digest") is not None:
        return

    default = AgentConfig(
        agent_id="weekly_digest",
        system_prompt=DEFAULT_SYSTEM_PROMPT,
        model_route="inherit",
        model_override=None,
        enabled_tools=(),
        enabled_skills=(),
        editable=False,
    )
    register_agent(AgentDefinition(
        agent_id="weekly_digest",
        name="Weekly Digest Author",
        description=(
            "Writes the user's weekly digest from a prepared data "
            "summary. Invoked by the built-in weekly-digest "
            "scheduled job."
        ),
        category="author",
        parent_agent="brain",
        tier=Tier.BACKGROUND,
        max_sensitivity_tier=2,
        editable=False,
        default_config=default,
        available_tools=(),
        available_skills=(),
        output_schema="DigestSummary",
        pattern="single",
        factory=WeeklyDigestAgent,
        tags=("author", "indirect", "builtin"),
    ))


__all__ = [
    "DEFAULT_SYSTEM_PROMPT",
    "WeeklyDigestAgent",
    "register_weekly_digest_agent",
]

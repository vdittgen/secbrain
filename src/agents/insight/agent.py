"""Pydantic AI insight author.

Takes a contextual prompt (already assembled by the legacy
``InsightGenerator``) and returns a :class:`InsightDraft` with the
user-facing title, body, and an optional follow-up question. The
caller wraps the draft into a full :class:`Insight` by attaching
``id``, ``domain``, ``trigger``, ``pattern``, ``generated_at``,
``sensitivity_tier``, and any ``sources`` it retrieved.

This is intentionally a thin authoring primitive — the insight
generation strategy (which patterns to look at, which contacts to
surface) stays in the orchestrator, not in the LLM.

sensitivity_tier: 2
"""

from __future__ import annotations

import logging

from src.agents.core.agent_base import SBAgent
from src.agents.core.output_types import InsightDraft
from src.agents.core.scheduler import Tier

logger = logging.getLogger(__name__)

DEFAULT_SYSTEM_PROMPT = """\
You are a proactive personal assistant authoring a single insight for \
the user. Given retrieved context and a question framing, return an \
InsightDraft with a short title and a concise, actionable body.

Rules:
- ``title``: <= 8 words, headline-style, no trailing punctuation.
- ``content``: 1-3 short paragraphs (or 2-4 bullet points). Be \
specific. Reference the user's data when relevant. Do NOT pad with \
hedging or generic advice.
- ``suggested_followup``: a single short question the user could ask \
to dig deeper. Optional — leave null if no obvious follow-up exists.
- Never claim to have executed actions; you only surface insights.
- Never fabricate names, dates, or numbers. If context is too thin, \
write the shortest honest title + body and skip the follow-up.\
"""


class InsightAgent(SBAgent[str, InsightDraft]):
    """Author the user-facing portion of a proactive insight.

    Deps is the assembled prompt (context + framing) that the legacy
    generator built. Output is a structured :class:`InsightDraft`.

    sensitivity_tier: 2
    """

    agent_id = "insight"
    output_type = InsightDraft
    tier = Tier.PROACTIVE
    system_prompt = DEFAULT_SYSTEM_PROMPT

    def author(self, prompt: str) -> InsightDraft | None:
        """Convenience wrapper returning the draft or None on failure.

        sensitivity_tier: 2
        """
        if not prompt or not prompt.strip():
            return None
        record = self.run(prompt)
        if record.output is None or record.error is not None:
            return None
        return record.output


def register_insight_agent() -> None:
    """Register the insight agent in the global agent registry.

    sensitivity_tier: 1
    """
    from src.agents.core.config_store import AgentConfig
    from src.agents.core.registry import (
        AgentDefinition,
        get_agent,
        register_agent,
    )

    if get_agent("insight") is not None:
        return

    default = AgentConfig(
        agent_id="insight",
        system_prompt=DEFAULT_SYSTEM_PROMPT,
        model_route="inherit",
        model_override=None,
        enabled_tools=(),
        enabled_skills=(),
        editable=False,
    )
    register_agent(AgentDefinition(
        agent_id="insight",
        name="Insight Author",
        description=(
            "Writes the user-facing title + body for a proactive "
            "insight, given retrieved context. The legacy "
            "InsightGenerator decides when to invoke and attaches "
            "metadata."
        ),
        category="author",
        parent_agent="brain",
        tier=Tier.PROACTIVE,
        max_sensitivity_tier=2,
        editable=False,
        default_config=default,
        available_tools=(),
        available_skills=(),
        output_schema="InsightDraft",
        pattern="single",
        factory=InsightAgent,
        tags=("author",),
    ))


__all__ = [
    "DEFAULT_SYSTEM_PROMPT",
    "InsightAgent",
    "register_insight_agent",
]

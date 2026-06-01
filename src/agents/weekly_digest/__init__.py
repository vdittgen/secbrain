"""Weekly digest as an SBAgent.

Migration target: ``src/extensions/builtin/weekly_digest/agent.py``.
The legacy built-in (which subclasses ``BrainAgent`` and writes
to ``ext_weekly_digest_summaries``) keeps its DB scans + persistence;
this module supplies the LLM authoring primitive.

sensitivity_tier: 2
"""

from src.agents.weekly_digest.agent import (
    DEFAULT_SYSTEM_PROMPT,
    WeeklyDigestAgent,
    register_weekly_digest_agent,
)

__all__ = [
    "DEFAULT_SYSTEM_PROMPT",
    "WeeklyDigestAgent",
    "register_weekly_digest_agent",
]

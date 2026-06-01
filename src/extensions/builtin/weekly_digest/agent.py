"""Weekly Digest agent — generates a weekly summary.

Reads messages and events from the past week, uses the LLM to
produce a human-readable digest, and writes it to
``ext_weekly_digest_summaries``.

sensitivity_tier: 2 (reads personal data, writes digest)
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from src.agent_runtime.base import BrainAgent
from src.agent_runtime.context import AgentContext
from src.agent_runtime.models import AgentResult


class WeeklyDigestAgent(BrainAgent):
    """Generates a weekly digest of messages, events, and notes.

    sensitivity_tier: 2
    """

    manifest = None  # Loaded by AgentRunner from manifest.yaml

    def run(self, context: AgentContext) -> AgentResult:
        """Fetch last 7 days of data, generate digest via LLM, write result.

        sensitivity_tier: 2
        """
        context.log("Starting weekly digest generation")

        week_ago = (
            datetime.now(tz=timezone.utc) - timedelta(days=7)
        ).isoformat()

        # Fetch recent messages.
        messages = context.query(
            f"SELECT sender, content, timestamp FROM raw_messages "
            f"WHERE timestamp >= '{week_ago}' "
            f"ORDER BY timestamp DESC LIMIT 50",
        )
        context.log(f"Fetched {len(messages)} messages")

        # Fetch recent events.
        events = context.query(
            f"SELECT title, start_time, location FROM raw_calendar_events "
            f"WHERE start_time >= '{week_ago}' "
            f"ORDER BY start_time LIMIT 30",
        )
        context.log(f"Fetched {len(events)} events")

        # Fetch recent notes.
        notes = context.query(
            f"SELECT title, content FROM raw_notes "
            f"WHERE created_at >= '{week_ago}' "
            f"ORDER BY created_at DESC LIMIT 20",
        )
        context.log(f"Fetched {len(notes)} notes")

        # Build context for LLM.
        data_summary = _build_data_summary(messages, events, notes)

        # Generate digest via LLM.
        digest_text = context.ask_llm(
            "Generate a concise weekly digest summarizing the key highlights, "
            "important meetings, notable messages, and any new notes. "
            "Organize by category: Communication, Schedule, Notes. "
            "Be brief and actionable.",
            context_data=data_summary,
        )

        if not digest_text:
            digest_text = _fallback_digest(messages, events, notes)

        # Write the digest.
        context.write("ext_weekly_digest_summaries", [{
            "id": str(uuid.uuid4()),
            "week_start": week_ago,
            "digest": digest_text,
            "message_count": len(messages),
            "event_count": len(events),
            "note_count": len(notes),
        }])

        context.log("Weekly digest written successfully")

        return AgentResult(
            agent_id="weekly-digest",
            status="success",
            output=digest_text,
        )


def _build_data_summary(
    messages: list[dict],
    events: list[dict],
    notes: list[dict],
) -> str:
    """Build a text summary of the week's data for the LLM.

    sensitivity_tier: 2
    """
    parts: list[str] = []

    if messages:
        parts.append(f"Messages ({len(messages)} total):")
        for m in messages[:10]:
            sender = m.get("sender", "?")
            body = str(m.get("content", ""))[:100]
            parts.append(f"  - From {sender}: {body}")

    if events:
        parts.append(f"\nEvents ({len(events)} total):")
        for e in events[:10]:
            parts.append(f"  - {e.get('title', '?')} at {e.get('start_time', '?')}")

    if notes:
        parts.append(f"\nNotes ({len(notes)} total):")
        for n in notes[:10]:
            parts.append(f"  - {n.get('title', '?')}: {str(n.get('content', ''))[:80]}")

    return "\n".join(parts) if parts else "No data available this week."


def _fallback_digest(
    messages: list[dict],
    events: list[dict],
    notes: list[dict],
) -> str:
    """Generate a simple digest without LLM.

    sensitivity_tier: 2
    """
    return (
        f"Weekly Summary: {len(messages)} messages, "
        f"{len(events)} events, {len(notes)} notes this week."
    )

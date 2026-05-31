"""Tests for the relationship_tracker built-in agent."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import yaml
from src.extensions.builtin.relationship_tracker.agent import (
    RelationshipTrackerAgent,
    _days_since,
    _generate_nudge,
)

MANIFEST_PATH = (
    Path(__file__).resolve().parents[4]
    / "src"
    / "extensions"
    / "builtin"
    / "relationship_tracker"
    / "manifest.yaml"
)


# -----------------------------------------------------------------------
# Manifest correctness
# -----------------------------------------------------------------------


class TestManifest:
    def test_manifest_file_exists(self) -> None:
        assert MANIFEST_PATH.exists()

    def test_manifest_fields(self) -> None:
        raw = yaml.safe_load(MANIFEST_PATH.read_text())
        assert raw["id"] == "relationship-tracker"
        assert raw["max_sensitivity_tier"] == 2
        assert raw["can_use_llm"] is True
        assert "scheduled" in raw["triggers"]
        assert "manual" in raw["triggers"]

    def test_manifest_tables(self) -> None:
        raw = yaml.safe_load(MANIFEST_PATH.read_text())
        table_names = [t["table"] for t in raw["tables"]]
        assert "raw_contacts" in table_names
        assert "raw_messages" in table_names

    def test_manifest_write_tables(self) -> None:
        raw = yaml.safe_load(MANIFEST_PATH.read_text())
        assert "ext_relationship_tracker_nudges" in raw["write_tables"]

    def test_manifest_schedule(self) -> None:
        raw = yaml.safe_load(MANIFEST_PATH.read_text())
        assert raw["schedule"] == "0 8 * * *"


# -----------------------------------------------------------------------
# Agent execution
# -----------------------------------------------------------------------


class TestRelationshipTrackerAgent:
    def _make_context(
        self,
        stale_contacts: list[dict] | None = None,
        llm_response: str = "LLM nudge text",
    ) -> MagicMock:
        ctx = MagicMock()
        ctx.query.return_value = stale_contacts or []
        ctx.ask_llm.return_value = llm_response
        ctx.write.return_value = None
        ctx.log.return_value = None
        return ctx

    def test_run_no_stale_contacts(self) -> None:
        ctx = self._make_context(stale_contacts=[])
        agent = RelationshipTrackerAgent()
        result = agent.run(ctx)

        assert result.status == "success"
        assert "No follow-ups" in result.output
        ctx.write.assert_not_called()

    def test_run_with_stale_contacts(self) -> None:
        contacts = [
            {
                "id": "c1",
                "name": "Alice",
                "relationship": "friend",
                "last_contact": "2024-01-01T00:00:00+00:00",
            },
        ]
        ctx = self._make_context(stale_contacts=contacts)
        agent = RelationshipTrackerAgent()
        result = agent.run(ctx)

        assert result.status == "success"
        assert "1 follow-up" in result.output
        ctx.write.assert_called_once()
        call_args = ctx.write.call_args
        assert call_args[0][0] == "ext_relationship_tracker_nudges"

    def test_run_uses_llm_for_nudges(self) -> None:
        contacts = [
            {
                "id": "c1",
                "name": "Bob",
                "relationship": "colleague",
                "last_contact": "2024-06-01T00:00:00+00:00",
            },
        ]
        ctx = self._make_context(stale_contacts=contacts)
        agent = RelationshipTrackerAgent()
        agent.run(ctx)

        ctx.ask_llm.assert_called_once()

    def test_run_fallback_when_llm_empty(self) -> None:
        contacts = [
            {
                "id": "c1",
                "name": "Carol",
                "relationship": "friend",
                "last_contact": None,
            },
        ]
        ctx = self._make_context(stale_contacts=contacts, llm_response="")
        agent = RelationshipTrackerAgent()
        agent.run(ctx)

        # Write should still be called — uses fallback nudge
        ctx.write.assert_called_once()
        written_data = ctx.write.call_args[0][1]
        assert len(written_data) == 1
        assert "Carol" in written_data[0]["nudge"]


# -----------------------------------------------------------------------
# Helper functions
# -----------------------------------------------------------------------


class TestDaysSince:
    def test_none_returns_999(self) -> None:
        assert _days_since(None) == 999

    def test_invalid_returns_999(self) -> None:
        assert _days_since("not-a-date") == 999

    def test_valid_iso_date(self) -> None:
        from datetime import datetime, timedelta, timezone

        recent = (datetime.now(tz=timezone.utc) - timedelta(days=5)).isoformat()
        result = _days_since(recent)
        assert 4 <= result <= 6

    def test_naive_datetime(self) -> None:
        from datetime import datetime, timedelta

        recent = (datetime.now() - timedelta(days=10)).isoformat()
        result = _days_since(recent)
        assert 9 <= result <= 11


class TestGenerateNudge:
    def test_short_absence(self) -> None:
        nudge = _generate_nudge("Alice", "friend", 45)
        assert "Alice" in nudge
        assert "45 days" in nudge
        assert "catch-up" in nudge.lower()

    def test_long_absence(self) -> None:
        nudge = _generate_nudge("Bob", "colleague", 120)
        assert "Bob" in nudge
        assert "120 days" in nudge
        assert "hello" in nudge.lower()

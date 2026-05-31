"""Tests for the weekly_digest built-in agent."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import yaml
from src.extensions.builtin.weekly_digest.agent import (
    WeeklyDigestAgent,
    _build_data_summary,
    _fallback_digest,
)

MANIFEST_PATH = (
    Path(__file__).resolve().parents[4]
    / "src"
    / "extensions"
    / "builtin"
    / "weekly_digest"
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
        assert raw["id"] == "weekly-digest"
        assert raw["max_sensitivity_tier"] == 2
        assert raw["can_use_llm"] is True
        assert "scheduled" in raw["triggers"]
        assert "manual" in raw["triggers"]

    def test_manifest_tables(self) -> None:
        raw = yaml.safe_load(MANIFEST_PATH.read_text())
        table_names = [t["table"] for t in raw["tables"]]
        assert "raw_messages" in table_names
        assert "raw_calendar_events" in table_names
        assert "raw_notes" in table_names

    def test_manifest_write_tables(self) -> None:
        raw = yaml.safe_load(MANIFEST_PATH.read_text())
        assert "ext_weekly_digest_summaries" in raw["write_tables"]

    def test_manifest_schedule(self) -> None:
        raw = yaml.safe_load(MANIFEST_PATH.read_text())
        assert raw["schedule"] == "0 9 * * 1"


# -----------------------------------------------------------------------
# Agent execution
# -----------------------------------------------------------------------


class TestWeeklyDigestAgent:
    def _make_context(
        self,
        messages: list[dict] | None = None,
        events: list[dict] | None = None,
        notes: list[dict] | None = None,
        llm_response: str = "LLM digest",
    ) -> MagicMock:
        """Build a mock AgentContext."""
        ctx = MagicMock()

        call_count = {"n": 0}
        all_data = [
            messages or [],
            events or [],
            notes or [],
        ]

        def query_side_effect(sql: str) -> list[dict]:
            idx = call_count["n"]
            call_count["n"] += 1
            return all_data[idx] if idx < len(all_data) else []

        ctx.query.side_effect = query_side_effect
        ctx.ask_llm.return_value = llm_response
        ctx.write.return_value = None
        ctx.log.return_value = None
        return ctx

    def test_run_success_with_data(self) -> None:
        ctx = self._make_context(
            messages=[
                {"sender": "Alice", "content": "Hello", "timestamp": "2025-01-01"},
            ],
            events=[
                {"title": "Standup", "start_time": "2025-01-02", "location": "Zoom"},
            ],
            notes=[{"title": "Ideas", "content": "Something new"}],
        )
        agent = WeeklyDigestAgent()
        result = agent.run(ctx)

        assert result.status == "success"
        assert result.agent_id == "weekly-digest"
        ctx.write.assert_called_once()
        call_args = ctx.write.call_args
        assert call_args[0][0] == "ext_weekly_digest_summaries"

    def test_run_uses_llm(self) -> None:
        ctx = self._make_context(
            messages=[{"sender": "Bob", "content": "Msg", "timestamp": "2025-01-01"}],
        )
        agent = WeeklyDigestAgent()
        agent.run(ctx)

        ctx.ask_llm.assert_called_once()

    def test_run_fallback_when_llm_returns_empty(self) -> None:
        ctx = self._make_context(
            messages=[{"sender": "X", "content": "Y", "timestamp": "now"}],
            llm_response="",
        )
        agent = WeeklyDigestAgent()
        result = agent.run(ctx)

        assert "1 messages" in result.output


# -----------------------------------------------------------------------
# Helper functions
# -----------------------------------------------------------------------


class TestBuildDataSummary:
    def test_empty_data(self) -> None:
        assert _build_data_summary([], [], []) == "No data available this week."

    def test_messages_included(self) -> None:
        summary = _build_data_summary(
            [{"sender": "Alice", "content": "Hello"}], [], [],
        )
        assert "Alice" in summary
        assert "Messages" in summary

    def test_events_included(self) -> None:
        summary = _build_data_summary(
            [], [{"title": "Standup", "start_time": "10am"}], [],
        )
        assert "Standup" in summary

    def test_notes_included(self) -> None:
        summary = _build_data_summary(
            [], [], [{"title": "Ideas", "content": "Brainstorm"}],
        )
        assert "Ideas" in summary


class TestFallbackDigest:
    def test_format(self) -> None:
        result = _fallback_digest(
            [{"x": 1}, {"x": 2}],
            [{"y": 1}],
            [],
        )
        assert "2 messages" in result
        assert "1 events" in result
        assert "0 notes" in result

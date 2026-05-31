"""Tests for agent_models.py — frozen dataclasses, defaults, enums."""

from __future__ import annotations

from src.agent_runtime.models import (
    AgentManifest,
    AgentResult,
    AgentStatus,
    TablePermission,
    TriggerMode,
)


class TestTriggerMode:
    def test_enum_values(self) -> None:
        assert TriggerMode.SCHEDULED.value == "scheduled"
        assert TriggerMode.ON_DATA_CHANGE.value == "on_data_change"
        assert TriggerMode.MANUAL.value == "manual"
        assert TriggerMode.ON_QUERY.value == "on_query"

    def test_str_enum_is_string(self) -> None:
        assert isinstance(TriggerMode.MANUAL, str)
        assert TriggerMode.MANUAL == "manual"


class TestTablePermission:
    def test_frozen(self) -> None:
        tp = TablePermission(table="raw_messages", max_tier=2)
        try:
            tp.table = "other"  # type: ignore[misc]
            raise AssertionError("Should be frozen")
        except AttributeError:
            pass

    def test_defaults(self) -> None:
        tp = TablePermission(table="raw_notes", max_tier=1)
        assert tp.columns == ()


class TestAgentManifest:
    def test_frozen(self) -> None:
        m = AgentManifest(
            id="test", name="Test", version="1.0.0",
            description="desc", author="author",
        )
        try:
            m.id = "other"  # type: ignore[misc]
            raise AssertionError("Should be frozen")
        except AttributeError:
            pass

    def test_defaults(self) -> None:
        m = AgentManifest(
            id="test", name="Test", version="1.0.0",
            description="desc", author="author",
        )
        assert m.tables == ()
        assert m.max_sensitivity_tier == 1
        assert m.can_use_llm is False
        assert m.write_tables == ()
        assert m.skills == ()
        assert m.triggers == (TriggerMode.MANUAL,)
        assert m.schedule is None
        assert m.memory_mb == 256
        assert m.timeout_seconds == 60
        assert m.category == "general"
        assert m.builtin is False

    def test_with_tables(self) -> None:
        m = AgentManifest(
            id="test", name="Test", version="1.0.0",
            description="desc", author="author",
            tables=(
                TablePermission(table="raw_messages", max_tier=2),
                TablePermission(table="raw_notes", max_tier=1),
            ),
            max_sensitivity_tier=2,
        )
        assert len(m.tables) == 2
        assert m.tables[0].table == "raw_messages"
        assert m.max_sensitivity_tier == 2


class TestAgentResult:
    def test_defaults(self) -> None:
        r = AgentResult(agent_id="test", status="success")
        assert r.output == ""
        assert r.tables_written == ()
        assert r.rows_written == 0
        assert r.llm_calls == 0
        assert r.duration_ms == 0.0
        assert r.error is None

    def test_frozen(self) -> None:
        r = AgentResult(agent_id="test", status="success")
        try:
            r.status = "error"  # type: ignore[misc]
            raise AssertionError("Should be frozen")
        except AttributeError:
            pass


class TestAgentStatus:
    def test_defaults(self) -> None:
        s = AgentStatus(
            agent_id="test", name="Test", description="desc",
            category="general", status="idle", builtin=True,
        )
        assert s.triggers == ()
        assert s.max_sensitivity_tier == 1
        assert s.last_run_at is None
        assert s.last_result is None
        assert s.error is None

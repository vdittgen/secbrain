"""Tests for sensitivity_guard.py — field classification, table access,
query validation, tier injection, write validation, and audit logging."""

from __future__ import annotations

import json
from pathlib import Path

from src.agent_runtime.models import AgentManifest, TablePermission
from src.agent_runtime.sensitivity_guard import (
    DEFAULT_TIER,
    AccessDecision,
    SensitivityGuard,
)


def _make_manifest(**overrides) -> AgentManifest:
    defaults = {
        "id": "test-agent",
        "name": "Test Agent",
        "version": "1.0.0",
        "description": "Test",
        "author": "test",
        "tables": (
            TablePermission(table="raw_messages", max_tier=2),
            TablePermission(table="raw_notes", max_tier=1),
        ),
        "max_sensitivity_tier": 2,
        "write_tables": ("ext_test_agent_results",),
    }
    defaults.update(overrides)
    return AgentManifest(**defaults)


def _make_guard(
    manifest: AgentManifest | None = None,
    audit_path: Path | None = None,
) -> SensitivityGuard:
    m = manifest or _make_manifest()
    return SensitivityGuard(
        agent_id=m.id,
        manifest=m,
        audit_path=audit_path,
    )


# -----------------------------------------------------------------------
# classify_fields
# -----------------------------------------------------------------------


class TestClassifyFields:
    def test_known_tier1_field(self) -> None:
        guard = _make_guard()
        assert guard.classify_fields(["id", "source"]) == 1

    def test_known_tier2_field(self) -> None:
        guard = _make_guard()
        assert guard.classify_fields(["name", "email"]) == 2

    def test_known_tier3_field(self) -> None:
        guard = _make_guard()
        assert guard.classify_fields(["content"]) == 3

    def test_unknown_field_defaults_to_tier3(self) -> None:
        guard = _make_guard()
        assert guard.classify_fields(["completely_unknown_field"]) == DEFAULT_TIER
        assert DEFAULT_TIER == 3

    def test_mixed_fields_returns_max(self) -> None:
        guard = _make_guard()
        assert guard.classify_fields(["id", "name", "content"]) == 3

    def test_empty_fields_returns_tier1(self) -> None:
        guard = _make_guard()
        assert guard.classify_fields([]) == 1


# -----------------------------------------------------------------------
# check_table_access
# -----------------------------------------------------------------------


class TestCheckTableAccess:
    def test_permitted_table(self) -> None:
        guard = _make_guard()
        decision = guard.check_table_access("raw_messages")
        assert decision.allowed is True
        assert decision.effective_tier == 2

    def test_denied_table(self) -> None:
        guard = _make_guard()
        decision = guard.check_table_access("raw_health_metrics")
        assert decision.allowed is False

    def test_ext_table_always_allowed(self) -> None:
        guard = _make_guard()
        decision = guard.check_table_access("ext_test_agent_results")
        assert decision.allowed is True
        assert decision.effective_tier == 1


# -----------------------------------------------------------------------
# check_query
# -----------------------------------------------------------------------


class TestCheckQuery:
    def test_allowed_select(self) -> None:
        guard = _make_guard()
        decision = guard.check_query(
            "SELECT id, sender FROM raw_messages LIMIT 10",
        )
        assert decision.allowed is True
        assert decision.effective_tier == 2

    def test_denied_unpermitted_table(self) -> None:
        guard = _make_guard()
        decision = guard.check_query(
            "SELECT * FROM raw_health_metrics",
        )
        assert decision.allowed is False

    def test_rejects_drop(self) -> None:
        guard = _make_guard()
        decision = guard.check_query("DROP TABLE raw_messages")
        assert decision.allowed is False
        assert "DDL" in decision.reason

    def test_rejects_alter(self) -> None:
        guard = _make_guard()
        decision = guard.check_query("ALTER TABLE raw_messages ADD COLUMN x VARCHAR")
        assert decision.allowed is False

    def test_rejects_write_to_non_ext_table(self) -> None:
        guard = _make_guard()
        decision = guard.check_query(
            "INSERT INTO raw_messages (id) VALUES ('x')",
        )
        assert decision.allowed is False
        assert "non-extension" in decision.reason

    def test_allows_write_to_ext_table(self) -> None:
        guard = _make_guard()
        decision = guard.check_query(
            "INSERT INTO ext_test_agent_results (id) VALUES ('x')",
        )
        assert decision.allowed is True

    def test_multiple_tables_in_join(self) -> None:
        guard = _make_guard()
        decision = guard.check_query(
            "SELECT m.id FROM raw_messages m JOIN raw_notes n ON m.id = n.id",
        )
        assert decision.allowed is True
        assert decision.effective_tier == 2  # max of messages(2) and notes(1)


# -----------------------------------------------------------------------
# inject_tier_filter
# -----------------------------------------------------------------------


class TestInjectTierFilter:
    def test_adds_where_clause(self) -> None:
        guard = _make_guard()
        sql = "SELECT * FROM raw_messages"
        result = guard.inject_tier_filter(sql, 2)
        assert "WHERE sensitivity_tier <= 2" in result

    def test_appends_to_existing_where(self) -> None:
        guard = _make_guard()
        sql = "SELECT * FROM raw_messages WHERE sender = 'alice'"
        result = guard.inject_tier_filter(sql, 2)
        assert "sensitivity_tier <= 2" in result
        assert "AND" in result

    def test_tier3_returns_unchanged(self) -> None:
        guard = _make_guard()
        sql = "SELECT * FROM raw_messages"
        result = guard.inject_tier_filter(sql, 3)
        assert result == sql

    def test_inserts_before_limit(self) -> None:
        guard = _make_guard()
        sql = "SELECT * FROM raw_messages LIMIT 10"
        result = guard.inject_tier_filter(sql, 2)
        assert "WHERE sensitivity_tier <= 2" in result
        assert result.index("sensitivity_tier") < result.index("LIMIT")

    def test_inserts_before_order_by(self) -> None:
        guard = _make_guard()
        sql = "SELECT * FROM raw_messages ORDER BY timestamp"
        result = guard.inject_tier_filter(sql, 1)
        assert "WHERE sensitivity_tier <= 1" in result
        assert result.index("sensitivity_tier") < result.index("ORDER BY")


# -----------------------------------------------------------------------
# validate_write_table
# -----------------------------------------------------------------------


class TestValidateWriteTable:
    def test_correct_prefix_and_in_manifest(self) -> None:
        guard = _make_guard()
        assert guard.validate_write_table("ext_test_agent_results") is True

    def test_wrong_prefix(self) -> None:
        guard = _make_guard()
        assert guard.validate_write_table("raw_messages") is False

    def test_correct_prefix_but_not_in_manifest(self) -> None:
        guard = _make_guard()
        assert guard.validate_write_table("ext_test_agent_other") is False

    def test_other_agent_prefix(self) -> None:
        guard = _make_guard()
        assert guard.validate_write_table("ext_other_agent_data") is False


# -----------------------------------------------------------------------
# log_access
# -----------------------------------------------------------------------


class TestLogAccess:
    def test_writes_audit_entry(self, tmp_path: Path) -> None:
        audit_file = tmp_path / "audit.jsonl"
        guard = _make_guard(audit_path=audit_file)

        decision = AccessDecision(allowed=True, reason="ok", effective_tier=1)
        guard.log_access(decision, {"sql": "SELECT 1"})

        lines = audit_file.read_text().strip().split("\n")
        assert len(lines) == 1
        entry = json.loads(lines[0])
        assert entry["agent_id"] == "test-agent"
        assert entry["allowed"] is True
        assert entry["sql"] == "SELECT 1"

    def test_appends_multiple_entries(self, tmp_path: Path) -> None:
        audit_file = tmp_path / "audit.jsonl"
        guard = _make_guard(audit_path=audit_file)

        d1 = AccessDecision(allowed=True, reason="ok", effective_tier=1)
        d2 = AccessDecision(allowed=False, reason="denied", effective_tier=3)
        guard.log_access(d1, {"sql": "SELECT 1"})
        guard.log_access(d2, {"sql": "DROP TABLE x"})

        lines = audit_file.read_text().strip().split("\n")
        assert len(lines) == 2

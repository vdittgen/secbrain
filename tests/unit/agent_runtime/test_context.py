"""Tests for agent_context.py — query routing, LLM gating, write isolation,
skill calls, logging, and counters."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest
from src.agent_runtime.context import AgentAccessDeniedError, AgentContext
from src.agent_runtime.models import AgentManifest, TablePermission
from src.agent_runtime.sensitivity_guard import SensitivityGuard
from src.agent_runtime.skills import Skill
from src.models.llm_gateway import set_provider_factory_for_tests
from src.models.llm_provider import LLMProvider, LLMResponse


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
        "can_use_llm": True,
        "write_tables": ("ext_test_agent_results",),
    }
    defaults.update(overrides)
    return AgentManifest(**defaults)


def _make_context(
    manifest: AgentManifest | None = None,
    db_return: list[dict] | None = None,
    skills: dict | None = None,
    settings: dict | None = None,
    audit_path: Path | None = None,
    llm_provider: LLMProvider | None = None,
) -> tuple[AgentContext, MagicMock]:
    m = manifest or _make_manifest()
    mock_db = MagicMock()
    mock_db.query.return_value = db_return or [{"id": "1", "sender": "alice"}]
    mock_db.execute.return_value = None

    guard = SensitivityGuard(
        agent_id=m.id,
        manifest=m,
        audit_path=audit_path or Path("/dev/null"),
    )
    ctx = AgentContext(
        agent_id=m.id,
        manifest=m,
        db_engine=mock_db,
        guard=guard,
        skills=skills,
        settings=settings,
        llm_provider=llm_provider,
    )
    return ctx, mock_db


# -----------------------------------------------------------------------
# query()
# -----------------------------------------------------------------------


class TestQuery:
    def test_returns_data_from_permitted_table(self) -> None:
        ctx, mock_db = _make_context()
        result = ctx.query("SELECT id, sender FROM raw_messages LIMIT 10")
        assert result == [{"id": "1", "sender": "alice"}]
        mock_db.query.assert_called_once()

    def test_injects_tier_filter(self) -> None:
        ctx, mock_db = _make_context()
        ctx.query("SELECT * FROM raw_messages")
        called_sql = mock_db.query.call_args[0][0]
        assert "sensitivity_tier <= 2" in called_sql

    def test_denies_unauthorized_table(self) -> None:
        ctx, _ = _make_context()
        with pytest.raises(AgentAccessDeniedError, match="not in manifest"):
            ctx.query("SELECT * FROM raw_health_metrics")

    def test_denies_ddl(self) -> None:
        ctx, _ = _make_context()
        with pytest.raises(AgentAccessDeniedError, match="DDL"):
            ctx.query("DROP TABLE raw_messages")

    def test_caps_tier_at_manifest_max(self) -> None:
        manifest = _make_manifest(max_sensitivity_tier=1)
        ctx, mock_db = _make_context(manifest=manifest)
        ctx.query("SELECT * FROM raw_notes")
        called_sql = mock_db.query.call_args[0][0]
        assert "sensitivity_tier <= 1" in called_sql


# -----------------------------------------------------------------------
# ask_llm()
# -----------------------------------------------------------------------


class TestAskLlm:
    def test_denied_when_not_permitted(self) -> None:
        manifest = _make_manifest(can_use_llm=False)
        mock_provider = MagicMock(spec=LLMProvider)
        ctx, _ = _make_context(manifest=manifest, llm_provider=mock_provider)
        with pytest.raises(AgentAccessDeniedError, match="LLM access not permitted"):
            ctx.ask_llm("Hello")

    def test_allowed_when_manifest_permits(self) -> None:
        mock_provider = MagicMock(spec=LLMProvider)
        mock_provider.chat.return_value = LLMResponse(
            content="Summary here", model="llama3.1:8b",
        )
        set_provider_factory_for_tests(lambda _route: mock_provider)
        try:
            ctx, _ = _make_context(llm_provider=mock_provider)
            result = ctx.ask_llm("Summarize this")
            assert result == "Summary here"
            assert ctx.llm_calls == 1
        finally:
            set_provider_factory_for_tests(None)

    def test_includes_context_data(self) -> None:
        mock_provider = MagicMock(spec=LLMProvider)
        mock_provider.chat.return_value = LLMResponse(
            content="ok", model="llama3.1:8b",
        )
        set_provider_factory_for_tests(lambda _route: mock_provider)
        try:
            ctx, _ = _make_context(llm_provider=mock_provider)
            ctx.ask_llm("Summarize", context_data="some data here")

            call_args = mock_provider.chat.call_args
            messages = call_args[0][0]
            prompt = messages[0]["content"]
            assert "some data here" in prompt
        finally:
            set_provider_factory_for_tests(None)


# -----------------------------------------------------------------------
# write()
# -----------------------------------------------------------------------


class TestWrite:
    def test_creates_table_and_inserts(self) -> None:
        ctx, mock_db = _make_context()
        rows = [{"title": "Digest", "body": "Weekly summary"}]
        count = ctx.write("ext_test_agent_results", rows)
        assert count == 1
        assert ctx.rows_written == 1
        assert "ext_test_agent_results" in ctx.tables_written

        # Should have called execute for CREATE TABLE and INSERT.
        assert mock_db.execute.call_count >= 2

    def test_rejects_non_ext_table(self) -> None:
        ctx, _ = _make_context()
        with pytest.raises(AgentAccessDeniedError, match="not permitted"):
            ctx.write("raw_messages", [{"id": "1"}])

    def test_rejects_undeclared_ext_table(self) -> None:
        ctx, _ = _make_context()
        with pytest.raises(AgentAccessDeniedError, match="not permitted"):
            ctx.write("ext_test_agent_other", [{"id": "1"}])

    def test_empty_data_returns_zero(self) -> None:
        ctx, _ = _make_context()
        assert ctx.write("ext_test_agent_results", []) == 0


# -----------------------------------------------------------------------
# call_skill()
# -----------------------------------------------------------------------


class TestCallSkill:
    def test_invokes_registered_skill(self) -> None:
        skill = Skill(
            id="test-skill",
            name="Test",
            description="test",
            execute_fn=lambda text: text.upper(),
        )
        ctx, _ = _make_context(skills={"test-skill": skill})
        result = ctx.call_skill("test-skill", text="hello")
        assert result == "HELLO"

    def test_raises_for_unknown_skill(self) -> None:
        ctx, _ = _make_context()
        with pytest.raises(KeyError, match="not found"):
            ctx.call_skill("nonexistent")


# -----------------------------------------------------------------------
# get_user_preference()
# -----------------------------------------------------------------------


class TestGetUserPreference:
    def test_returns_setting(self) -> None:
        ctx, _ = _make_context(settings={"theme": "dark"})
        assert ctx.get_user_preference("theme") == "dark"

    def test_returns_none_for_unknown(self) -> None:
        ctx, _ = _make_context()
        assert ctx.get_user_preference("nonexistent") is None


# -----------------------------------------------------------------------
# log()
# -----------------------------------------------------------------------


class TestLog:
    def test_writes_to_log_file(self, tmp_path: Path) -> None:
        ctx, _ = _make_context()
        # Override the log path.
        ctx._log_path = tmp_path / "agent.log"

        ctx.log("Hello from agent")
        content = ctx._log_path.read_text()
        assert "Hello from agent" in content
        assert "[INFO]" in content

    def test_writes_custom_level(self, tmp_path: Path) -> None:
        ctx, _ = _make_context()
        ctx._log_path = tmp_path / "agent.log"

        ctx.log("Something went wrong", level="error")
        content = ctx._log_path.read_text()
        assert "[ERROR]" in content

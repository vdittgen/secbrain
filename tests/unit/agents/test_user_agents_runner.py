"""Tests for the user-agent batch runner + post-batch delivery hook.

The batch path is exercised end-to-end with a stubbed pydantic-ai
agent factory and a stubbed MCP client so we can assert the wiring
between data-tool resolution, per-item dispatch, the delivery summary
LLM call, and the per-tool dispatch — without spinning up real models
or connectors.

sensitivity_tier: N/A
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest


@pytest.fixture(autouse=True)
def _isolate(tmp_path: Path, monkeypatch) -> None:
    from src.agents.core import config_store as _cfg_store
    from src.agents.core.registry import reset_registry_for_tests
    from src.agents.user_agents import skill_store as _sk_store
    from src.agents.user_agents import store as _ua_store
    monkeypatch.setattr(
        _cfg_store, "DEFAULT_DB_PATH", tmp_path / "test.sqlite3",
    )
    monkeypatch.setattr(
        _ua_store, "DEFAULT_DB_PATH", tmp_path / "user.sqlite3",
    )
    monkeypatch.setattr(
        _sk_store, "DEFAULT_DB_PATH", tmp_path / "user.sqlite3",
    )
    reset_registry_for_tests()
    from src.agents.brain import bootstrap_agents
    bootstrap_agents()


def _layer_with_two_unread_emails() -> Any:
    """Return a layer stub whose duckdb returns two unread email rows."""
    layer = MagicMock()
    db = MagicMock()

    def query(sql: str, params: list[Any] | None = None):
        if "FROM raw_emails" in sql and "COUNT(*)" not in sql:
            return [
                {"id": "1", "from_address": "a@x", "subject": "hi",
                 "body_preview": "first", "date": "2026-05-20"},
                {"id": "2", "from_address": "b@x", "subject": "yo",
                 "body_preview": "second", "date": "2026-05-20"},
            ]
        if "COUNT(*)" in sql:
            return [{"n": 0}]
        return []

    db.query.side_effect = query
    db.execute.return_value = None
    layer.duckdb = db
    monkey_table_exists(db)
    return layer


def monkey_table_exists(_db: Any) -> None:
    # Stub the helper so the runner's "does this table exist?" probe
    # returns True for raw_emails / raw_messages in tests.
    import src.agents.user_agents.runner as runner

    runner.table_exists = lambda *_args, **_kwargs: True  # type: ignore[attr-defined]


def _make_row_with_mail_source(
    *, delivery_tools: tuple[str, ...] = (),
) -> str:
    from src.agents.user_agents.registration import register_one_user_agent
    from src.agents.user_agents.store import UserAgentStore, UserAgentUpsert

    store = UserAgentStore()
    try:
        row = store.insert(UserAgentUpsert(
            name="Mail Watcher",
            description="reads unread mail",
            system_prompt="Process the email and reply succinctly.",
            model_route="inherit",
            enabled_mcp_tools=("apple-mail:list_emails", "apple-mail:send_email"),
            delivery_tools=delivery_tools,
            schedule_cron="* * * * *",
            schedule_enabled=True,
        ))
    finally:
        store.close()
    register_one_user_agent(row)
    return row.agent_id


def _factory_returning_outputs(per_item_text: str = "ok"):
    """Build an SBAgent stub whose runs return ``per_item_text`` outputs.

    The output object exposes an ``answer`` attribute (BrainResponse
    shape) so the runner's digest accumulator picks it up.
    """
    from src.agents.core.agent_base import AgentRunRecord

    class _Out:
        def __init__(self, text: str) -> None:
            self.answer = text

        def __str__(self) -> str:
            return self.answer

    def factory(*_a, **_kw):
        agent = MagicMock()
        agent.run = lambda deps, *, route=None: AgentRunRecord(
            agent_id="user.mail_watcher",
            output=_Out(per_item_text),
            duration_ms=1.0,
            llm_calls=1,
        )
        return agent

    return factory


def test_run_user_agent_batch_processes_per_item_without_delivery() -> None:
    from src.agents.core.registry import get_agent
    from src.agents.user_agents.runner import run_user_agent_batch

    agent_id = _make_row_with_mail_source()
    definition = get_agent(agent_id)
    object.__setattr__(
        definition, "factory", _factory_returning_outputs("ack"),
    )

    summary = run_user_agent_batch(_layer_with_two_unread_emails(), agent_id)
    assert summary.processed == 2
    assert summary.errors == 0
    # No delivery configured ⇒ no calls recorded.
    assert summary.delivery_calls == []


def test_run_user_agent_batch_fires_delivery_when_processed(
    monkeypatch,
) -> None:
    """Delivery hook fires exactly once, with the LLM-summarized digest."""
    from src.agents.core.registry import get_agent
    from src.agents.user_agents import runner as runner_mod

    agent_id = _make_row_with_mail_source(
        delivery_tools=("whatsapp:send_message",),
    )
    definition = get_agent(agent_id)
    object.__setattr__(
        definition, "factory", _factory_returning_outputs("ack"),
    )

    invocations: list[tuple[str, dict[str, Any]]] = []
    monkeypatch.setattr(
        runner_mod, "_invoke_delivery_tool",
        lambda tool_id, args: (
            invocations.append((tool_id, args)) or "delivered"
        ),
    )

    summary = runner_mod.run_user_agent_batch(
        _layer_with_two_unread_emails(), agent_id,
    )
    assert summary.processed == 2
    assert len(invocations) == 1, invocations
    sent_tool_id, sent_args = invocations[0]
    assert sent_tool_id == "whatsapp:send_message"
    # whatsapp:send_message's required string field is "to" first per
    # the catalog; the heuristic picks the first required string, so
    # the summary lands wherever the schema says it should.
    assert any(
        isinstance(v, str) and v.strip() for v in sent_args.values()
    ), sent_args
    assert summary.delivery_calls == [
        {
            "tool_id": "whatsapp:send_message",
            "status": "success",
            "error": None,
            "result_preview": "delivered",
        },
    ]


def test_delivery_hook_skipped_when_no_items_processed(monkeypatch) -> None:
    """Empty backlog ⇒ no LLM summary call, no delivery dispatch."""
    from src.agents.core.registry import get_agent
    from src.agents.user_agents import runner as runner_mod

    agent_id = _make_row_with_mail_source(
        delivery_tools=("whatsapp:send_message",),
    )
    definition = get_agent(agent_id)
    object.__setattr__(
        definition, "factory", _factory_returning_outputs("never called"),
    )

    invocations: list[Any] = []
    monkeypatch.setattr(
        runner_mod, "_invoke_delivery_tool",
        lambda tool_id, args: invocations.append((tool_id, args)),
    )

    # Layer where raw_emails is empty.
    layer = MagicMock()
    db = MagicMock()
    db.query.return_value = []
    db.execute.return_value = None
    layer.duckdb = db
    monkey_table_exists(db)

    summary = runner_mod.run_user_agent_batch(layer, agent_id)
    assert summary.processed == 0
    assert invocations == []
    assert summary.delivery_calls == []


def test_delivery_error_isolated_per_tool(monkeypatch) -> None:
    """One delivery tool failing must not abort the others."""
    from src.agents.core.registry import get_agent
    from src.agents.user_agents import runner as runner_mod

    agent_id = _make_row_with_mail_source(
        delivery_tools=("whatsapp:send_message", "apple-mail:send_email"),
    )
    definition = get_agent(agent_id)
    object.__setattr__(
        definition, "factory", _factory_returning_outputs("ack"),
    )

    def fake_invoke(tool_id: str, _args: dict[str, Any]) -> str:
        if tool_id == "whatsapp:send_message":
            raise RuntimeError("bridge offline")
        return "ok"

    monkeypatch.setattr(
        runner_mod, "_invoke_delivery_tool", fake_invoke,
    )

    summary = runner_mod.run_user_agent_batch(
        _layer_with_two_unread_emails(), agent_id,
    )
    statuses = {c["tool_id"]: c["status"] for c in summary.delivery_calls}
    assert statuses == {
        "whatsapp:send_message": "error",
        "apple-mail:send_email": "success",
    }
    # The failing tool's error is in the error_messages list so the UI
    # can surface it.
    assert any(
        "whatsapp:send_message" in m for m in summary.error_messages
    )


def test_coerce_delivery_args_picks_first_string_required() -> None:
    from src.agents.user_agents.runner import _coerce_delivery_args

    # whatsapp:send_message — schema lookup goes through the catalog.
    args = _coerce_delivery_args("whatsapp:send_message", "hello")
    assert "hello" in args.values()


def test_coerce_delivery_args_fallback_when_unknown_tool() -> None:
    from src.agents.user_agents.runner import _coerce_delivery_args

    args = _coerce_delivery_args("totally:unknown", "hi")
    assert args == {"text": "hi"}


def test_data_tool_ids_for_row_filters_to_data_only() -> None:
    from src.agents.user_agents.runner import data_tool_ids_for_row
    from src.agents.user_agents.store import UserAgentStore, UserAgentUpsert

    store = UserAgentStore()
    try:
        row = store.insert(UserAgentUpsert(
            name="Mixed Tools",
            description="d",
            system_prompt="p",
            model_route="inherit",
            enabled_mcp_tools=(
                "apple-mail:list_emails",     # data
                "apple-mail:send_email",      # action
                "whatsapp:list_chats",        # data
                "whatsapp:send_message",      # action
                "bogus:not_a_tool",           # unknown
            ),
        ))
    finally:
        store.close()
    sources = data_tool_ids_for_row(row)
    assert set(sources) == {
        "apple-mail:list_emails", "whatsapp:list_chats",
    }

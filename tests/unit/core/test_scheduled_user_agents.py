"""Tests for the user-agent slice of ``cmd_run_scheduled_agents``.

The wiring under test enumerates ``user_agents`` rows with
``schedule_enabled=1`` and a non-empty cron, checks each one against
the persisted last-run timestamp, and invokes due agents through the
registry factory.

sensitivity_tier: N/A
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from src.agents.brain import bootstrap_agents
from src.agents.core.registry import reset_registry_for_tests


@pytest.fixture(autouse=True)
def _isolate(tmp_path: Path, monkeypatch) -> None:
    # Point both the agent_configs and user_agents stores at tmp paths
    # so registrations + cron tick reads see a fresh DB.
    from src.agents.core import config_store as _cfg_store
    from src.agents.user_agents import store as _ua_store
    monkeypatch.setattr(
        _cfg_store, "DEFAULT_DB_PATH", tmp_path / "test.sqlite3",
    )
    monkeypatch.setattr(
        _ua_store, "DEFAULT_DB_PATH", tmp_path / "user.sqlite3",
    )
    from src.agents.user_agents import skill_store as _sk_store
    monkeypatch.setattr(
        _sk_store, "DEFAULT_DB_PATH", tmp_path / "user.sqlite3",
    )
    reset_registry_for_tests()
    bootstrap_agents()


def _make_user_agent_with_cron(cron: str, *, enabled: bool) -> str:
    """Register a user agent and set its schedule. Returns the agent id."""
    from src.agents.user_agents.registration import register_one_user_agent
    from src.agents.user_agents.store import UserAgentStore, UserAgentUpsert

    store = UserAgentStore()
    try:
        row = store.insert(UserAgentUpsert(
            name="Cron Test Agent",
            description="exists to verify the cron tick",
            system_prompt="just respond ok",
            model_route="inherit",
            schedule_cron=cron,
            schedule_enabled=enabled,
        ))
    finally:
        store.close()
    register_one_user_agent(row)
    return row.agent_id


def _layer_stub() -> MagicMock:
    """Return a layer-like object that satisfies the runner signature.

    All existing tests exercise the sourceless / generic path, which
    does not touch ``layer.duckdb`` — a bare ``MagicMock`` is enough.
    """
    return MagicMock()


def _fake_factory_capturing_inputs(captured: list[str]):
    """Return a factory whose agent records every input it sees."""
    from src.agents.core.agent_base import AgentRunRecord

    def factory(*_args, **_kwargs):
        instance = MagicMock()

        def fake_run(deps, *, route=None):  # noqa: ARG001
            captured.append(deps)
            return AgentRunRecord(
                agent_id="user.cron_test_agent",
                output=None,
                duration_ms=1.0,
                llm_calls=0,
            )

        instance.run = fake_run
        return instance

    return factory


def test_due_user_agent_is_fired() -> None:
    """A user agent whose cron is due gets ``agent.run(trigger)`` called."""
    from src.core.cli import _tick_scheduled_user_agents

    agent_id = _make_user_agent_with_cron("* * * * *", enabled=True)
    # Swap the factory so we capture the call without spinning up a
    # real pydantic-ai model.
    from src.agents.core.registry import get_agent
    definition = get_agent(agent_id)
    captured_inputs: list[str] = []
    object.__setattr__(
        definition, "factory", _fake_factory_capturing_inputs(captured_inputs),
    )

    state: dict[str, str] = {}
    now = datetime(2026, 5, 20, 21, 0, 30, tzinfo=timezone.utc)
    checked, run_list, errors = _tick_scheduled_user_agents(
        layer=_layer_stub(), state=state, now=now,
    )

    assert checked == 1
    assert run_list == [{"agent_id": agent_id, "status": "success"}]
    assert errors == []
    assert state[agent_id] == now.isoformat()
    assert len(captured_inputs) == 1
    # The trigger references the agent's description so the prompt
    # has context for what to do.
    assert "Execute sua tarefa" in captured_inputs[0]
    assert "exists to verify the cron tick" in captured_inputs[0]


def test_disabled_schedule_is_skipped() -> None:
    """``schedule_enabled=False`` rows are not checked or fired."""
    from src.core.cli import _tick_scheduled_user_agents

    _make_user_agent_with_cron("* * * * *", enabled=False)

    state: dict[str, str] = {}
    now = datetime(2026, 5, 20, 21, 0, 30, tzinfo=timezone.utc)
    checked, run_list, errors = _tick_scheduled_user_agents(
        layer=_layer_stub(), state=state, now=now,
    )

    assert checked == 0
    assert run_list == []
    assert errors == []
    assert state == {}


def test_not_due_yet_is_not_fired() -> None:
    """Hourly cron + last_run < 1h ago = not due."""
    from src.core.cli import _tick_scheduled_user_agents

    agent_id = _make_user_agent_with_cron("0 * * * *", enabled=True)
    last_run = datetime(2026, 5, 20, 20, 30, tzinfo=timezone.utc)
    state: dict[str, str] = {agent_id: last_run.isoformat()}
    now = datetime(2026, 5, 20, 20, 45, tzinfo=timezone.utc)
    checked, run_list, errors = _tick_scheduled_user_agents(
        layer=_layer_stub(), state=state, now=now,
    )

    assert checked == 1
    assert run_list == []
    assert errors == []
    # state untouched
    assert state[agent_id] == last_run.isoformat()


def test_agent_run_error_propagates_into_errors_list() -> None:
    """A failing agent appears in ``errors`` but doesn't break the tick."""
    from src.agents.core.agent_base import AgentRunRecord
    from src.agents.core.registry import get_agent
    from src.core.cli import _tick_scheduled_user_agents

    agent_id = _make_user_agent_with_cron("* * * * *", enabled=True)

    def factory(*_args, **_kwargs):
        instance = MagicMock()

        def fake_run(_deps, *, route=None):  # noqa: ARG001
            return AgentRunRecord(
                agent_id=agent_id,
                output=None,
                duration_ms=1.0,
                llm_calls=0,
                error="model unavailable",
            )

        instance.run = fake_run
        return instance

    definition = get_agent(agent_id)
    object.__setattr__(definition, "factory", factory)

    state: dict[str, str] = {}
    now = datetime(2026, 5, 20, 21, 0, 30, tzinfo=timezone.utc)
    checked, run_list, errors = _tick_scheduled_user_agents(
        layer=_layer_stub(), state=state, now=now,
    )
    assert checked == 1
    assert run_list == [{"agent_id": agent_id, "status": "error"}]
    assert any("model unavailable" in e for e in errors)
    # Don't advance last_run on error — next tick will retry.
    assert agent_id not in state

"""Verify the pattern-aware factory in user_agents.registration.

Single-pattern rows still produce an ``SBAgent`` subclass; orchestrator
rows produce an ``SBOrchestrator`` subclass whose ``subagents`` tuple
matches the row.

sensitivity_tier: 1
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from src.agents.core.agent_base import SBAgent, SBOrchestrator
from src.agents.user_agents.registration import _definition_for
from src.agents.user_agents.store import (
    UserAgentStore,
    UserAgentUpsert,
)


@pytest.fixture()
def store(tmp_path: Path) -> UserAgentStore:
    return UserAgentStore(path=tmp_path / "user.sqlite3")


def _orchestrator_upsert() -> UserAgentUpsert:
    return UserAgentUpsert(
        name="Research Lead",
        description="delegates research questions to sub-agents",
        system_prompt="Route the question to the right specialist.",
        model_route="inherit",
        pattern="orchestrator",
        subagents=("user.alice", "user.bob"),
    )


def _single_upsert() -> UserAgentUpsert:
    return UserAgentUpsert(
        name="Alice",
        description="answers research questions",
        system_prompt="You are a research assistant.",
        model_route="inherit",
    )


def test_single_pattern_factory_returns_sbagent(
    store: UserAgentStore,
) -> None:
    row = store.insert(_single_upsert())
    definition = _definition_for(row, query_engine=None)
    assert definition.pattern == "single"
    assert definition.factory is not None

    instance: Any = definition.factory()
    assert isinstance(instance, SBAgent)
    assert not isinstance(instance, SBOrchestrator)
    assert instance.agent_id == row.agent_id
    assert instance.system_prompt == row.system_prompt


def test_orchestrator_pattern_factory_returns_sborchestrator(
    store: UserAgentStore,
) -> None:
    row = store.insert(_orchestrator_upsert())
    definition = _definition_for(row, query_engine=None)
    assert definition.pattern == "orchestrator"
    assert definition.factory is not None

    instance: Any = definition.factory()
    assert isinstance(instance, SBOrchestrator)
    assert instance.agent_id == row.agent_id
    assert instance.system_prompt == row.system_prompt
    # Subagents bound per-row via the dynamic-subclass trick.
    assert instance.subagents == ("user.alice", "user.bob")


def test_orchestrator_definition_lists_delegation_in_available_tools(
    store: UserAgentStore,
) -> None:
    row = store.insert(_orchestrator_upsert())
    definition = _definition_for(row, query_engine=None)
    # Each sub-agent surfaces as ``delegate:<id>`` so the UI can render
    # the delegation graph without a second registry lookup.
    assert "delegate:user.alice" in definition.available_tools
    assert "delegate:user.bob" in definition.available_tools


def test_two_orchestrators_keep_distinct_subagents(
    store: UserAgentStore,
) -> None:
    """The dynamic-subclass trick must not leak between instances."""
    row_a = store.insert(_orchestrator_upsert())
    upsert_b = _orchestrator_upsert()
    upsert_b.name = "Other Lead"
    upsert_b.subagents = ("user.carol",)
    row_b = store.insert(upsert_b)

    def_a = _definition_for(row_a, query_engine=None)
    def_b = _definition_for(row_b, query_engine=None)
    assert def_a.factory is not None
    assert def_b.factory is not None
    inst_a: Any = def_a.factory()
    inst_b: Any = def_b.factory()
    assert inst_a.subagents == ("user.alice", "user.bob")
    assert inst_b.subagents == ("user.carol",)

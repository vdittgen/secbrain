"""Agent registry behaviour.

sensitivity_tier: N/A
"""

from __future__ import annotations

import pytest
from src.agents.core.config_store import AgentConfig
from src.agents.core.registry import (
    AgentDefinition,
    all_agents,
    children_of,
    filter_tools_for_agent,
    get_agent,
    register_agent,
    reset_registry_for_tests,
)
from src.agents.core.scheduler import Tier


def _make(
    agent_id: str,
    *,
    parent: str | None = None,
    editable: bool = True,
    tools: tuple[str, ...] = (),
) -> AgentDefinition:
    cfg = AgentConfig(
        agent_id=agent_id,
        system_prompt="",
        model_route="inherit",
        model_override=None,
        enabled_tools=tools,
        enabled_skills=(),
        editable=editable,
    )
    return AgentDefinition(
        agent_id=agent_id,
        name=agent_id,
        description=f"agent {agent_id}",
        category="test",
        parent_agent=parent,
        tier=Tier.BACKGROUND,
        max_sensitivity_tier=2,
        editable=editable,
        default_config=cfg,
        available_tools=tools,
        available_skills=(),
        output_schema="TriageDecision",
        pattern="single",
    )


@pytest.fixture(autouse=True)
def _clean() -> None:
    reset_registry_for_tests()


def test_register_and_lookup() -> None:
    # Use a test-only id so the tier injector in :func:`register_agent`
    # leaves ``default_config`` untouched and the equality check holds.
    d = _make("fake_test_agent")
    register_agent(d)
    assert get_agent("fake_test_agent") == d


def test_duplicate_registration_rejected() -> None:
    register_agent(_make("fake_test_agent"))
    with pytest.raises(ValueError):
        register_agent(_make("fake_test_agent"))


def test_children_of() -> None:
    register_agent(_make("test_root"))
    register_agent(_make("test_child_a", parent="test_root"))
    register_agent(_make("test_child_b", parent="test_root"))
    register_agent(_make("standalone"))
    kids = {d.agent_id for d in children_of("test_root")}
    assert kids == {"test_child_a", "test_child_b"}
    top = {d.agent_id for d in children_of(None)}
    assert "test_root" in top
    assert "standalone" in top


def test_filter_tools_for_agent_respects_allowlist() -> None:
    d = _make("fake_test_agent", tools=("a", "b"))
    register_agent(d)
    out = filter_tools_for_agent(d, ["a", "b", "c"])
    assert out == ("a", "b")


def test_all_agents_sorted_by_parent_then_id() -> None:
    register_agent(_make("z_root"))
    register_agent(_make("a_root"))
    register_agent(_make("c_child", parent="a_root"))
    ids = [d.agent_id for d in all_agents()]
    # parent-empty agents come first, sorted by id.
    assert ids.index("a_root") < ids.index("z_root")

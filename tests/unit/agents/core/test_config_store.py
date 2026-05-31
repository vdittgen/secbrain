"""AgentConfigStore round-trip and editability tests.

sensitivity_tier: N/A
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from src.agents.core.config_store import (
    AgentConfig,
    AgentConfigStore,
    AgentConfigStoreError,
    current_model_override,
    proposed_model_override,
)


@pytest.fixture()
def store(tmp_path: Path) -> AgentConfigStore:
    conn = sqlite3.connect(tmp_path / "agents.sqlite3")
    s = AgentConfigStore(conn)
    s.initialize()
    return s


def _default_editable() -> AgentConfig:
    return AgentConfig(
        agent_id="triage",
        system_prompt="default prompt",
        model_route="inherit",
        model_override=None,
        enabled_tools=("query_duckdb",),
        enabled_skills=("summarize-text",),
        editable=True,
    )


def _default_locked() -> AgentConfig:
    return AgentConfig(
        agent_id="firewall.injection",
        system_prompt="locked prompt",
        model_route="remote",
        model_override=None,
        enabled_tools=(),
        enabled_skills=(),
        editable=False,
    )


def test_resolve_returns_default_when_no_override(
    store: AgentConfigStore,
) -> None:
    default = _default_editable()
    assert store.resolve("triage", default=default) == default


def test_update_persists_patch(store: AgentConfigStore) -> None:
    default = _default_editable()
    updated = store.update(
        "triage",
        default=default,
        patch={"system_prompt": "new prompt"},
    )
    assert updated.system_prompt == "new prompt"
    # Re-resolve to confirm persistence.
    again = store.resolve("triage", default=default)
    assert again.system_prompt == "new prompt"
    assert again.version > default.version


def test_update_rejects_locked_agent(store: AgentConfigStore) -> None:
    with pytest.raises(AgentConfigStoreError):
        store.update(
            "firewall.injection",
            default=_default_locked(),
            patch={"system_prompt": "tampered"},
        )


def test_update_allows_model_override_on_locked_agent(
    store: AgentConfigStore,
) -> None:
    default = _default_locked()
    merged = store.update(
        "firewall.injection",
        default=default,
        patch={"model_override": "qwen3:8b"},
    )
    assert merged.model_override == "qwen3:8b"
    assert merged.system_prompt == default.system_prompt
    assert merged.editable is False


def test_update_allows_model_route_on_locked_agent(
    store: AgentConfigStore,
) -> None:
    # Route + override are a single coupled choice — the Model Picker
    # validates the pair against the live catalog and applies both.
    default = _default_locked()
    merged = store.update(
        "firewall.injection",
        default=default,
        patch={"model_route": "local"},
    )
    assert merged.model_route == "local"
    assert merged.system_prompt == default.system_prompt
    assert merged.editable is False


def test_update_rejects_unknown_field(store: AgentConfigStore) -> None:
    with pytest.raises(AgentConfigStoreError):
        store.update(
            "triage",
            default=_default_editable(),
            patch={"nonexistent_key": "x"},
        )


def test_reset_drops_override(store: AgentConfigStore) -> None:
    default = _default_editable()
    store.update(
        "triage",
        default=default,
        patch={"system_prompt": "changed"},
    )
    restored = store.reset("triage", default=default)
    assert restored == default
    assert store.resolve("triage", default=default) == default


def test_tool_list_persisted_as_json(store: AgentConfigStore) -> None:
    default = _default_editable()
    updated = store.update(
        "triage",
        default=default,
        patch={"enabled_tools": ["a", "b", "c"]},
    )
    assert updated.enabled_tools == ("a", "b", "c")


# ---------------------------------------------------------------------------
# proposed_model_override / current_model_override ContextVar interaction
# ---------------------------------------------------------------------------


def test_proposed_override_takes_precedence_inside_scope(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    # No DB → without a proposal, current_model_override returns None
    monkeypatch.setattr(
        "src.agents.core.config_store.DEFAULT_DB_PATH",
        tmp_path / "nonexistent.sqlite3",
    )
    assert current_model_override("triage") is None
    with proposed_model_override("triage", "deepseek-ai/DeepSeek-V3.1"):
        assert (
            current_model_override("triage")
            == "deepseek-ai/DeepSeek-V3.1"
        )
    # Exiting the scope restores the previous behavior
    assert current_model_override("triage") is None


def test_proposed_override_only_affects_target_agent(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        "src.agents.core.config_store.DEFAULT_DB_PATH",
        tmp_path / "nonexistent.sqlite3",
    )
    with proposed_model_override("triage", "model-X"):
        assert current_model_override("triage") == "model-X"
        assert current_model_override("other_agent") is None


def test_nested_proposed_overrides_compose(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        "src.agents.core.config_store.DEFAULT_DB_PATH",
        tmp_path / "nonexistent.sqlite3",
    )
    with proposed_model_override("a", "model-A"):
        with proposed_model_override("b", "model-B"):
            assert current_model_override("a") == "model-A"
            assert current_model_override("b") == "model-B"
        # Inner scope reset — only "a" still bound
        assert current_model_override("a") == "model-A"
        assert current_model_override("b") is None


def test_proposed_override_restored_on_exception(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        "src.agents.core.config_store.DEFAULT_DB_PATH",
        tmp_path / "nonexistent.sqlite3",
    )
    with pytest.raises(RuntimeError, match="boom"):
        with proposed_model_override("triage", "model-X"):
            raise RuntimeError("boom")
    assert current_model_override("triage") is None

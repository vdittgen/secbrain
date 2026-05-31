"""Unit tests for MessageTriager.

Covers happy path, cache short-circuit, fail-open behaviour when the
underlying SBAgent errors out, and empty-content quick-drop.

sensitivity_tier: N/A — test infrastructure
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest
from src.agents.core.output_types import (
    TriageBatch,
)
from src.agents.core.output_types import (
    TriageDecision as TriageVerdict,
)
from src.agents.triage import (
    MessageTriager,
    TriageDecision,
)
from src.core.sqlite.engine import DatabaseEngine


@pytest.fixture()
def tmp_db(tmp_path: Path) -> DatabaseEngine:
    db_path = tmp_path / "test_triage.db"
    engine = DatabaseEngine(db_path=db_path)
    yield engine
    engine.close()


@pytest.fixture()
def stub_triage(monkeypatch):
    """Monkey-patch ``TriageAgent.triage`` with a controllable stub.

    Tests set ``stub_triage.return_value`` to a :class:`TriageBatch` or
    ``stub_triage.side_effect`` to an exception. The patched method
    receives the ``TriageMessage`` list the orchestrator built so the
    same test can also assert on the input.
    """
    fake = MagicMock(return_value=TriageBatch(decisions=[]))

    def _bound_triage(self, messages):  # noqa: ARG001
        result = fake(messages)
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(
        "src.agents.triage.agent.TriageAgent.triage", _bound_triage,
    )
    return fake


def _msg(mid: str, content: str, sender: str = "Alice") -> dict:
    return {
        "id": mid,
        "content": content,
        "sender_name": sender,
        "source": "whatsapp",
    }


class TestTriageHappyPath:
    def test_keeps_and_drops_per_agent(
        self, tmp_db: DatabaseEngine, stub_triage,
    ) -> None:
        stub_triage.return_value = TriageBatch(decisions=[
            TriageVerdict(message_id="m1", keep=True, reason="real question"),
            TriageVerdict(
                message_id="m2", keep=False, reason="promo", is_promo=True,
            ),
        ])
        triager = MessageTriager(tmp_db)

        decisions = triager.triage([
            _msg("m1", "Can we meet tomorrow?"),
            _msg("m2", "EXCLUSIVE 50% OFF — click now"),
        ])

        assert len(decisions) == 2
        assert decisions[0].keep is True
        assert decisions[1].keep is False
        assert decisions[1].is_promo is True

    def test_persists_to_triage_log(
        self, tmp_db: DatabaseEngine, stub_triage,
    ) -> None:
        stub_triage.return_value = TriageBatch(decisions=[
            TriageVerdict(message_id="m1", keep=True, reason=""),
            TriageVerdict(
                message_id="m2", keep=False, reason="", is_ack_only=True,
            ),
        ])
        MessageTriager(tmp_db).triage([
            _msg("m1", "Need your input by Friday"),
            _msg("m2", "kkkk"),
        ])

        rows = tmp_db.query(
            "SELECT message_id, keep, flags_json FROM _triage_log "
            "ORDER BY message_id",
        )
        assert len(rows) == 2
        assert rows[0]["message_id"] == "m1"
        assert rows[0]["keep"] == 1
        assert rows[1]["keep"] == 0
        assert "is_ack_only" in rows[1]["flags_json"]


class TestTriageCache:
    def test_cache_short_circuits_subsequent_run(
        self, tmp_db: DatabaseEngine, stub_triage,
    ) -> None:
        """A second triage on the same IDs reuses the cached verdict."""
        stub_triage.return_value = TriageBatch(decisions=[
            TriageVerdict(message_id="m1", keep=True, reason=""),
            TriageVerdict(message_id="m2", keep=False, reason=""),
        ])
        triager = MessageTriager(tmp_db)
        triager.triage([_msg("m1", "hi"), _msg("m2", "bye")])

        # Reset and re-triage — must not hit the agent.
        stub_triage.reset_mock()
        stub_triage.return_value = TriageBatch(decisions=[
            TriageVerdict(message_id="m1", keep=False, reason=""),
            TriageVerdict(message_id="m2", keep=True, reason=""),
        ])
        decisions = triager.triage([
            _msg("m1", "hi"), _msg("m2", "bye"),
        ])

        assert stub_triage.call_count == 0
        # Cached values win, not the new stub response
        assert decisions[0].keep is True
        assert decisions[1].keep is False


class TestTriageFailOpen:
    def test_agent_error_keeps_everything(
        self, tmp_db: DatabaseEngine, stub_triage,
    ) -> None:
        stub_triage.side_effect = RuntimeError("network died")
        decisions = MessageTriager(tmp_db).triage([
            _msg("m1", "hi"), _msg("m2", "bye"),
        ])
        assert all(d.keep for d in decisions)
        assert "agent missing verdict" in decisions[0].reason

    def test_agent_returns_none_keeps_unmatched(
        self, tmp_db: DatabaseEngine, stub_triage,
    ) -> None:
        """If the agent returns None (LLM failure), items default to keep=True."""
        stub_triage.return_value = None
        decisions = MessageTriager(tmp_db).triage([
            _msg("m1", "hi"), _msg("m2", "bye"),
        ])
        assert all(d.keep for d in decisions)


class TestTriageEmptyContent:
    def test_empty_content_dropped_without_agent(
        self, tmp_db: DatabaseEngine, stub_triage,
    ) -> None:
        stub_triage.return_value = TriageBatch(decisions=[
            TriageVerdict(message_id="m2", keep=True, reason=""),
        ])
        decisions = MessageTriager(tmp_db).triage([
            _msg("m1", ""),
            _msg("m2", "real content"),
        ])
        assert decisions[0].keep is False
        assert decisions[0].is_automated is True
        assert decisions[1].keep is True
        # Only the non-empty message reached the agent.
        assert stub_triage.call_count == 1


class TestTriageOrderPreservation:
    def test_output_aligned_with_input(
        self, tmp_db: DatabaseEngine, stub_triage,
    ) -> None:
        """Agent may reorder items — output must still match input order."""
        stub_triage.return_value = TriageBatch(decisions=[
            TriageVerdict(message_id="m3", keep=False, reason=""),
            TriageVerdict(message_id="m1", keep=True, reason=""),
            TriageVerdict(message_id="m2", keep=False, reason=""),
        ])
        decisions = MessageTriager(tmp_db).triage([
            _msg("m1", "first"),
            _msg("m2", "second"),
            _msg("m3", "third"),
        ])
        assert decisions[0].message_id == "m1"
        assert decisions[1].message_id == "m2"
        assert decisions[2].message_id == "m3"
        assert decisions[0].keep is True
        assert decisions[1].keep is False
        assert decisions[2].keep is False


class TestTriageDecision:
    def test_frozen_dataclass(self) -> None:
        d = TriageDecision(message_id="x", keep=True)
        with pytest.raises(AttributeError):
            d.keep = False  # type: ignore[misc]

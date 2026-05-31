"""AgentRunLog behaviour tests.

Exercises the SQLite store directly without involving pydantic-ai —
the SBAgent integration is covered indirectly elsewhere.

sensitivity_tier: N/A
"""

from __future__ import annotations

from pathlib import Path

import pytest
from src.agents.core.run_log import (
    MAX_PER_AGENT,
    AgentRunLog,
    AgentRunLogEntry,
)


@pytest.fixture()
def log(tmp_path: Path) -> AgentRunLog:
    return AgentRunLog(path=tmp_path / "run_log.sqlite3", max_per_agent=5)


def test_record_and_recent_roundtrip(log: AgentRunLog) -> None:
    log.record(
        agent_id="triage",
        input="hello",
        output={"label": "important"},
        duration_ms=12.5,
        route="remote",
        status="ok",
    )
    rows = log.recent("triage", limit=10)
    assert len(rows) == 1
    entry = rows[0]
    assert isinstance(entry, AgentRunLogEntry)
    assert entry.agent_id == "triage"
    assert entry.input == "hello"
    assert entry.status == "ok"
    assert entry.route == "remote"
    assert entry.duration_ms == pytest.approx(12.5)
    # output is JSON-encoded
    assert entry.output is not None
    assert '"label"' in entry.output
    assert '"important"' in entry.output


def test_error_path_records_with_no_output(log: AgentRunLog) -> None:
    log.record(
        agent_id="triage",
        input="boom",
        output=None,
        duration_ms=3.0,
        route="remote",
        status="error",
        error="ValueError: bad input",
    )
    rows = log.recent("triage", limit=10)
    assert len(rows) == 1
    assert rows[0].status == "error"
    assert rows[0].output is None
    assert rows[0].error == "ValueError: bad input"


def test_ring_trims_to_max_per_agent(log: AgentRunLog) -> None:
    # max_per_agent is 5 in the fixture.
    for i in range(10):
        log.record(
            agent_id="triage",
            input=f"msg-{i}",
            output={"i": i},
            duration_ms=1.0,
            route="remote",
            status="ok",
        )
    rows = log.recent("triage", limit=100)
    assert len(rows) == 5
    # Newest first.
    inputs = [r.input for r in rows]
    assert inputs == ["msg-9", "msg-8", "msg-7", "msg-6", "msg-5"]
    assert log.count("triage") == 5


def test_per_agent_isolation(log: AgentRunLog) -> None:
    log.record(
        agent_id="triage", input="a", output=None,
        duration_ms=1.0, route="remote", status="ok",
    )
    log.record(
        agent_id="labeler", input="b", output=None,
        duration_ms=1.0, route="remote", status="ok",
    )
    triage = log.recent("triage", limit=10)
    labeler = log.recent("labeler", limit=10)
    assert [r.input for r in triage] == ["a"]
    assert [r.input for r in labeler] == ["b"]


def test_recent_clamps_limit_above_max(log: AgentRunLog) -> None:
    for i in range(3):
        log.record(
            agent_id="x", input=str(i), output=None,
            duration_ms=1.0, route="remote", status="ok",
        )
    # Asking for more than max_per_agent still works — we just return
    # what we have.
    rows = log.recent("x", limit=MAX_PER_AGENT + 50)
    assert len(rows) == 3


def test_pydantic_output_uses_model_dump_json(log: AgentRunLog) -> None:
    class FakeOutput:
        def model_dump_json(self) -> str:
            return '{"answer":42}'

    log.record(
        agent_id="x", input="q", output=FakeOutput(),
        duration_ms=1.0, route="remote", status="ok",
    )
    row = log.recent("x", limit=1)[0]
    assert row.output == '{"answer":42}'


def test_unserializable_output_falls_back_to_str(log: AgentRunLog) -> None:
    class Unserializable:
        def __repr__(self) -> str:
            return "<Unserializable>"

    log.record(
        agent_id="x", input="q", output=Unserializable(),
        duration_ms=1.0, route="remote", status="ok",
    )
    row = log.recent("x", limit=1)[0]
    # Either str() rendering or json.dumps default=str — either way
    # we don't crash and we record *something*.
    assert row.output is not None
    assert "Unserializable" in row.output


def test_empty_agent_id_is_ignored(log: AgentRunLog) -> None:
    log.record(
        agent_id="", input="x", output=None,
        duration_ms=1.0, route="remote", status="ok",
    )
    assert log.recent("", limit=10) == []

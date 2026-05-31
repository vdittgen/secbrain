"""Deep-agent sandbox isolation tests.

Covers the surface the firewall + agent base relies on:
- ``run_python`` rejects forbidden imports + identifiers up-front.
- ``run_python`` enforces a timeout.
- ``run_sql`` rejects writes/DDL and multi-statement payloads.
- ``resolve_in_workspace`` blocks path traversal.

These are not full security guarantees — see ``sandbox.py`` for the
threat model. They are the minimum behavioural contract.

sensitivity_tier: N/A
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from src.agents.core.sandbox import (
    WorkspaceError,
    resolve_in_workspace,
    run_python,
    run_sql,
)

# ---------------------------------------------------------------------------
# Python sandbox
# ---------------------------------------------------------------------------


def test_python_rejects_forbidden_import() -> None:
    result = run_python("import os\nprint('ok')")
    assert not result.ok
    assert result.exit_reason == "rejected"
    assert "os" in result.stderr


def test_python_rejects_open_identifier() -> None:
    result = run_python("x = open('/etc/passwd')")
    assert not result.ok
    assert result.exit_reason == "rejected"


def test_python_runs_safe_snippet() -> None:
    result = run_python("print(sum(range(10)))")
    assert result.ok, result.stderr
    assert result.stdout.strip() == "45"


def test_python_enforces_timeout() -> None:
    result = run_python(
        "import math\n"
        "x = 0\n"
        "while True:\n    x += 1\n",
        timeout_s=1.0,
    )
    assert not result.ok
    assert result.exit_reason == "timeout"


# ---------------------------------------------------------------------------
# SQL sandbox
# ---------------------------------------------------------------------------


@pytest.fixture()
def temp_db(tmp_path: Path) -> Path:
    db = tmp_path / "t.sqlite3"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE foo (id INTEGER, name TEXT)")
    conn.executemany(
        "INSERT INTO foo VALUES (?, ?)",
        [(1, "alice"), (2, "bob")],
    )
    conn.commit()
    conn.close()
    return db


def test_sql_select_allowed(temp_db: Path) -> None:
    res = run_sql("SELECT * FROM foo ORDER BY id", db_path=temp_db)
    assert res.ok, res.stderr
    assert res.rows == [
        {"id": 1, "name": "alice"},
        {"id": 2, "name": "bob"},
    ]


def test_sql_insert_rejected(temp_db: Path) -> None:
    res = run_sql(
        "INSERT INTO foo VALUES (3, 'charlie')",
        db_path=temp_db,
    )
    assert not res.ok
    assert res.exit_reason == "rejected"


def test_sql_drop_rejected(temp_db: Path) -> None:
    res = run_sql("DROP TABLE foo", db_path=temp_db)
    assert not res.ok
    assert res.exit_reason == "rejected"


def test_sql_multistatement_rejected(temp_db: Path) -> None:
    res = run_sql(
        "SELECT 1; SELECT 2", db_path=temp_db,
    )
    assert not res.ok
    assert res.exit_reason == "rejected"


def test_sql_comment_injection_blocked(temp_db: Path) -> None:
    # Comments are stripped before keyword detection, so the DROP is
    # still caught.
    res = run_sql(
        "SELECT 1 -- ; DROP TABLE foo\nUNION ALL SELECT 2",
        db_path=temp_db,
    )
    assert res.ok, res.stderr


# ---------------------------------------------------------------------------
# Workspace path safety
# ---------------------------------------------------------------------------


def test_resolve_in_workspace_blocks_traversal(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    with pytest.raises(WorkspaceError):
        resolve_in_workspace(ws, "../escape.txt")
    with pytest.raises(WorkspaceError):
        resolve_in_workspace(ws, "/etc/passwd")


def test_resolve_in_workspace_accepts_subpath(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    out = resolve_in_workspace(ws, "subdir/file.txt")
    assert ws in out.parents or out.parent == ws.resolve()

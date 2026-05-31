"""Unit tests for the chat-session-* CLI subcommands.

Each test drives the public ``cli_main`` entry point with a temp data
directory and inspects the JSON written to stdout. This proves the
Tauri-facing JSON contract that the Rust layer parses.

sensitivity_tier: 1
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from src.core.cli import main as cli_main


def _run(
    cli_args: list[str], data_dir: Path, capsys: pytest.CaptureFixture[str],
) -> dict:
    """Invoke cli_main and return the parsed JSON from stdout."""
    rc = cli_main(["--data-dir", str(data_dir), *cli_args])
    out = capsys.readouterr().out.strip()
    assert rc == 0, f"cli returned {rc}; stdout={out}"
    assert out, "expected JSON on stdout"
    return json.loads(out.splitlines()[-1])


def test_session_create_returns_id(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    payload = _run(["chat-session-create"], tmp_path, capsys)
    assert "session_id" in payload
    assert isinstance(payload["session_id"], str)


def test_session_create_with_title(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    payload = _run(
        ["chat-session-create", "--title", "Onboarding"], tmp_path, capsys,
    )
    sid = payload["session_id"]
    listed = _run(["chat-session-list"], tmp_path, capsys)
    assert any(
        s["id"] == sid and s["title"] == "Onboarding"
        for s in listed["sessions"]
    )


def test_session_list_empty(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    payload = _run(["chat-session-list"], tmp_path, capsys)
    assert payload == {"sessions": []}


def test_session_load_unknown_returns_empty(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    # An unknown session id is not an error — the store returns zero rows.
    payload = _run(
        ["chat-session-load", "nonexistent-id"], tmp_path, capsys,
    )
    assert payload == {"session_id": "nonexistent-id", "messages": []}


def test_session_delete_returns_ok(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    created = _run(["chat-session-create"], tmp_path, capsys)
    sid = created["session_id"]
    deleted = _run(["chat-session-delete", sid], tmp_path, capsys)
    assert deleted == {"ok": True}
    listed = _run(["chat-session-list"], tmp_path, capsys)
    assert listed["sessions"] == []

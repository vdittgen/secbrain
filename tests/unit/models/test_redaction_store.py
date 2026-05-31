"""Tests for the per-call redaction detail store.

Covers the SQLite-backed store used by the audit-log drilldown modal:
round-trip persistence, hash-format rejection, 0600 file mode on the
sqlite file, opportunistic retention pruning, and graceful absence
handling.

sensitivity_tier: N/A
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from src.models.redaction_store import RedactionStore


def _store(tmp_path: Path, *, retention_hours: int = 24) -> RedactionStore:
    return RedactionStore(
        path=tmp_path / "redaction_log.sqlite",
        retention_hours=retention_hours,
    )


VALID_HASH = "a" * 64
OTHER_HASH = "b" * 64


def test_store_roundtrip(tmp_path: Path) -> None:
    store = _store(tmp_path)
    ok = store.store(
        payload_hash=VALID_HASH,
        agent_id="brain.test",
        lane="interactive",
        original_messages=[{"role": "user", "content": "Alice"}],
        redacted_messages=[{"role": "user", "content": "__PERSON_1__"}],
        placeholder_map={"__PERSON_1__": "Alice"},
    )
    assert ok is True
    detail = store.get(VALID_HASH)
    assert detail is not None
    assert detail["payload_hash"] == VALID_HASH
    assert detail["agent_id"] == "brain.test"
    assert detail["lane"] == "interactive"
    assert detail["original_messages"][0]["content"] == "Alice"
    assert detail["redacted_messages"][0]["content"] == "__PERSON_1__"
    assert detail["placeholder_map"] == {"__PERSON_1__": "Alice"}
    assert "stored_at" in detail


def test_get_missing_returns_none(tmp_path: Path) -> None:
    assert _store(tmp_path).get(VALID_HASH) is None


def test_rejects_bad_hash(tmp_path: Path) -> None:
    store = _store(tmp_path)
    bad_hashes = ["../escape", "abc", "z" * 64, "", "A" * 64 + "X"]
    for h in bad_hashes:
        assert (
            store.store(
                payload_hash=h,
                agent_id="x", lane="x",
                original_messages=[],
                redacted_messages=[],
                placeholder_map={},
            )
            is False
        )
        assert store.get(h) is None


def test_sqlite_file_is_0600(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.store(
        payload_hash=VALID_HASH,
        agent_id="x", lane="x",
        original_messages=[], redacted_messages=[], placeholder_map={},
    )
    mode = store.path.stat().st_mode & 0o777
    assert mode == 0o600


def test_overwrites_on_repeat_hash(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.store(
        payload_hash=VALID_HASH,
        agent_id="first", lane="x",
        original_messages=[], redacted_messages=[], placeholder_map={},
    )
    store.store(
        payload_hash=VALID_HASH,
        agent_id="second", lane="x",
        original_messages=[], redacted_messages=[], placeholder_map={},
    )
    detail = store.get(VALID_HASH)
    assert detail is not None
    assert detail["agent_id"] == "second"


def test_retention_prunes_on_write(tmp_path: Path) -> None:
    """Rows past the retention window get swept on the next insert."""
    store = _store(tmp_path, retention_hours=24)
    # Backdate one row 48h into the past by writing directly.
    old_ts = (
        datetime.now(tz=timezone.utc) - timedelta(hours=48)
    ).isoformat()
    conn = sqlite3.connect(store.path)
    try:
        conn.execute(
            "INSERT INTO redaction_log "
            "(payload_hash, stored_at, agent_id, lane, "
            "original_messages, redacted_messages, placeholder_map) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (OTHER_HASH, old_ts, "old", "x", "[]", "[]", "{}"),
        )
        conn.commit()
    finally:
        conn.close()
    # Sanity: the old row is readable before pruning.
    assert store.get(OTHER_HASH) is not None
    # A fresh insert triggers opportunistic pruning of the stale row.
    store.store(
        payload_hash=VALID_HASH,
        agent_id="fresh", lane="x",
        original_messages=[], redacted_messages=[], placeholder_map={},
    )
    assert store.get(OTHER_HASH) is None
    assert store.get(VALID_HASH) is not None


def test_prune_older_than_returns_count(tmp_path: Path) -> None:
    # Keep the insert path's opportunistic prune quiet.
    store = _store(tmp_path, retention_hours=24 * 365)
    old_ts = (
        datetime.now(tz=timezone.utc) - timedelta(hours=48)
    ).isoformat()
    conn = sqlite3.connect(store.path)
    try:
        for h in (VALID_HASH, OTHER_HASH):
            conn.execute(
                "INSERT INTO redaction_log "
                "(payload_hash, stored_at, agent_id, lane, "
                "original_messages, redacted_messages, placeholder_map) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (h, old_ts, "x", "x", "[]", "[]", "{}"),
            )
        conn.commit()
    finally:
        conn.close()
    assert store.prune_older_than(hours=24) == 2
    assert store.get(VALID_HASH) is None
    assert store.get(OTHER_HASH) is None


def test_corrupt_row_returns_none(tmp_path: Path) -> None:
    store = _store(tmp_path)
    conn = sqlite3.connect(store.path)
    try:
        conn.execute(
            "INSERT INTO redaction_log "
            "(payload_hash, stored_at, agent_id, lane, "
            "original_messages, redacted_messages, placeholder_map) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                VALID_HASH,
                datetime.now(tz=timezone.utc).isoformat(),
                "x", "x",
                "not-json", "[]", "{}",
            ),
        )
        conn.commit()
    finally:
        conn.close()
    assert store.get(VALID_HASH) is None

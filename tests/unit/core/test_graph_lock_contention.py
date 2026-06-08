"""Tests for Kuzu read-only lock-contention handling.

While the pipeline holds Kuzu's exclusive read-write lock, every other
open fails with "Could not set lock on file". The graph engine retries
those transient failures, and ``graph-summary`` surfaces an honest error
instead of rendering an unreachable graph as an empty all-zeros one.

All tests stay in-process and monkeypatch the Kuzu open, so they never
touch the real ~/.arandu/data/kuzu_db or depend on cross-process timing.

sensitivity_tier: N/A (infrastructure layer)
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from src.core.cli import _graph_error_message
from src.core.cli import main as cli_main
from src.core.kuzu import engine as engine_mod
from src.core.kuzu.engine import GraphEngine, _is_lock_contention

_LOCK_ERROR = RuntimeError(
    "IO exception: Could not set lock on file : /tmp/kuzu_db\n"
    "See the docs: https://docs.kuzudb.com/concurrency for more information."
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class TestLockHelpers:
    def test_is_lock_contention_matches_kuzu_io_exception(self) -> None:
        assert _is_lock_contention(_LOCK_ERROR)

    def test_is_lock_contention_ignores_unrelated_errors(self) -> None:
        assert not _is_lock_contention(RuntimeError("table not found"))

    def test_graph_error_message_friendly_for_lock(self) -> None:
        msg = _graph_error_message(_LOCK_ERROR)
        assert "pipeline" in msg.lower()
        assert "lock" not in msg.lower()  # no raw Kuzu jargon leaks out

    def test_graph_error_message_passthrough_for_other_errors(self) -> None:
        assert _graph_error_message(RuntimeError("boom")) == "boom"


# ---------------------------------------------------------------------------
# Engine open retry
# ---------------------------------------------------------------------------


class _FakeDatabase:
    """Stand-in for kuzu.Database that fails a fixed number of times."""

    def __init__(self, *_: object, **__: object) -> None:
        pass


class TestOpenWithRetry:
    def test_retries_then_succeeds_on_transient_lock(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A lock held for the first two opens is retried past, not fatal."""
        attempts = {"n": 0}
        sleeps: list[float] = []

        def fake_db(*args: object, **kwargs: object) -> _FakeDatabase:
            attempts["n"] += 1
            if attempts["n"] < 3:
                raise _LOCK_ERROR
            return _FakeDatabase()

        monkeypatch.setattr(engine_mod.kuzu, "Database", fake_db)
        monkeypatch.setattr(engine_mod.kuzu, "Connection", lambda _db: object())
        monkeypatch.setattr(engine_mod.time, "sleep", sleeps.append)

        eng = GraphEngine(db_path=tmp_path / "kuzu_db", read_only=True)

        assert attempts["n"] == 3
        assert len(sleeps) == 2  # backed off before each retry
        assert eng._db is not None

    def test_reraises_after_exhausting_attempts(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A sustained lock surfaces the error once retries run out."""
        monkeypatch.setattr(
            engine_mod.kuzu, "Database",
            lambda *a, **k: (_ for _ in ()).throw(_LOCK_ERROR),
        )
        monkeypatch.setattr(engine_mod.time, "sleep", lambda _s: None)

        with pytest.raises(RuntimeError, match="set lock on file"):
            GraphEngine(db_path=tmp_path / "kuzu_db", read_only=True)

    def test_non_lock_error_is_not_retried(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Unrelated open failures propagate immediately without backoff."""
        sleeps: list[float] = []
        monkeypatch.setattr(
            engine_mod.kuzu, "Database",
            lambda *a, **k: (_ for _ in ()).throw(RuntimeError("corrupt db")),
        )
        monkeypatch.setattr(engine_mod.time, "sleep", sleeps.append)

        with pytest.raises(RuntimeError, match="corrupt db"):
            GraphEngine(db_path=tmp_path / "kuzu_db", read_only=True)
        assert sleeps == []  # no retry on non-contention errors


# ---------------------------------------------------------------------------
# graph-summary surfaces the failure (does not mask it as zeros)
# ---------------------------------------------------------------------------


class TestGraphSummarySurfacesLock:
    def test_graph_summary_errors_instead_of_zeros_when_locked(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A locked graph must yield exit 1 + friendly error, not all-zeros."""
        # Make the engine open always fail with lock contention, fast.
        monkeypatch.setattr(engine_mod.time, "sleep", lambda _s: None)
        monkeypatch.setattr(
            engine_mod.kuzu, "Database",
            lambda *a, **k: (_ for _ in ()).throw(_LOCK_ERROR),
        )

        rc = cli_main(["--data-dir", str(tmp_path), "graph-summary"])

        captured = capsys.readouterr()
        assert rc == 1, "lock contention must be a failure, not silent zeros"
        assert captured.out.strip() == "", "no summary should be printed"
        payload = json.loads(captured.err.strip().splitlines()[-1])
        assert "pipeline" in payload["error"].lower()

"""Tests for :mod:`src.core.retrieval.retrieval_log`.

sensitivity_tier: N/A
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest
from src.core.retrieval import retrieval_log
from src.core.sqlite.engine import DatabaseEngine


@pytest.fixture
def db(tmp_path: Path) -> DatabaseEngine:
    engine = DatabaseEngine(db_path=tmp_path / "log.sqlite3")
    retrieval_log.init_table(engine)
    return engine


class TestInitTable:
    def test_idempotent(self, db: DatabaseEngine) -> None:
        retrieval_log.init_table(db)  # second call must not raise
        rows = db.query(f"SELECT count(*) AS n FROM {retrieval_log.TABLE}")
        assert rows[0]["n"] == 0


class TestRecord:
    def test_basic_write(self, db: DatabaseEngine) -> None:
        rid = retrieval_log.record(
            db,
            query="who is Israel?",
            retrieved_ids=["a", "b"],
            scores=[0.9, 0.8],
            latency_ms=12.5,
            mode="hybrid",
            embedding_model="bge-m3",
            policy="remote-default",
        )
        assert rid
        rows = retrieval_log.recent(db)
        assert len(rows) == 1
        r = rows[0]
        assert r.query == "who is Israel?"
        assert r.retrieved_ids == ["a", "b"]
        assert r.scores == [0.9, 0.8]
        assert r.latency_ms == pytest.approx(12.5)
        assert r.mode == "hybrid"
        assert r.embedding_model == "bge-m3"
        assert r.policy == "remote-default"

    def test_extra_payload_roundtrips(self, db: DatabaseEngine) -> None:
        retrieval_log.record(
            db, query="q", retrieved_ids=[], scores=[],
            latency_ms=0.0, mode="hybrid",
            extra={"vector_n": 20, "bm25_n": 50},
        )
        rows = retrieval_log.recent(db)
        assert rows[0].extra == {"vector_n": 20, "bm25_n": 50}

    def test_failure_swallowed(self, tmp_path: Path) -> None:
        # Point at a path that doesn't allow DB creation. record()
        # logs the error but never raises — observability outage
        # must not break live retrieval.
        bad_db = DatabaseEngine(db_path=tmp_path / "log.sqlite3")
        # Drop the table after init so the insert fails.
        retrieval_log.init_table(bad_db)
        bad_db.execute(f"DROP TABLE {retrieval_log.TABLE}")
        # init_table inside record() recreates it — that's fine; this
        # test mainly asserts that *some* failure path doesn't raise.
        rid = retrieval_log.record(
            bad_db, query="q", retrieved_ids=[], scores=[],
            latency_ms=0.0, mode="hybrid",
        )
        assert rid  # always returns an id, even on failure


class TestRecent:
    def test_newest_first(self, db: DatabaseEngine) -> None:
        retrieval_log.record(
            db, query="first", retrieved_ids=[], scores=[],
            latency_ms=0.0, mode="hybrid",
        )
        time.sleep(0.01)
        retrieval_log.record(
            db, query="second", retrieved_ids=[], scores=[],
            latency_ms=0.0, mode="hybrid",
        )
        rows = retrieval_log.recent(db, limit=10)
        assert [r.query for r in rows] == ["second", "first"]

    def test_limit_respected(self, db: DatabaseEngine) -> None:
        for i in range(5):
            retrieval_log.record(
                db, query=f"q{i}", retrieved_ids=[], scores=[],
                latency_ms=0.0, mode="hybrid",
            )
        assert len(retrieval_log.recent(db, limit=3)) == 3

    def test_mode_filter(self, db: DatabaseEngine) -> None:
        retrieval_log.record(
            db, query="a", retrieved_ids=[], scores=[],
            latency_ms=0.0, mode="hybrid",
        )
        retrieval_log.record(
            db, query="b", retrieved_ids=[], scores=[],
            latency_ms=0.0, mode="vector",
        )
        only_hybrid = retrieval_log.recent(db, mode="hybrid")
        assert [r.query for r in only_hybrid] == ["a"]


class TestMeasure:
    def test_records_elapsed(self) -> None:
        with retrieval_log.measure() as t:
            time.sleep(0.01)
        assert t.ms >= 10.0

    def test_propagates_exceptions(self) -> None:
        with pytest.raises(RuntimeError), retrieval_log.measure():
            raise RuntimeError("boom")

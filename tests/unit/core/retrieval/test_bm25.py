"""Tests for :mod:`src.core.retrieval.bm25`.

Uses a real ephemeral SQLite database so FTS5 indexing semantics
match production. Each test gets its own ``tmp_path`` DB.

sensitivity_tier: N/A
"""

from __future__ import annotations

from pathlib import Path

import pytest
from src.core.retrieval import bm25
from src.core.sqlite.engine import DatabaseEngine


@pytest.fixture
def db(tmp_path: Path) -> DatabaseEngine:
    """Fresh ``DatabaseEngine`` with the FTS table initialised."""
    engine = DatabaseEngine(db_path=tmp_path / "fts.sqlite3")
    bm25.init_table(engine)
    return engine


def _row(
    chunk_id: str,
    text: str,
    *,
    record_id: str | None = None,
    collection: str = "personal",
    layer: str = "raw",
    tier: int = 2,
) -> dict:
    return {
        "id": chunk_id,
        "record_id": record_id or chunk_id,
        "text": text,
        "collection": collection,
        "layer": layer,
        "sensitivity_tier": tier,
    }


class TestSchema:
    def test_init_is_idempotent(self, db: DatabaseEngine) -> None:
        # Already initialised by the fixture; second call must not raise.
        bm25.init_table(db)
        assert bm25.count(db) == 0

    def test_clear_returns_previous_count(self, db: DatabaseEngine) -> None:
        bm25.upsert_documents(
            db,
            [_row("a", "hello"), _row("b", "world")],
        )
        assert bm25.count(db) == 2
        removed = bm25.clear(db)
        assert removed == 2
        assert bm25.count(db) == 0


class TestSanitiseQuery:
    def test_strips_reserved(self) -> None:
        cleaned = bm25.sanitise_query('Who is "Israel"?')
        assert '"' not in cleaned
        assert "?" in cleaned or "Who" in cleaned

    def test_collapses_whitespace(self) -> None:
        assert bm25.sanitise_query("a   b\nc") == "a b c"

    def test_empty_query_handled(self) -> None:
        assert bm25.sanitise_query("") == ""
        assert bm25.sanitise_query('"""') == ""


class TestSearch:
    def test_empty_query_returns_empty(self, db: DatabaseEngine) -> None:
        bm25.upsert_documents(db, [_row("a", "hello")])
        assert bm25.search(db, "") == []

    def test_unique_token_hit(self, db: DatabaseEngine) -> None:
        bm25.upsert_documents(
            db,
            [
                _row("a", "Contact: Israel Casa Rosa"),
                _row("b", "Contact: Marcos"),
                _row("c", "Contact: Daiana"),
            ],
        )
        hits = bm25.search(db, "Israel")
        assert hits
        assert hits[0].id == "a"

    def test_or_match_across_tokens(self, db: DatabaseEngine) -> None:
        # Query has multiple terms — OR match ensures docs containing
        # any term surface. "Israel rosa" should still find doc a.
        bm25.upsert_documents(
            db,
            [
                _row("a", "Contact: Israel Casa Rosa"),
                _row("b", "Event: Standup"),
            ],
        )
        hits = bm25.search(db, "Israel rosa")
        assert {h.id for h in hits} == {"a"}

    def test_diacritics_folded(self, db: DatabaseEngine) -> None:
        # The remove_diacritics tokenizer folds joao ↔ joão.
        bm25.upsert_documents(
            db, [_row("a", "Contact: João Paulo")],
        )
        hits = bm25.search(db, "joao")
        assert hits and hits[0].id == "a"

    def test_tier_filter_applied(self, db: DatabaseEngine) -> None:
        bm25.upsert_documents(
            db,
            [
                _row("a", "secret", tier=3),
                _row("b", "secret", tier=1),
            ],
        )
        hits = bm25.search(db, "secret", max_tier=1)
        assert [h.id for h in hits] == ["b"]

    def test_collection_filter_applied(self, db: DatabaseEngine) -> None:
        bm25.upsert_documents(
            db,
            [
                _row("a", "lunch plans", collection="personal"),
                _row("b", "lunch plans", collection="work"),
            ],
        )
        hits = bm25.search(db, "lunch", collections=["work"])
        assert [h.id for h in hits] == ["b"]

    def test_score_is_positive_descending(self, db: DatabaseEngine) -> None:
        bm25.upsert_documents(
            db,
            [
                _row("a", "alpha beta"),
                _row("b", "alpha alpha alpha beta"),
                _row("c", "gamma delta"),
            ],
        )
        hits = bm25.search(db, "alpha")
        # Both relevant docs returned, sorted by descending score
        ids = [h.id for h in hits]
        assert "a" in ids and "b" in ids
        scores = [h.score for h in hits if h.id in ("a", "b")]
        assert scores == sorted(scores, reverse=True)

    def test_failed_query_returns_empty(self, db: DatabaseEngine) -> None:
        # Reserved chars get stripped by sanitise — even pathological
        # input shouldn't raise.
        hits = bm25.search(db, '""')
        assert hits == []


class TestUpsert:
    def test_upsert_is_replace_not_insert(
        self, db: DatabaseEngine,
    ) -> None:
        bm25.upsert_documents(db, [_row("a", "first")])
        assert bm25.count(db) == 1
        bm25.upsert_documents(db, [_row("a", "second")])
        assert bm25.count(db) == 1
        hits = bm25.search(db, "second")
        assert hits and hits[0].id == "a"

    def test_empty_batch_is_noop(self, db: DatabaseEngine) -> None:
        bm25.upsert_documents(db, [])
        assert bm25.count(db) == 0

    def test_record_id_carried_through(
        self, db: DatabaseEngine,
    ) -> None:
        bm25.upsert_documents(
            db,
            [_row("a-chunk-0", "alpha", record_id="a")],
        )
        hits = bm25.search(db, "alpha")
        assert hits[0].record_id == "a"

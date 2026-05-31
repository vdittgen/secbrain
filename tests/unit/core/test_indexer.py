"""Unit tests for the DuckDB-to-ChromaDB indexer.

Tests cover: pure composition functions, chunking, domain
classification, and full Indexer class integration (using real
DuckDB + real ChromaDB with DefaultEmbeddingFunction).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from chromadb.utils.embedding_functions import DefaultEmbeddingFunction
from src.core.chromadb.engine import COLLECTION_NAMES, VectorEngine
from src.core.chromadb.indexer import (
    Indexer,
    chunk_text,
    classify_calendar_domain,
    classify_contact_domain,
    classify_message_domain,
    classify_note_domain,
    compose_calendar_text,
    compose_note_text,
)
from src.core.sqlite.engine import DatabaseEngine
from src.core.sqlite.schemas import create_all_tables

from tests.fixtures.sample_data import load_all_fixtures as load_sample

# ------------------------------------------------------------------
# Compose functions
# ------------------------------------------------------------------


class TestComposeCalendarText:
    def test_includes_all_fields(self) -> None:
        row = {
            "title": "Standup",
            "description": "Daily sync",
            "location": "Zoom",
            "start_time": "2025-06-01T09:00",
            "end_time": "2025-06-01T09:30",
            "attendees": '["alice", "bob"]',
        }
        result = compose_calendar_text(row)
        assert "Standup" in result
        assert "Daily sync" in result
        assert "Location: Zoom" in result
        assert "Attendees:" in result


class TestComposeNoteText:
    def test_includes_title_and_content(self) -> None:
        row = {
            "title": "My Note",
            "content": "Some content",
            "tags": '["a", "b"]',
        }
        result = compose_note_text(row)
        assert "My Note" in result
        assert "Some content" in result
        assert "Tags:" in result

    def test_empty_note(self) -> None:
        result = compose_note_text({})
        assert result == ""


# ------------------------------------------------------------------
# Chunking
# ------------------------------------------------------------------


class TestChunkText:
    def test_short_text_single_chunk(self) -> None:
        text = "Hello world"
        assert chunk_text(text) == ["Hello world"]

    def test_empty_string(self) -> None:
        assert chunk_text("") == [""]

    def test_long_text_splits(self) -> None:
        # 500 tokens * 4 chars = 2000 chars max per chunk
        text = "word " * 600  # ~3000 chars
        chunks = chunk_text(text)
        assert len(chunks) >= 2

    def test_paragraph_boundary_split(self) -> None:
        para1 = "A" * 1500
        para2 = "B" * 1500
        text = f"{para1}\n\n{para2}"
        chunks = chunk_text(text)
        assert len(chunks) == 2
        assert chunks[0].startswith("A")
        assert chunks[1].startswith("B")

    def test_sentence_boundary_split(self) -> None:
        # Single paragraph with sentences
        sentences = ". ".join(["Sentence"] * 500)
        chunks = chunk_text(sentences)
        assert len(chunks) >= 2

    def test_custom_max_tokens(self) -> None:
        text = "word " * 100  # 500 chars
        chunks = chunk_text(text, max_tokens=50)  # 200 chars
        assert len(chunks) >= 2


# ------------------------------------------------------------------
# Domain classification
# ------------------------------------------------------------------


class TestClassifyMessageDomain:
    def test_slack_is_work(self) -> None:
        row = {"source": "slack", "sender": "a", "recipient": "b"}
        assert classify_message_domain(row) == "work"

    def test_company_email_is_work(self) -> None:
        row = {
            "source": "gmail",
            "sender": "a@company.com",
            "recipient": "me",
        }
        assert classify_message_domain(row) == "work"

    def test_imessage_is_personal(self) -> None:
        row = {"source": "imessage", "sender": "mom", "recipient": "me"}
        assert classify_message_domain(row) == "personal"

    def test_doctor_relationship_is_health(self) -> None:
        contacts = [
            {
                "email": "doc@clinic.com",
                "name": "Dr.",
                "relationship": "doctor",
            },
        ]
        row = {
            "source": "gmail",
            "sender": "doc@clinic.com",
            "recipient": "me",
        }
        assert classify_message_domain(row, contacts) == "health"

    def test_friend_is_personal(self) -> None:
        contacts = [
            {"email": "pal@x.com", "name": "Pal", "relationship": "friend"},
        ]
        row = {
            "source": "gmail",
            "sender": "pal@x.com",
            "recipient": "me",
        }
        assert classify_message_domain(row, contacts) == "personal"

    def test_default_is_personal(self) -> None:
        row = {"source": "gmail", "sender": "x@y.com", "recipient": "me"}
        assert classify_message_domain(row) == "personal"


class TestClassifyCalendarDomain:
    def test_therapy_is_health(self) -> None:
        row = {"title": "Therapy Session", "description": ""}
        assert classify_calendar_domain(row) == "health"

    def test_standup_is_work(self) -> None:
        row = {"title": "Team Stand-up", "description": "Daily sync"}
        assert classify_calendar_domain(row) == "work"

    def test_concert_is_social(self) -> None:
        row = {"title": "Concert", "description": "Friday night"}
        assert classify_calendar_domain(row) == "social"

    def test_flight_is_personal(self) -> None:
        row = {"title": "Flight to NYC", "description": ""}
        assert classify_calendar_domain(row) == "personal"

    def test_default_is_personal(self) -> None:
        row = {"title": "Something", "description": ""}
        assert classify_calendar_domain(row) == "personal"


class TestClassifyNoteDomain:
    def test_work_tags(self) -> None:
        row = {"tags": '["work", "meetings"]', "title": "Notes"}
        assert classify_note_domain(row) == "work"

    def test_health_tags(self) -> None:
        row = {"tags": '["health", "sleep"]', "title": "Log"}
        assert classify_note_domain(row) == "health"

    def test_ideas_tags(self) -> None:
        row = {"tags": '["ideas", "coding"]', "title": "Project"}
        assert classify_note_domain(row) == "ideas"

    def test_social_tags(self) -> None:
        row = {"tags": '["friends", "social"]', "title": "Plans"}
        assert classify_note_domain(row) == "social"

    def test_default_is_personal(self) -> None:
        row = {"tags": '["recipes"]', "title": "Chicken"}
        assert classify_note_domain(row) == "personal"


class TestClassifyContactDomain:
    def test_colleague_is_work(self) -> None:
        row = {"relationship": "colleague"}
        assert classify_contact_domain(row) == "work"

    def test_family_is_personal(self) -> None:
        row = {"relationship": "family"}
        assert classify_contact_domain(row) == "personal"


# ------------------------------------------------------------------
# Indexer integration tests (real DuckDB + real ChromaDB)
# ------------------------------------------------------------------


@pytest.fixture()
def engines(tmp_path: Path):
    """DuckDB + ChromaDB engines with fixtures loaded."""
    duck = DatabaseEngine(
        db_path=tmp_path / "test.duckdb",
    )
    chroma = VectorEngine(
        db_path=tmp_path / "chroma",
        embedding_fn=DefaultEmbeddingFunction(),
    )
    create_all_tables(duck)
    load_sample(duck)
    yield duck, chroma
    duck.close()
    chroma.close()


class TestIndexer:
    def test_full_reindex_populates_collections(
        self, engines,
    ) -> None:
        duck, chroma = engines
        indexer = Indexer(duckdb=duck, chromadb=chroma)
        counts = indexer.full_reindex()

        total = sum(counts.values())
        assert total > 0
        # Should have docs in at least 3 collections
        assert len(counts) >= 3

    def test_full_reindex_is_idempotent(
        self, engines,
    ) -> None:
        duck, chroma = engines
        indexer = Indexer(duckdb=duck, chromadb=chroma)
        counts1 = indexer.full_reindex()
        counts2 = indexer.full_reindex()

        # Same counts after reindex
        for name in COLLECTION_NAMES:
            col = chroma.get_or_create_collection(name)
            c1 = counts1.get(name, 0)
            c2 = counts2.get(name, 0)
            assert c1 == c2, (
                f"{name}: first={c1}, second={c2}"
            )
            assert col.count() == c2

    def test_metadata_fields_present(
        self, engines,
    ) -> None:
        duck, chroma = engines
        indexer = Indexer(duckdb=duck, chromadb=chroma)
        indexer.full_reindex()

        required = {
            "source_table", "record_id", "timestamp",
            "sensitivity_tier", "domain",
            "chunk_index", "source",
        }
        for name in COLLECTION_NAMES:
            results = chroma.search(name, "test", n_results=5)
            for r in results:
                missing = required - set(r["metadata"].keys())
                assert not missing, (
                    f"Doc {r['id']} in '{name}' missing: {missing}"
                )

    def test_sensitivity_tier_preserved(
        self, engines,
    ) -> None:
        duck, chroma = engines
        indexer = Indexer(duckdb=duck, chromadb=chroma)
        indexer.full_reindex()

        # All health collection docs should be tier 3
        results = chroma.search(
            "health", "health metric", n_results=20,
        )
        for r in results:
            assert r["metadata"]["sensitivity_tier"] == 3, (
                f"Health doc {r['id']} is not tier 3"
            )

    def test_health_metrics_in_health_collection(
        self, engines,
    ) -> None:
        duck, chroma = engines
        indexer = Indexer(duckdb=duck, chromadb=chroma)
        indexer.full_reindex()

        results = chroma.search(
            "health", "heart rate blood pressure",
            n_results=20,
        )
        health_metric_docs = [
            r for r in results
            if r["metadata"]["source_table"] == "raw_health_metrics"
        ]
        assert len(health_metric_docs) > 0

    def test_chunk_index_metadata(self, engines) -> None:
        duck, chroma = engines
        indexer = Indexer(duckdb=duck, chromadb=chroma)
        indexer.full_reindex()

        # Fixture data is short, so all chunk_index should be 0
        for name in COLLECTION_NAMES:
            results = chroma.search(name, "test", n_results=20)
            for r in results:
                assert r["metadata"]["chunk_index"] == 0

    def test_work_messages_in_work_collection(
        self, engines,
    ) -> None:
        duck, chroma = engines
        indexer = Indexer(duckdb=duck, chromadb=chroma)
        indexer.full_reindex()

        results = chroma.search(
            "work", "code review pull request",
            n_results=10,
        )
        assert len(results) > 0
        for r in results:
            assert r["metadata"]["domain"] == "work"

    def test_incremental_index_returns_counts(
        self, engines,
    ) -> None:
        """incremental_index should index some or all docs."""
        duck, chroma = engines
        indexer = Indexer(duckdb=duck, chromadb=chroma)
        # Use a timestamp far in the past to get all records
        from datetime import datetime, timezone
        since = datetime(2020, 1, 1, tzinfo=timezone.utc)
        counts = indexer.incremental_index(since=since)
        assert sum(counts.values()) > 0

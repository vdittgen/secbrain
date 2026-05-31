"""Search quality tests after DuckDB-to-ChromaDB indexing.

Verifies that the composed text format and indexing pipeline produce
semantically meaningful embeddings for realistic queries.  Uses real
DefaultEmbeddingFunction (MiniLM) and real DuckDB fixture data.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from chromadb.utils.embedding_functions import DefaultEmbeddingFunction
from src.core.chromadb.engine import VectorEngine
from src.core.chromadb.indexer import Indexer
from src.core.sqlite.engine import DatabaseEngine
from src.core.sqlite.schemas import create_all_tables

from tests.fixtures.sample_data import load_all_fixtures as load_sample


@pytest.fixture()
def indexed_engine(tmp_path: Path):
    """DuckDB with fixtures, ChromaDB indexed from DuckDB."""
    duck = DatabaseEngine(
        db_path=tmp_path / "test.duckdb",
    )
    chroma = VectorEngine(
        db_path=tmp_path / "chroma",
        embedding_fn=DefaultEmbeddingFunction(),
    )
    create_all_tables(duck)
    load_sample(duck)

    indexer = Indexer(duckdb=duck, chromadb=chroma)
    indexer.full_reindex()

    yield chroma
    duck.close()
    chroma.close()


class TestSearchQualityAfterIndexing:
    """Verify DuckDB-indexed documents produce good search results."""

    def test_meeting_query_finds_calendar_events(
        self, indexed_engine: VectorEngine,
    ) -> None:
        """'meeting with John' should return calendar/work content."""
        results = indexed_engine.search(
            "work", "meeting with team planning session",
            n_results=5,
        )
        assert len(results) >= 1
        # Should find work-related meeting content
        top_docs = " ".join(
            r["document"].lower() for r in results[:3]
        )
        meeting_terms = {
            "standup", "planning", "meeting", "sync",
            "review", "session", "stand-up", "1-on-1",
        }
        assert any(t in top_docs for t in meeting_terms), (
            f"No meeting-related docs found in: {top_docs[:200]}"
        )

    def test_feeling_query_finds_health_docs(
        self, indexed_engine: VectorEngine,
    ) -> None:
        """'how am I feeling' should return health/emotional content."""
        results = indexed_engine.search(
            "health", "how am I feeling health emotions",
            n_results=5,
        )
        assert len(results) >= 1
        # Should find health-related content
        top_docs = " ".join(
            r["document"].lower() for r in results[:3]
        )
        health_terms = {
            "heart", "sleep", "anxiety", "fatigue",
            "blood", "vitamin", "therapy", "weight",
            "doctor", "mental",
        }
        assert any(t in top_docs for t in health_terms), (
            f"No health docs found in: {top_docs[:200]}"
        )

    def test_project_query_finds_work_content(
        self, indexed_engine: VectorEngine,
    ) -> None:
        """'project deadline' should return work-related content."""
        results = indexed_engine.search(
            "work", "project deadline deployment",
            n_results=5,
        )
        assert len(results) >= 1
        for r in results:
            assert r["metadata"]["domain"] == "work"

    def test_health_metric_searchable(
        self, indexed_engine: VectorEngine,
    ) -> None:
        """Specific health metrics should be findable."""
        results = indexed_engine.search(
            "health", "heart rate blood pressure",
            n_results=5,
        )
        assert len(results) >= 1
        top_docs = " ".join(
            r["document"].lower() for r in results[:3]
        )
        assert "heart_rate" in top_docs or "blood" in top_docs

    def test_note_content_searchable(
        self, indexed_engine: VectorEngine,
    ) -> None:
        """Note content should be semantically searchable."""
        results = indexed_engine.search(
            "ideas", "AI tool git LLM",
            n_results=5,
        )
        assert len(results) >= 1

    def test_sensitivity_tier_filtering_works(
        self, indexed_engine: VectorEngine,
    ) -> None:
        """Metadata filtering should work on indexed docs."""
        results = indexed_engine.search(
            "personal", "family dinner",
            n_results=10,
            where={"sensitivity_tier": {"$lte": 2}},
        )
        for r in results:
            assert r["metadata"]["sensitivity_tier"] <= 2

    def test_personal_messages_searchable(
        self, indexed_engine: VectorEngine,
    ) -> None:
        """Personal messages should be in personal collection."""
        results = indexed_engine.search(
            "personal", "family dinner sunday sister",
            n_results=5,
        )
        assert len(results) >= 1
        for r in results:
            assert r["metadata"]["domain"] == "personal"

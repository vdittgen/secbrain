"""Unit tests for the ChromaDB vector engine and fixtures.

All tests use a temporary directory — never the real
~/.arandu/data/chromadb/ — so they are isolated and safe to run in any
environment.  The all-MiniLM-L6-v2 model must be cached locally (it is
downloaded once on first use).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from chromadb.utils.embedding_functions import DefaultEmbeddingFunction
from src.core.chromadb.engine import COLLECTION_NAMES, VectorEngine

from tests.fixtures.chromadb_fixtures import EXPECTED_COUNTS, load_all_fixtures

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def tmp_engine(tmp_path: Path) -> VectorEngine:
    """Fresh VectorEngine backed by a temp directory; closed after test."""
    engine = VectorEngine(
        db_path=tmp_path / "chroma_test",
        embedding_fn=DefaultEmbeddingFunction(),
    )
    yield engine
    engine.close()


@pytest.fixture()
def seeded_engine(tmp_path: Path) -> VectorEngine:
    """VectorEngine with all fixture documents already indexed."""
    engine = VectorEngine(
        db_path=tmp_path / "chroma_seeded",
        embedding_fn=DefaultEmbeddingFunction(),
    )
    load_all_fixtures(engine)
    yield engine
    engine.close()


# ---------------------------------------------------------------------------
# Engine initialisation
# ---------------------------------------------------------------------------


class TestVectorEngineInit:
    def test_creates_storage_directory(self, tmp_path: Path) -> None:
        """VectorEngine must create its storage directory on disk."""
        db_path = tmp_path / "sub" / "chroma_db"
        assert not db_path.exists()
        engine = VectorEngine(
            db_path=db_path,
            embedding_fn=DefaultEmbeddingFunction(),
        )
        engine.close()
        assert db_path.is_dir(), (
            "ChromaDB storage directory was not created"
        )

    def test_creates_nested_parent_dirs(
        self, tmp_path: Path,
    ) -> None:
        """Parent dirs that don't exist are created automatically."""
        db_path = tmp_path / "a" / "b" / "chroma_db"
        engine = VectorEngine(
            db_path=db_path,
            embedding_fn=DefaultEmbeddingFunction(),
        )
        engine.close()
        assert db_path.parent.is_dir()

    def test_context_manager(self, tmp_path: Path) -> None:
        """Context manager must open and close without error."""
        db_path = tmp_path / "cm_chroma"
        with VectorEngine(
            db_path=db_path,
            embedding_fn=DefaultEmbeddingFunction(),
        ) as engine:
            col = engine.get_or_create_collection("test_cm")
            assert col.name == "test_cm"


# ---------------------------------------------------------------------------
# Collection management
# ---------------------------------------------------------------------------


class TestCollectionManagement:
    def test_all_domain_collections_pre_created(
        self, tmp_engine: VectorEngine
    ) -> None:
        """All five domain collections must exist right after init."""
        for name in COLLECTION_NAMES:
            col = tmp_engine.get_or_create_collection(name)
            assert col.name == name

    def test_get_or_create_is_idempotent(
        self, tmp_engine: VectorEngine
    ) -> None:
        """Calling get_or_create_collection twice must not raise."""
        col1 = tmp_engine.get_or_create_collection("personal")
        col2 = tmp_engine.get_or_create_collection("personal")
        assert col1.name == col2.name

    def test_custom_collection_created(
        self, tmp_engine: VectorEngine
    ) -> None:
        """A collection outside COLLECTION_NAMES can be created on demand."""
        col = tmp_engine.get_or_create_collection("custom_domain")
        assert col.name == "custom_domain"


# ---------------------------------------------------------------------------
# Document operations
# ---------------------------------------------------------------------------


class TestDocumentOperations:
    def test_add_documents_succeeds(self, tmp_engine: VectorEngine) -> None:
        """add_documents() must not raise for valid inputs."""
        tmp_engine.add_documents(
            "work",
            documents=["The build is green.", "PR approved by Alice."],
            metadatas=[
                {
                    "source": "slack",
                    "timestamp": "2025-06-01T10:00:00Z",
                    "sensitivity_tier": 1,
                    "domain": "work",
                },
                {
                    "source": "github",
                    "timestamp": "2025-06-01T11:00:00Z",
                    "sensitivity_tier": 1,
                    "domain": "work",
                },
            ],
            ids=["t-001", "t-002"],
        )
        col = tmp_engine.get_or_create_collection("work")
        assert col.count() == 2

    def test_add_documents_length_mismatch_raises(
        self, tmp_engine: VectorEngine
    ) -> None:
        """Mismatched list lengths must raise ValueError."""
        with pytest.raises(ValueError, match="same length"):
            tmp_engine.add_documents(
                "work",
                documents=["doc1", "doc2"],
                metadatas=[{"source": "x", "timestamp": "t",
                            "sensitivity_tier": 1, "domain": "work"}],
                ids=["id-1", "id-2"],
            )

    def test_upsert_does_not_duplicate(self, tmp_engine: VectorEngine) -> None:
        """Adding the same ID twice must not create a duplicate document."""
        meta = {
            "source": "test",
            "timestamp": "2025-01-01T00:00:00Z",
            "sensitivity_tier": 1,
            "domain": "work",
        }
        tmp_engine.add_documents("work", ["original"], [meta], ["dup-1"])
        tmp_engine.add_documents("work", ["updated"], [meta], ["dup-1"])
        col = tmp_engine.get_or_create_collection("work")
        assert col.count() == 1

    def test_search_empty_collection_returns_empty(
        self, tmp_engine: VectorEngine
    ) -> None:
        """search() on an empty collection must return []."""
        results = tmp_engine.search("personal", "anything")
        assert results == []

    def test_search_returns_list_of_dicts(
        self, tmp_engine: VectorEngine
    ) -> None:
        """search() result rows must have the expected keys."""
        meta = {
            "source": "obsidian",
            "timestamp": "2025-06-01T00:00:00Z",
            "sensitivity_tier": 1,
            "domain": "ideas",
        }
        tmp_engine.add_documents(
            "ideas",
            ["Building a CLI tool for git summaries using AI."],
            [meta],
            ["idea-1"],
        )
        results = tmp_engine.search("ideas", "command line tool", n_results=1)
        assert isinstance(results, list)
        assert len(results) == 1
        row = results[0]
        assert set(row.keys()) == {"id", "document", "metadata", "distance"}
        assert isinstance(row["id"], str)
        assert isinstance(row["document"], str)
        assert isinstance(row["metadata"], dict)
        assert isinstance(row["distance"], float)

    def test_search_n_results_clamped_to_collection_size(
        self, tmp_engine: VectorEngine
    ) -> None:
        """search() must not crash when n_results > collection size."""
        meta = {
            "source": "test",
            "timestamp": "2025-01-01T00:00:00Z",
            "sensitivity_tier": 1,
            "domain": "work",
        }
        tmp_engine.add_documents("work", ["Only doc."], [meta], ["solo"])
        results = tmp_engine.search("work", "something", n_results=10)
        assert len(results) == 1


# ---------------------------------------------------------------------------
# Semantic search quality
# ---------------------------------------------------------------------------


class TestSemanticSearch:
    def test_relevant_result_ranked_first(
        self, seeded_engine: VectorEngine
    ) -> None:
        """A targeted query should rank a clearly relevant doc first."""
        results = seeded_engine.search(
            "health", "fatigue and doctor visit", n_results=3
        )
        assert len(results) >= 1
        top_doc = results[0]["document"].lower()
        # The top result should be related to health / doctor / fatigue
        health_terms = {"fatigue", "doctor", "appointment", "vitamin",
                        "sleep", "heart", "blood", "anxiety", "therapy"}
        assert any(term in top_doc for term in health_terms), (
            f"Expected a health-related doc first, got: {top_doc!r}"
        )

    def test_work_query_returns_work_docs(
        self, seeded_engine: VectorEngine
    ) -> None:
        """A work-domain query should return docs from the work collection."""
        results = seeded_engine.search(
            "work", "code review pull request", n_results=3
        )
        assert len(results) >= 1
        # All docs in the work collection have domain=work
        for r in results:
            assert r["metadata"]["domain"] == "work"

    def test_ideas_query_returns_relevant_result(
        self, seeded_engine: VectorEngine
    ) -> None:
        """'AI tool' query in ideas collection should find relevant notes."""
        results = seeded_engine.search(
            "ideas", "artificial intelligence tool", n_results=3
        )
        assert len(results) >= 1

    def test_results_ordered_by_distance(
        self, seeded_engine: VectorEngine
    ) -> None:
        """Results must be ordered ascending by distance (closest first)."""
        results = seeded_engine.search(
            "personal", "family dinner Sunday", n_results=5
        )
        distances = [r["distance"] for r in results]
        assert distances == sorted(distances), (
            "Results are not ordered by ascending distance"
        )


# ---------------------------------------------------------------------------
# Metadata filtering
# ---------------------------------------------------------------------------


class TestMetadataFiltering:
    def _seed_mixed_tiers(self, engine: VectorEngine) -> None:
        """Add docs with tier 1 and tier 3 to the 'work' collection."""
        engine.add_documents(
            "work",
            documents=[
                "Deploy to production tonight.",
                "Personal salary information and bonus details.",
                "Update the CI pipeline configuration.",
            ],
            metadatas=[
                {
                    "source": "slack",
                    "timestamp": "2025-06-01T00:00:00Z",
                    "sensitivity_tier": 1,
                    "domain": "work",
                },
                {
                    "source": "email",
                    "timestamp": "2025-06-01T00:00:00Z",
                    "sensitivity_tier": 3,
                    "domain": "work",
                },
                {
                    "source": "github",
                    "timestamp": "2025-06-01T00:00:00Z",
                    "sensitivity_tier": 1,
                    "domain": "work",
                },
            ],
            ids=["f-001", "f-002", "f-003"],
        )

    def test_where_filter_excludes_high_tier(
        self, tmp_engine: VectorEngine
    ) -> None:
        """A where filter on sensitivity_tier must exclude tier-3 docs."""
        self._seed_mixed_tiers(tmp_engine)
        results = tmp_engine.search(
            "work",
            "production deployment",
            n_results=5,
            where={"sensitivity_tier": {"$lte": 2}},
        )
        for r in results:
            assert r["metadata"]["sensitivity_tier"] <= 2, (
                f"Tier-3 doc slipped through: {r['id']}"
            )

    def test_where_filter_selects_only_tier3(
        self, tmp_engine: VectorEngine
    ) -> None:
        """A filter for tier==3 should return only the tier-3 doc."""
        self._seed_mixed_tiers(tmp_engine)
        results = tmp_engine.search(
            "work",
            "salary bonus",
            n_results=5,
            where={"sensitivity_tier": {"$eq": 3}},
        )
        assert len(results) == 1
        assert results[0]["id"] == "f-002"

    def test_filter_by_source(self, tmp_engine: VectorEngine) -> None:
        """Filtering by source metadata field must work correctly."""
        self._seed_mixed_tiers(tmp_engine)
        results = tmp_engine.search(
            "work",
            "pipeline configuration",
            n_results=5,
            where={"source": {"$eq": "github"}},
        )
        assert len(results) >= 1
        for r in results:
            assert r["metadata"]["source"] == "github"


# ---------------------------------------------------------------------------
# Fixture loading tests
# ---------------------------------------------------------------------------


class TestFixtureLoading:
    def test_all_collections_populated(
        self, seeded_engine: VectorEngine
    ) -> None:
        """Every domain collection must have the expected document count."""
        for collection_name, expected in EXPECTED_COUNTS.items():
            col = seeded_engine.get_or_create_collection(collection_name)
            actual = col.count()
            assert actual == expected, (
                f"Collection '{collection_name}':"
                f" expected {expected} docs, got {actual}"
            )

    def test_fixture_load_is_idempotent(
        self, seeded_engine: VectorEngine
    ) -> None:
        """Calling load_all_fixtures twice must not duplicate documents."""
        load_all_fixtures(seeded_engine)
        for collection_name, expected in EXPECTED_COUNTS.items():
            col = seeded_engine.get_or_create_collection(collection_name)
            assert col.count() == expected

    def test_health_docs_all_tier3(self, seeded_engine: VectorEngine) -> None:
        """Every indexed health document must carry sensitivity_tier=3."""
        results = seeded_engine.search(
            "health", "health metrics", n_results=20
        )
        for r in results:
            assert r["metadata"]["sensitivity_tier"] == 3, (
                f"Non-tier-3 doc in health collection: {r['id']}"
            )

    def test_metadata_fields_present(self, seeded_engine: VectorEngine) -> None:
        """Every document must carry all required metadata fields."""
        required = {"source", "timestamp", "sensitivity_tier", "domain"}
        for collection_name in EXPECTED_COUNTS:
            results = seeded_engine.search(
                collection_name, "anything", n_results=20
            )
            for r in results:
                missing = required - set(r["metadata"].keys())
                assert not missing, (
                    f"Doc {r['id']} in '{collection_name}'"
                    f" missing metadata fields: {missing}"
                )

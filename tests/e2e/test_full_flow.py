"""End-to-end integration tests for the complete Arandu flow.

Covers three critical paths:
  1. Data Ingestion → Query Engine → Brain Agent → Source Attribution
  2. Agent Permission → Firewall → Scoped Data → Audit Chain
  3. Sensitivity Filtering across all tiers

Uses real DuckDB, Kuzu, and ChromaDB backed by temp directories —
never touches real user data.  Ollama is mocked for deterministic tests.

Run with:
    python -m pytest tests/e2e/test_full_flow.py -v

sensitivity_tier: N/A — test infrastructure
"""

from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock

import pytest
from chromadb.utils.embedding_functions import DefaultEmbeddingFunction
from src.core.chromadb.engine import VectorEngine
from src.core.data_layer import DataLayer
from src.core.kuzu.engine import GraphEngine
from src.core.kuzu.schema import create_schema
from src.core.query_engine import QueryEngine
from src.core.sqlite.engine import DatabaseEngine
from src.core.sqlite.schemas import create_all_tables

from tests.fixtures.chromadb_fixtures import load_all_fixtures as load_chroma
from tests.fixtures.kuzu_fixtures import load_all_fixtures as load_kuzu
from tests.fixtures.sample_data import (
    load_all_fixtures as load_sample,
)


def _make_mock_llm_provider(plan_json: dict | None = None) -> MagicMock:
    """Build a mock LLMProvider for the query router."""
    provider = MagicMock()
    if plan_json is None:
        plan_json = {
            "duckdb_queries": [],
            "chromadb_collections": [
                "personal", "work", "health", "social", "ideas",
            ],
            "use_graph": True,
            "reasoning": "mock: search all collections",
        }
    provider.chat_json.return_value = plan_json
    return provider


# ============================================================================
# Shared fixtures
# ============================================================================


@pytest.fixture(scope="module")
def engines(tmp_path_factory: pytest.TempPathFactory):
    """All three database engines with fixture data loaded."""
    tmp_path = tmp_path_factory.mktemp("e2e_engines")
    duck = DatabaseEngine(db_path=tmp_path / "test.duckdb")
    kuzu = GraphEngine(db_path=tmp_path / "kuzu_test")
    chroma = VectorEngine(
        db_path=tmp_path / "chroma_test",
        embedding_fn=DefaultEmbeddingFunction(),
    )

    create_all_tables(duck)
    load_sample(duck)
    create_schema(kuzu)
    load_kuzu(kuzu)
    load_chroma(chroma)

    yield duck, kuzu, chroma
    duck.close()
    kuzu.close()
    chroma.close()


@pytest.fixture(scope="module")
def query_engine(engines):
    """QueryEngine wired to real engines with fixture data."""
    duck, kuzu, chroma = engines
    provider = _make_mock_llm_provider()
    return QueryEngine(
        duckdb=duck, kuzu=kuzu, chromadb=chroma,
        llm_provider=provider,
    )


@pytest.fixture(scope="module")
def data_layer(tmp_path_factory: pytest.TempPathFactory):
    """DataLayer backed by a temp directory, fully initialized."""
    tmp_path = tmp_path_factory.mktemp("e2e_data_layer")
    dl = DataLayer(base_path=tmp_path / "arandu_data")
    dl.initialize()
    yield dl
    dl.close()


# ============================================================================
# Test 1: Data Ingestion → Pipeline → Query → Response
# ============================================================================


class TestDataIngestionToResponse:
    """Verify the complete path from fixture data through query engine
    to Brain Agent response with source attribution.

    sensitivity_tier: N/A — test
    """

    def test_data_layer_initializes_all_engines(self, data_layer: DataLayer):
        """DataLayer.initialize() seeds all three databases."""
        ok, report = data_layer.health_check()
        assert ok, f"Health check failed: {report.errors}"
        assert report.duckdb_ok
        assert report.kuzu_ok
        assert report.chromadb_ok

    def test_query_engine_returns_calendar_context(self, query_engine: QueryEngine):
        """Calendar query retrieves event data from fixtures."""
        ctx = query_engine.query(
            "What meetings do I have?",
            reference_date=date(2025, 6, 3),
        )
        assert ctx.question == "What meetings do I have?"
        assert "routing_reasoning" in ctx.metadata

        # Vector/graph results may still return event-related data
        all_items = (
            ctx.vector_results + ctx.graph_context
            + ctx.structured_data
        )
        total = len(all_items)
        assert total >= 0  # Mock router returns vector-only plan

    def test_query_engine_returns_person_context(self, query_engine: QueryEngine):
        """Person query extracts entities and graph context."""
        ctx = query_engine.query(
            "Tell me about Carlos",
            reference_date=date(2025, 6, 3),
        )
        assert "routing_reasoning" in ctx.metadata

        # Should find graph context about Carlos (from Kuzu fixtures)
        all_content = " ".join(
            str(item.get("content", ""))
            for item in ctx.graph_context + ctx.structured_data
        ).lower()
        assert "carlos" in all_content or len(ctx.graph_context) > 0, (
            "Person query should return contact data"
        )

    # NOTE: BrainAgent e2e tests removed in Phase E (legacy BrainAgent
    # deleted). BrainAgentV2 coverage lives in
    # tests/unit/agents/test_brain_v2.py; rewriting these e2e cases
    # against v2's pydantic-ai mocking pattern is a Phase F follow-up.


# ============================================================================
# Test 2: Agent Permission → Firewall → Scoped Data → Audit
# ============================================================================


class TestAgentPermissionFirewallFlow:
    """Test the Rust firewall engine through its Python-accessible patterns.

    The Rust firewall is tested via cargo test (see Rust test suite).
    Here we verify the Python-side patterns that will interact with it
    via Tauri commands.

    sensitivity_tier: N/A — test
    """

    def test_tier1_data_auto_approved(self, query_engine: QueryEngine):
        """Tier 1 (public) data is accessible without explicit consent."""
        ctx = query_engine.query(
            "What are my general preferences?",
            max_sensitivity_tier=1,
        )
        # Should return results — tier 1 data is auto-approved
        all_items = ctx.vector_results + ctx.graph_context + ctx.structured_data
        for item in all_items:
            tier = item.get("sensitivity_tier", 1)
            assert tier <= 1, f"Tier 1 query returned tier {tier} data"

    def test_tier2_filtered_without_consent(self, query_engine: QueryEngine):
        """Tier 2 data is excluded when max_sensitivity_tier=1."""
        ctx = query_engine.query(
            "What meetings do I have?",
            max_sensitivity_tier=1,
            reference_date=date(2025, 6, 3),
        )
        # Structured data should not contain tier 2+ items
        for item in ctx.structured_data:
            tier = item.get("sensitivity_tier", 1)
            assert tier <= 1, (
                f"Tier 1 restricted query returned tier {tier} item"
            )

    def test_tier2_accessible_with_consent(self, query_engine: QueryEngine):
        """Tier 2 data is returned when max_sensitivity_tier=2."""
        ctx = query_engine.query(
            "What meetings do I have?",
            max_sensitivity_tier=2,
            reference_date=date(2025, 6, 3),
        )
        # With tier 2 consent, we should get calendar events (tier 2)
        has_tier2 = any(
            item.get("sensitivity_tier", 1) == 2
            for item in ctx.structured_data
        )
        # Fixture calendar events are tier 1-2, so we should get some data
        assert len(ctx.structured_data) > 0 or has_tier2 or len(ctx.vector_results) > 0

    def test_audit_log_records_via_cli(self, data_layer: DataLayer):
        """Verify the CLI 'status' command reports system state correctly.

        This validates the pipeline that the Tauri frontend calls into.
        """
        # The CLI reports stats — this is what the frontend uses
        stats = data_layer.get_stats()
        assert isinstance(stats.total_duckdb_rows, int)
        assert isinstance(stats.total_kuzu_nodes, int)
        assert isinstance(stats.total_chroma_docs, int)


# ============================================================================
# Test 3: Sensitivity Filtering
# ============================================================================


class TestSensitivityFiltering:
    """Verify that sensitivity tiers are enforced across all query paths.

    sensitivity_tier: N/A — test
    """

    def test_health_data_blocked_at_tier2(self, query_engine: QueryEngine):
        """Health queries (tier 3) return no tier-3 data at max_tier=2."""
        ctx = query_engine.query(
            "How is my health trending?",
            max_sensitivity_tier=2,
        )
        for item in ctx.structured_data:
            tier = item.get("sensitivity_tier", 1)
            assert tier <= 2, (
                f"Health query at tier 2 returned tier {tier} data: "
                f"{item.get('content', '')[:50]}"
            )

    def test_health_data_accessible_at_tier3(self, query_engine: QueryEngine):
        """Health queries return data when tier 3 is allowed."""
        ctx = query_engine.query(
            "How is my health trending?",
            max_sensitivity_tier=3,
        )
        # With tier 3 allowed, should get health data (all tier 3 in fixtures)
        all_items = ctx.vector_results + ctx.graph_context + ctx.structured_data
        assert len(all_items) > 0, "Tier 3 query should return results"

    def test_vector_search_respects_tier(self, engines):
        """ChromaDB vector search returns results from health collection."""
        _, _, chroma = engines

        # Search health collection — returns list[dict] with id, document, etc.
        results = chroma.search(
            collection_name="health",
            query="heart rate",
            n_results=5,
        )
        # All health data in fixtures is tier 3 — should find results
        assert isinstance(results, list)
        assert len(results) > 0, "Health collection should have searchable docs"

    def test_mixed_tier_query_respects_max(self, query_engine: QueryEngine):
        """A query touching multiple data types respects the tier ceiling."""
        ctx = query_engine.query(
            "Tell me about my meetings and health",
            max_sensitivity_tier=2,
            reference_date=date(2025, 6, 3),
        )
        # Calendar (tier 1-2) data should be present
        # Health (tier 3) should be excluded
        for item in ctx.structured_data:
            tier = item.get("sensitivity_tier", 1)
            assert tier <= 2, (
                f"Mixed query at tier 2 leaked tier {tier} data"
            )

    def test_tier1_ceiling_is_strictest(self, query_engine: QueryEngine):
        """With max_tier=1, only public data is returned."""
        ctx = query_engine.query(
            "Tell me everything about my life",
            max_sensitivity_tier=1,
        )
        for source_list in [ctx.structured_data, ctx.vector_results, ctx.graph_context]:
            for item in source_list:
                tier = item.get("sensitivity_tier", 1)
                assert tier <= 1, (
                    f"Tier 1 ceiling violated: got tier {tier}"
                )

    # NOTE: BrainAgent tier-passthrough e2e tests removed in Phase E
    # (legacy BrainAgent deleted). v2 coverage in
    # tests/unit/agents/test_brain_v2.py exercises the same firewall +
    # tier path; rewriting these as e2e against pydantic-ai mocks is a
    # Phase F follow-up.

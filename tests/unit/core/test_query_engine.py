"""Unit tests for LLM-driven query routing and safe query building.

Tests cover: DuckDBQuerySpec defaults, RetrievalPlan validation,
build_safe_query whitelisting/injection prevention, LLMRouter plan
parsing, and default fallback behavior.

sensitivity_tier: N/A — test infrastructure
"""

from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock

import pytest
from src.core.query_engine import (
    DuckDBQuerySpec,
    LLMRouter,
    RetrievalPlan,
    _topic_boost_relevance,
    build_safe_query,
)

# ------------------------------------------------------------------
# DuckDBQuerySpec defaults
# ------------------------------------------------------------------


class TestDuckDBQuerySpec:
    def test_defaults(self) -> None:
        """DuckDBQuerySpec has correct default values."""
        spec = DuckDBQuerySpec(
            table="raw_notes",
            columns=["title", "content"],
        )
        assert spec.where is None
        assert spec.order_by is None
        assert spec.limit == 10

    def test_custom_values(self) -> None:
        """DuckDBQuerySpec accepts custom values."""
        spec = DuckDBQuerySpec(
            table="raw_messages",
            columns=["sender", "content"],
            where="sender LIKE '%Alice%'",
            order_by="timestamp DESC",
            limit=5,
        )
        assert spec.table == "raw_messages"
        assert spec.where == "sender LIKE '%Alice%'"
        assert spec.order_by == "timestamp DESC"
        assert spec.limit == 5


# ------------------------------------------------------------------
# RetrievalPlan
# ------------------------------------------------------------------


class TestRetrievalPlan:
    def test_creation(self) -> None:
        """RetrievalPlan can be created with all fields."""
        plan = RetrievalPlan(
            duckdb_queries=[
                DuckDBQuerySpec(
                    table="raw_notes",
                    columns=["title"],
                ),
            ],
            chromadb_collections=["personal"],
            use_graph=False,
            reasoning="test plan",
        )
        assert len(plan.duckdb_queries) == 1
        assert plan.chromadb_collections == ["personal"]
        assert plan.use_graph is False
        assert plan.reasoning == "test plan"


# ------------------------------------------------------------------
# build_safe_query
# ------------------------------------------------------------------


class TestBuildSafeQuery:
    def test_whitelisted_table_and_columns(self) -> None:
        """Allowed table+columns produce correct SQL."""
        spec = DuckDBQuerySpec(
            table="raw_notes",
            columns=["title", "content", "updated_at"],
            order_by="updated_at DESC",
            limit=10,
        )
        sql = build_safe_query(spec)
        assert sql is not None
        assert "SELECT title, content, updated_at" in sql
        assert "FROM raw_notes" in sql
        assert "ORDER BY updated_at DESC" in sql
        assert "LIMIT 10" in sql

    def test_rejects_unknown_table(self) -> None:
        """Unknown table returns None."""
        spec = DuckDBQuerySpec(
            table="raw_secrets",
            columns=["password"],
        )
        assert build_safe_query(spec) is None

    def test_rejects_unknown_columns(self) -> None:
        """All columns not in whitelist returns None."""
        spec = DuckDBQuerySpec(
            table="raw_notes",
            columns=["password", "secret_key"],
        )
        assert build_safe_query(spec) is None

    def test_filters_invalid_columns(self) -> None:
        """Invalid columns are stripped, valid ones kept."""
        spec = DuckDBQuerySpec(
            table="raw_notes",
            columns=["title", "fake_col", "content"],
        )
        sql = build_safe_query(spec)
        assert sql is not None
        assert "title" in sql
        assert "content" in sql
        assert "fake_col" not in sql

    def test_rejects_drop_in_where(self) -> None:
        """WHERE clause with DROP is rejected."""
        spec = DuckDBQuerySpec(
            table="raw_notes",
            columns=["title"],
            where="; DROP TABLE raw_notes",
        )
        assert build_safe_query(spec) is None

    def test_rejects_semicolon_in_where(self) -> None:
        """WHERE clause with semicolon is rejected."""
        spec = DuckDBQuerySpec(
            table="raw_notes",
            columns=["title"],
            where="1=1; DELETE FROM raw_notes",
        )
        assert build_safe_query(spec) is None

    def test_rejects_comment_injection(self) -> None:
        """WHERE clause with SQL comments is rejected."""
        spec = DuckDBQuerySpec(
            table="raw_notes",
            columns=["title"],
            where="title = 'x' -- rest ignored",
        )
        assert build_safe_query(spec) is None

    def test_rejects_union_injection(self) -> None:
        """WHERE clause with UNION is rejected."""
        spec = DuckDBQuerySpec(
            table="raw_notes",
            columns=["title"],
            where="1=1 UNION SELECT * FROM raw_contacts",
        )
        assert build_safe_query(spec) is None

    def test_valid_where_clause(self) -> None:
        """Safe WHERE clause is included in SQL."""
        spec = DuckDBQuerySpec(
            table="raw_notes",
            columns=["title", "content"],
            where="title LIKE '%meeting%'",
            limit=5,
        )
        sql = build_safe_query(spec)
        assert sql is not None
        assert "WHERE title LIKE '%meeting%'" in sql

    def test_dangerous_order_by_stripped(self) -> None:
        """Dangerous ORDER BY is skipped but query still runs."""
        spec = DuckDBQuerySpec(
            table="raw_notes",
            columns=["title"],
            order_by="; DROP TABLE raw_notes",
        )
        sql = build_safe_query(spec)
        assert sql is not None
        assert "ORDER BY" not in sql
        assert "DROP" not in sql

    def test_limit_capped_at_50(self) -> None:
        """Limit is capped at 50 even if spec asks for more."""
        spec = DuckDBQuerySpec(
            table="raw_notes",
            columns=["title"],
            limit=100,
        )
        sql = build_safe_query(spec)
        assert sql is not None
        assert "LIMIT 50" in sql

    def test_all_11_tables_accepted(self) -> None:
        """All 11 raw tables are accepted."""
        tables = [
            "raw_messages", "raw_calendar_events", "raw_notes",
            "raw_health_metrics", "raw_contacts", "raw_files",
            "raw_emails", "raw_reminders", "raw_workouts",
            "raw_listening_history", "raw_voice_memos",
        ]
        for table in tables:
            spec = DuckDBQuerySpec(
                table=table,
                columns=["id"],
            )
            sql = build_safe_query(spec)
            assert sql is not None, f"Table {table} was rejected"
            assert f"FROM {table}" in sql


# ------------------------------------------------------------------
# LLMRouter
# ------------------------------------------------------------------


def _agent_plan(
    *,
    duckdb_queries: list[dict] | None = None,
    chromadb_collections: list[str] | None = None,
    use_graph: bool = False,
    reasoning: str = "test",
):
    """Build a pydantic ``RetrievalPlan`` that ``QueryRouterAgent.plan``
    can return.

    The legacy LLMRouter tests previously asserted JSON-parsing
    behaviour against a mocked ``LLMProvider``. With the SBAgent
    swap-in, parsing + schema validation now happens inside pydantic-ai,
    so tests mock the agent's typed output instead.
    """
    from src.agents.core.output_types import (
        DuckDBQuerySpec as PydanticQuerySpec,
    )
    from src.agents.core.output_types import (
        RetrievalPlan as PydanticPlan,
    )

    queries = [
        PydanticQuerySpec(**q) for q in (duckdb_queries or [])
    ]
    return PydanticPlan(
        duckdb_queries=queries,
        chromadb_collections=chromadb_collections or [],
        use_graph=use_graph,
        reasoning=reasoning,
    )


@pytest.fixture()
def stub_query_router(monkeypatch):
    """Monkey-patch ``QueryRouterAgent.plan`` with a controllable stub.

    Tests set ``stub_query_router.return_value`` to a pydantic
    ``RetrievalPlan`` (via :func:`_agent_plan`) or
    ``stub_query_router.side_effect`` to an exception.
    """
    fake = MagicMock(return_value=None)

    def _bound(self, question):  # noqa: ARG001
        result = fake(question)
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(
        "src.agents.query_router.agent.QueryRouterAgent.plan", _bound,
    )
    return fake


class TestLLMRouter:
    def test_parses_valid_plan(self, stub_query_router) -> None:
        """A pydantic RetrievalPlan from the agent flows through unchanged."""
        stub_query_router.return_value = _agent_plan(
            duckdb_queries=[{
                "table": "raw_notes",
                "columns": ["title", "content"],
                "where": None,
                "order_by": "updated_at DESC",
                "limit": 10,
            }],
            chromadb_collections=["personal"],
            reasoning="User asks about notes",
        )
        router = LLMRouter()
        plan = router.plan("what are my notes?")

        assert isinstance(plan, RetrievalPlan)
        assert len(plan.duckdb_queries) == 1
        assert plan.duckdb_queries[0].table == "raw_notes"
        assert plan.chromadb_collections == ["personal"]
        assert plan.use_graph is False
        assert "notes" in plan.reasoning.lower()

    def test_returns_default_on_none(self, stub_query_router) -> None:
        """``QueryRouterAgent.plan`` returning None falls back to default."""
        stub_query_router.return_value = None
        router = LLMRouter()
        plan = router.plan("hello")

        assert isinstance(plan, RetrievalPlan)
        assert len(plan.duckdb_queries) == 0
        assert len(plan.chromadb_collections) == 5
        assert plan.use_graph is False
        assert "default" in plan.reasoning.lower()

    def test_returns_default_on_exception(
        self, stub_query_router,
    ) -> None:
        """Agent exception falls back to the default plan."""
        stub_query_router.side_effect = RuntimeError("agent down")
        router = LLMRouter()
        plan = router.plan("hello")

        assert isinstance(plan, RetrievalPlan)
        assert len(plan.duckdb_queries) == 0
        assert "default" in plan.reasoning.lower()

    def test_strips_invalid_tables(self, stub_query_router) -> None:
        """Unknown tables from the agent are stripped by the whitelist."""
        stub_query_router.return_value = _agent_plan(
            duckdb_queries=[
                {"table": "raw_notes", "columns": ["title"]},
                {"table": "raw_secrets", "columns": ["password"]},
            ],
            chromadb_collections=["personal"],
        )
        router = LLMRouter()
        plan = router.plan("test")

        assert len(plan.duckdb_queries) == 1
        assert plan.duckdb_queries[0].table == "raw_notes"

    def test_strips_invalid_collections(self, stub_query_router) -> None:
        """Unknown collections from the agent are stripped."""
        stub_query_router.return_value = _agent_plan(
            chromadb_collections=["personal", "fake_collection"],
        )
        router = LLMRouter()
        plan = router.plan("test")

        assert plan.chromadb_collections == ["personal"]

    def test_passes_reference_date(self, stub_query_router) -> None:
        """Reference date is prepended to the agent's input question."""
        stub_query_router.return_value = _agent_plan(
            chromadb_collections=["personal"],
        )
        router = LLMRouter()
        router.plan("test", reference_date=date(2025, 12, 25))

        question = stub_query_router.call_args.args[0]
        assert "2025-12-25" in question

    def test_dangerous_where_rejected(self, stub_query_router) -> None:
        """Dangerous WHERE clause from the agent is set to None."""
        stub_query_router.return_value = _agent_plan(
            duckdb_queries=[{
                "table": "raw_notes",
                "columns": ["title"],
                "where": "; DROP TABLE raw_notes",
            }],
        )
        router = LLMRouter()
        plan = router.plan("test")

        assert len(plan.duckdb_queries) == 1
        assert plan.duckdb_queries[0].where is None

    def test_limit_capped(self, stub_query_router) -> None:
        """Limit from the agent is capped at 50."""
        stub_query_router.return_value = _agent_plan(
            duckdb_queries=[{
                "table": "raw_notes",
                "columns": ["title"],
                "limit": 999,
            }],
        )
        router = LLMRouter()
        plan = router.plan("test")

        assert plan.duckdb_queries[0].limit == 50

    def test_empty_columns_gets_defaults(
        self, stub_query_router,
    ) -> None:
        """Empty columns list gets replaced with all columns."""
        stub_query_router.return_value = _agent_plan(
            duckdb_queries=[{
                "table": "raw_notes",
                "columns": [],
            }],
        )
        router = LLMRouter()
        plan = router.plan("test")

        assert len(plan.duckdb_queries) == 1
        # Should have all columns from the whitelist minus 'metadata'
        assert len(plan.duckdb_queries[0].columns) > 0

    def test_malformed_response_returns_default(
        self, stub_query_router,
    ) -> None:
        """Agent returning None (e.g. validation failed) → default plan."""
        stub_query_router.return_value = None
        router = LLMRouter()
        plan = router.plan("test")

        assert isinstance(plan, RetrievalPlan)
        # Empty queries list but valid plan
        assert len(plan.duckdb_queries) == 0

    def test_empty_collections_preserved(
        self, stub_query_router,
    ) -> None:
        """Empty chromadb_collections should be preserved, not replaced."""
        stub_query_router.return_value = _agent_plan(
            duckdb_queries=[{
                "table": "raw_calendar_events",
                "columns": ["title", "start_time"],
                "where": "start_time >= CURRENT_DATE",
                "order_by": "start_time ASC",
                "limit": 10,
            }],
            chromadb_collections=[],
            reasoning="Calendar query — structured only, no vector",
        )
        router = LLMRouter()
        plan = router.plan("what meetings do I have today?")

        assert plan.chromadb_collections == []
        assert len(plan.duckdb_queries) == 1


# ------------------------------------------------------------------
# Topic-boosted relevance
# ------------------------------------------------------------------


class TestTopicBoostRelevance:
    """Tests for _topic_boost_relevance helper."""

    def test_high_importance_boosts_relevance(self) -> None:
        """Contact with importance >= 7 gets +0.10."""
        tc = {
            "maria": {
                "name": "Maria",
                "importance": 9,
            },
        }
        row = {"sender_name": "Maria", "content": "test"}
        result = _topic_boost_relevance(0.70, row, tc)
        assert result == pytest.approx(0.80)

    def test_medium_importance_boosts_relevance(self) -> None:
        """Contact with importance 5-6 gets +0.05."""
        tc = {
            "samuel": {
                "name": "Samuel",
                "importance": 6,
            },
        }
        row = {"sender_name": "Samuel", "content": "test"}
        result = _topic_boost_relevance(0.70, row, tc)
        assert result == pytest.approx(0.75)

    def test_no_boost_for_unknown(self) -> None:
        """Unknown sender gets no boost."""
        tc = {
            "maria": {
                "name": "Maria",
                "importance": 9,
            },
        }
        row = {"sender_name": "Stranger", "content": "test"}
        result = _topic_boost_relevance(0.70, row, tc)
        assert result == pytest.approx(0.70)

    def test_capped_at_1(self) -> None:
        """Boosted relevance never exceeds 1.0."""
        tc = {
            "maria": {
                "name": "Maria",
                "importance": 9,
            },
        }
        row = {"sender_name": "Maria"}
        result = _topic_boost_relevance(0.95, row, tc)
        assert result == pytest.approx(1.0)

    def test_empty_topic_contacts(self) -> None:
        """No boost when topic_contacts is empty."""
        row = {"sender_name": "Anyone"}
        result = _topic_boost_relevance(0.70, row, {})
        assert result == pytest.approx(0.70)

    def test_matches_from_address(self) -> None:
        """Matches on from_address field too."""
        tc = {
            "boss@company.com": {
                "name": "boss@company.com",
                "importance": 8,
            },
        }
        row = {"from_address": "boss@company.com"}
        result = _topic_boost_relevance(0.65, row, tc)
        assert result == pytest.approx(0.75)

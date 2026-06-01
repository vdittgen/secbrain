"""Unit tests for the Kuzu graph engine, schema, and fixtures.

All tests use a temporary directory — never the real ~/.arandu/data/kuzu_db/
— so they are isolated and safe to run in any environment.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from src.core.kuzu.engine import GraphEngine
from src.core.kuzu.schema import (
    ALL_NODE_TABLES,
    ALL_REL_TABLES,
    create_schema,
)

from tests.fixtures.kuzu_fixtures import (
    EXPECTED_EDGE_COUNTS,
    EXPECTED_NODE_COUNTS,
    load_all_fixtures,
)

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def tmp_engine(tmp_path: Path) -> GraphEngine:
    """Fresh GraphEngine backed by a temp directory; closed after test."""
    engine = GraphEngine(db_path=tmp_path / "kuzu_test")
    yield engine
    engine.close()


@pytest.fixture()
def seeded_engine(tmp_path: Path) -> GraphEngine:
    """GraphEngine with schema and all fixtures already loaded."""
    engine = GraphEngine(db_path=tmp_path / "kuzu_seeded")
    create_schema(engine)
    load_all_fixtures(engine)
    yield engine
    engine.close()


# ---------------------------------------------------------------------------
# Engine initialisation
# ---------------------------------------------------------------------------


class TestGraphEngineInit:
    def test_creates_database_file(self, tmp_path: Path) -> None:
        """GraphEngine must create the Kuzu database file on disk."""
        db_path = tmp_path / "sub" / "kuzu_db"
        assert not db_path.exists()
        engine = GraphEngine(db_path=db_path)
        engine.close()
        assert db_path.exists(), "Kuzu database file was not created"

    def test_creates_nested_parent_directories(self, tmp_path: Path) -> None:
        """Parent directories that don't exist are created automatically."""
        db_path = tmp_path / "a" / "b" / "c" / "kuzu_db"
        engine = GraphEngine(db_path=db_path)
        engine.close()
        assert db_path.parent.is_dir()

    def test_context_manager_opens_and_closes(self, tmp_path: Path) -> None:
        """Using GraphEngine as a context manager must work without error."""
        db_path = tmp_path / "cm_kuzu"
        with GraphEngine(db_path=db_path) as engine:
            engine.execute(
                "CREATE NODE TABLE IF NOT EXISTS Tmp"
                " (id STRING, PRIMARY KEY(id))"
            )
            engine.execute("CREATE (:Tmp {id: 'x'})")
            rows = engine.query("MATCH (n:Tmp) RETURN n.id AS id")
            assert rows == [{"id": "x"}]


# ---------------------------------------------------------------------------
# Engine method tests
# ---------------------------------------------------------------------------


class TestGraphEngineMethods:
    def test_execute_ddl(self, tmp_engine: GraphEngine) -> None:
        """execute() should run DDL without raising."""
        tmp_engine.execute(
            "CREATE NODE TABLE IF NOT EXISTS N (id STRING, PRIMARY KEY(id))"
        )

    def test_query_returns_list_of_dicts(self, tmp_engine: GraphEngine) -> None:
        """query() must return a list of dicts with aliased column names."""
        tmp_engine.execute(
            "CREATE NODE TABLE IF NOT EXISTS N"
            " (id STRING, val INT64, PRIMARY KEY(id))"
        )
        tmp_engine.execute("CREATE (:N {id: 'a', val: 1})")
        tmp_engine.execute("CREATE (:N {id: 'b', val: 2})")

        rows = tmp_engine.query(
            "MATCH (n:N) RETURN n.id AS id, n.val AS val ORDER BY n.val"
        )

        assert isinstance(rows, list)
        assert len(rows) == 2
        assert isinstance(rows[0], dict)
        assert rows[0] == {"id": "a", "val": 1}
        assert rows[1] == {"id": "b", "val": 2}

    def test_query_empty_result(self, tmp_engine: GraphEngine) -> None:
        """query() with no matching nodes should return an empty list."""
        tmp_engine.execute(
            "CREATE NODE TABLE IF NOT EXISTS Empty"
            " (id STRING, PRIMARY KEY(id))"
        )
        result = tmp_engine.query("MATCH (n:Empty) RETURN n.id AS id")
        assert result == []

    def test_execute_with_parameters(self, tmp_engine: GraphEngine) -> None:
        """Parameterised execute() must bind values correctly."""
        tmp_engine.execute(
            "CREATE NODE TABLE IF NOT EXISTS P"
            " (id STRING, score DOUBLE, PRIMARY KEY(id))"
        )
        tmp_engine.execute(
            "CREATE (:P {id: $id, score: $score})",
            {"id": "p1", "score": 0.95},
        )
        rows = tmp_engine.query(
            "MATCH (n:P) RETURN n.id AS id, n.score AS score"
        )
        assert rows == [{"id": "p1", "score": 0.95}]

    def test_query_with_parameters(self, tmp_engine: GraphEngine) -> None:
        """Parameterised query() must filter correctly."""
        tmp_engine.execute(
            "CREATE NODE TABLE IF NOT EXISTS N"
            " (id STRING, tier INT64, PRIMARY KEY(id))"
        )
        tmp_engine.execute("CREATE (:N {id: 'a', tier: 1})")
        tmp_engine.execute("CREATE (:N {id: 'b', tier: 3})")

        rows = tmp_engine.query(
            "MATCH (n:N) WHERE n.tier = $tier RETURN n.id AS id",
            {"tier": 3},
        )
        assert rows == [{"id": "b"}]


# ---------------------------------------------------------------------------
# Schema tests
# ---------------------------------------------------------------------------


class TestSchema:
    def _table_names(self, engine: GraphEngine) -> set[str]:
        rows = engine.query("CALL show_tables() RETURN *")
        return {r["name"] for r in rows}

    def test_all_node_tables_created(self, tmp_engine: GraphEngine) -> None:
        """create_schema() must create every expected node table."""
        create_schema(tmp_engine)
        names = self._table_names(tmp_engine)
        for table in ALL_NODE_TABLES:
            assert table in names, f"Node table {table!r} was not created"

    def test_all_rel_tables_created(self, tmp_engine: GraphEngine) -> None:
        """create_schema() must create every expected relationship table."""
        create_schema(tmp_engine)
        names = self._table_names(tmp_engine)
        for table in ALL_REL_TABLES:
            assert table in names, f"Rel table {table!r} was not created"

    def test_schema_creation_is_idempotent(self, tmp_engine: GraphEngine) -> None:
        """Calling create_schema() twice must not raise."""
        create_schema(tmp_engine)
        create_schema(tmp_engine)

    def test_node_and_rel_table_count(self, tmp_engine: GraphEngine) -> None:
        """There should be exactly 6 node tables and 7 rel tables."""
        create_schema(tmp_engine)
        rows = tmp_engine.query("CALL show_tables() RETURN *")
        node_tables = [r for r in rows if r["type"] == "NODE"]
        rel_tables = [r for r in rows if r["type"] == "REL"]
        assert len(node_tables) == len(ALL_NODE_TABLES)
        assert len(rel_tables) == len(ALL_REL_TABLES)


# ---------------------------------------------------------------------------
# Fixture loading tests
# ---------------------------------------------------------------------------


class TestFixtures:
    def test_person_node_count(self, seeded_engine: GraphEngine) -> None:
        rows = seeded_engine.query(
            "MATCH (n:Person) RETURN count(n) AS cnt"
        )
        assert rows[0]["cnt"] == EXPECTED_NODE_COUNTS["Person"]

    def test_event_node_count(self, seeded_engine: GraphEngine) -> None:
        rows = seeded_engine.query(
            "MATCH (n:Event) RETURN count(n) AS cnt"
        )
        assert rows[0]["cnt"] == EXPECTED_NODE_COUNTS["Event"]

    def test_place_node_count(self, seeded_engine: GraphEngine) -> None:
        rows = seeded_engine.query(
            "MATCH (n:Place) RETURN count(n) AS cnt"
        )
        assert rows[0]["cnt"] == EXPECTED_NODE_COUNTS["Place"]

    def test_emotion_node_count(self, seeded_engine: GraphEngine) -> None:
        rows = seeded_engine.query(
            "MATCH (n:Emotion) RETURN count(n) AS cnt"
        )
        assert rows[0]["cnt"] == EXPECTED_NODE_COUNTS["Emotion"]

    def test_idea_node_count(self, seeded_engine: GraphEngine) -> None:
        rows = seeded_engine.query(
            "MATCH (n:Idea) RETURN count(n) AS cnt"
        )
        assert rows[0]["cnt"] == EXPECTED_NODE_COUNTS["Idea"]

    def test_topic_node_count(self, seeded_engine: GraphEngine) -> None:
        rows = seeded_engine.query(
            "MATCH (n:Topic) RETURN count(n) AS cnt"
        )
        assert rows[0]["cnt"] == EXPECTED_NODE_COUNTS["Topic"]

    def test_total_node_count_at_least_30(self, seeded_engine: GraphEngine) -> None:
        """Graph must have at least 30 nodes."""
        total = sum(EXPECTED_NODE_COUNTS.values())
        assert total >= 30, f"Total nodes {total} < 30"

    def test_total_edge_count_at_least_50(self, seeded_engine: GraphEngine) -> None:
        """Graph must have at least 50 edges."""
        total = sum(EXPECTED_EDGE_COUNTS.values())
        assert total >= 50, f"Total edges {total} < 50"

    def test_knows_edge_count(self, seeded_engine: GraphEngine) -> None:
        rows = seeded_engine.query(
            "MATCH ()-[r:KNOWS]->() RETURN count(r) AS cnt"
        )
        assert rows[0]["cnt"] == EXPECTED_EDGE_COUNTS["KNOWS"]

    def test_participated_in_edge_count(self, seeded_engine: GraphEngine) -> None:
        rows = seeded_engine.query(
            "MATCH ()-[r:PARTICIPATED_IN]->() RETURN count(r) AS cnt"
        )
        assert rows[0]["cnt"] == EXPECTED_EDGE_COUNTS["PARTICIPATED_IN"]

    def test_felt_edge_count(self, seeded_engine: GraphEngine) -> None:
        rows = seeded_engine.query(
            "MATCH ()-[r:FELT]->() RETURN count(r) AS cnt"
        )
        assert rows[0]["cnt"] == EXPECTED_EDGE_COUNTS["FELT"]

    def test_located_at_edge_count(self, seeded_engine: GraphEngine) -> None:
        rows = seeded_engine.query(
            "MATCH ()-[r:LOCATED_AT]->() RETURN count(r) AS cnt"
        )
        assert rows[0]["cnt"] == EXPECTED_EDGE_COUNTS["LOCATED_AT"]

    def test_tagged_with_edge_count(self, seeded_engine: GraphEngine) -> None:
        rows = seeded_engine.query(
            "MATCH ()-[r:TAGGED_WITH]->() RETURN count(r) AS cnt"
        )
        assert rows[0]["cnt"] == EXPECTED_EDGE_COUNTS["TAGGED_WITH"]


# ---------------------------------------------------------------------------
# Graph traversal tests
# ---------------------------------------------------------------------------


class TestGraphTraversal:
    def test_person_knows_persons(self, seeded_engine: GraphEngine) -> None:
        """'Me' should know at least 5 people."""
        rows = seeded_engine.query(
            "MATCH (me:Person {id: 'p-me'})-[:KNOWS]->(other:Person)"
            " RETURN other.name AS name"
        )
        assert len(rows) >= 5

    def test_person_participated_in_events(
        self, seeded_engine: GraphEngine
    ) -> None:
        """'Me' should have participated in at least 8 events."""
        rows = seeded_engine.query(
            "MATCH (me:Person {id: 'p-me'})-[:PARTICIPATED_IN]->(ev:Event)"
            " RETURN ev.title AS title"
        )
        assert len(rows) >= 8

    def test_event_located_at_place(self, seeded_engine: GraphEngine) -> None:
        """Q2 Planning Session should be located at a place."""
        rows = seeded_engine.query(
            "MATCH (ev:Event {id: 'ev-001'})-[:LOCATED_AT]->(pl:Place)"
            " RETURN pl.name AS place"
        )
        assert len(rows) == 1
        assert rows[0]["place"] == "Conference Room B"

    def test_two_hop_person_to_emotion_via_event(
        self, seeded_engine: GraphEngine
    ) -> None:
        """Should find emotions connected to 'Me' via Event traversal."""
        rows = seeded_engine.query(
            "MATCH (me:Person {id: 'p-me'})"
            "-[:PARTICIPATED_IN]->(ev:Event)"
            "-[:FELT]->(em:Emotion)"
            " RETURN DISTINCT em.name AS emotion"
        )
        assert len(rows) >= 1

    def test_idea_tagged_with_topic(self, seeded_engine: GraphEngine) -> None:
        """Arandu idea should be tagged with at least one topic."""
        rows = seeded_engine.query(
            "MATCH (i:Idea {id: 'id-001'})-[:TAGGED_WITH]->(t:Topic)"
            " RETURN t.name AS topic"
        )
        assert len(rows) >= 1

    def test_sensitivity_tier_filtering(
        self, seeded_engine: GraphEngine
    ) -> None:
        """Should be able to filter graph nodes by sensitivity_tier."""
        tier3 = seeded_engine.query(
            "MATCH (n:Emotion) WHERE n.sensitivity_tier = 3"
            " RETURN count(n) AS cnt"
        )
        tier1 = seeded_engine.query(
            "MATCH (n:Topic) WHERE n.sensitivity_tier = 1"
            " RETURN count(n) AS cnt"
        )
        assert tier3[0]["cnt"] > 0
        assert tier1[0]["cnt"] > 0

    def test_query_returns_dict_with_correct_types(
        self, seeded_engine: GraphEngine
    ) -> None:
        """Row dicts must contain Python-native types (str, int, float)."""
        rows = seeded_engine.query(
            "MATCH (p:Person {id: 'p-me'})"
            " RETURN p.id AS id, p.name AS name,"
            " p.sensitivity_tier AS tier"
        )
        assert len(rows) == 1
        row = rows[0]
        assert isinstance(row["id"], str)
        assert isinstance(row["name"], str)
        assert isinstance(row["tier"], int)

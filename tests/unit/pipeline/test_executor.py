"""Tests for the pipeline executor and auditor.

All tests use temporary SQLite databases.

sensitivity_tier: N/A
"""

from __future__ import annotations

from pathlib import Path

import pytest
from src.core.sqlite.engine import DatabaseEngine
from src.pipeline.auditor import (
    audit_accepted_values,
    audit_model,
    audit_not_null,
    audit_pipeline,
    audit_unique,
)
from src.pipeline.executor import (
    execute_model,
    execute_pipeline,
    execute_sql_model,
)
from src.pipeline.manifest import AuditSpec, ModelSpec

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def tmp_db(tmp_path: Path) -> DatabaseEngine:
    """Fresh SQLite engine for testing."""
    db_path = tmp_path / "test_pipeline.sqlite3"
    engine = DatabaseEngine(db_path=db_path)
    yield engine
    engine.close()


@pytest.fixture()
def seeded_db(tmp_db: DatabaseEngine) -> DatabaseEngine:
    """DB with a raw_messages table containing test data."""
    tmp_db.execute("""
        CREATE TABLE raw_messages (
            id TEXT PRIMARY KEY,
            source TEXT NOT NULL,
            sender TEXT NOT NULL,
            recipient TEXT NOT NULL,
            content TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            metadata TEXT,
            sensitivity_tier INTEGER NOT NULL DEFAULT 2,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)
    tmp_db.execute(
        "INSERT INTO raw_messages "
        "(id, source, sender, recipient, content, timestamp) VALUES "
        "('m1', 'test', 'alice', 'bob', 'hello', '2025-01-01T10:00:00Z')"
    )
    tmp_db.execute(
        "INSERT INTO raw_messages "
        "(id, source, sender, recipient, content, timestamp) VALUES "
        "('m2', 'test', 'bob', 'alice', 'hi there', '2025-01-01T10:05:00Z')"
    )
    return tmp_db


# ---------------------------------------------------------------------------
# SQL model execution tests
# ---------------------------------------------------------------------------


class TestExecuteSqlModel:
    def test_basic_sql_model(
        self, seeded_db: DatabaseEngine, tmp_path: Path,
    ) -> None:
        """Execute a simple SQL model that selects from raw_messages."""
        sql_dir = tmp_path / "sql"
        sql_dir.mkdir()
        sql_file = sql_dir / "stg_test.sql"
        sql_file.write_text(
            "SELECT id, source, sender, content, "
            "LENGTH(content) AS msg_length, sensitivity_tier "
            "FROM raw_messages",
        )

        model = ModelSpec(
            name="stg_test",
            layer="staging",
            sql_file=str(sql_file),
            depends_on=["raw_messages"],
        )

        # Patch PROJECT_ROOT for test
        import src.pipeline.executor as executor_mod

        original_root = executor_mod.PROJECT_ROOT
        executor_mod.PROJECT_ROOT = Path("/")
        try:
            count = execute_sql_model(seeded_db, model)
        finally:
            executor_mod.PROJECT_ROOT = original_root

        assert count == 2

        rows = seeded_db.query("SELECT * FROM stg_test ORDER BY id")
        assert len(rows) == 2
        assert rows[0]["msg_length"] == 5  # len("hello")

    def test_full_refresh_drops_old(
        self, seeded_db: DatabaseEngine, tmp_path: Path,
    ) -> None:
        """Running the model twice should replace, not append."""
        sql_file = tmp_path / "model.sql"
        sql_file.write_text("SELECT id FROM raw_messages")

        model = ModelSpec(
            name="test_refresh",
            layer="staging",
            sql_file=str(sql_file),
        )

        import src.pipeline.executor as executor_mod

        original_root = executor_mod.PROJECT_ROOT
        executor_mod.PROJECT_ROOT = Path("/")
        try:
            execute_sql_model(seeded_db, model)
            count = execute_sql_model(seeded_db, model)
        finally:
            executor_mod.PROJECT_ROOT = original_root

        assert count == 2  # Not 4

    def test_no_sql_file_raises(self, seeded_db: DatabaseEngine) -> None:
        model = ModelSpec(name="bad", layer="staging", sql_file=None)
        with pytest.raises(ValueError, match="no sql_file"):
            execute_sql_model(seeded_db, model)


# ---------------------------------------------------------------------------
# execute_model dispatch tests
# ---------------------------------------------------------------------------


class TestExecuteModel:
    def test_dispatches_sql(
        self, seeded_db: DatabaseEngine, tmp_path: Path,
    ) -> None:
        sql_file = tmp_path / "test.sql"
        sql_file.write_text("SELECT id, source FROM raw_messages")

        model = ModelSpec(
            name="dispatch_test",
            layer="staging",
            sql_file=str(sql_file),
        )

        import src.pipeline.executor as executor_mod

        original_root = executor_mod.PROJECT_ROOT
        executor_mod.PROJECT_ROOT = Path("/")
        try:
            count = execute_model(seeded_db, model)
        finally:
            executor_mod.PROJECT_ROOT = original_root

        assert count == 2


# ---------------------------------------------------------------------------
# execute_pipeline tests
# ---------------------------------------------------------------------------


class TestExecutePipeline:
    def test_pipeline_runs_in_order(
        self, seeded_db: DatabaseEngine, tmp_path: Path,
    ) -> None:
        """Pipeline executes models in provided order."""
        sql1 = tmp_path / "stg.sql"
        sql1.write_text("SELECT id, source FROM raw_messages")

        sql2 = tmp_path / "mart.sql"
        sql2.write_text("SELECT id, source FROM stg_pipeline")

        models = [
            ModelSpec(
                name="stg_pipeline",
                layer="staging",
                sql_file=str(sql1),
                depends_on=["raw_messages"],
            ),
            ModelSpec(
                name="mart_pipeline",
                layer="mart",
                sql_file=str(sql2),
                depends_on=["stg_pipeline"],
            ),
        ]

        import src.pipeline.executor as executor_mod

        original_root = executor_mod.PROJECT_ROOT
        executor_mod.PROJECT_ROOT = Path("/")
        try:
            counts = execute_pipeline(seeded_db, models)
        finally:
            executor_mod.PROJECT_ROOT = original_root

        assert counts["stg_pipeline"] == 2
        assert counts["mart_pipeline"] == 2

    def test_pipeline_cancel(
        self, seeded_db: DatabaseEngine, tmp_path: Path,
    ) -> None:
        """Pipeline stops when cancel_check returns True."""
        sql1 = tmp_path / "a.sql"
        sql1.write_text("SELECT 1 AS n")
        sql2 = tmp_path / "b.sql"
        sql2.write_text("SELECT 2 AS n")

        models = [
            ModelSpec(name="a", layer="staging", sql_file=str(sql1)),
            ModelSpec(name="b", layer="staging", sql_file=str(sql2)),
        ]

        call_count = 0

        def cancel_after_first() -> bool:
            nonlocal call_count
            call_count += 1
            return call_count > 1

        import src.pipeline.executor as executor_mod

        original_root = executor_mod.PROJECT_ROOT
        executor_mod.PROJECT_ROOT = Path("/")
        try:
            counts = execute_pipeline(
                seeded_db, models, cancel_check=cancel_after_first,
            )
        finally:
            executor_mod.PROJECT_ROOT = original_root

        assert "a" in counts
        assert "b" not in counts

    def test_pipeline_progress_callbacks(
        self, seeded_db: DatabaseEngine, tmp_path: Path,
    ) -> None:
        """Progress callback is called for start and complete events."""
        sql = tmp_path / "test.sql"
        sql.write_text("SELECT 1 AS n")

        models = [
            ModelSpec(name="test", layer="staging", sql_file=str(sql)),
        ]

        events: list[dict] = []

        import src.pipeline.executor as executor_mod

        original_root = executor_mod.PROJECT_ROOT
        executor_mod.PROJECT_ROOT = Path("/")
        try:
            execute_pipeline(
                seeded_db, models, on_progress=events.append,
            )
        finally:
            executor_mod.PROJECT_ROOT = original_root

        types = [e["type"] for e in events]
        assert "model_start" in types
        assert "model_complete" in types

    def test_pipeline_handles_model_error(
        self, seeded_db: DatabaseEngine, tmp_path: Path,
    ) -> None:
        """Errors in one model produce -1, don't stop the pipeline."""
        bad_sql = tmp_path / "bad.sql"
        bad_sql.write_text("SELECT * FROM nonexistent_table")

        good_sql = tmp_path / "good.sql"
        good_sql.write_text("SELECT 1 AS n")

        models = [
            ModelSpec(name="bad", layer="staging", sql_file=str(bad_sql)),
            ModelSpec(name="good", layer="staging", sql_file=str(good_sql)),
        ]

        import src.pipeline.executor as executor_mod

        original_root = executor_mod.PROJECT_ROOT
        executor_mod.PROJECT_ROOT = Path("/")
        try:
            counts = execute_pipeline(seeded_db, models)
        finally:
            executor_mod.PROJECT_ROOT = original_root

        assert counts["bad"] == -1
        assert counts["good"] == 1


# ---------------------------------------------------------------------------
# Auditor tests
# ---------------------------------------------------------------------------


class TestAuditNotNull:
    def test_passes_when_no_nulls(self, tmp_db: DatabaseEngine) -> None:
        tmp_db.execute("CREATE TABLE t (id TEXT NOT NULL, name TEXT NOT NULL)")
        tmp_db.execute("INSERT INTO t VALUES ('1', 'alice')")
        assert audit_not_null(tmp_db, "t", ["id", "name"]) == []

    def test_fails_on_null(self, tmp_db: DatabaseEngine) -> None:
        tmp_db.execute("CREATE TABLE t (id TEXT, name TEXT)")
        tmp_db.execute("INSERT INTO t VALUES ('1', NULL)")
        failures = audit_not_null(tmp_db, "t", ["name"])
        assert len(failures) == 1
        assert "NULL" in failures[0]


class TestAuditUnique:
    def test_passes_when_unique(self, tmp_db: DatabaseEngine) -> None:
        tmp_db.execute("CREATE TABLE t (id TEXT)")
        tmp_db.execute("INSERT INTO t VALUES ('a')")
        tmp_db.execute("INSERT INTO t VALUES ('b')")
        assert audit_unique(tmp_db, "t", ["id"]) == []

    def test_fails_on_duplicate(self, tmp_db: DatabaseEngine) -> None:
        tmp_db.execute("CREATE TABLE t (id TEXT)")
        tmp_db.execute("INSERT INTO t VALUES ('a')")
        tmp_db.execute("INSERT INTO t VALUES ('a')")
        failures = audit_unique(tmp_db, "t", ["id"])
        assert len(failures) == 1
        assert "duplicate" in failures[0]


class TestAuditAcceptedValues:
    def test_passes_when_valid(self, tmp_db: DatabaseEngine) -> None:
        tmp_db.execute("CREATE TABLE t (tier INTEGER)")
        tmp_db.execute("INSERT INTO t VALUES (1)")
        tmp_db.execute("INSERT INTO t VALUES (2)")
        assert audit_accepted_values(
            tmp_db, "t", {"tier": [1, 2, 3]},
        ) == []

    def test_fails_on_invalid(self, tmp_db: DatabaseEngine) -> None:
        tmp_db.execute("CREATE TABLE t (tier INTEGER)")
        tmp_db.execute("INSERT INTO t VALUES (1)")
        tmp_db.execute("INSERT INTO t VALUES (99)")
        failures = audit_accepted_values(
            tmp_db, "t", {"tier": [1, 2, 3]},
        )
        assert len(failures) == 1
        assert "99" in str(failures[0])


class TestAuditModel:
    def test_passes_with_valid_data(self, tmp_db: DatabaseEngine) -> None:
        tmp_db.execute(
            "CREATE TABLE test_model "
            "(id TEXT PRIMARY KEY, tier INTEGER NOT NULL)",
        )
        tmp_db.execute("INSERT INTO test_model VALUES ('a', 1)")
        tmp_db.execute("INSERT INTO test_model VALUES ('b', 2)")

        model = ModelSpec(
            name="test_model",
            layer="staging",
            audits=AuditSpec(
                not_null=["id", "tier"],
                unique=["id"],
                accepted_values={"tier": [1, 2, 3]},
            ),
        )

        result = audit_model(tmp_db, model)
        assert result.passed
        assert result.failures == []

    def test_fails_on_missing_table(self, tmp_db: DatabaseEngine) -> None:
        model = ModelSpec(
            name="nonexistent",
            layer="staging",
            audits=AuditSpec(not_null=["id"]),
        )
        result = audit_model(tmp_db, model)
        assert not result.passed
        assert "does not exist" in result.failures[0]


class TestAuditPipeline:
    def test_audits_multiple_models(self, tmp_db: DatabaseEngine) -> None:
        tmp_db.execute("CREATE TABLE a (id TEXT NOT NULL)")
        tmp_db.execute("INSERT INTO a VALUES ('1')")
        tmp_db.execute("CREATE TABLE b (id TEXT NOT NULL)")
        tmp_db.execute("INSERT INTO b VALUES ('2')")

        models = [
            ModelSpec(
                name="a", layer="staging",
                audits=AuditSpec(not_null=["id"]),
            ),
            ModelSpec(
                name="b", layer="staging",
                audits=AuditSpec(not_null=["id"]),
            ),
        ]

        results = audit_pipeline(tmp_db, models)
        assert len(results) == 2
        assert all(r.passed for r in results)

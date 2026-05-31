"""Unit tests for the SQLite engine, schemas, and sample-data fixtures.

All tests use a temporary in-memory or temp-file database — never the real
~/.secbrain/data/secbrain.sqlite3 — so they are safe to run in any environment.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from unittest.mock import patch

import pytest
from src.core.sqlite.engine import DatabaseEngine
from src.core.sqlite.schemas import ALL_TABLE_NAMES, create_all_tables

from tests.fixtures.sample_data import (
    CALENDAR_EVENTS,
    CONTACTS,
    HEALTH_METRICS,
    MESSAGES,
    NOTES,
    load_all_fixtures,
)

# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def tmp_db(tmp_path: Path) -> DatabaseEngine:
    """Open a fresh DatabaseEngine backed by a temp file; close after test."""
    db_path = tmp_path / "test_secbrain.duckdb"
    engine = DatabaseEngine(db_path=db_path)
    yield engine
    engine.close()


@pytest.fixture()
def seeded_db(tmp_db: DatabaseEngine) -> DatabaseEngine:
    """DatabaseEngine with all schemas and fixtures already loaded."""
    create_all_tables(tmp_db)
    load_all_fixtures(tmp_db)
    return tmp_db


# ---------------------------------------------------------------------------
# Engine initialisation tests
# ---------------------------------------------------------------------------


class TestDatabaseEngineInit:
    def test_creates_database_file(self, tmp_path: Path) -> None:
        """DatabaseEngine must create the .duckdb file on disk."""
        db_path = tmp_path / "subdir" / "secbrain.duckdb"
        assert not db_path.exists()

        engine = DatabaseEngine(db_path=db_path)
        engine.close()

        assert db_path.exists(), "DuckDB file was not created"

    def test_creates_parent_directories(self, tmp_path: Path) -> None:
        """Parent directories that don't exist should be created automatically."""
        db_path = tmp_path / "a" / "b" / "c" / "secbrain.duckdb"
        engine = DatabaseEngine(db_path=db_path)
        engine.close()

        assert db_path.parent.is_dir()

    def test_context_manager_closes_connection(self, tmp_path: Path) -> None:
        """Using the engine as a context manager must close on exit."""
        db_path = tmp_path / "cm_test.duckdb"
        with DatabaseEngine(db_path=db_path) as engine:
            # Must be usable inside the block
            result = engine.query("SELECT 42 AS answer")
            assert result[0]["answer"] == 42
        # After exit, re-opening should work (no file lock held)
        with DatabaseEngine(db_path=db_path) as engine2:
            result2 = engine2.query("SELECT 99 AS answer")
            assert result2[0]["answer"] == 99


# ---------------------------------------------------------------------------
# Engine method tests
# ---------------------------------------------------------------------------


class TestDatabaseEngineMethods:
    def test_execute_ddl(self, tmp_db: DatabaseEngine) -> None:
        """execute() should run DDL without raising."""
        tmp_db.execute("CREATE TABLE t (x INTEGER)")
        tmp_db.execute("INSERT INTO t VALUES (1)")

    def test_query_returns_list_of_dicts(self, tmp_db: DatabaseEngine) -> None:
        """query() must return a list of dicts with correct column names."""
        tmp_db.execute("CREATE TABLE nums (n INTEGER, label VARCHAR)")
        tmp_db.execute("INSERT INTO nums VALUES (1, 'one'), (2, 'two')")

        rows = tmp_db.query("SELECT n, label FROM nums ORDER BY n")

        assert isinstance(rows, list)
        assert len(rows) == 2
        assert isinstance(rows[0], dict)
        assert rows[0] == {"n": 1, "label": "one"}
        assert rows[1] == {"n": 2, "label": "two"}

    def test_query_empty_result(self, tmp_db: DatabaseEngine) -> None:
        """query() with no matching rows should return an empty list."""
        tmp_db.execute("CREATE TABLE empty_t (x INTEGER)")
        result = tmp_db.query("SELECT * FROM empty_t")
        assert result == []

    def test_execute_with_parameters(self, tmp_db: DatabaseEngine) -> None:
        """Parameterised execute() must bind values correctly."""
        tmp_db.execute("CREATE TABLE params_t (id INTEGER, val VARCHAR)")
        tmp_db.execute("INSERT INTO params_t VALUES (?, ?)", [42, "hello"])
        rows = tmp_db.query("SELECT id, val FROM params_t")
        assert rows == [{"id": 42, "val": "hello"}]

    def test_query_with_parameters(self, tmp_db: DatabaseEngine) -> None:
        """Parameterised query() must filter correctly."""
        tmp_db.execute("CREATE TABLE filter_t (n INTEGER)")
        tmp_db.execute("INSERT INTO filter_t VALUES (1), (2), (3)")
        rows = tmp_db.query("SELECT n FROM filter_t WHERE n > ?", [1])
        assert [r["n"] for r in rows] == [2, 3]


# ---------------------------------------------------------------------------
# Schema tests
# ---------------------------------------------------------------------------


class TestSchemas:
    def test_all_tables_created(self, tmp_db: DatabaseEngine) -> None:
        """create_all_tables() must create every expected table."""
        create_all_tables(tmp_db)

        existing = {
            row["name"]
            for row in tmp_db.query(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        for table in ALL_TABLE_NAMES:
            assert table in existing, f"Table {table!r} was not created"

    def test_idempotent_schema_creation(self, tmp_db: DatabaseEngine) -> None:
        """Calling create_all_tables() twice must not raise."""
        create_all_tables(tmp_db)
        create_all_tables(tmp_db)  # should not raise

    def test_raw_messages_has_sensitivity_tier_column(
        self, tmp_db: DatabaseEngine,
    ) -> None:
        """raw_messages must have a sensitivity_tier column with default 2."""
        create_all_tables(tmp_db)
        tmp_db.execute(
            "INSERT INTO raw_messages"
            " (id, source, sender, recipient, content, timestamp)"
            " VALUES ('x', 's', 'a', 'b', 'hi', '2025-01-01T00:00:00Z')"
        )
        rows = tmp_db.query(
            "SELECT sensitivity_tier FROM raw_messages WHERE id = 'x'"
        )
        assert rows[0]["sensitivity_tier"] == 2

    def test_raw_health_metrics_default_tier_3(
        self, tmp_db: DatabaseEngine,
    ) -> None:
        """raw_health_metrics default sensitivity_tier must be 3."""
        create_all_tables(tmp_db)
        tmp_db.execute(
            "INSERT INTO raw_health_metrics"
            " (id, metric_type, value, unit, recorded_at, source)"
            " VALUES ('h1', 'heart_rate', 70.0, 'bpm',"
            " '2025-01-01T07:00:00Z', 'test')"
        )
        rows = tmp_db.query(
            "SELECT sensitivity_tier FROM raw_health_metrics WHERE id = 'h1'"
        )
        assert rows[0]["sensitivity_tier"] == 3

    def test_raw_notes_default_tier_1(self, tmp_db: DatabaseEngine) -> None:
        """raw_notes default sensitivity_tier must be 1."""
        create_all_tables(tmp_db)
        tmp_db.execute(
            "INSERT INTO raw_notes (id, title, content, source)"
            " VALUES ('n1', 'Test', 'body', 'obsidian')"
        )
        rows = tmp_db.query("SELECT sensitivity_tier FROM raw_notes WHERE id = 'n1'")
        assert rows[0]["sensitivity_tier"] == 1


# ---------------------------------------------------------------------------
# Fixture loading tests
# ---------------------------------------------------------------------------


class TestFixtures:
    def test_messages_row_count(self, seeded_db: DatabaseEngine) -> None:
        rows = seeded_db.query("SELECT COUNT(*) AS cnt FROM raw_messages")
        assert rows[0]["cnt"] == len(MESSAGES), f"Expected {len(MESSAGES)} messages"

    def test_calendar_events_row_count(self, seeded_db: DatabaseEngine) -> None:
        rows = seeded_db.query("SELECT COUNT(*) AS cnt FROM raw_calendar_events")
        assert rows[0]["cnt"] == len(CALENDAR_EVENTS)

    def test_notes_row_count(self, seeded_db: DatabaseEngine) -> None:
        rows = seeded_db.query("SELECT COUNT(*) AS cnt FROM raw_notes")
        assert rows[0]["cnt"] == len(NOTES)

    def test_health_metrics_row_count(self, seeded_db: DatabaseEngine) -> None:
        rows = seeded_db.query("SELECT COUNT(*) AS cnt FROM raw_health_metrics")
        assert rows[0]["cnt"] == len(HEALTH_METRICS)

    def test_contacts_row_count(self, seeded_db: DatabaseEngine) -> None:
        rows = seeded_db.query("SELECT COUNT(*) AS cnt FROM raw_contacts")
        assert rows[0]["cnt"] == len(CONTACTS)

    def test_sensitivity_tiers_mixed_in_messages(
        self, seeded_db: DatabaseEngine,
    ) -> None:
        """Messages should contain rows across multiple sensitivity tiers."""
        rows = seeded_db.query(
            "SELECT DISTINCT sensitivity_tier FROM raw_messages"
            " ORDER BY sensitivity_tier"
        )
        tiers = {r["sensitivity_tier"] for r in rows}
        assert len(tiers) >= 2, "Expected mixed sensitivity tiers in raw_messages"
        assert 1 in tiers
        assert 3 in tiers

    def test_all_health_metrics_tier_3(self, seeded_db: DatabaseEngine) -> None:
        """All health metric fixtures must be sensitivity tier 3."""
        rows = seeded_db.query(
            "SELECT DISTINCT sensitivity_tier FROM raw_health_metrics"
        )
        tiers = {r["sensitivity_tier"] for r in rows}
        assert tiers == {3}, f"Expected only tier 3 for health metrics, got {tiers}"

    def test_fixture_load_is_idempotent(self, seeded_db: DatabaseEngine) -> None:
        """Calling load_all_fixtures twice must not duplicate rows."""
        load_all_fixtures(seeded_db)
        rows = seeded_db.query("SELECT COUNT(*) AS cnt FROM raw_messages")
        assert rows[0]["cnt"] == len(MESSAGES)

    def test_query_returns_dict_types(self, seeded_db: DatabaseEngine) -> None:
        """Rows from query() must be proper dicts with expected key types."""
        rows = seeded_db.query("SELECT * FROM raw_contacts LIMIT 1")
        assert len(rows) == 1
        row = rows[0]
        assert isinstance(row, dict)
        assert isinstance(row["id"], str)
        assert isinstance(row["name"], str)
        assert isinstance(row["sensitivity_tier"], int)


# ---------------------------------------------------------------------------
# Write-lock retry tests
# ---------------------------------------------------------------------------


class TestWALModeAndBusyTimeout:
    """Tests for SQLite WAL mode and busy_timeout configuration."""

    def test_wal_mode_is_enabled(self, tmp_path: Path) -> None:
        """SQLite connection must use WAL journal mode."""
        db_path = tmp_path / "wal_test.db"
        engine = DatabaseEngine(db_path=db_path)
        rows = engine.query("PRAGMA journal_mode")
        engine.close()
        assert rows[0]["journal_mode"] == "wal"

    def test_busy_timeout_is_set(self, tmp_path: Path) -> None:
        """SQLite connection must have busy_timeout configured."""
        db_path = tmp_path / "timeout_test.db"
        engine = DatabaseEngine(db_path=db_path)
        rows = engine.query("PRAGMA busy_timeout")
        engine.close()
        assert rows[0]["timeout"] == 30000

    def test_connect_error_propagates_immediately(
        self, tmp_path: Path,
    ) -> None:
        """OperationalError propagates immediately (no retry loop)."""
        db_path = tmp_path / "err_test.db"
        err = sqlite3.OperationalError("unable to open database file")

        with patch("src.core.sqlite.engine.sqlite3.connect") as mock_connect, \
             pytest.raises(sqlite3.OperationalError, match="unable to open"):
            mock_connect.side_effect = err
            DatabaseEngine(db_path=db_path)

        assert mock_connect.call_count == 1  # no retry

    def test_read_only_flag_accepted(
        self, tmp_path: Path,
    ) -> None:
        """read_only=True is accepted for API compat and connects normally."""
        db_path = tmp_path / "ro_test.db"
        engine = DatabaseEngine(db_path=db_path, read_only=True)
        rows = engine.query("SELECT 1 AS ok")
        engine.close()
        assert rows[0]["ok"] == 1

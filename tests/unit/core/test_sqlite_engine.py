"""Unit tests for the SQLite engine, schemas, cache, and migrations.

All tests use temporary file databases — never the real
~/.secbrain/data/secbrain.sqlite3 — so they are safe to run in any environment.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest
from src.core.sqlite.engine import DatabaseEngine, QueryCache
from src.core.sqlite.migrations import (
    MIGRATION_SCHEMAS,
    ensure_table,
    get_existing_tables,
    run_column_additions,
    run_migrations,
)
from src.core.sqlite.schemas import ALL_TABLE_NAMES, create_all_tables

# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def tmp_db(tmp_path: Path) -> DatabaseEngine:
    """Open a fresh DatabaseEngine backed by a temp file; close after test."""
    db_path = tmp_path / "test_secbrain.sqlite3"
    engine = DatabaseEngine(db_path=db_path)
    yield engine
    engine.close()


@pytest.fixture()
def seeded_db(tmp_db: DatabaseEngine) -> DatabaseEngine:
    """DatabaseEngine with all base schemas already created."""
    create_all_tables(tmp_db)
    return tmp_db


# ---------------------------------------------------------------------------
# Engine initialisation tests
# ---------------------------------------------------------------------------


class TestDatabaseEngineInit:
    def test_creates_database_file(self, tmp_path: Path) -> None:
        """DatabaseEngine must create the .sqlite3 file on disk."""
        db_path = tmp_path / "subdir" / "secbrain.sqlite3"
        assert not db_path.exists()

        engine = DatabaseEngine(db_path=db_path)
        engine.close()

        assert db_path.exists(), "SQLite file was not created"

    def test_creates_parent_directories(self, tmp_path: Path) -> None:
        """Parent directories that don't exist should be created automatically."""
        db_path = tmp_path / "a" / "b" / "c" / "secbrain.sqlite3"
        engine = DatabaseEngine(db_path=db_path)
        engine.close()

        assert db_path.parent.is_dir()

    def test_context_manager_closes_connection(self, tmp_path: Path) -> None:
        """Using the engine as a context manager must close on exit."""
        db_path = tmp_path / "cm_test.sqlite3"
        with DatabaseEngine(db_path=db_path) as engine:
            result = engine.query("SELECT 42 AS answer")
            assert result[0]["answer"] == 42
        # After exit, re-opening should work (no file lock held)
        with DatabaseEngine(db_path=db_path) as engine2:
            result2 = engine2.query("SELECT 99 AS answer")
            assert result2[0]["answer"] == 99

    def test_wal_mode_enabled(self, tmp_path: Path) -> None:
        """SQLite engine must use WAL journal mode."""
        db_path = tmp_path / "wal_test.sqlite3"
        with DatabaseEngine(db_path=db_path) as engine:
            rows = engine.query("PRAGMA journal_mode")
            assert rows[0]["journal_mode"] == "wal"

    def test_foreign_keys_enabled(self, tmp_path: Path) -> None:
        """Foreign key enforcement should be ON."""
        db_path = tmp_path / "fk_test.sqlite3"
        with DatabaseEngine(db_path=db_path) as engine:
            rows = engine.query("PRAGMA foreign_keys")
            assert rows[0]["foreign_keys"] == 1

    def test_read_only_param_accepted(self, tmp_path: Path) -> None:
        """read_only parameter should be accepted for API compat."""
        db_path = tmp_path / "ro_test.sqlite3"
        engine = DatabaseEngine(db_path=db_path, read_only=True)
        result = engine.query("SELECT 1 AS n")
        assert result[0]["n"] == 1
        engine.close()


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
        tmp_db.execute("CREATE TABLE nums (n INTEGER, label TEXT)")
        tmp_db.execute("INSERT INTO nums VALUES (1, 'one')")
        tmp_db.execute("INSERT INTO nums VALUES (2, 'two')")

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
        tmp_db.execute("CREATE TABLE params_t (id INTEGER, val TEXT)")
        tmp_db.execute("INSERT INTO params_t VALUES (?, ?)", [42, "hello"])
        rows = tmp_db.query("SELECT id, val FROM params_t")
        assert rows == [{"id": 42, "val": "hello"}]

    def test_query_with_parameters(self, tmp_db: DatabaseEngine) -> None:
        """Parameterised query() must filter correctly."""
        tmp_db.execute("CREATE TABLE filter_t (n INTEGER)")
        tmp_db.execute("INSERT INTO filter_t VALUES (1)")
        tmp_db.execute("INSERT INTO filter_t VALUES (2)")
        tmp_db.execute("INSERT INTO filter_t VALUES (3)")
        rows = tmp_db.query("SELECT n FROM filter_t WHERE n > ?", [1])
        values = sorted(r["n"] for r in rows)
        assert values == [2, 3]

    def test_query_no_description_returns_empty(
        self, tmp_db: DatabaseEngine,
    ) -> None:
        """DDL-like statements via query() should return empty list."""
        tmp_db.execute("CREATE TABLE t (x INTEGER)")
        # SQLite doesn't return description for DDL via query path,
        # but the engine handles cursor.description == None
        result = tmp_db.query("SELECT * FROM t")
        assert result == []

    def test_concurrent_read_write(self, tmp_path: Path) -> None:
        """WAL mode allows a reader and writer on the same file."""
        db_path = tmp_path / "concurrent.sqlite3"
        writer = DatabaseEngine(db_path=db_path)
        reader = DatabaseEngine(db_path=db_path)

        writer.execute("CREATE TABLE t (n INTEGER)")
        writer.execute("INSERT INTO t VALUES (1)")

        # Reader should see committed data
        rows = reader.query("SELECT n FROM t")
        assert rows == [{"n": 1}]

        writer.close()
        reader.close()


# ---------------------------------------------------------------------------
# Schema tests
# ---------------------------------------------------------------------------


class TestSchemas:
    def test_all_tables_created(self, tmp_db: DatabaseEngine) -> None:
        """create_all_tables() must create every expected table."""
        create_all_tables(tmp_db)

        existing = get_existing_tables(tmp_db)
        for table in ALL_TABLE_NAMES:
            assert table in existing, f"Table {table!r} was not created"

    def test_idempotent_schema_creation(self, tmp_db: DatabaseEngine) -> None:
        """Calling create_all_tables() twice must not raise."""
        create_all_tables(tmp_db)
        create_all_tables(tmp_db)  # should not raise

    def test_raw_messages_has_sensitivity_tier(
        self, seeded_db: DatabaseEngine,
    ) -> None:
        """raw_messages must have a sensitivity_tier column with default 2."""
        seeded_db.execute(
            "INSERT INTO raw_messages "
            "(id, source, sender, recipient, content, timestamp) "
            "VALUES ('x', 's', 'a', 'b', 'hi', '2025-01-01T00:00:00Z')"
        )
        rows = seeded_db.query(
            "SELECT sensitivity_tier FROM raw_messages WHERE id = 'x'"
        )
        assert rows[0]["sensitivity_tier"] == 2

    def test_raw_health_metrics_default_tier_3(
        self, seeded_db: DatabaseEngine,
    ) -> None:
        """raw_health_metrics default sensitivity_tier must be 3."""
        seeded_db.execute(
            "INSERT INTO raw_health_metrics "
            "(id, metric_type, value, unit, recorded_at, source) "
            "VALUES ('h1', 'heart_rate', 70.0, 'bpm', "
            "'2025-01-01T07:00:00Z', 'test')"
        )
        rows = seeded_db.query(
            "SELECT sensitivity_tier FROM raw_health_metrics WHERE id = 'h1'"
        )
        assert rows[0]["sensitivity_tier"] == 3

    def test_raw_notes_default_tier_1(self, seeded_db: DatabaseEngine) -> None:
        """raw_notes default sensitivity_tier must be 1."""
        seeded_db.execute(
            "INSERT INTO raw_notes (id, title, content, source) "
            "VALUES ('n1', 'Test', 'body', 'obsidian')"
        )
        rows = seeded_db.query(
            "SELECT sensitivity_tier FROM raw_notes WHERE id = 'n1'"
        )
        assert rows[0]["sensitivity_tier"] == 1

    def test_raw_messages_has_sender_name_column(
        self, seeded_db: DatabaseEngine,
    ) -> None:
        """raw_messages should have sender_name and is_from_me columns."""
        seeded_db.execute(
            "INSERT INTO raw_messages "
            "(id, source, sender, recipient, content, timestamp, "
            "sender_name, is_from_me) "
            "VALUES ('m1', 'whatsapp', 'a', 'b', 'hi', "
            "'2025-01-01T00:00:00Z', 'Alice', 1)"
        )
        rows = seeded_db.query(
            "SELECT sender_name, is_from_me FROM raw_messages WHERE id = 'm1'"
        )
        assert rows[0]["sender_name"] == "Alice"
        assert rows[0]["is_from_me"] == 1

    def test_created_at_default(self, seeded_db: DatabaseEngine) -> None:
        """created_at should default to current timestamp."""
        seeded_db.execute(
            "INSERT INTO raw_notes (id, title, content, source) "
            "VALUES ('ts1', 'Test', 'body', 'test')"
        )
        rows = seeded_db.query(
            "SELECT created_at FROM raw_notes WHERE id = 'ts1'"
        )
        # Should be a non-empty ISO 8601 string
        assert rows[0]["created_at"] is not None
        assert len(rows[0]["created_at"]) > 10

    def test_table_count(self) -> None:
        """ALL_TABLE_NAMES should have exactly 6 base raw tables."""
        assert len(ALL_TABLE_NAMES) == 6


# ---------------------------------------------------------------------------
# Migration tests
# ---------------------------------------------------------------------------


class TestMigrations:
    def test_run_migrations_creates_tables(
        self, seeded_db: DatabaseEngine,
    ) -> None:
        """run_migrations() should create all connector-introduced tables."""
        created = run_migrations(seeded_db)
        assert "raw_emails" in created
        assert "raw_reminders" in created
        assert "raw_workouts" in created
        assert "raw_voice_memos" in created
        assert "raw_listening_history" in created

    def test_run_migrations_idempotent(
        self, seeded_db: DatabaseEngine,
    ) -> None:
        """Running migrations twice should not raise or create duplicates."""
        run_migrations(seeded_db)
        created = run_migrations(seeded_db)
        assert len(created) == 0, "Second run should not create any tables"

    def test_ensure_table_creates_single_table(
        self, seeded_db: DatabaseEngine,
    ) -> None:
        """ensure_table() should create one specific table."""
        result = ensure_table(seeded_db, "raw_emails")
        assert result is True

        tables = get_existing_tables(seeded_db)
        assert "raw_emails" in tables

    def test_ensure_table_unknown_raises(
        self, seeded_db: DatabaseEngine,
    ) -> None:
        """ensure_table() with unknown table name should raise ValueError."""
        with pytest.raises(ValueError, match="Unknown migration table"):
            ensure_table(seeded_db, "nonexistent_table")

    def test_ensure_table_existing_returns_false(
        self, seeded_db: DatabaseEngine,
    ) -> None:
        """ensure_table() on existing table returns False."""
        ensure_table(seeded_db, "raw_emails")
        result = ensure_table(seeded_db, "raw_emails")
        assert result is False

    def test_column_additions(self, seeded_db: DatabaseEngine) -> None:
        """run_column_additions() should add missing columns."""
        added = run_column_additions(seeded_db)
        # raw_calendar_events should get is_all_day
        assert "raw_calendar_events.is_all_day" in added
        # raw_contacts should get birthday and address
        assert "raw_contacts.birthday" in added
        assert "raw_contacts.address" in added
        # raw_messages should get chat_name, is_group
        assert "raw_messages.chat_name" in added
        assert "raw_messages.is_group" in added

    def test_column_additions_idempotent(
        self, seeded_db: DatabaseEngine,
    ) -> None:
        """Running column additions twice should not add duplicates."""
        run_column_additions(seeded_db)
        added = run_column_additions(seeded_db)
        assert len(added) == 0

    def test_migration_table_schemas_count(self) -> None:
        """MIGRATION_SCHEMAS should have 5 connector tables."""
        assert len(MIGRATION_SCHEMAS) == 5

    def test_get_existing_tables(self, seeded_db: DatabaseEngine) -> None:
        """get_existing_tables() should return created table names."""
        tables = get_existing_tables(seeded_db)
        for name in ALL_TABLE_NAMES:
            assert name in tables

    def test_raw_emails_sensitivity_default(
        self, seeded_db: DatabaseEngine,
    ) -> None:
        """raw_emails should default sensitivity_tier to 2."""
        run_migrations(seeded_db)
        seeded_db.execute(
            "INSERT INTO raw_emails (id, subject, from_address) "
            "VALUES ('e1', 'Test', 'test@example.com')"
        )
        rows = seeded_db.query(
            "SELECT sensitivity_tier FROM raw_emails WHERE id = 'e1'"
        )
        assert rows[0]["sensitivity_tier"] == 2


# ---------------------------------------------------------------------------
# QueryCache unit tests
# ---------------------------------------------------------------------------


class TestQueryCache:
    def test_cache_hit_returns_same_result(self) -> None:
        """Cached result should be returned on subsequent get()."""
        cache = QueryCache(maxsize=10, ttl_seconds=60.0)
        result = [{"n": 1}, {"n": 2}]
        cache.put("SELECT n FROM t", None, result)

        cached = cache.get("SELECT n FROM t", None)
        assert cached == result

    def test_cache_miss_returns_none(self) -> None:
        """get() on a missing key should return None."""
        cache = QueryCache(maxsize=10, ttl_seconds=60.0)
        assert cache.get("SELECT 1", None) is None

    def test_cache_ttl_expiry(self) -> None:
        """Entries should expire after the TTL elapses."""
        cache = QueryCache(maxsize=10, ttl_seconds=0.05)
        cache.put("SELECT 1", None, [{"x": 1}])

        assert cache.get("SELECT 1", None) is not None
        time.sleep(0.06)
        assert cache.get("SELECT 1", None) is None

    def test_cache_lru_eviction(self) -> None:
        """Oldest entry should be evicted when maxsize is exceeded."""
        cache = QueryCache(maxsize=2, ttl_seconds=60.0)
        cache.put("q1", None, [{"a": 1}])
        cache.put("q2", None, [{"b": 2}])
        cache.put("q3", None, [{"c": 3}])

        assert cache.get("q1", None) is None
        assert cache.get("q2", None) is not None
        assert cache.get("q3", None) is not None

    def test_lru_access_refreshes_position(self) -> None:
        """Accessing an entry should refresh its LRU position."""
        cache = QueryCache(maxsize=2, ttl_seconds=60.0)
        cache.put("q1", None, [{"a": 1}])
        cache.put("q2", None, [{"b": 2}])

        cache.get("q1", None)

        cache.put("q3", None, [{"c": 3}])
        assert cache.get("q1", None) is not None
        assert cache.get("q2", None) is None

    def test_invalidate_clears_all(self) -> None:
        """invalidate() should remove all entries."""
        cache = QueryCache(maxsize=10, ttl_seconds=60.0)
        cache.put("q1", None, [{"a": 1}])
        cache.put("q2", [1], [{"b": 2}])

        cache.invalidate()
        assert cache.get("q1", None) is None
        assert cache.get("q2", [1]) is None

    def test_cache_stats(self) -> None:
        """stats() should report hits, misses, and size accurately."""
        cache = QueryCache(maxsize=10, ttl_seconds=60.0)
        cache.put("q1", None, [{"a": 1}])

        cache.get("q1", None)  # hit
        cache.get("q1", None)  # hit
        cache.get("q2", None)  # miss

        stats = cache.stats()
        assert stats["hits"] == 2
        assert stats["misses"] == 1
        assert stats["size"] == 1
        assert stats["maxsize"] == 10
        assert stats["hit_rate"] == pytest.approx(2 / 3)

    def test_different_params_different_keys(self) -> None:
        """Same SQL with different params should be separate cache entries."""
        cache = QueryCache(maxsize=10, ttl_seconds=60.0)
        cache.put("SELECT * FROM t WHERE id = ?", [1], [{"id": 1}])
        cache.put("SELECT * FROM t WHERE id = ?", [2], [{"id": 2}])

        r1 = cache.get("SELECT * FROM t WHERE id = ?", [1])
        r2 = cache.get("SELECT * FROM t WHERE id = ?", [2])
        assert r1 == [{"id": 1}]
        assert r2 == [{"id": 2}]


# ---------------------------------------------------------------------------
# DatabaseEngine cache integration tests
# ---------------------------------------------------------------------------


class TestDatabaseEngineCache:
    def test_query_caches_result(self, tmp_db: DatabaseEngine) -> None:
        """Repeated identical queries should return cached results."""
        tmp_db.execute("CREATE TABLE nums (n INTEGER)")
        tmp_db.execute("INSERT INTO nums VALUES (1)")
        tmp_db.execute("INSERT INTO nums VALUES (2)")

        r1 = tmp_db.query("SELECT n FROM nums ORDER BY n")
        r2 = tmp_db.query("SELECT n FROM nums ORDER BY n")
        assert r1 == r2

        stats = tmp_db.cache_stats()
        assert stats["hits"] >= 1

    def test_execute_invalidates_cache(self, tmp_db: DatabaseEngine) -> None:
        """execute() (DDL/DML) should clear the query cache."""
        tmp_db.execute("CREATE TABLE t (x INTEGER)")
        tmp_db.execute("INSERT INTO t VALUES (1)")
        tmp_db.query("SELECT x FROM t")

        assert tmp_db.cache_stats()["size"] == 1

        tmp_db.execute("INSERT INTO t VALUES (2)")
        assert tmp_db.cache_stats()["size"] == 0

    def test_invalidate_cache_method(self, tmp_db: DatabaseEngine) -> None:
        """invalidate_cache() should clear all cached queries."""
        tmp_db.execute("CREATE TABLE t (x INTEGER)")
        tmp_db.execute("INSERT INTO t VALUES (1)")
        tmp_db.query("SELECT x FROM t")

        tmp_db.invalidate_cache()
        assert tmp_db.cache_stats()["size"] == 0

    def test_cache_reflects_fresh_data(self, tmp_db: DatabaseEngine) -> None:
        """After invalidation, query should return updated data."""
        tmp_db.execute("CREATE TABLE t (x INTEGER)")
        tmp_db.execute("INSERT INTO t VALUES (1)")

        r1 = tmp_db.query("SELECT x FROM t")
        assert r1 == [{"x": 1}]

        tmp_db.execute("INSERT INTO t VALUES (2)")
        r2 = tmp_db.query("SELECT x FROM t ORDER BY x")
        assert r2 == [{"x": 1}, {"x": 2}]

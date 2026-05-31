"""Integration tests for the connector catalog with a live DuckDB instance.

Verifies that the catalog loads correctly, migrations run against a real
DataLayer, and all field mappings resolve to actual database columns.

Run with:
    python -m pytest tests/integration/test_connector_catalog.py -v
"""

from __future__ import annotations

import pytest
from src.core.data_layer import DataLayer
from src.core.sqlite.migrations import (
    MIGRATION_TABLE_NAMES,
    run_migrations,
)
from src.core.sqlite.schemas import ALL_TABLE_NAMES
from src.extensions.connectors.catalog import ConnectorCatalog

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def initialized_layer(
    tmp_path_factory: pytest.TempPathFactory,
) -> DataLayer:
    """Module-scoped DataLayer with schemas + migrations applied."""
    base = tmp_path_factory.mktemp("catalog_integration")
    dl = DataLayer(base_path=base / "secbrain_data")
    dl.initialize()
    run_migrations(dl.duckdb)
    yield dl
    dl.close()


@pytest.fixture(scope="module")
def catalog() -> ConnectorCatalog:
    """Module-scoped catalog instance."""
    return ConnectorCatalog()


# ---------------------------------------------------------------------------
# Catalog + DataLayer integration
# ---------------------------------------------------------------------------


class TestCatalogWithDataLayer:
    def test_all_migration_tables_exist(
        self, initialized_layer: DataLayer,
    ) -> None:
        """After migrations, all 6 new tables must exist."""
        rows = initialized_layer.duckdb.query(
            "SELECT name FROM sqlite_master"
            " WHERE type = 'table'"
        )
        existing = {r["name"] for r in rows}
        for table in MIGRATION_TABLE_NAMES:
            assert table in existing, (
                f"Migration table {table} not found"
            )

    def test_original_tables_unaffected(
        self, initialized_layer: DataLayer,
    ) -> None:
        """Original tables must still exist and have data."""
        rows = initialized_layer.duckdb.query(
            "SELECT name FROM sqlite_master"
            " WHERE type = 'table'"
        )
        existing = {r["name"] for r in rows}
        for table in ALL_TABLE_NAMES:
            assert table in existing, (
                f"Original table {table} missing after migrations"
            )

    def test_every_connector_field_resolves_to_column(
        self,
        initialized_layer: DataLayer,
        catalog: ConnectorCatalog,
    ) -> None:
        """Every data tool field must map to an actual DB column."""
        db = initialized_layer.duckdb
        for connector in catalog.all:
            for tool in connector.tools:
                if tool.tool_type != "data" or not tool.target_table:
                    continue
                cols = db.query(
                    f"PRAGMA table_info({tool.target_table})"
                )
                col_names = {r["name"] for r in cols}
                for field in tool.fields:
                    assert field.target_column in col_names, (
                        f"{connector.id}/{tool.tool_name}: "
                        f"column {field.target_column!r} missing "
                        f"from {tool.target_table}"
                    )

    def test_migration_tables_accept_inserts(
        self, initialized_layer: DataLayer,
    ) -> None:
        """Smoke test: insert a row into each migration table."""
        db = initialized_layer.duckdb
        inserts = {
            "raw_emails": (
                "INSERT INTO raw_emails (id, source, subject) "
                "VALUES ('e1', 'gmail', 'Hello')"
            ),
            "raw_reminders": (
                "INSERT INTO raw_reminders (id, title) "
                "VALUES ('r1', 'Buy milk')"
            ),
            "raw_workouts": (
                "INSERT INTO raw_workouts "
                "(id, workout_type, date) "
                "VALUES ('w1', 'running', '2026-01-01T08:00:00Z')"
            ),
            "raw_voice_memos": (
                "INSERT INTO raw_voice_memos (id) "
                "VALUES ('v1')"
            ),
            "raw_listening_history": (
                "INSERT INTO raw_listening_history "
                "(id, track_name, played_at) "
                "VALUES ('l1', 'Song', '2026-01-01T20:00:00Z')"
            ),
        }
        for table, sql in inserts.items():
            db.execute(sql)
            rows = db.query(f"SELECT id FROM {table} LIMIT 1")
            assert len(rows) == 1, (
                f"Insert into {table} produced no rows"
            )

    def test_column_additions_on_existing_tables(
        self, initialized_layer: DataLayer,
    ) -> None:
        """Columns added by migrations must be writable."""
        db = initialized_layer.duckdb
        # Insert a calendar event with is_all_day
        db.execute(
            "INSERT INTO raw_calendar_events "
            "(id, title, start_time, end_time, is_all_day) "
            "VALUES ('cal-int-1', 'All Day Event', "
            "'2026-02-24T00:00:00Z', '2026-02-25T00:00:00Z', true)"
        )
        rows = db.query(
            "SELECT is_all_day FROM raw_calendar_events "
            "WHERE id = 'cal-int-1'"
        )
        # SQLite stores booleans as INTEGER 0/1.
        assert bool(rows[0]["is_all_day"]) is True

        # Insert a message with chat_name and is_from_me
        db.execute(
            "INSERT INTO raw_messages "
            "(id, source, sender, recipient, content, "
            "timestamp, chat_name, is_from_me) "
            "VALUES ('msg-int-1', 'imessage', 'me', 'them', "
            "'hi', '2026-02-24T10:00:00Z', 'Group Chat', true)"
        )
        rows = db.query(
            "SELECT chat_name, is_from_me FROM raw_messages "
            "WHERE id = 'msg-int-1'"
        )
        assert rows[0]["chat_name"] == "Group Chat"
        assert bool(rows[0]["is_from_me"]) is True

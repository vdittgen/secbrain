"""Tests for IngestionAdapter — fetch, transform, dedup, upsert."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from src.core.sqlite.engine import DatabaseEngine
from src.core.sqlite.migrations import run_migrations
from src.core.sqlite.schemas import create_all_tables
from src.extensions.ingestion.adapter import (
    IngestionAdapter,
    SyncError,
    SyncResult,
)
from src.extensions.models import FieldTemplate, ToolTemplate


@pytest.fixture(autouse=True)
def _disable_ingest_cutoff(monkeypatch: pytest.MonkeyPatch) -> None:
    """Prevent the real ``~/.secbrain/settings.json`` cutoff from filtering
    test rows whose timestamps predate the user's actual cutoff.
    """
    monkeypatch.setattr(
        "src.extensions.ingestion.adapter._load_ingest_cutoff",
        lambda: None,
    )

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class FakeMcpClient:
    """Controllable MCP client for adapter tests."""

    def __init__(
        self,
        records: list[dict[str, Any]] | None = None,
        error: Exception | None = None,
    ) -> None:
        self._records = records or []
        self._error = error
        self.call_count = 0
        self.last_tool_name: str | None = None
        self.last_arguments: dict[str, Any] | None = None

    def call_tool(
        self,
        tool_name: str,
        arguments: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        self.call_count += 1
        self.last_tool_name = tool_name
        self.last_arguments = arguments
        if self._error:
            raise self._error
        return list(self._records)


class ScriptedMcpClient:
    """MCP client with per-tool scripted responses."""

    def __init__(
        self,
        responses: dict[str, Any],
        errors: dict[str, Exception] | None = None,
    ) -> None:
        self._responses = responses
        self._errors = errors or {}
        self.calls: list[tuple[str, dict[str, Any] | None]] = []

    def call_tool(
        self,
        tool_name: str,
        arguments: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        self.calls.append((tool_name, arguments))
        if tool_name in self._errors:
            raise self._errors[tool_name]

        payload = self._responses.get(tool_name, [])
        if callable(payload):
            result = payload(arguments or {})
        else:
            result = payload
        return list(result)


def _make_tool(
    target_table: str = "raw_messages",
    dedup_key: tuple[str, ...] = ("id",),
) -> ToolTemplate:
    """Create a minimal ToolTemplate for testing.

    Matches the raw_messages schema (id, source, sender, recipient,
    content, timestamp are all NOT NULL).
    """
    return ToolTemplate(
        tool_name="list_messages",
        tool_type="data",
        target_table=target_table,
        fields=(
            FieldTemplate(
                source_name="id",
                target_column="id",
                source_type="string",
                target_type="VARCHAR",
                sensitivity_tier=1,
                transform=None,
            ),
            FieldTemplate(
                source_name="sender",
                target_column="sender",
                source_type="string",
                target_type="VARCHAR",
                sensitivity_tier=2,
                transform="trim",
            ),
            FieldTemplate(
                source_name="recipient",
                target_column="recipient",
                source_type="string",
                target_type="VARCHAR",
                sensitivity_tier=2,
                transform=None,
            ),
            FieldTemplate(
                source_name="content",
                target_column="content",
                source_type="string",
                target_type="TEXT",
                sensitivity_tier=3,
                transform=None,
            ),
            FieldTemplate(
                source_name="ts",
                target_column="timestamp",
                source_type="string",
                target_type="TIMESTAMPTZ",
                sensitivity_tier=2,
                transform="iso_to_timestamp",
            ),
        ),
        dedup_key=dedup_key,
    )


def _make_whatsapp_chats_tool() -> ToolTemplate:
    """Create a WhatsApp list_chats tool template."""
    return ToolTemplate(
        tool_name="list_chats",
        tool_type="data",
        target_table="raw_messages",
        fields=(
            FieldTemplate(
                source_name="sender",
                target_column="sender",
                source_type="string",
                target_type="VARCHAR",
                sensitivity_tier=2,
                transform=None,
            ),
            FieldTemplate(
                source_name="recipient",
                target_column="recipient",
                source_type="string",
                target_type="VARCHAR",
                sensitivity_tier=2,
                transform=None,
            ),
            FieldTemplate(
                source_name="content",
                target_column="content",
                source_type="string",
                target_type="TEXT",
                sensitivity_tier=3,
                transform=None,
            ),
            FieldTemplate(
                source_name="timestamp",
                target_column="timestamp",
                source_type="string",
                target_type="TIMESTAMPTZ",
                sensitivity_tier=2,
                transform="iso_to_timestamp",
            ),
            FieldTemplate(
                source_name="is_from_me",
                target_column="is_from_me",
                source_type="boolean",
                target_type="BOOLEAN",
                sensitivity_tier=1,
                transform=None,
            ),
            FieldTemplate(
                source_name="chat_name",
                target_column="chat_name",
                source_type="string",
                target_type="VARCHAR",
                sensitivity_tier=2,
                transform=None,
            ),
            FieldTemplate(
                source_name="is_group",
                target_column="is_group",
                source_type="boolean",
                target_type="BOOLEAN",
                sensitivity_tier=1,
                transform=None,
            ),
            FieldTemplate(
                source_name="sender_name",
                target_column="sender_name",
                source_type="string",
                target_type="VARCHAR",
                sensitivity_tier=2,
                transform=None,
            ),
        ),
        dedup_key=("id", "source"),
    )


@pytest.fixture()
def tmp_db(tmp_path: Path) -> DatabaseEngine:
    """Fresh DuckDB with all base schemas + migration tables."""
    db_path = tmp_path / "test_adapter.duckdb"
    engine = DatabaseEngine(db_path=db_path)
    create_all_tables(engine)
    yield engine
    engine.close()


def _write_whatsapp_store(path: Path, payload: dict[str, Any]) -> None:
    """Persist a WhatsApp store payload for adapter ingestion tests."""
    path.write_text(json.dumps(payload), encoding="utf-8")


# ---------------------------------------------------------------------------
# TestTransformRecord
# ---------------------------------------------------------------------------


class TestTransformRecord:
    def test_maps_source_to_target_columns(self) -> None:
        tool = _make_tool()
        client = FakeMcpClient()
        adapter = IngestionAdapter("test-conn", tool, client, None)
        raw = {
            "id": "msg-1",
            "sender": "alice",
            "content": "hello",
            "ts": "2025-06-02T10:00:00",
        }
        result = adapter._transform_record(raw)
        assert result["id"] == "msg-1"
        assert result["sender"] == "alice"
        assert result["content"] == "hello"
        assert result["timestamp"] == "2025-06-02T10:00:00"

    def test_applies_trim_transform(self) -> None:
        tool = _make_tool()
        client = FakeMcpClient()
        adapter = IngestionAdapter("test-conn", tool, client, None)
        raw = {"id": "1", "sender": "  bob  ", "content": "hi", "ts": None}
        result = adapter._transform_record(raw)
        assert result["sender"] == "bob"

    def test_applies_iso_to_timestamp_transform(self) -> None:
        tool = _make_tool()
        client = FakeMcpClient()
        adapter = IngestionAdapter("test-conn", tool, client, None)
        raw = {"id": "1", "sender": "a", "content": "b", "ts": "2025-06-02T10:00:00Z"}
        result = adapter._transform_record(raw)
        assert result["timestamp"] == "2025-06-02T10:00:00Z"

    def test_missing_source_field_maps_to_none(self) -> None:
        tool = _make_tool()
        client = FakeMcpClient()
        adapter = IngestionAdapter("test-conn", tool, client, None)
        raw = {"id": "1"}
        result = adapter._transform_record(raw)
        assert result["sender"] is None
        assert result["content"] is None

    def test_adds_source_column(self) -> None:
        tool = _make_tool()
        client = FakeMcpClient()
        adapter = IngestionAdapter("test-conn", tool, client, None)
        raw = {"id": "1", "sender": "a", "content": "b", "ts": None}
        result = adapter._transform_record(raw)
        assert result["source"] == "test-conn"

    def test_preserves_id_when_present(self) -> None:
        tool = _make_tool()
        client = FakeMcpClient()
        adapter = IngestionAdapter("test-conn", tool, client, None)
        raw = {"id": "my-custom-id", "sender": "a", "content": "b", "ts": None}
        result = adapter._transform_record(raw)
        assert result["id"] == "my-custom-id"

    def test_generates_id_when_missing_from_raw(self) -> None:
        # Tool where id is NOT in the field mapping
        tool = ToolTemplate(
            tool_name="list_items",
            tool_type="data",
            target_table="raw_notes",
            fields=(
                FieldTemplate(
                    source_name="title",
                    target_column="title",
                    source_type="string",
                    target_type="VARCHAR",
                    sensitivity_tier=1,
                    transform=None,
                ),
            ),
            dedup_key=("title",),
        )
        client = FakeMcpClient()
        adapter = IngestionAdapter("test-conn", tool, client, None)
        raw = {"title": "My Note"}
        result = adapter._transform_record(raw)
        assert result["id"] is not None
        assert len(result["id"]) == 16


# ---------------------------------------------------------------------------
# TestSyncNewRecords
# ---------------------------------------------------------------------------


class TestSyncNewRecords:
    def test_inserts_new_records(self, tmp_db: DatabaseEngine) -> None:
        """Sync into empty table should insert all records."""
        tool = _make_tool()
        records = [
            {
                "id": "msg-1", "sender": "alice", "recipient": "bob",
                "content": "hi", "ts": "2025-06-02T10:00:00",
            },
            {
                "id": "msg-2", "sender": "bob", "recipient": "alice",
                "content": "hey", "ts": "2025-06-02T11:00:00",
            },
        ]
        client = FakeMcpClient(records=records)
        adapter = IngestionAdapter("test-conn", tool, client, tmp_db)

        result = adapter.sync()

        assert result.status == "success"
        assert result.rows_fetched == 2
        assert result.rows_new == 2
        assert result.rows_updated == 0
        assert result.rows_unchanged == 0

        # Verify data in DuckDB
        rows = tmp_db.query("SELECT * FROM raw_messages WHERE source = 'test-conn'")
        assert len(rows) == 2

    def test_sets_sensitivity_tier(self, tmp_db: DatabaseEngine) -> None:
        tool = _make_tool()
        records = [
            {
                "id": "msg-1", "sender": "a", "recipient": "b",
                "content": "b", "ts": "2025-06-02T10:00:00",
            },
        ]
        client = FakeMcpClient(records=records)
        adapter = IngestionAdapter("test-conn", tool, client, tmp_db)

        adapter.sync()

        rows = tmp_db.query(
            "SELECT sensitivity_tier FROM raw_messages WHERE id = 'msg-1'",
        )
        assert rows[0]["sensitivity_tier"] == 3  # max tier from fields

    def test_handles_missing_dedup_columns_in_target_table(
        self, tmp_db: DatabaseEngine,
    ) -> None:
        """Dedup keys referencing absent columns should not break sync.

        raw_calendar_events has no ``source`` column, so the adapter must
        ignore that key and still insert/update by ``id``.
        """
        tool = ToolTemplate(
            tool_name="list_calendar_events",
            tool_type="data",
            target_table="raw_calendar_events",
            fields=(
                FieldTemplate(
                    source_name="id",
                    target_column="id",
                    source_type="string",
                    target_type="VARCHAR",
                    sensitivity_tier=1,
                    transform=None,
                ),
                FieldTemplate(
                    source_name="title",
                    target_column="title",
                    source_type="string",
                    target_type="VARCHAR",
                    sensitivity_tier=1,
                    transform=None,
                ),
                FieldTemplate(
                    source_name="start_time",
                    target_column="start_time",
                    source_type="string",
                    target_type="TIMESTAMPTZ",
                    sensitivity_tier=2,
                    transform="iso_to_timestamp",
                ),
                FieldTemplate(
                    source_name="end_time",
                    target_column="end_time",
                    source_type="string",
                    target_type="TIMESTAMPTZ",
                    sensitivity_tier=2,
                    transform="iso_to_timestamp",
                ),
            ),
            dedup_key=("id", "source"),
        )
        records = [
            {
                "id": "evt-1",
                "title": "Team sync",
                "start_time": "2025-06-02T10:00:00Z",
                "end_time": "2025-06-02T11:00:00Z",
            },
        ]
        client = FakeMcpClient(records=records)
        adapter = IngestionAdapter("apple-calendar", tool, client, tmp_db)

        with patch.object(adapter, "_fetch_apple_native", return_value=records):
            result = adapter.sync()

        assert result.status == "success"
        assert result.rows_new == 1
        rows = tmp_db.query(
            "SELECT id, title FROM raw_calendar_events WHERE id = 'evt-1'",
        )
        assert len(rows) == 1
        assert rows[0]["title"] == "Team sync"

    def test_returns_correct_counts(self, tmp_db: DatabaseEngine) -> None:
        tool = _make_tool()
        records = [
            {
                "id": f"msg-{i}", "sender": "a", "recipient": "b",
                "content": "b", "ts": "2025-06-02T10:00:00",
            }
            for i in range(5)
        ]
        client = FakeMcpClient(records=records)
        adapter = IngestionAdapter("test-conn", tool, client, tmp_db)

        result = adapter.sync()
        assert result.rows_new == 5
        assert result.rows_fetched == 5

    def test_empty_records_returns_zero_counts(
        self, tmp_db: DatabaseEngine,
    ) -> None:
        tool = _make_tool()
        client = FakeMcpClient(records=[])
        adapter = IngestionAdapter("test-conn", tool, client, tmp_db)

        result = adapter.sync()
        assert result.rows_fetched == 0
        assert result.rows_new == 0


# ---------------------------------------------------------------------------
# TestSyncDedup
# ---------------------------------------------------------------------------


class TestSyncDedup:
    def test_skips_unchanged_records(
        self, tmp_db: DatabaseEngine,
    ) -> None:
        """Second sync with same data should report unchanged."""
        tool = _make_tool()
        records = [
            {
                "id": "msg-1", "sender": "alice", "recipient": "bob",
                "content": "hi", "ts": "2025-06-02T10:00:00",
            },
        ]

        # First sync
        client1 = FakeMcpClient(records=records)
        adapter1 = IngestionAdapter("test-conn", tool, client1, tmp_db)
        adapter1.sync()

        # Second sync — same data
        client2 = FakeMcpClient(records=records)
        adapter2 = IngestionAdapter("test-conn", tool, client2, tmp_db)
        result = adapter2.sync()

        assert result.rows_new == 0
        assert result.rows_updated == 0
        assert result.rows_unchanged == 1

    def test_updates_changed_records(
        self, tmp_db: DatabaseEngine,
    ) -> None:
        """Sync with modified field values should UPDATE existing rows."""
        tool = _make_tool()

        # First sync
        records1 = [
            {
                "id": "msg-1", "sender": "alice", "recipient": "bob",
                "content": "v1", "ts": "2025-06-02T10:00:00",
            },
        ]
        client1 = FakeMcpClient(records=records1)
        adapter1 = IngestionAdapter("test-conn", tool, client1, tmp_db)
        adapter1.sync()

        # Second sync — changed content
        records2 = [
            {
                "id": "msg-1", "sender": "alice", "recipient": "bob",
                "content": "v2", "ts": "2025-06-02T10:00:00",
            },
        ]
        client2 = FakeMcpClient(records=records2)
        adapter2 = IngestionAdapter("test-conn", tool, client2, tmp_db)
        result = adapter2.sync()

        assert result.rows_updated == 1
        assert result.rows_new == 0

        # Verify updated value
        rows = tmp_db.query("SELECT content FROM raw_messages WHERE id = 'msg-1'")
        assert rows[0]["content"] == "v2"

    def test_mixed_new_and_existing(
        self, tmp_db: DatabaseEngine,
    ) -> None:
        """Batch with some new and some existing records."""
        tool = _make_tool()

        # Insert one record
        records1 = [
            {
                "id": "msg-1", "sender": "alice", "recipient": "bob",
                "content": "hi", "ts": "2025-06-02T10:00:00",
            },
        ]
        client1 = FakeMcpClient(records=records1)
        adapter1 = IngestionAdapter("test-conn", tool, client1, tmp_db)
        adapter1.sync()

        # Sync with existing + new
        records2 = [
            {
                "id": "msg-1", "sender": "alice", "recipient": "bob",
                "content": "hi", "ts": "2025-06-02T10:00:00",
            },
            {
                "id": "msg-2", "sender": "bob", "recipient": "alice",
                "content": "hey", "ts": "2025-06-02T11:00:00",
            },
        ]
        client2 = FakeMcpClient(records=records2)
        adapter2 = IngestionAdapter("test-conn", tool, client2, tmp_db)
        result = adapter2.sync()

        assert result.rows_new == 1
        assert result.rows_unchanged == 1

    def test_collapses_intra_batch_duplicates_by_dedup_key(
        self, tmp_db: DatabaseEngine,
    ) -> None:
        """Two records with the same dedup key in one batch → one INSERT.

        Mirrors macOS Mail's Envelope Index, where one Gmail message
        appears once per label folder (Inbox + Important + All Mail)
        all sharing the same ``message_id``. Pre-fix, the second
        ``INSERT INTO raw_messages`` would raise
        ``UNIQUE constraint failed: raw_messages.id`` and roll back
        the entire sync.
        """
        tool = _make_tool()
        records = [
            {
                "id": "msg-1", "sender": "alice", "recipient": "bob",
                "content": "from Inbox folder",
                "ts": "2025-06-02T10:00:00",
            },
            {
                "id": "msg-1", "sender": "alice", "recipient": "bob",
                "content": "from Important folder",
                "ts": "2025-06-02T10:00:00",
            },
            {
                "id": "msg-1", "sender": "alice", "recipient": "bob",
                "content": "from All Mail folder",
                "ts": "2025-06-02T10:00:00",
            },
            {
                "id": "msg-2", "sender": "carol", "recipient": "dave",
                "content": "unique",
                "ts": "2025-06-02T11:00:00",
            },
        ]
        client = FakeMcpClient(records=records)
        adapter = IngestionAdapter("test-conn", tool, client, tmp_db)

        result = adapter.sync()

        assert result.rows_new == 2
        assert result.rows_updated == 0
        rows = tmp_db.query(
            "SELECT id, content FROM raw_messages "
            "WHERE id IN ('msg-1', 'msg-2') ORDER BY id",
        )
        # First-occurrence wins for the duplicated id.
        assert rows[0]["id"] == "msg-1"
        assert rows[0]["content"] == "from Inbox folder"
        assert rows[1]["id"] == "msg-2"

    def test_inserts_all_when_no_dedup_key(
        self, tmp_db: DatabaseEngine,
    ) -> None:
        """Tool with empty dedup_key should insert every record."""
        tool = _make_tool(dedup_key=())
        records = [
            {
                "id": "msg-1", "sender": "a", "recipient": "b",
                "content": "b", "ts": "2025-06-02T10:00:00",
            },
            {
                "id": "msg-2", "sender": "c", "recipient": "d",
                "content": "d", "ts": "2025-06-02T11:00:00",
            },
        ]
        client = FakeMcpClient(records=records)
        adapter = IngestionAdapter("test-conn", tool, client, tmp_db)

        result = adapter.sync()
        assert result.rows_new == 2
        assert result.rows_updated == 0


# ---------------------------------------------------------------------------
# TestSyncErrors
# ---------------------------------------------------------------------------


class TestSyncErrors:
    def test_mcp_tool_error_raises_sync_error(
        self, tmp_db: DatabaseEngine,
    ) -> None:
        tool = _make_tool()
        client = FakeMcpClient(error=RuntimeError("MCP timeout"))
        adapter = IngestionAdapter("test-conn", tool, client, tmp_db)

        with pytest.raises(SyncError, match="MCP tool call failed"):
            adapter.sync()

    def test_transaction_rollback_on_insert_error(
        self, tmp_db: DatabaseEngine,
    ) -> None:
        """If insert fails, transaction should be rolled back."""
        # Use a tool targeting a non-existent table
        tool = _make_tool(target_table="nonexistent_table")
        records = [
            {
                "id": "1", "sender": "a", "recipient": "b",
                "content": "b", "ts": "2025-06-02T10:00:00",
            },
        ]
        client = FakeMcpClient(records=records)
        adapter = IngestionAdapter("test-conn", tool, client, tmp_db)

        with pytest.raises(SyncError):
            adapter.sync()


# ---------------------------------------------------------------------------
# TestPlaceholderFiltering
# ---------------------------------------------------------------------------


class TestPlaceholderFiltering:
    def test_filters_fake_calendar_rows(self, tmp_db: DatabaseEngine) -> None:
        tool = ToolTemplate(
            tool_name="list_calendar_events",
            tool_type="data",
            target_table="raw_calendar_events",
            fields=(
                FieldTemplate(
                    source_name="title",
                    target_column="title",
                    source_type="string",
                    target_type="VARCHAR",
                    sensitivity_tier=1,
                    transform=None,
                ),
                FieldTemplate(
                    source_name="start_time",
                    target_column="start_time",
                    source_type="string",
                    target_type="TIMESTAMPTZ",
                    sensitivity_tier=2,
                    transform="iso_to_timestamp",
                ),
                FieldTemplate(
                    source_name="end_time",
                    target_column="end_time",
                    source_type="string",
                    target_type="TIMESTAMPTZ",
                    sensitivity_tier=2,
                    transform="iso_to_timestamp",
                ),
                FieldTemplate(
                    source_name="description",
                    target_column="description",
                    source_type="string",
                    target_type="TEXT",
                    sensitivity_tier=2,
                    transform=None,
                ),
            ),
            dedup_key=("id",),
        )
        records = [
            {
                "id": "dummy-event-1",
                "title": "No events available - Calendar operations too slow",
                "start_time": "2026-02-27T10:00:00Z",
                "end_time": "2026-02-27T11:00:00Z",
                "description": (
                    "Calendar.app AppleScript queries are "
                    "notoriously slow and unreliable"
                ),
            },
        ]
        client = FakeMcpClient(records=records)
        adapter = IngestionAdapter("apple-calendar", tool, client, tmp_db)

        with patch.object(adapter, "_fetch_apple_native", return_value=records):
            result = adapter.sync()
        assert result.rows_fetched == 0
        assert result.rows_new == 0
        rows = tmp_db.query("SELECT COUNT(*) AS n FROM raw_calendar_events")
        assert rows[0]["n"] == 0

    def test_filters_placeholder_reminder_rows(self, tmp_db: DatabaseEngine) -> None:
        run_migrations(tmp_db)
        tool = ToolTemplate(
            tool_name="list_reminders",
            tool_type="data",
            target_table="raw_reminders",
            fields=(
                FieldTemplate(
                    source_name="title",
                    target_column="title",
                    source_type="string",
                    target_type="VARCHAR",
                    sensitivity_tier=1,
                    transform=None,
                ),
                FieldTemplate(
                    source_name="due_date",
                    target_column="due_date",
                    source_type="string",
                    target_type="TIMESTAMPTZ",
                    sensitivity_tier=2,
                    transform="iso_to_timestamp",
                ),
                FieldTemplate(
                    source_name="notes",
                    target_column="notes",
                    source_type="string",
                    target_type="TEXT",
                    sensitivity_tier=2,
                    transform=None,
                ),
                FieldTemplate(
                    source_name="completed",
                    target_column="completed",
                    source_type="boolean",
                    target_type="BOOLEAN",
                    sensitivity_tier=1,
                    transform=None,
                ),
                FieldTemplate(
                    source_name="list_name",
                    target_column="list_name",
                    source_type="string",
                    target_type="VARCHAR",
                    sensitivity_tier=1,
                    transform=None,
                ),
            ),
            dedup_key=("id",),
        )
        records = [
            {
                "_raw_text": "Found 0 lists and 0 reminders.",
                "id": None,
                "title": "Untitled Reminder",
                "due_date": None,
                "notes": None,
                "list_name": None,
                "completed": False,
            },
        ]
        client = FakeMcpClient(records=records)
        adapter = IngestionAdapter("apple-calendar", tool, client, tmp_db)

        with patch.object(adapter, "_fetch_apple_native", return_value=records):
            result = adapter.sync()
        assert result.rows_fetched == 0
        assert result.rows_new == 0
        rows = tmp_db.query("SELECT COUNT(*) AS n FROM raw_reminders")
        assert rows[0]["n"] == 0

    def test_generates_real_id_for_none_source_id(self, tmp_db: DatabaseEngine) -> None:
        run_migrations(tmp_db)
        tool = ToolTemplate(
            tool_name="list_reminders",
            tool_type="data",
            target_table="raw_reminders",
            fields=(
                FieldTemplate(
                    source_name="title",
                    target_column="title",
                    source_type="string",
                    target_type="VARCHAR",
                    sensitivity_tier=1,
                    transform=None,
                ),
                FieldTemplate(
                    source_name="list_name",
                    target_column="list_name",
                    source_type="string",
                    target_type="VARCHAR",
                    sensitivity_tier=1,
                    transform=None,
                ),
            ),
            dedup_key=("id",),
        )
        records = [
            {
                "id": None,
                "title": "Pay rent",
                "list_name": "Personal",
            },
        ]
        client = FakeMcpClient(records=records)
        adapter = IngestionAdapter("apple-calendar", tool, client, tmp_db)

        with patch.object(adapter, "_fetch_apple_native", return_value=records):
            result = adapter.sync()
        assert result.rows_new == 1
        rows = tmp_db.query("SELECT id, title FROM raw_reminders")
        assert len(rows) == 1
        assert rows[0]["id"] != "None"
        assert rows[0]["title"] == "Pay rent"

    def test_whatsapp_missing_store_file_is_non_fatal(
        self,
        tmp_db: DatabaseEngine,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        store_path = tmp_path / "missing_store.json"
        monkeypatch.setattr(
            "src.extensions.ingestion.adapter.resolve_whatsapp_store_path",
            lambda: store_path,
        )
        tool = _make_whatsapp_chats_tool()
        client = FakeMcpClient(error=RuntimeError("should not be called"))
        adapter = IngestionAdapter("whatsapp", tool, client, tmp_db)

        result = adapter.sync()

        assert result.status == "success"
        assert result.rows_fetched == 0
        assert client.call_count == 0


class TestWhatsAppStoreIncrementalSync:
    def test_syncs_messages_from_store_payload(
        self,
        tmp_db: DatabaseEngine,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        run_migrations(tmp_db)
        store_path = tmp_path / "store.json"
        _write_whatsapp_store(
            store_path,
            {
                "chats": {
                    "14155551234@s.whatsapp.net": {
                        "id": "14155551234@s.whatsapp.net",
                        "name": "Alice",
                    },
                },
                "contacts": {},
                "messages": {
                    "14155551234@s.whatsapp.net": [
                        {
                            "key": {
                                "id": "m-1",
                                "remoteJid": "14155551234@s.whatsapp.net",
                                "fromMe": False,
                            },
                            "message": {
                                "conversation": "hello",
                            },
                            "messageTimestamp": 1772298000,
                        },
                        {
                            "key": {
                                "id": "m-2",
                                "remoteJid": "14155551234@s.whatsapp.net",
                                "fromMe": True,
                            },
                            "message": {
                                "extendedTextMessage": {
                                    "text": "hi back",
                                },
                            },
                            "messageTimestamp": 1772298060,
                        },
                    ],
                },
            },
        )
        monkeypatch.setattr(
            "src.extensions.ingestion.adapter.resolve_whatsapp_store_path",
            lambda: store_path,
        )

        tool = _make_whatsapp_chats_tool()
        adapter = IngestionAdapter("whatsapp", tool, FakeMcpClient(), tmp_db)

        result = adapter.sync()

        assert result.status == "success"
        assert result.rows_new == 2
        rows = tmp_db.query(
            "SELECT id, recipient, chat_name, source, is_from_me, sender_name "
            "FROM raw_messages WHERE source = 'whatsapp' ORDER BY timestamp",
        )
        assert len(rows) == 2
        assert rows[0]["recipient"] == "14155551234@s.whatsapp.net"
        assert rows[0]["chat_name"] == "Alice"
        assert rows[0]["source"] == "whatsapp"
        assert not rows[0]["is_from_me"]
        assert rows[0]["sender_name"] == "Alice"
        assert rows[1]["is_from_me"]
        assert rows[1]["sender_name"] == "me"
        assert str(rows[0]["id"]).startswith("14155551234@s.whatsapp.net:")

    def test_filters_already_synced_messages_by_chat_timestamp(
        self,
        tmp_db: DatabaseEngine,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        run_migrations(tmp_db)
        tmp_db.execute(
            "INSERT INTO raw_messages "
            "(id, source, sender, recipient, content, timestamp, chat_name, is_group) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [
                "14155551234@s.whatsapp.net:m-1",
                "whatsapp",
                "14155551234@s.whatsapp.net",
                "14155551234@s.whatsapp.net",
                "old message",
                "2026-02-28T17:00:00Z",
                "Alice",
                False,
            ],
        )

        store_path = tmp_path / "store.json"
        _write_whatsapp_store(
            store_path,
            {
                "chats": {
                    "14155551234@s.whatsapp.net": {
                        "id": "14155551234@s.whatsapp.net",
                        "name": "Alice",
                    },
                },
                "contacts": {},
                "messages": {
                    "14155551234@s.whatsapp.net": [
                        {
                            "key": {
                                "id": "m-1",
                                "remoteJid": "14155551234@s.whatsapp.net",
                                "fromMe": False,
                            },
                            "message": {"conversation": "old message"},
                            "messageTimestamp": "2026-02-28T17:00:00Z",
                        },
                        {
                            "key": {
                                "id": "m-2",
                                "remoteJid": "14155551234@s.whatsapp.net",
                                "fromMe": True,
                            },
                            "message": {"conversation": "new message"},
                            "messageTimestamp": "2026-02-28T17:05:00Z",
                        },
                    ],
                },
            },
        )
        monkeypatch.setattr(
            "src.extensions.ingestion.adapter.resolve_whatsapp_store_path",
            lambda: store_path,
        )

        tool = _make_whatsapp_chats_tool()
        adapter = IngestionAdapter("whatsapp", tool, FakeMcpClient(), tmp_db)
        result = adapter.sync()

        assert result.status == "success"
        assert result.rows_new == 1
        rows = tmp_db.query(
            "SELECT id, content FROM raw_messages "
            "WHERE source = 'whatsapp' ORDER BY timestamp",
        )
        assert len(rows) == 2
        assert rows[-1]["id"] == "14155551234@s.whatsapp.net:m-2"
        assert rows[-1]["content"] == "new message"

    def test_skips_protocol_messages_from_store(
        self,
        tmp_db: DatabaseEngine,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        run_migrations(tmp_db)
        store_path = tmp_path / "store.json"
        _write_whatsapp_store(
            store_path,
            {
                "chats": {"14150000000@s.whatsapp.net": {"name": "Control"}},
                "contacts": {},
                "messages": {
                    "14150000000@s.whatsapp.net": [
                        {
                            "key": {
                                "id": "ctrl-1",
                                "remoteJid": "14150000000@s.whatsapp.net",
                            },
                            "message": {
                                "protocolMessage": {
                                    "type": "APP_STATE_SYNC_KEY_SHARE",
                                },
                            },
                            "messageTimestamp": 1772298123,
                        },
                    ],
                },
            },
        )
        monkeypatch.setattr(
            "src.extensions.ingestion.adapter.resolve_whatsapp_store_path",
            lambda: store_path,
        )

        tool = _make_whatsapp_chats_tool()
        adapter = IngestionAdapter("whatsapp", tool, FakeMcpClient(), tmp_db)
        result = adapter.sync()

        assert result.status == "success"
        assert result.rows_fetched == 0


# ---------------------------------------------------------------------------
# TestIdGeneration
# ---------------------------------------------------------------------------


class TestWhatsAppSenderNameResolution:
    """Tests for sender name resolution from contacts and chats dict."""

    def test_resolves_sender_name_from_chat_name_in_direct_chat(
        self,
        tmp_db: DatabaseEngine,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """1:1 chat: sender_name = chat_name (the contact name)."""
        run_migrations(tmp_db)
        store_path = tmp_path / "store.json"
        _write_whatsapp_store(
            store_path,
            {
                "chats": {
                    "14155551234@s.whatsapp.net": {
                        "id": "14155551234@s.whatsapp.net",
                        "name": "Alice",
                    },
                },
                "contacts": {},
                "messages": {
                    "14155551234@s.whatsapp.net": [
                        {
                            "key": {
                                "id": "m-1",
                                "remoteJid": "14155551234@s.whatsapp.net",
                                "fromMe": False,
                            },
                            "message": {"conversation": "hello"},
                            "messageTimestamp": 1772298000,
                        },
                    ],
                },
            },
        )
        monkeypatch.setattr(
            "src.extensions.ingestion.adapter.resolve_whatsapp_store_path",
            lambda: store_path,
        )

        tool = _make_whatsapp_chats_tool()
        adapter = IngestionAdapter("whatsapp", tool, FakeMcpClient(), tmp_db)
        result = adapter.sync()

        assert result.status == "success"
        rows = tmp_db.query(
            "SELECT sender, sender_name, chat_name FROM raw_messages "
            "WHERE source = 'whatsapp'",
        )
        assert len(rows) == 1
        assert rows[0]["sender_name"] == "Alice"
        assert rows[0]["chat_name"] == "Alice"

    def test_resolves_sender_name_from_raw_contacts(
        self,
        tmp_db: DatabaseEngine,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Phone-based lookup from raw_contacts resolves sender name."""
        run_migrations(tmp_db)
        # Seed a contact with matching phone
        tmp_db.execute(
            "INSERT INTO raw_contacts (id, name, phone, sensitivity_tier) "
            "VALUES (?, ?, ?, ?)",
            ["c-1", "Bob Smith", "+1 (415) 555-1234", 2],
        )

        store_path = tmp_path / "store.json"
        _write_whatsapp_store(
            store_path,
            {
                "chats": {
                    "14155551234@s.whatsapp.net": {
                        "id": "14155551234@s.whatsapp.net",
                    },
                },
                "contacts": {},
                "messages": {
                    "14155551234@s.whatsapp.net": [
                        {
                            "key": {
                                "id": "m-1",
                                "remoteJid": "14155551234@s.whatsapp.net",
                                "fromMe": False,
                            },
                            "message": {"conversation": "hi"},
                            "messageTimestamp": 1772298000,
                        },
                    ],
                },
            },
        )
        monkeypatch.setattr(
            "src.extensions.ingestion.adapter.resolve_whatsapp_store_path",
            lambda: store_path,
        )

        tool = _make_whatsapp_chats_tool()
        adapter = IngestionAdapter("whatsapp", tool, FakeMcpClient(), tmp_db)
        result = adapter.sync()

        assert result.status == "success"
        rows = tmp_db.query(
            "SELECT sender_name FROM raw_messages WHERE source = 'whatsapp'",
        )
        assert len(rows) == 1
        assert rows[0]["sender_name"] == "Bob Smith"

    def test_group_message_sender_name_from_lookup(
        self,
        tmp_db: DatabaseEngine,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Group message: participant JID resolved via chats dict lookup."""
        run_migrations(tmp_db)
        store_path = tmp_path / "store.json"
        _write_whatsapp_store(
            store_path,
            {
                "chats": {
                    "groupid@g.us": {
                        "id": "groupid@g.us",
                        "name": "Family Chat",
                        "isGroup": True,
                    },
                    "14155551234@s.whatsapp.net": {
                        "id": "14155551234@s.whatsapp.net",
                        "name": "Alice",
                    },
                },
                "contacts": {},
                "messages": {
                    "groupid@g.us": [
                        {
                            "key": {
                                "id": "gm-1",
                                "remoteJid": "groupid@g.us",
                                "fromMe": False,
                                "participant": "14155551234@s.whatsapp.net",
                            },
                            "message": {"conversation": "hey group"},
                            "messageTimestamp": 1772298000,
                        },
                    ],
                },
            },
        )
        monkeypatch.setattr(
            "src.extensions.ingestion.adapter.resolve_whatsapp_store_path",
            lambda: store_path,
        )

        tool = _make_whatsapp_chats_tool()
        adapter = IngestionAdapter("whatsapp", tool, FakeMcpClient(), tmp_db)
        result = adapter.sync()

        assert result.status == "success"
        rows = tmp_db.query(
            "SELECT sender_name, chat_name, is_group FROM raw_messages "
            "WHERE source = 'whatsapp'",
        )
        assert len(rows) == 1
        assert rows[0]["sender_name"] == "Alice"
        assert rows[0]["chat_name"] == "Family Chat"
        assert rows[0]["is_group"]

    def test_lid_jid_fallback_to_unknown(
        self,
        tmp_db: DatabaseEngine,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """@lid JID with no match → sender_name = 'Unknown'."""
        run_migrations(tmp_db)
        store_path = tmp_path / "store.json"
        _write_whatsapp_store(
            store_path,
            {
                "chats": {
                    "groupid@g.us": {
                        "id": "groupid@g.us",
                        "name": "Work Group",
                        "isGroup": True,
                    },
                },
                "contacts": {},
                "messages": {
                    "groupid@g.us": [
                        {
                            "key": {
                                "id": "gm-lid",
                                "remoteJid": "groupid@g.us",
                                "fromMe": False,
                                "participant": "85573213663263@lid",
                            },
                            "message": {"conversation": "hi from lid"},
                            "messageTimestamp": 1772298000,
                        },
                    ],
                },
            },
        )
        monkeypatch.setattr(
            "src.extensions.ingestion.adapter.resolve_whatsapp_store_path",
            lambda: store_path,
        )

        tool = _make_whatsapp_chats_tool()
        adapter = IngestionAdapter("whatsapp", tool, FakeMcpClient(), tmp_db)
        result = adapter.sync()

        assert result.status == "success"
        rows = tmp_db.query(
            "SELECT sender_name FROM raw_messages WHERE source = 'whatsapp'",
        )
        assert len(rows) == 1
        assert rows[0]["sender_name"] == "Unknown"

    def test_from_me_sender_name_is_me(
        self,
        tmp_db: DatabaseEngine,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Own messages: sender_name = 'me'."""
        run_migrations(tmp_db)
        store_path = tmp_path / "store.json"
        _write_whatsapp_store(
            store_path,
            {
                "chats": {
                    "14155551234@s.whatsapp.net": {
                        "id": "14155551234@s.whatsapp.net",
                        "name": "Alice",
                    },
                },
                "contacts": {},
                "messages": {
                    "14155551234@s.whatsapp.net": [
                        {
                            "key": {
                                "id": "m-me",
                                "remoteJid": "14155551234@s.whatsapp.net",
                                "fromMe": True,
                            },
                            "message": {"conversation": "my message"},
                            "messageTimestamp": 1772298000,
                        },
                    ],
                },
            },
        )
        monkeypatch.setattr(
            "src.extensions.ingestion.adapter.resolve_whatsapp_store_path",
            lambda: store_path,
        )

        tool = _make_whatsapp_chats_tool()
        adapter = IngestionAdapter("whatsapp", tool, FakeMcpClient(), tmp_db)
        result = adapter.sync()

        assert result.status == "success"
        rows = tmp_db.query(
            "SELECT sender, sender_name FROM raw_messages WHERE source = 'whatsapp'",
        )
        assert len(rows) == 1
        assert rows[0]["sender"] == "me"
        assert rows[0]["sender_name"] == "me"

    def test_phone_jid_no_contact_shows_formatted_phone(
        self,
        tmp_db: DatabaseEngine,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """@s.whatsapp.net JID with no contact match → formatted phone."""
        run_migrations(tmp_db)
        store_path = tmp_path / "store.json"
        _write_whatsapp_store(
            store_path,
            {
                "chats": {
                    "5511999887766@s.whatsapp.net": {
                        "id": "5511999887766@s.whatsapp.net",
                    },
                },
                "contacts": {},
                "messages": {
                    "5511999887766@s.whatsapp.net": [
                        {
                            "key": {
                                "id": "m-phone",
                                "remoteJid": "5511999887766@s.whatsapp.net",
                                "fromMe": False,
                            },
                            "message": {"conversation": "hi"},
                            "messageTimestamp": 1772298000,
                        },
                    ],
                },
            },
        )
        monkeypatch.setattr(
            "src.extensions.ingestion.adapter.resolve_whatsapp_store_path",
            lambda: store_path,
        )

        tool = _make_whatsapp_chats_tool()
        adapter = IngestionAdapter("whatsapp", tool, FakeMcpClient(), tmp_db)
        result = adapter.sync()

        assert result.status == "success"
        rows = tmp_db.query(
            "SELECT sender_name FROM raw_messages WHERE source = 'whatsapp'",
        )
        assert len(rows) == 1
        assert rows[0]["sender_name"] == "+5511999887766"


class TestNormalizePhone:
    """Tests for _normalize_phone helper."""

    def test_strips_formatting(self) -> None:
        from src.extensions.ingestion.adapter import _normalize_phone

        assert _normalize_phone("+55 (11) 99988-7766") == "1999887766"

    def test_extracts_last_10_digits(self) -> None:
        from src.extensions.ingestion.adapter import _normalize_phone

        assert _normalize_phone("554892011083") == "4892011083"

    def test_short_number(self) -> None:
        from src.extensions.ingestion.adapter import _normalize_phone

        assert _normalize_phone("12345") == "12345"


class TestResolveSenderName:
    """Tests for _resolve_sender_name helper."""

    def test_me_returns_me(self) -> None:
        from src.extensions.ingestion.adapter import _resolve_sender_name

        result = _resolve_sender_name(
            "me", is_group=False, chat_name="Alice",
            contact_lookup={},
        )
        assert result == "me"

    def test_direct_jid_lookup(self) -> None:
        from src.extensions.ingestion.adapter import _resolve_sender_name

        result = _resolve_sender_name(
            "14155551234@s.whatsapp.net",
            is_group=False,
            chat_name="14155551234@s.whatsapp.net",
            contact_lookup={"14155551234@s.whatsapp.net": "Alice"},
        )
        assert result == "Alice"

    def test_phone_lookup(self) -> None:
        from src.extensions.ingestion.adapter import _resolve_sender_name

        result = _resolve_sender_name(
            "14155551234@s.whatsapp.net",
            is_group=False,
            chat_name="14155551234@s.whatsapp.net",
            contact_lookup={"4155551234": "Bob"},
        )
        assert result == "Bob"

    def test_lid_unknown(self) -> None:
        from src.extensions.ingestion.adapter import _resolve_sender_name

        result = _resolve_sender_name(
            "85573213663263@lid",
            is_group=True,
            chat_name="Group",
            contact_lookup={},
        )
        assert result == "Unknown"

    def test_chat_name_fallback_for_direct(self) -> None:
        from src.extensions.ingestion.adapter import _resolve_sender_name

        result = _resolve_sender_name(
            "14155551234@s.whatsapp.net",
            is_group=False,
            chat_name="Alice Smith",
            contact_lookup={},
        )
        assert result == "Alice Smith"


class TestIdGeneration:
    def test_deterministic_across_calls(self) -> None:
        """Same input produces same ID."""
        tool = _make_tool()
        client = FakeMcpClient()
        adapter = IngestionAdapter("test-conn", tool, client, None)

        record = {"id": "x", "sender": "a", "content": "b"}
        id1 = adapter._generate_id(record)
        id2 = adapter._generate_id(record)
        assert id1 == id2

    def test_different_inputs_different_ids(self) -> None:
        tool = _make_tool()
        client = FakeMcpClient()
        adapter = IngestionAdapter("test-conn", tool, client, None)

        r1 = {"id": "x"}
        r2 = {"id": "y"}
        assert adapter._generate_id(r1) != adapter._generate_id(r2)


# ---------------------------------------------------------------------------
# TestSyncResultDataclass
# ---------------------------------------------------------------------------


class TestSyncResultDataclass:
    def test_frozen(self) -> None:
        import datetime

        r = SyncResult(
            connector_id="c",
            tool_name="t",
            target_table="tab",
            timestamp=datetime.datetime.now(tz=datetime.timezone.utc),
        )
        with pytest.raises(AttributeError):
            r.status = "error"  # type: ignore[misc]

    def test_default_values(self) -> None:
        import datetime

        r = SyncResult(
            connector_id="c",
            tool_name="t",
            target_table="tab",
            timestamp=datetime.datetime.now(tz=datetime.timezone.utc),
        )
        assert r.rows_fetched == 0
        assert r.status == "success"
        assert r.error is None


class TestToolCallArguments:
    def test_apple_calendar_data_tools_send_limit(self, tmp_db: DatabaseEngine) -> None:
        tool = ToolTemplate(
            tool_name="list_reminders",
            tool_type="data",
            target_table="raw_reminders",
            fields=(
                FieldTemplate(
                    source_name="title",
                    target_column="title",
                    source_type="string",
                    target_type="VARCHAR",
                    sensitivity_tier=1,
                    transform=None,
                ),
            ),
            dedup_key=("id",),
        )
        run_migrations(tmp_db)
        client = FakeMcpClient(records=[])
        adapter = IngestionAdapter("apple-calendar", tool, client, tmp_db)

        captured_args: list[dict[str, Any]] = []

        def fake_native(
            args: dict[str, Any],
        ) -> list[dict[str, Any]]:
            captured_args.append(args)
            return []

        with patch(
            "src.extensions.bridges.apple.server.list_reminders",
            fake_native,
        ):
            adapter.sync()

        assert len(captured_args) == 1
        assert captured_args[0] == {"limit": 200}


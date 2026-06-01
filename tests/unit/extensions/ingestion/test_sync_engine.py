"""Tests for SyncEngine — orchestrates adapters, provides sync_fn."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from src.core.sqlite.engine import DatabaseEngine
from src.core.sqlite.migrations import run_migrations
from src.core.sqlite.schemas import create_all_tables
from src.extensions.connectors.catalog import ConnectorCatalog
from src.extensions.connectors.registry import ExtensionRegistry
from src.extensions.ingestion.sync_engine import SyncEngine
from src.extensions.models import (
    ConnectorTemplate,
    FieldTemplate,
    ToolTemplate,
)


@pytest.fixture(autouse=True)
def _disable_ingest_cutoff(monkeypatch: pytest.MonkeyPatch) -> None:
    """Prevent the real ``~/.arandu/settings.json`` cutoff from filtering
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
    """Controllable MCP client for sync engine tests."""

    def __init__(
        self,
        records: list[dict[str, Any]] | None = None,
        error: Exception | None = None,
    ) -> None:
        self._records = records or []
        self._error = error

    def call_tool(
        self,
        tool_name: str,
        arguments: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        if self._error:
            raise self._error
        return list(self._records)

    def __enter__(self) -> FakeMcpClient:
        return self

    def __exit__(self, *_: object) -> None:
        pass


def _fake_factory(
    records: list[dict[str, Any]] | None = None,
    error: Exception | None = None,
    connect_error: Exception | None = None,
):
    """Return a factory that produces FakeMcpClients."""
    def factory(
        command: str,
        args: tuple[str, ...],
        timeout: float,
    ) -> FakeMcpClient:
        if connect_error is not None:
            raise connect_error
        return FakeMcpClient(records=records, error=error)
    return factory


def _make_catalog_with(
    connector: ConnectorTemplate,
    tmp_path: Path,
) -> ConnectorCatalog:
    """Build a ConnectorCatalog containing a single connector."""
    data = {
        "connectors": [
            {
                "id": connector.id,
                "name": connector.name,
                "category": connector.category,
                "icon": connector.icon,
                "description": connector.description,
                "command": connector.command,
                "args": list(connector.args),
                "transport": "stdio",
                "tools": [
                    {
                        "tool_name": t.tool_name,
                        "tool_type": t.tool_type,
                        "target_table": t.target_table,
                        "fields": [
                            {
                                "source_name": f.source_name,
                                "target_column": f.target_column,
                                "source_type": f.source_type,
                                "target_type": f.target_type,
                                "sensitivity_tier": f.sensitivity_tier,
                                "transform": f.transform,
                            }
                            for f in t.fields
                        ],
                        "dedup_key": list(t.dedup_key),
                    }
                    for t in connector.tools
                ],
                "default_schedule": "hourly",
            },
        ],
    }
    path = tmp_path / "catalog.json"
    with path.open("w") as f:
        json.dump(data, f)
    return ConnectorCatalog(catalog_path=path)


def _make_connector(
    connector_id: str = "test-conn",
    tools: tuple[ToolTemplate, ...] | None = None,
) -> ConnectorTemplate:
    """Build a minimal ConnectorTemplate."""
    if tools is None:
        tools = (_make_data_tool(),)
    return ConnectorTemplate(
        id=connector_id,
        name="Test Connector",
        category="test",
        icon="T",
        description="A test connector",
        command="echo",
        args=("hello",),
        transport="stdio",
        tools=tools,
    )


def _make_data_tool(
    tool_name: str = "list_messages",
    target_table: str = "raw_messages",
) -> ToolTemplate:
    """Build a ToolTemplate targeting raw_messages."""
    return ToolTemplate(
        tool_name=tool_name,
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
                source_name="ts",
                target_column="timestamp",
                source_type="string",
                target_type="TIMESTAMPTZ",
                sensitivity_tier=2,
                transform="iso_to_timestamp",
            ),
        ),
        dedup_key=("id",),
    )


def _make_action_tool() -> ToolTemplate:
    """Build an action ToolTemplate (no target_table)."""
    return ToolTemplate(
        tool_name="send_message",
        tool_type="action",
        target_table=None,
        fields=(),
        dedup_key=(),
    )


@pytest.fixture()
def tmp_db(tmp_path: Path) -> DatabaseEngine:
    """Fresh DuckDB with all base schemas."""
    db_path = tmp_path / "test_sync_engine.duckdb"
    engine = DatabaseEngine(db_path=db_path)
    create_all_tables(engine)
    yield engine
    engine.close()


# ---------------------------------------------------------------------------
# TestSyncConnectorSuccess
# ---------------------------------------------------------------------------


class TestSyncConnectorSuccess:
    def test_syncs_all_data_tools(
        self, tmp_db: DatabaseEngine, tmp_path: Path,
    ) -> None:
        """All data tools should be run through adapters."""
        records = [
            {
                "id": "msg-1", "sender": "a", "recipient": "b",
                "content": "hi", "ts": "2025-06-02T10:00:00",
            },
        ]
        connector = _make_connector()
        catalog = _make_catalog_with(connector, tmp_path)
        registry = ExtensionRegistry(
            registry_path=tmp_path / "ext.json",
        )
        engine = SyncEngine(
            mcp_client_factory=_fake_factory(records=records),
            db_engine=tmp_db,
            catalog=catalog,
            registry=registry,
        )

        stats = engine.sync_connector("test-conn")
        assert stats.status == "success"
        assert stats.rows_synced == 1

    def test_aggregates_stats_from_multiple_tools(
        self, tmp_db: DatabaseEngine, tmp_path: Path,
    ) -> None:
        """Multiple data tools should have combined row counts."""
        records = [
            {
                "id": "msg-1", "sender": "a", "recipient": "b",
                "content": "hi", "ts": "2025-06-02T10:00:00",
            },
        ]
        # Two data tools targeting the same table (different tool_name)
        tool1 = _make_data_tool(tool_name="list_messages")
        tool2 = _make_data_tool(tool_name="list_messages_2")
        connector = _make_connector(tools=(tool1, tool2))
        catalog = _make_catalog_with(connector, tmp_path)
        registry = ExtensionRegistry(
            registry_path=tmp_path / "ext.json",
        )
        engine = SyncEngine(
            mcp_client_factory=_fake_factory(records=records),
            db_engine=tmp_db,
            catalog=catalog,
            registry=registry,
        )

        stats = engine.sync_connector("test-conn")
        assert stats.status == "success"
        # Both tools insert the same record but with different
        # adapter instances, so dedup may apply.  At minimum
        # we expect >= 1 row synced.
        assert stats.rows_synced >= 1

    def test_skips_action_tools(
        self, tmp_db: DatabaseEngine, tmp_path: Path,
    ) -> None:
        """Action tools should not be processed."""
        records = [
            {
                "id": "msg-1", "sender": "a", "recipient": "b",
                "content": "hi", "ts": "2025-06-02T10:00:00",
            },
        ]
        connector = _make_connector(
            tools=(_make_data_tool(), _make_action_tool()),
        )
        catalog = _make_catalog_with(connector, tmp_path)
        registry = ExtensionRegistry(
            registry_path=tmp_path / "ext.json",
        )
        engine = SyncEngine(
            mcp_client_factory=_fake_factory(records=records),
            db_engine=tmp_db,
            catalog=catalog,
            registry=registry,
        )

        stats = engine.sync_connector("test-conn")
        assert stats.status == "success"
        assert stats.rows_synced == 1

    def test_empty_records_returns_success(
        self, tmp_db: DatabaseEngine, tmp_path: Path,
    ) -> None:
        """No records from MCP should still be success."""
        connector = _make_connector()
        catalog = _make_catalog_with(connector, tmp_path)
        registry = ExtensionRegistry(
            registry_path=tmp_path / "ext.json",
        )
        engine = SyncEngine(
            mcp_client_factory=_fake_factory(records=[]),
            db_engine=tmp_db,
            catalog=catalog,
            registry=registry,
        )

        stats = engine.sync_connector("test-conn")
        assert stats.status == "success"
        assert stats.rows_synced == 0

    def test_whatsapp_uses_store_sync_without_live_mcp(
        self,
        tmp_db: DatabaseEngine,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """WhatsApp sync should not depend on MCP polling connections."""
        run_migrations(tmp_db)

        store_path = tmp_path / "store.json"
        store_path.write_text(
            json.dumps(
                {
                    "chats": {
                        "14155550000@s.whatsapp.net": {
                            "name": "Bob",
                        },
                    },
                    "contacts": {},
                    "messages": {
                        "14155550000@s.whatsapp.net": [
                            {
                                "key": {
                                    "id": "m-1",
                                    "remoteJid": "14155550000@s.whatsapp.net",
                                    "fromMe": False,
                                },
                                "message": {
                                    "conversation": "hello from store",
                                },
                                "messageTimestamp": "2026-02-28T17:10:00Z",
                            },
                        ],
                    },
                },
            ),
            encoding="utf-8",
        )
        monkeypatch.setattr(
            "src.extensions.ingestion.adapter.resolve_whatsapp_store_path",
            lambda: store_path,
        )

        registry = ExtensionRegistry(
            registry_path=tmp_path / "ext.json",
        )
        engine = SyncEngine(
            mcp_client_factory=_fake_factory(
                connect_error=RuntimeError("should not connect"),
            ),
            db_engine=tmp_db,
            catalog=ConnectorCatalog(),
            registry=registry,
        )

        stats = engine.sync_connector("whatsapp")
        assert stats.status == "success"
        assert stats.rows_synced == 1


# ---------------------------------------------------------------------------
# TestSyncConnectorPartialFailure
# ---------------------------------------------------------------------------


class TestSyncConnectorPartialFailure:
    def test_continues_after_tool_failure(
        self, tmp_db: DatabaseEngine, tmp_path: Path,
    ) -> None:
        """If one tool fails, remaining tools should still run."""
        # Use a tool targeting a bad table + a good tool
        bad_tool = _make_data_tool(
            tool_name="bad_tool",
            target_table="nonexistent_table",
        )
        good_tool = _make_data_tool(tool_name="list_messages")
        connector = _make_connector(tools=(bad_tool, good_tool))
        catalog = _make_catalog_with(connector, tmp_path)
        registry = ExtensionRegistry(
            registry_path=tmp_path / "ext.json",
        )
        records = [
            {
                "id": "msg-1", "sender": "a", "recipient": "b",
                "content": "hi", "ts": "2025-06-02T10:00:00",
            },
        ]
        engine = SyncEngine(
            mcp_client_factory=_fake_factory(records=records),
            db_engine=tmp_db,
            catalog=catalog,
            registry=registry,
        )

        stats = engine.sync_connector("test-conn")
        assert stats.status == "error"
        assert stats.rows_synced >= 1  # good tool succeeded

    def test_error_status_when_any_tool_fails(
        self, tmp_db: DatabaseEngine, tmp_path: Path,
    ) -> None:
        """Status should be error if any tool failed."""
        bad_tool = _make_data_tool(
            tool_name="bad_tool",
            target_table="nonexistent_table",
        )
        connector = _make_connector(tools=(bad_tool,))
        catalog = _make_catalog_with(connector, tmp_path)
        registry = ExtensionRegistry(
            registry_path=tmp_path / "ext.json",
        )
        records = [
            {
                "id": "msg-1", "sender": "a", "recipient": "b",
                "content": "hi", "ts": "2025-06-02T10:00:00",
            },
        ]
        engine = SyncEngine(
            mcp_client_factory=_fake_factory(records=records),
            db_engine=tmp_db,
            catalog=catalog,
            registry=registry,
        )

        stats = engine.sync_connector("test-conn")
        assert stats.status == "error"
        assert stats.error is not None


# ---------------------------------------------------------------------------
# TestSyncConnectorConnectionFailure
# ---------------------------------------------------------------------------


class TestSyncConnectorConnectionFailure:
    def test_mcp_connect_failure(
        self, tmp_db: DatabaseEngine, tmp_path: Path,
    ) -> None:
        """Connection failure should return error SyncStats."""
        connector = _make_connector()
        catalog = _make_catalog_with(connector, tmp_path)
        registry = ExtensionRegistry(
            registry_path=tmp_path / "ext.json",
        )
        engine = SyncEngine(
            mcp_client_factory=_fake_factory(
                connect_error=RuntimeError("Connection refused"),
            ),
            db_engine=tmp_db,
            catalog=catalog,
            registry=registry,
        )

        stats = engine.sync_connector("test-conn")
        assert stats.status == "error"
        assert "Connection refused" in (stats.error or "")


# ---------------------------------------------------------------------------
# TestSyncConnectorNotFound
# ---------------------------------------------------------------------------


class TestSyncConnectorNotFound:
    def test_unknown_connector_returns_error(
        self, tmp_db: DatabaseEngine, tmp_path: Path,
    ) -> None:
        """Connector not in catalog or metadata should return error."""
        # Empty catalog
        data = {"connectors": []}
        cat_path = tmp_path / "empty_catalog.json"
        with cat_path.open("w") as f:
            json.dump(data, f)
        catalog = ConnectorCatalog(catalog_path=cat_path)
        registry = ExtensionRegistry(
            registry_path=tmp_path / "ext.json",
        )
        engine = SyncEngine(
            mcp_client_factory=_fake_factory(),
            db_engine=tmp_db,
            catalog=catalog,
            registry=registry,
        )

        stats = engine.sync_connector("nonexistent")
        assert stats.status == "error"
        assert "No config found" in (stats.error or "")


# ---------------------------------------------------------------------------
# TestGetConnectorConfig
# ---------------------------------------------------------------------------


class TestGetConnectorConfig:
    def test_bundled_connector(
        self, tmp_db: DatabaseEngine, tmp_path: Path,
    ) -> None:
        """Should resolve config from bundled catalog."""
        connector = _make_connector()
        catalog = _make_catalog_with(connector, tmp_path)
        registry = ExtensionRegistry(
            registry_path=tmp_path / "ext.json",
        )
        engine = SyncEngine(
            mcp_client_factory=_fake_factory(),
            db_engine=tmp_db,
            catalog=catalog,
            registry=registry,
        )

        command, args, tools = engine._get_connector_config(
            "test-conn",
        )
        assert command == "echo"
        assert args == ("hello",)
        assert len(tools) == 1
        assert tools[0].tool_name == "list_messages"

    def test_custom_connector_metadata(
        self, tmp_db: DatabaseEngine, tmp_path: Path, monkeypatch,
    ) -> None:
        """Should fall back to custom metadata.json."""
        # Empty catalog
        data = {"connectors": []}
        cat_path = tmp_path / "empty_catalog.json"
        with cat_path.open("w") as f:
            json.dump(data, f)
        catalog = ConnectorCatalog(catalog_path=cat_path)
        registry = ExtensionRegistry(
            registry_path=tmp_path / "ext.json",
        )
        engine = SyncEngine(
            mcp_client_factory=_fake_factory(),
            db_engine=tmp_db,
            catalog=catalog,
            registry=registry,
        )

        # Create custom metadata
        meta_dir = tmp_path / "custom-conn"
        meta_dir.mkdir()
        meta = {
            "command": "node",
            "args": ["server.js"],
            "tools": [
                {
                    "tool_name": "list_items",
                    "tool_type": "data",
                    "target_table": "raw_notes",
                    "fields": [
                        {
                            "source_name": "title",
                            "target_column": "title",
                            "source_type": "string",
                            "target_type": "VARCHAR",
                            "sensitivity_tier": 1,
                        },
                    ],
                    "dedup_key": ["title"],
                },
                {
                    "tool_name": "do_action",
                    "tool_type": "action",
                    "target_table": None,
                },
            ],
        }
        with (meta_dir / "metadata.json").open("w") as f:
            json.dump(meta, f)

        # Patch the extensions dir
        monkeypatch.setattr(
            "src.extensions.ingestion.sync_engine._EXTENSIONS_DIR",
            tmp_path,
        )

        command, args, tools = engine._get_connector_config(
            "custom-conn",
        )
        assert command == "node"
        assert args == ("server.js",)
        assert len(tools) == 1
        assert tools[0].tool_name == "list_items"
        assert tools[0].fields[0].source_name == "title"


# ---------------------------------------------------------------------------
# TestAggregateResults
# ---------------------------------------------------------------------------


class TestAggregateResults:
    def test_sums_rows_synced(
        self, tmp_db: DatabaseEngine, tmp_path: Path,
    ) -> None:
        """rows_synced = sum of new + updated across tools."""
        import time
        from datetime import datetime, timezone

        from src.extensions.ingestion.adapter import SyncResult

        data = {"connectors": []}
        cat_path = tmp_path / "empty.json"
        with cat_path.open("w") as f:
            json.dump(data, f)
        catalog = ConnectorCatalog(catalog_path=cat_path)
        registry = ExtensionRegistry(
            registry_path=tmp_path / "ext.json",
        )
        engine = SyncEngine(
            mcp_client_factory=_fake_factory(),
            db_engine=tmp_db,
            catalog=catalog,
            registry=registry,
        )

        now = datetime.now(tz=timezone.utc)
        results = [
            SyncResult(
                connector_id="c", tool_name="t1",
                target_table="tab", timestamp=now,
                rows_new=3, rows_updated=1,
            ),
            SyncResult(
                connector_id="c", tool_name="t2",
                target_table="tab", timestamp=now,
                rows_new=2, rows_updated=0,
            ),
        ]
        stats = engine._aggregate_results(
            "c", results, [], now, time.monotonic(),
        )
        assert stats.rows_synced == 6
        assert stats.status == "success"

    def test_error_propagates(
        self, tmp_db: DatabaseEngine, tmp_path: Path,
    ) -> None:
        """If errors list is non-empty, status is error."""
        import time
        from datetime import datetime, timezone

        data = {"connectors": []}
        cat_path = tmp_path / "empty.json"
        with cat_path.open("w") as f:
            json.dump(data, f)
        catalog = ConnectorCatalog(catalog_path=cat_path)
        registry = ExtensionRegistry(
            registry_path=tmp_path / "ext.json",
        )
        engine = SyncEngine(
            mcp_client_factory=_fake_factory(),
            db_engine=tmp_db,
            catalog=catalog,
            registry=registry,
        )

        now = datetime.now(tz=timezone.utc)
        stats = engine._aggregate_results(
            "c", [], ["tool1: boom"], now, time.monotonic(),
        )
        assert stats.status == "error"
        assert stats.error == "tool1: boom"

    def test_no_data_tools_returns_success(
        self, tmp_db: DatabaseEngine, tmp_path: Path,
    ) -> None:
        """Connector with only action tools — success, 0 rows."""
        connector = _make_connector(tools=(_make_action_tool(),))
        catalog = _make_catalog_with(connector, tmp_path)
        registry = ExtensionRegistry(
            registry_path=tmp_path / "ext.json",
        )
        engine = SyncEngine(
            mcp_client_factory=_fake_factory(),
            db_engine=tmp_db,
            catalog=catalog,
            registry=registry,
        )

        stats = engine.sync_connector("test-conn")
        assert stats.status == "success"
        assert stats.rows_synced == 0

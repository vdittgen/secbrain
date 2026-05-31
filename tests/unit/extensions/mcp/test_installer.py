"""Tests for the zero-friction extension installer.

Covers: McpClient, ToolClassifier, ExtensionInstaller, dynamic DDL,
sample data probing, server name derivation, and edge cases.

All external I/O is mocked (subprocess, MCP client, Ollama, DB engine).

sensitivity_tier: N/A (tests)
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from src.extensions.mcp.client import (
    McpClient,
    McpConnectionError,
    McpToolError,
    McpToolInfo,
    _encode_framed,
    _encode_jsonl,
)
from src.extensions.mcp.installer import (
    ExtensionInstaller,
    InstallPreview,
    ToolPreview,
    _build_create_table_ddl,
    _build_probe_args,
    _derive_server_name,
    _make_connector_id,
)
from src.extensions.mcp.tool_classifier import classify_tool

# ---------------------------------------------------------------------------
# Test data helpers
# ---------------------------------------------------------------------------


def _make_tool(
    name: str = "list_items",
    description: str = "Returns a list of items",
    required: list[str] | None = None,
    properties: dict[str, Any] | None = None,
) -> McpToolInfo:
    """Create an McpToolInfo for testing.

    sensitivity_tier: N/A
    """
    schema: dict[str, Any] = {"type": "object"}
    if properties:
        schema["properties"] = properties
    if required:
        schema["required"] = required
    return McpToolInfo(
        name=name,
        description=description,
        input_schema=schema,
    )


def _make_sample_records() -> list[dict[str, Any]]:
    """Sample MCP tool output for a weather service.

    sensitivity_tier: N/A
    """
    return [
        {
            "id": "w1",
            "location": "San Francisco",
            "temperature": 65.2,
            "humidity": 72,
            "conditions": "Partly Cloudy",
            "timestamp": "2025-06-15T10:00:00Z",
        },
        {
            "id": "w2",
            "location": "New York",
            "temperature": 78.5,
            "humidity": 55,
            "conditions": "Clear",
            "timestamp": "2025-06-15T10:00:00Z",
        },
        {
            "id": "w3",
            "location": "London",
            "temperature": 58.1,
            "humidity": 80,
            "conditions": "Overcast",
            "timestamp": "2025-06-15T10:00:00Z",
        },
    ]


def _make_message_records() -> list[dict[str, Any]]:
    """Sample MCP tool output for a messaging service.

    sensitivity_tier: N/A
    """
    return [
        {
            "id": "m1",
            "sender": "alice@example.com",
            "recipient": "bob@example.com",
            "content": "Hey, meeting at 3pm",
            "timestamp": "2025-06-15T14:30:00Z",
            "source": "slack",
        },
        {
            "id": "m2",
            "sender": "carol@example.com",
            "recipient": "bob@example.com",
            "content": "Project update attached",
            "timestamp": "2025-06-15T15:00:00Z",
            "source": "slack",
        },
    ]


def _make_discovered_mapping(
    tool_name: str = "list_items",
    target_table: str = "raw_weather",
    is_new_table: bool = True,
    confidence: float = 0.75,
) -> MagicMock:
    """Create a mock DiscoveredMapping.

    sensitivity_tier: N/A
    """
    from src.extensions.ingestion.schema_discovery import FieldMapping

    mock = MagicMock()
    mock.tool_name = tool_name
    mock.target_table = target_table
    mock.is_new_table = is_new_table
    mock.confidence = confidence
    mock.domain = "general"
    mock.analysis_method = "rules_only"
    mock.dedup_key = ("id",)
    mock.suggested_schedule = "hourly"
    mock.unmapped_fields = ()
    mock.warnings = ()
    mock.fields = (
        FieldMapping(
            source_name="id",
            target_column="id",
            source_type="string",
            target_type="VARCHAR",
            sensitivity_tier=1,
            confidence=0.9,
            tier_source="default",
            transform=None,
            is_new_column=True,
        ),
        FieldMapping(
            source_name="location",
            target_column="location",
            source_type="string",
            target_type="VARCHAR",
            sensitivity_tier=2,
            confidence=0.8,
            tier_source="keyword_match",
            transform=None,
            is_new_column=True,
        ),
        FieldMapping(
            source_name="temperature",
            target_column="temperature",
            source_type="number",
            target_type="DOUBLE",
            sensitivity_tier=1,
            confidence=0.9,
            tier_source="default",
            transform=None,
            is_new_column=True,
        ),
    )
    return mock


@pytest.fixture(autouse=True)
def _isolate_discovery_cache(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Prevent tests from reading/writing real user discovery cache."""
    monkeypatch.setattr(
        "src.extensions.mcp.installer.DEFAULT_DISCOVERY_CACHE_DIR",
        tmp_path / "discovery_cache",
    )


# ---------------------------------------------------------------------------
# TestMcpClient
# ---------------------------------------------------------------------------


class TestMcpClient:
    """Tests for the minimal MCP JSON-RPC 2.0 client.

    sensitivity_tier: N/A
    """

    def test_encode_framed_format(self) -> None:
        """Encoded framed message has Content-Length header and JSON body."""
        payload = {"jsonrpc": "2.0", "id": 1, "method": "test"}
        encoded = _encode_framed(payload)
        header, body = encoded.split(b"\r\n\r\n", 1)
        assert header.startswith(b"Content-Length: ")
        assert json.loads(body) == payload

    def test_encode_framed_length_accurate(self) -> None:
        """Content-Length matches actual body byte count."""
        payload = {"jsonrpc": "2.0", "id": 1, "method": "test"}
        encoded = _encode_framed(payload)
        header, body = encoded.split(b"\r\n\r\n", 1)
        length = int(header.split(b": ")[1])
        assert length == len(body)

    def test_encode_jsonl_format(self) -> None:
        """JSONL encoding produces JSON + newline."""
        payload = {"jsonrpc": "2.0", "id": 1, "method": "test"}
        encoded = _encode_jsonl(payload)
        assert encoded.endswith(b"\n")
        assert json.loads(encoded.strip()) == payload

    @patch("src.extensions.mcp.client.subprocess.Popen")
    @patch("src.extensions.mcp.client._read_message_auto")
    def test_connect_sends_initialize(
        self,
        mock_read_auto: MagicMock,
        mock_popen: MagicMock,
    ) -> None:
        """connect() sends initialize request and processes response."""
        # Set up mock process
        mock_proc = MagicMock()
        mock_popen.return_value = mock_proc

        # Mock stdin/stdout/stderr (binary mode)
        mock_proc.stdin = MagicMock()
        mock_proc.stdout = MagicMock()
        mock_proc.stderr = MagicMock()
        mock_proc.stderr.__iter__ = MagicMock(return_value=iter([]))
        mock_proc.poll.return_value = None

        # Mock _read_message_auto to return initialize response + mode
        mock_read_auto.return_value = (
            {
                "jsonrpc": "2.0",
                "id": 1,
                "result": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "serverInfo": {"name": "test", "version": "1.0"},
                },
            },
            "jsonl",
        )

        client = McpClient("echo", timeout=5.0)
        client.connect()

        # Verify initialize was sent
        assert mock_proc.stdin.write.called
        assert mock_proc.stdin.flush.called

    @patch("src.extensions.mcp.client.subprocess.Popen")
    def test_connect_command_not_found_raises(
        self, mock_popen: MagicMock,
    ) -> None:
        """connect() raises McpConnectionError for missing command."""
        mock_popen.side_effect = FileNotFoundError("not found")
        client = McpClient("nonexistent-cmd")
        with pytest.raises(McpConnectionError, match="Command not found"):
            client.connect()

    def test_close_without_connect(self) -> None:
        """close() is safe to call before connect()."""
        client = McpClient("echo")
        client.close()  # Should not raise

    def test_context_manager_closes_on_exit(self) -> None:
        """__exit__ calls close()."""
        client = McpClient("echo")
        client.close = MagicMock()  # type: ignore[method-assign]
        client.__exit__(None, None, None)
        client.close.assert_called_once()


def _make_reader(data: bytes) -> Any:
    """Create a mock reader that returns data char by char.

    sensitivity_tier: N/A
    """
    decoded = data.decode("utf-8")
    pos = [0]

    def read(n: int = 1) -> str:
        if pos[0] >= len(decoded):
            return ""
        result = decoded[pos[0] : pos[0] + n]
        pos[0] += n
        return result

    return read


# ---------------------------------------------------------------------------
# TestToolClassifier
# ---------------------------------------------------------------------------


class TestToolClassifier:
    """Tests for DATA vs ACTION tool classification.

    sensitivity_tier: N/A
    """

    def test_list_prefix_classified_as_data(self) -> None:
        """Tools with list_ prefix are classified as data."""
        tool = _make_tool(name="list_messages")
        assert classify_tool(tool) == "data"

    def test_get_prefix_classified_as_data(self) -> None:
        """Tools with get_ prefix are classified as data."""
        tool = _make_tool(name="get_weather")
        assert classify_tool(tool) == "data"

    def test_create_prefix_classified_as_action(self) -> None:
        """Tools with create_ prefix are classified as action."""
        tool = _make_tool(name="create_event")
        assert classify_tool(tool) == "action"

    def test_delete_prefix_classified_as_action(self) -> None:
        """Tools with delete_ prefix are classified as action."""
        tool = _make_tool(name="delete_file")
        assert classify_tool(tool) == "action"

    def test_description_returns_classified_as_data(self) -> None:
        """Description keyword 'returns' signals data tool."""
        tool = _make_tool(
            name="weather_forecast",
            description="Returns the weather forecast for a city",
        )
        assert classify_tool(tool) == "data"

    def test_description_sends_classified_as_action(self) -> None:
        """Description keyword 'sends' signals action tool."""
        tool = _make_tool(
            name="notify_user",
            description="Sends a notification to the user",
        )
        assert classify_tool(tool) == "action"

    def test_no_required_params_classified_as_data(self) -> None:
        """Tools with no required params default to data."""
        tool = _make_tool(
            name="current_status",
            description="Shows the current system status",
            properties={"verbose": {"type": "boolean"}},
        )
        assert classify_tool(tool) == "data"

    def test_filter_only_params_classified_as_data(self) -> None:
        """Tools with only filter params are data tools."""
        tool = _make_tool(
            name="items",
            description="Items endpoint",
            required=["limit"],
            properties={
                "limit": {"type": "integer"},
                "offset": {"type": "integer"},
            },
        )
        assert classify_tool(tool) == "data"

    def test_default_classification_is_data(self) -> None:
        """Ambiguous tools default to data (conservative)."""
        tool = _make_tool(
            name="process",
            description="Does something with the data",
            required=["input_data"],
            properties={"input_data": {"type": "string"}},
        )
        # Has non-filter required param, no keyword match — falls through
        # to default "data"
        assert classify_tool(tool) == "data"


# ---------------------------------------------------------------------------
# TestServerNameDerivation
# ---------------------------------------------------------------------------


class TestServerNameDerivation:
    """Tests for server name extraction from command/args.

    sensitivity_tier: N/A
    """

    def test_npm_package_name_extraction(self) -> None:
        """npm-style @scope/mcp-server-name extracts 'name'."""
        name = _derive_server_name(
            "npx", ("-y", "@anthropic/mcp-server-weather"),
        )
        assert name == "weather"

    def test_mcp_prefix_extraction(self) -> None:
        """mcp-server- prefix is stripped."""
        name = _derive_server_name("uvx", ("mcp-server-fetch",))
        assert name == "fetch"

    def test_command_fallback(self) -> None:
        """When args don't match, derive from command."""
        name = _derive_server_name("/usr/local/bin/my-server", ())
        assert name == "my-server"

    def test_user_override_honored(self) -> None:
        """User-provided name overrides derivation."""
        # _derive_server_name is the underlying function;
        # the discover() level uses name= kwarg to override.
        name = _derive_server_name("npx", ("-y", "@foo/mcp-server-bar"))
        assert name == "bar"

    def test_connector_id_generation(self) -> None:
        """Server name is slugified to a connector ID."""
        assert _make_connector_id("weather") == "custom-weather"
        assert _make_connector_id("My Server") == "custom-my-server"
        assert _make_connector_id("file_system") == "custom-file-system"


# ---------------------------------------------------------------------------
# TestBuildProbeArgs
# ---------------------------------------------------------------------------


class TestSampleDataProbing:
    """Tests for building probe arguments from tool schemas.

    sensitivity_tier: N/A
    """

    def test_empty_args_for_no_required(self) -> None:
        """Tools with no required params get empty probe args."""
        tool = _make_tool(required=[], properties={})
        args = _build_probe_args(tool)
        assert args == {}

    def test_limit_param_gets_default(self) -> None:
        """Required 'limit' param gets MAX_SAMPLE_RECORDS value."""
        tool = _make_tool(
            required=["limit"],
            properties={"limit": {"type": "integer"}},
        )
        args = _build_probe_args(tool)
        assert args["limit"] == 5

    def test_query_param_gets_empty_string(self) -> None:
        """Required 'query' param gets empty string."""
        tool = _make_tool(
            required=["query"],
            properties={"query": {"type": "string"}},
        )
        args = _build_probe_args(tool)
        assert args["query"] == ""

    def test_required_params_get_type_defaults(self) -> None:
        """Required non-filter params get type-based defaults."""
        tool = _make_tool(
            required=["name", "count_val", "active"],
            properties={
                "name": {"type": "string"},
                "count_val": {"type": "integer"},
                "active": {"type": "boolean"},
            },
        )
        args = _build_probe_args(tool)
        assert args["name"] == ""
        assert args["count_val"] == 0
        assert args["active"] is False

    def test_optional_limit_added(self) -> None:
        """Optional limit param is added to probe args."""
        tool = _make_tool(
            required=[],
            properties={
                "limit": {"type": "integer"},
                "verbose": {"type": "boolean"},
            },
        )
        args = _build_probe_args(tool)
        assert args.get("limit") == 5


# ---------------------------------------------------------------------------
# TestDynamicDDL
# ---------------------------------------------------------------------------


class TestDynamicDDL:
    """Tests for dynamic CREATE TABLE DDL generation.

    sensitivity_tier: N/A
    """

    def test_ddl_includes_all_fields(self) -> None:
        """Generated DDL includes all discovered fields."""
        from src.extensions.ingestion.schema_discovery import FieldMapping

        fields = (
            FieldMapping(
                source_name="id", target_column="id",
                source_type="string", target_type="VARCHAR",
                sensitivity_tier=1, confidence=0.9,
                tier_source="default", transform=None,
                is_new_column=True,
            ),
            FieldMapping(
                source_name="name", target_column="name",
                source_type="string", target_type="VARCHAR",
                sensitivity_tier=2, confidence=0.8,
                tier_source="keyword_match", transform=None,
                is_new_column=True,
            ),
        )
        ddl = _build_create_table_ddl(
            "raw_test", fields, ("id",), default_tier=2,
        )
        assert "raw_test" in ddl
        assert "id" in ddl
        assert "name" in ddl
        assert "VARCHAR" in ddl

    def test_ddl_has_correct_types(self) -> None:
        """DDL uses DuckDB types from field mappings."""
        from src.extensions.ingestion.schema_discovery import FieldMapping

        fields = (
            FieldMapping(
                source_name="ts", target_column="timestamp_col",
                source_type="string", target_type="TIMESTAMPTZ",
                sensitivity_tier=1, confidence=0.9,
                tier_source="default", transform="iso_to_timestamp",
                is_new_column=True,
            ),
            FieldMapping(
                source_name="val", target_column="value",
                source_type="number", target_type="DOUBLE",
                sensitivity_tier=1, confidence=0.9,
                tier_source="default", transform=None,
                is_new_column=True,
            ),
        )
        ddl = _build_create_table_ddl(
            "raw_metrics", fields, (), default_tier=1,
        )
        assert "TIMESTAMPTZ" in ddl
        assert "DOUBLE" in ddl

    def test_ddl_includes_sensitivity_tier(self) -> None:
        """DDL adds sensitivity_tier column with correct default."""
        from src.extensions.ingestion.schema_discovery import FieldMapping

        fields = (
            FieldMapping(
                source_name="id", target_column="id",
                source_type="string", target_type="VARCHAR",
                sensitivity_tier=3, confidence=0.9,
                tier_source="default", transform=None,
                is_new_column=True,
            ),
        )
        ddl = _build_create_table_ddl(
            "raw_health", fields, ("id",), default_tier=3,
        )
        assert "sensitivity_tier" in ddl
        assert "DEFAULT 3" in ddl

    def test_ddl_handles_primary_key(self) -> None:
        """DDL marks id field as PRIMARY KEY when in dedup_key."""
        from src.extensions.ingestion.schema_discovery import FieldMapping

        fields = (
            FieldMapping(
                source_name="id", target_column="id",
                source_type="string", target_type="VARCHAR",
                sensitivity_tier=1, confidence=0.9,
                tier_source="default", transform=None,
                is_new_column=True,
            ),
        )
        ddl = _build_create_table_ddl(
            "raw_items", fields, ("id",), default_tier=1,
        )
        assert "PRIMARY KEY" in ddl


# ---------------------------------------------------------------------------
# TestExtensionInstaller — discover flow
# ---------------------------------------------------------------------------


class TestExtensionInstaller:
    """Tests for the discover() flow.

    sensitivity_tier: N/A
    """

    @patch("src.extensions.mcp.installer.McpClient")
    @patch("src.extensions.mcp.installer.SchemaDiscoveryAgent")
    def test_discover_happy_path(
        self,
        mock_agent_cls: MagicMock,
        mock_client_cls: MagicMock,
    ) -> None:
        """discover() returns preview with tools and tables."""
        # Set up MCP client mock
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.list_tools.return_value = [
            _make_tool("list_weather", "Returns weather data"),
        ]
        mock_client.call_tool.return_value = _make_sample_records()

        # Set up schema discovery mock
        mock_agent = MagicMock()
        mock_agent_cls.return_value = mock_agent
        mock_agent.discover.return_value = _make_discovered_mapping()

        installer = ExtensionInstaller()
        preview = installer.discover(
            "npx", ("-y", "@test/mcp-server-weather"),
        )

        assert preview.server_name == "weather"
        assert preview.data_tools == 1
        assert len(preview.tools) == 1
        assert preview.tools[0].tool_type == "data"

    @patch("src.extensions.mcp.installer.McpClient")
    @patch("src.extensions.mcp.installer.SchemaDiscoveryAgent")
    def test_discover_with_action_tools(
        self,
        mock_agent_cls: MagicMock,
        mock_client_cls: MagicMock,
    ) -> None:
        """discover() classifies action tools correctly."""
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.list_tools.return_value = [
            _make_tool("list_items", "Returns items"),
            _make_tool("create_item", "Creates an item"),
        ]
        mock_client.call_tool.return_value = _make_sample_records()

        mock_agent = MagicMock()
        mock_agent_cls.return_value = mock_agent
        mock_agent.discover.return_value = _make_discovered_mapping()

        installer = ExtensionInstaller()
        preview = installer.discover("npx", ("-y", "@test/mcp-server-items"))

        assert preview.data_tools == 1
        assert preview.action_tools == 1

    @patch("src.extensions.mcp.installer.McpClient")
    @patch("src.extensions.mcp.installer.SchemaDiscoveryAgent")
    def test_discover_tool_call_failure_graceful(
        self,
        mock_agent_cls: MagicMock,
        mock_client_cls: MagicMock,
    ) -> None:
        """discover() handles tool call failures gracefully."""
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.list_tools.return_value = [
            _make_tool("list_data", "Returns data"),
        ]
        mock_client.call_tool.side_effect = McpToolError("fail")

        installer = ExtensionInstaller()
        preview = installer.discover("npx", ("-y", "@test/mcp-server-fail"))

        # Tool still appears but with low confidence
        assert len(preview.tools) == 1
        assert preview.tools[0].confidence == 0.3

    @patch("src.extensions.mcp.installer.McpClient")
    @patch("src.extensions.mcp.installer.SchemaDiscoveryAgent")
    def test_discover_new_table_detection(
        self,
        mock_agent_cls: MagicMock,
        mock_client_cls: MagicMock,
    ) -> None:
        """discover() detects new tables."""
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.list_tools.return_value = [
            _make_tool("list_weather", "Returns weather"),
        ]
        mock_client.call_tool.return_value = _make_sample_records()

        mock_agent = MagicMock()
        mock_agent_cls.return_value = mock_agent
        mock_agent.discover.return_value = _make_discovered_mapping(
            is_new_table=True, target_table="raw_weather",
        )

        installer = ExtensionInstaller()
        preview = installer.discover("npx", ("-y", "@test/mcp-server-wx"))

        assert "raw_weather" in preview.new_tables

    @patch("src.extensions.mcp.installer.McpClient")
    @patch("src.extensions.mcp.installer.SchemaDiscoveryAgent")
    def test_discover_existing_table_match(
        self,
        mock_agent_cls: MagicMock,
        mock_client_cls: MagicMock,
    ) -> None:
        """discover() identifies matches to existing tables."""
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.list_tools.return_value = [
            _make_tool("list_msgs", "Returns messages"),
        ]
        mock_client.call_tool.return_value = _make_message_records()

        mock_agent = MagicMock()
        mock_agent_cls.return_value = mock_agent
        mock_agent.discover.return_value = _make_discovered_mapping(
            tool_name="list_msgs",
            is_new_table=False,
            target_table="raw_messages",
        )

        installer = ExtensionInstaller()
        preview = installer.discover("npx", ("-y", "@test/mcp-server-chat"))

        assert "raw_messages" in preview.existing_tables

    @patch("src.extensions.mcp.installer.McpClient")
    def test_discover_name_override(
        self,
        mock_client_cls: MagicMock,
    ) -> None:
        """discover() uses user-provided name when given."""
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.list_tools.return_value = []

        installer = ExtensionInstaller()
        preview = installer.discover(
            "npx", ("-y", "@test/mcp-server-foo"),
            name="MyCustomName",
        )

        assert preview.server_name == "MyCustomName"

    @patch("src.extensions.mcp.installer.McpClient")
    @patch("src.extensions.mcp.installer.SchemaDiscoveryAgent")
    def test_discover_cache_hit_skips_reprobe(
        self,
        mock_agent_cls: MagicMock,
        mock_client_cls: MagicMock,
    ) -> None:
        """Second discover() with same command should use cached result."""
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.list_tools.return_value = [
            _make_tool("list_items", "Returns items"),
        ]
        mock_client.call_tool.return_value = _make_sample_records()

        mock_agent = MagicMock()
        mock_agent_cls.return_value = mock_agent
        mock_agent.discover.return_value = _make_discovered_mapping()

        installer = ExtensionInstaller()
        first = installer.discover("npx", ("-y", "@test/mcp-server-items"))
        assert first.data_tools == 1
        assert mock_client_cls.call_count == 1
        assert mock_agent_cls.call_count == 1

        second = installer.discover("npx", ("-y", "@test/mcp-server-items"))
        assert second == first
        # Performance guard: no handshake/probe/analysis on cache hit.
        assert mock_client_cls.call_count == 1
        assert mock_agent_cls.call_count == 1


# ---------------------------------------------------------------------------
# TestConfirmFlow
# ---------------------------------------------------------------------------


class TestConfirmFlow:
    """Tests for the confirm() flow.

    sensitivity_tier: N/A
    """

    def _make_preview(
        self,
        tools: tuple[ToolPreview, ...] | None = None,
    ) -> InstallPreview:
        """Create a test InstallPreview.

        sensitivity_tier: N/A
        """
        if tools is None:
            tools = (
                ToolPreview(
                    tool_name="list_items",
                    tool_type="data",
                    target_table="raw_weather",
                    is_new_table=True,
                    field_count=3,
                    sensitivity_tiers={1: 2, 2: 1},
                    confidence=0.75,
                ),
            )
        return InstallPreview(
            server_name="weather",
            command="npx",
            args=("-y", "@test/mcp-server-weather"),
            tools=tools,
            data_tools=sum(1 for t in tools if t.tool_type == "data"),
            action_tools=sum(
                1 for t in tools if t.tool_type == "action"
            ),
            new_tables=tuple(
                t.target_table
                for t in tools
                if t.is_new_table and t.target_table
            ),
            overall_confidence=0.75,
        )

    def test_confirm_creates_tables(self) -> None:
        """confirm() creates new tables via DDL."""
        mock_db = MagicMock()
        mock_registry = MagicMock()

        installer = ExtensionInstaller(
            db_engine=mock_db, registry=mock_registry,
        )
        # Seed the discovered mapping cache
        installer._last_discovered["list_items"] = (
            _make_discovered_mapping()
        )

        preview = self._make_preview()
        result = installer.confirm(preview)

        assert result.status == "installed"
        assert "raw_weather" in result.tables_created
        mock_db.execute.assert_called_once()

    def test_confirm_registers_connector(self) -> None:
        """confirm() registers the connector in the registry."""
        mock_db = MagicMock()
        mock_registry = MagicMock()

        installer = ExtensionInstaller(
            db_engine=mock_db, registry=mock_registry,
        )
        installer._last_discovered["list_items"] = (
            _make_discovered_mapping()
        )

        preview = self._make_preview()
        result = installer.confirm(preview)

        mock_registry.register.assert_called_once_with(
            "custom-weather",
            tools_count=1,
            command_line="npx -y @test/mcp-server-weather",
            env_values=None,
        )
        assert result.connector_id == "custom-weather"

    def test_confirm_generates_connector_id(self) -> None:
        """confirm() generates slugified connector ID."""
        mock_registry = MagicMock()
        installer = ExtensionInstaller(registry=mock_registry)
        installer._last_discovered["list_items"] = (
            _make_discovered_mapping()
        )

        preview = self._make_preview()
        result = installer.confirm(preview)

        assert result.connector_id == "custom-weather"

    def test_confirm_with_mixed_tools(self) -> None:
        """confirm() handles both data and action tools."""
        mock_db = MagicMock()
        mock_registry = MagicMock()

        installer = ExtensionInstaller(
            db_engine=mock_db, registry=mock_registry,
        )
        installer._last_discovered["list_items"] = (
            _make_discovered_mapping()
        )

        tools = (
            ToolPreview(
                tool_name="list_items",
                tool_type="data",
                target_table="raw_weather",
                is_new_table=True,
                field_count=3,
                confidence=0.75,
            ),
            ToolPreview(
                tool_name="create_item",
                tool_type="action",
            ),
        )
        preview = self._make_preview(tools=tools)
        result = installer.confirm(preview)

        assert result.status == "installed"
        # 1 data + 1 action = 2 registered tools
        assert result.tools_registered == 2

    def test_confirm_error_handling(self) -> None:
        """confirm() returns error result on failure."""
        mock_db = MagicMock()
        mock_db.execute.side_effect = Exception("DB error")
        mock_registry = MagicMock()

        installer = ExtensionInstaller(
            db_engine=mock_db, registry=mock_registry,
        )
        installer._last_discovered["list_items"] = (
            _make_discovered_mapping()
        )

        preview = self._make_preview()
        result = installer.confirm(preview)

        assert result.status == "error"
        assert "DB error" in (result.error or "")

    @patch("src.extensions.mcp.installer.McpClient")
    @patch("src.extensions.mcp.installer.SchemaDiscoveryAgent")
    def test_confirm_hydrates_mappings_from_discovery_cache(
        self,
        mock_agent_cls: MagicMock,
        mock_client_cls: MagicMock,
        tmp_path: Path,
    ) -> None:
        """confirm() should load mappings from persisted discovery cache."""
        cache_dir = tmp_path / "discovery_cache"

        # First installer does discovery and writes cache.
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.list_tools.return_value = [
            _make_tool("list_items", "Returns items"),
        ]
        mock_client.call_tool.return_value = _make_sample_records()

        mock_agent = MagicMock()
        mock_agent_cls.return_value = mock_agent
        mock_agent.discover.return_value = _make_discovered_mapping()

        discover_installer = ExtensionInstaller(cache_dir=cache_dir)
        preview = discover_installer.discover(
            "npx", ("-y", "@test/mcp-server-weather"),
        )

        # New installer instance simulates confirm in a new process.
        mock_db = MagicMock()
        mock_registry = MagicMock()
        confirm_installer = ExtensionInstaller(
            db_engine=mock_db,
            registry=mock_registry,
            cache_dir=cache_dir,
        )
        result = confirm_installer.confirm(preview)

        assert result.status == "installed"
        assert "raw_weather" in result.tables_created
        # Performance guard: no second MCP handshake during confirm.
        assert mock_client_cls.call_count == 1


# ---------------------------------------------------------------------------
# TestEdgeCases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    """Tests for edge cases and error conditions.

    sensitivity_tier: N/A
    """

    @patch("src.extensions.mcp.installer.McpClient")
    def test_server_with_no_tools(
        self,
        mock_client_cls: MagicMock,
    ) -> None:
        """discover() handles server with zero tools."""
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.list_tools.return_value = []

        installer = ExtensionInstaller()
        preview = installer.discover("echo", ())

        assert len(preview.tools) == 0
        assert preview.data_tools == 0
        assert "no tools" in preview.warnings[0].lower()

    @patch("src.extensions.mcp.installer.McpClient")
    def test_all_action_tools(
        self,
        mock_client_cls: MagicMock,
    ) -> None:
        """discover() handles server with only action tools."""
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.list_tools.return_value = [
            _make_tool("create_thing", "Creates a thing"),
            _make_tool("delete_thing", "Deletes a thing"),
        ]

        installer = ExtensionInstaller()
        preview = installer.discover("npx", ("-y", "@test/mcp-actions"))

        assert preview.data_tools == 0
        assert preview.action_tools == 2
        assert len(preview.new_tables) == 0

    @patch("src.extensions.mcp.installer.McpClient")
    def test_mcp_connection_failure(
        self,
        mock_client_cls: MagicMock,
    ) -> None:
        """discover() propagates connection errors."""
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        mock_client.__enter__ = MagicMock(
            side_effect=McpConnectionError("refused"),
        )
        mock_client.__exit__ = MagicMock(return_value=False)

        installer = ExtensionInstaller()
        with pytest.raises(McpConnectionError, match="refused"):
            installer.discover("bad-server", ())

    @patch("src.extensions.mcp.installer.McpClient")
    @patch("src.extensions.mcp.installer.SchemaDiscoveryAgent")
    def test_empty_sample_records(
        self,
        mock_agent_cls: MagicMock,
        mock_client_cls: MagicMock,
    ) -> None:
        """discover() handles tools that return empty results."""
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.list_tools.return_value = [
            _make_tool("list_empty", "Returns nothing"),
        ]
        mock_client.call_tool.return_value = []

        installer = ExtensionInstaller()
        preview = installer.discover("npx", ("-y", "@test/mcp-empty"))

        # Tool appears with low confidence
        assert len(preview.tools) == 1
        assert preview.tools[0].confidence == 0.3

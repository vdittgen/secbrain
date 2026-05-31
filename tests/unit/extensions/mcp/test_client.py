"""Unit tests for MCP client result parsing."""

from __future__ import annotations

from src.extensions.mcp.client import McpClient


class TestCallToolStructuredPayloads:
    """Ensure structured result payload fields are parsed into rows."""

    def test_legacy_calendar_tool_reads_result_events(self) -> None:
        client = McpClient("echo")

        def _fake_call(
            tool_name: str,
            arguments: dict[str, object] | None = None,
        ) -> dict[str, object]:
            _ = tool_name
            _ = arguments
            return {
                "jsonrpc": "2.0",
                "id": 1,
                "result": {
                    "isError": False,
                    "content": [
                        {"type": "text", "text": "Found 1 events."},
                    ],
                    "events": [
                        {
                            "eventIdentifier": "evt-1",
                            "summary": "Team Sync",
                            "startDate": "2026-02-27T10:00:00Z",
                            "endDate": "2026-02-27T11:00:00Z",
                            "isAllDay": False,
                        },
                    ],
                },
            }

        client._call_tool_rpc = _fake_call  # type: ignore[method-assign]
        rows = client.call_tool("list_calendar_events")

        assert len(rows) == 1
        assert rows[0]["id"] == "evt-1"
        assert rows[0]["title"] == "Team Sync"
        assert rows[0]["start_time"] == "2026-02-27T10:00:00Z"
        assert rows[0]["end_time"] == "2026-02-27T11:00:00Z"

    def test_nonlegacy_tool_reads_structured_content_rows(self) -> None:
        client = McpClient("echo")

        def _fake_call(
            tool_name: str,
            arguments: dict[str, object] | None = None,
        ) -> dict[str, object]:
            _ = tool_name
            _ = arguments
            return {
                "jsonrpc": "2.0",
                "id": 1,
                "result": {
                    "isError": False,
                    "content": [
                        {"type": "text", "text": "ok"},
                    ],
                    "structuredContent": [
                        {"id": "row-1", "value": 123},
                    ],
                },
            }

        client._call_tool_rpc = _fake_call  # type: ignore[method-assign]
        rows = client.call_tool("some_tool")

        assert rows == [{"id": "row-1", "value": 123}]

    def test_legacy_reminders_drops_placeholder_text_only_rows(self) -> None:
        client = McpClient("echo")

        def _fake_call(
            tool_name: str,
            arguments: dict[str, object] | None = None,
        ) -> dict[str, object]:
            _ = tool_name
            _ = arguments
            return {
                "jsonrpc": "2.0",
                "id": 1,
                "result": {
                    "isError": False,
                    "content": [
                        {"type": "text", "text": "Found 0 lists and 0 reminders."},
                    ],
                },
            }

        client._call_tool_rpc = _fake_call  # type: ignore[method-assign]
        rows = client.call_tool("list_reminders")

        assert rows == []

    def test_legacy_calendar_drops_known_dummy_events(self) -> None:
        client = McpClient("echo")

        def _fake_call(
            tool_name: str,
            arguments: dict[str, object] | None = None,
        ) -> dict[str, object]:
            _ = tool_name
            _ = arguments
            return {
                "jsonrpc": "2.0",
                "id": 1,
                "result": {
                    "isError": False,
                    "events": [
                        {
                            "eventIdentifier": "dummy-event-1",
                            "summary": (
                                "No events available -"
                                " Calendar operations too slow"
                            ),
                            "startDate": "2026-02-27T10:00:00Z",
                            "endDate": "2026-02-27T11:00:00Z",
                            "notes": (
                                "Calendar.app AppleScript queries are"
                                " notoriously slow and unreliable"
                            ),
                        },
                    ],
                },
            }

        client._call_tool_rpc = _fake_call  # type: ignore[method-assign]
        rows = client.call_tool("list_calendar_events")

        assert rows == []

    def test_legacy_whatsapp_normalizes_recent_chats_payload(self) -> None:
        client = McpClient("echo")

        def _fake_call(
            tool_name: str,
            arguments: dict[str, object] | None = None,
        ) -> dict[str, object]:
            _ = arguments
            if tool_name == "list_chats":
                return {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "error": {"message": "Unknown tool: list_chats"},
                }
            if tool_name == "get_recent_chats":
                return {
                    "jsonrpc": "2.0",
                    "id": 2,
                    "result": {
                        "isError": False,
                        "content": [
                            {
                                "type": "json",
                                "json": [
                                    {
                                        "id": "14155551234",
                                        "name": "Alice",
                                        "lastMessage": "hey there",
                                        "lastMessageTime": 1700000000,
                                        "isGroup": False,
                                    },
                                ],
                            },
                        ],
                    },
                }
            raise AssertionError(f"unexpected tool call: {tool_name}")

        client._call_tool_rpc = _fake_call  # type: ignore[method-assign]
        rows = client.call_tool("list_chats")

        assert len(rows) == 1
        assert rows[0]["id"] == "14155551234"
        assert rows[0]["sender"] == "Alice"
        assert rows[0]["recipient"] == "Alice"
        assert rows[0]["content"] == "hey there"
        assert rows[0]["chat_name"] == "Alice"
        assert rows[0]["is_group"] is False
        assert isinstance(rows[0]["timestamp"], str)

    def test_legacy_whatsapp_drops_plain_text_error_rows(self) -> None:
        client = McpClient("echo")

        def _fake_call(
            tool_name: str,
            arguments: dict[str, object] | None = None,
        ) -> dict[str, object]:
            _ = arguments
            if tool_name == "list_chats":
                return {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "error": {"message": "Unknown tool: list_chats"},
                }
            if tool_name == "get_recent_chats":
                return {
                    "jsonrpc": "2.0",
                    "id": 2,
                    "result": {
                        "isError": False,
                        "content": [
                            {"type": "text", "text": "Error: Invalid time value"},
                        ],
                    },
                }
            raise AssertionError(f"unexpected tool call: {tool_name}")

        client._call_tool_rpc = _fake_call  # type: ignore[method-assign]
        rows = client.call_tool("list_chats")

        assert rows == []


class TestFlattenNestedRecordsResilience:
    """Defensive: an MCP server occasionally returns a mixed list with
    raw strings interleaved with dict records. The flattener must not
    crash with ``'str' object has no attribute 'get'``."""

    def test_string_in_records_is_skipped(self) -> None:
        from src.extensions.mcp.client import _flatten_nested_records

        records = [
            {"chats": [{"id": "1"}]},
            "noise string that should be skipped",
            {"id": "2"},
        ]
        out = _flatten_nested_records(records, ("chats",))
        # Skipped raw string, kept the rest.
        assert {"id": "1"} in out
        assert {"id": "2"} in out
        assert all(isinstance(r, dict) for r in out)

    def test_only_strings_does_not_raise(self) -> None:
        from src.extensions.mcp.client import _flatten_nested_records

        assert _flatten_nested_records(["a", "b"], ("k",)) == []


class TestCallToolErrorShape:
    """JSON-RPC says ``error`` is a dict, but real servers sometimes
    emit it as a bare string. ``call_tool`` must surface that as an
    :class:`McpToolError` instead of crashing with
    ``'str' object has no attribute 'get'``."""

    def test_string_error_becomes_mcp_tool_error(self) -> None:
        from src.extensions.mcp.client import McpToolError

        client = McpClient("echo")

        def _fake_call(
            tool_name: str,
            arguments: dict[str, object] | None = None,
        ) -> dict[str, object]:
            _ = tool_name, arguments
            return {
                "type": "error",
                "id": None,
                "error": "Unknown command: undefined",
            }

        client._call_tool_rpc = _fake_call  # type: ignore[method-assign]
        try:
            client.call_tool("send_message", {"to": "+5511", "text": "hi"})
        except McpToolError as exc:
            assert "Unknown command" in str(exc)
            return
        msg = "Expected McpToolError"
        raise AssertionError(msg)

    def test_dict_error_still_extracts_message(self) -> None:
        from src.extensions.mcp.client import McpToolError

        client = McpClient("echo")

        def _fake_call(
            tool_name: str,
            arguments: dict[str, object] | None = None,
        ) -> dict[str, object]:
            _ = tool_name, arguments
            return {
                "jsonrpc": "2.0", "id": 1,
                "error": {"code": -32603, "message": "boom"},
            }

        client._call_tool_rpc = _fake_call  # type: ignore[method-assign]
        try:
            client.call_tool("noop")
        except McpToolError as exc:
            assert "boom" in str(exc)
            return
        msg = "Expected McpToolError"
        raise AssertionError(msg)


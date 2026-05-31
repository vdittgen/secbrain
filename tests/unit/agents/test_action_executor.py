"""Unit tests for the ActionExecutor — MCP action execution."""

from __future__ import annotations

from typing import Any

import pytest
from src.agents.action_executor import ActionExecutor, ActionResult
from src.extensions.mcp.client import (
    McpConnectionError,
    McpTimeoutError,
    McpToolError,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class FakeMcpClient:
    """Controllable MCP client for executor tests."""

    def __init__(
        self,
        result: list[dict[str, Any]] | None = None,
        error: Exception | None = None,
    ) -> None:
        self._result = result or []
        self._error = error
        self.call_count = 0
        self.last_tool: str | None = None
        self.last_args: dict[str, Any] | None = None

    def __enter__(self) -> FakeMcpClient:
        if isinstance(self._error, (McpConnectionError, McpTimeoutError)):
            raise self._error
        return self

    def __exit__(self, exc_type, exc, tb) -> None:  # noqa: ANN001
        return None

    def call_tool(
        self,
        tool_name: str,
        arguments: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        self.call_count += 1
        self.last_tool = tool_name
        self.last_args = arguments
        if isinstance(self._error, McpToolError):
            raise self._error
        if isinstance(self._error, Exception) and not isinstance(
            self._error, (McpConnectionError, McpTimeoutError),
        ):
            raise self._error
        return list(self._result)


def _make_executor(
    fake: FakeMcpClient | None = None,
) -> tuple[ActionExecutor, FakeMcpClient]:
    """Create an executor with a fake MCP client."""
    client = fake or FakeMcpClient()

    def factory(
        command: str,
        args: tuple[str, ...],
        timeout: float,
    ) -> FakeMcpClient:
        return client

    executor = ActionExecutor(
        mcp_client_factory=factory,
        mcp_timeout=10.0,
    )
    return executor, client


# ---------------------------------------------------------------------------
# TestExecuteSuccess
# ---------------------------------------------------------------------------


class TestExecuteSuccess:
    def test_returns_success_result(self) -> None:
        """Successful tool call should return status='success'."""
        fake = FakeMcpClient(result=[{"id": "evt-1", "title": "Meeting"}])
        executor, _ = _make_executor(fake)

        result = executor.execute(
            connector_id="apple-calendar",
            command="npx",
            args=("-y", "@mcp/cal"),
            tool_name="create_event",
            arguments={"title": "Meeting", "date": "2025-07-01"},
            proposal_id="test-123",
        )

        assert isinstance(result, ActionResult)
        assert result.status == "success"
        assert result.proposal_id == "test-123"
        assert result.error is None

    def test_includes_raw_result(self) -> None:
        """Raw MCP result should be included."""
        raw = [{"id": "evt-1"}]
        fake = FakeMcpClient(result=raw)
        executor, _ = _make_executor(fake)

        result = executor.execute(
            connector_id="cal",
            command="npx",
            args=(),
            tool_name="create_event",
            arguments={},
            proposal_id="p-1",
        )

        assert result.raw_result == raw

    def test_calls_correct_tool(self) -> None:
        """Should pass tool_name and arguments to call_tool."""
        fake = FakeMcpClient(result=[])
        executor, client = _make_executor(fake)

        executor.execute(
            connector_id="msg",
            command="npx",
            args=("-y", "@mcp/msg"),
            tool_name="send_message",
            arguments={"to": "Alice", "body": "Hello"},
            proposal_id="p-2",
        )

        assert client.last_tool == "send_message"
        assert client.last_args == {"to": "Alice", "body": "Hello"}
        assert client.call_count == 1

    def test_summarizes_with_title_field(self) -> None:
        """Result with 'title' field should appear in output."""
        fake = FakeMcpClient(result=[{"title": "Team Standup"}])
        executor, _ = _make_executor(fake)

        result = executor.execute(
            connector_id="cal",
            command="npx",
            args=(),
            tool_name="create_event",
            arguments={},
            proposal_id="p-3",
        )

        assert "Team Standup" in result.output

    def test_summarizes_empty_result(self) -> None:
        """Empty result should still report success."""
        fake = FakeMcpClient(result=[])
        executor, _ = _make_executor(fake)

        result = executor.execute(
            connector_id="cal",
            command="npx",
            args=(),
            tool_name="create_event",
            arguments={},
            proposal_id="p-4",
        )

        assert result.status == "success"
        assert "successfully" in result.output.lower()


# ---------------------------------------------------------------------------
# TestExecuteErrors
# ---------------------------------------------------------------------------


class TestExecuteErrors:
    def test_mcp_tool_error(self) -> None:
        """McpToolError should return status='error'."""
        fake = FakeMcpClient(error=McpToolError("Tool failed"))
        executor, _ = _make_executor(fake)

        result = executor.execute(
            connector_id="cal",
            command="npx",
            args=(),
            tool_name="create_event",
            arguments={},
            proposal_id="p-err-1",
        )

        assert result.status == "error"
        assert "Tool failed" in (result.error or "")

    def test_mcp_connection_error(self) -> None:
        """McpConnectionError should return status='error'."""
        fake = FakeMcpClient(error=McpConnectionError("Refused"))
        executor, _ = _make_executor(fake)

        result = executor.execute(
            connector_id="cal",
            command="npx",
            args=(),
            tool_name="create_event",
            arguments={},
            proposal_id="p-err-2",
        )

        assert result.status == "error"
        assert "Refused" in (result.error or "")

    def test_mcp_timeout_error(self) -> None:
        """McpTimeoutError should return status='error'."""
        fake = FakeMcpClient(error=McpTimeoutError("Timed out"))
        executor, _ = _make_executor(fake)

        result = executor.execute(
            connector_id="cal",
            command="npx",
            args=(),
            tool_name="create_event",
            arguments={},
            proposal_id="p-err-3",
        )

        assert result.status == "error"
        assert "Timed out" in (result.error or "")


# ---------------------------------------------------------------------------
# TestActionResultDataclass
# ---------------------------------------------------------------------------


class TestWhatsAppSendRouting:
    """WhatsApp sends bypass MCP and route via the listener outbox.

    The catalog's whatsapp ``command`` is the listener itself (not
    an MCP server), so a real tools/call request never reaches the
    Baileys socket. ActionExecutor must short-circuit and call the
    outbox IPC instead.
    """

    def test_routes_through_listener_outbox(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        captured: dict[str, Any] = {}

        def fake_send(
            to: str, message: str, timeout_seconds: float,
        ) -> dict[str, Any]:
            captured["to"] = to
            captured["message"] = message
            captured["timeout"] = timeout_seconds
            return {"status": "sent", "message_id": "wamid.XYZ"}

        monkeypatch.setattr(
            "src.extensions.bridges.whatsapp.listener."
            "send_text_via_running_listener",
            fake_send,
        )
        fake = FakeMcpClient()
        executor, client = _make_executor(fake)
        result = executor.execute(
            connector_id="whatsapp",
            command="node",
            args=("src/extensions/bridges/whatsapp/node/client.js",),
            tool_name="send_message",
            arguments={"to": "+5511999991234", "text": "Bom dia"},
            proposal_id="wp-1",
        )

        assert result.status == "success"
        assert result.error is None
        # MCP path must NOT be used for WhatsApp send.
        assert client.call_count == 0
        # Phone formatted as a Baileys JID.
        assert captured["to"] == "5511999991234@s.whatsapp.net"
        assert captured["message"] == "Bom dia"

    def test_missing_to_returns_error(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(
            "src.extensions.bridges.whatsapp.listener."
            "send_text_via_running_listener",
            lambda **_kw: {"status": "sent"},
        )
        executor, _ = _make_executor()
        result = executor.execute(
            connector_id="whatsapp", command="node", args=(),
            tool_name="send_message",
            arguments={"text": "hi"},
            proposal_id="wp-2",
        )
        assert result.status == "error"
        assert "missing" in (result.output or "").lower()

    def test_listener_not_running_surfaces_clearly(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(
            "src.extensions.bridges.whatsapp.listener."
            "send_text_via_running_listener",
            lambda **_kw: None,
        )
        executor, _ = _make_executor()
        result = executor.execute(
            connector_id="whatsapp", command="node", args=(),
            tool_name="send_message",
            arguments={"to": "+5511", "text": "hi"},
            proposal_id="wp-3",
        )
        assert result.status == "error"
        assert "listener" in (result.output or "").lower()

    def test_reports_resolved_jid_when_listener_rewrites_it(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """If the listener rewrote the JID (Brazilian mobile-9 quirk
        resolved via onWhatsApp), the success output should reflect
        the actual destination — not the original raw 'to'."""
        monkeypatch.setattr(
            "src.extensions.bridges.whatsapp.listener."
            "send_text_via_running_listener",
            lambda *, to, message, timeout_seconds: {
                "status": "sent",
                "message_id": "wamid.ZZZ",
                # Original "to" was the +9 form; Baileys resolved it
                # to the legacy 8-digit subscriber.
                "resolved_jid": "555196669496@s.whatsapp.net",
            },
        )
        executor, _ = _make_executor()
        result = executor.execute(
            connector_id="whatsapp", command="node", args=(),
            tool_name="send_message",
            arguments={"to": "+5551996669496", "text": "Bom dia"},
            proposal_id="wp-resolve",
        )
        assert result.status == "success"
        assert "555196669496" in result.output
        assert result.raw_result[0]["to"] == "555196669496@s.whatsapp.net"

    def test_accepts_body_as_alias_for_text(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        captured: dict[str, Any] = {}
        monkeypatch.setattr(
            "src.extensions.bridges.whatsapp.listener."
            "send_text_via_running_listener",
            lambda *, to, message, timeout_seconds: (
                captured.update({"message": message})
                or {"status": "sent"}
            ),
        )
        executor, _ = _make_executor()
        result = executor.execute(
            connector_id="whatsapp", command="node", args=(),
            tool_name="send_message",
            arguments={"to": "+5511", "body": "from body alias"},
            proposal_id="wp-4",
        )
        assert result.status == "success"
        assert captured["message"] == "from body alias"


class TestActionResultDataclass:
    def test_frozen(self) -> None:
        r = ActionResult(
            proposal_id="p",
            status="success",
            output="ok",
        )
        with pytest.raises(AttributeError):
            r.status = "error"  # type: ignore[misc]

    def test_default_values(self) -> None:
        r = ActionResult(
            proposal_id="p",
            status="success",
            output="ok",
        )
        assert r.raw_result == []
        assert r.error is None

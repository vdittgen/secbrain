"""Unit tests for WhatsAppClient Python wrapper.

Tests the subprocess management, JSONL protocol, and error handling
without requiring a real Node.js process or Baileys connection.

sensitivity_tier: N/A — test infrastructure
"""

from __future__ import annotations

import json
import subprocess
import threading
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from src.extensions.bridges.whatsapp.client import (
    WhatsAppClient,
    WhatsAppClientError,
    WhatsAppConnectTimeoutError,
    WhatsAppQRRequiredError,
    WhatsAppSendError,
)

# ================================================================
# Helpers
# ================================================================


class _BlockingStdout:
    """Iterator that yields lines then blocks until ``release()`` is called.

    This simulates a real subprocess stdout where the pipe stays open
    until the process terminates.
    """

    def __init__(self, lines: list[bytes]) -> None:
        self._lines = list(lines)
        self._stop = threading.Event()

    def __iter__(self) -> _BlockingStdout:
        return self

    def __next__(self) -> bytes:
        if self._lines:
            return self._lines.pop(0)
        # Block until test releases (simulates pipe staying open)
        self._stop.wait(timeout=10.0)
        raise StopIteration

    def release(self) -> None:
        """Unblock the iterator so the reader thread can exit."""
        self._stop.set()


class FakeProcess:
    """Simulates a subprocess.Popen for WhatsAppClient tests.

    Write JSONL lines into ``stdout_lines`` before calling ``connect()``
    to control what the reader thread sees.  Each line is yielded as
    ``b"json_line\\n"`` matching real subprocess pipe behavior.

    Set ``blocking=True`` (default) to keep stdout open after all lines
    are consumed — this prevents ``_reader_loop`` from clearing
    ``_connected``.  Call ``stdout.release()`` in test cleanup.
    """

    def __init__(
        self,
        stdout_lines: list[str] | None = None,
        *,
        returncode: int | None = None,
        blocking: bool = True,
    ) -> None:
        self._stdout_lines = stdout_lines or []
        self.returncode = returncode
        self.pid = 12345

        byte_lines = [
            (line + "\n").encode("utf-8") for line in self._stdout_lines
        ]
        self.stdin = MagicMock()
        if blocking:
            self.stdout = _BlockingStdout(byte_lines)
        else:
            self.stdout = byte_lines
        self.stderr: list[bytes] = []

    def poll(self) -> int | None:
        return self.returncode

    def wait(self, timeout: float | None = None) -> int:
        return self.returncode or 0


def _make_ready_process(jid: str = "554892011083") -> FakeProcess:
    """Return a FakeProcess that emits a ready event."""
    return FakeProcess(
        stdout_lines=[json.dumps({"type": "ready", "jid": jid})],
    )


def _make_qr_process(qr_data: str = "2@test_qr_data") -> FakeProcess:
    """Return a FakeProcess that emits a QR event."""
    return FakeProcess(
        stdout_lines=[json.dumps({"type": "qr", "qr": qr_data})],
    )


# ================================================================
# Exception classes
# ================================================================


class TestExceptions:
    """Verify exception hierarchy and attributes."""

    def test_base_error_is_runtime(self) -> None:
        assert issubclass(WhatsAppClientError, RuntimeError)

    def test_qr_error_carries_data(self) -> None:
        err = WhatsAppQRRequiredError("2@abc123")
        assert err.qr_data == "2@abc123"
        assert "QR pairing required" in str(err)

    def test_connect_timeout_error(self) -> None:
        err = WhatsAppConnectTimeoutError("timed out")
        assert isinstance(err, WhatsAppClientError)

    def test_send_error(self) -> None:
        err = WhatsAppSendError("delivery failed")
        assert isinstance(err, WhatsAppClientError)


# ================================================================
# Initialization
# ================================================================


class TestInit:
    """Constructor and attribute tests."""

    def test_default_script_path(self, tmp_path: Path) -> None:
        client = WhatsAppClient(auth_dir=tmp_path)
        assert client._auth_dir == tmp_path
        assert client._timeout == 45.0
        assert client._proc is None
        assert client.jid is None
        assert client._closed is False

    def test_custom_timeout(self, tmp_path: Path) -> None:
        client = WhatsAppClient(auth_dir=tmp_path, timeout=10.0)
        assert client._timeout == 10.0

    def test_custom_script(self, tmp_path: Path) -> None:
        script = tmp_path / "custom.js"
        client = WhatsAppClient(
            auth_dir=tmp_path, node_script=script,
        )
        assert client._script == script


# ================================================================
# Connect lifecycle
# ================================================================


class TestConnect:
    """Test the connect() method with various process behaviors."""

    def test_connect_success_sets_jid(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Successful connect() sets jid and is_connected."""
        proc = _make_ready_process("554892011083")
        monkeypatch.setattr(
            "src.extensions.bridges.whatsapp.client.shutil.which",
            lambda _name: "/usr/local/bin/node",
        )
        monkeypatch.setattr(
            subprocess, "Popen", lambda *a, **kw: proc,
        )
        monkeypatch.setattr(
            "src.extensions.bridges.whatsapp.client.os.killpg",
            lambda *a: None,
        )

        client = WhatsAppClient(auth_dir=tmp_path, timeout=5.0)
        monkeypatch.setattr(client, "_ensure_npm_installed", lambda: None)
        try:
            client.connect()
            assert client.jid == "554892011083"
            assert client.is_connected
        finally:
            proc.stdout.release()
            client._closed = True

    def test_connect_raises_on_qr(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """QR event raises WhatsAppQRRequiredError."""
        proc = _make_qr_process("2@test_qr_code")
        monkeypatch.setattr(
            "src.extensions.bridges.whatsapp.client.shutil.which",
            lambda _name: "/usr/local/bin/node",
        )
        monkeypatch.setattr(
            subprocess, "Popen", lambda *a, **kw: proc,
        )
        monkeypatch.setattr(
            "src.extensions.bridges.whatsapp.client.os.killpg",
            lambda *a: None,
        )

        client = WhatsAppClient(auth_dir=tmp_path, timeout=5.0)
        monkeypatch.setattr(client, "_ensure_npm_installed", lambda: None)

        try:
            with pytest.raises(WhatsAppQRRequiredError) as exc_info:
                client.connect()
            assert exc_info.value.qr_data == "2@test_qr_code"
        finally:
            proc.stdout.release()
            client._closed = True

    def test_connect_raises_on_process_exit(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Process exit during connect raises WhatsAppClientError."""
        proc = FakeProcess(
            stdout_lines=[], returncode=1, blocking=False,
        )
        monkeypatch.setattr(
            "src.extensions.bridges.whatsapp.client.shutil.which",
            lambda _name: "/usr/local/bin/node",
        )
        monkeypatch.setattr(
            subprocess, "Popen", lambda *a, **kw: proc,
        )

        client = WhatsAppClient(auth_dir=tmp_path, timeout=2.0)
        monkeypatch.setattr(client, "_ensure_npm_installed", lambda: None)

        with pytest.raises(WhatsAppClientError, match="exited with code 1"):
            client.connect()

    def test_connect_raises_when_no_node(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Missing node binary raises WhatsAppClientError."""
        monkeypatch.setattr(
            "src.extensions.bridges.whatsapp.client.shutil.which",
            lambda _name: None,
        )

        client = WhatsAppClient(auth_dir=tmp_path)
        monkeypatch.setattr(client, "_ensure_npm_installed", lambda: None)

        with pytest.raises(WhatsAppClientError, match="not found"):
            client.connect()

    def test_connect_noop_when_already_connected(
        self, tmp_path: Path,
    ) -> None:
        """Calling connect() twice is a no-op."""
        client = WhatsAppClient(auth_dir=tmp_path, timeout=5.0)
        # Simulate already connected
        client._proc = MagicMock()
        client._connected.set()

        # Second call should be a no-op (proc already set)
        client.connect()
        assert client.is_connected


# ================================================================
# Close
# ================================================================


class TestClose:
    """Test close() and context manager."""

    def test_close_noop_before_connect(self, tmp_path: Path) -> None:
        """close() on unused client should not raise."""
        client = WhatsAppClient(auth_dir=tmp_path)
        client.close()  # Should not raise
        assert client._closed is True

    def test_close_idempotent(self, tmp_path: Path) -> None:
        """Calling close() twice is safe."""
        client = WhatsAppClient(auth_dir=tmp_path)
        client.close()
        client.close()  # Should not raise

    def test_context_manager(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Context manager calls connect() and close()."""
        proc = _make_ready_process()
        monkeypatch.setattr(
            "src.extensions.bridges.whatsapp.client.shutil.which",
            lambda _name: "/usr/local/bin/node",
        )
        monkeypatch.setattr(
            subprocess, "Popen", lambda *a, **kw: proc,
        )
        monkeypatch.setattr(
            "src.extensions.bridges.whatsapp.client.os.killpg",
            lambda *a: None,
        )

        client = WhatsAppClient(auth_dir=tmp_path, timeout=5.0)
        monkeypatch.setattr(client, "_ensure_npm_installed", lambda: None)

        with client as c:
            assert c is client
            assert c.is_connected
            # Release blocking stdout so reader thread exits cleanly
            proc.stdout.release()

        assert client._closed is True


# ================================================================
# Send command
# ================================================================


class TestSendMessage:
    """Test send_message() and internal _send_command()."""

    def test_send_message_success(self, tmp_path: Path) -> None:
        """Successful send returns data with message_id."""
        client = WhatsAppClient(auth_dir=tmp_path)

        # Simulate a connected client with a writable stdin
        mock_stdin = MagicMock()
        mock_proc = MagicMock()
        mock_proc.stdin = mock_stdin
        mock_proc.poll.return_value = None
        client._proc = mock_proc
        client._connected.set()

        # Simulate response arriving in background
        def _fake_response() -> None:
            """Wait for the command to register, then deliver response."""
            import time
            for _ in range(50):
                with client._lock:
                    if client._pending:
                        req_id = next(iter(client._pending))
                        client._responses[req_id] = {
                            "type": "response",
                            "id": req_id,
                            "ok": True,
                            "data": {"message_id": "3AA_test_123"},
                        }
                        client._pending[req_id].set()
                        return
                time.sleep(0.01)

        t = threading.Thread(target=_fake_response, daemon=True)
        t.start()

        result = client.send_message(
            "5511999@s.whatsapp.net", "Hello test",
        )
        t.join(timeout=2)

        assert result["message_id"] == "3AA_test_123"

        # Verify command was written to stdin
        mock_stdin.write.assert_called_once()
        written = mock_stdin.write.call_args[0][0]
        cmd = json.loads(written.decode("utf-8"))
        assert cmd["cmd"] == "send"
        assert cmd["to"] == "5511999@s.whatsapp.net"
        assert cmd["text"] == "Hello test"

    def test_send_message_failure_raises(self, tmp_path: Path) -> None:
        """Failed send raises WhatsAppSendError."""
        client = WhatsAppClient(auth_dir=tmp_path)

        mock_proc = MagicMock()
        mock_proc.stdin = MagicMock()
        mock_proc.poll.return_value = None
        client._proc = mock_proc
        client._connected.set()

        def _fake_error_response() -> None:
            import time
            for _ in range(50):
                with client._lock:
                    if client._pending:
                        req_id = next(iter(client._pending))
                        client._responses[req_id] = {
                            "type": "error",
                            "id": req_id,
                            "ok": False,
                            "error": "Not connected",
                        }
                        client._pending[req_id].set()
                        return
                time.sleep(0.01)

        t = threading.Thread(target=_fake_error_response, daemon=True)
        t.start()

        with pytest.raises(WhatsAppSendError, match="Not connected"):
            client.send_message("5511999@s.whatsapp.net", "Hello")
        t.join(timeout=2)

    def test_send_raises_when_not_connected(self, tmp_path: Path) -> None:
        """send_message() before connect() raises error."""
        client = WhatsAppClient(auth_dir=tmp_path)
        with pytest.raises(WhatsAppClientError, match="not connected"):
            client.send_message("5511999@s.whatsapp.net", "Hello")


# ================================================================
# Reader thread
# ================================================================


class TestReaderThread:
    """Test _reader_loop event parsing and dispatch."""

    def test_reader_processes_message_events(
        self, tmp_path: Path,
    ) -> None:
        """Non-response events should go into the event queue."""
        client = WhatsAppClient(auth_dir=tmp_path)

        msg_event = json.dumps({
            "type": "message",
            "jid": "5511999@s.whatsapp.net",
            "msg_id": "ABC123",
            "text": "Hello",
        })

        mock_proc = MagicMock()
        mock_proc.stdout = [(msg_event + "\n").encode("utf-8")]
        client._proc = mock_proc

        client._reader_loop()

        assert not client._event_queue.empty()
        event = client._event_queue.get_nowait()
        assert event["type"] == "message"
        assert event["msg_id"] == "ABC123"

    def test_reader_matches_responses(self, tmp_path: Path) -> None:
        """Responses should be matched to pending commands."""
        client = WhatsAppClient(auth_dir=tmp_path)

        req_id = "test_req_001"
        pending_event = threading.Event()
        client._pending[req_id] = pending_event

        response = json.dumps({
            "type": "response",
            "id": req_id,
            "ok": True,
            "data": {"connected": True},
        })

        mock_proc = MagicMock()
        mock_proc.stdout = [(response + "\n").encode("utf-8")]
        client._proc = mock_proc

        client._reader_loop()

        assert pending_event.is_set()
        assert client._responses[req_id]["ok"] is True

    def test_reader_sets_jid_on_ready(
        self, tmp_path: Path,
    ) -> None:
        """Ready event should store jid (and briefly set _connected).

        Note: _connected is cleared after stdout exhaustion, but jid persists.
        """
        client = WhatsAppClient(auth_dir=tmp_path)

        ready = json.dumps({"type": "ready", "jid": "554892011083"})
        mock_proc = MagicMock()
        mock_proc.stdout = [(ready + "\n").encode("utf-8")]
        client._proc = mock_proc

        client._reader_loop()

        # jid is set permanently by the ready event
        assert client.jid == "554892011083"
        # _connected is cleared because stdout was exhausted (process exited)
        assert not client._connected.is_set()

    def test_reader_sets_lid_on_ready(
        self, tmp_path: Path,
    ) -> None:
        """Ready event with lid field should store the linked device ID."""
        client = WhatsAppClient(auth_dir=tmp_path)

        ready = json.dumps({
            "type": "ready",
            "jid": "554892011083",
            "lid": "161048623628515",
        })
        mock_proc = MagicMock()
        mock_proc.stdout = [(ready + "\n").encode("utf-8")]
        client._proc = mock_proc

        client._reader_loop()

        assert client.jid == "554892011083"
        assert client.lid == "161048623628515"

    def test_reader_lid_none_when_absent(
        self, tmp_path: Path,
    ) -> None:
        """Ready event without lid field leaves lid as None."""
        client = WhatsAppClient(auth_dir=tmp_path)

        ready = json.dumps({"type": "ready", "jid": "554892011083"})
        mock_proc = MagicMock()
        mock_proc.stdout = [(ready + "\n").encode("utf-8")]
        client._proc = mock_proc

        client._reader_loop()

        assert client.jid == "554892011083"
        assert client.lid is None

    def test_reader_handles_connection_close(
        self, tmp_path: Path,
    ) -> None:
        """Connection close event should clear _connected."""
        client = WhatsAppClient(auth_dir=tmp_path)
        client._connected.set()

        close_event = json.dumps({
            "type": "connection",
            "status": "close",
        })
        mock_proc = MagicMock()
        mock_proc.stdout = [(close_event + "\n").encode("utf-8")]
        client._proc = mock_proc

        client._reader_loop()

        assert not client._connected.is_set()

    def test_reader_ignores_non_json(self, tmp_path: Path) -> None:
        """Non-JSON lines should be silently skipped."""
        client = WhatsAppClient(auth_dir=tmp_path)

        mock_proc = MagicMock()
        mock_proc.stdout = [
            b"Some random log line\n",
            b"Another log\n",
        ]
        client._proc = mock_proc

        client._reader_loop()

        assert client._event_queue.empty()

    def test_reader_handles_qr_event(self, tmp_path: Path) -> None:
        """QR event should set _qr_event and _qr_data."""
        client = WhatsAppClient(auth_dir=tmp_path)

        qr_event = json.dumps({"type": "qr", "qr": "2@testqr"})
        mock_proc = MagicMock()
        mock_proc.stdout = [(qr_event + "\n").encode("utf-8")]
        client._proc = mock_proc

        client._reader_loop()

        assert client._qr_event.is_set()
        assert client._qr_data == "2@testqr"


# ================================================================
# Event iteration
# ================================================================


class TestIterEvents:
    """Test iter_events() generator."""

    def test_iter_events_yields_queued(self, tmp_path: Path) -> None:
        """iter_events() should yield events from the queue."""
        client = WhatsAppClient(auth_dir=tmp_path)
        client._event_queue.put_nowait({"type": "message", "text": "hi"})
        client._event_queue.put_nowait({"type": "store_updated"})

        events = list(client.iter_events(timeout=0.01))
        assert len(events) == 2
        assert events[0]["type"] == "message"
        assert events[1]["type"] == "store_updated"

    def test_iter_events_empty(self, tmp_path: Path) -> None:
        """iter_events() should return empty when no events."""
        client = WhatsAppClient(auth_dir=tmp_path)
        events = list(client.iter_events(timeout=0.01))
        assert events == []


# ================================================================
# npm install
# ================================================================


class TestNpmInstall:
    """Test _ensure_npm_installed logic."""

    def test_skips_when_node_modules_exists(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """No npm install when node_modules/ already present."""
        import src.extensions.bridges.whatsapp.client as wc

        pkg_dir = tmp_path / "whatsapp"
        pkg_dir.mkdir()
        (pkg_dir / "node_modules").mkdir()

        monkeypatch.setattr(wc, "_PACKAGE_DIR", pkg_dir)

        client = WhatsAppClient(auth_dir=tmp_path)
        # Should not raise (no npm call needed)
        client._ensure_npm_installed()

    def test_raises_when_npm_not_found(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Missing npm raises WhatsAppClientError."""
        import src.extensions.bridges.whatsapp.client as wc

        pkg_dir = tmp_path / "whatsapp"
        pkg_dir.mkdir()

        monkeypatch.setattr(wc, "_PACKAGE_DIR", pkg_dir)
        monkeypatch.setattr(
            "src.extensions.bridges.whatsapp.client.shutil.which",
            lambda _name: None,
        )

        client = WhatsAppClient(auth_dir=tmp_path)
        with pytest.raises(WhatsAppClientError, match="npm not found"):
            client._ensure_npm_installed()


# ================================================================
# is_connected property
# ================================================================


class TestIsConnected:
    """Test the is_connected property."""

    def test_false_when_no_proc(self, tmp_path: Path) -> None:
        client = WhatsAppClient(auth_dir=tmp_path)
        assert client.is_connected is False

    def test_false_when_not_connected_event(
        self, tmp_path: Path,
    ) -> None:
        client = WhatsAppClient(auth_dir=tmp_path)
        client._proc = MagicMock()
        # _connected is not set
        assert client.is_connected is False

    def test_true_when_connected_and_proc(
        self, tmp_path: Path,
    ) -> None:
        client = WhatsAppClient(auth_dir=tmp_path)
        client._proc = MagicMock()
        client._connected.set()
        assert client.is_connected is True

"""Unit tests for WhatsApp listener lifecycle helpers."""

from __future__ import annotations

import fcntl
import json
import os
import uuid
from pathlib import Path
from typing import Any

import pytest


class _FakeProc:
    def __init__(self, pid: int) -> None:
        self.pid = pid


@pytest.fixture()
def patched_runtime_paths(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> Path:
    """Redirect listener runtime files to a temporary directory."""
    import src.extensions.bridges.whatsapp.listener as wl

    runtime = tmp_path / "wa-listener"
    monkeypatch.setattr(wl, "_RUNTIME_DIR", runtime)
    monkeypatch.setattr(wl, "_PID_PATH", runtime / "listener.pid.json")
    monkeypatch.setattr(wl, "_STATUS_PATH", runtime / "status.json")
    monkeypatch.setattr(wl, "_LOG_PATH", runtime / "listener.log")
    monkeypatch.setattr(wl, "_OUTBOX_DIR", runtime / "outbox")
    monkeypatch.setattr(wl, "_OUTBOX_RESP_DIR", runtime / "outbox_responses")
    monkeypatch.setattr(wl, "_LOCK_PATH", runtime / "listener.lock")
    return runtime


def test_status_not_running_without_pid_file(
    patched_runtime_paths: Path,
) -> None:
    """status() should report not-running when no pid exists."""
    from src.extensions.bridges.whatsapp.listener import WhatsAppListenerService

    status = WhatsAppListenerService().status()
    assert status["running"] is False
    assert status["pid"] is None


def test_start_writes_pid_and_invokes_cli_runner(
    patched_runtime_paths: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """start() should spawn the runner and persist pid metadata."""
    import src.extensions.bridges.whatsapp.listener as wl

    launched: list[list[str]] = []

    def _fake_popen(*args, **kwargs):  # noqa: ANN002, ANN003
        cmd = list(args[0])
        launched.append(cmd)
        return _FakeProc(pid=43210)

    monkeypatch.setattr(wl.subprocess, "Popen", _fake_popen)
    monkeypatch.setattr(
        wl,
        "_is_process_running",
        lambda pid, expected_cmd_substring=None: pid == 43210,  # noqa: ARG005
    )
    monkeypatch.setattr(wl.time, "sleep", lambda _s: None)

    service = wl.WhatsAppListenerService()
    status = service.start("npx", ("-y", "whatsapp-mcp-lifeosai"))

    assert status["running"] is True
    assert status["pid"] == 43210
    assert launched, "listener process was not spawned"
    assert "whatsapp-listener-run" in launched[0]
    assert "--mcp-command" in launched[0]
    assert any(token.startswith("--mcp-arg=") for token in launched[0])

    pid_data = json.loads((patched_runtime_paths / "listener.pid.json").read_text())
    assert pid_data["pid"] == 43210


def test_stop_removes_pid_for_non_running_process(
    patched_runtime_paths: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """stop() should clear stale pid files."""
    import src.extensions.bridges.whatsapp.listener as wl

    pid_path = patched_runtime_paths / "listener.pid.json"
    pid_path.parent.mkdir(parents=True, exist_ok=True)
    pid_path.write_text(
        json.dumps({"pid": 55555, "started_at": "2026-02-28T00:00:00Z"}),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        wl,
        "_is_process_running",
        lambda _pid, expected_cmd_substring=None: False,  # noqa: ARG005
    )

    status = wl.WhatsAppListenerService().stop()
    assert status["running"] is False
    assert not pid_path.exists()


# ================================================================
# resolve_self_jid tests
# ================================================================


class TestResolveSelfJid:
    """Test resolve_self_jid reads bare JID from creds.json."""

    def test_returns_bare_jid(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        import src.extensions.bridges.whatsapp.paths as whatsapp_paths

        auth_dir = tmp_path / "auth"
        auth_dir.mkdir()
        creds = {"me": {"id": "554892011083:34@s.whatsapp.net"}}
        (auth_dir / "creds.json").write_text(json.dumps(creds))
        monkeypatch.setattr(
            whatsapp_paths, "resolve_whatsapp_auth_dir", lambda: auth_dir,
        )

        result = whatsapp_paths.resolve_self_jid()
        assert result == "554892011083"

    def test_returns_none_when_no_creds(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        import src.extensions.bridges.whatsapp.paths as whatsapp_paths

        auth_dir = tmp_path / "auth"
        auth_dir.mkdir()
        monkeypatch.setattr(
            whatsapp_paths, "resolve_whatsapp_auth_dir", lambda: auth_dir,
        )

        assert whatsapp_paths.resolve_self_jid() is None

    def test_returns_none_when_no_me_field(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        import src.extensions.bridges.whatsapp.paths as whatsapp_paths

        auth_dir = tmp_path / "auth"
        auth_dir.mkdir()
        (auth_dir / "creds.json").write_text("{}")
        monkeypatch.setattr(
            whatsapp_paths, "resolve_whatsapp_auth_dir", lambda: auth_dir,
        )

        assert whatsapp_paths.resolve_self_jid() is None


# ================================================================
# resolve_self_lid tests
# ================================================================


class TestResolveSelfLid:
    """Test resolve_self_lid reads bare LID from creds.json."""

    def test_returns_bare_lid(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        import src.extensions.bridges.whatsapp.paths as whatsapp_paths

        auth_dir = tmp_path / "auth"
        auth_dir.mkdir()
        creds = {
            "me": {
                "id": "554892011083:34@s.whatsapp.net",
                "lid": "161048623628515:34@lid",
            },
        }
        (auth_dir / "creds.json").write_text(json.dumps(creds))
        monkeypatch.setattr(
            whatsapp_paths, "resolve_whatsapp_auth_dir", lambda: auth_dir,
        )

        result = whatsapp_paths.resolve_self_lid()
        assert result == "161048623628515"

    def test_returns_none_when_no_lid(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        import src.extensions.bridges.whatsapp.paths as whatsapp_paths

        auth_dir = tmp_path / "auth"
        auth_dir.mkdir()
        creds = {"me": {"id": "554892011083:34@s.whatsapp.net"}}
        (auth_dir / "creds.json").write_text(json.dumps(creds))
        monkeypatch.setattr(
            whatsapp_paths, "resolve_whatsapp_auth_dir", lambda: auth_dir,
        )

        assert whatsapp_paths.resolve_self_lid() is None

    def test_returns_none_when_no_creds(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        import src.extensions.bridges.whatsapp.paths as whatsapp_paths

        auth_dir = tmp_path / "auth"
        auth_dir.mkdir()
        monkeypatch.setattr(
            whatsapp_paths, "resolve_whatsapp_auth_dir", lambda: auth_dir,
        )

        assert whatsapp_paths.resolve_self_lid() is None

    def test_returns_none_when_empty_me(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        import src.extensions.bridges.whatsapp.paths as whatsapp_paths

        auth_dir = tmp_path / "auth"
        auth_dir.mkdir()
        (auth_dir / "creds.json").write_text("{}")
        monkeypatch.setattr(
            whatsapp_paths, "resolve_whatsapp_auth_dir", lambda: auth_dir,
        )

        assert whatsapp_paths.resolve_self_lid() is None


# ================================================================
# Singleton lock tests
# ================================================================


class TestSingletonLock:
    """Test fcntl.flock singleton mechanism."""

    def test_acquire_and_release(
        self, patched_runtime_paths: Path,
    ) -> None:
        """Lock can be acquired and released."""
        from src.extensions.bridges.whatsapp.listener import (
            _is_listener_locked,
            _release_lock,
            _try_acquire_lock,
        )

        fd = _try_acquire_lock()
        assert fd is not None
        assert _is_listener_locked() is True

        _release_lock(fd)
        assert _is_listener_locked() is False

    def test_second_acquire_fails_while_held(
        self, patched_runtime_paths: Path,
    ) -> None:
        """Second lock attempt fails when first is held."""
        from src.extensions.bridges.whatsapp.listener import (
            _release_lock,
            _try_acquire_lock,
        )

        fd1 = _try_acquire_lock()
        assert fd1 is not None

        fd2 = _try_acquire_lock()
        assert fd2 is None, "should fail when lock is held"

        _release_lock(fd1)

    def test_lock_available_after_fd_close(
        self, patched_runtime_paths: Path,
    ) -> None:
        """OS releases flock when fd is closed (simulates crash)."""
        from src.extensions.bridges.whatsapp.listener import (
            _is_listener_locked,
            _try_acquire_lock,
        )

        fd = _try_acquire_lock()
        assert fd is not None
        # Simulate crash: close fd without explicit unlock
        os.close(fd)

        assert _is_listener_locked() is False

        # Can re-acquire
        fd2 = _try_acquire_lock()
        assert fd2 is not None
        os.close(fd2)

    def test_is_listener_locked_false_no_file(
        self, patched_runtime_paths: Path,
    ) -> None:
        """_is_listener_locked returns False when no lock file."""
        from src.extensions.bridges.whatsapp.listener import _is_listener_locked

        assert _is_listener_locked() is False

    def test_start_skips_spawn_when_locked(
        self,
        patched_runtime_paths: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """start() should not spawn when lock is held."""
        import src.extensions.bridges.whatsapp.listener as wl

        # Hold the lock externally
        lock_path = patched_runtime_paths / "listener.lock"
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        lock_fd = os.open(
            str(lock_path), os.O_CREAT | os.O_RDWR,
        )
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)

        spawned: list[str] = []

        def _fake_popen(*a, **kw):  # noqa: ANN002, ANN003
            spawned.append("spawned")
            return _FakeProc(pid=99999)

        monkeypatch.setattr(
            wl.subprocess, "Popen", _fake_popen,
        )
        monkeypatch.setattr(
            wl,
            "_is_process_running",
            lambda _p, expected_cmd_substring=None: False,
        )
        # status() falls back to pgrep when the lock is held but no pid file
        # exists; stub it so this test doesn't depend on the host's process
        # table (and doesn't reach into the mocked Popen).
        monkeypatch.setattr(wl, "_pgrep_listener_pid", lambda: 0)

        service = wl.WhatsAppListenerService()
        status = service.start("node", ("client.js",))

        assert not spawned, "should NOT spawn when lock held"
        assert status["running"] is False

        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        os.close(lock_fd)


# ================================================================
# Outbox flow: send-side durability + delivery acks
# ================================================================


class _StubClient:
    """Minimal stand-in for WhatsAppClient used by outbox tests."""

    def __init__(
        self,
        *,
        send_result: dict[str, Any] | None = None,
        send_error: Exception | None = None,
        acks: list[dict[str, Any]] | None = None,
    ) -> None:
        self._send_result = send_result or {"message_id": "STUB"}
        self._send_error = send_error
        self._acks = list(acks or [])
        self.send_calls: list[dict[str, Any]] = []
        self.drain_calls = 0

    def send_message(
        self,
        to: str,
        text: str,
        message_id: str | None = None,
    ) -> dict[str, Any]:
        self.send_calls.append(
            {"to": to, "text": text, "message_id": message_id},
        )
        if self._send_error is not None:
            raise self._send_error
        return dict(self._send_result)

    def drain_acks(self) -> list[dict[str, Any]]:
        self.drain_calls += 1
        out = self._acks
        self._acks = []
        return out


def _write_outbox_request(
    outbox_dir: Path,
    payload: dict[str, Any],
) -> Path:
    outbox_dir.mkdir(parents=True, exist_ok=True)
    path = outbox_dir / f"{payload['id']}.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_outbound_keeps_file_on_send_success(
    patched_runtime_paths: Path,
) -> None:
    """Successful Baileys send leaves the request file for ack-based cleanup."""
    import src.extensions.bridges.whatsapp.listener as wl

    request_id = uuid.uuid4().hex
    outbox_dir = patched_runtime_paths / "outbox"
    req_path = _write_outbox_request(
        outbox_dir,
        {"id": request_id, "to": "5511999@s.whatsapp.net", "message": "hi"},
    )
    client = _StubClient(send_result={"message_id": "WAID-123"})

    wl._process_outbound_requests(client)

    assert req_path.exists(), "request file must survive until ack drains it"
    resp_path = patched_runtime_paths / "outbox_responses" / f"{request_id}.json"
    response = json.loads(resp_path.read_text())
    assert response["status"] == "sent"
    assert response["message_id"] == "WAID-123"
    # Payload was rewritten to include resolved message_id for ack matching.
    stamped = json.loads(req_path.read_text())
    assert stamped["message_id"] == "WAID-123"


def test_outbound_deletes_file_immediately_for_self_chat(
    patched_runtime_paths: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """@lid self-chat sends never receive acks — delete on success instead."""
    import src.extensions.bridges.whatsapp.listener as wl
    from src.core.sqlite.engine import DatabaseEngine
    from src.notifications.preference_service import PreferenceService

    db_path = tmp_path / "test.sqlite3"
    monkeypatch.setattr(wl, "DEFAULT_DB_PATH", db_path)

    request_id = uuid.uuid4().hex
    outbox_dir = patched_runtime_paths / "outbox"
    req_path = _write_outbox_request(
        outbox_dir,
        {"id": request_id, "to": "161048623628515@lid", "message": "hi"},
    )

    # Seed a notification row so we can confirm delivered_at gets stamped.
    with DatabaseEngine(db_path=db_path) as db:
        PreferenceService(db)
        db.execute(
            "INSERT INTO _notification_log "
            "(id, dedupe_key, category, importance_score, decision, "
            "delivery_status, message, opt_out_text, error, source_type, "
            "source_id, message_id, delivered_at, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                "rec-1", "dk", "test", 5.0, "send", "sent", "hi",
                "", None, "test", "src-1", request_id, None,
                "2026-05-25T10:00:00",
            ],
        )

    client = _StubClient(send_result={"message_id": request_id})
    wl._process_outbound_requests(client)

    assert not req_path.exists(), "self-chat file must be deleted on send"
    with DatabaseEngine(db_path=db_path) as db:
        rows = db.query(
            "SELECT delivered_at FROM _notification_log "
            "WHERE message_id = ?",
            [request_id],
        )
    assert rows and rows[0]["delivered_at"], (
        "delivered_at must be stamped synchronously for self-chat"
    )


def test_is_self_chat_jid_classification() -> None:
    """JID classifier distinguishes @lid self-chat from normal recipients."""
    from src.extensions.bridges.whatsapp.listener import _is_self_chat_jid

    assert _is_self_chat_jid("161048623628515@lid") is True
    assert _is_self_chat_jid("5511999@s.whatsapp.net") is False
    assert _is_self_chat_jid("120363xxx@g.us") is False
    assert _is_self_chat_jid("") is False


def test_outbound_threads_request_id_as_message_id(
    patched_runtime_paths: Path,
) -> None:
    """Request id is passed to Baileys as the WhatsApp messageId."""
    import src.extensions.bridges.whatsapp.listener as wl

    request_id = uuid.uuid4().hex
    _write_outbox_request(
        patched_runtime_paths / "outbox",
        {"id": request_id, "to": "5511999@s.whatsapp.net", "message": "hi"},
    )
    client = _StubClient(send_result={"message_id": None})

    wl._process_outbound_requests(client)

    assert client.send_calls == [
        {
            "to": "5511999@s.whatsapp.net",
            "text": "hi",
            "message_id": request_id,
        },
    ]


def test_outbound_bumps_attempts_on_send_error(
    patched_runtime_paths: Path,
) -> None:
    """Transient Baileys failure keeps the file for retry with bumped counter."""
    import src.extensions.bridges.whatsapp.listener as wl
    from src.extensions.bridges.whatsapp.client import WhatsAppSendError

    request_id = uuid.uuid4().hex
    outbox_dir = patched_runtime_paths / "outbox"
    req_path = _write_outbox_request(
        outbox_dir,
        {"id": request_id, "to": "5511999@s.whatsapp.net", "message": "hi"},
    )
    client = _StubClient(send_error=WhatsAppSendError("connection closed"))

    wl._process_outbound_requests(client)

    assert req_path.exists()
    payload = json.loads(req_path.read_text())
    assert payload["attempts"] == 1
    assert payload["last_error"] == "connection closed"


def test_outbound_renames_to_failed_at_max_attempts(
    patched_runtime_paths: Path,
) -> None:
    """After _MAX_OUTBOUND_ATTEMPTS the file is parked as .failed."""
    import src.extensions.bridges.whatsapp.listener as wl
    from src.extensions.bridges.whatsapp.client import WhatsAppSendError

    request_id = uuid.uuid4().hex
    outbox_dir = patched_runtime_paths / "outbox"
    req_path = _write_outbox_request(
        outbox_dir,
        {
            "id": request_id,
            "to": "5511999@s.whatsapp.net",
            "message": "hi",
            "attempts": wl._MAX_OUTBOUND_ATTEMPTS - 1,
        },
    )
    client = _StubClient(send_error=WhatsAppSendError("network gone"))

    wl._process_outbound_requests(client)

    assert not req_path.exists()
    failed_path = outbox_dir / f"{request_id}.failed"
    assert failed_path.exists()
    parked = json.loads(failed_path.read_text())
    assert parked["attempts"] == wl._MAX_OUTBOUND_ATTEMPTS


def test_outbound_deletes_file_on_validation_error(
    patched_runtime_paths: Path,
) -> None:
    """Malformed request (missing 'to') is dropped — replay would never work."""
    import src.extensions.bridges.whatsapp.listener as wl

    request_id = uuid.uuid4().hex
    outbox_dir = patched_runtime_paths / "outbox"
    req_path = _write_outbox_request(
        outbox_dir,
        {"id": request_id, "message": "hi"},
    )
    client = _StubClient()

    wl._process_outbound_requests(client)

    assert not req_path.exists()
    resp = json.loads(
        (patched_runtime_paths / "outbox_responses" / f"{request_id}.json").read_text(),
    )
    assert resp["status"] == "failed"
    assert "to/message" in resp["error"]


def test_drain_acks_deletes_matching_outbox_file(
    patched_runtime_paths: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A delivery ack clears the corresponding {msg_id}.json file."""
    import src.extensions.bridges.whatsapp.listener as wl

    outbox_dir = patched_runtime_paths / "outbox"
    outbox_dir.mkdir(parents=True, exist_ok=True)
    msg_id = "WAID-ACK-1"
    (outbox_dir / f"{msg_id}.json").write_text("{}", encoding="utf-8")

    # Route DB writes to an isolated file so the test never touches ~/.arandu.
    monkeypatch.setattr(wl, "DEFAULT_DB_PATH", tmp_path / "test.sqlite3")

    client = _StubClient(
        acks=[{"type": "message_ack", "msg_id": msg_id, "status": 3}],
    )

    wl._drain_message_acks(client)

    assert not (outbox_dir / f"{msg_id}.json").exists()


def test_drain_acks_updates_delivered_at(
    patched_runtime_paths: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """The ack handler stamps _notification_log.delivered_at."""
    import src.extensions.bridges.whatsapp.listener as wl
    from src.core.sqlite.engine import DatabaseEngine
    from src.notifications.preference_service import PreferenceService

    db_path = tmp_path / "test.sqlite3"
    monkeypatch.setattr(wl, "DEFAULT_DB_PATH", db_path)

    msg_id = "WAID-ACK-2"
    with DatabaseEngine(db_path=db_path) as db:
        PreferenceService(db)  # creates tables
        db.execute(
            "INSERT INTO _notification_log "
            "(id, dedupe_key, category, importance_score, decision, "
            "delivery_status, message, opt_out_text, error, source_type, "
            "source_id, message_id, delivered_at, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                "rec-1", "dk", "test", 5.0, "send", "sent", "hi",
                "", None, "test", "src-1", msg_id, None, "2026-05-21T20:00:00",
            ],
        )

    client = _StubClient(
        acks=[{"type": "message_ack", "msg_id": msg_id, "status": 4}],
    )
    wl._drain_message_acks(client)

    with DatabaseEngine(db_path=db_path) as db:
        rows = db.query(
            "SELECT delivered_at FROM _notification_log WHERE message_id = ?",
            [msg_id],
        )
    assert rows and rows[0]["delivered_at"]


def test_crash_recovery_replay_then_ack(
    patched_runtime_paths: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """End-to-end: send fails → file kept → retry succeeds → ack drains it."""
    import src.extensions.bridges.whatsapp.listener as wl
    from src.extensions.bridges.whatsapp.client import WhatsAppSendError

    monkeypatch.setattr(wl, "DEFAULT_DB_PATH", tmp_path / "test.sqlite3")

    request_id = uuid.uuid4().hex
    outbox_dir = patched_runtime_paths / "outbox"
    req_path = _write_outbox_request(
        outbox_dir,
        {"id": request_id, "to": "5511999@s.whatsapp.net", "message": "hi"},
    )

    # Attempt #1: Baileys raises (simulates a crash mid-send window).
    failing_client = _StubClient(send_error=WhatsAppSendError("boom"))
    wl._process_outbound_requests(failing_client)
    assert req_path.exists()

    # Attempt #2: listener restarted, Baileys back. Sends succeed.
    ok_client = _StubClient(send_result={"message_id": request_id})
    wl._process_outbound_requests(ok_client)
    assert req_path.exists(), "file must survive until ack"
    assert ok_client.send_calls[0]["message_id"] == request_id

    # Ack arrives → file removed.
    ok_client._acks = [
        {"type": "message_ack", "msg_id": request_id, "status": 3},
    ]
    wl._drain_message_acks(ok_client)
    assert not req_path.exists()

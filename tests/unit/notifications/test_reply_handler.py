"""Tests for reply_handler.py.

Covers STOP command parsing, ReplyTracker persistence, ReplyHandler
brain query and stop flows, and conversation context building.

sensitivity_tier: N/A — test infrastructure
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from src.core.sqlite.engine import DatabaseEngine
from src.notifications.reply_handler import (
    BRAIN_PREFIX,
    PendingActionStore,
    ReplyHandler,
    ReplyTracker,
    _get_conversation_context,
    _is_batch_or_temporal,
    _parse_confirmation_intent,
    _parse_item_selection,
    _parse_stop_command,
)

# ================================================================
# Fixtures
# ================================================================


@pytest.fixture()
def tmp_db(tmp_path: Path) -> DatabaseEngine:
    """Fresh DuckDB engine backed by a temp file."""
    db_path = tmp_path / "test_replies.duckdb"
    engine = DatabaseEngine(db_path=db_path)
    yield engine
    engine.close()


@pytest.fixture()
def tracker(tmp_db: DatabaseEngine) -> ReplyTracker:
    """ReplyTracker wired to the temp database."""
    return ReplyTracker(tmp_db)


@pytest.fixture()
def mock_brain() -> MagicMock:
    """Mocked BrainAgent."""
    brain = MagicMock()

    @dataclass(frozen=True)
    class FakeBrainResponse:
        answer: str = "Test answer from brain"
        sources: list[dict[str, Any]] = field(default_factory=list)
        context_summary: str = ""
        model: str = "test"
        latency_ms: float = 0.0

    brain.ask.return_value = FakeBrainResponse()
    return brain


def _seed_raw_messages(db: DatabaseEngine, phone: str) -> None:
    """Create raw_messages table and seed self-chat data."""
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS raw_messages (
            id          VARCHAR PRIMARY KEY,
            sender      VARCHAR,
            sender_name VARCHAR,
            recipient   VARCHAR,
            content     TEXT,
            timestamp   TIMESTAMPTZ,
            is_from_me  BOOLEAN,
            chat_name   VARCHAR,
            source      VARCHAR DEFAULT 'whatsapp',
            metadata    TEXT
        )
        """
    )
    phone_jid = f"{phone.lstrip('+')}@s.whatsapp.net"
    now = datetime.now(tz=timezone.utc)

    messages = [
        # Brain notification (should be skipped)
        (
            f"{phone_jid}:msg001",
            "me",
            "me",
            phone_jid,
            f"{BRAIN_PREFIX}Messages Needing Your Reply\nFamily:\n- Dad",
            (now - timedelta(minutes=30)).isoformat(),
            True,
            phone_jid,
        ),
        # User reply (should be processed)
        (
            f"{phone_jid}:msg002",
            "me",
            "me",
            phone_jid,
            "What meetings do I have tomorrow?",
            (now - timedelta(minutes=15)).isoformat(),
            True,
            phone_jid,
        ),
        # STOP command (should be processed)
        (
            f"{phone_jid}:msg003",
            "me",
            "me",
            phone_jid,
            "STOP REPLIES",
            (now - timedelta(minutes=5)).isoformat(),
            True,
            phone_jid,
        ),
    ]

    for msg in messages:
        db.execute(
            "INSERT INTO raw_messages "
            "(id, sender, sender_name, recipient, content, timestamp, "
            "is_from_me, chat_name) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            list(msg),
        )


# ================================================================
# _parse_stop_command tests
# ================================================================


class TestParseStopCommand:
    """Test STOP command parsing."""

    def test_stop_replies(self) -> None:
        assert _parse_stop_command("STOP REPLIES") == "pending_replies"

    def test_stop_all(self) -> None:
        assert _parse_stop_command("STOP ALL") == "_global"

    def test_stop_birthdays(self) -> None:
        assert _parse_stop_command("STOP BIRTHDAYS") == "birthday_reminders"

    def test_stop_events(self) -> None:
        assert _parse_stop_command("STOP EVENTS") == "event_actions"

    def test_stop_people(self) -> None:
        assert _parse_stop_command("STOP PEOPLE") == "important_people"

    def test_stop_calendar(self) -> None:
        assert _parse_stop_command("STOP CALENDAR") == "calendar_conflicts"

    def test_stop_health(self) -> None:
        assert _parse_stop_command("STOP HEALTH") == "health_alerts"

    def test_stop_actions(self) -> None:
        assert _parse_stop_command("STOP ACTIONS") == "action_results"

    def test_stop_pipeline(self) -> None:
        assert _parse_stop_command("STOP PIPELINE") == "pipeline_summary"

    def test_case_insensitive(self) -> None:
        assert _parse_stop_command("stop replies") == "pending_replies"
        assert _parse_stop_command("Stop All") == "_global"

    def test_with_whitespace(self) -> None:
        assert _parse_stop_command("  STOP REPLIES  ") == "pending_replies"

    def test_not_a_stop_command(self) -> None:
        assert _parse_stop_command("hello world") is None
        assert _parse_stop_command("What's my schedule?") is None
        assert _parse_stop_command("STOP") is None
        assert _parse_stop_command("STOP SOMETHING") is None

    def test_empty_string(self) -> None:
        assert _parse_stop_command("") is None


# ================================================================
# ReplyTracker tests
# ================================================================


class TestReplyTracker:
    """Test ReplyTracker DuckDB persistence."""

    def test_creates_table(self, tracker: ReplyTracker) -> None:
        """Table exists after construction."""
        assert not tracker.is_processed("nonexistent")

    def test_idempotent_creation(self, tmp_db: DatabaseEngine) -> None:
        """Creating ReplyTracker twice doesn't error."""
        ReplyTracker(tmp_db)
        ReplyTracker(tmp_db)

    def test_mark_and_check_processed(
        self, tracker: ReplyTracker,
    ) -> None:
        tracker.mark_processed(
            "msg001", "hello", "brain_query",
            response_text="answer", response_sent=True,
        )
        assert tracker.is_processed("msg001")
        assert not tracker.is_processed("msg002")

    def test_get_last_check_time_empty(
        self, tracker: ReplyTracker,
    ) -> None:
        assert tracker.get_last_check_time() is None

    def test_get_last_check_time_after_mark(
        self, tracker: ReplyTracker,
    ) -> None:
        tracker.mark_processed(
            "msg001", "test", "brain_query",
        )
        result = tracker.get_last_check_time()
        assert result is not None
        assert isinstance(result, datetime)

    def test_mark_with_error(self, tracker: ReplyTracker) -> None:
        tracker.mark_processed(
            "msg_err", "bad", "error",
            error="Something failed",
        )
        assert tracker.is_processed("msg_err")


# ================================================================
# _get_conversation_context tests
# ================================================================


class TestConversationContext:
    """Test conversation context building."""

    def test_returns_empty_when_no_messages(
        self, tmp_db: DatabaseEngine,
    ) -> None:
        # Create empty table
        tmp_db.execute(
            """
            CREATE TABLE IF NOT EXISTS raw_messages (
                id VARCHAR PRIMARY KEY,
                sender VARCHAR,
                sender_name VARCHAR,
                recipient VARCHAR,
                content TEXT,
                timestamp TIMESTAMPTZ,
                is_from_me BOOLEAN,
                chat_name VARCHAR,
                source VARCHAR DEFAULT 'whatsapp',
                metadata TEXT
            )
            """
        )
        result = _get_conversation_context(tmp_db, "5511999999999")
        assert result == ""

    def test_formats_messages(self, tmp_db: DatabaseEngine) -> None:
        _seed_raw_messages(tmp_db, "5511999999999")
        result = _get_conversation_context(tmp_db, "5511999999999")
        assert "Recent self-chat conversation:" in result
        assert "[Arandu]:" in result
        assert "[User]:" in result
        assert "What meetings do I have tomorrow?" in result

    def test_respects_limit(self, tmp_db: DatabaseEngine) -> None:
        _seed_raw_messages(tmp_db, "5511999999999")
        result = _get_conversation_context(
            tmp_db, "5511999999999", limit=1,
        )
        # Only 1 message returned by SQL, so at most 2 lines
        # (header + 1 message)
        lines = [ln for ln in result.split("\n") if ln.strip()]
        assert len(lines) <= 2


# ================================================================
# ReplyHandler tests
# ================================================================


class TestReplyHandler:
    """Test full reply processing flow."""

    def test_no_messages_returns_zero(
        self, tmp_db: DatabaseEngine, mock_brain: MagicMock,
    ) -> None:
        # Create empty raw_messages
        tmp_db.execute(
            """
            CREATE TABLE IF NOT EXISTS raw_messages (
                id VARCHAR PRIMARY KEY,
                sender VARCHAR, sender_name VARCHAR,
                recipient VARCHAR, content TEXT,
                timestamp TIMESTAMPTZ, is_from_me BOOLEAN,
                chat_name VARCHAR, source VARCHAR DEFAULT 'whatsapp',
                metadata TEXT
            )
            """
        )
        handler = ReplyHandler(
            db_engine=tmp_db, brain_agent=mock_brain,
            phone="+5511999999999",
        )
        assert handler.process_new_replies() == 0

    @patch(
        "src.notifications.reply_handler.ReplyHandler._send_response",
        return_value=True,
    )
    def test_processes_brain_query(
        self,
        mock_send: MagicMock,
        tmp_db: DatabaseEngine,
        mock_brain: MagicMock,
    ) -> None:
        _seed_raw_messages(tmp_db, "5511999999999")
        handler = ReplyHandler(
            db_engine=tmp_db, brain_agent=mock_brain,
            phone="+5511999999999",
        )
        count = handler.process_new_replies()
        # 2 messages processed: brain query + STOP command
        assert count == 2
        # Brain was called for the non-STOP message
        mock_brain.ask.assert_called_once()
        question_arg = mock_brain.ask.call_args[0][0]
        assert "What meetings do I have tomorrow?" in question_arg

    @patch(
        "src.notifications.reply_handler.ReplyHandler._send_response",
        return_value=True,
    )
    def test_handles_stop_command(
        self,
        mock_send: MagicMock,
        tmp_db: DatabaseEngine,
        mock_brain: MagicMock,
    ) -> None:
        _seed_raw_messages(tmp_db, "5511999999999")
        handler = ReplyHandler(
            db_engine=tmp_db, brain_agent=mock_brain,
            phone="+5511999999999",
        )
        handler.process_new_replies()

        # Check that the tracker recorded the STOP command
        tracker = handler._tracker
        phone_jid = "5511999999999@s.whatsapp.net"
        assert tracker.is_processed(f"{phone_jid}:msg003")

        # Check preference was updated (mock it)
        rows = tmp_db.query(
            "SELECT enabled FROM _notification_preferences "
            "WHERE category = 'pending_replies'",
        )
        assert rows
        assert not rows[0]["enabled"]

    @patch(
        "src.notifications.reply_handler.ReplyHandler._send_response",
        return_value=True,
    )
    def test_skips_brain_prefix_messages(
        self,
        mock_send: MagicMock,
        tmp_db: DatabaseEngine,
        mock_brain: MagicMock,
    ) -> None:
        _seed_raw_messages(tmp_db, "5511999999999")
        handler = ReplyHandler(
            db_engine=tmp_db, brain_agent=mock_brain,
            phone="+5511999999999",
        )
        handler.process_new_replies()

        # Brain prefix message should NOT be in tracker
        tracker = handler._tracker
        phone_jid = "5511999999999@s.whatsapp.net"
        assert not tracker.is_processed(f"{phone_jid}:msg001")

    @patch(
        "src.notifications.reply_handler.ReplyHandler._send_response",
        return_value=True,
    )
    def test_does_not_reprocess(
        self,
        mock_send: MagicMock,
        tmp_db: DatabaseEngine,
        mock_brain: MagicMock,
    ) -> None:
        _seed_raw_messages(tmp_db, "5511999999999")
        handler = ReplyHandler(
            db_engine=tmp_db, brain_agent=mock_brain,
            phone="+5511999999999",
        )
        # Process twice
        handler.process_new_replies()
        mock_brain.reset_mock()
        count = handler.process_new_replies()
        assert count == 0
        mock_brain.ask.assert_not_called()


class TestReplyHandlerBrainFailure:
    """Test behavior when BrainAgent fails."""

    @patch(
        "src.notifications.reply_handler.ReplyHandler._send_response",
        return_value=True,
    )
    def test_brain_error_sends_fallback(
        self,
        mock_send: MagicMock,
        tmp_db: DatabaseEngine,
    ) -> None:
        brain = MagicMock()
        brain.ask.side_effect = RuntimeError("Ollama down")

        _seed_raw_messages(tmp_db, "5511999999999")
        handler = ReplyHandler(
            db_engine=tmp_db, brain_agent=brain,
            phone="+5511999999999",
        )
        handler.process_new_replies()

        # Should still send a response (fallback message)
        assert mock_send.called
        sent_msg = mock_send.call_args_list[0][0][0]
        assert "Sorry" in sent_msg or BRAIN_PREFIX in sent_msg


class TestReplyHandlerSelfJid:
    """Test JID mismatch scenario (e.g. Brazil phone normalization)."""

    @patch(
        "src.notifications.reply_handler.ReplyHandler._send_response",
        return_value=True,
    )
    def test_self_jid_used_for_queries(
        self,
        mock_send: MagicMock,
        tmp_db: DatabaseEngine,
        mock_brain: MagicMock,
    ) -> None:
        """When self_jid differs from phone, queries use self_jid."""
        # Seed data with the BARE JID (what Baileys stores)
        bare_jid = "554892011083"
        _seed_raw_messages(tmp_db, bare_jid)

        # Create handler with the FULL phone (settings format) + correct JID
        handler = ReplyHandler(
            db_engine=tmp_db, brain_agent=mock_brain,
            phone="+5548992011083",  # Brazil 9-digit format
            self_jid=bare_jid,  # Baileys JID format
        )
        count = handler.process_new_replies()
        # Should find messages because it queries using self_jid
        assert count == 2  # brain query + STOP command

    def test_send_uses_lid_jid_for_self_chat(
        self,
        tmp_db: DatabaseEngine,
        mock_brain: MagicMock,
    ) -> None:
        """Reply is sent to @lid JID so it lands in the phone's self-chat."""
        bare_jid = "554892011083"
        _seed_raw_messages(tmp_db, bare_jid)

        captured: list[str] = []

        def _capture_send(to: str, message: str) -> bool:
            captured.append(to)
            return True

        handler = ReplyHandler(
            db_engine=tmp_db, brain_agent=mock_brain,
            phone="+5548992011083",
            self_jid=bare_jid,
            self_lid="161048623628515",
            send_fn=_capture_send,
        )
        handler.process_new_replies()

        # All sends should target the @lid JID, not @s.whatsapp.net —
        # @s.whatsapp.net creates a separate chat thread on the phone.
        for target in captured:
            assert target == "161048623628515@lid", (
                f"Expected @lid JID but got {target}"
            )

    def test_send_falls_back_to_jid_when_no_lid(
        self,
        tmp_db: DatabaseEngine,
        mock_brain: MagicMock,
    ) -> None:
        """Without LID, reply falls back to @s.whatsapp.net JID."""
        bare_jid = "554892011083"
        _seed_raw_messages(tmp_db, bare_jid)

        captured: list[str] = []

        def _capture_send(to: str, message: str) -> bool:
            captured.append(to)
            return True

        handler = ReplyHandler(
            db_engine=tmp_db, brain_agent=mock_brain,
            phone="+5548992011083",
            self_jid=bare_jid,
            # No self_lid — falls back to @s.whatsapp.net
            send_fn=_capture_send,
        )
        handler.process_new_replies()

        for target in captured:
            assert target == "554892011083@s.whatsapp.net", (
                f"Expected @s.whatsapp.net JID but got {target}"
            )

    @patch(
        "src.notifications.reply_handler.ReplyHandler._send_response",
        return_value=True,
    )
    def test_phone_mismatch_without_self_jid_misses_messages(
        self,
        mock_send: MagicMock,
        tmp_db: DatabaseEngine,
        mock_brain: MagicMock,
    ) -> None:
        """When phone doesn't match JID and no self_jid, queries miss data."""
        # Seed data with BARE JID
        _seed_raw_messages(tmp_db, "554892011083")

        # Create handler with FULL phone only (no self_jid)
        handler = ReplyHandler(
            db_engine=tmp_db, brain_agent=mock_brain,
            phone="+5548992011083",  # Doesn't match seeded JID
        )
        count = handler.process_new_replies()
        # Should NOT find any messages (JID mismatch)
        assert count == 0


class TestReplyHandlerLidQuery:
    """Test that _fetch_new_self_chat_messages finds @lid messages."""

    @patch(
        "src.notifications.reply_handler.ReplyHandler._send_response",
        return_value=True,
    )
    def test_fetch_includes_lid_jid(
        self,
        mock_send: MagicMock,
        tmp_db: DatabaseEngine,
        mock_brain: MagicMock,
    ) -> None:
        """Messages stored with @lid JID are found by reply handler."""
        lid = "161048623628515"
        lid_jid = f"{lid}@lid"
        now = datetime.now(tz=timezone.utc)

        tmp_db.execute(
            """
            CREATE TABLE IF NOT EXISTS raw_messages (
                id          VARCHAR PRIMARY KEY,
                sender      VARCHAR,
                sender_name VARCHAR,
                recipient   VARCHAR,
                content     TEXT,
                timestamp   TIMESTAMPTZ,
                is_from_me  BOOLEAN,
                chat_name   VARCHAR,
                source      VARCHAR DEFAULT 'whatsapp',
                metadata    TEXT
            )
            """,
        )
        # Self-chat message stored under @lid JID
        tmp_db.execute(
            "INSERT INTO raw_messages "
            "(id, sender, sender_name, recipient, content, "
            "timestamp, is_from_me, chat_name) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [
                f"{lid_jid}:msg100",
                "me", "me", lid_jid,
                "What should I prepare for tomorrow?",
                (now - timedelta(minutes=5)).isoformat(),
                True, lid_jid,
            ],
        )

        handler = ReplyHandler(
            db_engine=tmp_db, brain_agent=mock_brain,
            phone="+5548992011083",
            self_jid="554892011083",
            self_lid=lid,
        )
        count = handler.process_new_replies()
        # Should find and process the @lid message
        assert count == 1


class TestReplyHandlerStopAll:
    """Test STOP ALL global mute."""

    @patch(
        "src.notifications.reply_handler.ReplyHandler._send_response",
        return_value=True,
    )
    def test_stop_all_mutes_globally(
        self,
        mock_send: MagicMock,
        tmp_db: DatabaseEngine,
        mock_brain: MagicMock,
    ) -> None:
        # Seed only a STOP ALL message
        tmp_db.execute(
            """
            CREATE TABLE IF NOT EXISTS raw_messages (
                id VARCHAR PRIMARY KEY,
                sender VARCHAR, sender_name VARCHAR,
                recipient VARCHAR, content TEXT,
                timestamp TIMESTAMPTZ, is_from_me BOOLEAN,
                chat_name VARCHAR, source VARCHAR DEFAULT 'whatsapp',
                metadata TEXT
            )
            """
        )
        phone_jid = "5511999999999@s.whatsapp.net"
        now = datetime.now(tz=timezone.utc)
        tmp_db.execute(
            "INSERT INTO raw_messages "
            "(id, sender, sender_name, recipient, content, timestamp, "
            "is_from_me, chat_name) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [
                f"{phone_jid}:stop_all",
                "me", "me", phone_jid,
                "STOP ALL",
                now.isoformat(), True, phone_jid,
            ],
        )

        handler = ReplyHandler(
            db_engine=tmp_db, brain_agent=mock_brain,
            phone="+5511999999999",
        )
        handler.process_new_replies()

        # Global mute should be set
        rows = tmp_db.query(
            "SELECT muted_until FROM _notification_preferences "
            "WHERE category = '_global'",
        )
        assert rows
        assert rows[0]["muted_until"] is not None


# ================================================================
# Action support tests
# ================================================================


class TestParseConfirmationIntent:
    """Test confirmation intent parsing."""

    @pytest.mark.parametrize("word", ["yes", "Yes", "YES", "y", "Y"])
    def test_confirm_english(self, word: str) -> None:
        assert _parse_confirmation_intent(word) == "confirm"

    @pytest.mark.parametrize("word", ["sim", "Sim", "SIM", "s", "S"])
    def test_confirm_portuguese(self, word: str) -> None:
        assert _parse_confirmation_intent(word) == "confirm"

    @pytest.mark.parametrize("word", ["ok", "confirm", "go", "proceed"])
    def test_confirm_other(self, word: str) -> None:
        assert _parse_confirmation_intent(word) == "confirm"

    @pytest.mark.parametrize("word", ["no", "No", "n", "N"])
    def test_reject_english(self, word: str) -> None:
        assert _parse_confirmation_intent(word) == "reject"

    @pytest.mark.parametrize(
        "word", ["não", "Não", "nao", "cancel", "cancelar"],
    )
    def test_reject_portuguese(self, word: str) -> None:
        assert _parse_confirmation_intent(word) == "reject"

    def test_unknown_returns_none(self) -> None:
        assert _parse_confirmation_intent("what time?") is None

    def test_whitespace_stripped(self) -> None:
        assert _parse_confirmation_intent("  yes  ") == "confirm"


class TestPendingActionStore:
    """Test PendingActionStore CRUD and TTL."""

    def test_store_and_get(self, tmp_db: DatabaseEngine) -> None:
        store = PendingActionStore(tmp_db)
        store.store("p1", '{"tool": "test"}', "Test action")
        pending = store.get_pending()
        assert pending is not None
        assert pending["proposal_id"] == "p1"
        assert pending["description"] == "Test action"

    def test_resolve_removes_from_pending(
        self, tmp_db: DatabaseEngine,
    ) -> None:
        store = PendingActionStore(tmp_db)
        store.store("p1", '{"tool": "test"}', "Test")
        store.resolve("p1", "confirmed")
        assert store.get_pending() is None

    def test_expired_not_returned(self, tmp_db: DatabaseEngine) -> None:
        store = PendingActionStore(tmp_db)
        # Insert with a timestamp 35 minutes in the past (TTL=30).
        old_ts = (
            datetime.now(tz=timezone.utc) - timedelta(minutes=35)
        ).isoformat()
        tmp_db.execute(
            "INSERT INTO _pending_actions "
            "(proposal_id, proposal_json, description, created_at, status) "
            "VALUES (?, ?, ?, ?, 'pending')",
            ["old", '{}', "Old action", old_ts],
        )
        assert store.get_pending() is None

    def test_most_recent_returned(self, tmp_db: DatabaseEngine) -> None:
        store = PendingActionStore(tmp_db)
        store.store("p1", '{"a":1}', "First")
        store.store("p2", '{"a":2}', "Second")
        pending = store.get_pending()
        assert pending is not None
        assert pending["proposal_id"] == "p2"

    def test_within_30min_ttl_still_returns(
        self, tmp_db: DatabaseEngine,
    ) -> None:
        """Actions within 30-min TTL are still pending."""
        store = PendingActionStore(tmp_db)
        ts_20m = (
            datetime.now(tz=timezone.utc) - timedelta(minutes=20)
        ).isoformat()
        tmp_db.execute(
            "INSERT INTO _pending_actions "
            "(proposal_id, proposal_json, description, "
            "created_at, status) "
            "VALUES (?, ?, ?, ?, 'pending')",
            ["recent", '{}', "Recent action", ts_20m],
        )
        assert store.get_pending() is not None

    def test_get_recently_expired_returns_ttl_expired(
        self, tmp_db: DatabaseEngine,
    ) -> None:
        """get_recently_expired() returns actions past TTL."""
        store = PendingActionStore(tmp_db)
        ts_35m = (
            datetime.now(tz=timezone.utc) - timedelta(minutes=35)
        ).isoformat()
        tmp_db.execute(
            "INSERT INTO _pending_actions "
            "(proposal_id, proposal_json, description, "
            "created_at, status) "
            "VALUES (?, ?, ?, ?, 'pending')",
            ["expired-p", '{"tool":"test"}', "Expired", ts_35m],
        )
        expired = store.get_recently_expired()
        assert expired is not None
        assert expired["proposal_id"] == "expired-p"

    def test_get_recently_expired_none_when_active(
        self, tmp_db: DatabaseEngine,
    ) -> None:
        """get_recently_expired() returns None for active actions."""
        store = PendingActionStore(tmp_db)
        store.store("active-p", '{"tool":"test"}', "Active")
        assert store.get_recently_expired() is None

    def test_get_recently_expired_none_when_resolved(
        self, tmp_db: DatabaseEngine,
    ) -> None:
        """get_recently_expired() skips already-resolved actions."""
        store = PendingActionStore(tmp_db)
        ts_35m = (
            datetime.now(tz=timezone.utc) - timedelta(minutes=35)
        ).isoformat()
        tmp_db.execute(
            "INSERT INTO _pending_actions "
            "(proposal_id, proposal_json, description, "
            "created_at, status) "
            "VALUES (?, ?, ?, ?, 'confirmed')",
            ["done-p", '{}', "Done action", ts_35m],
        )
        assert store.get_recently_expired() is None


_FAKE_PROPOSAL = {
    "proposal_id": "test-uuid",
    "connector_id": "apple-calendar",
    "connector_name": "Apple Calendar",
    "tool_name": "create_event",
    "display_name": "Create Event",
    "arguments": {"title": "Meeting", "start": "2026-03-03T15:00"},
    "description": "Create Event: title='Meeting', start='2026-03-03T15:00'",
    "missing_params": [],
    "command": "node",
    "args": ["cal-mcp"],
}


def _make_stream_events(
    proposal: dict[str, Any] | None = None,
    answer: str = "",
) -> list[dict[str, Any]]:
    """Build a list of events as ask_stream() would yield."""
    events: list[dict[str, Any]] = [
        {"type": "context", "context_summary": "", "sources": []},
    ]
    if proposal is not None:
        events.append({"type": "action_proposal", "proposal": proposal})
    else:
        for token in answer.split(" "):
            events.append({"type": "token", "token": token + " "})
        events.append({"type": "done", "answer": answer})
    return events


class TestActionProposalFlow:
    """Test action detection → confirmation message flow."""

    def test_action_detected_sends_confirmation(
        self,
        tmp_db: DatabaseEngine,
        mock_brain: MagicMock,
    ) -> None:
        """When ask_stream yields action_proposal, a confirmation is sent."""
        _seed_raw_messages(tmp_db, "5511999999999")
        mock_brain.ask_stream.return_value = iter(
            _make_stream_events(proposal=_FAKE_PROPOSAL),
        )

        sent_messages: list[str] = []

        def _capture(to: str, msg: str) -> bool:
            sent_messages.append(msg)
            return True

        executor = MagicMock()
        handler = ReplyHandler(
            db_engine=tmp_db, brain_agent=mock_brain,
            phone="+5511999999999",
            send_fn=_capture,
            action_executor=executor,
        )
        handler.process_new_replies()

        # Should have sent a confirmation message (for the user reply msg).
        confirm_msgs = [
            m for m in sent_messages if "I can do this for you" in m
        ]
        assert len(confirm_msgs) >= 1
        assert "Create Event" in confirm_msgs[0]

        # Should have stored a pending action.
        store = PendingActionStore(tmp_db)
        pending = store.get_pending()
        assert pending is not None
        assert pending["proposal_id"] == "test-uuid"

    def test_missing_params_no_pending(
        self,
        tmp_db: DatabaseEngine,
        mock_brain: MagicMock,
    ) -> None:
        """Action with missing params sends info, no pending stored."""
        _seed_raw_messages(tmp_db, "5511999999999")
        bad_proposal = {**_FAKE_PROPOSAL, "missing_params": ["end_time"]}
        mock_brain.ask_stream.return_value = iter(
            _make_stream_events(proposal=bad_proposal),
        )

        sent_messages: list[str] = []

        def _capture(to: str, msg: str) -> bool:
            sent_messages.append(msg)
            return True

        executor = MagicMock()
        handler = ReplyHandler(
            db_engine=tmp_db, brain_agent=mock_brain,
            phone="+5511999999999",
            send_fn=_capture,
            action_executor=executor,
        )
        handler.process_new_replies()

        missing_msgs = [m for m in sent_messages if "need more" in m]
        assert len(missing_msgs) >= 1
        assert "end_time" in missing_msgs[0]

        store = PendingActionStore(tmp_db)
        assert store.get_pending() is None


class TestActionConfirmationFlow:
    """Test confirmation → execution and cancellation flows."""

    def _setup_pending(
        self, tmp_db: DatabaseEngine, phone: str = "5511999999999",
    ) -> None:
        """Seed a pending action and a confirmation reply message."""
        phone_jid = f"{phone}@s.whatsapp.net"
        tmp_db.execute(
            """
            CREATE TABLE IF NOT EXISTS raw_messages (
                id VARCHAR PRIMARY KEY,
                sender VARCHAR, sender_name VARCHAR,
                recipient VARCHAR, content TEXT,
                timestamp TIMESTAMPTZ, is_from_me BOOLEAN,
                chat_name VARCHAR, source VARCHAR DEFAULT 'whatsapp',
                metadata TEXT
            )
            """
        )
        now = datetime.now(tz=timezone.utc)
        tmp_db.execute(
            "INSERT INTO raw_messages "
            "(id, sender, sender_name, recipient, content, timestamp, "
            "is_from_me, chat_name) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [
                f"{phone_jid}:confirm_msg", "me", "me", phone_jid,
                "yes", now.isoformat(), True, phone_jid,
            ],
        )
        # Store a pending action
        store = PendingActionStore(tmp_db)
        import json
        store.store(
            "test-uuid",
            json.dumps(_FAKE_PROPOSAL),
            "Create Event: title='Meeting'",
        )

    def test_yes_executes_action(
        self, tmp_db: DatabaseEngine, mock_brain: MagicMock,
    ) -> None:
        """Replying 'yes' to pending action executes it."""
        self._setup_pending(tmp_db)

        sent_messages: list[str] = []

        def _capture(to: str, msg: str) -> bool:
            sent_messages.append(msg)
            return True

        @dataclass(frozen=True)
        class FakeResult:
            proposal_id: str = "test-uuid"
            status: str = "success"
            output: str = "Event created successfully"
            raw_result: list[dict[str, Any]] = field(
                default_factory=list,
            )
            error: str | None = None

        executor = MagicMock()
        executor.execute.return_value = FakeResult()
        sync_called: list[str] = []

        handler = ReplyHandler(
            db_engine=tmp_db, brain_agent=mock_brain,
            phone="+5511999999999",
            send_fn=_capture,
            action_executor=executor,
            sync_fn=lambda cid: sync_called.append(cid),
        )
        handler.process_new_replies()

        # Executor should have been called.
        executor.execute.assert_called_once()
        call_kwargs = executor.execute.call_args
        assert call_kwargs[1]["tool_name"] == "create_event"

        # Success message sent.
        done_msgs = [m for m in sent_messages if "Done!" in m]
        assert len(done_msgs) == 1

        # Re-sync triggered.
        assert sync_called == ["apple-calendar"]

        # Pending resolved.
        store = PendingActionStore(tmp_db)
        assert store.get_pending() is None

    def test_no_cancels_action(
        self, tmp_db: DatabaseEngine, mock_brain: MagicMock,
    ) -> None:
        """Replying 'no' cancels the pending action."""
        phone = "5511999999999"
        phone_jid = f"{phone}@s.whatsapp.net"
        tmp_db.execute(
            """
            CREATE TABLE IF NOT EXISTS raw_messages (
                id VARCHAR PRIMARY KEY,
                sender VARCHAR, sender_name VARCHAR,
                recipient VARCHAR, content TEXT,
                timestamp TIMESTAMPTZ, is_from_me BOOLEAN,
                chat_name VARCHAR, source VARCHAR DEFAULT 'whatsapp',
                metadata TEXT
            )
            """
        )
        now = datetime.now(tz=timezone.utc)
        tmp_db.execute(
            "INSERT INTO raw_messages "
            "(id, sender, sender_name, recipient, content, timestamp, "
            "is_from_me, chat_name) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [
                f"{phone_jid}:reject_msg", "me", "me", phone_jid,
                "no", now.isoformat(), True, phone_jid,
            ],
        )
        import json
        PendingActionStore(tmp_db).store(
            "test-uuid",
            json.dumps(_FAKE_PROPOSAL),
            "Create Event",
        )

        sent_messages: list[str] = []

        def _capture(to: str, msg: str) -> bool:
            sent_messages.append(msg)
            return True

        executor = MagicMock()
        handler = ReplyHandler(
            db_engine=tmp_db, brain_agent=mock_brain,
            phone=f"+{phone}",
            send_fn=_capture,
            action_executor=executor,
        )
        handler.process_new_replies()

        # Executor should NOT have been called.
        executor.execute.assert_not_called()

        # Cancel message sent.
        cancel_msgs = [m for m in sent_messages if "cancelled" in m]
        assert len(cancel_msgs) == 1

        # Pending resolved.
        store = PendingActionStore(tmp_db)
        assert store.get_pending() is None


class TestActionBackwardCompat:
    """Verify backward compatibility when no executor is provided."""

    @patch(
        "src.notifications.reply_handler.ReplyHandler._send_response",
        return_value=True,
    )
    def test_no_executor_uses_ask(
        self,
        mock_send: MagicMock,
        tmp_db: DatabaseEngine,
        mock_brain: MagicMock,
    ) -> None:
        """Without action_executor, uses ask() not ask_stream()."""
        _seed_raw_messages(tmp_db, "5511999999999")
        handler = ReplyHandler(
            db_engine=tmp_db, brain_agent=mock_brain,
            phone="+5511999999999",
        )
        handler.process_new_replies()

        # ask() should be called, ask_stream() should NOT.
        mock_brain.ask.assert_called()
        mock_brain.ask_stream.assert_not_called()


# ================================================================
# Multi-step action flow tests
# ================================================================


class TestIsBatchOrTemporal:
    """Test batch/temporal request detection."""

    @pytest.mark.parametrize(
        "text",
        [
            "delete all notes from yesterday",
            "Delete the new notes created yesterday",
            "remove every event from today",
            "delete todos from last 5 hours",
            "apague todas as notas de ontem",
            "delete all reminders from this week",
            "remove the recent notes",
            "delete the latest emails",
        ],
    )
    def test_detects_batch_temporal(self, text: str) -> None:
        assert _is_batch_or_temporal(text) is True

    @pytest.mark.parametrize(
        "text",
        [
            "delete the meeting with Sarah",
            "create a new note",
            "send a message to João",
            "what meetings do I have?",
            "schedule lunch at noon",
        ],
    )
    def test_rejects_single_actions(self, text: str) -> None:
        assert _is_batch_or_temporal(text) is False


class TestParseItemSelection:
    """Test item index parsing from user replies."""

    def test_single_index(self) -> None:
        assert _parse_item_selection("3", 5) == [2]

    def test_multiple_indices(self) -> None:
        result = _parse_item_selection("1, 3, 5", 5)
        assert result == [0, 2, 4]

    def test_space_separated(self) -> None:
        result = _parse_item_selection("1 3 5", 5)
        assert result == [0, 2, 4]

    def test_out_of_range_ignored(self) -> None:
        result = _parse_item_selection("1, 10", 5)
        assert result == [0]

    def test_not_a_selection(self) -> None:
        assert _parse_item_selection("yes", 5) is None
        assert _parse_item_selection("no", 5) is None
        assert _parse_item_selection(
            "what meetings do I have?", 5,
        ) is None

    def test_empty_string(self) -> None:
        assert _parse_item_selection("", 5) is None

    def test_all_out_of_range(self) -> None:
        assert _parse_item_selection("10, 20", 5) is None


@pytest.mark.skip(
    reason=(
        "Multi-step batch action *creation* is dead code in production. "
        "ReplyHandler._handle_multi_step_action (reply_handler.py:873) "
        "has no callers — the new flow routes through "
        "_ask_with_action_detection -> BrainAgent.ask_stream(), which "
        "only emits single-action proposals from _build_action_proposal "
        "(brain_agent.py:1613). Batch *confirmation* (1,3,5 selection) "
        "is still alive at reply_handler.py:736-745. "
        "See docs/CODEBASE_REVIEW.md §7 for the cleanup task."
    ),
)
class TestMultiStepActionFlow:
    """Test multi-step action: query → present → confirm → execute."""

    def _seed_and_build_handler(
        self,
        tmp_db: DatabaseEngine,
        mock_brain: MagicMock,
        user_msg: str = "delete all notes from yesterday",
    ) -> tuple[ReplyHandler, list[str], MagicMock]:
        """Helper: seed data, mock brain, build handler."""
        phone = "5511999999999"
        phone_jid = f"{phone}@s.whatsapp.net"
        tmp_db.execute(
            """
            CREATE TABLE IF NOT EXISTS raw_messages (
                id VARCHAR PRIMARY KEY,
                sender VARCHAR, sender_name VARCHAR,
                recipient VARCHAR, content TEXT,
                timestamp TIMESTAMPTZ, is_from_me BOOLEAN,
                chat_name VARCHAR,
                source VARCHAR DEFAULT 'whatsapp',
                metadata TEXT
            )
            """
        )
        now = datetime.now(tz=timezone.utc)
        tmp_db.execute(
            "INSERT INTO raw_messages "
            "(id, sender, sender_name, recipient, content, "
            "timestamp, is_from_me, chat_name) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [
                f"{phone_jid}:action_msg", "me", "me",
                phone_jid, user_msg,
                now.isoformat(), True, phone_jid,
            ],
        )

        sent: list[str] = []

        def _capture(to: str, msg: str) -> bool:
            sent.append(msg)
            return True

        executor = MagicMock()
        handler = ReplyHandler(
            db_engine=tmp_db,
            brain_agent=mock_brain,
            phone=f"+{phone}",
            send_fn=_capture,
            action_executor=executor,
        )
        return handler, sent, executor

    def test_batch_action_presents_candidates(
        self,
        tmp_db: DatabaseEngine,
        mock_brain: MagicMock,
    ) -> None:
        """Batch request queries candidates and presents them."""
        handler, sent, _ = self._seed_and_build_handler(
            tmp_db, mock_brain,
        )

        # Mock: action intent detected
        fake_action = MagicMock()
        fake_action.connector_id = "apple-notes"
        fake_action.connector_name = "Apple Notes"
        fake_action.tool_name = "delete_note"
        fake_action.display_name = "Delete Note"
        mock_brain.match_action_intent.return_value = fake_action

        # Mock: candidates found
        mock_brain.query_action_candidates.return_value = [
            {
                "title": "Shopping List",
                "created_at": "2026-03-02",
                "_table": "raw_notes",
            },
            {
                "title": "Meeting Notes",
                "created_at": "2026-03-02",
                "_table": "raw_notes",
            },
        ]
        mock_brain.format_candidates_message.return_value = (
            "I found 2 matching items:\n"
            "  1. title=Shopping List, created_at=2026-03-02\n"
            "  2. title=Meeting Notes, created_at=2026-03-02"
        )
        mock_brain._resolve_connector_command.return_value = (
            "node", ("notes-mcp",),
        )

        handler.process_new_replies()

        # Should present candidates, not execute
        assert any("I found 2 matching items" in m for m in sent)
        assert any("delete note" in m.lower() for m in sent)

        # Should store a batch pending action
        store = PendingActionStore(tmp_db)
        pending = store.get_pending()
        assert pending is not None
        import json
        proposal = json.loads(pending["proposal_json"])
        assert proposal["batch"] is True
        assert len(proposal["candidates"]) == 2

    def test_batch_action_serializes_datetime_candidates(
        self,
        tmp_db: DatabaseEngine,
        mock_brain: MagicMock,
    ) -> None:
        """Datetime objects in candidates are serialized to ISO strings.

        Regression: DuckDB returns datetime objects for TIMESTAMPTZ columns.
        json.dumps() would raise TypeError, silently skipping the pending
        action store while the candidates message was already sent.
        """
        handler, sent, _ = self._seed_and_build_handler(
            tmp_db, mock_brain,
        )

        fake_action = MagicMock()
        fake_action.connector_id = "apple-notes"
        fake_action.connector_name = "Apple Notes"
        fake_action.tool_name = "delete_note"
        fake_action.display_name = "Delete Note"
        mock_brain.match_action_intent.return_value = fake_action

        # Candidates with datetime objects (as DuckDB returns them)
        mock_brain.query_action_candidates.return_value = [
            {
                "title": "Shopping List",
                "created_at": datetime(2026, 3, 2, 19, 0, tzinfo=timezone.utc),
                "updated_at": datetime(2026, 3, 2, 19, 30, tzinfo=timezone.utc),
                "_table": "raw_notes",
            },
            {
                "title": "Meeting Notes",
                "created_at": datetime(2026, 3, 2, 18, 0, tzinfo=timezone.utc),
                "updated_at": datetime(2026, 3, 2, 18, 45, tzinfo=timezone.utc),
                "_table": "raw_notes",
            },
        ]
        mock_brain.format_candidates_message.return_value = (
            "I found 2 matching items:\n"
            "  1. title=Shopping List\n"
            "  2. title=Meeting Notes"
        )
        mock_brain._resolve_connector_command.return_value = (
            "node", ("notes-mcp",),
        )

        handler.process_new_replies()

        # Pending action must be stored (not silently skipped)
        store = PendingActionStore(tmp_db)
        pending = store.get_pending()
        assert pending is not None, (
            "Batch pending action was not stored — datetime serialization "
            "likely failed"
        )

        import json
        proposal = json.loads(pending["proposal_json"])
        assert proposal["batch"] is True
        assert len(proposal["candidates"]) == 2

        # Datetime fields must be ISO strings, not datetime objects
        for c in proposal["candidates"]:
            assert isinstance(c["created_at"], str)
            assert isinstance(c["updated_at"], str)
            # _table should be stripped
            assert "_table" not in c

    def test_no_candidates_informs_user(
        self,
        tmp_db: DatabaseEngine,
        mock_brain: MagicMock,
    ) -> None:
        """When no candidates found, user is informed."""
        handler, sent, _ = self._seed_and_build_handler(
            tmp_db, mock_brain,
        )

        fake_action = MagicMock()
        fake_action.connector_id = "apple-notes"
        fake_action.connector_name = "Apple Notes"
        fake_action.tool_name = "delete_note"
        fake_action.display_name = "Delete Note"
        mock_brain.match_action_intent.return_value = fake_action
        mock_brain.query_action_candidates.return_value = []

        handler.process_new_replies()

        assert any("found nothing" in m for m in sent)

    def test_single_candidate_falls_through(
        self,
        tmp_db: DatabaseEngine,
        mock_brain: MagicMock,
    ) -> None:
        """Single candidate falls through to regular ask_stream."""
        handler, sent, _ = self._seed_and_build_handler(
            tmp_db, mock_brain,
        )

        fake_action = MagicMock()
        fake_action.connector_id = "apple-notes"
        fake_action.connector_name = "Apple Notes"
        fake_action.tool_name = "delete_note"
        fake_action.display_name = "Delete Note"
        mock_brain.match_action_intent.return_value = fake_action
        mock_brain.query_action_candidates.return_value = [
            {
                "title": "Only Note",
                "created_at": "2026-03-02",
                "_table": "raw_notes",
            },
        ]
        # ask_stream returns a regular answer (no proposal)
        mock_brain.ask_stream.return_value = iter(
            _make_stream_events(answer="Here's what I found"),
        )

        handler.process_new_replies()

        # Should fall through to ask_stream, not present
        mock_brain.ask_stream.assert_called_once()

    def test_batch_confirm_executes_all_candidates(
        self,
        tmp_db: DatabaseEngine,
        mock_brain: MagicMock,
    ) -> None:
        """User confirms batch → all candidates executed sequentially.

        Regression: datetime in candidates broke json.dumps, so the
        pending action was never stored, and 'Yes' fell through to
        BrainAgent instead of executing the batch.
        """
        phone = "5511999999999"
        phone_jid = f"{phone}@s.whatsapp.net"
        tmp_db.execute(
            """
            CREATE TABLE IF NOT EXISTS raw_messages (
                id VARCHAR PRIMARY KEY,
                sender VARCHAR, sender_name VARCHAR,
                recipient VARCHAR, content TEXT,
                timestamp TIMESTAMPTZ, is_from_me BOOLEAN,
                chat_name VARCHAR,
                source VARCHAR DEFAULT 'whatsapp',
                metadata TEXT
            )
            """
        )
        now = datetime.now(tz=timezone.utc)
        # Insert both the action request AND the "Yes" confirmation
        tmp_db.execute(
            "INSERT INTO raw_messages "
            "(id, sender, sender_name, recipient, content, "
            "timestamp, is_from_me, chat_name) VALUES "
            "(?, ?, ?, ?, ?, ?, ?, ?), "
            "(?, ?, ?, ?, ?, ?, ?, ?)",
            [
                f"{phone_jid}:req", "me", "me", phone_jid,
                "delete all notes from yesterday",
                now.isoformat(), True, phone_jid,
                f"{phone_jid}:confirm", "me", "me", phone_jid,
                "Yes",
                (now + timedelta(seconds=30)).isoformat(),
                True, phone_jid,
            ],
        )

        sent: list[str] = []
        executor = MagicMock()

        def _capture(to: str, msg: str) -> bool:
            sent.append(msg)
            return True

        handler = ReplyHandler(
            db_engine=tmp_db,
            brain_agent=mock_brain,
            phone=f"+{phone}",
            send_fn=_capture,
            action_executor=executor,
        )

        # Mock action intent for the request message
        fake_action = MagicMock()
        fake_action.connector_id = "apple-notes"
        fake_action.connector_name = "Apple Notes"
        fake_action.tool_name = "delete_note"
        fake_action.display_name = "Delete Note"
        mock_brain.match_action_intent.return_value = fake_action

        # Candidates with datetime objects
        mock_brain.query_action_candidates.return_value = [
            {
                "title": "Note A",
                "created_at": datetime(2026, 3, 2, 10, tzinfo=timezone.utc),
                "_table": "raw_notes",
            },
            {
                "title": "Note B",
                "created_at": datetime(2026, 3, 2, 11, tzinfo=timezone.utc),
                "_table": "raw_notes",
            },
        ]
        mock_brain.format_candidates_message.return_value = (
            "1. title=Note A\n2. title=Note B"
        )
        mock_brain._resolve_connector_command.return_value = ("", ())

        # Mock successful execution
        result = MagicMock()
        result.status = "success"
        result.output = "Deleted"
        executor.execute.return_value = result

        handler.process_new_replies()

        # Both messages should be processed:
        # 1st → presents candidates  2nd → executes batch
        assert executor.execute.call_count == 2
        assert any("Working on it" in m for m in sent)
        assert any("Successfully completed" in m for m in sent)

    def test_non_batch_skips_multi_step(
        self,
        tmp_db: DatabaseEngine,
        mock_brain: MagicMock,
    ) -> None:
        """Non-batch request skips multi-step, uses ask_stream."""
        handler, sent, _ = self._seed_and_build_handler(
            tmp_db, mock_brain,
            user_msg="create a meeting with Sarah",
        )

        fake_action = MagicMock()
        fake_action.connector_id = "apple-calendar"
        mock_brain.match_action_intent.return_value = fake_action
        mock_brain.ask_stream.return_value = iter(
            _make_stream_events(proposal=_FAKE_PROPOSAL),
        )

        handler.process_new_replies()

        # Should NOT query candidates
        mock_brain.query_action_candidates.assert_not_called()
        # Should use ask_stream directly
        mock_brain.ask_stream.assert_called_once()


# ================================================================
# Expired action confirmation tests
# ================================================================


class TestExpiredActionConfirmation:
    """Test that 'yes' after TTL sends expiry notice, not LLM."""

    def test_yes_after_expiry_sends_expired_message(
        self,
        tmp_db: DatabaseEngine,
        mock_brain: MagicMock,
    ) -> None:
        """Replying 'yes' after TTL sends an expiry notice."""
        phone = "5511999999999"
        phone_jid = f"{phone}@s.whatsapp.net"
        tmp_db.execute(
            """
            CREATE TABLE IF NOT EXISTS raw_messages (
                id VARCHAR PRIMARY KEY,
                sender VARCHAR, sender_name VARCHAR,
                recipient VARCHAR, content TEXT,
                timestamp TIMESTAMPTZ, is_from_me BOOLEAN,
                chat_name VARCHAR,
                source VARCHAR DEFAULT 'whatsapp',
                metadata TEXT
            )
            """
        )
        now = datetime.now(tz=timezone.utc)
        tmp_db.execute(
            "INSERT INTO raw_messages "
            "(id, sender, sender_name, recipient, content, "
            "timestamp, is_from_me, chat_name) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [
                f"{phone_jid}:late_yes", "me", "me",
                phone_jid, "yes",
                now.isoformat(), True, phone_jid,
            ],
        )
        # Store a pending action 35 minutes old (expired).
        _store = PendingActionStore(tmp_db)
        ts_35m = (
            now - timedelta(minutes=35)
        ).isoformat()
        tmp_db.execute(
            "INSERT INTO _pending_actions "
            "(proposal_id, proposal_json, description, "
            "created_at, status) "
            "VALUES (?, ?, ?, ?, 'pending')",
            [
                "expired-uuid",
                json.dumps(_FAKE_PROPOSAL),
                "Create Event: title='Meeting'",
                ts_35m,
            ],
        )

        sent_messages: list[str] = []

        def _capture(to: str, msg: str) -> bool:
            sent_messages.append(msg)
            return True

        executor = MagicMock()
        handler = ReplyHandler(
            db_engine=tmp_db, brain_agent=mock_brain,
            phone=f"+{phone}",
            send_fn=_capture,
            action_executor=executor,
        )
        handler.process_new_replies()

        # Executor should NOT have been called.
        executor.execute.assert_not_called()
        # BrainAgent should NOT have been called.
        mock_brain.ask.assert_not_called()
        mock_brain.ask_stream.assert_not_called()
        # Should have sent an expiry message.
        expired_msgs = [
            m for m in sent_messages if "expired" in m
        ]
        assert len(expired_msgs) == 1
        assert "repeat your request" in expired_msgs[0]

    def test_non_confirmation_after_expiry_goes_to_brain(
        self,
        tmp_db: DatabaseEngine,
        mock_brain: MagicMock,
    ) -> None:
        """Non-confirmation text after TTL goes to brain query."""
        phone = "5511999999999"
        phone_jid = f"{phone}@s.whatsapp.net"
        tmp_db.execute(
            """
            CREATE TABLE IF NOT EXISTS raw_messages (
                id VARCHAR PRIMARY KEY,
                sender VARCHAR, sender_name VARCHAR,
                recipient VARCHAR, content TEXT,
                timestamp TIMESTAMPTZ, is_from_me BOOLEAN,
                chat_name VARCHAR,
                source VARCHAR DEFAULT 'whatsapp',
                metadata TEXT
            )
            """
        )
        now = datetime.now(tz=timezone.utc)
        tmp_db.execute(
            "INSERT INTO raw_messages "
            "(id, sender, sender_name, recipient, content, "
            "timestamp, is_from_me, chat_name) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [
                f"{phone_jid}:new_q", "me", "me",
                phone_jid, "What meetings do I have?",
                now.isoformat(), True, phone_jid,
            ],
        )
        # Store expired pending action.
        ts_35m = (
            now - timedelta(minutes=35)
        ).isoformat()
        PendingActionStore(tmp_db)
        tmp_db.execute(
            "INSERT INTO _pending_actions "
            "(proposal_id, proposal_json, description, "
            "created_at, status) "
            "VALUES (?, ?, ?, ?, 'pending')",
            [
                "expired-uuid",
                json.dumps(_FAKE_PROPOSAL),
                "Create Event",
                ts_35m,
            ],
        )

        sent_messages: list[str] = []

        def _capture(to: str, msg: str) -> bool:
            sent_messages.append(msg)
            return True

        handler = ReplyHandler(
            db_engine=tmp_db, brain_agent=mock_brain,
            phone=f"+{phone}",
            send_fn=_capture,
        )
        handler.process_new_replies()

        # BrainAgent.ask() should be called (no executor).
        mock_brain.ask.assert_called()


# ================================================================
# Context annotation tests
# ================================================================


class TestContextActionAnnotation:
    """Test that action proposals are annotated in context."""

    def test_action_proposals_annotated(
        self, tmp_db: DatabaseEngine,
    ) -> None:
        """Proposals are tagged as 'NOT executed' in context."""
        phone = "5511999999999"
        phone_jid = f"{phone}@s.whatsapp.net"
        tmp_db.execute(
            """
            CREATE TABLE IF NOT EXISTS raw_messages (
                id VARCHAR PRIMARY KEY,
                sender VARCHAR, sender_name VARCHAR,
                recipient VARCHAR, content TEXT,
                timestamp TIMESTAMPTZ, is_from_me BOOLEAN,
                chat_name VARCHAR,
                source VARCHAR DEFAULT 'whatsapp',
                metadata TEXT
            )
            """
        )
        now = datetime.now(tz=timezone.utc)
        tmp_db.execute(
            "INSERT INTO raw_messages "
            "(id, sender, sender_name, recipient, content, "
            "timestamp, is_from_me, chat_name) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [
                f"{phone_jid}:proposal1", "me", "me",
                phone_jid,
                f"{BRAIN_PREFIX}I can do this for you:\n\n"
                "  Create Event: title='Meeting'\n\n"
                'Reply "yes" to confirm or "no" to cancel.',
                now.isoformat(), True, phone_jid,
            ],
        )
        context = _get_conversation_context(tmp_db, phone)
        assert "past action proposal, NOT executed" in context

    def test_regular_brain_messages_not_annotated(
        self, tmp_db: DatabaseEngine,
    ) -> None:
        """Regular brain messages keep the [Arandu] tag."""
        phone = "5511999999999"
        phone_jid = f"{phone}@s.whatsapp.net"
        tmp_db.execute(
            """
            CREATE TABLE IF NOT EXISTS raw_messages (
                id VARCHAR PRIMARY KEY,
                sender VARCHAR, sender_name VARCHAR,
                recipient VARCHAR, content TEXT,
                timestamp TIMESTAMPTZ, is_from_me BOOLEAN,
                chat_name VARCHAR,
                source VARCHAR DEFAULT 'whatsapp',
                metadata TEXT
            )
            """
        )
        now = datetime.now(tz=timezone.utc)
        tmp_db.execute(
            "INSERT INTO raw_messages "
            "(id, sender, sender_name, recipient, content, "
            "timestamp, is_from_me, chat_name) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [
                f"{phone_jid}:brain_msg", "me", "me",
                phone_jid,
                f"{BRAIN_PREFIX}You have 3 meetings today.",
                now.isoformat(), True, phone_jid,
            ],
        )
        context = _get_conversation_context(tmp_db, phone)
        assert "[Arandu]:" in context
        assert "NOT executed" not in context

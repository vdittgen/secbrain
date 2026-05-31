"""Tests for MessageEvaluator.

The LLM step is delegated to :class:`MessageEvaluatorAgent`
(pydantic-ai) and the triage step to :class:`TriageAgent`. Tests mock
each SBAgent's convenience method directly via monkeypatch; the
``stub_triage`` fixture controls the triage outcome and
``stub_evaluate`` controls the topic-aware evaluation.

sensitivity_tier: N/A — test infrastructure
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest
from src.agents.core.output_types import (
    MessageNotificationBatch,
    MessageNotificationDraft,
    TriageBatch,
)
from src.agents.core.output_types import (
    TriageDecision as TriageVerdict,
)
from src.agents.message_eval import (
    MESSAGE_CONNECTORS,
    MessageEvaluator,
    MessageNotification,
    format_realtime_notification,
)
from src.agents.message_eval.persistence import _CONNECTOR_TABLES
from src.core.sqlite.engine import DatabaseEngine

# ================================================================
# Fixtures
# ================================================================


@pytest.fixture()
def tmp_db(tmp_path: Path) -> DatabaseEngine:
    """Fresh SQLite engine backed by a temp file."""
    db_path = tmp_path / "test_msg_eval.db"
    engine = DatabaseEngine(db_path=db_path)
    yield engine
    engine.close()


@pytest.fixture()
def stub_triage(monkeypatch):
    """Monkey-patch ``TriageAgent.triage`` with a fail-open default.

    Default behaviour: keep every triaged message. Tests can override
    via ``stub_triage.return_value`` or ``stub_triage.side_effect``.
    The patched method receives the ``TriageMessage`` list so tests can
    also assert on the inputs.
    """
    fake = MagicMock(
        side_effect=lambda messages: TriageBatch(
            decisions=[
                TriageVerdict(
                    message_id=m.message_id, keep=True, reason="",
                )
                for m in messages
            ],
        ),
    )

    def _bound_triage(self, messages):  # noqa: ARG001
        return fake(messages)

    monkeypatch.setattr(
        "src.agents.triage.agent.TriageAgent.triage", _bound_triage,
    )
    return fake


@pytest.fixture()
def stub_evaluate(monkeypatch):
    """Monkey-patch ``MessageEvaluatorAgent.evaluate`` with an empty default.

    Tests set ``stub_evaluate.return_value`` to a
    :class:`MessageNotificationBatch` to drive specific scenarios. The
    patched method captures the call so tests can also assert on the
    messages, topics, today_events, and existing_pending_ids inputs.
    """
    fake = MagicMock(return_value=MessageNotificationBatch(notifications=[]))

    def _bound_evaluate(
        self, *, messages, topics=None,
        today_events=None, existing_pending_ids=None,
    ):  # noqa: ARG001
        result = fake(
            messages=messages,
            topics=topics,
            today_events=today_events,
            existing_pending_ids=existing_pending_ids,
        )
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(
        "src.agents.message_eval.agent.MessageEvaluatorAgent.evaluate",
        _bound_evaluate,
    )
    return fake


@pytest.fixture()
def evaluator(
    tmp_db: DatabaseEngine,
    stub_triage,  # noqa: ARG001 (autoused via monkeypatch)
    stub_evaluate,  # noqa: ARG001
) -> MessageEvaluator:
    """MessageEvaluator with stubbed SBAgents."""
    return MessageEvaluator(db_engine=tmp_db)


@pytest.fixture()
def evaluator_bare(tmp_db: DatabaseEngine) -> MessageEvaluator:
    """MessageEvaluator without SBAgent stubs — persistence-only tests."""
    return MessageEvaluator(db_engine=tmp_db)


def _seed_messages(db: DatabaseEngine) -> None:
    """Create raw_messages table with test data."""
    db.execute("""
        CREATE TABLE IF NOT EXISTS raw_messages (
            id TEXT PRIMARY KEY,
            source TEXT,
            sender TEXT,
            sender_name TEXT,
            content TEXT,
            timestamp TEXT,
            is_from_me INTEGER,
            chat_name TEXT,
            is_group INTEGER,
            sensitivity_tier INTEGER DEFAULT 2
        )
    """)
    db.execute("""
        INSERT INTO raw_messages
        (id, source, sender, sender_name, content, timestamp,
         is_from_me, chat_name, is_group)
        VALUES
        ('msg1', 'whatsapp', '5511@s.whatsapp.net', 'Sarah',
         'Can we meet tomorrow at 3pm?',
         datetime('now', '-30 minutes'),
         0, 'Sarah', 0),
        ('msg2', 'whatsapp', '5522@s.whatsapp.net', 'Carlos',
         'The deadline moved to Friday',
         datetime('now', '-1 hours'),
         0, 'Carlos', 0),
        ('msg3', 'whatsapp', '5533@s.whatsapp.net', 'Bot',
         'ok thanks',
         datetime('now', '-2 hours'),
         0, 'Bot', 0),
        ('msg_own', 'whatsapp', 'me', 'Me',
         'Sure, will do',
         datetime('now', '-10 minutes'),
         1, 'Sarah', 0),
        ('msg_group', 'whatsapp', '5544@s.whatsapp.net', 'Ana',
         'Has anyone seen this?',
         datetime('now', '-1 hours'),
         0, 'Group Chat', 1),
        ('msg_old', 'whatsapp', '5555@s.whatsapp.net', 'Old',
         'This is from yesterday',
         datetime('now', '-10 hours'),
         0, 'Old Contact', 0)
    """)


def _seed_emails(db: DatabaseEngine) -> None:
    """Create raw_emails table with test data."""
    db.execute("""
        CREATE TABLE IF NOT EXISTS raw_emails (
            id TEXT PRIMARY KEY,
            subject TEXT,
            from_address TEXT,
            to_addresses TEXT,
            date TEXT,
            body_preview TEXT,
            folder TEXT,
            is_read INTEGER,
            sensitivity_tier INTEGER DEFAULT 2
        )
    """)
    db.execute("""
        INSERT INTO raw_emails
        (id, subject, from_address, to_addresses, date,
         body_preview, folder, is_read)
        VALUES
        ('email1', 'Project Update', 'boss@corp.com',
         'me@corp.com',
         datetime('now', '-1 hours'),
         'Please review the attached report',
         'INBOX', 0),
        ('email2', 'Newsletter', 'noreply@news.com',
         'me@corp.com',
         datetime('now', '-2 hours'),
         'Your weekly digest',
         'INBOX', 1)
    """)


def _seed_mart_contact_summary(db: DatabaseEngine) -> None:
    """Create mart_contact_summary with topic data."""
    db.execute("""
        CREATE TABLE IF NOT EXISTS mart_contact_summary (
            contact_name TEXT PRIMARY KEY,
            top_topic TEXT,
            max_topic_importance REAL,
            active_topics_json TEXT,
            notification_priority REAL,
            messages_7d INTEGER DEFAULT 0
        )
    """)
    db.execute("""
        INSERT INTO mart_contact_summary
        (contact_name, top_topic, max_topic_importance,
         active_topics_json, notification_priority, messages_7d)
        VALUES
        ('Sarah', 'construction project', 8.0,
         '[{"topic": "construction project"}, {"topic": "Q2 planning"}]',
         9.0, 15),
        ('Carlos', 'deadline discussion', 6.0,
         '[{"topic": "deadline discussion"}]',
         5.0, 8),
        ('Maria', 'father cancer treatment', 9.0,
         '[{"topic": "father cancer treatment"}]',
         10.0, 22)
    """)


def _seed_calendar_events(db: DatabaseEngine) -> None:
    """Create calendar events for today."""
    db.execute("""
        CREATE TABLE IF NOT EXISTS raw_calendar_events (
            id TEXT PRIMARY KEY,
            title TEXT,
            description TEXT,
            start_time TEXT,
            end_time TEXT,
            location TEXT,
            attendees TEXT,
            is_all_day INTEGER DEFAULT 0,
            sensitivity_tier INTEGER DEFAULT 2
        )
    """)
    db.execute("""
        INSERT INTO raw_calendar_events
        (id, title, start_time, end_time, attendees)
        VALUES
        ('evt1', 'Q2 Planning Session',
         datetime(date('now'), '+10 hours'),
         datetime(date('now'), '+11 hours'),
         'Sarah, Carlos, Ana')
    """)


def _seed_pending_replies(db: DatabaseEngine) -> None:
    """Create pending replies table with existing entries."""
    db.execute("""
        CREATE TABLE IF NOT EXISTS _pending_replies (
            id TEXT PRIMARY KEY,
            message_id TEXT NOT NULL,
            source TEXT NOT NULL,
            contact_name TEXT NOT NULL,
            domain TEXT NOT NULL,
            preview TEXT,
            importance INTEGER DEFAULT 5,
            reason TEXT,
            message_at TEXT NOT NULL,
            detected_at TEXT DEFAULT (datetime('now')),
            dismissed_at TEXT,
            notified_at TEXT,
            sensitivity_tier INTEGER DEFAULT 2
        )
    """)
    db.execute("""
        INSERT INTO _pending_replies
        (id, message_id, source, contact_name, domain,
         message_at)
        VALUES
        ('pr1', 'msg_already_flagged', 'whatsapp', 'OldPerson',
         'personal', datetime('now', '-1 hours'))
    """)


# ================================================================
# Table creation tests
# ================================================================


class TestTableCreation:
    """Verify table setup works correctly."""

    def test_ensure_tables_creates_schema(
        self, evaluator: MessageEvaluator, tmp_db: DatabaseEngine,
    ) -> None:
        """Tables are created on init."""
        rows = tmp_db.query("""
            SELECT name FROM sqlite_master
            WHERE type = 'table' AND name IN (
                '_evaluated_messages', '_message_notifications'
            )
            ORDER BY name
        """)
        names = [r["name"] for r in rows]
        assert "_evaluated_messages" in names
        assert "_message_notifications" in names

    def test_readonly_mode_skips_creation(
        self, tmp_path: Path,
    ) -> None:
        """Read-only DB doesn't crash on table creation."""
        db_path = tmp_path / "readonly_test.db"
        # Create the DB first in write mode
        with DatabaseEngine(db_path=db_path) as db:
            evaluator = MessageEvaluator(
                db_engine=db,
            )
            assert evaluator is not None


# ================================================================
# Empty / no-op cases
# ================================================================


class TestNoOpCases:
    """Verify correct handling of empty/no-op scenarios."""

    def test_no_messages_returns_empty(
        self, evaluator: MessageEvaluator,
    ) -> None:
        """No messages table → empty result."""
        result = evaluator.evaluate_new_messages(
            "whatsapp", "raw_messages",
        )
        assert result == []

    def test_invalid_table_returns_empty(
        self, evaluator: MessageEvaluator,
    ) -> None:
        """Invalid table name → empty result."""
        result = evaluator.evaluate_new_messages(
            "whatsapp", "raw_contacts",
        )
        assert result == []


# ================================================================
# Message filtering tests
# ================================================================


class TestMessageFiltering:
    """Verify SQL pre-filtering of messages."""

    def test_skips_own_messages(
        self, evaluator: MessageEvaluator,
        tmp_db: DatabaseEngine,

    ) -> None:
        """Own messages (is_from_me=true) are filtered out."""
        _seed_messages(tmp_db)

        # LLM returns empty → all candidates go to _evaluated_messages

        evaluator.evaluate_new_messages("whatsapp", "raw_messages")

        # Check that msg_own is NOT in evaluated (filtered by SQL)
        rows = tmp_db.query("""
            SELECT message_id FROM _evaluated_messages
        """)
        ids = {r["message_id"] for r in rows}
        assert "msg_own" not in ids

    def test_inactive_group_messages_filtered_by_sql(
        self, evaluator: MessageEvaluator,
        tmp_db: DatabaseEngine,

    ) -> None:
        """Groups the user never posts in are SQL-filtered.

        The user has only sent in the ``Sarah`` chat in the seed,
        so ``Group Chat`` (msg_group) is excluded before triage.
        """
        _seed_messages(tmp_db)

        evaluator.evaluate_new_messages("whatsapp", "raw_messages")

        rows = tmp_db.query("""
            SELECT message_id FROM _evaluated_messages
        """)
        ids = {r["message_id"] for r in rows}
        assert "msg_group" not in ids

    def test_active_group_messages_reach_triage(
        self, evaluator: MessageEvaluator,
        tmp_db: DatabaseEngine,

    ) -> None:
        """Groups where the user has posted reach triage.

        Seed an own-message in ``Group Chat`` so it qualifies as
        active, then confirm msg_group is in _evaluated_messages.
        """
        _seed_messages(tmp_db)
        tmp_db.execute(
            "INSERT INTO raw_messages "
            "(id, source, sender, sender_name, content, timestamp,"
            " is_from_me, chat_name, is_group) "
            "VALUES (?, 'whatsapp', 'me', 'Me', ?, "
            "datetime('now', '-2 days'), 1, 'Group Chat', 1)",
            ["msg_group_own", "yes I agree"],
        )

        evaluator.evaluate_new_messages("whatsapp", "raw_messages")

        rows = tmp_db.query(
            "SELECT message_id FROM _evaluated_messages",
        )
        ids = {r["message_id"] for r in rows}
        assert "msg_group" in ids

    def test_skips_old_messages(
        self, evaluator: MessageEvaluator,
        tmp_db: DatabaseEngine,

    ) -> None:
        """Messages older than 4 hours are filtered out."""
        _seed_messages(tmp_db)

        evaluator.evaluate_new_messages("whatsapp", "raw_messages")

        rows = tmp_db.query("""
            SELECT message_id FROM _evaluated_messages
        """)
        ids = {r["message_id"] for r in rows}
        assert "msg_old" not in ids

    def test_skips_already_evaluated(
        self, evaluator: MessageEvaluator,
        tmp_db: DatabaseEngine,

    ) -> None:
        """Messages already in _evaluated_messages are skipped."""
        _seed_messages(tmp_db)

        # Pre-mark msg1 as evaluated
        tmp_db.execute("""
            INSERT INTO _evaluated_messages
            (message_id, source_table, connector_id)
            VALUES ('msg1', 'raw_messages', 'whatsapp')
        """)


        evaluator.evaluate_new_messages("whatsapp", "raw_messages")

        # msg1 should still only appear once
        rows = tmp_db.query("""
            SELECT COUNT(*) as cnt
            FROM _evaluated_messages
            WHERE message_id = 'msg1'
        """)
        assert rows[0]["cnt"] == 1

    def test_email_filtering(
        self, evaluator: MessageEvaluator,
        tmp_db: DatabaseEngine,

    ) -> None:
        """SQL only filters by recency now — triage decides relevance.

        ``is_read`` is no longer checked at the SQL layer; the triager
        is responsible for dropping newsletters/promo regardless of
        read state.  The empty chat_json return below causes triage to
        fall open, so both emails reach _evaluated_messages.
        """
        _seed_emails(tmp_db)

        evaluator.evaluate_new_messages(
            "apple-mail", "raw_emails",
        )

        rows = tmp_db.query("""
            SELECT message_id FROM _evaluated_messages
        """)
        ids = {r["message_id"] for r in rows}
        assert "email1" in ids
        assert "email2" in ids


# ================================================================
# Triage integration — replaces the deleted TestPreFilterScoring
# ================================================================


class TestTriageIntegration:
    """Verify AI triage drops trash before the topic-aware LLM call."""

    def test_triage_drops_promo_before_eval(
        self,
        tmp_db: DatabaseEngine,
        stub_triage,
        stub_evaluate,
    ) -> None:
        """When triage returns keep=False, the message never reaches
        the topic-aware LLM evaluation prompt."""
        _seed_messages(tmp_db)
        _seed_mart_contact_summary(tmp_db)

        # Override the default fail-open triage with explicit verdicts.
        stub_triage.side_effect = lambda messages: TriageBatch(
            decisions=[
                TriageVerdict(
                    message_id=m.message_id,
                    keep=m.message_id in {"msg1", "msg2"},
                    reason="kept" if m.message_id in {"msg1", "msg2"}
                    else "filtered",
                    is_ack_only=m.message_id == "msg3",
                )
                for m in messages
            ],
        )

        evaluator = MessageEvaluator(db_engine=tmp_db)
        evaluator.evaluate_new_messages("whatsapp", "raw_messages")

        # The evaluation call only sees the kept messages — the
        # triaged-out content (msg3 ack, msg_group lurker) must not
        # appear in the messages payload.
        assert stub_evaluate.call_count == 1
        sent_messages = stub_evaluate.call_args.kwargs["messages"]
        sent_contents = " ".join(m["content"] for m in sent_messages)
        assert "ok thanks" not in sent_contents
        assert "Has anyone seen this?" not in sent_contents
        assert "Can we meet tomorrow at 3pm?" in sent_contents

    def test_triage_cache_short_circuits_second_run(
        self,
        tmp_db: DatabaseEngine,
        stub_triage,
        stub_evaluate,  # noqa: ARG002
    ) -> None:
        """A second evaluation cycle reuses _triage_log entries."""
        _seed_messages(tmp_db)
        stub_triage.side_effect = lambda messages: TriageBatch(
            decisions=[
                TriageVerdict(
                    message_id=m.message_id,
                    keep=m.message_id in {"msg1", "msg2"},
                    reason="",
                    is_ack_only=m.message_id == "msg3",
                )
                for m in messages
            ],
        )

        evaluator = MessageEvaluator(db_engine=tmp_db)
        evaluator.evaluate_new_messages("whatsapp", "raw_messages")

        rows = tmp_db.query("SELECT message_id, keep FROM _triage_log")
        cached = {r["message_id"]: bool(r["keep"]) for r in rows}
        assert cached["msg1"] is True
        assert cached["msg3"] is False


# ================================================================
# Context building tests
# ================================================================


class TestContextBuilding:
    """Verify context is gathered from existing tables."""

    def test_gathers_topic_contacts(
        self, evaluator: MessageEvaluator,
        tmp_db: DatabaseEngine,
    ) -> None:
        """Topic contacts from mart_contact_summary are fetched."""
        _seed_mart_contact_summary(tmp_db)
        context = evaluator._build_evaluation_context()

        tc = context["topic_contacts"]
        assert len(tc) >= 2
        assert "sarah" in tc
        assert tc["sarah"]["importance"] == 8.0
        assert "maria" in tc
        assert tc["maria"]["importance"] == 9.0

    def test_gathers_today_events(
        self, evaluator: MessageEvaluator,
        tmp_db: DatabaseEngine,
    ) -> None:
        """Today's events are fetched."""
        _seed_calendar_events(tmp_db)
        context = evaluator._build_evaluation_context()

        events = context["today_events"]
        assert len(events) == 1
        assert "Q2 Planning" in events[0]["title"]

    def test_gathers_existing_pending_ids(
        self, evaluator: MessageEvaluator,
        tmp_db: DatabaseEngine,
    ) -> None:
        """Already-flagged pending reply IDs are collected."""
        _seed_pending_replies(tmp_db)
        context = evaluator._build_evaluation_context()

        pending = context["existing_pending_ids"]
        assert "msg_already_flagged" in pending

    def test_empty_tables_graceful(
        self, evaluator: MessageEvaluator,
    ) -> None:
        """Missing tables don't crash context building."""
        context = evaluator._build_evaluation_context()
        assert context["topic_contacts"] == {}
        assert context["today_events"] == []
        assert context["existing_pending_ids"] == set()


# ================================================================
# LLM evaluation tests
# ================================================================


class TestLLMEvaluation:
    """Verify the batch LLM evaluation flow."""

    def test_batch_llm_evaluation_success(
        self, evaluator: MessageEvaluator,
        tmp_db: DatabaseEngine,
        stub_evaluate,
    ) -> None:
        """Agent returns drafts → notifications created."""
        _seed_messages(tmp_db)
        _seed_mart_contact_summary(tmp_db)

        stub_evaluate.return_value = MessageNotificationBatch(
            notifications=[
                MessageNotificationDraft(
                    message_id="msg1",
                    notification_type="topic_action",
                    importance=8,
                    domain="work",
                    summary="Sarah wants to meet tomorrow",
                    related_to="Q2 Planning",
                ),
            ],
        )

        results = evaluator.evaluate_new_messages(
            "whatsapp", "raw_messages",
        )

        assert len(results) == 1
        assert results[0].notification_type == "topic_action"
        assert results[0].importance == 8
        assert results[0].domain == "work"
        assert "Sarah" in results[0].summary

    def test_batch_llm_evaluation_failure_non_fatal(
        self, evaluator: MessageEvaluator,
        tmp_db: DatabaseEngine,
        stub_evaluate,
    ) -> None:
        """Agent failure → empty result, no crash."""
        _seed_messages(tmp_db)
        stub_evaluate.side_effect = RuntimeError("agent down")

        results = evaluator.evaluate_new_messages(
            "whatsapp", "raw_messages",
        )

        assert results == []

    def test_notification_threshold_is_7(
        self, evaluator: MessageEvaluator,
        tmp_db: DatabaseEngine,
        stub_evaluate,
    ) -> None:
        """Only importance >= 7 is returned (filtered post-agent)."""
        _seed_messages(tmp_db)
        _seed_mart_contact_summary(tmp_db)

        stub_evaluate.return_value = MessageNotificationBatch(
            notifications=[
                MessageNotificationDraft(
                    message_id="msg1",
                    notification_type="topic_enrichment",
                    importance=6,
                    domain="personal",
                    summary="Below threshold item",
                ),
                MessageNotificationDraft(
                    message_id="msg2",
                    notification_type="topic_action",
                    importance=8,
                    domain="work",
                    summary="High importance item",
                ),
            ],
        )

        results = evaluator.evaluate_new_messages(
            "whatsapp", "raw_messages",
        )

        # Only importance >= 7 should appear
        for r in results:
            assert r.importance >= 7
        # The importance=6 item should be filtered out
        summaries = [r.summary for r in results]
        assert "Below threshold item" not in summaries


# ================================================================
# Dedup tests
# ================================================================


class TestDedup:
    """Verify dedup via _evaluated_messages table."""

    def test_all_candidates_marked_evaluated(
        self, evaluator: MessageEvaluator,
        tmp_db: DatabaseEngine,

    ) -> None:
        """After evaluation, all candidates are in _evaluated_messages."""
        _seed_messages(tmp_db)

        evaluator.evaluate_new_messages("whatsapp", "raw_messages")

        rows = tmp_db.query("""
            SELECT message_id FROM _evaluated_messages
        """)
        ids = {r["message_id"] for r in rows}
        # msg1, msg2, msg3 should be there (recent, not own)
        assert "msg1" in ids
        assert "msg2" in ids
        assert "msg3" in ids

    def test_dedup_across_calls(
        self, evaluator: MessageEvaluator,
        tmp_db: DatabaseEngine,
        stub_evaluate,
    ) -> None:
        """Second call skips already-evaluated messages."""
        _seed_messages(tmp_db)

        # First call
        evaluator.evaluate_new_messages("whatsapp", "raw_messages")
        first_count = len(tmp_db.query(
            "SELECT * FROM _evaluated_messages",
        ))

        # Second call — no new messages
        stub_evaluate.reset_mock()
        evaluator.evaluate_new_messages("whatsapp", "raw_messages")

        second_count = len(tmp_db.query(
            "SELECT * FROM _evaluated_messages",
        ))
        assert second_count == first_count

        # Agent should not have been called the second time (no candidates).
        assert stub_evaluate.call_count == 0

    def test_notification_stored(
        self, evaluator: MessageEvaluator,
        tmp_db: DatabaseEngine,
        stub_evaluate,
    ) -> None:
        """Notifications are stored in _message_notifications."""
        _seed_messages(tmp_db)
        _seed_mart_contact_summary(tmp_db)

        stub_evaluate.return_value = MessageNotificationBatch(
            notifications=[
                MessageNotificationDraft(
                    message_id="msg1",
                    notification_type="topic_action",
                    importance=8,
                    domain="work",
                    summary="Sarah wants to meet",
                ),
            ],
        )

        evaluator.evaluate_new_messages("whatsapp", "raw_messages")

        rows = tmp_db.query("""
            SELECT * FROM _message_notifications
        """)
        assert len(rows) == 1
        assert rows[0]["notification_type"] == "topic_action"
        assert rows[0]["importance"] == 8


# Digest tests removed in Phase F1: MessageEvaluator.generate_digest()
# was deleted along with its free-form ``self._llm.chat(...)`` call.
# The method had no production callers and was only exercised here;
# any future digest UX should use BrainAgentV2.ask() or a dedicated
# SBAgent.


# ================================================================
# Notification formatting tests
# ================================================================


class TestNotificationFormatting:
    """Verify notification message formatting."""

    def test_format_topic_action_notification(self) -> None:
        """Topic action notifications are formatted correctly."""
        items = [
            MessageNotification(
                id="n1",
                notification_type="topic_action",
                importance=8,
                summary="Reply to Sarah about meeting",
                contacts=["Sarah"],
            ),
        ]
        msg = format_realtime_notification(items)
        assert "Action Required:" in msg
        assert "Sarah" in msg
        assert "Reply to Sarah" in msg

    def test_format_topic_enrichment_notification(self) -> None:
        """Topic enrichment notifications are formatted correctly."""
        items = [
            MessageNotification(
                id="n2",
                notification_type="topic_enrichment",
                importance=7,
                summary="Deadline moved to Friday",
                contacts=["Carlos"],
            ),
        ]
        msg = format_realtime_notification(items)
        assert "New Info:" in msg
        assert "Carlos" in msg
        assert "Deadline moved" in msg

    def test_format_mixed_notification(self) -> None:
        """Mixed action+enrichment notifications formatted."""
        items = [
            MessageNotification(
                id="n1",
                notification_type="topic_action",
                importance=8,
                summary="Reply to Sarah",
                contacts=["Sarah"],
            ),
            MessageNotification(
                id="n2",
                notification_type="topic_enrichment",
                importance=7,
                summary="Deadline info",
                contacts=["Carlos"],
            ),
        ]
        msg = format_realtime_notification(items)
        assert "Action Required:" in msg
        assert "New Info:" in msg


# ================================================================
# Constants tests
# ================================================================


class TestConstants:
    """Verify module constants are correct."""

    def test_message_connectors(self) -> None:
        """MESSAGE_CONNECTORS has expected values."""
        assert "whatsapp" in MESSAGE_CONNECTORS
        assert "apple-messages" in MESSAGE_CONNECTORS
        assert "apple-mail" in MESSAGE_CONNECTORS
        assert "filesystem" not in MESSAGE_CONNECTORS

    def test_connector_tables(self) -> None:
        """_CONNECTOR_TABLES maps correctly."""
        assert _CONNECTOR_TABLES["whatsapp"] == ["raw_messages"]
        assert _CONNECTOR_TABLES["apple-mail"] == ["raw_emails"]

"""Tests for topic_loader shared utility.

sensitivity_tier: N/A — test infrastructure
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from src.core.sqlite.engine import DatabaseEngine
from src.core.topic_loader import (
    get_topic_contacts_for_prompt,
    load_group_engagement,
    load_pending_reply_ids,
    load_today_events,
    load_topic_contacts,
)


@pytest.fixture()
def tmp_db(tmp_path: Path) -> DatabaseEngine:
    """Fresh DB engine backed by a temp file."""
    db_path = tmp_path / "test_topic_loader.duckdb"
    engine = DatabaseEngine(db_path=db_path)
    yield engine
    engine.close()


def _seed_mart_contact_summary(db: DatabaseEngine) -> None:
    """Create mart_contact_summary with test data."""
    db.execute("""
        CREATE TABLE IF NOT EXISTS mart_contact_summary (
            contact_name VARCHAR,
            top_topic VARCHAR,
            max_topic_importance INTEGER,
            active_topics_json TEXT,
            notification_priority INTEGER,
            messages_7d INTEGER
        )
    """)
    db.execute(
        "INSERT INTO mart_contact_summary VALUES "
        "(?, ?, ?, ?, ?, ?)",
        [
            "Maria",
            "Father cancer treatment",
            9,
            json.dumps([
                {"topic": "Father cancer treatment"},
                {"topic": "Family reunion"},
            ]),
            90,
            15,
        ],
    )
    db.execute(
        "INSERT INTO mart_contact_summary VALUES "
        "(?, ?, ?, ?, ?, ?)",
        [
            "Samuel",
            "Construction project",
            6,
            json.dumps([
                {"topic": "Construction project"},
            ]),
            60,
            8,
        ],
    )
    db.execute(
        "INSERT INTO mart_contact_summary VALUES "
        "(?, ?, ?, ?, ?, ?)",
        ["João", "Weekend plans", 3, None, 20, 5],
    )


def _seed_group_messages(db: DatabaseEngine) -> None:
    """Create raw_messages with group data."""
    db.execute("""
        CREATE TABLE IF NOT EXISTS raw_messages (
            id VARCHAR PRIMARY KEY,
            source VARCHAR,
            sender VARCHAR,
            content TEXT,
            timestamp TEXT,
            is_group INTEGER,
            is_from_me INTEGER,
            chat_name VARCHAR
        )
    """)
    # Small engaged group: 3 members, user sent 6
    for i in range(6):
        db.execute(
            "INSERT INTO raw_messages VALUES "
            "(?, ?, ?, ?, ?, ?, ?, ?)",
            [
                f"g1-{i}",
                "whatsapp",
                "me",
                f"msg {i}",
                "2025-06-01T10:00:00Z",
                1,
                1,
                "Work Team",
            ],
        )
    for i in range(4):
        db.execute(
            "INSERT INTO raw_messages VALUES "
            "(?, ?, ?, ?, ?, ?, ?, ?)",
            [
                f"g1-other-{i}",
                "whatsapp",
                f"person{i}",
                f"reply {i}",
                "2025-06-01T10:00:00Z",
                1,
                0,
                "Work Team",
            ],
        )
    # Large lurk group: 20 members, user sent 0
    for i in range(20):
        db.execute(
            "INSERT INTO raw_messages VALUES "
            "(?, ?, ?, ?, ?, ?, ?, ?)",
            [
                f"g2-{i}",
                "whatsapp",
                f"stranger{i}",
                f"noise {i}",
                "2025-06-01T10:00:00Z",
                1,
                0,
                "Big Group",
            ],
        )


class TestLoadTopicContacts:
    """Tests for load_topic_contacts()."""

    def test_returns_high_importance_only(
        self, tmp_db: DatabaseEngine,
    ) -> None:
        """Only contacts with importance >= 5 returned."""
        _seed_mart_contact_summary(tmp_db)
        result = load_topic_contacts(tmp_db)
        assert "maria" in result
        assert "samuel" in result
        # João has importance=3, should be excluded
        assert "joão" not in result

    def test_custom_min_importance(
        self, tmp_db: DatabaseEngine,
    ) -> None:
        """Custom min_importance filters correctly."""
        _seed_mart_contact_summary(tmp_db)
        result = load_topic_contacts(
            tmp_db, min_importance=7,
        )
        assert "maria" in result
        assert "samuel" not in result

    def test_returns_topic_data(
        self, tmp_db: DatabaseEngine,
    ) -> None:
        """Returned dict has expected keys."""
        _seed_mart_contact_summary(tmp_db)
        result = load_topic_contacts(tmp_db)
        maria = result["maria"]
        assert maria["name"] == "Maria"
        assert maria["importance"] == 9
        assert len(maria["topics"]) == 2
        assert maria["notification_priority"] == 90

    def test_empty_when_no_mart(
        self, tmp_db: DatabaseEngine,
    ) -> None:
        """Returns empty dict when table doesn't exist."""
        result = load_topic_contacts(tmp_db)
        assert result == {}

    def test_limit_parameter(
        self, tmp_db: DatabaseEngine,
    ) -> None:
        """Limit caps the number of contacts returned."""
        _seed_mart_contact_summary(tmp_db)
        result = load_topic_contacts(tmp_db, limit=1)
        assert len(result) == 1

    def test_fallback_topics_from_top_topic(
        self, tmp_db: DatabaseEngine,
    ) -> None:
        """When active_topics_json is NULL, uses top_topic."""
        _seed_mart_contact_summary(tmp_db)
        # João was excluded by importance, add one with
        # NULL topics but importance >= 5
        tmp_db.execute(
            "INSERT INTO mart_contact_summary VALUES "
            "(?, ?, ?, ?, ?, ?)",
            ["Ana", "Budget review", 7, None, 70, 3],
        )
        result = load_topic_contacts(tmp_db)
        ana = result["ana"]
        assert len(ana["topics"]) == 1
        assert ana["topics"][0]["topic"] == "Budget review"


class TestLoadGroupEngagement:
    """Tests for load_group_engagement()."""

    def test_returns_engaged_groups(
        self, tmp_db: DatabaseEngine,
    ) -> None:
        """Returns group stats with correct counts."""
        _seed_group_messages(tmp_db)
        result = load_group_engagement(tmp_db)
        assert "Work Team" in result
        wt = result["Work Team"]
        assert wt["sent"] == 6
        assert wt["total"] == 10

    def test_lurk_group_has_zero_sent(
        self, tmp_db: DatabaseEngine,
    ) -> None:
        """Lurk group shows zero sent messages."""
        _seed_group_messages(tmp_db)
        result = load_group_engagement(tmp_db)
        bg = result["Big Group"]
        assert bg["sent"] == 0
        assert bg["members"] == 20

    def test_empty_when_no_groups(
        self, tmp_db: DatabaseEngine,
    ) -> None:
        """Returns empty dict when no tables exist."""
        result = load_group_engagement(tmp_db)
        assert result == {}


class TestGetTopicContactsForPrompt:
    """Tests for get_topic_contacts_for_prompt()."""

    def test_formats_for_prompt(self) -> None:
        """Returns list of dicts for LLM prompt."""
        tc = {
            "maria": {
                "name": "Maria",
                "importance": 9,
                "topics": [
                    {"topic": "Father cancer"},
                ],
                "notification_priority": 90,
            },
        }
        result = get_topic_contacts_for_prompt(tc)
        assert len(result) == 1
        assert result[0]["contact"] == "Maria"
        assert result[0]["importance"] == 9
        assert "Father cancer" in result[0]["topics"]

    def test_limits_contacts(self) -> None:
        """Respects max_contacts parameter."""
        tc = {
            f"c{i}": {
                "name": f"C{i}",
                "importance": 5,
                "topics": [],
                "notification_priority": i,
            }
            for i in range(20)
        }
        result = get_topic_contacts_for_prompt(
            tc, max_contacts=3,
        )
        assert len(result) == 3

    def test_sorted_by_priority(self) -> None:
        """Higher priority contacts come first."""
        tc = {
            "low": {
                "name": "Low",
                "importance": 5,
                "topics": [],
                "notification_priority": 10,
            },
            "high": {
                "name": "High",
                "importance": 9,
                "topics": [],
                "notification_priority": 90,
            },
        }
        result = get_topic_contacts_for_prompt(tc)
        assert result[0]["contact"] == "High"


# ------------------------------------------------------------------
# load_today_events
# ------------------------------------------------------------------


def _seed_calendar_events(db: DatabaseEngine) -> None:
    """Create raw_calendar_events with test data."""
    db.execute("""
        CREATE TABLE IF NOT EXISTS raw_calendar_events (
            id VARCHAR PRIMARY KEY,
            title VARCHAR,
            start_time TEXT,
            end_time TEXT,
            start_date TEXT,
            end_date TEXT,
            attendees TEXT,
            location TEXT
        )
    """)
    # Event today (using start_time)
    db.execute(
        "INSERT INTO raw_calendar_events VALUES "
        "(?, ?, date('now','start of day','+10 hours'), "
        "date('now','start of day','+11 hours'), NULL, NULL, ?, ?)",
        ["e1", "Team Standup", "Alice, Bob", "Room 3"],
    )
    # Event tomorrow (using start_time)
    db.execute(
        "INSERT INTO raw_calendar_events VALUES "
        "(?, ?, date('now','+1 day','start of day','+14 hours'), "
        "date('now','+1 day','start of day','+15 hours'), NULL, NULL, ?, ?)",
        ["e2", "Review", "Carol", "Zoom"],
    )
    # Event far in the future
    db.execute(
        "INSERT INTO raw_calendar_events VALUES "
        "(?, ?, date('now','+30 days'), "
        "date('now','+30 days'), NULL, NULL, ?, ?)",
        ["e3", "Conference", "Everyone", "Convention Center"],
    )


class TestLoadTodayEvents:
    """Tests for load_today_events()."""

    def test_returns_today_events(
        self, tmp_db: DatabaseEngine,
    ) -> None:
        """Returns events within the specified day range."""
        _seed_calendar_events(tmp_db)
        result = load_today_events(tmp_db, days_ahead=1)
        titles = [e["title"] for e in result]
        assert "Team Standup" in titles
        assert "Conference" not in titles

    def test_days_ahead_expands_window(
        self, tmp_db: DatabaseEngine,
    ) -> None:
        """days_ahead=3 includes tomorrow's event."""
        _seed_calendar_events(tmp_db)
        result = load_today_events(tmp_db, days_ahead=3)
        titles = [e["title"] for e in result]
        assert "Review" in titles

    def test_empty_when_no_table(
        self, tmp_db: DatabaseEngine,
    ) -> None:
        """Returns empty list when table doesn't exist."""
        result = load_today_events(tmp_db)
        assert result == []

    def test_limit_parameter(
        self, tmp_db: DatabaseEngine,
    ) -> None:
        """Limit caps the number of events returned."""
        _seed_calendar_events(tmp_db)
        result = load_today_events(tmp_db, days_ahead=3, limit=1)
        assert len(result) <= 1

    def test_result_keys(
        self, tmp_db: DatabaseEngine,
    ) -> None:
        """Each event dict has expected keys."""
        _seed_calendar_events(tmp_db)
        result = load_today_events(tmp_db, days_ahead=1)
        if result:
            event = result[0]
            assert "title" in event
            assert "start" in event
            assert "attendees" in event
            assert "location" in event


# ------------------------------------------------------------------
# load_pending_reply_ids
# ------------------------------------------------------------------


def _seed_pending_replies(db: DatabaseEngine) -> None:
    """Create _pending_replies with test data."""
    db.execute("""
        CREATE TABLE IF NOT EXISTS _pending_replies (
            id VARCHAR PRIMARY KEY,
            message_id VARCHAR NOT NULL,
            source VARCHAR NOT NULL,
            contact_name VARCHAR NOT NULL,
            domain VARCHAR NOT NULL,
            preview TEXT,
            importance INTEGER DEFAULT 5,
            reason TEXT,
            message_at TEXT NOT NULL,
            detected_at TEXT DEFAULT CURRENT_TIMESTAMP,
            dismissed_at TEXT,
            notified_at TEXT,
            sensitivity_tier INTEGER DEFAULT 2
        )
    """)
    # Active pending reply
    db.execute(
        "INSERT INTO _pending_replies "
        "(id, message_id, source, contact_name, domain, message_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        ["r1", "msg-001", "whatsapp", "Maria", "social", "2025-06-01"],
    )
    # Dismissed pending reply
    db.execute(
        "INSERT INTO _pending_replies "
        "(id, message_id, source, contact_name, domain, message_at, "
        "dismissed_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        [
            "r2", "msg-002", "whatsapp", "João",
            "social", "2025-06-01", "2025-06-02",
        ],
    )


class TestLoadPendingReplyIds:
    """Tests for load_pending_reply_ids()."""

    def test_returns_active_ids(
        self, tmp_db: DatabaseEngine,
    ) -> None:
        """Returns only non-dismissed message IDs."""
        _seed_pending_replies(tmp_db)
        result = load_pending_reply_ids(tmp_db)
        assert "msg-001" in result
        assert "msg-002" not in result

    def test_empty_when_no_table(
        self, tmp_db: DatabaseEngine,
    ) -> None:
        """Returns empty set when table doesn't exist."""
        result = load_pending_reply_ids(tmp_db)
        assert result == set()

    def test_empty_when_all_dismissed(
        self, tmp_db: DatabaseEngine,
    ) -> None:
        """Returns empty set when all replies are dismissed."""
        _seed_pending_replies(tmp_db)
        tmp_db.execute(
            "UPDATE _pending_replies SET dismissed_at = '2025-06-02'",
        )
        result = load_pending_reply_ids(tmp_db)
        assert result == set()

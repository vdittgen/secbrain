"""Tests for PreferenceService.

Uses a real temp DuckDB for table creation, CRUD, dedup, and log operations.

sensitivity_tier: N/A — test infrastructure
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from src.core.sqlite.engine import DatabaseEngine
from src.notifications.models import NotificationRecord
from src.notifications.preference_service import PreferenceService

# ================================================================
# Fixtures
# ================================================================


@pytest.fixture()
def tmp_db(tmp_path: Path) -> DatabaseEngine:
    """Fresh DuckDB engine backed by a temp file."""
    db_path = tmp_path / "test_notifications.duckdb"
    engine = DatabaseEngine(db_path=db_path)
    yield engine
    engine.close()


@pytest.fixture()
def prefs(tmp_db: DatabaseEngine) -> PreferenceService:
    """PreferenceService wired to the temp database."""
    return PreferenceService(db_engine=tmp_db)


# ================================================================
# Table creation
# ================================================================


class TestTableCreation:
    """Table setup tests."""

    def test_creates_tables_on_init(self, prefs: PreferenceService) -> None:
        """Tables exist after construction."""
        result = prefs.get_preferences()
        assert isinstance(result, list)

    def test_idempotent_table_creation(
        self, tmp_db: DatabaseEngine,
    ) -> None:
        """Creating PreferenceService twice doesn't error."""
        PreferenceService(db_engine=tmp_db)
        PreferenceService(db_engine=tmp_db)


# ================================================================
# Preference CRUD
# ================================================================


class TestPreferencesCRUD:
    """Preference read/write tests."""

    def test_get_empty_preferences(
        self, prefs: PreferenceService,
    ) -> None:
        """Empty DB returns empty list."""
        assert prefs.get_preferences() == []

    def test_update_and_get(
        self, prefs: PreferenceService,
    ) -> None:
        """Can insert and retrieve a preference."""
        prefs.update_preference("calendar_conflicts", enabled=True)
        result = prefs.get_preferences()
        assert len(result) == 1
        assert result[0].category == "calendar_conflicts"
        assert result[0].enabled is True

    def test_update_overwrites(
        self, prefs: PreferenceService,
    ) -> None:
        """Updating same category overwrites the old value."""
        prefs.update_preference("health_alerts", enabled=True)
        prefs.update_preference("health_alerts", enabled=False)
        result = prefs.get_preferences()
        assert len(result) == 1
        assert result[0].enabled is False

    def test_is_category_enabled_default_true(
        self, prefs: PreferenceService,
    ) -> None:
        """Unknown categories default to enabled."""
        assert prefs.is_category_enabled("unknown_category") is True

    def test_is_category_enabled_disabled(
        self, prefs: PreferenceService,
    ) -> None:
        """Disabled categories return False."""
        prefs.update_preference("health_alerts", enabled=False)
        assert prefs.is_category_enabled("health_alerts") is False

    def test_multiple_categories(
        self, prefs: PreferenceService,
    ) -> None:
        """Multiple categories coexist."""
        prefs.update_preference("calendar_conflicts", enabled=True)
        prefs.update_preference("health_alerts", enabled=False)
        prefs.update_preference("action_results", enabled=True)
        result = prefs.get_preferences()
        assert len(result) == 3


# ================================================================
# Global mute
# ================================================================


class TestGlobalMute:
    """Global mute/unmute tests."""

    def test_mute_all_sets_muted(
        self, prefs: PreferenceService,
    ) -> None:
        """Muting sets global muted state."""
        prefs.mute_all()
        assert prefs.is_muted_globally() is True

    def test_is_muted_with_future_timestamp(
        self, prefs: PreferenceService,
    ) -> None:
        """Muted until a future time returns True."""
        future = (
            datetime.now(timezone.utc) + timedelta(hours=2)
        ).isoformat()
        prefs.mute_all(until=future)
        assert prefs.is_muted_globally() is True

    def test_is_muted_with_past_timestamp(
        self, prefs: PreferenceService,
    ) -> None:
        """Muted until a past time returns False."""
        past = (
            datetime.now(timezone.utc) - timedelta(hours=2)
        ).isoformat()
        prefs.mute_all(until=past)
        assert prefs.is_muted_globally() is False

    def test_unmute_all(
        self, prefs: PreferenceService,
    ) -> None:
        """Unmuting removes global mute."""
        prefs.mute_all()
        assert prefs.is_muted_globally() is True
        prefs.unmute_all()
        assert prefs.is_muted_globally() is False

    def test_not_muted_by_default(
        self, prefs: PreferenceService,
    ) -> None:
        """No global mute by default."""
        assert prefs.is_muted_globally() is False


# ================================================================
# Notification log
# ================================================================


class TestNotificationLog:
    """Log persistence and dedup tests."""

    @staticmethod
    def _make_record(
        prefs: PreferenceService,
        **overrides: str,
    ) -> NotificationRecord:
        """Build a NotificationRecord with defaults."""
        now = datetime.now(timezone.utc).isoformat()
        defaults = {
            "id": prefs.new_record_id(),
            "dedupe_key": "test_key_123",
            "category": "calendar_conflicts",
            "importance_score": 7.5,
            "decision": "send",
            "delivery_status": "sent",
            "message": "Test notification",
            "opt_out_text": "Reply STOP to opt out",
            "source_type": "pipeline",
            "source_id": "run_123",
            "error": None,
            "created_at": now,
        }
        defaults.update(overrides)
        return NotificationRecord(**defaults)

    def test_log_notification(
        self, prefs: PreferenceService,
    ) -> None:
        """Can log and retrieve a notification record."""
        record = self._make_record(prefs)
        prefs.log_notification(record)
        log = prefs.get_notification_log(limit=10)
        assert len(log) == 1
        assert log[0].category == "calendar_conflicts"
        assert log[0].delivery_status == "sent"

    def test_log_pagination(
        self, prefs: PreferenceService,
    ) -> None:
        """Pagination works for log entries."""
        for i in range(5):
            record = self._make_record(
                prefs,
                dedupe_key=f"key_{i}",
            )
            prefs.log_notification(record)

        page1 = prefs.get_notification_log(limit=2, offset=0)
        page2 = prefs.get_notification_log(limit=2, offset=2)
        assert len(page1) == 2
        assert len(page2) == 2

    def test_has_recent_dedup_true(
        self, prefs: PreferenceService,
    ) -> None:
        """Recent sent notification triggers dedup."""
        record = self._make_record(prefs)
        prefs.log_notification(record)
        assert prefs.has_recent_dedup("test_key_123") is True

    def test_has_recent_dedup_false_different_key(
        self, prefs: PreferenceService,
    ) -> None:
        """Different dedup key does not trigger dedup."""
        record = self._make_record(prefs)
        prefs.log_notification(record)
        assert prefs.has_recent_dedup("other_key") is False

    def test_has_recent_dedup_false_skipped(
        self, prefs: PreferenceService,
    ) -> None:
        """Skipped (not sent) notifications don't trigger dedup."""
        record = self._make_record(
            prefs, delivery_status="skipped",
        )
        prefs.log_notification(record)
        assert prefs.has_recent_dedup("test_key_123") is False

    def test_recent_log_summary(
        self, prefs: PreferenceService,
    ) -> None:
        """Recent log summary returns formatted entries."""
        record = self._make_record(prefs)
        prefs.log_notification(record)
        summary = prefs.get_recent_log_summary()
        assert len(summary) == 1
        assert summary[0]["category"] == "calendar_conflicts"

"""Unit tests for the SyncScheduler.

Tests verify scheduling logic, retry backoff, and failure disabling
without relying on real timers (uses mocks and direct method calls).
"""

from __future__ import annotations

from datetime import datetime, timezone

from src.extensions.connectors.sync_scheduler import (
    MAX_RETRIES,
    RETRY_BACKOFF,
    SCHEDULE_INTERVALS,
    SyncScheduler,
    SyncStats,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_success_sync(connector_id: str) -> SyncStats:
    """Create a successful SyncStats result."""
    now = datetime.now(timezone.utc)
    return SyncStats(
        connector_id=connector_id,
        started_at=now,
        completed_at=now,
        status="success",
        rows_synced=42,
    )


def _make_error_sync(connector_id: str) -> SyncStats:
    """Create an error SyncStats result."""
    now = datetime.now(timezone.utc)
    return SyncStats(
        connector_id=connector_id,
        started_at=now,
        completed_at=now,
        status="error",
        error="Connection refused",
    )


# ---------------------------------------------------------------------------
# Basic scheduling tests
# ---------------------------------------------------------------------------


class TestScheduleBasics:
    def test_schedule_manual_no_timer(self) -> None:
        """Manual schedule should not create a timer."""
        scheduler = SyncScheduler()
        scheduler.schedule("test-conn", "manual")

        info = scheduler.get_schedule_info("test-conn")
        assert info is not None
        assert info["interval_seconds"] == 0
        assert info["enabled"] is True

        scheduler.stop_all()

    def test_schedule_creates_entry(self) -> None:
        """Scheduling should create an entry with correct interval."""
        scheduler = SyncScheduler()
        scheduler.schedule("test-conn", "hourly")

        info = scheduler.get_schedule_info("test-conn")
        assert info is not None
        assert info["interval_seconds"] == 3600
        assert info["enabled"] is True

        scheduler.stop_all()

    def test_unschedule_removes_entry(self) -> None:
        """Unscheduling should remove the entry."""
        scheduler = SyncScheduler()
        scheduler.schedule("test-conn", "hourly")
        scheduler.unschedule("test-conn")

        info = scheduler.get_schedule_info("test-conn")
        assert info is None

        scheduler.stop_all()

    def test_get_next_sync_times(self) -> None:
        """Should return next sync times for all entries."""
        scheduler = SyncScheduler()
        scheduler.schedule("a", "hourly")
        scheduler.schedule("b", "manual")

        times = scheduler.get_next_sync_times()
        assert "a" in times
        assert "b" in times
        # Manual has no next_sync
        assert times["b"] is None
        # Hourly should have a future time
        assert times["a"] is not None

        scheduler.stop_all()

    def test_stop_all_cancels_timers(self) -> None:
        """stop_all should cancel all pending timers."""
        scheduler = SyncScheduler()
        scheduler.schedule("a", "every_15min")
        scheduler.schedule("b", "hourly")
        scheduler.stop_all()

        # After stop, entries exist but no active timers
        info_a = scheduler.get_schedule_info("a")
        info_b = scheduler.get_schedule_info("b")
        assert info_a is not None
        assert info_b is not None

    def test_get_all_schedules(self) -> None:
        """get_all_schedules should return info for all entries."""
        scheduler = SyncScheduler()
        scheduler.schedule("x", "hourly")
        scheduler.schedule("y", "daily")

        schedules = scheduler.get_all_schedules()
        assert len(schedules) == 2
        ids = {s["connector_id"] for s in schedules}
        assert ids == {"x", "y"}

        scheduler.stop_all()


# ---------------------------------------------------------------------------
# run_now tests
# ---------------------------------------------------------------------------


class TestRunNow:
    def test_run_now_with_sync_fn(self) -> None:
        """run_now should call the sync function and return stats."""
        calls: list[str] = []

        def sync_fn(cid: str) -> SyncStats:
            calls.append(cid)
            return _make_success_sync(cid)

        scheduler = SyncScheduler(sync_fn=sync_fn)
        scheduler.schedule("my-conn", "manual")

        stats = scheduler.run_now("my-conn")
        assert stats.status == "success"
        assert stats.rows_synced == 42
        assert calls == ["my-conn"]

        scheduler.stop_all()

    def test_run_now_without_sync_fn(self) -> None:
        """run_now without sync_fn should return success (no-op)."""
        scheduler = SyncScheduler(sync_fn=None)
        scheduler.schedule("test", "manual")

        stats = scheduler.run_now("test")
        assert stats.status == "success"

        scheduler.stop_all()

    def test_run_now_updates_last_sync(self) -> None:
        """run_now should update the last_sync timestamp."""
        scheduler = SyncScheduler()
        scheduler.schedule("conn", "manual")

        scheduler.run_now("conn")

        info = scheduler.get_schedule_info("conn")
        assert info is not None
        assert info["last_sync"] is not None
        assert info["last_status"] == "success"

        scheduler.stop_all()

    def test_run_now_records_error(self) -> None:
        """run_now should record errors from sync function."""

        def failing_sync(cid: str) -> SyncStats:
            msg = "Connection failed"
            raise RuntimeError(msg)

        scheduler = SyncScheduler(sync_fn=failing_sync)
        scheduler.schedule("conn", "manual")

        stats = scheduler.run_now("conn")
        assert stats.status == "error"
        assert "Connection failed" in (stats.error or "")

        info = scheduler.get_schedule_info("conn")
        assert info["last_status"] == "error"

        scheduler.stop_all()


# ---------------------------------------------------------------------------
# Retry backoff tests
# ---------------------------------------------------------------------------


class TestRetryBackoff:
    def test_failure_increments_counter(self) -> None:
        """Consecutive failures should increment the counter."""

        def error_sync(cid: str) -> SyncStats:
            return _make_error_sync(cid)

        scheduler = SyncScheduler(sync_fn=error_sync)
        scheduler.schedule("conn", "manual")

        # Simulate timer-fired syncs
        scheduler._on_timer_fire("conn")

        info = scheduler.get_schedule_info("conn")
        assert info["consecutive_failures"] == 1

        scheduler.stop_all()

    def test_success_resets_counter(self) -> None:
        """A successful sync should reset the failure counter."""
        call_count = 0

        def mixed_sync(cid: str) -> SyncStats:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return _make_error_sync(cid)
            return _make_success_sync(cid)

        scheduler = SyncScheduler(sync_fn=mixed_sync)
        scheduler.schedule("conn", "manual")

        # First call fails
        scheduler._on_timer_fire("conn")
        info = scheduler.get_schedule_info("conn")
        assert info["consecutive_failures"] == 1

        # Second call succeeds
        scheduler._on_timer_fire("conn")
        info = scheduler.get_schedule_info("conn")
        assert info["consecutive_failures"] == 0

        scheduler.stop_all()

    def test_max_retries_disables_schedule(self) -> None:
        """After MAX_RETRIES failures, schedule should be disabled."""

        def error_sync(cid: str) -> SyncStats:
            return _make_error_sync(cid)

        scheduler = SyncScheduler(sync_fn=error_sync)
        scheduler.schedule("conn", "manual")

        # Fire MAX_RETRIES + 1 times to exceed the limit
        for _ in range(MAX_RETRIES + 1):
            scheduler._on_timer_fire("conn")

        info = scheduler.get_schedule_info("conn")
        assert info["enabled"] is False
        assert info["consecutive_failures"] > MAX_RETRIES

        scheduler.stop_all()


# ---------------------------------------------------------------------------
# Schedule intervals
# ---------------------------------------------------------------------------


class TestScheduleIntervals:
    def test_known_intervals(self) -> None:
        """All expected intervals should be defined."""
        assert "every_15min" in SCHEDULE_INTERVALS
        assert "hourly" in SCHEDULE_INTERVALS
        assert "daily" in SCHEDULE_INTERVALS
        assert "manual" in SCHEDULE_INTERVALS

    def test_interval_values(self) -> None:
        """Intervals should have correct second values."""
        assert SCHEDULE_INTERVALS["every_15min"] == 900
        assert SCHEDULE_INTERVALS["hourly"] == 3600
        assert SCHEDULE_INTERVALS["daily"] == 86400
        assert SCHEDULE_INTERVALS["manual"] == 0

    def test_retry_backoff_values(self) -> None:
        """Retry backoff should be 1min, 5min, 15min."""
        assert RETRY_BACKOFF == (60, 300, 900)
        assert MAX_RETRIES == len(RETRY_BACKOFF)

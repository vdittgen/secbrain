"""Unit tests for the minimal cron matcher.

Tests cover field parsing, full expression matching, and due-checking
logic for agent scheduling.
"""

from __future__ import annotations

from datetime import datetime

from src.extensions.cron import _parse_field, cron_is_due, cron_matches

# ---------------------------------------------------------------------------
# _parse_field
# ---------------------------------------------------------------------------


class TestParseField:
    def test_wildcard(self) -> None:
        assert _parse_field("*", 0, 59) == set(range(0, 60))

    def test_literal(self) -> None:
        assert _parse_field("5", 0, 59) == {5}

    def test_step(self) -> None:
        assert _parse_field("*/15", 0, 59) == {0, 15, 30, 45}

    def test_range(self) -> None:
        assert _parse_field("1-5", 0, 59) == {1, 2, 3, 4, 5}

    def test_list(self) -> None:
        assert _parse_field("1,3,5", 0, 59) == {1, 3, 5}

    def test_combined_list_and_range(self) -> None:
        assert _parse_field("1-3,7", 0, 59) == {1, 2, 3, 7}


# ---------------------------------------------------------------------------
# cron_matches
# ---------------------------------------------------------------------------


class TestCronMatches:
    def test_every_minute(self) -> None:
        """'* * * * *' matches any datetime."""
        dt = datetime(2026, 3, 1, 14, 30)
        assert cron_matches("* * * * *", dt) is True

    def test_exact_minute_hour(self) -> None:
        """'30 14 * * *' matches 14:30 on any day."""
        dt = datetime(2026, 3, 1, 14, 30)
        assert cron_matches("30 14 * * *", dt) is True

    def test_exact_minute_hour_no_match(self) -> None:
        dt = datetime(2026, 3, 1, 14, 31)
        assert cron_matches("30 14 * * *", dt) is False

    def test_weekly_digest_schedule(self) -> None:
        """'0 9 * * 1' = every Monday at 9:00 AM."""
        # 2026-03-02 is a Monday
        monday_9am = datetime(2026, 3, 2, 9, 0)
        assert cron_matches("0 9 * * 1", monday_9am) is True

        # Same time on Tuesday should not match
        tuesday_9am = datetime(2026, 3, 3, 9, 0)
        assert cron_matches("0 9 * * 1", tuesday_9am) is False

    def test_daily_8am(self) -> None:
        """'0 8 * * *' = every day at 8:00 AM."""
        dt = datetime(2026, 3, 1, 8, 0)
        assert cron_matches("0 8 * * *", dt) is True

        dt_wrong_hour = datetime(2026, 3, 1, 9, 0)
        assert cron_matches("0 8 * * *", dt_wrong_hour) is False

    def test_specific_day_of_month(self) -> None:
        """'0 0 15 * *' = midnight on the 15th of every month."""
        assert cron_matches("0 0 15 * *", datetime(2026, 3, 15, 0, 0)) is True
        assert cron_matches("0 0 15 * *", datetime(2026, 3, 14, 0, 0)) is False

    def test_specific_month(self) -> None:
        """'0 0 1 6 *' = midnight, June 1st."""
        assert cron_matches("0 0 1 6 *", datetime(2026, 6, 1, 0, 0)) is True
        assert cron_matches("0 0 1 6 *", datetime(2026, 7, 1, 0, 0)) is False

    def test_step_minutes(self) -> None:
        """'*/15 * * * *' = every 15 minutes."""
        expr = "*/15 * * * *"
        assert cron_matches(expr, datetime(2026, 3, 1, 10, 0)) is True
        assert cron_matches(expr, datetime(2026, 3, 1, 10, 15)) is True
        assert cron_matches(expr, datetime(2026, 3, 1, 10, 7)) is False

    def test_invalid_expression_returns_false(self) -> None:
        """Invalid cron expression (wrong number of fields) returns False."""
        assert cron_matches("* *", datetime(2026, 3, 1, 10, 0)) is False
        assert cron_matches("", datetime(2026, 3, 1, 10, 0)) is False

    def test_weekday_range(self) -> None:
        """'0 9 * * 1-5' = weekdays Mon-Fri at 9am (cron: 1=Mon, 5=Fri)."""
        # 2026-03-02 is Monday
        assert cron_matches("0 9 * * 1-5", datetime(2026, 3, 2, 9, 0)) is True
        # 2026-03-07 is Saturday (cron weekday=6)
        assert cron_matches("0 9 * * 1-5", datetime(2026, 3, 7, 9, 0)) is False


# ---------------------------------------------------------------------------
# cron_is_due
# ---------------------------------------------------------------------------


class TestCronIsDue:
    def test_never_run_and_matches_now(self) -> None:
        """First-ever run: if now matches, it's due."""
        now = datetime(2026, 3, 1, 8, 0)
        assert cron_is_due("0 8 * * *", last_run=None, now=now) is True

    def test_never_run_and_no_match(self) -> None:
        """First-ever run: if now doesn't match, not due."""
        now = datetime(2026, 3, 1, 8, 5)
        assert cron_is_due("0 8 * * *", last_run=None, now=now) is False

    def test_ran_recently_no_match_in_between(self) -> None:
        """Ran 5 minutes ago, no cron match between then and now."""
        now = datetime(2026, 3, 1, 8, 10)
        last = datetime(2026, 3, 1, 8, 5)
        assert cron_is_due("0 9 * * *", last_run=last, now=now) is False

    def test_ran_yesterday_match_today(self) -> None:
        """Ran yesterday, cron matches today at 8am."""
        last = datetime(2026, 2, 28, 8, 0)
        now = datetime(2026, 3, 1, 8, 1)
        assert cron_is_due("0 8 * * *", last_run=last, now=now) is True

    def test_ran_at_same_minute_not_due(self) -> None:
        """If last_run is at the exact cron minute, don't re-trigger."""
        last = datetime(2026, 3, 1, 8, 0)
        now = datetime(2026, 3, 1, 8, 0, 30)
        assert cron_is_due("0 8 * * *", last_run=last, now=now) is False

    def test_weekly_schedule_fires_on_monday(self) -> None:
        """Weekly digest (Mon 9am) fires when Monday arrives."""
        # Last ran previous Monday
        last = datetime(2026, 2, 23, 9, 0)  # Monday
        now = datetime(2026, 3, 2, 9, 1)  # Next Monday
        assert cron_is_due("0 9 * * 1", last_run=last, now=now) is True

    def test_weekly_schedule_not_due_on_tuesday(self) -> None:
        """Weekly digest should not fire on Tuesday."""
        last = datetime(2026, 3, 2, 9, 0)  # Monday
        now = datetime(2026, 3, 3, 9, 0)  # Tuesday
        assert cron_is_due("0 9 * * 1", last_run=last, now=now) is False

    def test_large_gap_capped_at_24h(self) -> None:
        """When last_run is weeks old, scan caps at 24h from now."""
        last = datetime(2026, 1, 1, 0, 0)
        now = datetime(2026, 3, 1, 8, 0)
        # Daily 8am should still be detected (within 24h window)
        assert cron_is_due("0 8 * * *", last_run=last, now=now) is True

    def test_step_schedule(self) -> None:
        """'*/30 * * * *' fires every 30 minutes."""
        last = datetime(2026, 3, 1, 10, 0)
        now = datetime(2026, 3, 1, 10, 31)
        assert cron_is_due("*/30 * * * *", last_run=last, now=now) is True

    def test_future_last_run_returns_false(self) -> None:
        """If last_run is in the future (clock skew), not due."""
        last = datetime(2026, 3, 1, 10, 0)
        now = datetime(2026, 3, 1, 9, 0)
        assert cron_is_due("0 8 * * *", last_run=last, now=now) is False

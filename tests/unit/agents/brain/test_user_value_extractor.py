"""Tests for the deterministic user-value extractor.

The extractor is the structural defense against LLM-rewriting a user's
literal title (``"Play Tennis with Tiago"``) into something from the
personal context (``"Coffee chat with Sarah"``). Every regex and
date-shorthand we accept needs a case here — pattern-based parsing is
fragile enough that "we tested it manually once" doesn't cut it.

sensitivity_tier: 1
"""

from __future__ import annotations

from datetime import date as _date

import pytest
from src.agents.brain.user_value_extractor import (
    UserGivenValues,
    extract_user_given_values,
)

# Pin "today" so the date-math assertions are reproducible regardless
# of when the suite runs in CI.
TODAY = _date(2026, 5, 22)  # Friday


class TestTitleExtraction:
    """The user's quoted / explicitly-named title is the single most
    common thing the LLM clobbers, so this is where we are strictest."""

    def test_double_quotes(self) -> None:
        v = extract_user_given_values(
            'create an event tomorrow 7am called "Play Tennis with Tiago"',
            today=TODAY,
        )
        assert v.title == "Play Tennis with Tiago"

    def test_smart_quotes(self) -> None:
        v = extract_user_given_values(
            "create an event tomorrow 7am called “Play Tennis with Tiago”",
            today=TODAY,
        )
        assert v.title == "Play Tennis with Tiago"

    def test_single_quotes(self) -> None:
        v = extract_user_given_values(
            "schedule 'Lunch with Maria' for noon tomorrow",
            today=TODAY,
        )
        assert v.title == "Lunch with Maria"

    def test_backticks(self) -> None:
        v = extract_user_given_values(
            "create an event `Demo run` tomorrow at 3pm",
            today=TODAY,
        )
        assert v.title == "Demo run"

    def test_called_keyword_without_quotes(self) -> None:
        v = extract_user_given_values(
            "create an event for tomorrow 7am called Play Tennis with Tiago",
            today=TODAY,
        )
        assert v.title == "Play Tennis with Tiago"

    def test_called_keyword_strips_trailing_time_clause(self) -> None:
        # "called Lunch with Maria at noon" — we only want the title,
        # not the time prep clause.
        v = extract_user_given_values(
            "create an event called Lunch with Maria at 12:30 pm",
            today=TODAY,
        )
        assert v.title == "Lunch with Maria"

    def test_titled_keyword(self) -> None:
        v = extract_user_given_values(
            "add an event titled Quarterly review next Monday 3pm",
            today=TODAY,
        )
        assert v.title == "Quarterly review"

    def test_no_title_returns_none(self) -> None:
        v = extract_user_given_values(
            "schedule something tomorrow at 7am",
            today=TODAY,
        )
        assert v.title is None

    def test_quoted_wins_over_called(self) -> None:
        # Both signals present — the quoted form is more explicit and
        # should win.
        v = extract_user_given_values(
            'create event called Old Title "New Title" tomorrow 9am',
            today=TODAY,
        )
        assert v.title == "New Title"


class TestDateExtraction:
    """Date-shorthand resolution. Today is Friday 2026-05-22."""

    def test_today(self) -> None:
        v = extract_user_given_values("schedule it today at 3pm", today=TODAY)
        assert v.start_time is not None
        assert v.start_time.startswith("2026-05-22T15:00")

    def test_tomorrow(self) -> None:
        v = extract_user_given_values(
            "create event tomorrow 7am called Tennis", today=TODAY,
        )
        assert v.start_time is not None
        assert v.start_time.startswith("2026-05-23T07:00")

    def test_day_after_tomorrow(self) -> None:
        v = extract_user_given_values(
            "block 2pm the day after tomorrow", today=TODAY,
        )
        assert v.start_time is not None
        assert v.start_time.startswith("2026-05-24T14:00")

    def test_this_monday(self) -> None:
        # Friday → "this Monday" is the upcoming Monday (3 days out).
        v = extract_user_given_values(
            "let's meet this Monday at 10am", today=TODAY,
        )
        assert v.start_time is not None
        assert v.start_time.startswith("2026-05-25T10:00")

    def test_next_friday_is_one_week_out(self) -> None:
        v = extract_user_given_values(
            "block out next Friday at 3pm", today=TODAY,
        )
        assert v.start_time is not None
        assert v.start_time.startswith("2026-05-29T15:00")

    def test_explicit_iso_date_wins(self) -> None:
        v = extract_user_given_values(
            "create event 2026-12-31 at 7pm called NYE",
            today=TODAY,
        )
        assert v.start_time is not None
        assert v.start_time.startswith("2026-12-31T19:00")
        assert v.title == "NYE"

    def test_portuguese_amanha(self) -> None:
        v = extract_user_given_values(
            "criar evento amanhã 7am chamado Tennis", today=TODAY,
        )
        assert v.start_time is not None
        assert v.start_time.startswith("2026-05-23T07:00")


class TestTimeExtraction:
    """Clock-time parsing. We accept 12-hour with am/pm, 24-hour, and
    the words ``noon`` / ``midnight``."""

    def test_12_hour_am(self) -> None:
        v = extract_user_given_values("tomorrow at 7am", today=TODAY)
        assert v.start_time is not None
        assert v.start_time.startswith("2026-05-23T07:00")

    def test_12_hour_pm(self) -> None:
        v = extract_user_given_values("tomorrow at 3pm", today=TODAY)
        assert v.start_time.startswith("2026-05-23T15:00")

    def test_12_hour_with_minutes(self) -> None:
        v = extract_user_given_values("tomorrow at 7:30 pm", today=TODAY)
        assert v.start_time.startswith("2026-05-23T19:30")

    def test_24_hour(self) -> None:
        v = extract_user_given_values("tomorrow at 14:30", today=TODAY)
        assert v.start_time.startswith("2026-05-23T14:30")

    def test_noon(self) -> None:
        v = extract_user_given_values("tomorrow at noon", today=TODAY)
        assert v.start_time.startswith("2026-05-23T12:00")

    def test_midnight(self) -> None:
        v = extract_user_given_values("tomorrow at midnight", today=TODAY)
        assert v.start_time.startswith("2026-05-23T00:00")


class TestDefaults:
    """Defaults the extractor must apply when only one piece is given."""

    def test_default_duration_is_one_hour(self) -> None:
        v = extract_user_given_values("tomorrow at 7am", today=TODAY)
        # Hour math: 7:00 → 8:00.
        assert v.end_time.startswith("2026-05-23T08:00")

    def test_explicit_duration(self) -> None:
        v = extract_user_given_values(
            "tomorrow at 7am", today=TODAY, default_duration_minutes=30,
        )
        assert v.end_time.startswith("2026-05-23T07:30")

    def test_only_clock_uses_today(self) -> None:
        v = extract_user_given_values("block 3pm", today=TODAY)
        assert v.start_time.startswith("2026-05-22T15:00")

    def test_only_day_uses_nine_am(self) -> None:
        v = extract_user_given_values(
            "schedule a meeting tomorrow", today=TODAY,
        )
        assert v.start_time.startswith("2026-05-23T09:00")


class TestEmptyAndMalformed:
    """Defensive cases — the extractor must never raise."""

    def test_empty_input(self) -> None:
        assert extract_user_given_values("") == UserGivenValues()

    def test_no_signals(self) -> None:
        v = extract_user_given_values(
            "hello, can you help me with something?", today=TODAY,
        )
        assert v == UserGivenValues()

    def test_invalid_iso_date(self) -> None:
        # 2026-13-99 is not a real date — extractor must shrug, not raise.
        v = extract_user_given_values(
            "create event 2026-13-99 called nope", today=TODAY,
        )
        assert v.title == "nope"
        # No valid date → no derived time.
        assert v.start_time is None or "2026-13" not in v.start_time

    @pytest.mark.parametrize("clock", ["25:00", "12:99"])
    def test_invalid_clock_silently_ignored(self, clock: str) -> None:
        v = extract_user_given_values(
            f"tomorrow at {clock} please", today=TODAY,
        )
        # No clock match → defaults to 9am ("we have a day, not a time").
        assert v.start_time is not None
        assert "09:00" in v.start_time

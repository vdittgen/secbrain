"""Unit tests for the brain.notifications helpers.

Covers the pure ``apply_notification_action`` translator that Brain v2's
``update_notification_preferences`` tool delegates to.

sensitivity_tier: 1
"""

from __future__ import annotations

from dataclasses import dataclass
from unittest.mock import MagicMock

from src.agents.brain.notifications import (
    _KNOWN_CATEGORIES,
    apply_notification_action,
)


@dataclass
class _FakePref:
    category: str
    enabled: bool


def _fake_prefs(pref_list: list[_FakePref] | None = None) -> MagicMock:
    prefs = MagicMock()
    prefs.get_preferences.return_value = pref_list or []
    return prefs


def test_show_with_empty_preferences_offers_start_hint() -> None:
    prefs = _fake_prefs([])
    out = apply_notification_action(prefs, "show")
    assert "haven't set any notification preferences yet" in out


def test_show_lists_each_pref_with_state() -> None:
    prefs = _fake_prefs([
        _FakePref(category="calendar_conflicts", enabled=True),
        _FakePref(category="health_alerts", enabled=False),
    ])
    out = apply_notification_action(prefs, "show")
    assert "calendar conflicts: on" in out
    assert "health alerts: off" in out


def test_mute_all_calls_service_and_returns_confirmation() -> None:
    prefs = _fake_prefs()
    out = apply_notification_action(prefs, "mute_all")
    prefs.mute_all.assert_called_once_with()
    assert "muted for 24 hours" in out


def test_unmute_calls_service_and_returns_confirmation() -> None:
    prefs = _fake_prefs()
    out = apply_notification_action(prefs, "unmute")
    prefs.unmute_all.assert_called_once_with()
    assert "back on" in out


def test_enable_without_category_asks_for_one() -> None:
    prefs = _fake_prefs()
    out = apply_notification_action(prefs, "enable")
    prefs.update_preference.assert_not_called()
    assert "Which notification category" in out


def test_enable_rejects_unknown_category() -> None:
    prefs = _fake_prefs()
    out = apply_notification_action(prefs, "enable", category="bogus")
    prefs.update_preference.assert_not_called()
    assert "Unknown notification category" in out
    # The error message should list valid categories.
    for cat in _KNOWN_CATEGORIES:
        assert cat in out


def test_enable_with_known_category_mutates_service() -> None:
    prefs = _fake_prefs()
    out = apply_notification_action(
        prefs, "enable", category="calendar_conflicts",
    )
    prefs.update_preference.assert_called_once_with(
        "calendar_conflicts", enabled=True,
    )
    assert "calendar conflicts" in out


def test_disable_with_known_category_mutates_service() -> None:
    prefs = _fake_prefs()
    out = apply_notification_action(
        prefs, "disable", category="health_alerts",
    )
    prefs.update_preference.assert_called_once_with(
        "health_alerts", enabled=False,
    )
    assert "health alerts" in out

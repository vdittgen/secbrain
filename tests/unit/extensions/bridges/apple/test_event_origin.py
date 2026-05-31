"""Tests for the Apple Calendar event-origin classifier.

The classifier turns three structural signals (calendar sharing, calendar
subscription, whether the user is an invited participant) into a single
``event_origin`` label that drives how the dashboard groups events:
personal / team_awareness / subscribed.

sensitivity_tier: 1
"""

from __future__ import annotations

import pytest
from src.extensions.bridges.apple.server import (
    _classify_event_origin,
    _is_shared_to_me,
)


class TestClassifyEventOrigin:
    """Encodes the precedence rule: invitation wins over calendar type."""

    def test_owned_calendar_no_invite_is_personal(self) -> None:
        assert _classify_event_origin(
            is_shared_calendar=False,
            is_subscribed_calendar=False,
            is_self_invited=False,
        ) == "personal"

    def test_shared_calendar_not_invited_is_team_awareness(self) -> None:
        assert _classify_event_origin(
            is_shared_calendar=True,
            is_subscribed_calendar=False,
            is_self_invited=False,
        ) == "team_awareness"

    def test_subscribed_calendar_not_invited_is_subscribed(self) -> None:
        assert _classify_event_origin(
            is_shared_calendar=False,
            is_subscribed_calendar=True,
            is_self_invited=False,
        ) == "subscribed"

    def test_shared_calendar_with_invite_is_personal(self) -> None:
        """User explicitly invited overrides shared-calendar awareness."""
        assert _classify_event_origin(
            is_shared_calendar=True,
            is_subscribed_calendar=False,
            is_self_invited=True,
        ) == "personal"

    def test_subscribed_calendar_with_invite_is_personal(self) -> None:
        assert _classify_event_origin(
            is_shared_calendar=False,
            is_subscribed_calendar=True,
            is_self_invited=True,
        ) == "personal"


class TestIsSharedToMe:
    """Reads Calendar.app's shared-with-me signals."""

    def test_no_share_metadata_returns_false(self) -> None:
        assert not _is_shared_to_me(
            sharing_status=0,
            shared_owner_address=None,
            self_identity_email=None,
        )

    def test_sharing_status_one_returns_true(self) -> None:
        """sharing_status > 0 means Apple Calendar already flagged this
        as a shared calendar; the address fields are unnecessary."""
        assert _is_shared_to_me(
            sharing_status=1,
            shared_owner_address=None,
            self_identity_email=None,
        )

    def test_shared_by_someone_else_is_shared(self) -> None:
        assert _is_shared_to_me(
            sharing_status=0,
            shared_owner_address="mailto:yash.ambegaokar@powerhrg.com",
            self_identity_email="vinicius.dittgen@powerhrg.com",
        )

    def test_shared_by_self_is_not_shared_to_me(self) -> None:
        """A calendar whose ``shared_owner_address`` is the user's own
        email is one they themselves own, not one shared to them."""
        assert not _is_shared_to_me(
            sharing_status=0,
            shared_owner_address="mailto:vinicius.dittgen@powerhrg.com",
            self_identity_email="vinicius.dittgen@powerhrg.com",
        )

    @pytest.mark.parametrize("status", [None, 0])
    def test_no_owner_no_share_is_not_shared(self, status: int | None) -> None:
        assert not _is_shared_to_me(
            sharing_status=status,
            shared_owner_address=None,
            self_identity_email="me@example.com",
        )

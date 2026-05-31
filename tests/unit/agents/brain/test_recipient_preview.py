"""Tests for ``_build_recipient_preview`` — the recipient resolver
that powers the confirmation-card preview line ("To: Elmara · +55 11
99999-1234 · WhatsApp").

The preview is the user-facing safeguard against the "to: WhatsApp"
class of bug where the LLM put a channel name (or any garbage
string) in the recipient field. ``resolved=False`` means the card
must warn the user — and we *must* still surface the card so the
user can cancel instead of the agent silently shipping a wrong
destination.

sensitivity_tier: 2
"""

from __future__ import annotations

from typing import Any

from src.agents.brain.actions import _build_recipient_preview


class _FakeDB:
    """Tiny stand-in for the DuckDB engine; routes contact queries to
    a canned response list."""

    def __init__(self, contacts: list[dict[str, Any]]):
        self._contacts = contacts

    def query(self, _sql: str, _params: list[Any]) -> list:
        return self._contacts


class TestNonMessagingConnectors:
    """No preview for calendar / notes / etc. — there's no recipient
    to verify."""

    def test_calendar_returns_none(self) -> None:
        assert _build_recipient_preview(
            extracted={"title": "x"},
            connector_id="apple-calendar",
            db=_FakeDB([]),
        ) is None

    def test_notes_returns_none(self) -> None:
        assert _build_recipient_preview(
            extracted={"title": "x"},
            connector_id="apple-notes",
            db=_FakeDB([]),
        ) is None


class TestWhatsAppResolution:
    def test_resolves_known_contact(self) -> None:
        db = _FakeDB([
            {"name": "Elmara", "phone": "+5511999991234", "email": None},
        ])
        preview = _build_recipient_preview(
            extracted={"to": "Elmara", "text": "Bom dia"},
            connector_id="whatsapp",
            db=db,
        )
        assert preview is not None
        assert preview["channel"] == "whatsapp"
        assert preview["name"] == "Elmara"
        assert preview["phone"] == "+5511999991234"
        assert preview["resolved"] is True
        assert "warning" not in preview

    def test_unknown_contact_warns(self) -> None:
        preview = _build_recipient_preview(
            extracted={"to": "SomePerson", "text": "hi"},
            connector_id="whatsapp",
            db=_FakeDB([]),
        )
        assert preview is not None
        assert preview["resolved"] is False
        assert "warning" in preview
        # Name carries through as the raw input so the user sees what
        # the LLM extracted and can decide to cancel.
        assert preview["name"] == "SomePerson"

    def test_channel_name_in_recipient_field_flagged(self) -> None:
        """The exact production failure: LLM put 'WhatsApp' (the
        channel name) in the ``to`` field."""
        preview = _build_recipient_preview(
            extracted={"to": "WhatsApp", "text": "hi"},
            connector_id="whatsapp",
            db=_FakeDB([
                {"name": "Elmara", "phone": "+5511...", "email": None},
            ]),
        )
        assert preview is not None
        assert preview["resolved"] is False
        assert "channel name" in preview["warning"].lower()

    def test_resolves_via_phone_lookup(self) -> None:
        """When the LLM put the phone number directly, the lookup
        should still surface the contact's name for the card."""
        db = _FakeDB([
            {"name": "Elmara", "phone": "+5511999991234", "email": None},
        ])
        preview = _build_recipient_preview(
            extracted={"to": "+5511999991234"},
            connector_id="whatsapp",
            db=db,
        )
        assert preview is not None
        assert preview["resolved"] is True
        assert preview["name"] == "Elmara"


class TestEmailResolution:
    def test_resolves_via_email(self) -> None:
        db = _FakeDB([
            {
                "name": "Hugo",
                "phone": None,
                "email": "hugo@example.com",
            },
        ])
        preview = _build_recipient_preview(
            extracted={
                "to": "hugo@example.com",
                "subject": "x",
                "body": "y",
            },
            connector_id="apple-mail",
            db=db,
        )
        assert preview is not None
        assert preview["channel"] == "email"
        assert preview["email"] == "hugo@example.com"
        assert preview["resolved"] is True

    def test_email_with_phone_only_contact_unresolved(self) -> None:
        """Channel needs the matching identifier — a contact with only
        a phone can't be the destination for an email."""
        db = _FakeDB([
            {"name": "Sarah", "phone": "+1...", "email": None},
        ])
        preview = _build_recipient_preview(
            extracted={"to": "Sarah", "subject": "x", "body": "y"},
            connector_id="apple-mail",
            db=db,
        )
        assert preview is not None
        assert preview["resolved"] is False


class TestMissingRecipientField:
    def test_no_recipient_field_returns_none(self) -> None:
        preview = _build_recipient_preview(
            extracted={"text": "hi but no recipient"},
            connector_id="whatsapp",
            db=_FakeDB([]),
        )
        assert preview is None


class TestDbFailure:
    def test_db_error_still_returns_preview_with_warning(self) -> None:
        class _Boom:
            def query(self, *a, **k):  # noqa: ANN002, ANN003, ARG002
                raise RuntimeError("db down")

        preview = _build_recipient_preview(
            extracted={"to": "Elmara"},
            connector_id="whatsapp",
            db=_Boom(),
        )
        assert preview is not None
        assert preview["resolved"] is False
        # Name is the raw input — we still want the card to show
        # something so the user can cancel.
        assert preview["name"] == "Elmara"

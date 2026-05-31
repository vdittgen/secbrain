"""Tests for the recipient-profile lookup.

The profile is what lets the param extractor + judge calibrate tone
(intimate for spouse, formal for colleague) and pick the right
grammatical number (singular for a named single recipient). It's a
direct read against the source-of-truth tables: ``raw_contacts``
for the relationship label and ``raw_messages`` for recent outbound
samples.

sensitivity_tier: 2
"""

from __future__ import annotations

from typing import Any

from src.agents.brain.recipient_profile import (
    RecipientProfile,
    format_profile_for_prompt,
    lookup_recipient_profile,
)


class _FakeDB:
    """In-memory stand-in for a DuckDB / SQLite engine.

    Routes queries to canned response lists keyed on a substring of
    the SQL; tests configure the canned responses up front.
    """

    def __init__(self, *, contacts=(), outbound=(), counts=()):
        self._contacts = list(contacts)
        self._outbound = list(outbound)
        self._counts = list(counts)

    def query(self, sql: str, params: list[Any] | None = None) -> list:
        sql_lower = sql.lower()
        if "from raw_contacts" in sql_lower:
            return self._contacts
        if "from raw_messages" in sql_lower and "count" in sql_lower:
            return self._counts
        if "from raw_messages" in sql_lower:
            return self._outbound
        return []


class TestLookupRecipientProfile:
    def test_empty_name_returns_empty_profile(self) -> None:
        profile = lookup_recipient_profile("", _FakeDB())
        assert profile == RecipientProfile()

    def test_none_db_returns_empty_profile(self) -> None:
        profile = lookup_recipient_profile("Elmara", None)
        assert profile == RecipientProfile()

    def test_spouse_relationship_is_picked_up(self) -> None:
        db = _FakeDB(
            contacts=[{"relationship": "wife"}],
            outbound=[
                {"content": "amor te amo"},
                {"content": "já tô voltando"},
            ],
            counts=[{"n": 47}],
        )
        profile = lookup_recipient_profile("Elmara", db)
        assert profile.name == "Elmara"
        assert profile.relationship == "wife"
        assert profile.recent_outbound_samples == (
            "amor te amo",
            "já tô voltando",
        )
        assert profile.count_recent_messages == 47

    def test_relationship_lowercased_and_trimmed(self) -> None:
        db = _FakeDB(contacts=[{"relationship": "  Husband "}])
        profile = lookup_recipient_profile("Hugo", db)
        assert profile.relationship == "husband"

    def test_no_relationship_returns_empty_label(self) -> None:
        db = _FakeDB(contacts=[])
        profile = lookup_recipient_profile("Stranger", db)
        assert profile.relationship == ""
        # Even an empty-relationship profile must not crash later code.
        assert profile.is_present is False

    def test_samples_truncated_to_160_chars(self) -> None:
        long = "x" * 500
        db = _FakeDB(outbound=[{"content": long}])
        profile = lookup_recipient_profile("Friend", db)
        assert len(profile.recent_outbound_samples[0]) == 160

    def test_db_exception_yields_empty_profile(self) -> None:
        class _Boom:
            def query(self, *a, **k):  # noqa: ANN002, ANN003, ARG002
                raise RuntimeError("db down")

        profile = lookup_recipient_profile("Anyone", _Boom())
        assert profile == RecipientProfile(name="Anyone")


class TestFormatProfileForPrompt:
    def test_empty_profile_returns_empty_string(self) -> None:
        assert format_profile_for_prompt(RecipientProfile()) == ""

    def test_includes_relationship_label(self) -> None:
        block = format_profile_for_prompt(
            RecipientProfile(name="Elmara", relationship="wife"),
        )
        assert "Elmara" in block
        assert "wife" in block

    def test_includes_outbound_samples(self) -> None:
        block = format_profile_for_prompt(
            RecipientProfile(
                name="Elmara",
                relationship="wife",
                recent_outbound_samples=("amor te amo", "já tô indo"),
            ),
        )
        assert "amor te amo" in block
        assert "já tô indo" in block

    def test_singular_addressing_directive_in_block(self) -> None:
        """The header line tells the LLM to default to singular
        addressing — that's how the grammatical-number rule fires."""
        block = format_profile_for_prompt(
            RecipientProfile(name="Elmara", relationship="wife"),
        )
        assert "singular" in block.lower()


class TestResolveRecipientName:
    """``_resolve_recipient_name`` in actions.py picks the sender of
    the most recent inbound message — that's the reply target."""

    def test_picks_sender_name_from_inbound_source(self) -> None:
        from src.agents.brain.actions import _resolve_recipient_name

        sources = [
            {
                "source": "whatsapp",
                "sender_name": "Elmara",
                "content": "oi tudo bem?",
                "is_from_me": False,
            },
        ]
        assert _resolve_recipient_name(sources) == "Elmara"

    def test_skips_outbound_messages(self) -> None:
        from src.agents.brain.actions import _resolve_recipient_name

        sources = [
            {
                "source": "whatsapp",
                "sender_name": "User",
                "content": "outbound",
                "is_from_me": True,
            },
            {
                "source": "whatsapp",
                "sender_name": "Elmara",
                "content": "inbound",
                "is_from_me": False,
            },
        ]
        assert _resolve_recipient_name(sources) == "Elmara"

    def test_no_inbound_returns_none(self) -> None:
        from src.agents.brain.actions import _resolve_recipient_name

        assert _resolve_recipient_name(None) is None
        assert _resolve_recipient_name([]) is None
        assert _resolve_recipient_name([
            {"sender_name": "Me", "is_from_me": True},
        ]) is None

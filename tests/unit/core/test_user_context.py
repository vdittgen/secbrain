"""Unit tests for user context assembly and profile inference.

sensitivity_tier: 2
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from src.core.user_context import (
    COUNTRY_CODE_MAP,
    _compute_age,
    _infer_from_phone,
    _name_from_contacts,
    _name_from_emails,
    build_active_topics_context,
    build_user_context,
    infer_user_profile,
)

# All tests that touch resolve_self_jid must patch at the source
# module because _infer_from_phone / _name_from_contacts do a
# lazy ``from src.extensions.bridges.whatsapp.paths import resolve_self_jid``
# inside the function body.
_PATCH_JID = "src.extensions.bridges.whatsapp.paths.resolve_self_jid"
_P = "src.core.user_context"


# -------------------------------------------------------------------
# build_user_context
# -------------------------------------------------------------------


class TestBuildUserContext:
    """Tests for the build_user_context() function."""

    @patch(f"{_P}._get_system_timezone", return_value=None)
    def test_empty_settings_returns_date_line(self, _m: MagicMock) -> None:
        now = datetime(2026, 3, 3, 14, 30, tzinfo=timezone.utc)
        result = build_user_context(settings={}, now=now)
        assert "--- User Context ---" in result
        assert "2026-03-03" in result
        assert "Tuesday" in result
        assert "14:30" in result

    def test_full_profile(self) -> None:
        settings = {
            "user_name": "Vinicius",
            "user_birthday": "1990-05-15",
            "user_location": "Florianopolis, Brazil",
            "user_timezone": "America/Sao_Paulo",
            "user_language": "Portuguese",
            "user_bio": "Software engineer, loves surfing",
        }
        now = datetime(2026, 3, 3, 14, 0, tzinfo=timezone.utc)
        result = build_user_context(settings=settings, now=now)

        assert "User's name: Vinicius" in result
        assert "User's age: 35" in result
        assert "Florianopolis, Brazil" in result
        assert "America/Sao_Paulo" in result
        assert "Portuguese" in result
        assert "Software engineer" in result
        assert "2026-03-03" in result

    def test_partial_profile_only_name(self) -> None:
        settings = {"user_name": "Alice"}
        now = datetime(2026, 6, 15, 10, 0, tzinfo=timezone.utc)
        result = build_user_context(settings=settings, now=now)

        assert "User's name: Alice" in result
        assert "User's age" not in result
        assert "User's location" not in result
        assert "2026-06-15" in result

    def test_timezone_conversion(self) -> None:
        settings = {"user_timezone": "America/Sao_Paulo"}
        # UTC 18:00 → Sao Paulo UTC-3 → 15:00
        now = datetime(2026, 3, 3, 18, 0, tzinfo=timezone.utc)
        result = build_user_context(settings=settings, now=now)
        assert "15:00" in result

    def test_invalid_timezone_degrades(self) -> None:
        settings = {"user_timezone": "Invalid/Timezone_XXX"}
        now = datetime(2026, 3, 3, 14, 30, tzinfo=timezone.utc)
        result = build_user_context(settings=settings, now=now)
        assert "2026-03-03" in result

    def test_no_disk_io_when_settings_provided(self) -> None:
        mock_path = "src.core.user_context.load_llm_settings"
        with patch(mock_path) as mock_load:
            now = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
            build_user_context(
                settings={"user_name": "Test"}, now=now,
            )
            mock_load.assert_not_called()

    def test_reads_from_disk_when_no_settings(self) -> None:
        mock_path = "src.core.user_context.load_llm_settings"
        with patch(
            mock_path, return_value={"user_name": "Disk"},
        ) as mock_load:
            now = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
            result = build_user_context(now=now)
            mock_load.assert_called_once()
            assert "Disk" in result


# -------------------------------------------------------------------
# _compute_age
# -------------------------------------------------------------------


class TestComputeAge:
    """Tests for the _compute_age() helper."""

    def test_age_after_birthday(self) -> None:
        now = datetime(2026, 6, 1, tzinfo=timezone.utc)
        assert _compute_age("1990-05-15", now) == 36

    def test_age_before_birthday(self) -> None:
        now = datetime(2026, 3, 1, tzinfo=timezone.utc)
        assert _compute_age("1990-05-15", now) == 35

    def test_age_on_birthday(self) -> None:
        now = datetime(2026, 5, 15, tzinfo=timezone.utc)
        assert _compute_age("1990-05-15", now) == 36

    def test_invalid_date_returns_none(self) -> None:
        assert _compute_age("not-a-date") is None

    def test_empty_string_returns_none(self) -> None:
        assert _compute_age("") is None

    def test_future_birthday_returns_none(self) -> None:
        now = datetime(2020, 1, 1, tzinfo=timezone.utc)
        assert _compute_age("2025-01-01", now) is None


# -------------------------------------------------------------------
# _infer_from_phone
# -------------------------------------------------------------------


class TestInferFromPhone:
    """Tests for phone-based country inference."""

    @patch(_PATCH_JID, return_value="554892011083")
    def test_brazil_phone(self, _mock: MagicMock) -> None:
        result = _infer_from_phone()
        assert result is not None
        country, tz, lang = result
        assert country == "Brazil"
        assert tz == "America/Sao_Paulo"
        assert lang == "Portuguese"

    @patch(_PATCH_JID, return_value="14155551234")
    def test_us_phone(self, _mock: MagicMock) -> None:
        result = _infer_from_phone()
        assert result is not None
        assert result[0] == "United States"

    @patch(_PATCH_JID, return_value="351912345678")
    def test_portugal_3_digit(self, _mock: MagicMock) -> None:
        result = _infer_from_phone()
        assert result is not None
        assert result[0] == "Portugal"

    @patch(_PATCH_JID, return_value=None)
    def test_no_jid_returns_none(self, _mock: MagicMock) -> None:
        assert _infer_from_phone() is None

    @patch(_PATCH_JID, side_effect=Exception("no creds"))
    def test_exception_returns_none(self, _mock: MagicMock) -> None:
        assert _infer_from_phone() is None


# -------------------------------------------------------------------
# _name_from_contacts
# -------------------------------------------------------------------


class TestNameFromContacts:
    """Tests for name inference from contacts table."""

    def test_finds_matching_contact(self) -> None:
        layer = MagicMock()
        layer.duckdb.query.return_value = [("Vinicius",)]
        with patch(_PATCH_JID, return_value="554892011083"):
            result = _name_from_contacts(layer)
        assert result == "Vinicius"

    def test_no_matching_contact(self) -> None:
        layer = MagicMock()
        layer.duckdb.query.return_value = []
        with patch(_PATCH_JID, return_value="554892011083"):
            result = _name_from_contacts(layer)
        assert result is None

    def test_no_whatsapp_jid(self) -> None:
        layer = MagicMock()
        with patch(_PATCH_JID, return_value=None):
            result = _name_from_contacts(layer)
        assert result is None


# -------------------------------------------------------------------
# _name_from_emails
# -------------------------------------------------------------------


class TestNameFromEmails:
    """Tests for name inference from email addresses."""

    def test_extracts_name_from_brackets(self) -> None:
        layer = MagicMock()
        layer.duckdb.query.return_value = [
            ("Vinicius Dittgen <vini@email.com>", 42),
        ]
        result = _name_from_emails(layer)
        assert result == "Vinicius Dittgen"

    def test_no_name_in_plain_email(self) -> None:
        layer = MagicMock()
        layer.duckdb.query.return_value = [("vini@email.com", 10)]
        result = _name_from_emails(layer)
        assert result is None

    def test_no_emails(self) -> None:
        layer = MagicMock()
        layer.duckdb.query.return_value = []
        result = _name_from_emails(layer)
        assert result is None

    def test_exception_returns_none(self) -> None:
        layer = MagicMock()
        layer.duckdb.query.side_effect = Exception("DB error")
        result = _name_from_emails(layer)
        assert result is None


# -------------------------------------------------------------------
# infer_user_profile (integration)
# -------------------------------------------------------------------


class TestInferUserProfile:
    """Tests for the full infer_user_profile() function."""

    @patch(f"{_P}._infer_from_phone")
    @patch(f"{_P}._infer_name")
    def test_full_inference(
        self,
        mock_name: MagicMock,
        mock_phone: MagicMock,
    ) -> None:
        mock_phone.return_value = (
            "Brazil", "America/Sao_Paulo", "Portuguese",
        )
        mock_name.return_value = "Vinicius"

        result = infer_user_profile(MagicMock())
        assert result["user_name"] == "Vinicius"
        assert result["user_location"] == "Brazil"
        assert result["user_timezone"] == "America/Sao_Paulo"
        assert result["user_language"] == "Portuguese"

    @patch(f"{_P}._infer_from_phone", return_value=None)
    @patch(f"{_P}._infer_name", return_value=None)
    @patch(
        f"{_P}._get_system_timezone",
        return_value="Europe/London",
    )
    def test_fallback_to_system_timezone(
        self,
        _mock_tz: MagicMock,
        _mock_name: MagicMock,
        _mock_phone: MagicMock,
    ) -> None:
        result = infer_user_profile(MagicMock())
        assert result["user_timezone"] == "Europe/London"
        assert "user_name" not in result
        assert "user_location" not in result

    @patch(f"{_P}._infer_from_phone", return_value=None)
    @patch(f"{_P}._infer_name", return_value=None)
    @patch(f"{_P}._get_system_timezone", return_value=None)
    def test_empty_when_no_data(
        self,
        _mock_tz: MagicMock,
        _mock_name: MagicMock,
        _mock_phone: MagicMock,
    ) -> None:
        result = infer_user_profile(MagicMock())
        assert result == {}

    def test_never_infers_birthday_or_bio(self) -> None:
        with (
            patch(
                f"{_P}._infer_from_phone",
                return_value=(
                    "Brazil", "America/Sao_Paulo", "Portuguese",
                ),
            ),
            patch(f"{_P}._infer_name", return_value="Test"),
        ):
            result = infer_user_profile(MagicMock())
        assert "user_birthday" not in result
        assert "user_bio" not in result


# -------------------------------------------------------------------
# COUNTRY_CODE_MAP sanity
# -------------------------------------------------------------------


class TestCountryCodeMap:
    """Basic sanity checks on the country code mapping."""

    def test_has_common_countries(self) -> None:
        assert "55" in COUNTRY_CODE_MAP
        assert "1" in COUNTRY_CODE_MAP
        assert "44" in COUNTRY_CODE_MAP
        assert "49" in COUNTRY_CODE_MAP

    def test_all_entries_have_three_fields(self) -> None:
        for code, value in COUNTRY_CODE_MAP.items():
            assert len(value) == 3, f"{code}: 3 fields"
            country, tz, lang = value
            assert country, f"{code}: country"
            assert tz, f"{code}: timezone"
            assert lang, f"{code}: language"


# -------------------------------------------------------------------
# build_active_topics_context
# -------------------------------------------------------------------


def _make_topics_db(
    contacts: list[dict[str, object]],
) -> MagicMock:
    """Build a mock DB that returns contacts from mart_contact_summary."""
    db = MagicMock()
    db.query.return_value = contacts
    return db


class TestBuildActiveTopicsContext:
    """Tests for the build_active_topics_context() function."""

    def test_formats_correctly(self) -> None:
        contacts = [
            {
                "contact_name": "Maria",
                "top_topic": "father's cancer treatment",
                "max_topic_importance": 9,
                "active_topics_json": json.dumps([
                    {
                        "topic": "father's cancer treatment",
                        "importance": 9,
                        "status": "active",
                    },
                    {
                        "topic": "house renovation",
                        "importance": 6,
                        "status": "active",
                    },
                ]),
                "messages_7d": 12,
            },
            {
                "contact_name": "João",
                "top_topic": "hiring psychologist",
                "max_topic_importance": 7,
                "active_topics_json": json.dumps([
                    {
                        "topic": "hiring psychologist",
                        "importance": 7,
                        "status": "active",
                    },
                ]),
                "messages_7d": 5,
            },
        ]
        db = _make_topics_db(contacts)
        result = build_active_topics_context(db)

        assert "--- Active Topics" in result
        assert "Maria" in result
        assert "father's cancer treatment" in result
        assert "house renovation" in result
        assert "João" in result
        assert "hiring psychologist" in result

    def test_empty_when_no_contacts(self) -> None:
        db = _make_topics_db([])
        assert build_active_topics_context(db) == ""

    def test_none_db_returns_empty(self) -> None:
        assert build_active_topics_context(None) == ""

    def test_respects_max_chars(self) -> None:
        contacts = [
            {
                "contact_name": f"Contact{i}",
                "top_topic": f"topic number {i} that is quite long",
                "max_topic_importance": 8,
                "active_topics_json": None,
                "messages_7d": 10,
            }
            for i in range(20)
        ]
        db = _make_topics_db(contacts)
        result = build_active_topics_context(db, max_chars=200)

        # Should be truncated — not all 20 contacts
        assert len(result) <= 400  # generous bound
        assert "Contact0" in result

    def test_handles_db_error(self) -> None:
        db = MagicMock()
        db.query.side_effect = Exception("DB failure")
        assert build_active_topics_context(db) == ""

    def test_fallback_to_top_topic_when_no_json(self) -> None:
        contacts = [
            {
                "contact_name": "Alice",
                "top_topic": "job interview prep",
                "max_topic_importance": 7,
                "active_topics_json": None,
                "messages_7d": 3,
            },
        ]
        db = _make_topics_db(contacts)
        result = build_active_topics_context(db)

        assert "Alice" in result
        assert "job interview prep" in result

    def test_invalid_json_uses_fallback(self) -> None:
        contacts = [
            {
                "contact_name": "Bob",
                "top_topic": "budget planning",
                "max_topic_importance": 6,
                "active_topics_json": "not valid json{{{",
                "messages_7d": 8,
            },
        ]
        db = _make_topics_db(contacts)
        result = build_active_topics_context(db)

        assert "Bob" in result
        assert "budget planning" in result

"""Unit tests for staging pipeline models.

Each test creates a temporary SQLite database, loads raw schemas and fixtures,
then runs the staging model SQL directly to verify transformations,
computed columns, and data quality constraints.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from src.core.sqlite.engine import DatabaseEngine
from src.core.sqlite.schemas import create_all_tables

from tests.fixtures.sample_data import (
    CALENDAR_EVENTS,
    CONTACTS,
    HEALTH_METRICS,
    MESSAGES,
    NOTES,
    load_all_fixtures,
)

STAGING_DIR = Path(__file__).resolve().parents[3] / "src" / "pipeline" / "staging"


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


def _read_model_sql(model_path: Path) -> str:
    """Read the SQL SELECT/WITH statement from a pipeline model file.

    Handles both legacy MODEL() header format and new plain SQL format.
    """
    text = model_path.read_text()
    match = re.search(r"(?m)^(SELECT|WITH)\b", text)
    if match:
        return text[match.start() :].strip()
    msg = f"Could not find SELECT/WITH in {model_path}"
    raise ValueError(msg)


@pytest.fixture()
def seeded_db(tmp_path: Path) -> DatabaseEngine:
    """DatabaseEngine with all raw schemas and fixtures loaded."""
    db_path = tmp_path / "test_staging.sqlite3"
    engine = DatabaseEngine(db_path=db_path)
    create_all_tables(engine)
    load_all_fixtures(engine)
    yield engine
    engine.close()


def _run_model(engine: DatabaseEngine, model_name: str) -> list[dict]:
    """Run a staging model SQL and return all rows as dicts."""
    sql = _read_model_sql(STAGING_DIR / f"{model_name}.sql")
    return engine.query(sql)


# ---------------------------------------------------------------------------
# stg_messages
# ---------------------------------------------------------------------------


class TestStgMessages:
    def test_row_count_matches_raw(self, seeded_db: DatabaseEngine) -> None:
        """Staging should contain exactly as many rows as the raw table."""
        rows = _run_model(seeded_db, "stg_messages")
        assert len(rows) == len(MESSAGES)

    def test_expected_columns(self, seeded_db: DatabaseEngine) -> None:
        """All expected columns must be present in the output."""
        rows = _run_model(seeded_db, "stg_messages")
        expected = {
            "id", "source", "sender", "recipient", "content",
            "timestamp", "metadata", "sensitivity_tier",
            "message_length", "_loaded_at",
        }
        assert set(rows[0].keys()) == expected

    def test_message_length_computed(self, seeded_db: DatabaseEngine) -> None:
        """message_length must equal the character count of content."""
        rows = _run_model(seeded_db, "stg_messages")
        for row in rows:
            assert row["message_length"] == len(row["content"])

    def test_strings_are_trimmed(self, seeded_db: DatabaseEngine) -> None:
        """Source, sender, recipient should have no leading/trailing whitespace."""
        rows = _run_model(seeded_db, "stg_messages")
        for row in rows:
            assert row["source"] == row["source"].strip()
            assert row["sender"] == row["sender"].strip()
            assert row["recipient"] == row["recipient"].strip()

    def test_loaded_at_not_null(self, seeded_db: DatabaseEngine) -> None:
        """Audit column _loaded_at must never be NULL."""
        rows = _run_model(seeded_db, "stg_messages")
        for row in rows:
            assert row["_loaded_at"] is not None

    def test_sensitivity_tier_values(self, seeded_db: DatabaseEngine) -> None:
        """sensitivity_tier must only contain values 1, 2, or 3."""
        rows = _run_model(seeded_db, "stg_messages")
        for row in rows:
            assert row["sensitivity_tier"] in (1, 2, 3)

    def test_id_uniqueness(self, seeded_db: DatabaseEngine) -> None:
        """All ids must be unique."""
        rows = _run_model(seeded_db, "stg_messages")
        ids = [r["id"] for r in rows]
        assert len(ids) == len(set(ids))

    def test_id_not_null(self, seeded_db: DatabaseEngine) -> None:
        """Primary key id must never be NULL."""
        rows = _run_model(seeded_db, "stg_messages")
        for row in rows:
            assert row["id"] is not None


# ---------------------------------------------------------------------------
# stg_calendar_events
# ---------------------------------------------------------------------------


class TestStgCalendarEvents:
    def test_row_count_matches_raw(self, seeded_db: DatabaseEngine) -> None:
        rows = _run_model(seeded_db, "stg_calendar_events")
        assert len(rows) == len(CALENDAR_EVENTS)

    def test_expected_columns(self, seeded_db: DatabaseEngine) -> None:
        rows = _run_model(seeded_db, "stg_calendar_events")
        expected = {
            "id", "title", "description", "start_time", "end_time",
            "location", "attendees", "sensitivity_tier",
            "attendees_count", "duration_minutes",
            "calendar_name", "calendar_owner_email",
            "is_shared_calendar", "is_subscribed_calendar",
            "self_response_status", "event_origin",
            "_loaded_at",
        }
        assert set(rows[0].keys()) == expected

    def test_attendees_count_positive(self, seeded_db: DatabaseEngine) -> None:
        """Every event should have at least one attendee."""
        rows = _run_model(seeded_db, "stg_calendar_events")
        for row in rows:
            assert row["attendees_count"] >= 1

    def test_duration_minutes_positive(self, seeded_db: DatabaseEngine) -> None:
        """Duration in minutes must be positive (end > start)."""
        rows = _run_model(seeded_db, "stg_calendar_events")
        for row in rows:
            assert row["duration_minutes"] > 0

    def test_known_event_duration(self, seeded_db: DatabaseEngine) -> None:
        """Q2 Planning Session is 10:00-12:00 = 120 minutes."""
        rows = _run_model(seeded_db, "stg_calendar_events")
        q2 = next(r for r in rows if r["id"] == "cal-001")
        assert q2["duration_minutes"] == 120

    def test_known_event_attendees(self, seeded_db: DatabaseEngine) -> None:
        """Q2 Planning Session has 3 attendees."""
        rows = _run_model(seeded_db, "stg_calendar_events")
        q2 = next(r for r in rows if r["id"] == "cal-001")
        assert q2["attendees_count"] == 3

    def test_sensitivity_tier_values(self, seeded_db: DatabaseEngine) -> None:
        rows = _run_model(seeded_db, "stg_calendar_events")
        for row in rows:
            assert row["sensitivity_tier"] in (1, 2, 3)

    def test_id_uniqueness(self, seeded_db: DatabaseEngine) -> None:
        rows = _run_model(seeded_db, "stg_calendar_events")
        ids = [r["id"] for r in rows]
        assert len(ids) == len(set(ids))


# ---------------------------------------------------------------------------
# stg_notes
# ---------------------------------------------------------------------------


class TestStgNotes:
    def test_row_count_matches_raw(self, seeded_db: DatabaseEngine) -> None:
        rows = _run_model(seeded_db, "stg_notes")
        assert len(rows) == len(NOTES)

    def test_expected_columns(self, seeded_db: DatabaseEngine) -> None:
        rows = _run_model(seeded_db, "stg_notes")
        expected = {
            "id", "title", "content", "source", "created_at",
            "updated_at", "tags", "sensitivity_tier",
            "word_count", "tags_csv", "_loaded_at",
        }
        assert set(rows[0].keys()) == expected

    def test_word_count_positive(self, seeded_db: DatabaseEngine) -> None:
        """Every note has content, so word_count must be >= 1."""
        rows = _run_model(seeded_db, "stg_notes")
        for row in rows:
            assert row["word_count"] >= 1

    def test_tags_csv_no_brackets(self, seeded_db: DatabaseEngine) -> None:
        """tags_csv must not contain JSON brackets or quotes."""
        rows = _run_model(seeded_db, "stg_notes")
        for row in rows:
            if row["tags_csv"]:
                assert "[" not in row["tags_csv"]
                assert "]" not in row["tags_csv"]
                assert '"' not in row["tags_csv"]

    def test_known_note_tags(self, seeded_db: DatabaseEngine) -> None:
        """Project Ideas note should have 'ideas, coding, LLM' as tags_csv."""
        rows = _run_model(seeded_db, "stg_notes")
        n = next(r for r in rows if r["id"] == "note-001")
        assert "ideas" in n["tags_csv"]
        assert "coding" in n["tags_csv"]
        assert "LLM" in n["tags_csv"]

    def test_sensitivity_tier_values(self, seeded_db: DatabaseEngine) -> None:
        rows = _run_model(seeded_db, "stg_notes")
        for row in rows:
            assert row["sensitivity_tier"] in (1, 2, 3)

    def test_id_uniqueness(self, seeded_db: DatabaseEngine) -> None:
        rows = _run_model(seeded_db, "stg_notes")
        ids = [r["id"] for r in rows]
        assert len(ids) == len(set(ids))


# ---------------------------------------------------------------------------
# stg_health_metrics
# ---------------------------------------------------------------------------


class TestStgHealthMetrics:
    def test_row_count_matches_raw(self, seeded_db: DatabaseEngine) -> None:
        rows = _run_model(seeded_db, "stg_health_metrics")
        assert len(rows) == len(HEALTH_METRICS)

    def test_expected_columns(self, seeded_db: DatabaseEngine) -> None:
        rows = _run_model(seeded_db, "stg_health_metrics")
        expected = {
            "id", "metric_type", "value", "unit",
            "recorded_at", "source", "sensitivity_tier", "_loaded_at",
        }
        assert set(rows[0].keys()) == expected

    def test_value_is_float(self, seeded_db: DatabaseEngine) -> None:
        """value must be a float (REAL)."""
        rows = _run_model(seeded_db, "stg_health_metrics")
        for row in rows:
            assert isinstance(row["value"], float)

    def test_known_metric_value(self, seeded_db: DatabaseEngine) -> None:
        """Heart rate reading hm-001 should be 72.0 bpm."""
        rows = _run_model(seeded_db, "stg_health_metrics")
        hr = next(r for r in rows if r["id"] == "hm-001")
        assert hr["value"] == 72.0
        assert hr["unit"] == "bpm"

    def test_all_tier_3(self, seeded_db: DatabaseEngine) -> None:
        """All health metrics should be tier 3 (high sensitivity)."""
        rows = _run_model(seeded_db, "stg_health_metrics")
        for row in rows:
            assert row["sensitivity_tier"] == 3

    def test_id_uniqueness(self, seeded_db: DatabaseEngine) -> None:
        rows = _run_model(seeded_db, "stg_health_metrics")
        ids = [r["id"] for r in rows]
        assert len(ids) == len(set(ids))


# ---------------------------------------------------------------------------
# stg_contacts
# ---------------------------------------------------------------------------


class TestStgContacts:
    def test_row_count_matches_raw(self, seeded_db: DatabaseEngine) -> None:
        rows = _run_model(seeded_db, "stg_contacts")
        assert len(rows) == len(CONTACTS)

    def test_expected_columns(self, seeded_db: DatabaseEngine) -> None:
        rows = _run_model(seeded_db, "stg_contacts")
        expected = {
            "id", "name", "email", "phone", "relationship",
            "notes", "last_contact", "sensitivity_tier",
            "days_since_last_contact", "_loaded_at",
        }
        assert set(rows[0].keys()) == expected

    def test_days_since_last_contact_non_negative(
        self, seeded_db: DatabaseEngine,
    ) -> None:
        """days_since_last_contact must be >= 0 when last_contact is set."""
        rows = _run_model(seeded_db, "stg_contacts")
        for row in rows:
            if row["last_contact"] is not None:
                assert row["days_since_last_contact"] >= 0

    def test_days_null_when_no_contact(self, seeded_db: DatabaseEngine) -> None:
        """If last_contact is NULL, days_since_last_contact should be NULL."""
        rows = _run_model(seeded_db, "stg_contacts")
        for row in rows:
            if row["last_contact"] is None:
                assert row["days_since_last_contact"] is None

    def test_sensitivity_tier_values(self, seeded_db: DatabaseEngine) -> None:
        rows = _run_model(seeded_db, "stg_contacts")
        for row in rows:
            assert row["sensitivity_tier"] in (1, 2, 3)

    def test_id_uniqueness(self, seeded_db: DatabaseEngine) -> None:
        rows = _run_model(seeded_db, "stg_contacts")
        ids = [r["id"] for r in rows]
        assert len(ids) == len(set(ids))

    def test_known_contact(self, seeded_db: DatabaseEngine) -> None:
        """Mom contact should have expected data."""
        rows = _run_model(seeded_db, "stg_contacts")
        mom = next(r for r in rows if r["id"] == "con-001")
        assert mom["name"] == "Mom"
        assert mom["relationship"] == "family"
        assert mom["email"] == "mom@family.com"

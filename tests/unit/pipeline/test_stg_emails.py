"""Unit tests for stg_emails staging model."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from src.core.sqlite.engine import DatabaseEngine
from src.core.sqlite.schemas import create_all_tables

from tests.fixtures.sample_data import EMAILS, load_all_fixtures

STAGING_DIR = (
    Path(__file__).resolve().parents[3] / "src" / "pipeline" / "staging"
)


def _read_model_sql(model_path: Path) -> str:
    """Read the SQL SELECT/WITH statement from a pipeline model file."""
    text = model_path.read_text()
    match = re.search(r"(?m)^(SELECT|WITH)\b", text)
    if match:
        return text[match.start():].strip()
    msg = f"Could not find SELECT/WITH in {model_path}"
    raise ValueError(msg)


@pytest.fixture()
def seeded_db(tmp_path: Path) -> DatabaseEngine:
    """DatabaseEngine with raw schemas, migrations, and fixtures."""
    db_path = tmp_path / "test_stg_emails.sqlite3"
    engine = DatabaseEngine(db_path=db_path)
    create_all_tables(engine)
    load_all_fixtures(engine)
    yield engine
    engine.close()


def _run_model(engine: DatabaseEngine) -> list[dict]:
    """Run stg_emails SQL and return all rows."""
    sql = _read_model_sql(STAGING_DIR / "stg_emails.sql")
    return engine.query(sql)


class TestStgEmails:
    def test_row_count_matches_raw(
        self, seeded_db: DatabaseEngine,
    ) -> None:
        """Staging should have same row count as fixtures."""
        rows = _run_model(seeded_db)
        assert len(rows) == len(EMAILS)

    def test_expected_columns(
        self, seeded_db: DatabaseEngine,
    ) -> None:
        """All expected columns must be present."""
        rows = _run_model(seeded_db)
        expected = {
            "id", "source", "message_id", "subject",
            "from_address", "to_addresses", "date",
            "body_preview", "is_read", "folder", "labels",
            "sensitivity_tier", "recipient_count",
            "body_length", "labels_csv", "_loaded_at",
        }
        assert set(rows[0].keys()) == expected

    def test_recipient_count_positive(
        self, seeded_db: DatabaseEngine,
    ) -> None:
        """Every email has at least one recipient."""
        rows = _run_model(seeded_db)
        for row in rows:
            assert row["recipient_count"] >= 1

    def test_body_length_computed(
        self, seeded_db: DatabaseEngine,
    ) -> None:
        """body_length must match actual body_preview length."""
        rows = _run_model(seeded_db)
        for row in rows:
            if row["body_preview"]:
                assert row["body_length"] == len(
                    row["body_preview"],
                )

    def test_strings_are_trimmed(
        self, seeded_db: DatabaseEngine,
    ) -> None:
        """String fields should have no extra whitespace."""
        rows = _run_model(seeded_db)
        for row in rows:
            assert row["source"] == row["source"].strip()
            assert row["subject"] == row["subject"].strip()
            assert (
                row["from_address"]
                == row["from_address"].strip()
            )

    def test_labels_csv_no_brackets(
        self, seeded_db: DatabaseEngine,
    ) -> None:
        """labels_csv must not contain JSON brackets/quotes."""
        rows = _run_model(seeded_db)
        for row in rows:
            if row["labels_csv"]:
                assert "[" not in row["labels_csv"]
                assert "]" not in row["labels_csv"]
                assert '"' not in row["labels_csv"]

    def test_loaded_at_not_null(
        self, seeded_db: DatabaseEngine,
    ) -> None:
        rows = _run_model(seeded_db)
        for row in rows:
            assert row["_loaded_at"] is not None

    def test_sensitivity_tier_values(
        self, seeded_db: DatabaseEngine,
    ) -> None:
        rows = _run_model(seeded_db)
        for row in rows:
            assert row["sensitivity_tier"] in (1, 2, 3)

    def test_id_uniqueness(
        self, seeded_db: DatabaseEngine,
    ) -> None:
        rows = _run_model(seeded_db)
        ids = [r["id"] for r in rows]
        assert len(ids) == len(set(ids))

    def test_known_email(
        self, seeded_db: DatabaseEngine,
    ) -> None:
        """Verify email-001 fixture data is staged correctly."""
        rows = _run_model(seeded_db)
        e1 = next(r for r in rows if r["id"] == "email-001")
        assert e1["subject"] == "Q2 Planning Docs"
        assert e1["from_address"] == "boss@company.com"
        # SQLite stores booleans as integers
        assert e1["is_read"] == 1
        assert e1["folder"] == "INBOX"
        assert e1["recipient_count"] == 1

"""Unit tests for stg_reminders staging model."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from src.core.sqlite.engine import DatabaseEngine
from src.core.sqlite.schemas import create_all_tables

from tests.fixtures.sample_data import REMINDERS, load_all_fixtures

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
    db_path = tmp_path / "test_stg_reminders.sqlite3"
    engine = DatabaseEngine(db_path=db_path)
    create_all_tables(engine)
    load_all_fixtures(engine)
    yield engine
    engine.close()


def _run_model(engine: DatabaseEngine) -> list[dict]:
    """Run stg_reminders SQL and return all rows."""
    sql = _read_model_sql(STAGING_DIR / "stg_reminders.sql")
    return engine.query(sql)


class TestStgReminders:
    def test_row_count_matches_raw(
        self, seeded_db: DatabaseEngine,
    ) -> None:
        rows = _run_model(seeded_db)
        assert len(rows) == len(REMINDERS)

    def test_expected_columns(
        self, seeded_db: DatabaseEngine,
    ) -> None:
        rows = _run_model(seeded_db)
        expected = {
            "id", "source", "title", "due_date", "notes",
            "completed", "list_name", "sensitivity_tier",
            "is_overdue", "days_until_due", "_loaded_at",
        }
        assert set(rows[0].keys()) == expected

    def test_is_overdue_for_past_incomplete(
        self, seeded_db: DatabaseEngine,
    ) -> None:
        """rem-004: due 2025-05-25, not completed => overdue."""
        rows = _run_model(seeded_db)
        rem4 = next(r for r in rows if r["id"] == "rem-004")
        # SQLite stores booleans as integers
        assert rem4["is_overdue"] == 1

    def test_completed_not_overdue(
        self, seeded_db: DatabaseEngine,
    ) -> None:
        """rem-003: due 2025-05-30, completed => not overdue."""
        rows = _run_model(seeded_db)
        rem3 = next(r for r in rows if r["id"] == "rem-003")
        assert rem3["is_overdue"] == 0

    def test_days_until_due_null_when_no_date(
        self, seeded_db: DatabaseEngine,
    ) -> None:
        """rem-005: no due_date => days_until_due is NULL."""
        rows = _run_model(seeded_db)
        rem5 = next(r for r in rows if r["id"] == "rem-005")
        assert rem5["days_until_due"] is None

    def test_no_overdue_when_no_date(
        self, seeded_db: DatabaseEngine,
    ) -> None:
        """Reminders with NULL due_date are not overdue."""
        rows = _run_model(seeded_db)
        no_date = [r for r in rows if r["due_date"] is None]
        for row in no_date:
            assert row["is_overdue"] == 0

    def test_strings_are_trimmed(
        self, seeded_db: DatabaseEngine,
    ) -> None:
        rows = _run_model(seeded_db)
        for row in rows:
            assert row["source"] == row["source"].strip()
            assert row["title"] == row["title"].strip()
            if row["list_name"]:
                assert (
                    row["list_name"]
                    == row["list_name"].strip()
                )

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

    def test_known_reminder(
        self, seeded_db: DatabaseEngine,
    ) -> None:
        """Verify rem-001 fixture data is staged correctly."""
        rows = _run_model(seeded_db)
        r1 = next(r for r in rows if r["id"] == "rem-001")
        assert r1["title"] == "Buy groceries"
        assert r1["list_name"] == "Personal"
        # SQLite stores booleans as integers (0 = False)
        assert r1["completed"] == 0

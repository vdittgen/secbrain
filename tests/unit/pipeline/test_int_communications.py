"""Unit tests for int_communications_enriched intermediate model."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from src.core.sqlite.engine import DatabaseEngine
from src.core.sqlite.schemas import create_all_tables

from tests.fixtures.sample_data import EMAILS, MESSAGES, load_all_fixtures

PIPELINE_DIR = (
    Path(__file__).resolve().parents[3] / "src" / "pipeline"
)
STAGING_DIR = PIPELINE_DIR / "staging"
INTERMEDIATE_DIR = PIPELINE_DIR / "intermediate"


def _read_model_sql(model_path: Path) -> str:
    """Read the SQL SELECT/WITH statement from a pipeline model file."""
    text = model_path.read_text()
    match = re.search(r"(?m)^(SELECT|WITH)\b", text)
    if match:
        return text[match.start():].strip()
    msg = f"Could not find SELECT/WITH in {model_path}"
    raise ValueError(msg)


def _materialize_staging(engine: DatabaseEngine) -> None:
    """Materialize needed staging models."""
    for name in [
        "stg_messages", "stg_contacts", "stg_emails",
    ]:
        sql = _read_model_sql(STAGING_DIR / f"{name}.sql")
        engine.execute(f"CREATE TABLE {name} AS {sql}")


@pytest.fixture()
def pipeline_db(tmp_path: Path) -> DatabaseEngine:
    """SQLite with raw data + materialized staging tables."""
    engine = DatabaseEngine(
        db_path=tmp_path / "test_int_comms.sqlite3",
    )
    create_all_tables(engine)
    load_all_fixtures(engine)
    _materialize_staging(engine)
    yield engine
    engine.close()


def _run_model(engine: DatabaseEngine) -> list[dict]:
    """Run int_communications_enriched and return rows."""
    sql = _read_model_sql(
        INTERMEDIATE_DIR / "int_communications_enriched.sql",
    )
    return engine.query(sql)


class TestIntCommunicationsEnriched:
    def test_row_count_is_messages_plus_emails(
        self, pipeline_db: DatabaseEngine,
    ) -> None:
        """UNION of messages + emails."""
        rows = _run_model(pipeline_db)
        assert len(rows) == len(MESSAGES) + len(EMAILS)

    def test_expected_columns(
        self, pipeline_db: DatabaseEngine,
    ) -> None:
        rows = _run_model(pipeline_db)
        expected = {
            "id", "channel_type", "sender",
            "content_preview", "occurred_at",
            "sensitivity_tier", "content_length",
            "contact_name", "relationship",
            "comm_category", "_loaded_at",
        }
        assert set(rows[0].keys()) == expected

    def test_category_values(
        self, pipeline_db: DatabaseEngine,
    ) -> None:
        rows = _run_model(pipeline_db)
        valid = {"personal", "work", "health", "other"}
        for row in rows:
            assert row["comm_category"] in valid

    def test_slack_classified_as_work(
        self, pipeline_db: DatabaseEngine,
    ) -> None:
        """Slack messages should be work."""
        rows = _run_model(pipeline_db)
        slack = [
            r for r in rows if r["channel_type"] == "slack"
        ]
        assert len(slack) > 0
        for row in slack:
            assert row["comm_category"] == "work"

    def test_email_channel_type(
        self, pipeline_db: DatabaseEngine,
    ) -> None:
        """All email-sourced rows have channel_type='email'."""
        rows = _run_model(pipeline_db)
        emails = [
            r for r in rows if r["id"].startswith("email-")
        ]
        assert len(emails) == len(EMAILS)
        for row in emails:
            assert row["channel_type"] == "email"

    def test_contact_name_resolved(
        self, pipeline_db: DatabaseEngine,
    ) -> None:
        """alice@company.com should resolve to Alice Kim."""
        rows = _run_model(pipeline_db)
        alice = [
            r for r in rows
            if r["sender"] == "alice@company.com"
        ]
        assert len(alice) > 0
        assert alice[0]["contact_name"] == "Alice Kim"

    def test_sensitivity_tier_values(
        self, pipeline_db: DatabaseEngine,
    ) -> None:
        rows = _run_model(pipeline_db)
        for row in rows:
            assert row["sensitivity_tier"] in (1, 2, 3)

    def test_id_uniqueness(
        self, pipeline_db: DatabaseEngine,
    ) -> None:
        rows = _run_model(pipeline_db)
        ids = [r["id"] for r in rows]
        assert len(ids) == len(set(ids))

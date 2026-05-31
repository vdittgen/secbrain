"""Unit tests for mart_communications mart model."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from src.core.sqlite.engine import DatabaseEngine
from src.core.sqlite.schemas import create_all_tables

from tests.fixtures.sample_data import load_all_fixtures

PIPELINE_DIR = (
    Path(__file__).resolve().parents[3] / "src" / "pipeline"
)
STAGING_DIR = PIPELINE_DIR / "staging"
INTERMEDIATE_DIR = PIPELINE_DIR / "intermediate"
MARTS_DIR = PIPELINE_DIR / "marts"


def _read_model_sql(model_path: Path) -> str:
    """Read the SQL SELECT/WITH statement from a pipeline model file."""
    text = model_path.read_text()
    match = re.search(r"(?m)^(SELECT|WITH)\b", text)
    if match:
        return text[match.start():].strip()
    msg = f"Could not find SELECT/WITH in {model_path}"
    raise ValueError(msg)


def _materialize_staging(engine: DatabaseEngine) -> None:
    """Materialize staging models needed for communications."""
    for name in [
        "stg_messages", "stg_contacts", "stg_emails",
    ]:
        sql = _read_model_sql(STAGING_DIR / f"{name}.sql")
        engine.execute(f"CREATE TABLE {name} AS {sql}")


def _materialize_intermediate(
    engine: DatabaseEngine,
) -> None:
    """Materialize intermediate communications model."""
    sql = _read_model_sql(
        INTERMEDIATE_DIR
        / "int_communications_enriched.sql",
    )
    engine.execute(
        f"CREATE TABLE int_communications_enriched AS {sql}",
    )


@pytest.fixture()
def pipeline_db(tmp_path: Path) -> DatabaseEngine:
    """SQLite with all layers through intermediate."""
    engine = DatabaseEngine(
        db_path=tmp_path / "test_mart_comms.sqlite3",
    )
    create_all_tables(engine)
    load_all_fixtures(engine)
    _materialize_staging(engine)
    _materialize_intermediate(engine)
    yield engine
    engine.close()


def _run_model(engine: DatabaseEngine) -> list[dict]:
    """Run mart_communications and return rows."""
    sql = _read_model_sql(
        MARTS_DIR / "mart_communications.sql",
    )
    return engine.query(sql)


class TestMartCommunications:
    def test_has_rows(
        self, pipeline_db: DatabaseEngine,
    ) -> None:
        rows = _run_model(pipeline_db)
        assert len(rows) > 0

    def test_expected_columns(
        self, pipeline_db: DatabaseEngine,
    ) -> None:
        rows = _run_model(pipeline_db)
        expected = {
            "summary_date", "channel_type",
            "comm_category", "message_count",
            "avg_content_length", "top_sender",
            "sensitivity_tier", "_loaded_at",
        }
        assert set(rows[0].keys()) == expected

    def test_category_values(
        self, pipeline_db: DatabaseEngine,
    ) -> None:
        rows = _run_model(pipeline_db)
        valid = {"personal", "work", "health", "other"}
        for row in rows:
            assert row["comm_category"] in valid

    def test_message_count_positive(
        self, pipeline_db: DatabaseEngine,
    ) -> None:
        rows = _run_model(pipeline_db)
        for row in rows:
            assert row["message_count"] > 0

    def test_unique_date_channel_category(
        self, pipeline_db: DatabaseEngine,
    ) -> None:
        """Grain is (date, channel_type, comm_category)."""
        rows = _run_model(pipeline_db)
        keys = [
            (
                r["summary_date"],
                r["channel_type"],
                r["comm_category"],
            )
            for r in rows
        ]
        assert len(keys) == len(set(keys))

    def test_sensitivity_tier_is_2(
        self, pipeline_db: DatabaseEngine,
    ) -> None:
        """Fixed sensitivity_tier=2 for aggregated data."""
        rows = _run_model(pipeline_db)
        for row in rows:
            assert row["sensitivity_tier"] == 2

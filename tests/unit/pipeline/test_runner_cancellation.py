"""Unit tests for PipelineRunner cancel_check parameter.

Tests cover: cancellation before pipeline, cancellation during execution,
backward compatibility when cancel_check is not provided, event emission,
and stats recording for cancelled runs.

sensitivity_tier: 1
"""

from __future__ import annotations

from pathlib import Path

import pytest
from src.core.sqlite.engine import DatabaseEngine
from src.core.sqlite.schemas import create_all_tables
from src.pipeline.runner import PipelineRunner
from src.pipeline.stats import ProcessingStats

from tests.fixtures.sample_data import load_all_fixtures

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def seeded_db(tmp_path: Path) -> DatabaseEngine:
    """Create a SQLite DB with all tables and fixtures loaded.

    sensitivity_tier: 1
    """
    db_path = tmp_path / "test.sqlite3"
    db = DatabaseEngine(db_path)
    create_all_tables(db)
    load_all_fixtures(db)
    return db


@pytest.fixture()
def stats(tmp_path: Path) -> ProcessingStats:
    """Create a ProcessingStats with a temporary stats file.

    sensitivity_tier: 1
    """
    return ProcessingStats(stats_path=tmp_path / "stats.jsonl")


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestRunnerCancellation:
    """Tests for PipelineRunner.run() with cancel_check."""

    def test_cancel_before_pipeline_run(
        self,
        seeded_db: DatabaseEngine,
        stats: ProcessingStats,
    ) -> None:
        """cancel_check returning True before execution cancels.

        sensitivity_tier: 1
        """
        runner = PipelineRunner(duckdb=seeded_db, stats=stats)
        result = runner.run(
            trigger="test",
            cancel_check=lambda: True,
        )

        assert result.status == "cancelled"
        assert result.models_processed == []
        assert result.rows_processed == {}

    def test_cancel_during_model_execution(
        self,
        seeded_db: DatabaseEngine,
        stats: ProcessingStats,
    ) -> None:
        """cancel_check returning True mid-execution gives partial.

        sensitivity_tier: 1
        """
        call_count = 0

        def cancel_after_3_models() -> bool:
            nonlocal call_count
            call_count += 1
            # Call 1: before execution starts → False
            # The executor checks cancel between each model.
            # After 3 models, cancel.
            return call_count > 4

        runner = PipelineRunner(duckdb=seeded_db, stats=stats)
        result = runner.run(
            trigger="test",
            cancel_check=cancel_after_3_models,
        )

        assert result.status == "cancelled"
        # Some models should have been processed
        assert len(result.models_processed) >= 1

    def test_cancel_check_none_backward_compatible(
        self,
        seeded_db: DatabaseEngine,
        stats: ProcessingStats,
    ) -> None:
        """run() without cancel_check behaves normally.

        sensitivity_tier: 1
        """
        runner = PipelineRunner(duckdb=seeded_db, stats=stats)
        result = runner.run(trigger="test")

        assert result.status == "success"
        assert result.trigger == "test"

    def test_cancelled_run_emits_cancelled_event(
        self,
        seeded_db: DatabaseEngine,
        stats: ProcessingStats,
    ) -> None:
        """on_progress receives 'cancelled' event when cancel fires.

        sensitivity_tier: 1
        """
        events: list[dict] = []
        runner = PipelineRunner(duckdb=seeded_db, stats=stats)
        runner.run(
            trigger="test",
            on_progress=events.append,
            cancel_check=lambda: True,
        )

        types = [e["type"] for e in events]
        assert "cancelled" in types

    def test_cancelled_run_recorded_in_stats(
        self,
        seeded_db: DatabaseEngine,
        stats: ProcessingStats,
    ) -> None:
        """Stats file records a run with status='cancelled'.

        sensitivity_tier: 1
        """
        runner = PipelineRunner(duckdb=seeded_db, stats=stats)
        runner.run(
            trigger="test",
            cancel_check=lambda: True,
        )

        history = stats.get_run_history(limit=1)
        assert len(history) == 1
        assert history[0].status == "cancelled"

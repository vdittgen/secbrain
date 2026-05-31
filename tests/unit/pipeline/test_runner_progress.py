"""Unit tests for PipelineRunner progress callback mechanism.

Tests cover: callback invocation, event ordering, backward compatibility
when no callback is provided, and error event emission.

sensitivity_tier: 1
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

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


class TestRunnerProgressCallback:
    """Tests for PipelineRunner.run() with on_progress callback."""

    def test_on_progress_receives_started_and_done(
        self,
        seeded_db: DatabaseEngine,
        stats: ProcessingStats,
    ) -> None:
        """Callback receives 'started' and 'done' events on success.

        sensitivity_tier: 1
        """
        events: list[dict] = []
        runner = PipelineRunner(duckdb=seeded_db, stats=stats)
        runner.run(trigger="test", on_progress=events.append)

        types = [e["type"] for e in events]
        assert types[0] == "started"
        assert "sqlmesh_running" in types
        assert "done" in types

    def test_on_progress_receives_model_complete_events(
        self,
        seeded_db: DatabaseEngine,
        stats: ProcessingStats,
    ) -> None:
        """Callback receives 'model_complete' per model.

        sensitivity_tier: 1
        """
        events: list[dict] = []
        runner = PipelineRunner(duckdb=seeded_db, stats=stats)
        runner.run(trigger="test", on_progress=events.append)

        model_events = [
            e for e in events if e["type"] == "model_complete"
        ]
        assert len(model_events) > 0

        # Verify step_index increments correctly
        for i, event in enumerate(model_events):
            assert event["step_index"] == i + 1

    def test_on_progress_none_is_backward_compatible(
        self,
        seeded_db: DatabaseEngine,
        stats: ProcessingStats,
    ) -> None:
        """run() works without on_progress (no errors raised).

        sensitivity_tier: 1
        """
        runner = PipelineRunner(duckdb=seeded_db, stats=stats)
        result = runner.run(trigger="test")

        assert result.status == "success"
        assert result.trigger == "test"

    def test_error_emits_error_event(
        self,
        seeded_db: DatabaseEngine,
        stats: ProcessingStats,
    ) -> None:
        """on_progress receives 'error' event when pipeline fails.

        sensitivity_tier: 1
        """
        events: list[dict] = []
        runner = PipelineRunner(duckdb=seeded_db, stats=stats)

        with patch(
            "src.pipeline.runner.execute_pipeline",
            side_effect=RuntimeError("Pipeline failed"),
        ):
            result = runner.run(
                trigger="test", on_progress=events.append,
            )

        assert result.status == "failed"
        error_events = [
            e for e in events if e["type"] == "error"
        ]
        assert len(error_events) == 1
        assert "Pipeline failed" in error_events[0]["error"]

    def test_done_event_contains_run_metadata(
        self,
        seeded_db: DatabaseEngine,
        stats: ProcessingStats,
    ) -> None:
        """The 'done' event includes run_id and duration.

        sensitivity_tier: 1
        """
        events: list[dict] = []
        runner = PipelineRunner(duckdb=seeded_db, stats=stats)
        result = runner.run(
            trigger="test", on_progress=events.append,
        )

        done_events = [
            e for e in events if e["type"] == "done"
        ]
        assert len(done_events) == 1
        done = done_events[0]
        assert done["run_id"] == result.run_id
        assert done["duration_seconds"] > 0
        assert done["step_index"] == done["total_steps"]

    def test_model_complete_includes_rows_processed(
        self,
        seeded_db: DatabaseEngine,
        stats: ProcessingStats,
    ) -> None:
        """Each 'model_complete' event has a rows_processed field.

        sensitivity_tier: 1
        """
        events: list[dict] = []
        runner = PipelineRunner(duckdb=seeded_db, stats=stats)
        runner.run(trigger="test", on_progress=events.append)

        for event in events:
            if event["type"] == "model_complete":
                assert "rows_processed" in event
                assert isinstance(event["rows_processed"], int)

    def test_elapsed_seconds_increases(
        self,
        seeded_db: DatabaseEngine,
        stats: ProcessingStats,
    ) -> None:
        """elapsed_seconds should be non-negative on all events.

        sensitivity_tier: 1
        """
        events: list[dict] = []
        runner = PipelineRunner(duckdb=seeded_db, stats=stats)
        runner.run(trigger="test", on_progress=events.append)

        for event in events:
            assert "elapsed_seconds" in event
            assert event["elapsed_seconds"] >= 0

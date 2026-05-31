"""Unit tests for pipeline ProcessingStats and PipelineRunner staleness.

Tests cover: record/retrieve runs, average duration, linear regression
estimation, persistence across instances, and staleness detection
against a temporary DuckDB.

sensitivity_tier: 1
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from src.core.sqlite.engine import DatabaseEngine
from src.core.sqlite.schemas import create_all_tables
from src.pipeline.runner import PipelineRunner
from src.pipeline.stats import PipelineRun, ProcessingStats

from tests.fixtures.sample_data import load_all_fixtures

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_run(
    run_id: str = "run-001",
    status: str = "success",
    duration: float = 10.0,
    rows_processed: dict[str, int] | None = None,
    trigger: str = "manual",
) -> PipelineRun:
    """Build a minimal PipelineRun for testing.

    sensitivity_tier: 1
    """
    now = datetime.now(tz=timezone.utc)
    return PipelineRun(
        run_id=run_id,
        started_at=now,
        completed_at=now,
        duration_seconds=duration,
        status=status,
        models_processed=["staging.stg_messages"],
        rows_processed=rows_processed or {"staging.stg_messages": 5},
        rows_changed={"staging.stg_messages": 5},
        trigger=trigger,
        error=None,
    )


# ---------------------------------------------------------------------------
# TestProcessingStats
# ---------------------------------------------------------------------------


class TestProcessingStats:
    """Tests for the ProcessingStats JSONL store."""

    def test_empty_stats_returns_none(self, tmp_path: Path) -> None:
        """get_last_run returns None when no runs recorded."""
        stats = ProcessingStats(stats_path=tmp_path / "stats.jsonl")
        assert stats.get_last_run() is None
        assert stats.get_last_successful_run() is None
        assert stats.get_run_history() == []
        assert stats.get_average_duration() is None

    def test_record_and_retrieve_run(self, tmp_path: Path) -> None:
        """Recording a run makes it retrievable via get_last_run."""
        stats = ProcessingStats(stats_path=tmp_path / "stats.jsonl")
        run = _make_run("run-001")
        stats.record_run(run)

        last = stats.get_last_run()
        assert last is not None
        assert last.run_id == "run-001"
        assert last.status == "success"

    def test_multiple_runs_history_order(
        self, tmp_path: Path,
    ) -> None:
        """get_run_history returns newest first, capped at limit."""
        stats = ProcessingStats(stats_path=tmp_path / "stats.jsonl")
        for i in range(5):
            stats.record_run(_make_run(run_id=f"run-{i:03d}"))

        history = stats.get_run_history(limit=3)
        assert len(history) == 3
        assert history[0].run_id == "run-004"
        assert history[2].run_id == "run-002"

    def test_get_last_successful_run_skips_failures(
        self, tmp_path: Path,
    ) -> None:
        """get_last_successful_run ignores failed runs."""
        stats = ProcessingStats(stats_path=tmp_path / "stats.jsonl")
        stats.record_run(_make_run("run-001", status="success"))
        stats.record_run(_make_run("run-002", status="failed"))

        last_ok = stats.get_last_successful_run()
        assert last_ok is not None
        assert last_ok.run_id == "run-001"

    def test_average_duration_correct(self, tmp_path: Path) -> None:
        """get_average_duration returns mean of successful runs."""
        stats = ProcessingStats(stats_path=tmp_path / "stats.jsonl")
        for duration in [10.0, 20.0, 30.0]:
            stats.record_run(_make_run(duration=duration))

        avg = stats.get_average_duration(last_n=3)
        assert avg == pytest.approx(20.0)

    def test_average_duration_only_successful(
        self, tmp_path: Path,
    ) -> None:
        """get_average_duration excludes failed runs."""
        stats = ProcessingStats(stats_path=tmp_path / "stats.jsonl")
        stats.record_run(
            _make_run("r1", status="success", duration=10.0),
        )
        stats.record_run(
            _make_run("r2", status="failed", duration=999.0),
        )

        avg = stats.get_average_duration()
        assert avg == pytest.approx(10.0)

    def test_estimate_fallback_fewer_than_3_points(
        self, tmp_path: Path,
    ) -> None:
        """estimate_next_duration falls back to avg*1.2 with <3 runs."""
        stats = ProcessingStats(stats_path=tmp_path / "stats.jsonl")
        stats.record_run(_make_run(duration=10.0))
        stats.record_run(_make_run(duration=20.0))

        est = stats.estimate_next_duration(data_size=100)
        # avg = 15.0, fallback = 15.0 * 1.2 = 18.0
        assert est == pytest.approx(18.0)

    def test_estimate_cold_start_no_runs(
        self, tmp_path: Path,
    ) -> None:
        """estimate_next_duration returns 60.0 with no runs at all."""
        stats = ProcessingStats(stats_path=tmp_path / "stats.jsonl")
        est = stats.estimate_next_duration(data_size=0)
        assert est == pytest.approx(60.0)

    def test_estimate_linear_regression(
        self, tmp_path: Path,
    ) -> None:
        """estimate_next_duration uses linear regression with >=3 points."""
        stats = ProcessingStats(stats_path=tmp_path / "stats.jsonl")
        # Perfect linear: y = 0.5x + 5
        for rows, dur in [(10, 10.0), (20, 15.0), (30, 20.0)]:
            stats.record_run(
                _make_run(
                    duration=dur,
                    rows_processed={"staging.stg_messages": rows},
                ),
            )

        # x=40 → y = 0.5*40 + 5 = 25.0
        est = stats.estimate_next_duration(data_size=40)
        assert est == pytest.approx(25.0, abs=0.5)

    def test_append_only_persists_across_instances(
        self, tmp_path: Path,
    ) -> None:
        """Records persist across ProcessingStats instances."""
        path = tmp_path / "stats.jsonl"
        s1 = ProcessingStats(stats_path=path)
        s1.record_run(_make_run("run-A"))

        s2 = ProcessingStats(stats_path=path)
        last = s2.get_last_run()
        assert last is not None
        assert last.run_id == "run-A"


# ---------------------------------------------------------------------------
# TestPipelineRunnerStaleness
# ---------------------------------------------------------------------------


class TestPipelineRunnerStaleness:
    """Tests for PipelineRunner.is_stale() and related methods."""

    @pytest.fixture()
    def seeded_db(self, tmp_path: Path) -> DatabaseEngine:
        """SQLite DB with raw schemas and fixtures loaded.

        sensitivity_tier: 1
        """
        engine = DatabaseEngine(db_path=tmp_path / "test.sqlite3")
        create_all_tables(engine)
        load_all_fixtures(engine)
        yield engine
        engine.close()

    def test_is_stale_with_no_successful_run(
        self,
        seeded_db: DatabaseEngine,
        tmp_path: Path,
    ) -> None:
        """is_stale() returns True when no successful run exists."""
        stats = ProcessingStats(stats_path=tmp_path / "stats.jsonl")
        runner = PipelineRunner(duckdb=seeded_db, stats=stats)
        assert runner.is_stale() is True

    def test_is_stale_false_after_run_recorded(
        self,
        seeded_db: DatabaseEngine,
        tmp_path: Path,
    ) -> None:
        """is_stale() returns False when last run is after all data."""
        stats = ProcessingStats(stats_path=tmp_path / "stats.jsonl")
        runner = PipelineRunner(duckdb=seeded_db, stats=stats)

        # Record a successful run with completed_at in the future.
        future = datetime.now(tz=timezone.utc) + timedelta(seconds=60)
        run = PipelineRun(
            run_id="run-001",
            started_at=datetime.now(tz=timezone.utc),
            completed_at=future,
            duration_seconds=1.0,
            status="success",
            models_processed=["staging.stg_messages"],
            rows_processed={"staging.stg_messages": 5},
            rows_changed={"staging.stg_messages": 5},
            trigger="manual",
            error=None,
        )
        stats.record_run(run)

        assert runner.is_stale() is False

    def test_get_pending_changes_with_no_run(
        self,
        seeded_db: DatabaseEngine,
        tmp_path: Path,
    ) -> None:
        """get_pending_changes() returns all rows when no run exists."""
        stats = ProcessingStats(stats_path=tmp_path / "stats.jsonl")
        runner = PipelineRunner(duckdb=seeded_db, stats=stats)
        pending = runner.get_pending_changes()
        assert "raw_messages" in pending
        assert all(v >= 0 for v in pending.values())

    def test_dry_run_returns_estimate(
        self,
        seeded_db: DatabaseEngine,
        tmp_path: Path,
    ) -> None:
        """dry_run() returns a PipelineEstimate with valid fields."""
        stats = ProcessingStats(stats_path=tmp_path / "stats.jsonl")
        runner = PipelineRunner(duckdb=seeded_db, stats=stats)
        estimate = runner.dry_run()

        assert estimate.estimated_duration_seconds > 0
        assert isinstance(estimate.models_to_process, list)
        assert len(estimate.models_to_process) > 0
        assert estimate.last_run_at is None
        assert isinstance(estimate.pending_changes, dict)

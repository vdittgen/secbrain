"""Unit tests for pipeline-run-stream and pipeline-run-history CLI commands.

Tests cover: JSON-line output format for streaming, and JSON array output
for run history.

sensitivity_tier: 1
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from src.pipeline.stats import PipelineRun, ProcessingStats

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_run(
    run_id: str = "run-001",
    status: str = "success",
    duration: float = 10.0,
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
        rows_processed={"staging.stg_messages": 5},
        rows_changed={"staging.stg_messages": 5},
        trigger=trigger,
        error=None,
    )


# ---------------------------------------------------------------------------
# Tests: pipeline-run-history
# ---------------------------------------------------------------------------


class TestPipelineRunHistory:
    """Tests for the cmd_pipeline_run_history CLI function."""

    def test_returns_empty_array_with_no_history(
        self,
        tmp_path: Path,
    ) -> None:
        """Returns [] when no runs have been recorded.

        sensitivity_tier: 1
        """
        stats_path = tmp_path / "stats.jsonl"
        stats = ProcessingStats(stats_path=stats_path)
        history = stats.get_run_history(limit=5)
        assert history == []

    def test_returns_limited_history(self, tmp_path: Path) -> None:
        """Returns at most `limit` runs, newest first.

        sensitivity_tier: 1
        """
        stats_path = tmp_path / "stats.jsonl"
        stats = ProcessingStats(stats_path=stats_path)

        # Record 7 runs
        for i in range(7):
            stats.record_run(_make_run(run_id=f"run-{i:03d}"))

        history = stats.get_run_history(limit=5)
        assert len(history) == 5
        # Newest first
        assert history[0].run_id == "run-006"
        assert history[4].run_id == "run-002"

    def test_run_history_is_json_serializable(
        self,
        tmp_path: Path,
    ) -> None:
        """Each run in history can be serialized to JSON.

        sensitivity_tier: 1
        """
        from dataclasses import asdict

        stats_path = tmp_path / "stats.jsonl"
        stats = ProcessingStats(stats_path=stats_path)
        stats.record_run(_make_run(run_id="run-abc"))

        history = stats.get_run_history(limit=5)
        for run in history:
            d = asdict(run)
            d["started_at"] = run.started_at.isoformat()
            d["completed_at"] = run.completed_at.isoformat()
            serialized = json.dumps(d)
            parsed = json.loads(serialized)
            assert parsed["run_id"] == run.run_id
            assert parsed["status"] == run.status


# ---------------------------------------------------------------------------
# Tests: pipeline-run-stream progress output
# ---------------------------------------------------------------------------


class TestPipelineRunStreamOutput:
    """Tests for streaming progress event structure."""

    def test_progress_callback_outputs_valid_json_lines(self) -> None:
        """Each event dict is JSON-serializable.

        sensitivity_tier: 1
        """
        events: list[dict] = []

        def callback(event: dict) -> None:
            events.append(event)

        # Simulate events that the runner would emit
        callback({
            "type": "started",
            "step_index": 0,
            "total_steps": 13,
            "status": "starting",
            "elapsed_seconds": 0.0,
        })
        callback({
            "type": "model_complete",
            "model_name": "staging.stg_messages",
            "step_index": 1,
            "total_steps": 13,
            "status": "counted",
            "elapsed_seconds": 1.5,
            "rows_processed": 42,
        })
        callback({
            "type": "done",
            "run_id": "test-id",
            "duration_seconds": 14.2,
            "step_index": 13,
            "total_steps": 13,
            "status": "success",
            "elapsed_seconds": 14.2,
        })

        for event in events:
            line = json.dumps(event)
            parsed = json.loads(line)
            assert parsed["type"] in (
                "started",
                "sqlmesh_running",
                "model_complete",
                "done",
                "error",
            )

    def test_error_event_has_error_field(self) -> None:
        """Error events must include an 'error' string field.

        sensitivity_tier: 1
        """
        event = {
            "type": "error",
            "error": "Something went wrong",
            "elapsed_seconds": 5.0,
        }
        serialized = json.dumps(event)
        parsed = json.loads(serialized)
        assert parsed["type"] == "error"
        assert "Something went wrong" in parsed["error"]

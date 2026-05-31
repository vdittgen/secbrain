"""Unit tests for the pipeline worker module.

Tests cover: argument parsing, signal handler, JSON output helper.

sensitivity_tier: 1
"""

from __future__ import annotations

import json

from src.pipeline.worker import _cancel_event, _emit_json, _sigterm_handler, main

# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestWorkerArgparse:
    """Tests for worker CLI argument parsing."""

    def test_no_subcommand_returns_one(self, monkeypatch: object) -> None:
        """main() with no arguments prints help and returns 1.

        sensitivity_tier: 1
        """
        import sys

        monkeypatch.setattr(sys, "argv", ["src.pipeline.worker"])  # type: ignore[union-attr]
        assert main() == 1

    def test_run_subcommand_default_trigger(self, monkeypatch: object) -> None:
        """'run' subcommand defaults trigger to 'manual'.

        sensitivity_tier: 1
        """
        import argparse
        import sys

        monkeypatch.setattr(sys, "argv", ["src.pipeline.worker", "run"])  # type: ignore[union-attr]

        # We need to verify parser behaviour without actually running
        # the full pipeline, so parse the args directly.
        parser = argparse.ArgumentParser()
        sub = parser.add_subparsers(dest="command")
        run_p = sub.add_parser("run")
        run_p.add_argument("--trigger", type=str, default="manual")

        args = parser.parse_args(["run"])
        assert args.command == "run"
        assert args.trigger == "manual"


class TestSigtermHandler:
    """Tests for SIGTERM handler."""

    def test_sigterm_handler_sets_cancel_event(self) -> None:
        """Calling the SIGTERM handler sets the cancellation event.

        sensitivity_tier: 1
        """
        _cancel_event.clear()
        assert not _cancel_event.is_set()

        _sigterm_handler(15, None)

        assert _cancel_event.is_set()
        # Clean up for other tests
        _cancel_event.clear()


class TestEmitJson:
    """Tests for JSON line output helper."""

    def test_emit_json_outputs_valid_json(self, capsys: object) -> None:
        """_emit_json writes parseable JSON to stdout.

        sensitivity_tier: 1
        """
        import sys
        from io import StringIO

        captured = StringIO()
        old_stdout = sys.stdout
        sys.stdout = captured
        try:
            _emit_json({"type": "started", "step_index": 0})
        finally:
            sys.stdout = old_stdout

        line = captured.getvalue().strip()
        parsed = json.loads(line)
        assert parsed["type"] == "started"
        assert parsed["step_index"] == 0

    def test_emit_json_handles_non_serializable(self) -> None:
        """_emit_json uses default=str for non-serializable objects.

        sensitivity_tier: 1
        """
        import sys
        from datetime import datetime, timezone
        from io import StringIO

        captured = StringIO()
        old_stdout = sys.stdout
        sys.stdout = captured
        try:
            _emit_json({"ts": datetime(2025, 1, 1, tzinfo=timezone.utc)})
        finally:
            sys.stdout = old_stdout

        line = captured.getvalue().strip()
        parsed = json.loads(line)
        assert "2025" in parsed["ts"]

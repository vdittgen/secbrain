"""Unit tests for the Ollama preemption and quiet-window module."""

from __future__ import annotations

import time
from pathlib import Path
from unittest.mock import patch

import src.models.ollama_preempt as preempt_mod
from src.models.ollama_preempt import (
    check_preempted,
    clear_preempt,
    is_quiet_window,
    signal_preempt,
)


class TestPreemptSignal:
    """Verify signal/check/clear lifecycle."""

    def test_signal_and_check(self, tmp_path: Path) -> None:
        with patch.object(
            preempt_mod, "_PREEMPT_PATH", tmp_path / ".preempt",
        ):
            signal_preempt()
            assert check_preempted() is True

    def test_clear_removes_signal(self, tmp_path: Path) -> None:
        with patch.object(
            preempt_mod, "_PREEMPT_PATH", tmp_path / ".preempt",
        ):
            signal_preempt()
            clear_preempt()
            assert check_preempted() is False

    def test_no_signal_file_not_preempted(self, tmp_path: Path) -> None:
        with patch.object(
            preempt_mod, "_PREEMPT_PATH", tmp_path / ".preempt",
        ):
            assert check_preempted() is False


class TestQuietWindow:
    """Verify quiet-window detection."""

    def test_no_signal_is_quiet(self, tmp_path: Path) -> None:
        with patch.object(
            preempt_mod, "_PREEMPT_PATH", tmp_path / ".preempt",
        ):
            assert is_quiet_window() is True

    def test_recent_signal_not_quiet(self, tmp_path: Path) -> None:
        with patch.object(
            preempt_mod, "_PREEMPT_PATH", tmp_path / ".preempt",
        ):
            signal_preempt()
            assert is_quiet_window() is False

    def test_old_signal_is_quiet(self, tmp_path: Path) -> None:
        with patch.object(
            preempt_mod, "_PREEMPT_PATH", tmp_path / ".preempt",
        ):
            # Write a timestamp 60 seconds ago
            old_ts = str(time.time() - 60)
            (tmp_path / ".preempt").write_text(old_ts)
            assert is_quiet_window() is True

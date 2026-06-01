"""Unit tests for :mod:`src.agents.core.cancel_registry`.

The registry has two surfaces: an in-process ``threading.Event`` cache
and an on-disk flag file. Both must agree about whether a run was
cancelled, including across processes — which we simulate here by
reading the flag file directly.

sensitivity_tier: 1
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from src.agents.core import cancel_registry


@pytest.fixture(autouse=True)
def _isolated_cancel_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Point the registry at a temp directory and clear it after.

    Without this, tests would write into ``~/.arandu/data/cancel/``
    on the developer's machine and possibly collide with a real
    streaming run.

    sensitivity_tier: 1
    """
    monkeypatch.setenv("ARANDU_DATA_DIR", str(tmp_path))
    cancel_registry._reset_for_tests()
    yield
    cancel_registry._reset_for_tests()


def test_cancel_token_creates_event_for_new_id() -> None:
    """First call for a run_id creates and returns its event.

    sensitivity_tier: 1
    """
    ev = cancel_registry.cancel_token("run-a")
    assert not ev.is_set()


def test_request_cancel_writes_flag_and_sets_event() -> None:
    """``request_cancel`` always writes the flag and sets the in-mem event.

    sensitivity_tier: 1
    """
    ev = cancel_registry.cancel_token("run-b")
    assert cancel_registry.request_cancel("run-b") is True
    assert ev.is_set()
    assert cancel_registry.should_stop("run-b")


def test_should_stop_picks_up_cross_process_flag(tmp_path: Path) -> None:
    """A flag written by an "other process" still triggers should_stop.

    Simulates the real wire path: ``stop-research`` subprocess writes
    the flag file; the ``ask-stream`` subprocess sees it via
    ``should_stop`` without ever having called ``cancel_token``.

    sensitivity_tier: 1
    """
    # No in-process token registered.
    flag = Path(os.environ["ARANDU_DATA_DIR"]) / "cancel" / "run-c.flag"
    flag.parent.mkdir(parents=True, exist_ok=True)
    flag.touch()
    assert cancel_registry.should_stop("run-c")


def test_release_clears_event_and_flag() -> None:
    """``release`` drops both the in-memory event and the on-disk flag.

    sensitivity_tier: 1
    """
    cancel_registry.cancel_token("run-d")
    cancel_registry.request_cancel("run-d")
    assert cancel_registry.should_stop("run-d")

    cancel_registry.release("run-d")
    assert not cancel_registry.should_stop("run-d")


def test_request_cancel_returns_true_even_without_prior_token() -> None:
    """Caller in a different process never reserved a token — still OK.

    The flag file is written, so a future ``should_stop`` from any
    process sees the cancellation. Returning ``True`` is the
    well-formed answer; only filesystem errors yield ``False``.

    sensitivity_tier: 1
    """
    assert cancel_registry.request_cancel("run-e") is True
    assert cancel_registry.should_stop("run-e")


def test_should_stop_unknown_id_returns_false() -> None:
    """An id that was never registered nor flagged returns False.

    sensitivity_tier: 1
    """
    assert cancel_registry.should_stop("nonexistent-run") is False

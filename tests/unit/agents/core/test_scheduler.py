"""LLMScheduler concurrency and tier-priority tests.

Verifies that:
- ``Tier.SYSTEM`` bypasses queues and never blocks.
- Concurrency caps are honoured per tier.
- ``starve_background_on_interactive`` makes background defer until
  interactive callers drain.

sensitivity_tier: N/A
"""

from __future__ import annotations

import threading
import time

import pytest
from src.agents.core.scheduler import (
    LLMScheduler,
    SchedulerConfig,
    Tier,
)


def test_system_tier_does_not_block() -> None:
    cfg = SchedulerConfig(
        interactive_concurrency=0,
        proactive_concurrency=0,
        background_concurrency=0,
    )
    scheduler = LLMScheduler(cfg)
    start = time.monotonic()
    with scheduler.acquire(Tier.SYSTEM, agent_id="firewall.injection"):
        pass
    assert (time.monotonic() - start) < 0.1


def test_blocked_route_rejected() -> None:
    scheduler = LLMScheduler()
    with pytest.raises(ValueError):
        cm = scheduler.acquire(Tier.INTERACTIVE, route="blocked")
        cm.__enter__()


def test_concurrency_cap_enforced() -> None:
    cfg = SchedulerConfig(
        interactive_concurrency=1,
        proactive_concurrency=1,
        background_concurrency=1,
        starve_background_on_interactive=False,
    )
    scheduler = LLMScheduler(cfg)

    barrier = threading.Event()
    second_started = threading.Event()

    def first() -> None:
        with scheduler.acquire(Tier.INTERACTIVE, agent_id="brain"):
            barrier.wait(timeout=2)

    def second() -> None:
        with scheduler.acquire(Tier.INTERACTIVE, agent_id="brain"):
            second_started.set()

    t1 = threading.Thread(target=first)
    t2 = threading.Thread(target=second)
    t1.start()
    time.sleep(0.05)
    t2.start()
    time.sleep(0.1)
    assert not second_started.is_set(), "cap should have blocked"
    barrier.set()
    t1.join(timeout=2)
    t2.join(timeout=2)
    assert second_started.is_set()


def test_background_defers_when_interactive_waits() -> None:
    cfg = SchedulerConfig(
        interactive_concurrency=1,
        background_concurrency=1,
        starve_background_on_interactive=True,
    )
    scheduler = LLMScheduler(cfg)

    interactive_holding = threading.Event()
    interactive_release = threading.Event()
    background_acquired = threading.Event()

    def interactive() -> None:
        with scheduler.acquire(Tier.INTERACTIVE, agent_id="brain"):
            interactive_holding.set()
            interactive_release.wait(timeout=2)

    def background() -> None:
        with scheduler.acquire(Tier.BACKGROUND, agent_id="triage"):
            background_acquired.set()

    # Start a background-blocking interactive holder first.
    t_int = threading.Thread(target=interactive)
    t_int.start()
    assert interactive_holding.wait(timeout=2)

    # Now start a second interactive that will queue. While it waits,
    # the background admission should be deferred.
    waiting = threading.Event()

    def interactive_waiter() -> None:
        waiting.set()
        with scheduler.acquire(Tier.INTERACTIVE, agent_id="brain"):
            pass

    t_int_wait = threading.Thread(target=interactive_waiter)
    t_int_wait.start()
    waiting.wait(timeout=2)
    # Give the waiter a moment to enter the semaphore acquire.
    time.sleep(0.05)

    t_bg = threading.Thread(target=background)
    t_bg.start()
    time.sleep(0.2)
    assert not background_acquired.is_set(), (
        "background should defer while interactive queued"
    )

    interactive_release.set()
    t_int.join(timeout=2)
    t_int_wait.join(timeout=2)
    t_bg.join(timeout=2)
    assert background_acquired.is_set()


def test_metrics_snapshot_records_calls() -> None:
    scheduler = LLMScheduler()
    with scheduler.acquire(Tier.INTERACTIVE, agent_id="brain"):
        pass
    metrics = scheduler.metrics_snapshot()
    assert any(m["agent_id"] == "brain" for m in metrics)
    assert any(m["tier"] == "INTERACTIVE" for m in metrics)

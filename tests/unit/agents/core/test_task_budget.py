"""Unit tests for :mod:`src.agents.core.task_budget`.

sensitivity_tier: 1
"""

from __future__ import annotations

import pytest
from src.agents.core.task_budget import TaskBudget, TaskClass


def test_interactive_fast_factory_reflects_at_10s() -> None:
    """Default chat budget triggers the first review at the 10s mark.

    sensitivity_tier: 1
    """
    b = TaskBudget.interactive_fast()
    assert b.task_class is TaskClass.INTERACTIVE_FAST
    assert b.first_reflect_at_s == 10.0


def test_interactive_deep_uses_longer_total_hint() -> None:
    """Promoting to DEEP gives the UI a longer ``expected_total_s`` hint.

    sensitivity_tier: 1
    """
    fast = TaskBudget.interactive_fast()
    deep = TaskBudget.interactive_deep()
    assert deep.expected_total_s > fast.expected_total_s


def test_background_deep_first_reflect_is_later() -> None:
    """Background callers (daily brief) wait longer before reflecting.

    sensitivity_tier: 1
    """
    bg = TaskBudget.background_deep()
    fast = TaskBudget.interactive_fast()
    assert bg.first_reflect_at_s > fast.first_reflect_at_s
    assert bg.task_class is TaskClass.BACKGROUND_DEEP


@pytest.mark.parametrize(
    "task_class",
    [
        TaskClass.INTERACTIVE_FAST,
        TaskClass.INTERACTIVE_DEEP,
        TaskClass.BACKGROUND_DEEP,
    ],
)
def test_for_class_round_trips(task_class: TaskClass) -> None:
    """``for_class`` returns the canonical budget for every class.

    sensitivity_tier: 1
    """
    b = TaskBudget.for_class(task_class)
    assert b.task_class is task_class


def test_for_class_rejects_unknown() -> None:
    """Unknown classes raise ``ValueError`` rather than silently default.

    sensitivity_tier: 1
    """
    with pytest.raises(ValueError):
        TaskBudget.for_class("garbage")  # type: ignore[arg-type]

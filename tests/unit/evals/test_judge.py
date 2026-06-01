"""LLM-judge wrapper tests.

We don't reach a real model — the judge has to degrade gracefully
when the remote endpoint can't be constructed, and it has to honour
the kill switch. The integration with a live model is exercised by
``make evals`` itself.

sensitivity_tier: N/A
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest
from evals import judge as judge_mod


@pytest.fixture(autouse=True)
def _reset_judge_cache() -> Any:
    """Ensure each test sees a fresh module-level cache."""
    judge_mod.reset_for_tests()
    yield
    judge_mod.reset_for_tests()


def test_grade_returns_none_when_kill_switch_set(monkeypatch) -> None:
    monkeypatch.setenv("ARANDU_EVAL_JUDGE_DISABLED", "1")
    assert (
        judge_mod.grade(
            rubric="anything", inputs="x", output_text="y", threshold=7,
        )
        is None
    )


def test_grade_returns_none_when_factory_missing(monkeypatch) -> None:
    monkeypatch.delenv("ARANDU_EVAL_JUDGE_DISABLED", raising=False)

    def boom() -> Any:
        raise RuntimeError("no remote endpoint configured")

    monkeypatch.setattr(
        "src.agents.core.model_factory.default_factory",
        lambda: MagicMock(get=lambda _: boom()),
        raising=False,
    )
    # First call resolves "unavailable" reason; subsequent calls
    # return None without retrying so we don't thrash.
    assert (
        judge_mod.grade(
            rubric="anything", inputs="x", output_text="y", threshold=7,
        )
        is None
    )
    assert (
        judge_mod.grade(
            rubric="anything", inputs="x", output_text="y", threshold=7,
        )
        is None
    )


def test_grade_passes_threshold_check(monkeypatch) -> None:
    """A score >= threshold flips passed=True even if the model said False."""
    monkeypatch.delenv("ARANDU_EVAL_JUDGE_DISABLED", raising=False)
    fake_agent = MagicMock()
    fake_agent.run_sync.return_value = MagicMock(
        output=judge_mod.JudgeVerdict(
            score=8, passed=False, reason="model was unsure",
        ),
    )
    monkeypatch.setattr(
        judge_mod, "_build_judge",
        lambda: (fake_agent, judge_mod._JudgeCfg(available=True, reason="")),
    )
    verdict = judge_mod.grade(
        rubric="any", inputs={"q": "x"}, output_text="ok", threshold=7,
    )
    assert verdict is not None
    assert verdict.score == 8
    assert verdict.passed is True


def test_grade_handles_judge_exception(monkeypatch) -> None:
    monkeypatch.delenv("ARANDU_EVAL_JUDGE_DISABLED", raising=False)
    fake_agent = MagicMock()
    fake_agent.run_sync.side_effect = RuntimeError("network down")
    monkeypatch.setattr(
        judge_mod, "_build_judge",
        lambda: (fake_agent, judge_mod._JudgeCfg(available=True, reason="")),
    )
    assert (
        judge_mod.grade(
            rubric="any", inputs="x", output_text="y", threshold=7,
        )
        is None
    )


def test_render_for_prompt_json_for_dicts() -> None:
    out = judge_mod._render_for_prompt({"q": "hi", "n": 2})
    assert '"q"' in out
    assert '"n"' in out


def test_render_for_prompt_passthrough_for_strings() -> None:
    assert judge_mod._render_for_prompt("plain") == "plain"

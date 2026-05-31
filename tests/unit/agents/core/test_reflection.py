"""Unit tests for :mod:`src.agents.core.reflection`.

We stub the underlying LLM by injecting a fake ReflectorAgent that
returns a canned record, so these tests don't hit pydantic-ai at all
and run without network or model setup.

sensitivity_tier: 1
"""

from __future__ import annotations

from dataclasses import dataclass

from src.agents.core.agent_base import AgentRunRecord
from src.agents.core.output_types import ReflectionVerdict
from src.agents.core.reflection import (
    Reflector,
    ToolCallEntry,
    _render_tool_log,
)
from src.agents.core.task_budget import TaskClass


@dataclass
class _CannedAgent:
    """Stand-in for ReflectorAgent with a pre-baked record."""

    record: AgentRunRecord
    calls: list[str]

    def run(self, prompt: str) -> AgentRunRecord:
        self.calls.append(prompt)
        return self.record


def _record_with(verdict: ReflectionVerdict) -> AgentRunRecord:
    return AgentRunRecord(
        agent_id="reflector",
        output=verdict,
        duration_ms=10.0,
        llm_calls=1,
    )


def test_review_returns_verdict_from_agent() -> None:
    """Happy path: the agent's output flows back unchanged.

    sensitivity_tier: 1
    """
    verdict = ReflectionVerdict(
        continue_research=True,
        reason="needs cross-source synthesis",
        suggested_class="interactive_deep",
    )
    agent = _CannedAgent(record=_record_with(verdict), calls=[])
    refl = Reflector(agent=agent)  # type: ignore[arg-type]

    result = refl.review(
        "How are my goals tracking?",
        tool_log=(),
        elapsed_s=11.2,
        current_class=TaskClass.INTERACTIVE_FAST,
    )
    assert result.continue_research is True
    assert result.suggested_class == "interactive_deep"
    assert "How are my goals tracking?" in agent.calls[0]


def test_review_fails_closed_on_agent_exception() -> None:
    """A broken Reflector must not stall the run forever.

    The wrapper returns ``continue_research=False`` so the reflective
    runner injects a STOP_REQUEST and the model wraps up cleanly.

    sensitivity_tier: 1
    """

    class _BrokenAgent:
        def run(self, prompt: str) -> AgentRunRecord:
            raise RuntimeError("LLM exploded")

    refl = Reflector(agent=_BrokenAgent())  # type: ignore[arg-type]
    verdict = refl.review(
        "anything",
        tool_log=(),
        elapsed_s=10.0,
        current_class=TaskClass.INTERACTIVE_FAST,
    )
    assert verdict.continue_research is False


def test_review_fails_closed_when_record_has_no_output() -> None:
    """``record.output is None`` is treated the same as an exception.

    sensitivity_tier: 1
    """
    empty_record = AgentRunRecord(
        agent_id="reflector",
        output=None,
        duration_ms=0.0,
        llm_calls=1,
        error="parse error",
    )
    agent = _CannedAgent(record=empty_record, calls=[])
    refl = Reflector(agent=agent)  # type: ignore[arg-type]

    verdict = refl.review(
        "anything", tool_log=(), elapsed_s=10.0,
        current_class=TaskClass.INTERACTIVE_FAST,
    )
    assert verdict.continue_research is False


def test_render_tool_log_truncates_and_numbers() -> None:
    """Tool log is rendered with index + truncated args/result.

    sensitivity_tier: 1
    """
    log = (
        ToolCallEntry(
            name="recall_context",
            args_summary="a" * 200,
            result_summary="r" * 200,
            duration_ms=42.0,
            status="ok",
        ),
    )
    rendered = _render_tool_log(log)
    assert rendered.startswith("[1] recall_context(")
    assert "..." not in rendered  # truncation is just a slice
    # Args truncated to 60 chars.
    assert "a" * 60 in rendered
    assert "a" * 61 not in rendered


def test_render_tool_log_empty_is_human_readable() -> None:
    """An empty tool log renders as a clear marker, not an empty string.

    sensitivity_tier: 1
    """
    assert _render_tool_log(()) == "(no tools called yet)"

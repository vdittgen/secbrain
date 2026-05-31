"""LLM judge for eval datasets.

Runs a separate pydantic-ai ``Agent`` whose only job is to grade an
agent output against a rubric and return a 0-10 score with a short
reason. Used by :class:`evals.evaluators.LLMJudgeOnReason` and
:class:`evals.evaluators.LLMJudgeOnField` to upgrade datasets from
"did it crash?" structural checks to actual quality checks.

Routing — the judge uses the model resolved by
``default_factory().get("remote")``, which in SecBrain is the local
Ollama model. Eval inputs are synthetic dataset cases, not user
data, so the egress firewall is not consulted.

When the model isn't reachable (daemon down) :func:`grade` returns
``None`` and the evaluator records the case as "skipped — judge
unavailable" rather than failing it. This keeps ``make evals``
runnable for structural-only checks.

sensitivity_tier: N/A
"""

from __future__ import annotations

import asyncio
import logging
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class JudgeVerdict(BaseModel):
    """Structured grade returned by the judge agent.

    sensitivity_tier: N/A
    """

    score: int = Field(ge=0, le=10)
    passed: bool
    reason: str


_SYSTEM_PROMPT = """\
You are an evaluation judge for an AI assistant's outputs. Given a
case's INPUTS, the agent's OUTPUT, and a RUBRIC, score the output
from 0 to 10 against the rubric and decide whether it passes.

Rules:
- ``score``: integer 0-10. 0 = utter failure / hallucination / off-topic;
  5 = partial / hedged but on-topic; 7 = solid response that meets the
  rubric; 10 = exemplary.
- ``passed``: true iff score >= the threshold the caller specified.
- ``reason``: one short sentence (<= 25 words), specific. Quote the
  failing detail when score < threshold. Never echo the rubric back.
- Be strict on fabrication: any invented name, date, number, or fact
  not present in INPUTS drops the score below 5.
- Be lenient on stylistic differences when the rubric is satisfied.
"""


@dataclass(frozen=True)
class _JudgeCfg:
    """Resolved judge configuration.

    sensitivity_tier: N/A
    """

    available: bool
    reason: str  # populated when unavailable


_judge_agent: Any | None = None
_judge_cfg: _JudgeCfg | None = None
_judge_lock = threading.Lock()


def _build_judge() -> tuple[Any | None, _JudgeCfg]:
    """Build the pydantic-ai judge agent or return why we can't.

    sensitivity_tier: N/A
    """
    try:
        from pydantic_ai import Agent  # type: ignore
    except ImportError:
        return None, _JudgeCfg(
            available=False,
            reason="pydantic-ai not installed",
        )
    try:
        from src.agents.core.model_factory import default_factory
    except Exception as exc:  # noqa: BLE001
        return None, _JudgeCfg(
            available=False, reason=f"model factory unavailable: {exc}",
        )
    try:
        model = default_factory().get("remote")
    except Exception as exc:  # noqa: BLE001
        return None, _JudgeCfg(
            available=False, reason=f"remote model unavailable: {exc}",
        )
    # Reuse the same `pydantic_ai.Agent` path the SBAgents use. The
    # judge needs typed output but no tools, no scheduler — direct
    # construction is fine here.
    agent = Agent(
        model=model,
        output_type=JudgeVerdict,
        system_prompt=_SYSTEM_PROMPT,
    )
    return agent, _JudgeCfg(available=True, reason="")


def _judge() -> tuple[Any | None, _JudgeCfg]:
    """Return a cached judge agent + availability flag.

    sensitivity_tier: N/A
    """
    global _judge_agent, _judge_cfg
    if _judge_cfg is not None:
        return _judge_agent, _judge_cfg
    with _judge_lock:
        if _judge_cfg is not None:
            return _judge_agent, _judge_cfg
        _judge_agent, _judge_cfg = _build_judge()
        return _judge_agent, _judge_cfg


def reset_for_tests() -> None:
    """Drop the cached judge agent. Used by unit tests.

    sensitivity_tier: N/A
    """
    global _judge_agent, _judge_cfg
    with _judge_lock:
        _judge_agent = None
        _judge_cfg = None


def grade(
    *,
    rubric: str,
    inputs: Any,
    output_text: str,
    threshold: int = 7,
) -> JudgeVerdict | None:
    """Run the judge on one case. Returns ``None`` if the judge is offline.

    Eval suites that ship LLM-judge evaluators degrade gracefully on
    offline runs — the evaluator records the case as ``skipped`` so
    the structural assertions still gate the suite.

    sensitivity_tier: N/A
    """
    if os.environ.get("SECBRAIN_EVAL_JUDGE_DISABLED") == "1":
        return None
    agent, cfg = _judge()
    if agent is None or not cfg.available:
        return None
    prompt = (
        "RUBRIC:\n"
        f"{rubric.strip()}\n\n"
        f"PASS THRESHOLD: score >= {threshold}\n\n"
        "CASE INPUTS:\n"
        f"{_render_for_prompt(inputs)}\n\n"
        "AGENT OUTPUT:\n"
        f"{output_text.strip()}\n\n"
        "Return a JudgeVerdict."
    )
    try:
        result = _run_agent_blocking(agent, prompt)
    except Exception:  # noqa: BLE001
        logger.warning("Judge call failed", exc_info=True)
        return None
    verdict = result.output if hasattr(result, "output") else result
    if not isinstance(verdict, JudgeVerdict):
        return None
    # Trust the model's `passed` boolean only as a sanity check; the
    # caller's threshold is the source of truth.
    return JudgeVerdict(
        score=verdict.score,
        passed=verdict.score >= threshold,
        reason=verdict.reason,
    )


_judge_executor: ThreadPoolExecutor | None = None


def _run_agent_blocking(agent: Any, prompt: str) -> Any:
    """Invoke ``agent.run_sync`` even when an asyncio loop is running.

    pydantic-evals' ``Dataset.evaluate_sync`` owns the outer event
    loop, so calling ``run_sync`` from inside an evaluator hits
    ``RuntimeError: This event loop is already running``. We detect
    that case and dispatch the judge call to a dedicated worker
    thread that gets its own loop. When no loop is active we still
    call ``run_sync`` directly so unit tests and offline callers stay
    on the fast path.

    sensitivity_tier: N/A
    """
    try:
        asyncio.get_running_loop()
        loop_running = True
    except RuntimeError:
        loop_running = False
    if not loop_running:
        return agent.run_sync(prompt)
    global _judge_executor
    if _judge_executor is None:
        _judge_executor = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="evals-judge",
        )
    future = _judge_executor.submit(agent.run_sync, prompt)
    return future.result()


def _render_for_prompt(value: Any) -> str:
    """Stringify a YAML-loaded input for the judge prompt.

    Strings pass through; dicts/lists are JSON-encoded so the judge
    sees structure rather than a Python repr.

    sensitivity_tier: N/A
    """
    if isinstance(value, str):
        return value
    try:
        import json
        return json.dumps(value, indent=2, default=str)
    except (TypeError, ValueError):
        return str(value)


__all__ = [
    "JudgeVerdict",
    "grade",
    "reset_for_tests",
]

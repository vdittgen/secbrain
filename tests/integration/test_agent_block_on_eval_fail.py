"""Per-agent block after eval failure under local-only mode.

Confirms that:

- ``cmd_agents_run_eval`` writes a block row when the active policy
  is ``local-only`` and the run's status is ``failed``.
- ``chat_via_firewalls`` short-circuits with ``GatewayBlocked`` for
  the blocked agent.
- Sibling agents are unaffected by another agent's block.
- A subsequent ``passed`` run clears the block.

The eval runner itself is monkeypatched so we don't need a live
model — the test exercises the *gateway-level* enforcement, not the
underlying suite.

sensitivity_tier: N/A
"""

from __future__ import annotations

import io
import json
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from src.agents.core.agent_block_store import (
    default_agent_block_store,
    reset_agent_block_store_for_tests,
)
from src.agents.core.audit import reset_default_chain_for_tests
from src.agents.core.scheduler import (
    SchedulerConfig,
    reset_default_scheduler_for_tests,
)
from src.agents.eval_runner import EvalRun
from src.agents.firewall.egress_firewall import (
    EgressPolicy,
    Lane,
    reset_egress_firewall_for_tests,
)
from src.agents.firewall.injection_firewall import (
    reset_injection_firewall_for_tests,
)
from src.models.llm_gateway import (
    GatewayBlocked,
    chat_via_firewalls,
    set_provider_factory_for_tests,
)
from src.models.llm_provider import LLMResponse
from src.models.redaction_registry import reset_redaction_registry_for_tests


def _fake_run(agent_id: str, status: str) -> EvalRun:
    return EvalRun(
        run_id=f"r-{agent_id}",
        agent_id=agent_id,
        suite="test",
        trigger="manual",
        started_at="2026-05-15T00:00:00+00:00",
        finished_at="2026-05-15T00:00:01+00:00",
        status=status,
        cases_total=1,
        cases_passed=1 if status == "passed" else 0,
        cases_failed=0 if status == "passed" else 1,
        failed_cases=([] if status == "passed"
                      else [{"case": "c1", "reason": "x"}]),
        error=None,
    )


@pytest.fixture(autouse=True)
def _isolate(tmp_path: Path, monkeypatch):
    monkeypatch.setenv(
        "ARANDU_AUDIT_PATH", str(tmp_path / "audit.jsonl"),
    )
    reset_default_chain_for_tests()
    reset_injection_firewall_for_tests()
    reset_egress_firewall_for_tests(
        policy=EgressPolicy(
            routing="local-only",
            local_inference_for_sensitive=True,
        ),
    )
    reset_default_scheduler_for_tests(SchedulerConfig())
    reset_redaction_registry_for_tests(
        path=tmp_path / "redaction.sqlite",
    )
    reset_agent_block_store_for_tests(
        path=tmp_path / "blocks.sqlite",
    )
    monkeypatch.setattr(
        "src.agents.cli_handlers._ensure_bootstrap", lambda: None,
    )
    # cmd_agents_run_eval looks up the agent definition; pretend
    # every id is registered.
    monkeypatch.setattr(
        "src.agents.cli_handlers.get_agent", lambda _aid: MagicMock(),
        raising=False,
    )

    def _resolve_get_agent(aid):
        return MagicMock(agent_id=aid)

    import src.agents.core.registry as registry_mod
    monkeypatch.setattr(
        registry_mod, "get_agent", _resolve_get_agent,
        raising=False,
    )


def _capture(call) -> dict:
    buf = io.StringIO()
    with redirect_stdout(buf):
        call()
    out = buf.getvalue().strip().splitlines()[-1]
    return json.loads(out)


def _stub_provider() -> None:
    def factory(_route: str):
        provider = MagicMock()
        provider.chat.return_value = LLMResponse(
            content="ok", model="stub",
        )
        return provider

    set_provider_factory_for_tests(factory)


def test_failed_eval_blocks_agent_at_gateway(monkeypatch) -> None:
    monkeypatch.setattr(
        "src.agents.eval_runner.run_agent_eval",
        lambda aid, **_kw: _fake_run(aid, "failed"),
    )
    from src.agents.cli_handlers import cmd_agents_run_eval

    payload = _capture(lambda: cmd_agents_run_eval("brain.alpha"))
    assert payload["run"]["status"] == "failed"
    assert default_agent_block_store().get_block("brain.alpha") is not None

    _stub_provider()
    try:
        with pytest.raises(GatewayBlocked):
            chat_via_firewalls(
                [{"role": "user", "content": "hello"}],
                agent_id="brain.alpha",
                lane=Lane.INTERACTIVE,
                agent_max_tier=1,
            )
    finally:
        set_provider_factory_for_tests(None)


def test_block_does_not_affect_siblings(monkeypatch) -> None:
    monkeypatch.setattr(
        "src.agents.eval_runner.run_agent_eval",
        lambda aid, **_kw: _fake_run(aid, "failed"),
    )
    from src.agents.cli_handlers import cmd_agents_run_eval

    _capture(lambda: cmd_agents_run_eval("brain.alpha"))

    _stub_provider()
    try:
        # Sibling has no block — call still succeeds.
        resp = chat_via_firewalls(
            [{"role": "user", "content": "hi"}],
            agent_id="brain.beta",
            lane=Lane.INTERACTIVE,
            agent_max_tier=1,
        )
        assert resp.content == "ok"
    finally:
        set_provider_factory_for_tests(None)


def test_passed_re_run_clears_block(monkeypatch) -> None:
    from src.agents.cli_handlers import cmd_agents_run_eval

    # First: fail → block written.
    monkeypatch.setattr(
        "src.agents.eval_runner.run_agent_eval",
        lambda aid, **_kw: _fake_run(aid, "failed"),
    )
    _capture(lambda: cmd_agents_run_eval("brain.alpha"))
    assert default_agent_block_store().get_block("brain.alpha") is not None

    # Second: pass → block cleared.
    monkeypatch.setattr(
        "src.agents.eval_runner.run_agent_eval",
        lambda aid, **_kw: _fake_run(aid, "passed"),
    )
    _capture(lambda: cmd_agents_run_eval("brain.alpha"))
    assert default_agent_block_store().get_block("brain.alpha") is None

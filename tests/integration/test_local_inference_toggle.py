"""Local-inference toggle integration tests.

Exercises ``cmd_set_local_inference_for_sensitive`` end-to-end:

- Every agent passes → flag commits and the egress firewall reloads
  into ``local-only`` mode.
- One agent fails → the flag stays ``false`` and the response carries
  the failure list.

The eval-runner is monkeypatched to return synthetic
:class:`EvalRun` rows so the test doesn't need a live local model.

sensitivity_tier: N/A
"""

from __future__ import annotations

import io
import json
from contextlib import redirect_stdout
from pathlib import Path

import pytest
from src.agents.core.agent_block_store import (
    reset_agent_block_store_for_tests,
)
from src.agents.core.audit import reset_default_chain_for_tests
from src.agents.eval_runner import EvalRun
from src.agents.firewall.egress_firewall import (
    EgressPolicy,
    default_egress_firewall,
    reset_egress_firewall_for_tests,
)


def _fake_run(agent_id: str, *, status: str) -> EvalRun:
    return EvalRun(
        run_id=f"r-{agent_id}",
        agent_id=agent_id,
        suite="test",
        trigger="local_inference_gate",
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
    settings_path = tmp_path / "settings.json"
    settings_path.write_text("{}")
    monkeypatch.setattr(
        "src.agents.cli_handlers._SETTINGS_PATH", settings_path,
    )
    monkeypatch.setattr(
        "src.agents.firewall.egress_firewall.SETTINGS_PATH", settings_path,
    )
    monkeypatch.setenv(
        "ARANDU_AUDIT_PATH", str(tmp_path / "audit.jsonl"),
    )
    reset_default_chain_for_tests()
    reset_egress_firewall_for_tests(
        policy=EgressPolicy(
            routing="remote-default",
            local_inference_for_sensitive=False,
        ),
    )
    reset_agent_block_store_for_tests(
        path=tmp_path / "blocks.sqlite",
    )
    # Stub _ensure_bootstrap so the test doesn't need the full agent
    # registry up.
    monkeypatch.setattr(
        "src.agents.cli_handlers._ensure_bootstrap",
        lambda: None,
    )
    yield settings_path


def _capture(call) -> dict:
    buf = io.StringIO()
    with redirect_stdout(buf):
        call()
    out = buf.getvalue().strip().splitlines()[-1]
    return json.loads(out)


def test_toggle_on_when_every_agent_passes(monkeypatch, _isolate) -> None:
    settings_path = _isolate
    # Pin the suite map to a small set so the test is fast.
    monkeypatch.setattr(
        "src.agents.eval_runner.AGENT_SUITE_MAP",
        {"alpha": "alpha", "beta": "beta"},
    )
    monkeypatch.setattr(
        "src.agents.eval_runner.run_agent_eval",
        lambda agent_id, **kw: _fake_run(agent_id, status="passed"),
    )
    from src.agents.cli_handlers import (
        cmd_set_local_inference_for_sensitive,
    )

    payload = _capture(
        lambda: cmd_set_local_inference_for_sensitive("true"),
    )
    assert payload["status"] == "ok"
    assert payload["enabled"] is True
    persisted = json.loads(settings_path.read_text())
    assert persisted["local_inference_for_sensitive"] is True
    assert default_egress_firewall().policy.routing == "local-only"


def test_toggle_off_clears_blocks(monkeypatch, _isolate) -> None:
    from src.agents.cli_handlers import (
        cmd_set_local_inference_for_sensitive,
    )

    block_store = reset_agent_block_store_for_tests()
    block_store.block("alpha", reason="prior eval failure")
    payload = _capture(
        lambda: cmd_set_local_inference_for_sensitive("false"),
    )
    assert payload["status"] == "ok"
    assert payload["enabled"] is False
    assert block_store.get_block("alpha") is None
    assert (
        default_egress_firewall().policy.routing == "remote-default"
    )


def test_toggle_aborts_when_one_agent_fails(monkeypatch, _isolate) -> None:
    settings_path = _isolate

    monkeypatch.setattr(
        "src.agents.eval_runner.AGENT_SUITE_MAP",
        {"alpha": "alpha", "beta": "beta"},
    )

    def fake(agent_id: str, **_kw):
        return _fake_run(
            agent_id,
            status="passed" if agent_id == "alpha" else "failed",
        )

    monkeypatch.setattr(
        "src.agents.eval_runner.run_agent_eval", fake,
    )
    from src.agents.cli_handlers import (
        cmd_set_local_inference_for_sensitive,
    )

    payload = _capture(
        lambda: cmd_set_local_inference_for_sensitive("true"),
    )
    assert payload["status"] == "eval_failed"
    assert payload["enabled"] is False
    assert [f["agent_id"] for f in payload["failures"]] == ["beta"]
    # Flag did NOT commit.
    persisted = json.loads(settings_path.read_text())
    assert persisted.get("local_inference_for_sensitive", False) is False
    assert (
        default_egress_firewall().policy.routing == "remote-default"
    )

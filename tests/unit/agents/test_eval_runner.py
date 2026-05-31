"""EvalRunStore + run_agent_eval behaviour tests.

These exercise the persistence layer (autocommit + row shape) and the
status-decision branches (passed / failed / skipped / error) without
hitting the real eval framework. Where a full eval run is needed,
we drive the firewall_prompts suite which is deterministic and runs
offline.

sensitivity_tier: N/A
"""

from __future__ import annotations

from pathlib import Path

import pytest
from src.agents.eval_runner import (
    AGENT_SUITE_MAP,
    MANUAL_ONLY_AGENTS,
    EvalRunStore,
    run_agent_eval,
)


@pytest.fixture()
def store(tmp_path: Path) -> EvalRunStore:
    db = tmp_path / "evals.sqlite3"
    return EvalRunStore(path=db)


def test_insert_and_finalize_round_trip(store: EvalRunStore) -> None:
    run_id = store.insert_pending(
        agent_id="triage", suite="triage", trigger="manual",
    )
    store.finalize(
        run_id,
        status="passed",
        cases_total=5, cases_passed=5, cases_failed=0,
        failed_cases=[],
    )
    row = store.latest("triage")
    assert row is not None
    assert row.run_id == run_id
    assert row.status == "passed"
    assert row.cases_total == 5
    assert row.cases_passed == 5
    assert row.failed_cases == []


def test_finalize_persists_failed_cases(store: EvalRunStore) -> None:
    run_id = store.insert_pending(
        agent_id="triage", suite="triage", trigger="auto",
    )
    failed = [
        {"case": "promo_dropped", "evaluator": "TriageDecisionAccuracy",
         "reason": "is_promo: got False, expected True"},
    ]
    store.finalize(
        run_id, status="failed",
        cases_total=2, cases_passed=1, cases_failed=1,
        failed_cases=failed,
    )
    row = store.latest("triage")
    assert row is not None
    assert row.status == "failed"
    assert row.failed_cases == failed


def test_history_orders_newest_first(store: EvalRunStore) -> None:
    import time
    for i in range(3):
        rid = store.insert_pending(
            agent_id="labeler", suite="labeler", trigger="manual",
        )
        store.finalize(rid, status="passed", cases_total=i + 1)
        time.sleep(0.01)  # ensure distinct started_at timestamps
    rows = store.history("labeler", limit=10)
    assert len(rows) == 3
    # Newest (highest cases_total) first.
    assert rows[0].cases_total == 3
    assert rows[-1].cases_total == 1


def test_agent_suite_map_covers_every_registered_agent() -> None:
    from src.agents.brain import bootstrap_agents
    from src.agents.core.registry import (
        all_agents,
        reset_registry_for_tests,
    )

    reset_registry_for_tests()
    bootstrap_agents()
    missing = [
        d.agent_id for d in all_agents()
        if d.agent_id not in AGENT_SUITE_MAP
    ]
    assert missing == [], f"agents without an eval suite: {missing}"


def test_manual_only_agents_are_locked() -> None:
    # The manual-only set should match the locked agents in the
    # registry to keep auto-trigger / locked-card behaviour aligned.
    assert "brain" in MANUAL_ONLY_AGENTS
    assert "firewall.injection" in MANUAL_ONLY_AGENTS
    assert "firewall.egress" in MANUAL_ONLY_AGENTS


def test_unknown_agent_records_skipped(tmp_path: Path) -> None:
    store = EvalRunStore(path=tmp_path / "evals.sqlite3")
    run = run_agent_eval(
        "no_such_agent", trigger="manual", store=store,
    )
    assert run.status == "skipped"
    assert "no dataset" in (run.error or "")


def test_firewall_injection_eval_passes(tmp_path: Path) -> None:
    # Deterministic suite — must always pass end-to-end.
    store = EvalRunStore(path=tmp_path / "evals.sqlite3")
    run = run_agent_eval(
        "firewall.injection", trigger="manual", store=store,
    )
    assert run.status == "passed"
    assert run.cases_failed == 0
    assert run.cases_passed > 0
    assert run.suite == "firewall_prompts"


def test_firewall_egress_eval_passes(tmp_path: Path) -> None:
    store = EvalRunStore(path=tmp_path / "evals.sqlite3")
    run = run_agent_eval(
        "firewall.egress", trigger="manual", store=store,
    )
    assert run.status == "passed"
    assert run.suite == "egress_routing"


def test_spawn_auto_eval_no_longer_exported() -> None:
    """Auto-eval was removed in 0.5.0; evals run on explicit user action.

    The Agents page now exposes a "Run eval" button, and ``make
    evals`` / ``python -m evals.run_evals`` runs the full batch from
    the CLI. Nothing else may trigger judge calls.
    """
    import src.agents.eval_runner as er

    assert not hasattr(er, "spawn_auto_eval")

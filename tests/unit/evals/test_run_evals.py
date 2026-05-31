"""Eval runner CLI tests.

The firewall suite runs end-to-end without an LLM (heuristics only),
so it's a perfect smoke test for the full Dataset → task → evaluator
pipeline. Other suites have agent tasks stubbed via monkey-patching.

sensitivity_tier: N/A
"""

from __future__ import annotations

from evals.run_evals import (
    available_suites,
    main,
    resolve_suites,
    run_suite,
)


def test_available_suites_lists_yaml_stems() -> None:
    suites = available_suites()
    assert "firewall_prompts" in suites
    assert "sensitivity" in suites
    assert "triage" in suites


def test_resolve_suites_all_expands() -> None:
    suites = resolve_suites("all")
    assert "firewall_prompts" in suites


def test_resolve_suites_csv() -> None:
    suites = resolve_suites("firewall_prompts,sensitivity")
    assert suites == ["firewall_prompts", "sensitivity"]


def test_resolve_suites_unknown_raises() -> None:
    import pytest as _pytest

    with _pytest.raises(SystemExit):
        resolve_suites("nope")


def test_run_suite_firewall_is_clean() -> None:
    # Firewall heuristics are deterministic; this suite must always
    # achieve 100% locally.
    result = run_suite("firewall_prompts")
    assert result.cases > 0
    assert result.failed == 0
    assert result.pass_rate == 1.0


def test_main_exit_zero_on_firewall(capsys) -> None:
    code = main(["--suite", "firewall_prompts"])
    assert code == 0
    captured = capsys.readouterr()
    assert "firewall_prompts" in captured.out


def test_main_list_flag(capsys) -> None:
    code = main(["--list"])
    assert code == 0
    assert "firewall_prompts" in capsys.readouterr().out


def test_main_json_output(capsys) -> None:
    import json as _json

    code = main(["--suite", "firewall_prompts", "--json"])
    assert code == 0
    payload = _json.loads(capsys.readouterr().out)
    assert "suites" in payload
    assert payload["suites"][0]["suite"] == "firewall_prompts"

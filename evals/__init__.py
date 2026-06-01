"""Pydantic AI eval suites for Arandu agents.

Datasets are YAML files in ``evals/datasets/``; evaluators live in
``evals/evaluators.py``; the runner is ``evals/run_evals.py``.

These are NOT unit tests — they exercise real Pydantic AI agents
through the same scheduler + firewall path as production. CI runs the
suite as a separate workflow; locally use ``make evals-fast`` for the
structural-only pass.

sensitivity_tier: N/A
"""

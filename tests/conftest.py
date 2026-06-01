"""Test suite environment setup.

Disables the egress firewall's LLM-driven tier classifier by default so
unit tests don't make spurious HTTP calls to a (likely-absent) local
Ollama. Tests that specifically want to exercise the classifier path
clear ``ARANDU_FIREWALL_DISABLE_LLM_TIER`` from the environment with
the standard ``monkeypatch.delenv`` fixture.

sensitivity_tier: N/A
"""

from __future__ import annotations

import os


def pytest_configure(config) -> None:  # noqa: ARG001
    """Apply default test-suite env vars.

    sensitivity_tier: N/A
    """
    os.environ.setdefault("ARANDU_FIREWALL_DISABLE_LLM_TIER", "1")
    os.environ.setdefault("ARANDU_FIREWALL_DISABLE_SEMANTIC_SCAN", "1")

"""Wire-format tests for the inline-prompt ``_SUFFIX`` literals.

Phase 2's golden tests cover the on-disk prefix bytes (via SHA-256) and
the rendered ``prefix + <fixture>.input.txt`` bytes (via
:meth:`FrozenPromptTemplate.render_inline`). What they do NOT cover is
the actual ``.format()`` call site in production code — the
``_INTENT_CLASSIFY_SUFFIX`` / ``_PARAM_EXTRACT_SUFFIX`` /
``_ACTION_WHERE_SUFFIX`` literals in :mod:`src.agents.brain_agent`,
``_SUFFIX_TEMPLATE`` in :mod:`src.core.llm_classifier`, and the
``f"{text}\\n"`` / ``f"{block}\\n"`` concatenations in
:mod:`src.models.labeler`.

An edit to one of those Python literals drifts the wire format
silently — the existing render test reads ``.input.txt`` (the
already-substituted suffix) and concatenates it with the on-disk
prefix, so it would pass even after the Python literal diverged.

These tests close the gap: each registered case imports the live
``_SUFFIX`` / inline literal, runs the SAME concat the agent runs
with fixed kwargs, and asserts byte-equality against a checked-in
``<name>.wire.golden.txt``. Edit the Python literal without
re-capturing the fixture and the test fails loudly.

Regenerate the fixtures with::

    python -m tests.unit.models.prompts.test_inline_suffix_wire_format

sensitivity_tier: N/A
"""

from __future__ import annotations

import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import pytest

FIXTURES_DIR = (
    Path(__file__).parent.parent.parent.parent
    / "fixtures" / "prompts"
)


# ---------- production-path renderers ----------
#
# Each renderer imports the live ``_SUFFIX`` / template and runs the
# same concat the production call site runs. Fixed kwargs keep the
# output byte-stable; in particular, no call here invokes
# ``date.today()`` — the date string is passed explicitly so the
# fixture stays reproducible.


def _render_intent_classify() -> str:
    from src.agents.brain.actions import (
        _INTENT_CLASSIFY_SUFFIX,
        _INTENT_CLASSIFY_TEMPLATE,
    )
    return _INTENT_CLASSIFY_TEMPLATE.prefix + _INTENT_CLASSIFY_SUFFIX.format(
        tools="",
        message="How many meetings did I have last week?",
        context_section="",
    )


def _render_param_extractor() -> str:
    from src.agents.brain.actions import (
        _PARAM_EXTRACT_SUFFIX,
        _PARAM_EXTRACT_TEMPLATE,
    )
    return _PARAM_EXTRACT_TEMPLATE.prefix + _PARAM_EXTRACT_SUFFIX.format(
        tool_name="",
        schema="{}",
        question="Create a note",
        context_section="Today: 2026-05-12\n",
        today="2026-05-12",
    )


def _render_action_where() -> str:
    from src.agents.brain.actions import (
        _ACTION_WHERE_SUFFIX,
        _ACTION_WHERE_TEMPLATE,
    )
    return _ACTION_WHERE_TEMPLATE.prefix + _ACTION_WHERE_SUFFIX.format(
        table="",
        columns="id, title, created_at",
        question="delete the last note",
        today="2026-05-12",
    )


def _render_llm_classifier() -> str:
    from src.core.llm_classifier import _SUFFIX_TEMPLATE, _TEMPLATE
    return _TEMPLATE.prefix + _SUFFIX_TEMPLATE.format(
        schema_json=(
            '{"type": "object", "properties": {"x": {"type": "string"}}}'
        ),
        text="Hello world",
    )


# NOTE: labeler_single / labeler_batch wire-format cases removed in
# Phase F1.5 — the legacy ``_SINGLE_TEMPLATE`` / ``_BATCH_TEMPLATE``
# prompts no longer exist; the labeler delegates to
# :class:`LabelerAgent` (pydantic-ai), whose frozen prompt has its own
# golden coverage.


@dataclass(frozen=True)
class WireCase:
    """One production-path wire-format case.

    sensitivity_tier: 1
    """

    name: str
    lane: str
    render: Callable[[], str]


REGISTRY: list[WireCase] = [
    WireCase("intent_classify", "interactive", _render_intent_classify),
    WireCase("param_extractor", "background", _render_param_extractor),
    WireCase("action_where", "background", _render_action_where),
    WireCase("llm_classifier", "classifier", _render_llm_classifier),
]


def _fixture_path(case: WireCase) -> Path:
    return FIXTURES_DIR / case.lane / f"{case.name}.wire.golden.txt"


@pytest.mark.parametrize("case", REGISTRY, ids=lambda c: c.name)
def test_inline_suffix_wire_format_matches_fixture(case: WireCase) -> None:
    """The live ``_SUFFIX`` ``.format()`` output must equal the fixture.

    sensitivity_tier: 1
    """
    actual = case.render()
    fixture = _fixture_path(case)
    if not fixture.exists():
        pytest.fail(
            f"missing {fixture.relative_to(FIXTURES_DIR.parent.parent)}. "
            f"Regenerate fixtures with:\n"
            f"  python -m {__name__}\n"
            f"after reviewing the actual bytes.",
        )
    expected = fixture.read_text(encoding="utf-8")
    assert actual == expected, (
        f"{case.name} wire format drifted from "
        f"{fixture.relative_to(FIXTURES_DIR.parent.parent)}.\n"
        "The Python `_SUFFIX` literal was edited (or the renderer "
        "kwargs changed). If the edit was intentional, re-capture "
        "the fixture with:\n"
        f"  python -m {__name__}\n"
        "AFTER reviewing the diff."
    )


def _regenerate_all() -> None:
    """Overwrite every ``.wire.golden.txt`` with the current render.

    Invoked via ``python -m
    tests.unit.models.prompts.test_inline_suffix_wire_format``.
    Prints the relative path of each fixture written. Intentionally
    NOT exposed as a pytest plugin flag — fixture regeneration is a
    deliberate act that should leave a diff in git.

    sensitivity_tier: 1
    """
    for case in REGISTRY:
        path = _fixture_path(case)
        path.parent.mkdir(parents=True, exist_ok=True)
        bytes_out = case.render()
        path.write_text(bytes_out, encoding="utf-8")
        rel = path.relative_to(FIXTURES_DIR.parent.parent)
        sys.stdout.write(f"wrote {rel} ({len(bytes_out)} bytes)\n")


if __name__ == "__main__":
    _regenerate_all()

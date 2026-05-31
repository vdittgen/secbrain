"""Tests for the action-proposal judge sub-agent integration.

The judge runs *after* the primary extractor and produces an
:class:`ActionProposalVerdict`. ``build_action_proposal`` applies the
judge's patches to the payload before rendering the confirmation card.

These tests stub the judge entirely so the integration is exercised
without an LLM round-trip. The judge agent's own behavior is exercised
by the eval suite (``evals/datasets/action_proposal_judge.yaml``).

sensitivity_tier: 2
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from unittest.mock import patch

from src.agents.brain import actions as actions_mod
from src.agents.brain.actions import _apply_judge_patches
from src.agents.core.output_types import ActionProposalVerdict


@dataclass(frozen=True)
class _StubAction:
    """Minimal action shape ``build_action_proposal`` reads from."""

    tool_name: str
    display_name: str
    connector_id: str = "calendar"
    connector_name: str = "Calendar & Reminders"
    input_schema: dict[str, Any] | None = None


CREATE_EVENT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "start_time": {"type": "string"},
        "end_time": {"type": "string"},
        "location": {"type": "string"},
    },
    "required": ["title", "start_time"],
}


class TestApplyJudgePatches:
    """``_apply_judge_patches`` is the choke point between the judge's
    JSON output and the proposal's arguments dict."""

    def test_patches_known_field(self) -> None:
        extracted = {"title": "Coffee chat with Sarah"}
        patches = {"title": "Play Tennis with Tiago"}
        patched, applied = _apply_judge_patches(
            extracted, CREATE_EVENT_SCHEMA, patches,
        )
        assert patched["title"] == "Play Tennis with Tiago"
        assert applied == ["title"]

    def test_skips_unknown_fields(self) -> None:
        """The judge cannot invent fields the tool doesn't accept."""
        extracted = {"title": "X"}
        patches = {"invented_field": "anything"}
        patched, applied = _apply_judge_patches(
            extracted, CREATE_EVENT_SCHEMA, patches,
        )
        assert "invented_field" not in patched
        assert applied == []

    def test_coerces_literal_none_string_to_null(self) -> None:
        extracted = {"end_time": "None"}
        patches = {"end_time": "null"}
        patched, applied = _apply_judge_patches(
            extracted, CREATE_EVENT_SCHEMA, patches,
        )
        assert patched["end_time"] is None
        assert applied == ["end_time"]

    def test_empty_patches_is_a_noop(self) -> None:
        extracted = {"title": "X", "start_time": "2026-05-23T07:00:00"}
        patched, applied = _apply_judge_patches(
            extracted, CREATE_EVENT_SCHEMA, {},
        )
        assert patched == extracted
        assert applied == []

    def test_multiple_patches(self) -> None:
        extracted = {"title": "Wrong", "start_time": "2026-08-19T07:00:00"}
        patches = {
            "title": "Right",
            "start_time": "2026-05-23T07:00:00",
            "end_time": "2026-05-23T08:00:00",
        }
        patched, applied = _apply_judge_patches(
            extracted, CREATE_EVENT_SCHEMA, patches,
        )
        assert patched["title"] == "Right"
        assert patched["start_time"] == "2026-05-23T07:00:00"
        assert patched["end_time"] == "2026-05-23T08:00:00"
        assert set(applied) == {"title", "start_time", "end_time"}


class TestBuildActionProposalWithJudge:
    """End-to-end through ``build_action_proposal`` with a stubbed
    primary extractor + a stubbed judge. Mirrors the production
    failure modes."""

    def _common_patches(self):
        """Stub the heavy dependencies so we focus on the judge wiring.

        Returns a list of patches the caller can ``ExitStack`` over;
        we re-use the list across tests by nesting ``patch.object``
        calls in each test method.
        """
        return None  # convenience placeholder

    def _run(
        self,
        *,
        primary_output: tuple[dict[str, Any], list[str]],
        judge_verdict: ActionProposalVerdict | None,
        question: str,
        tool_name: str = "create_event",
    ):
        def fake_extract(q, a, s, c, p):  # noqa: ANN001, ARG001
            return primary_output

        def fake_resolve(*args, **kwargs):  # noqa: ANN002, ANN003, ARG001
            return ("python", ["-m", "stub"])

        def fake_data_context(*args, **kwargs):  # noqa: ANN002, ANN003, ARG001
            return ""

        def fake_judge(**kwargs):  # noqa: ARG001
            return judge_verdict

        with (
            patch.object(actions_mod, "extract_action_params", fake_extract),
            patch.object(
                actions_mod, "resolve_connector_command", fake_resolve,
            ),
            patch.object(
                actions_mod, "get_action_data_context", fake_data_context,
            ),
            patch.object(
                actions_mod, "fetch_tool_schema", lambda *a, **k: None,
            ),
            patch.object(
                actions_mod, "is_low_risk_tool", lambda *a, **k: False,
            ),
            patch(
                "src.agents.action_proposal_judge.judge_action_proposal",
                side_effect=fake_judge,
            ),
        ):
            return actions_mod.build_action_proposal(
                _StubAction(
                    tool_name=tool_name,
                    display_name=tool_name.replace("_", " ").title(),
                    input_schema=CREATE_EVENT_SCHEMA,
                ),
                question=question,
                context_text="",
                tool_registry=None,
                mcp_client_factory=None,
                duckdb=None,
                provider=None,  # type: ignore[arg-type]
            )

    def test_judge_patches_hallucinated_title(self) -> None:
        """The exact production failure: primary returns
        'Coffee chat with Sarah' for a tennis request; judge patches
        title back to the user's literal text."""
        proposal = self._run(
            primary_output=(
                {
                    "title": "Coffee chat with Sarah",
                    "start_time": "2026-08-19T07:00:00",
                    "end_time": None,
                },
                [],
            ),
            judge_verdict=ActionProposalVerdict(
                ok=False,
                reasons=[
                    "title doesn't match the user's quoted text",
                    "start_time doesn't match 'tomorrow'",
                ],
                patches={
                    "title": "Play Tennis with Tiago",
                    "start_time": "2026-05-23T07:00:00",
                    "end_time": "2026-05-23T08:00:00",
                },
                cannot_recover=False,
            ),
            question=(
                'create an event on my calendar for tomorrow 7am called '
                '"Play Tennis with Tiago"'
            ),
        )
        assert proposal.arguments["title"] == "Play Tennis with Tiago"
        assert proposal.arguments["start_time"] == "2026-05-23T07:00:00"
        assert proposal.arguments["end_time"] == "2026-05-23T08:00:00"
        # No warning suffix when cannot_recover is False.
        assert "⚠" not in proposal.description

    def test_judge_ok_passes_proposal_through(self) -> None:
        primary = {
            "title": "Play Tennis with Tiago",
            "start_time": "2026-05-23T07:00:00",
            "end_time": "2026-05-23T08:00:00",
        }
        proposal = self._run(
            primary_output=(primary, []),
            judge_verdict=ActionProposalVerdict(ok=True),
            question=(
                'create event tomorrow 7am called "Play Tennis with Tiago"'
            ),
        )
        for k, v in primary.items():
            assert proposal.arguments[k] == v
        assert "⚠" not in proposal.description

    def test_judge_unavailable_proposal_still_ships(self) -> None:
        """Judge returning None (model offline / not registered) MUST
        NOT block the proposal. Safety net != hard gate."""
        primary = {
            "title": "X",
            "start_time": "2026-05-23T07:00:00",
            "end_time": "2026-05-23T08:00:00",
        }
        proposal = self._run(
            primary_output=(primary, []),
            judge_verdict=None,
            question="anything",
        )
        assert proposal.arguments["title"] == "X"

    def test_cannot_recover_surfaces_warning(self) -> None:
        proposal = self._run(
            primary_output=(
                {"title": "Something", "start_time": None}, ["start_time"],
            ),
            judge_verdict=ActionProposalVerdict(
                ok=False,
                reasons=["request is too ambiguous"],
                patches={},
                cannot_recover=True,
            ),
            question="do the thing",
        )
        assert "⚠" in proposal.description
        assert "too ambiguous" in proposal.description

    def test_judge_missing_recomputation(self) -> None:
        """If the judge fills in a previously-missing required param,
        ``missing_params`` shrinks accordingly."""
        proposal = self._run(
            primary_output=(
                {"title": "X", "start_time": None}, ["start_time"],
            ),
            judge_verdict=ActionProposalVerdict(
                ok=False,
                patches={"start_time": "2026-05-23T07:00:00"},
            ),
            question="schedule X tomorrow 7am",
        )
        assert "start_time" not in proposal.missing_params
        assert proposal.arguments["start_time"] == "2026-05-23T07:00:00"


class TestJudgeAgentRegistration:
    """Smoke-test the agent definition shape."""

    def test_register_is_idempotent(self) -> None:
        from src.agents.action_proposal_judge import (
            register_action_proposal_judge,
        )
        from src.agents.core.registry import get_agent

        register_action_proposal_judge()
        register_action_proposal_judge()  # second call is a no-op
        defn = get_agent("action_proposal_judge")
        assert defn is not None
        assert defn.editable is False
        assert defn.output_schema == "ActionProposalVerdict"
        assert "judge" in defn.tags
        assert "locked" in defn.tags

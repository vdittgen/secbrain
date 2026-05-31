"""Structural tests for action-proposal parameter overrides.

The "Play Tennis with Tiago → Coffee chat with Sarah" failure was a
structural one: the LLM's parameter extraction is fundamentally
unreliable for values the user typed literally. The fix layers a
deterministic extractor (:func:`extract_user_given_values`) on top
of the LLM extractor and force-overrides any field where the user
gave a literal value.

These tests stub the LLM extractor entirely so a hostile
implementation (returning hallucinated titles, ``None`` for required
times) still lands a proposal carrying the user's real values.

sensitivity_tier: 2
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from unittest.mock import patch

from src.agents.brain import actions as actions_mod
from src.agents.brain.actions import _apply_user_value_overrides, _is_create_tool
from src.agents.brain.user_value_extractor import UserGivenValues


@dataclass(frozen=True)
class _StubAction:
    """Minimal shape ``build_action_proposal`` reads from an action."""

    tool_name: str
    display_name: str
    connector_id: str = "calendar"
    connector_name: str = "Calendar & Reminders"
    input_schema: dict[str, Any] | None = None


CREATE_EVENT_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "start_time": {"type": "string"},
        "end_time": {"type": "string"},
        "location": {"type": "string"},
    },
    "required": ["title", "start_time"],
}


class TestIsCreateTool:
    """``_is_create_tool`` decides whether to skip DB-context
    augmentation. Getting this wrong on either side is bad — false
    positives starve update tools of context, false negatives let
    hallucinations through on create tools."""

    def test_create_event(self) -> None:
        assert _is_create_tool("create_event") is True

    def test_create_note(self) -> None:
        assert _is_create_tool("create_note") is True

    def test_schedule_meeting(self) -> None:
        assert _is_create_tool("schedule_meeting") is True

    def test_compose_email(self) -> None:
        assert _is_create_tool("compose_email") is True

    def test_update_event_is_not_create(self) -> None:
        assert _is_create_tool("update_event") is False

    def test_delete_event_is_not_create(self) -> None:
        assert _is_create_tool("delete_event") is False

    def test_search_emails_is_not_create(self) -> None:
        assert _is_create_tool("search_emails") is False

    def test_empty_is_not_create(self) -> None:
        assert _is_create_tool("") is False


class TestApplyUserValueOverrides:
    """The single function responsible for "user literals always win"."""

    def test_overrides_title_from_quoted_string(self) -> None:
        extracted = {"title": "Coffee chat with Sarah", "start_time": None}
        user = UserGivenValues(title="Play Tennis with Tiago")
        patched, changed = _apply_user_value_overrides(
            extracted, CREATE_EVENT_SCHEMA, user,
        )
        assert patched["title"] == "Play Tennis with Tiago"
        assert changed is True

    def test_overrides_start_and_end_times(self) -> None:
        extracted = {"title": "X", "start_time": "2026-08-19T07:00:00"}
        user = UserGivenValues(
            title="X",
            start_time="2026-05-23T07:00:00",
            end_time="2026-05-23T08:00:00",
        )
        patched, changed = _apply_user_value_overrides(
            extracted, CREATE_EVENT_SCHEMA, user,
        )
        assert patched["start_time"] == "2026-05-23T07:00:00"
        assert patched["end_time"] == "2026-05-23T08:00:00"
        assert changed is True

    def test_no_op_when_user_supplied_nothing(self) -> None:
        extracted = {"title": "Auto-filled", "start_time": "2026-05-23T07:00:00"}
        user = UserGivenValues()
        patched, changed = _apply_user_value_overrides(
            extracted, CREATE_EVENT_SCHEMA, user,
        )
        assert patched == extracted
        assert changed is False

    def test_skips_fields_not_in_schema(self) -> None:
        """Never invents fields the tool doesn't accept."""
        schema = {"properties": {"title": {"type": "string"}}}
        extracted = {"title": "X"}
        user = UserGivenValues(
            title="Y",
            start_time="2026-05-23T07:00:00",
            end_time="2026-05-23T08:00:00",
        )
        patched, _changed = _apply_user_value_overrides(
            extracted, schema, user,
        )
        assert patched == {"title": "Y"}
        assert "start_time" not in patched
        assert "end_time" not in patched

    def test_writes_start_date_when_schema_uses_that_name(self) -> None:
        """Some connectors use ``start_date`` / ``ends_at`` instead of
        ``start_time`` / ``end_time``. The override maps to whichever
        the schema declares."""
        schema = {
            "properties": {
                "title": {"type": "string"},
                "start_date": {"type": "string"},
                "ends_at": {"type": "string"},
            },
        }
        extracted: dict[str, Any] = {}
        user = UserGivenValues(
            title="X",
            start_time="2026-05-23T07:00:00",
            end_time="2026-05-23T08:00:00",
        )
        patched, _changed = _apply_user_value_overrides(
            extracted, schema, user,
        )
        assert patched["start_date"] == "2026-05-23T07:00:00"
        assert patched["ends_at"] == "2026-05-23T08:00:00"


class TestBuildActionProposalOverride:
    """End-to-end through ``build_action_proposal`` with a hostile LLM
    stub. Mirrors the in-app failure: user says one thing, LLM emits
    another, the proposal must still carry the user's value."""

    def _stub_action(self) -> _StubAction:
        return _StubAction(
            tool_name="create_event",
            display_name="Create Event",
            input_schema=CREATE_EVENT_SCHEMA,
        )

    def test_user_literal_title_wins_over_hallucinated_llm_value(self) -> None:
        # Hostile LLM extractor returns the wrong title and start_time
        # (the exact production failure mode the user reported).
        def fake_extract(question, action, schema, ctx, provider):  # noqa: ANN001, ARG001
            return (
                {
                    "title": "Coffee chat with Sarah",
                    "start_time": "2026-08-19T07:00:00",
                    "end_time": None,
                },
                [],
            )

        # ``resolve_connector_command`` calls the registry; stub it.
        def fake_resolve(tool_registry, connector_id):  # noqa: ANN001, ARG001
            return ("python", ["-m", "stub"])

        # No data-context injection should fire for create tools, but
        # stub the function anyway to make the assertion obvious.
        def fake_data_context(*args, **kwargs):  # noqa: ANN002, ANN003, ARG001
            raise AssertionError(
                "data context must be skipped for create_* tools",
            )

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
        ):
            proposal = actions_mod.build_action_proposal(
                self._stub_action(),
                question=(
                    'create an event on my calendar for tomorrow 7 am '
                    'called "Play Tennis with Tiago"'
                ),
                context_text="",
                tool_registry=None,
                mcp_client_factory=None,
                duckdb=None,
                provider=None,  # type: ignore[arg-type]
            )

        # The literal title the user typed must survive even though
        # the LLM tried to substitute it.
        assert proposal.arguments["title"] == "Play Tennis with Tiago"
        # ``end_time`` was None from the LLM — the deterministic
        # extractor provided start + 1h, so the bridge will see a
        # real value rather than None / "None".
        assert proposal.arguments["end_time"] is not None
        assert proposal.arguments["start_time"] is not None
        # Required-params recomputation: with both times set, nothing
        # is missing.
        assert "start_time" not in proposal.missing_params

    def test_update_event_still_gets_data_context(self) -> None:
        """Mirror test — update_event MUST still receive DB context
        so the LLM can resolve "delete tomorrow's meeting" properly."""
        called = {"yes": False}

        def fake_data_context(*args, **kwargs):  # noqa: ANN002, ANN003, ARG001
            called["yes"] = True
            return ""

        def fake_extract(question, action, schema, ctx, provider):  # noqa: ANN001, ARG001
            return ({"title": "X", "start_time": "2026-05-23T07:00:00"}, [])

        def fake_resolve(tool_registry, connector_id):  # noqa: ANN001, ARG001
            return ("python", ["-m", "stub"])

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
        ):
            actions_mod.build_action_proposal(
                _StubAction(
                    tool_name="update_event",
                    display_name="Update Event",
                    input_schema=CREATE_EVENT_SCHEMA,
                ),
                question="reschedule tomorrow's tennis to 9am",
                context_text="",
                tool_registry=None,
                mcp_client_factory=None,
                duckdb=None,
                provider=None,  # type: ignore[arg-type]
            )

        assert called["yes"] is True

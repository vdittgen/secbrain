"""Tests for the defense-in-depth rehydration pass in build_action_proposal.

``chat_via_firewalls`` rehydrates LLM output through a *per-call*
``RedactionMap`` that only knows about placeholders newly minted on
that call. If a placeholder reached the extractor via the persistent
registry (because the entity was registered earlier in the session)
the per-call map can't reverse it — the placeholder would otherwise
land on the confirmation card and on the wire to the connector.

``build_action_proposal`` now runs every stringy argument through the
persistent registry as a safety net. These tests prove that the
proposal the user sees never contains a raw ``__PERSON_N__`` /
``__EMAIL_N__`` token whenever the registry has the mapping.

sensitivity_tier: 2
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from unittest.mock import patch

from src.agents.brain import actions as actions_mod


@dataclass(frozen=True)
class _StubAction:
    tool_name: str
    display_name: str
    connector_id: str = "whatsapp"
    connector_name: str = "WhatsApp"
    input_schema: dict[str, Any] | None = None


SEND_WHATSAPP_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "to": {"type": "string"},
        "body": {"type": "string"},
    },
    "required": ["to", "body"],
}


class _FakeRegistry:
    """Minimal stand-in for ``RedactionRegistry`` — only ``rehydrate``
    is called by ``build_action_proposal``."""

    def __init__(self, mapping: dict[str, str]) -> None:
        self._mapping = mapping

    def rehydrate(self, text: str) -> str:
        out = text
        for placeholder, raw in self._mapping.items():
            out = out.replace(placeholder, raw)
        return out


def _run(
    *,
    primary_output: tuple[dict[str, Any], list[str]],
    registry_mapping: dict[str, str],
    tool_name: str = "send_whatsapp_message",
):
    """Drive ``build_action_proposal`` with stubbed dependencies and a
    fake registry that knows specific placeholders."""

    def fake_extract(*args, **kwargs):  # noqa: ANN002, ANN003, ARG001
        return primary_output

    def fake_resolve(*args, **kwargs):  # noqa: ANN002, ANN003, ARG001
        return ("python", ["-m", "stub"])

    def fake_data_context(*args, **kwargs):  # noqa: ANN002, ANN003, ARG001
        return ""

    with (
        patch.object(actions_mod, "extract_action_params", fake_extract),
        patch.object(
            actions_mod, "resolve_connector_command", fake_resolve,
        ),
        patch.object(
            actions_mod, "get_action_data_context", fake_data_context,
        ),
        patch.object(actions_mod, "fetch_tool_schema", lambda *a, **k: None),
        patch.object(actions_mod, "is_low_risk_tool", lambda *a, **k: False),
        # Judge off so this suite isolates the rehydration pass.
        patch(
            "src.agents.action_proposal_judge.judge_action_proposal",
            return_value=None,
        ),
        patch(
            "src.models.redaction_registry.default_redaction_registry",
            return_value=_FakeRegistry(registry_mapping),
        ),
    ):
        return actions_mod.build_action_proposal(
            _StubAction(
                tool_name=tool_name,
                display_name=tool_name.replace("_", " ").title(),
                input_schema=SEND_WHATSAPP_SCHEMA,
            ),
            question="reply saying I'm going to water them now",
            context_text="",
            tool_registry=None,
            mcp_client_factory=None,
            duckdb=None,
            provider=None,  # type: ignore[arg-type]
            skip_recipient_resolution=True,
        )


class TestRehydrationPass:
    def test_recipient_placeholder_is_restored(self) -> None:
        """The exact production failure: ``to=__PERSON_2726__`` lands on
        the confirmation card. After rehydration the user sees the
        real name."""
        proposal = _run(
            primary_output=(
                {"to": "__PERSON_2726__", "body": "oi tudo bem?"},
                [],
            ),
            registry_mapping={"__PERSON_2726__": "Elmara"},
        )
        assert proposal.arguments["to"] == "Elmara"

    def test_body_placeholder_inline_restored(self) -> None:
        proposal = _run(
            primary_output=(
                {
                    "to": "__PERSON_2726__",
                    "body": "Olá __PERSON_2726__! Tudo bem?",
                },
                [],
            ),
            registry_mapping={"__PERSON_2726__": "Elmara"},
        )
        assert "__PERSON_2726__" not in proposal.arguments["body"]
        assert "Elmara" in proposal.arguments["body"]

    def test_unknown_placeholder_passes_through(self) -> None:
        """A placeholder the registry doesn't know about stays as-is —
        the judge / user can decide what to do; we never raise."""
        proposal = _run(
            primary_output=(
                {"to": "__PERSON_9999__", "body": "hi"},
                [],
            ),
            registry_mapping={"__PERSON_1__": "Other Person"},
        )
        assert proposal.arguments["to"] == "__PERSON_9999__"

    def test_no_placeholder_in_input_is_noop(self) -> None:
        proposal = _run(
            primary_output=(
                {"to": "Elmara", "body": "oi tudo bem?"},
                [],
            ),
            registry_mapping={"__PERSON_2726__": "Elmara"},
        )
        assert proposal.arguments == {"to": "Elmara", "body": "oi tudo bem?"}

    def test_non_string_fields_untouched(self) -> None:
        """Numbers, lists, dicts pass through the rehydration loop
        without being stringified."""
        schema = {
            "type": "object",
            "properties": {
                "to": {"type": "string"},
                "body": {"type": "string"},
                "max_retries": {"type": "integer"},
                "tags": {"type": "array"},
            },
            "required": ["to", "body"],
        }

        def fake_extract(*args, **kwargs):  # noqa: ANN002, ANN003, ARG001
            return (
                {
                    "to": "__PERSON_1__",
                    "body": "hi __PERSON_1__",
                    "max_retries": 3,
                    "tags": ["urgent"],
                },
                [],
            )

        def fake_resolve(*args, **kwargs):  # noqa: ANN002, ANN003, ARG001
            return ("python", ["-m", "stub"])

        with (
            patch.object(actions_mod, "extract_action_params", fake_extract),
            patch.object(
                actions_mod, "resolve_connector_command", fake_resolve,
            ),
            patch.object(
                actions_mod, "get_action_data_context", lambda *a, **k: "",
            ),
            patch.object(
                actions_mod, "fetch_tool_schema", lambda *a, **k: None,
            ),
            patch.object(
                actions_mod, "is_low_risk_tool", lambda *a, **k: False,
            ),
            patch(
                "src.agents.action_proposal_judge.judge_action_proposal",
                return_value=None,
            ),
            patch(
                "src.models.redaction_registry.default_redaction_registry",
                return_value=_FakeRegistry({"__PERSON_1__": "Sarah"}),
            ),
        ):
            proposal = actions_mod.build_action_proposal(
                _StubAction(
                    tool_name="send_whatsapp_message",
                    display_name="Send",
                    input_schema=schema,
                ),
                question="reply",
                context_text="",
                tool_registry=None,
                mcp_client_factory=None,
                duckdb=None,
                provider=None,  # type: ignore[arg-type]
                skip_recipient_resolution=True,
            )

        assert proposal.arguments["to"] == "Sarah"
        assert proposal.arguments["body"] == "hi Sarah"
        assert proposal.arguments["max_retries"] == 3
        assert proposal.arguments["tags"] == ["urgent"]

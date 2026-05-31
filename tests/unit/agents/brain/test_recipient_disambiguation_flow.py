"""Integration tests for the recipient-disambiguation flow.

Exercises ``build_action_proposal`` end-to-end for messaging tools:
the resolver fires after rehydration, candidates rank by mart
``notification_priority``, and the resumption path
(``resume_action_from_disambiguation``) produces a normal
``ActionProposal`` carrying the chosen handle.

sensitivity_tier: 2
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any
from unittest.mock import patch

from src.agents.brain import actions as actions_mod
from src.agents.brain.actions import (
    ActionProposal,
    RecipientDisambiguationProposal,
    resume_action_from_disambiguation,
)


@dataclass(frozen=True)
class _StubAction:
    tool_name: str = "send_whatsapp_message"
    display_name: str = "Send Whatsapp Message"
    connector_id: str = "whatsapp"
    connector_name: str = "WhatsApp"
    input_schema: dict[str, Any] | None = None


_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "to": {"type": "string"},
        "body": {"type": "string"},
    },
    "required": ["to", "body"],
}


class _FakeRegistry:
    def __init__(self, mapping: dict[str, str]) -> None:
        self._mapping = mapping

    def rehydrate(self, text: str) -> str:
        out = text
        for placeholder, raw in self._mapping.items():
            out = out.replace(placeholder, raw)
        return out


class _FakeDB:
    """Routes queries by FROM-table to a canned response list."""

    def __init__(
        self,
        mart: list[dict[str, Any]] | None = None,
        raw_contacts: list[dict[str, Any]] | None = None,
    ) -> None:
        self._mart = mart or []
        self._raw = raw_contacts or []

    def query(self, sql: str, _params: list[Any]) -> list[dict[str, Any]]:
        if "mart_contact_summary" in sql:
            return list(self._mart)
        if "raw_contacts" in sql:
            return list(self._raw)
        return []


def _build(*, extracted: dict[str, Any], db: Any):
    def fake_extract(*_a, **_k):
        return (extracted, [])

    def fake_resolve(*_a, **_k):
        return ("python", ["-m", "stub"])

    with (
        patch.object(actions_mod, "extract_action_params", fake_extract),
        patch.object(actions_mod, "resolve_connector_command", fake_resolve),
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
            return_value=_FakeRegistry({"__PERSON_2726__": "Elmara"}),
        ),
    ):
        return actions_mod.build_action_proposal(
            _StubAction(input_schema=_SCHEMA),
            question="send a whatsapp to Elmara",
            context_text="",
            tool_registry=None,
            mcp_client_factory=None,
            duckdb=db,
            provider=None,  # type: ignore[arg-type]
        )


class TestMessagingTriggersDisambiguation:
    def test_returns_disambiguation_when_recipient_is_a_name(self) -> None:
        db = _FakeDB(mart=[
            {
                "contact_name": "Elmara Silva",
                "handle": "+5511000001",
                "relationship": "wife",
                "top_topic": "trip",
                "topic_importance": 9,
                "priority": 80,
                "match_rank": 1,
            },
            {
                "contact_name": "Elmara Costa",
                "handle": "+5511000002",
                "relationship": "colleague",
                "top_topic": "",
                "topic_importance": 0,
                "priority": 20,
                "match_rank": 1,
            },
        ])
        result = _build(
            extracted={"to": "Elmara", "body": "Bom dia"},
            db=db,
        )
        assert isinstance(result, RecipientDisambiguationProposal)
        assert result.original_name == "Elmara"
        names = [c["name"] for c in result.candidates]
        assert names == ["Elmara Silva", "Elmara Costa"]
        # The draft body is preserved so the resumption can reuse it.
        assert result.draft_arguments["body"] == "Bom dia"

    def test_rehydrated_placeholder_feeds_resolver_as_original_name(self) -> None:
        # Even though the LLM emitted a bare placeholder, the
        # rehydration pass restores "Elmara" before the resolver runs.
        db = _FakeDB(mart=[{
            "contact_name": "Elmara",
            "handle": "+5511000001",
            "relationship": "",
            "top_topic": "",
            "topic_importance": 0,
            "priority": 0,
            "match_rank": 1,
        }])
        result = _build(
            extracted={"to": "__PERSON_2726__", "body": "oi"},
            db=db,
        )
        assert isinstance(result, RecipientDisambiguationProposal)
        assert result.original_name == "Elmara"

    def test_phone_handle_skips_disambiguation(self) -> None:
        # If the LLM already produced a phone number, there's
        # nothing to disambiguate — fall through to ActionProposal.
        db = _FakeDB()
        result = _build(
            extracted={"to": "+5511999991234", "body": "oi"},
            db=db,
        )
        assert isinstance(result, ActionProposal)
        assert result.arguments["to"] == "+5511999991234"


class TestResumeFromDisambiguation:
    def test_chosen_candidate_becomes_action_proposal(self) -> None:
        disambiguation = {
            "proposal_id": "p1",
            "connector_id": "whatsapp",
            "connector_name": "WhatsApp",
            "tool_name": "send_whatsapp_message",
            "display_name": "Send Whatsapp Message",
            "channel": "whatsapp",
            "original_name": "Elmara",
            "candidates": [],
            "draft_arguments": {"to": "Elmara", "body": "Bom dia"},
            "command": "python",
            "args": ["-m", "stub"],
            "question": "send a whatsapp to Elmara",
            "context_text": "",
        }
        candidate = {
            "name": "Elmara Silva",
            "handle": "+5511999991234",
            "relationship": "wife",
            "active_topic": "trip",
            "topic_importance": 9,
            "notification_priority": 80,
            "source": "mart",
        }
        proposal = resume_action_from_disambiguation(
            disambiguation=disambiguation,
            candidate=candidate,
            duckdb=None,
        )
        assert isinstance(proposal, ActionProposal)
        assert proposal.arguments["to"] == "+5511999991234"
        # Original body is preserved.
        assert proposal.arguments["body"] == "Bom dia"
        # Chosen display name is remembered for any downstream UI.
        assert (
            proposal.arguments["recipient_display_name"]
            == "Elmara Silva"
        )
        # Round-trips through dataclasses.asdict cleanly.
        as_dict = asdict(proposal)
        assert as_dict["connector_id"] == "whatsapp"

    def test_missing_handle_raises(self) -> None:
        disambiguation = {
            "channel": "whatsapp",
            "connector_id": "whatsapp",
            "connector_name": "WhatsApp",
            "tool_name": "send_whatsapp_message",
            "display_name": "Send",
            "draft_arguments": {"body": "x"},
            "command": "",
            "args": [],
        }
        candidate = {"name": "Elmara", "handle": None}
        try:
            resume_action_from_disambiguation(
                disambiguation=disambiguation,
                candidate=candidate,
                duckdb=None,
            )
        except ValueError:
            return
        msg = "Expected ValueError for missing handle"
        raise AssertionError(msg)

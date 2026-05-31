"""Tests for ``resolve_recipient`` — the disambiguation lookup.

Covers mart ranking, staging fallback, Apple Contacts MCP fallback,
channel/handle filtering, and dedup across sources.

sensitivity_tier: 2
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any

from src.agents.brain.recipient_resolver import (
    ContactCandidate,
    handle_field_for_channel,
    resolve_recipient,
)


class _FakeDB:
    """Routes SQL to canned responses by matching the FROM table.

    Tests inject a ``responses`` map keyed by table name so the same
    DB stand-in can serve both ``mart_contact_summary`` and
    ``raw_contacts`` queries within one ``resolve_recipient`` call.
    """

    def __init__(self, responses: dict[str, list[dict[str, Any]]]):
        self._responses = responses
        self.calls: list[tuple[str, list[Any]]] = []

    def query(self, sql: str, params: list[Any]) -> list[dict[str, Any]]:
        self.calls.append((sql, params))
        if "mart_contact_summary" in sql:
            return list(self._responses.get("mart", []))
        if "raw_contacts" in sql:
            return list(self._responses.get("raw_contacts", []))
        return []


class _FakeMCPClient:
    def __init__(self, results: list[dict[str, Any]]):
        self._results = results
        self.called_with: dict[str, Any] | None = None

    def call_tool(
        self, name: str, args: dict[str, Any],
    ) -> list[dict[str, Any]]:
        self.called_with = {"tool": name, "args": args}
        return list(self._results)


def _mcp_factory(client: _FakeMCPClient):
    @contextmanager
    def factory(_command: str, _args: tuple[str, ...], _timeout: float):
        yield client
    return factory


class _StubTemplate:
    def __init__(self) -> None:
        self.command = "python3"
        self.args = ["-m", "src.extensions.bridges.apple.server"]


class _StubRegistry:
    def __init__(self) -> None:
        self._catalog = {"apple-contacts": _StubTemplate()}


class TestHandleFieldForChannel:
    def test_whatsapp_uses_phone(self) -> None:
        assert handle_field_for_channel("whatsapp") == "phone"

    def test_email_uses_email(self) -> None:
        assert handle_field_for_channel("email") == "email"

    def test_imessage_uses_phone(self) -> None:
        assert handle_field_for_channel("imessage") == "phone"


class TestEmptyInput:
    def test_blank_name_returns_empty(self) -> None:
        result = resolve_recipient("", "whatsapp", _FakeDB({}))
        assert result.candidates == ()
        assert result.original_name == ""

    def test_whitespace_only_name_returns_empty(self) -> None:
        result = resolve_recipient("   ", "whatsapp", _FakeDB({}))
        assert result.candidates == ()


class TestMartRanking:
    def test_single_match_returns_one_candidate(self) -> None:
        db = _FakeDB({
            "mart": [{
                "contact_name": "Elmara Silva",
                "handle": "+5511999991234",
                "relationship": "wife",
                "top_topic": "weekend trip",
                "topic_importance": 9,
                "priority": 88,
                "match_rank": 1,
            }],
        })
        result = resolve_recipient("Elmara", "whatsapp", db)
        assert len(result.candidates) == 1
        c = result.candidates[0]
        assert c.name == "Elmara Silva"
        assert c.handle == "+5511999991234"
        assert c.relationship == "wife"
        assert c.active_topic == "weekend trip"
        assert c.notification_priority == 88
        assert c.source == "mart"

    def test_multiple_candidates_preserve_db_order(self) -> None:
        # The SQL already orders by match_rank → priority → topic;
        # the resolver must surface them in that order.
        db = _FakeDB({
            "mart": [
                {
                    "contact_name": "Elmara Silva",
                    "handle": "+5511000001",
                    "relationship": "wife",
                    "top_topic": "weekend trip",
                    "topic_importance": 9,
                    "priority": 90,
                    "match_rank": 1,
                },
                {
                    "contact_name": "Elmara Costa",
                    "handle": "+5511000002",
                    "relationship": "colleague",
                    "top_topic": "",
                    "topic_importance": 0,
                    "priority": 30,
                    "match_rank": 1,
                },
            ],
        })
        result = resolve_recipient("Elmara", "whatsapp", db, limit=5)
        names = [c.name for c in result.candidates]
        assert names == ["Elmara Silva", "Elmara Costa"]


class TestStagingFallback:
    def test_pulls_from_raw_contacts_when_mart_empty(self) -> None:
        db = _FakeDB({
            "mart": [],
            "raw_contacts": [{
                "name": "New Contact",
                "handle": "+5511000003",
                "relationship": "",
                "match_rank": 1,
            }],
        })
        result = resolve_recipient("New", "whatsapp", db)
        assert len(result.candidates) == 1
        assert result.candidates[0].source == "stg_contacts"
        assert result.candidates[0].handle == "+5511000003"


class TestAppleMCPFallback:
    def test_mcp_always_appends_on_miss_path(self) -> None:
        db = _FakeDB({"mart": [], "raw_contacts": []})
        client = _FakeMCPClient([
            {
                "name": "Address Book Elmara",
                "phone": "+5511000099",
                "email": None,
                "relationship": "",
            },
        ])
        result = resolve_recipient(
            "Elmara", "whatsapp", db,
            tool_registry=_StubRegistry(),
            mcp_client_factory=_mcp_factory(client),
        )
        assert len(result.candidates) == 1
        assert result.candidates[0].source == "apple_mcp"
        assert result.candidates[0].handle == "+5511000099"
        assert client.called_with == {
            "tool": "search_contacts",
            "args": {"query": "Elmara", "limit": 5},
        }

    def test_mcp_results_without_channel_handle_are_dropped(self) -> None:
        # WhatsApp requires phone; an MCP entry with only email is
        # useless for this channel.
        db = _FakeDB({"mart": [], "raw_contacts": []})
        client = _FakeMCPClient([
            {"name": "Elmara", "phone": None, "email": "elmara@x.com"},
        ])
        result = resolve_recipient(
            "Elmara", "whatsapp", db,
            tool_registry=_StubRegistry(),
            mcp_client_factory=_mcp_factory(client),
        )
        assert result.candidates == ()

    def test_dedup_across_sources_on_handle(self) -> None:
        # Same phone present in mart and MCP — only one entry survives,
        # and the mart row wins (it's added first).
        db = _FakeDB({
            "mart": [{
                "contact_name": "Elmara",
                "handle": "+5511000001",
                "relationship": "wife",
                "top_topic": "trip",
                "topic_importance": 5,
                "priority": 50,
                "match_rank": 1,
            }],
        })
        client = _FakeMCPClient([
            {"name": "Elmara", "phone": "+5511000001"},
        ])
        result = resolve_recipient(
            "Elmara", "whatsapp", db,
            tool_registry=_StubRegistry(),
            mcp_client_factory=_mcp_factory(client),
        )
        assert len(result.candidates) == 1
        assert result.candidates[0].source == "mart"


class TestErrorTolerance:
    def test_db_failure_returns_empty_candidates(self) -> None:
        class _Boom:
            def query(self, *_a, **_k):
                raise RuntimeError("db down")
        result = resolve_recipient("Elmara", "whatsapp", _Boom())
        assert result.candidates == ()
        assert result.original_name == "Elmara"

    def test_mcp_failure_does_not_drop_db_candidates(self) -> None:
        db = _FakeDB({
            "mart": [{
                "contact_name": "Elmara",
                "handle": "+5511000001",
                "relationship": "",
                "top_topic": "",
                "topic_importance": 0,
                "priority": 0,
                "match_rank": 1,
            }],
        })

        class _BoomClient:
            def call_tool(self, *_a, **_k):
                raise RuntimeError("mcp down")

        result = resolve_recipient(
            "Elmara", "whatsapp", db,
            tool_registry=_StubRegistry(),
            mcp_client_factory=_mcp_factory(_BoomClient()),
        )
        assert len(result.candidates) == 1
        assert result.candidates[0].source == "mart"


class TestContactCandidateShape:
    def test_dataclass_is_frozen(self) -> None:
        c = ContactCandidate(
            name="x", handle="y", relationship="",
            active_topic="", topic_importance=0,
            notification_priority=0, source="mart",
        )
        try:
            c.name = "z"  # type: ignore[misc]
        except Exception:  # noqa: BLE001
            return
        msg = "ContactCandidate should be frozen"
        raise AssertionError(msg)

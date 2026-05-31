"""Tests for channel + language inference helpers.

These two helpers exist because the action matcher kept proposing
``reply_email`` for replies to WhatsApp messages — the matcher saw
``reply`` and grabbed the first reply-shaped tool. Channel inference
is the structural fix; this suite locks it down.

sensitivity_tier: 1
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from src.agents.brain.channel_inference import (
    ChannelHint,
    filter_tools_by_channel,
    infer_action_channel,
    infer_inbound_language_hint,
)


@dataclass
class _Tool:
    """Minimal shape ``filter_tools_by_channel`` reads from."""

    connector_id: str
    tool_name: str


class TestInferActionChannelFromText:
    """Explicit channel mentions in the user's message always win."""

    def test_whatsapp_explicit(self) -> None:
        hint = infer_action_channel("reply on WhatsApp saying yes")
        assert hint.channel == "whatsapp"
        assert hint.confidence == "explicit"

    def test_email_explicit(self) -> None:
        hint = infer_action_channel("send her an email about the meeting")
        assert hint.channel == "email"
        assert hint.confidence == "explicit"

    def test_imessage_explicit(self) -> None:
        hint = infer_action_channel("send her an iMessage saying hi")
        assert hint.channel == "imessage"
        assert hint.confidence == "explicit"

    def test_portuguese_zap(self) -> None:
        hint = infer_action_channel("responde pelo zap dizendo que estou indo")
        assert hint.channel == "whatsapp"
        assert hint.confidence == "explicit"

    def test_no_keyword_returns_empty(self) -> None:
        hint = infer_action_channel("reply to her saying yes")
        assert hint.channel == ""
        assert hint.confidence == ""


class TestInferActionChannelFromSources:
    """When the user doesn't name a channel, fall back to the most
    recent inbound message's source."""

    def test_whatsapp_source(self) -> None:
        sources = [
            {"source": "whatsapp", "content": "oi tudo bem?"},
        ]
        hint = infer_action_channel("reply saying yes", sources=sources)
        assert hint.channel == "whatsapp"
        assert hint.confidence == "inferred"

    def test_apple_mail_source(self) -> None:
        sources = [{"source": "apple_mail", "subject": "watering plants"}]
        hint = infer_action_channel("reply saying yes", sources=sources)
        assert hint.channel == "email"
        assert hint.confidence == "inferred"

    def test_explicit_wins_over_sources(self) -> None:
        sources = [{"source": "apple_mail"}]
        hint = infer_action_channel(
            "reply on WhatsApp saying yes", sources=sources,
        )
        assert hint.channel == "whatsapp"
        assert hint.confidence == "explicit"

    def test_unknown_source_falls_through(self) -> None:
        sources = [{"source": "telegram"}]
        hint = infer_action_channel("reply saying yes", sources=sources)
        assert hint.channel == ""

    def test_context_text_fallback(self) -> None:
        hint = infer_action_channel(
            "reply saying yes",
            context_text="From John via WhatsApp: oi",
        )
        assert hint.channel == "whatsapp"
        assert hint.confidence == "inferred"


class TestFilterToolsByChannel:
    """The matcher uses this to bias / filter ranked tool candidates."""

    def _tools(self) -> list[_Tool]:
        return [
            _Tool("apple-mail", "reply_email"),
            _Tool("whatsapp", "send_message"),
            _Tool("apple-messages", "send_message"),
        ]

    def test_no_hint_is_passthrough(self) -> None:
        tools = self._tools()
        assert filter_tools_by_channel(tools, ChannelHint()) == tools

    def test_explicit_filters_to_matching_only(self) -> None:
        tools = self._tools()
        out = filter_tools_by_channel(
            tools, ChannelHint("whatsapp", "explicit"),
        )
        assert len(out) == 1
        assert out[0].connector_id == "whatsapp"

    def test_explicit_no_match_returns_empty(self) -> None:
        tools = [_Tool("apple-mail", "reply_email")]
        out = filter_tools_by_channel(
            tools, ChannelHint("whatsapp", "explicit"),
        )
        assert out == []

    def test_inferred_promotes_but_preserves_all(self) -> None:
        tools = self._tools()
        out = filter_tools_by_channel(
            tools, ChannelHint("whatsapp", "inferred"),
        )
        # WhatsApp tool moves to the front; the others survive.
        assert out[0].connector_id == "whatsapp"
        assert len(out) == 3


class TestInferInboundLanguageHint:
    """The hint is the inbound message text — the LLM detects the
    language from it. This helper only has to expose the snippet."""

    def test_returns_inbound_content(self) -> None:
        sources = [
            {"source": "whatsapp", "content": "Oi! Vai regar as plantas?"},
        ]
        snippet = infer_inbound_language_hint(sources)
        assert "regar" in snippet

    def test_skips_outbound_messages(self) -> None:
        sources = [
            {
                "source": "whatsapp",
                "is_from_me": "True",
                "content": "outbound, ignore me",
            },
            {
                "source": "whatsapp",
                "content": "inbound — pick me",
            },
        ]
        snippet = infer_inbound_language_hint(sources)
        assert "pick me" in snippet
        assert "ignore me" not in snippet

    def test_empty_when_no_sources(self) -> None:
        assert infer_inbound_language_hint(None) == ""
        assert infer_inbound_language_hint([]) == ""

    def test_truncates_long_bodies(self) -> None:
        long_body = "a" * 1000
        sources = [{"source": "apple_mail", "body": long_body}]
        snippet = infer_inbound_language_hint(sources)
        assert len(snippet) <= 400

    def test_falls_back_to_context_line(self) -> None:
        snippet = infer_inbound_language_hint(
            None, context_text="From Sarah: oi tudo bem?",
        )
        assert "oi tudo bem" in snippet


class TestSourceOfTruth:
    """``raw_messages.source`` is the column-of-truth for channel.
    These tests guarantee the inference path actually reads it (vs.
    a stale assumption that recall_context exposed only ``table``)
    by running an end-to-end through ``format_context``."""

    def _make_ctx(self, *rows: dict[str, Any]) -> Any:
        @dataclass
        class _Ctx:
            structured_data: list[dict[str, Any]]
            graph_context: list[dict[str, Any]]
            vector_results: list[dict[str, Any]]

        return _Ctx(
            structured_data=list(rows),
            graph_context=[],
            vector_results=[],
        )

    def test_raw_messages_source_propagates_to_sources_list(self) -> None:
        """The actual DB column value ('whatsapp') must reach the
        sources list — not just the table name."""
        from src.agents.brain.context import format_context

        ctx = self._make_ctx({
            "id": "m1",
            "source_table": "raw_messages",
            "source": "whatsapp",
            "sender": "Sarah",
            "sender_name": "Sarah",
            "content": "Oi! Vai regar as plantas hoje?",
            "is_from_me": 0,
            "sensitivity_tier": 2,
        })
        _text, sources = format_context(ctx)
        assert len(sources) == 1
        assert sources[0]["source"] == "whatsapp"
        assert sources[0]["content"] == "Oi! Vai regar as plantas hoje?"
        assert sources[0]["is_from_me"] is False

    def test_channel_inference_uses_db_column(self) -> None:
        """End-to-end: raw_messages row → format_context → sources →
        infer_action_channel. The whole pipeline must agree the
        channel is WhatsApp."""
        from src.agents.brain.context import format_context

        ctx = self._make_ctx({
            "id": "m1",
            "source_table": "raw_messages",
            "source": "whatsapp",
            "sender": "Sarah",
            "sender_name": "Sarah",
            "content": "Oi! Vai regar as plantas hoje?",
            "is_from_me": 0,
            "sensitivity_tier": 2,
        })
        _text, sources = format_context(ctx)
        hint = infer_action_channel(
            "reply saying I'm going to water them now",
            sources=sources,
        )
        assert hint.channel == "whatsapp"
        assert hint.confidence == "inferred"

    def test_raw_emails_synthesises_email_channel(self) -> None:
        from src.agents.brain.context import format_context

        ctx = self._make_ctx({
            "id": "e1",
            "source_table": "raw_emails",
            "subject": "watering plants",
            "body": "Hey, can you water the plants?",
            "is_from_me": 0,
            "sensitivity_tier": 2,
        })
        _text, sources = format_context(ctx)
        assert sources[0]["source"] == "email"
        hint = infer_action_channel("reply yes", sources=sources)
        assert hint.channel == "email"

    def test_inbound_language_hint_uses_db_content(self) -> None:
        from src.agents.brain.context import format_context

        ctx = self._make_ctx({
            "id": "m1",
            "source_table": "raw_messages",
            "source": "whatsapp",
            "sender": "Sarah",
            "content": "Oi! Vai regar as plantas hoje?",
            "is_from_me": 0,
            "sensitivity_tier": 2,
        })
        _text, sources = format_context(ctx)
        snippet = infer_inbound_language_hint(sources)
        assert "regar" in snippet

    def test_vector_branch_propagates_source_metadata(self) -> None:
        """ChromaDB chunks carry ``source`` in their metadata (per the
        ``add_documents`` contract). The vector branch of
        ``format_context`` must surface it the same way the structured
        branch does, so channel inference works whether the message
        arrived via DuckDB or via semantic search."""
        from src.agents.brain.context import format_context

        @dataclass
        class _Ctx:
            structured_data: list[dict[str, Any]]
            graph_context: list[dict[str, Any]]
            vector_results: list[dict[str, Any]]

        ctx = _Ctx(
            structured_data=[],
            graph_context=[],
            vector_results=[{
                "id": "msg-abc123",
                "document": "Oi! Vai regar as plantas hoje?",
                "metadata": {
                    "source": "whatsapp",
                    "sensitivity_tier": 2,
                    "timestamp": "2026-05-22T09:00:00Z",
                    "domain": "personal",
                    "is_from_me": False,
                    "sender_name": "Sarah",
                },
                "distance": 0.12,
                "collection": "personal",
            }],
        )
        _text, sources = format_context(ctx)
        assert len(sources) == 1
        assert sources[0]["source"] == "whatsapp"
        assert sources[0]["content"] == "Oi! Vai regar as plantas hoje?"
        # End-to-end: same channel inference works from a vector hit.
        hint = infer_action_channel("reply saying yes", sources=sources)
        assert hint.channel == "whatsapp"

    def test_outbound_messages_skipped_with_bool_flag(self) -> None:
        from src.agents.brain.context import format_context

        ctx = self._make_ctx(
            {
                "id": "m1",
                "source_table": "raw_messages",
                "source": "whatsapp",
                "content": "outbound — me writing",
                "is_from_me": 1,
                "sensitivity_tier": 2,
            },
            {
                "id": "m2",
                "source_table": "raw_messages",
                "source": "whatsapp",
                "content": "inbound — Sarah",
                "is_from_me": 0,
                "sensitivity_tier": 2,
            },
        )
        _text, sources = format_context(ctx)
        snippet = infer_inbound_language_hint(sources)
        assert "Sarah" in snippet
        assert "outbound" not in snippet


class TestMatchActionIntentChannelBias:
    """Smoke-test the integration between ``match_action_intent`` and
    ``filter_tools_by_channel`` — the matcher must prefer the
    same-channel tool when the hint matches."""

    def test_explicit_whatsapp_drops_email(self) -> None:
        from src.agents.brain.actions import match_action_intent

        @dataclass
        class FakeRegistry:
            tools: list[_Tool]

            def match_intent(self, _text: str) -> list[Any]:
                return list(self.tools)

        registry = FakeRegistry(
            tools=[
                _Tool("apple-mail", "reply_email"),
                _Tool("whatsapp", "send_message"),
            ],
        )
        chosen = match_action_intent(
            "reply on WhatsApp saying yes",
            registry,
            channel_hint=ChannelHint("whatsapp", "explicit"),
        )
        assert chosen is not None
        assert chosen.connector_id == "whatsapp"

"""Reply-context propagation: from "Draft reply" click to channel lock.

When the user clicks "Draft reply" on a card in the Today's Loops widget,
the Inbox, or a domain's Open Loops list, the navigation handler attaches
a structured ``reply_context = {source, message_id, contact_name}``. That
context travels through ``cmd_ask_stream`` into the Brain and is
consumed in two places:

1. ``seed_toolbox_from_reply_context`` — pins the context on the
   per-run ``ToolBox`` and seeds the original ``raw_messages`` row at
   the front of ``sources`` so the LLM has the authoritative contact
   info (WhatsApp JID, email, iMessage handle).
2. ``propose_action`` — converts ``reply_context.source`` into an
   *explicit* ``ChannelHint``, which makes ``filter_tools_by_channel``
   drop any non-matching reply tool. This is what stops a WhatsApp
   reply from being routed through Mail.

These tests lock that whole chain down at the unit boundaries.

sensitivity_tier: 2
"""

from __future__ import annotations

from typing import Any

from src.agents.brain.shared_tools import (
    ToolBox,
    seed_toolbox_from_reply_context,
)
from src.core.cli import _parse_reply_context_arg

# ---------------------------------------------------------------------
# _parse_reply_context_arg — the Rust → Python boundary
# ---------------------------------------------------------------------


class TestParseReplyContextArg:
    """The Rust IPC serializes ``ReplyContext`` to JSON and passes it
    as ``--reply-context``. Only fully-formed payloads should survive."""

    def test_none_input_returns_none(self) -> None:
        assert _parse_reply_context_arg(None) is None

    def test_empty_string_returns_none(self) -> None:
        assert _parse_reply_context_arg("") is None

    def test_invalid_json_returns_none(self) -> None:
        assert _parse_reply_context_arg("not json") is None

    def test_missing_source_returns_none(self) -> None:
        assert _parse_reply_context_arg('{"message_id": "m1"}') is None

    def test_missing_message_id_returns_none(self) -> None:
        assert _parse_reply_context_arg('{"source": "whatsapp"}') is None

    def test_valid_payload_normalizes(self) -> None:
        out = _parse_reply_context_arg(
            '{"source": "whatsapp", "message_id": "raw-42", '
            '"contact_name": "Elmara"}'
        )
        assert out == {
            "source": "whatsapp",
            "message_id": "raw-42",
            "contact_name": "Elmara",
        }

    def test_missing_contact_name_is_none(self) -> None:
        out = _parse_reply_context_arg(
            '{"source": "whatsapp", "message_id": "m1"}'
        )
        assert out is not None
        assert out["contact_name"] is None


# ---------------------------------------------------------------------
# seed_toolbox_from_reply_context — the Brain-side seed
# ---------------------------------------------------------------------


class _FakeDuck:
    """Stand-in for ``DataLayer.duckdb`` that returns a single row."""

    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows
        self.queries: list[tuple[str, list[Any]]] = []

    def query(
        self, sql: str, params: list[Any] | None = None,
    ) -> list[dict[str, Any]]:
        self.queries.append((sql, list(params or [])))
        return list(self._rows)


class _FakeQueryEngine:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        # Production ``QueryEngine`` exposes the analytical engine as
        # ``_duck`` (private by convention). Mirroring that name here
        # ensures the seed actually exercises the same code path it
        # would in production — using ``duckdb`` previously masked a
        # bug where seeding silently returned 0 sources.
        self._duck = _FakeDuck(rows)


class TestSeedToolboxFromReplyContext:
    """The seed helper has to do two things in one pass:
    pin the context on the toolbox and prepend the original message
    to ``sources`` so contact resolution is deterministic."""

    def test_no_reply_context_is_noop(self) -> None:
        tb = ToolBox.empty()
        qe = _FakeQueryEngine(rows=[])
        seed_toolbox_from_reply_context(tb, None, qe)
        assert tb.reply_context is None
        assert tb.sources == []

    def test_missing_message_id_still_pins_context(self) -> None:
        """A context without a message_id still gets pinned so the
        explicit ChannelHint path in propose_action fires, but sources
        is left untouched because there's nothing to seed."""
        tb = ToolBox.empty()
        qe = _FakeQueryEngine(rows=[])
        seed_toolbox_from_reply_context(
            tb,
            {"source": "whatsapp", "message_id": ""},
            qe,
        )
        assert tb.reply_context == {"source": "whatsapp", "message_id": ""}
        assert tb.sources == []
        assert qe._duck.queries == []

    def test_message_found_is_inserted_at_front(self) -> None:
        tb = ToolBox.empty()
        # Pretend the toolbox already had some unrelated source.
        tb.sources.append({"id": "later", "type": "structured"})
        qe = _FakeQueryEngine(rows=[{
            "id": "raw-42",
            "source": "whatsapp",
            "sender": "5511999999999@s.whatsapp.net",
            "sender_name": "Elmara Dittgen",
            "recipient": "me@s.whatsapp.net",
            "content": "Oi! Vai regar as plantas?",
            "is_from_me": False,
            "timestamp": "2026-05-22T08:00:00Z",
        }])
        ctx = {
            "source": "whatsapp",
            "message_id": "raw-42",
            "contact_name": "Elmara Dittgen",
        }
        seed_toolbox_from_reply_context(tb, ctx, qe)

        assert tb.reply_context == ctx
        # Seeded row must be at the front — ``infer_action_channel``
        # only inspects the first source with a known ``source`` value.
        assert tb.sources[0]["id"] == "raw-42"
        assert tb.sources[0]["source"] == "whatsapp"
        assert tb.sources[0]["sender"] == "5511999999999@s.whatsapp.net"
        assert tb.sources[0]["sender_name"] == "Elmara Dittgen"
        assert tb.sources[0]["content"] == "Oi! Vai regar as plantas?"
        assert tb.sources[0]["is_from_me"] is False
        # Earlier sources survive.
        assert tb.sources[-1]["id"] == "later"

    def test_message_not_found_only_pins_context(self) -> None:
        """When the row vanished (deleted, dismissed), seeding sources
        is silently skipped — the brain still gets the channel lock."""
        tb = ToolBox.empty()
        qe = _FakeQueryEngine(rows=[])
        seed_toolbox_from_reply_context(
            tb,
            {"source": "apple_mail", "message_id": "gone"},
            qe,
        )
        assert tb.reply_context == {
            "source": "apple_mail", "message_id": "gone",
        }
        assert tb.sources == []

    def test_db_failure_is_swallowed(self) -> None:
        class _ExplodingDuck(_FakeDuck):
            def query(self, sql: str, params: Any = None) -> Any:
                raise RuntimeError("db blew up")

        tb = ToolBox.empty()
        qe = _FakeQueryEngine(rows=[])
        qe._duck = _ExplodingDuck(rows=[])
        seed_toolbox_from_reply_context(
            tb,
            {"source": "whatsapp", "message_id": "m1"},
            qe,
        )
        # Context still pinned — the brain's channel lock must not be
        # held hostage by a transient DB error.
        assert tb.reply_context == {
            "source": "whatsapp", "message_id": "m1",
        }
        assert tb.sources == []

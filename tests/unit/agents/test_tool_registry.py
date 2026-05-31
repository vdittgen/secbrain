"""Unit tests for the ToolRegistry — action tool discovery and intent matching.

Tests cover ActionTool dataclass, tool discovery from enabled connectors,
intent matching, and edge cases.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from src.agents.tool_registry import ActionTool, ToolRegistry
from src.extensions.models import ConnectorTemplate, ToolTemplate

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_connector(
    connector_id: str = "apple-calendar",
    name: str = "Apple Calendar",
    tools: tuple[ToolTemplate, ...] | None = None,
) -> ConnectorTemplate:
    """Build a minimal ConnectorTemplate for testing."""
    if tools is None:
        tools = (
            ToolTemplate(
                tool_name="list_calendar_events",
                tool_type="data",
                target_table="raw_calendar_events",
            ),
            ToolTemplate(
                tool_name="create_event",
                tool_type="action",
                target_table=None,
            ),
            ToolTemplate(
                tool_name="create_reminder",
                tool_type="action",
                target_table=None,
            ),
        )
    return ConnectorTemplate(
        id=connector_id,
        name=name,
        category="apple",
        icon="calendar",
        description="Apple Calendar events and reminders",
        command="npx",
        args=("-y", "@supermemoryai/apple-mcp"),
        transport="stdio",
        tools=tools,
    )


def _make_registry_and_catalog(
    connectors: list[ConnectorTemplate] | None = None,
    enabled_ids: list[str] | None = None,
) -> tuple[MagicMock, MagicMock]:
    """Build mock catalog and registry.

    Returns (catalog, registry).
    """
    if connectors is None:
        connectors = [_make_connector()]
    if enabled_ids is None:
        enabled_ids = [c.id for c in connectors]

    catalog = MagicMock()
    catalog.get.side_effect = lambda cid: next(
        (c for c in connectors if c.id == cid), None,
    )

    # Build mock enabled extensions
    enabled = []
    for cid in enabled_ids:
        ext = MagicMock()
        ext.connector_id = cid
        enabled.append(ext)

    registry = MagicMock()
    registry.get_enabled.return_value = enabled

    return catalog, registry


# ---------------------------------------------------------------------------
# TestActionTool
# ---------------------------------------------------------------------------


class TestActionTool:
    def test_creates_with_defaults(self) -> None:
        tool = ActionTool(
            connector_id="cal",
            connector_name="Calendar",
            tool_name="create_event",
            description="Create events",
        )
        assert tool.connector_id == "cal"
        assert tool.input_schema == {}

    def test_generates_display_name(self) -> None:
        tool = ActionTool(
            connector_id="cal",
            connector_name="Calendar",
            tool_name="create_event",
            description="Create events",
        )
        assert tool.display_name == "Create Event"

    def test_preserves_explicit_display_name(self) -> None:
        tool = ActionTool(
            connector_id="cal",
            connector_name="Calendar",
            tool_name="create_event",
            description="Create events",
            display_name="Custom Name",
        )
        assert tool.display_name == "Custom Name"

    def test_display_name_multi_word(self) -> None:
        tool = ActionTool(
            connector_id="msg",
            connector_name="Messages",
            tool_name="send_message",
            description="Send messages",
        )
        assert tool.display_name == "Send Message"

    def test_frozen(self) -> None:
        tool = ActionTool(
            connector_id="cal",
            connector_name="Calendar",
            tool_name="create_event",
            description="Create events",
        )
        with pytest.raises(AttributeError):
            tool.connector_id = "other"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# TestGetAvailableActions
# ---------------------------------------------------------------------------


class TestGetAvailableActions:
    def test_discovers_action_tools(self) -> None:
        """Should return only action tools from enabled connectors."""
        catalog, registry = _make_registry_and_catalog()
        tr = ToolRegistry(catalog=catalog, registry=registry)
        actions = tr.get_available_actions()

        assert len(actions) == 2
        names = {a.tool_name for a in actions}
        assert names == {"create_event", "create_reminder"}

    def test_skips_data_tools(self) -> None:
        """Data tools should not be returned."""
        catalog, registry = _make_registry_and_catalog()
        tr = ToolRegistry(catalog=catalog, registry=registry)
        actions = tr.get_available_actions()

        for a in actions:
            assert a.tool_name != "list_calendar_events"

    def test_empty_when_no_enabled(self) -> None:
        """No enabled connectors → empty list."""
        catalog, registry = _make_registry_and_catalog(enabled_ids=[])
        tr = ToolRegistry(catalog=catalog, registry=registry)
        assert tr.get_available_actions() == []

    def test_skips_unknown_connector(self) -> None:
        """Enabled connector not in catalog should be skipped."""
        catalog, registry = _make_registry_and_catalog(
            connectors=[_make_connector()],
            enabled_ids=["nonexistent"],
        )
        tr = ToolRegistry(catalog=catalog, registry=registry)
        assert tr.get_available_actions() == []

    def test_multiple_connectors(self) -> None:
        """Action tools from multiple connectors are combined."""
        cal = _make_connector(
            connector_id="apple-calendar",
            name="Apple Calendar",
        )
        msg = _make_connector(
            connector_id="imessage",
            name="iMessage",
            tools=(
                ToolTemplate(
                    tool_name="send_message",
                    tool_type="action",
                    target_table=None,
                ),
            ),
        )
        catalog, registry = _make_registry_and_catalog(
            connectors=[cal, msg],
            enabled_ids=["apple-calendar", "imessage"],
        )
        tr = ToolRegistry(catalog=catalog, registry=registry)
        actions = tr.get_available_actions()
        assert len(actions) == 3

    def test_connector_with_no_action_tools(self) -> None:
        """Connector with only data tools → no actions returned."""
        data_only = _make_connector(
            connector_id="filesystem",
            name="Filesystem",
            tools=(
                ToolTemplate(
                    tool_name="list_files",
                    tool_type="data",
                    target_table="raw_files",
                ),
            ),
        )
        catalog, registry = _make_registry_and_catalog(
            connectors=[data_only],
        )
        tr = ToolRegistry(catalog=catalog, registry=registry)
        assert tr.get_available_actions() == []


# ---------------------------------------------------------------------------
# TestGetAction
# ---------------------------------------------------------------------------


class TestGetAction:
    def test_finds_existing_action(self) -> None:
        catalog, registry = _make_registry_and_catalog()
        tr = ToolRegistry(catalog=catalog, registry=registry)
        action = tr.get_action("apple-calendar", "create_event")
        assert action is not None
        assert action.tool_name == "create_event"
        assert action.connector_id == "apple-calendar"

    def test_returns_none_for_data_tool(self) -> None:
        catalog, registry = _make_registry_and_catalog()
        tr = ToolRegistry(catalog=catalog, registry=registry)
        assert tr.get_action("apple-calendar", "list_calendar_events") is None

    def test_returns_none_for_unknown_connector(self) -> None:
        catalog, registry = _make_registry_and_catalog()
        tr = ToolRegistry(catalog=catalog, registry=registry)
        assert tr.get_action("nonexistent", "create_event") is None

    def test_returns_none_for_unknown_tool(self) -> None:
        catalog, registry = _make_registry_and_catalog()
        tr = ToolRegistry(catalog=catalog, registry=registry)
        assert tr.get_action("apple-calendar", "delete_event") is None


# ---------------------------------------------------------------------------
# TestMatchIntent
# ---------------------------------------------------------------------------


class TestMatchIntent:
    def test_matches_send_message(self) -> None:
        """'Send Alice a message' should match send_message."""
        msg = _make_connector(
            connector_id="imessage",
            name="iMessage",
            tools=(
                ToolTemplate(
                    tool_name="send_message",
                    tool_type="action",
                    target_table=None,
                ),
            ),
        )
        catalog, registry = _make_registry_and_catalog(
            connectors=[msg],
        )
        tr = ToolRegistry(catalog=catalog, registry=registry)
        matches = tr.match_intent("Send Alice a message saying hello")
        assert len(matches) >= 1
        assert matches[0].tool_name == "send_message"

    def test_matches_create_event(self) -> None:
        """'Create an event tomorrow' should match create_event."""
        catalog, registry = _make_registry_and_catalog()
        tr = ToolRegistry(catalog=catalog, registry=registry)
        matches = tr.match_intent("Create an event for tomorrow at 3pm")
        assert len(matches) >= 1
        assert matches[0].tool_name == "create_event"

    def test_matches_schedule_meeting(self) -> None:
        """'Schedule a meeting' should match create_event."""
        catalog, registry = _make_registry_and_catalog()
        tr = ToolRegistry(catalog=catalog, registry=registry)
        matches = tr.match_intent("Schedule a meeting with Bob on Friday")
        assert len(matches) >= 1
        tool_names = {m.tool_name for m in matches}
        assert "create_event" in tool_names or "create_reminder" in tool_names

    def test_no_match_for_query(self) -> None:
        """'What's on my schedule?' should not match."""
        catalog, registry = _make_registry_and_catalog()
        tr = ToolRegistry(catalog=catalog, registry=registry)
        matches = tr.match_intent("What's on my schedule today?")
        assert matches == []

    def test_no_match_for_empty_text(self) -> None:
        catalog, registry = _make_registry_and_catalog()
        tr = ToolRegistry(catalog=catalog, registry=registry)
        assert tr.match_intent("") == []
        assert tr.match_intent("   ") == []

    def test_no_match_when_no_enabled_connectors(self) -> None:
        catalog, registry = _make_registry_and_catalog(enabled_ids=[])
        tr = ToolRegistry(catalog=catalog, registry=registry)
        assert tr.match_intent("Send a message") == []

    def test_matches_play_music(self) -> None:
        """'Play some music' should match play_track."""
        spotify = _make_connector(
            connector_id="spotify",
            name="Spotify",
            tools=(
                ToolTemplate(
                    tool_name="play_track",
                    tool_type="action",
                    target_table=None,
                ),
            ),
        )
        catalog, registry = _make_registry_and_catalog(
            connectors=[spotify],
        )
        tr = ToolRegistry(catalog=catalog, registry=registry)
        matches = tr.match_intent("Play some music for me")
        assert len(matches) >= 1
        assert matches[0].tool_name == "play_track"

    def test_matches_write_note(self) -> None:
        """'Write a note about...' should match create_note."""
        notes = _make_connector(
            connector_id="obsidian",
            name="Obsidian",
            tools=(
                ToolTemplate(
                    tool_name="create_note",
                    tool_type="action",
                    target_table=None,
                ),
            ),
        )
        catalog, registry = _make_registry_and_catalog(
            connectors=[notes],
        )
        tr = ToolRegistry(catalog=catalog, registry=registry)
        matches = tr.match_intent("Write a note about today's meeting")
        assert len(matches) >= 1
        assert matches[0].tool_name == "create_note"

    # ----- Portuguese intent matching -----

    def test_match_portuguese_create_note(self) -> None:
        """'Crie uma nota' should match create_note."""
        notes = _make_connector(
            connector_id="apple-notes",
            name="Apple Notes",
            tools=(
                ToolTemplate(
                    tool_name="create_note",
                    tool_type="action",
                    target_table=None,
                ),
            ),
        )
        catalog, registry = _make_registry_and_catalog(connectors=[notes])
        tr = ToolRegistry(catalog=catalog, registry=registry)
        matches = tr.match_intent("Crie uma nota com as tarefas de hoje")
        assert len(matches) >= 1
        assert matches[0].tool_name == "create_note"

    def test_match_portuguese_schedule_event(self) -> None:
        """'Agende uma reunião amanhã' should match create_event."""
        catalog, registry = _make_registry_and_catalog()
        tr = ToolRegistry(catalog=catalog, registry=registry)
        matches = tr.match_intent("Agende uma reunião amanhã às 15h")
        assert len(matches) >= 1
        assert matches[0].tool_name == "create_event"

    def test_match_portuguese_send_message(self) -> None:
        """'Envie uma mensagem para João' should match send_message."""
        msg = _make_connector(
            connector_id="whatsapp",
            name="WhatsApp",
            tools=(
                ToolTemplate(
                    tool_name="send_message",
                    tool_type="action",
                    target_table=None,
                ),
            ),
        )
        catalog, registry = _make_registry_and_catalog(connectors=[msg])
        tr = ToolRegistry(catalog=catalog, registry=registry)
        matches = tr.match_intent("Envie uma mensagem para João")
        assert len(matches) >= 1
        assert matches[0].tool_name == "send_message"

    def test_match_portuguese_question_not_action(self) -> None:
        """'Qual é a minha agenda?' is a question, not an action."""
        catalog, registry = _make_registry_and_catalog()
        tr = ToolRegistry(catalog=catalog, registry=registry)
        matches = tr.match_intent("Qual é a minha agenda?")
        assert matches == []

    def test_match_portuguese_request_pattern(self) -> None:
        """'Você pode criar um evento?' should match create_event."""
        catalog, registry = _make_registry_and_catalog()
        tr = ToolRegistry(catalog=catalog, registry=registry)
        matches = tr.match_intent("Você pode criar um evento amanhã?")
        assert len(matches) >= 1
        assert matches[0].tool_name == "create_event"

    def test_unicode_accented_nouns(self) -> None:
        """Portuguese nouns with accents should be tokenized correctly."""
        catalog, registry = _make_registry_and_catalog()
        tr = ToolRegistry(catalog=catalog, registry=registry)
        # "reunião" must be kept whole, not split at "ã"
        matches = tr.match_intent("Marque uma reunião para sexta-feira")
        assert len(matches) >= 1
        tool_names = {m.tool_name for m in matches}
        assert "create_event" in tool_names

    def test_match_portuguese_infinitive_criar(self) -> None:
        """Infinitive 'criar' should also match."""
        notes = _make_connector(
            connector_id="apple-notes",
            name="Apple Notes",
            tools=(
                ToolTemplate(
                    tool_name="create_note",
                    tool_type="action",
                    target_table=None,
                ),
            ),
        )
        catalog, registry = _make_registry_and_catalog(connectors=[notes])
        tr = ToolRegistry(catalog=catalog, registry=registry)
        matches = tr.match_intent("Eu quero criar uma nota")
        assert len(matches) >= 1
        assert matches[0].tool_name == "create_note"

    # ----- End Portuguese tests -----

    # ----- Search / Reply / Email / Note action tests -----

    def test_matches_search_notes(self) -> None:
        """'Search my notes' should match search_notes."""
        notes = _make_connector(
            connector_id="apple-notes",
            name="Apple Notes",
            tools=(
                ToolTemplate(
                    tool_name="search_notes",
                    tool_type="action",
                    target_table=None,
                ),
                ToolTemplate(
                    tool_name="update_note",
                    tool_type="action",
                    target_table=None,
                ),
            ),
        )
        catalog, registry = _make_registry_and_catalog(connectors=[notes])
        tr = ToolRegistry(catalog=catalog, registry=registry)
        matches = tr.match_intent("Search my notes for meeting minutes")
        assert len(matches) >= 1
        assert matches[0].tool_name == "search_notes"

    def test_matches_update_note(self) -> None:
        """'Edit my note' should match update_note."""
        notes = _make_connector(
            connector_id="apple-notes",
            name="Apple Notes",
            tools=(
                ToolTemplate(
                    tool_name="update_note",
                    tool_type="action",
                    target_table=None,
                ),
            ),
        )
        catalog, registry = _make_registry_and_catalog(connectors=[notes])
        tr = ToolRegistry(catalog=catalog, registry=registry)
        matches = tr.match_intent("Edit my note about tasks")
        assert len(matches) >= 1
        assert matches[0].tool_name == "update_note"

    def test_matches_reply_email(self) -> None:
        """'Reply to the email' should match reply_email."""
        mail = _make_connector(
            connector_id="apple-mail",
            name="Mail",
            tools=(
                ToolTemplate(
                    tool_name="reply_email",
                    tool_type="action",
                    target_table=None,
                ),
                ToolTemplate(
                    tool_name="send_email",
                    tool_type="action",
                    target_table=None,
                ),
            ),
        )
        catalog, registry = _make_registry_and_catalog(connectors=[mail])
        tr = ToolRegistry(catalog=catalog, registry=registry)
        matches = tr.match_intent("Reply to the email from Bob")
        assert len(matches) >= 1
        assert matches[0].tool_name == "reply_email"

    def test_matches_delete_email(self) -> None:
        """'Delete the email' should match delete_email."""
        mail = _make_connector(
            connector_id="apple-mail",
            name="Mail",
            tools=(
                ToolTemplate(
                    tool_name="delete_email",
                    tool_type="action",
                    target_table=None,
                ),
            ),
        )
        catalog, registry = _make_registry_and_catalog(connectors=[mail])
        tr = ToolRegistry(catalog=catalog, registry=registry)
        matches = tr.match_intent("Delete the email about project update")
        assert len(matches) >= 1
        assert matches[0].tool_name == "delete_email"

    def test_matches_flag_email(self) -> None:
        """'Flag the email' should match flag_email."""
        mail = _make_connector(
            connector_id="apple-mail",
            name="Mail",
            tools=(
                ToolTemplate(
                    tool_name="flag_email",
                    tool_type="action",
                    target_table=None,
                ),
            ),
        )
        catalog, registry = _make_registry_and_catalog(connectors=[mail])
        tr = ToolRegistry(catalog=catalog, registry=registry)
        matches = tr.match_intent("Flag the email from HR")
        assert len(matches) >= 1
        assert matches[0].tool_name == "flag_email"

    def test_matches_move_email(self) -> None:
        """'Move the email to Archive' should match move_email."""
        mail = _make_connector(
            connector_id="apple-mail",
            name="Mail",
            tools=(
                ToolTemplate(
                    tool_name="move_email",
                    tool_type="action",
                    target_table=None,
                ),
            ),
        )
        catalog, registry = _make_registry_and_catalog(connectors=[mail])
        tr = ToolRegistry(catalog=catalog, registry=registry)
        matches = tr.match_intent("Move the email to Archive folder")
        assert len(matches) >= 1
        assert matches[0].tool_name == "move_email"

    def test_matches_send_email(self) -> None:
        """'Send an email to Alice' should match send_email."""
        mail = _make_connector(
            connector_id="apple-mail",
            name="Mail",
            tools=(
                ToolTemplate(
                    tool_name="send_email",
                    tool_type="action",
                    target_table=None,
                ),
            ),
        )
        catalog, registry = _make_registry_and_catalog(connectors=[mail])
        tr = ToolRegistry(catalog=catalog, registry=registry)
        matches = tr.match_intent("Send an email to Alice about the meeting")
        assert len(matches) >= 1
        assert matches[0].tool_name == "send_email"

    def test_match_portuguese_search_notes(self) -> None:
        """'Busque nas notas' should match search_notes."""
        notes = _make_connector(
            connector_id="apple-notes",
            name="Apple Notes",
            tools=(
                ToolTemplate(
                    tool_name="search_notes",
                    tool_type="action",
                    target_table=None,
                ),
            ),
        )
        catalog, registry = _make_registry_and_catalog(connectors=[notes])
        tr = ToolRegistry(catalog=catalog, registry=registry)
        matches = tr.match_intent("Busque nas minhas notas sobre reunião")
        assert len(matches) >= 1
        assert matches[0].tool_name == "search_notes"

    def test_match_portuguese_reply_email(self) -> None:
        """'Responda o email' should match reply_email."""
        mail = _make_connector(
            connector_id="apple-mail",
            name="Mail",
            tools=(
                ToolTemplate(
                    tool_name="reply_email",
                    tool_type="action",
                    target_table=None,
                ),
            ),
        )
        catalog, registry = _make_registry_and_catalog(connectors=[mail])
        tr = ToolRegistry(catalog=catalog, registry=registry)
        matches = tr.match_intent("Responda o email do João")
        assert len(matches) >= 1
        assert matches[0].tool_name == "reply_email"

    def test_match_portuguese_delete_email(self) -> None:
        """'Apague o email' should match delete_email."""
        mail = _make_connector(
            connector_id="apple-mail",
            name="Mail",
            tools=(
                ToolTemplate(
                    tool_name="delete_email",
                    tool_type="action",
                    target_table=None,
                ),
            ),
        )
        catalog, registry = _make_registry_and_catalog(connectors=[mail])
        tr = ToolRegistry(catalog=catalog, registry=registry)
        matches = tr.match_intent("Apague o email sobre promoção")
        assert len(matches) >= 1
        assert matches[0].tool_name == "delete_email"

    def test_match_portuguese_edit_note(self) -> None:
        """'Edite a nota' should match update_note."""
        notes = _make_connector(
            connector_id="apple-notes",
            name="Apple Notes",
            tools=(
                ToolTemplate(
                    tool_name="update_note",
                    tool_type="action",
                    target_table=None,
                ),
            ),
        )
        catalog, registry = _make_registry_and_catalog(connectors=[notes])
        tr = ToolRegistry(catalog=catalog, registry=registry)
        matches = tr.match_intent("Edite a nota de tarefas")
        assert len(matches) >= 1
        assert matches[0].tool_name == "update_note"

    # ----- End search/reply/email/note tests -----

    def test_ranks_noun_match_higher(self) -> None:
        """When multiple tools match, noun-specific match ranks higher."""
        conn = _make_connector(
            connector_id="multi",
            name="Multi",
            tools=(
                ToolTemplate(
                    tool_name="send_email",
                    tool_type="action",
                    target_table=None,
                ),
                ToolTemplate(
                    tool_name="send_message",
                    tool_type="action",
                    target_table=None,
                ),
            ),
        )
        catalog, registry = _make_registry_and_catalog(
            connectors=[conn],
        )
        tr = ToolRegistry(catalog=catalog, registry=registry)
        matches = tr.match_intent("Send an email to Bob")
        assert len(matches) >= 1
        assert matches[0].tool_name == "send_email"

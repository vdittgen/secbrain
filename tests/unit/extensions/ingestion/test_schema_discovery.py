"""Tests for the two-pass schema discovery agent.

sensitivity_tier: N/A (test infrastructure)
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest
from src.extensions.ingestion.schema_discovery import (
    SchemaDiscoveryAgent,
    _classify_domain,
    _classify_field_sensitivity,
    _compute_jaccard,
    _detect_dedup_key,
    _detect_nested_fields,
    _find_best_table_match,
    _infer_source_type,
    _infer_target_type,
    _normalize_column_name,
    _suggest_schedule,
    to_tool_template,
)

# ---------------------------------------------------------------------------
# Test data factories
# ---------------------------------------------------------------------------


def _existing_table_schemas() -> dict[str, list[str]]:
    """All 12 raw tables and their columns, matching DuckDB schema."""
    return {
        "raw_messages": [
            "id", "source", "sender", "recipient", "content", "timestamp",
            "metadata", "sensitivity_tier", "is_from_me", "chat_name", "is_group",
        ],
        "raw_calendar_events": [
            "id", "title", "description", "start_time", "end_time",
            "location", "attendees", "sensitivity_tier", "is_all_day",
        ],
        "raw_notes": [
            "id", "title", "content", "source", "created_at", "updated_at",
            "tags", "sensitivity_tier", "filepath", "parent_page",
        ],
        "raw_health_metrics": [
            "id", "metric_type", "value", "unit", "recorded_at",
            "source", "sensitivity_tier",
        ],
        "raw_contacts": [
            "id", "name", "email", "phone", "relationship", "notes",
            "last_contact", "sensitivity_tier", "birthday", "address",
        ],
        "raw_files": [
            "id", "filepath", "filename", "filetype", "size_bytes",
            "created_at", "modified_at", "content_preview", "sensitivity_tier",
        ],
        "raw_emails": [
            "id", "subject", "sender", "recipients", "body_preview",
            "received_at", "folder", "is_read", "labels", "sensitivity_tier",
        ],
        "raw_reminders": [
            "id", "title", "due_date", "notes", "completed",
            "list_name", "sensitivity_tier",
        ],
        "raw_workouts": [
            "id", "workout_type", "duration_minutes", "calories_burned",
            "distance_km", "heart_rate_avg", "recorded_at", "source",
            "sensitivity_tier",
        ],
        "raw_voice_memos": [
            "id", "title", "filepath", "duration_seconds", "recorded_at",
            "transcript", "sensitivity_tier",
        ],
        "raw_listening_history": [
            "id", "track_name", "artist_name", "album_name", "played_at",
            "duration_seconds", "source", "sensitivity_tier",
        ],
    }


def _make_calendar_records() -> list[dict[str, Any]]:
    """Sample MCP output matching raw_calendar_events."""
    return [
        {
            "id": "evt-001",
            "title": "Team standup",
            "description": "Daily sync meeting",
            "start_time": "2025-06-15T09:00:00Z",
            "end_time": "2025-06-15T09:30:00Z",
            "location": "Conference Room A",
            "attendees": ["alice@co.com", "bob@co.com"],
            "is_all_day": False,
        },
        {
            "id": "evt-002",
            "title": "Lunch with Sarah",
            "description": None,
            "start_time": "2025-06-15T12:00:00Z",
            "end_time": "2025-06-15T13:00:00Z",
            "location": "Café Milano",
            "attendees": [],
            "is_all_day": False,
        },
        {
            "id": "evt-003",
            "title": "Project deadline",
            "description": "Final delivery for Q2 project",
            "start_time": "2025-06-20T00:00:00Z",
            "end_time": "2025-06-20T23:59:59Z",
            "location": None,
            "attendees": [],
            "is_all_day": True,
        },
    ]


def _make_message_records() -> list[dict[str, Any]]:
    """Sample MCP output matching raw_messages."""
    return [
        {
            "id": "msg-001",
            "sender": "alice@example.com",
            "recipient": "me@example.com",
            "content": "Hey, can we meet tomorrow?",
            "timestamp": "2025-06-14T18:30:00Z",
            "source": "imessage",
        },
        {
            "id": "msg-002",
            "sender": "me@example.com",
            "recipient": "bob@work.com",
            "content": "The report is ready for review",
            "timestamp": "2025-06-14T19:00:00Z",
            "source": "imessage",
        },
        {
            "id": "msg-003",
            "sender": "charlie@example.com",
            "recipient": "me@example.com",
            "content": "Happy birthday!",
            "timestamp": "2025-06-14T20:00:00Z",
            "source": "imessage",
        },
    ]


def _make_health_records() -> list[dict[str, Any]]:
    """Sample MCP output matching raw_health_metrics."""
    return [
        {
            "id": "h-001",
            "metric_type": "heart_rate",
            "value": 72.0,
            "unit": "bpm",
            "recorded_at": "2025-06-14T08:00:00Z",
            "source": "apple_health",
        },
        {
            "id": "h-002",
            "metric_type": "steps",
            "value": 8450.0,
            "unit": "count",
            "recorded_at": "2025-06-14T23:59:00Z",
            "source": "apple_health",
        },
        {
            "id": "h-003",
            "metric_type": "blood_pressure",
            "value": 120.0,
            "unit": "mmHg",
            "recorded_at": "2025-06-14T09:00:00Z",
            "source": "apple_health",
        },
    ]


def _make_music_records() -> list[dict[str, Any]]:
    """Sample MCP output for listening history."""
    return [
        {
            "id": "play-001",
            "track_name": "Bohemian Rhapsody",
            "artist_name": "Queen",
            "album_name": "A Night at the Opera",
            "played_at": "2025-06-14T14:30:00Z",
            "duration_seconds": 354,
            "source": "spotify",
        },
        {
            "id": "play-002",
            "track_name": "Imagine",
            "artist_name": "John Lennon",
            "album_name": "Imagine",
            "played_at": "2025-06-14T14:36:00Z",
            "duration_seconds": 187,
            "source": "spotify",
        },
        {
            "id": "play-003",
            "track_name": "Stairway to Heaven",
            "artist_name": "Led Zeppelin",
            "album_name": "Led Zeppelin IV",
            "played_at": "2025-06-14T14:40:00Z",
            "duration_seconds": 482,
            "source": "spotify",
        },
    ]


def _make_nested_records() -> list[dict[str, Any]]:
    """Sample MCP output with nested objects."""
    return [
        {
            "id": "n-001",
            "title": "Team meeting notes",
            "author": {"name": "Alice Smith", "email": "alice@co.com"},
            "created_at": "2025-06-14T10:00:00Z",
        },
        {
            "id": "n-002",
            "title": "Project plan",
            "author": {"name": "Bob Jones", "email": "bob@co.com"},
            "created_at": "2025-06-14T11:00:00Z",
        },
        {
            "id": "n-003",
            "title": "Design review",
            "author": {"name": "Carol Lee", "email": "carol@co.com"},
            "created_at": "2025-06-14T12:00:00Z",
        },
    ]


def _make_unknown_records() -> list[dict[str, Any]]:
    """Sample MCP output for a novel data type (no existing table match)."""
    return [
        {
            "id": "recipe-001",
            "recipe_name": "Pasta Carbonara",
            "cuisine": "Italian",
            "prep_minutes": 15,
            "cook_minutes": 20,
            "ingredients": ["pasta", "eggs", "pecorino", "guanciale"],
            "rating": 4.5,
        },
        {
            "id": "recipe-002",
            "recipe_name": "Pad Thai",
            "cuisine": "Thai",
            "prep_minutes": 20,
            "cook_minutes": 15,
            "ingredients": ["rice noodles", "shrimp", "peanuts", "lime"],
            "rating": 4.2,
        },
        {
            "id": "recipe-003",
            "recipe_name": "Caesar Salad",
            "cuisine": "American",
            "prep_minutes": 10,
            "cook_minutes": 0,
            "ingredients": ["romaine", "croutons", "parmesan", "dressing"],
            "rating": 3.8,
        },
    ]


@pytest.fixture()
def existing_tables() -> dict[str, list[str]]:
    """All existing DuckDB raw table schemas."""
    return _existing_table_schemas()


@pytest.fixture(autouse=True)
def _stub_sbagent_default(monkeypatch):
    """Default: ``SchemaDiscoveryAgent.discover`` returns None.

    Forces rule-based-only behaviour in tests that don't explicitly
    care about the LLM path. ``TestLLMFallback`` and
    ``TestMergeStrategy`` override this stub with the
    ``stub_schema_sbagent`` fixture below.
    """
    monkeypatch.setattr(
        "src.agents.schema_discovery.agent.SchemaDiscoveryAgent.discover",
        lambda self, *, tool_name, sample_records, known_tables=None: None,
    )


@pytest.fixture()
def stub_schema_sbagent(monkeypatch):
    """Monkey-patch ``SchemaDiscoveryAgent.discover`` with a controllable stub.

    Tests set ``stub_schema_sbagent.return_value`` to a
    :class:`SchemaDiscoveryDraft` (or ``None`` to simulate failure),
    or ``side_effect`` to raise.
    """
    fake = MagicMock(return_value=None)

    def _bound(
        self,
        *,
        tool_name,
        sample_records,
        known_tables=None,
    ):  # noqa: ARG001
        result = fake(
            tool_name=tool_name,
            sample_records=sample_records,
            known_tables=known_tables,
        )
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(
        "src.agents.schema_discovery.agent.SchemaDiscoveryAgent.discover",
        _bound,
    )
    return fake


@pytest.fixture()
def agent(existing_tables: dict[str, list[str]]) -> SchemaDiscoveryAgent:
    """SchemaDiscoveryAgent with all existing table schemas loaded."""
    return SchemaDiscoveryAgent(
        existing_tables=existing_tables,
        confidence_threshold=0.6,
    )


@pytest.fixture()
def agent_no_tables() -> SchemaDiscoveryAgent:
    """SchemaDiscoveryAgent with no existing tables."""
    return SchemaDiscoveryAgent(existing_tables={}, confidence_threshold=0.6)


# ---------------------------------------------------------------------------
# TestTypeInference
# ---------------------------------------------------------------------------


class TestTypeInference:
    """Tests for _infer_source_type()."""

    def test_infer_string_type(self) -> None:
        """All string values should return 'string'."""
        assert _infer_source_type(["hello", "world", "test"]) == "string"

    def test_infer_number_type_int(self) -> None:
        """All integer values should return 'number'."""
        assert _infer_source_type([1, 2, 3]) == "number"

    def test_infer_number_type_float(self) -> None:
        """All float values should return 'number'."""
        assert _infer_source_type([1.5, 2.7, 3.14]) == "number"

    def test_infer_boolean_type(self) -> None:
        """All boolean values should return 'boolean'."""
        assert _infer_source_type([True, False, True]) == "boolean"

    def test_infer_array_type(self) -> None:
        """All list values should return 'array'."""
        assert _infer_source_type([[1, 2], [3], []]) == "array"

    def test_infer_object_type(self) -> None:
        """All dict values should return 'object'."""
        assert _infer_source_type([{"a": 1}, {"b": 2}]) == "object"

    def test_infer_mixed_defaults_to_string(self) -> None:
        """Mixed types should default to 'string' (majority or tie-break)."""
        result = _infer_source_type(["hello", 42, True])
        # Each type has 1 vote; string wins alphabetically or by dict order
        assert result in ("string", "number", "boolean")

    def test_infer_all_none_defaults_to_string(self) -> None:
        """All None values should default to 'string'."""
        assert _infer_source_type([None, None, None]) == "string"


# ---------------------------------------------------------------------------
# TestTargetTypeMapping
# ---------------------------------------------------------------------------


class TestTargetTypeMapping:
    """Tests for _infer_target_type()."""

    def test_timestamp_detection_from_field_name(self) -> None:
        """Field named 'created_at' with ISO values should map to TEXT."""
        target, transform = _infer_target_type(
            "string", "created_at", ["2025-06-14T10:00:00Z"],
        )
        assert target == "TEXT"
        assert transform == "iso_to_timestamp"

    def test_long_text_detection(self) -> None:
        """Strings averaging >500 chars should map to TEXT."""
        long_text = "x" * 600
        target, transform = _infer_target_type(
            "string", "body", [long_text, long_text],
        )
        assert target == "TEXT"
        assert transform is None

    def test_short_string_to_varchar(self) -> None:
        """Normal short strings should map to VARCHAR."""
        target, transform = _infer_target_type(
            "string", "title", ["Hello", "World"],
        )
        assert target == "VARCHAR"
        assert transform is None

    def test_integer_detection(self) -> None:
        """All int values should map to INTEGER."""
        target, transform = _infer_target_type(
            "number", "count", [10, 20, 30],
        )
        assert target == "INTEGER"
        assert transform is None

    def test_bigint_detection(self) -> None:
        """Large int values should map to BIGINT."""
        target, transform = _infer_target_type(
            "number", "big_id", [2**32, 2**33],
        )
        assert target == "BIGINT"
        assert transform is None

    def test_float_to_double(self) -> None:
        """Float values should map to DOUBLE."""
        target, transform = _infer_target_type(
            "number", "score", [1.5, 2.7],
        )
        assert target == "DOUBLE"
        assert transform is None

    def test_boolean_mapping(self) -> None:
        """Boolean values should map to BOOLEAN."""
        target, transform = _infer_target_type(
            "boolean", "is_active", [True, False],
        )
        assert target == "BOOLEAN"
        assert transform is None

    def test_array_to_json(self) -> None:
        """Array values should map to JSON with json_array transform."""
        target, transform = _infer_target_type(
            "array", "tags", [["a", "b"], ["c"]],
        )
        assert target == "JSON"
        assert transform == "json_array"


# ---------------------------------------------------------------------------
# TestSensitivityClassification
# ---------------------------------------------------------------------------


class TestSensitivityClassification:
    """Tests for _classify_field_sensitivity()."""

    def test_health_field_is_tier_3(self) -> None:
        """Field named 'heart_rate' should classify as tier 3."""
        tier, source = _classify_field_sensitivity("heart_rate", [72, 68])
        assert tier == 3
        assert source == "keyword_match"

    def test_financial_field_is_tier_3(self) -> None:
        """Field named 'salary' should classify as tier 3."""
        tier, source = _classify_field_sensitivity("salary", [75000])
        assert tier == 3
        assert source == "keyword_match"

    def test_email_field_is_tier_2(self) -> None:
        """Field named 'email_address' should classify as tier 2."""
        tier, source = _classify_field_sensitivity("email_address", ["a@b.com"])
        assert tier == 2
        assert source == "keyword_match"

    def test_name_field_is_tier_2(self) -> None:
        """Field named 'sender_name' should classify as tier 2."""
        tier, source = _classify_field_sensitivity("sender_name", ["Alice"])
        assert tier == 2
        assert source == "keyword_match"

    def test_title_field_is_tier_1(self) -> None:
        """Field named 'title' should classify as tier 1."""
        tier, source = _classify_field_sensitivity("title", ["Meeting notes"])
        assert tier == 1
        assert source == "default"

    def test_id_field_is_tier_1(self) -> None:
        """Field named 'id' should classify as tier 1."""
        tier, source = _classify_field_sensitivity("id", ["abc-123"])
        assert tier == 1
        assert source == "default"

    def test_value_content_promotes_tier(self) -> None:
        """Tier-1 name but dollar amount in value should promote to tier 3."""
        tier, source = _classify_field_sensitivity(
            "notes", ["Payment of $5,000 received"],
        )
        assert tier == 3
        assert source == "value_scan"

    def test_conservative_max_wins(self) -> None:
        """When name is tier-2 and value is tier-3, tier 3 wins."""
        tier, _ = _classify_field_sensitivity(
            "sender_name", ["SSN: 123-45-6789"],
        )
        assert tier == 3


# ---------------------------------------------------------------------------
# TestTableMatching
# ---------------------------------------------------------------------------


class TestTableMatching:
    """Tests for _find_best_table_match() and _compute_jaccard()."""

    def test_jaccard_identical_sets(self) -> None:
        """Identical sets should have Jaccard = 1.0."""
        assert _compute_jaccard({"a", "b", "c"}, {"a", "b", "c"}) == 1.0

    def test_jaccard_disjoint_sets(self) -> None:
        """Disjoint sets should have Jaccard = 0.0."""
        assert _compute_jaccard({"a", "b"}, {"c", "d"}) == 0.0

    def test_exact_field_match_scores_high(
        self, existing_tables: dict[str, list[str]],
    ) -> None:
        """Fields matching raw_messages columns exactly should score high."""
        source = {"id", "sender", "recipient", "content", "timestamp", "source"}
        table, score = _find_best_table_match(source, existing_tables)
        assert table == "raw_messages"
        assert score > 0.4

    def test_no_match_below_threshold(
        self, existing_tables: dict[str, list[str]],
    ) -> None:
        """Completely different fields should return None."""
        source = {"recipe_name", "cuisine", "prep_minutes", "cook_minutes"}
        table, _score = _find_best_table_match(source, existing_tables)
        assert table is None

    def test_normalized_names_match(
        self, existing_tables: dict[str, list[str]],
    ) -> None:
        """CamelCase source fields should match snake_case table columns."""
        source = {"id", "startTime", "endTime", "location", "attendees", "title"}
        table, score = _find_best_table_match(source, existing_tables)
        assert table == "raw_calendar_events"
        assert score > 0.3


# ---------------------------------------------------------------------------
# TestColumnNormalization
# ---------------------------------------------------------------------------


class TestColumnNormalization:
    """Tests for _normalize_column_name()."""

    def test_camel_case_to_snake(self) -> None:
        """CamelCase should convert to snake_case."""
        assert _normalize_column_name("startTime") == "start_time"

    def test_hyphens_to_underscores(self) -> None:
        """Hyphens should convert to underscores."""
        assert _normalize_column_name("body-preview") == "body_preview"

    def test_dots_to_underscores(self) -> None:
        """Dots should convert to underscores."""
        assert _normalize_column_name("user.name") == "user_name"

    def test_already_snake_case_unchanged(self) -> None:
        """Already snake_case should remain unchanged."""
        assert _normalize_column_name("start_time") == "start_time"


# ---------------------------------------------------------------------------
# TestNestedFieldDetection
# ---------------------------------------------------------------------------


class TestNestedFieldDetection:
    """Tests for _detect_nested_fields()."""

    def test_consistent_nested_keys_flattened(self) -> None:
        """Nested objects with consistent keys should be detected for flattening."""
        records = _make_nested_records()
        result = _detect_nested_fields(records)
        assert len(result) == 1
        parent, children = result[0]
        assert parent == "author"
        assert set(children) == {"email", "name"}

    def test_variable_nested_keys_not_flattened(self) -> None:
        """Nested objects with highly variable keys should not be flattened."""
        records = [
            {"id": "1", "meta": {"foo": 1}},
            {"id": "2", "meta": {"bar": 2, "baz": 3}},
            {"id": "3", "meta": {"qux": 4, "quux": 5, "corge": 6}},
        ]
        result = _detect_nested_fields(records)
        assert len(result) == 0

    def test_deep_nesting_becomes_json(self) -> None:
        """Objects with nested dicts inside should not be flattened."""
        records = [
            {"id": "1", "data": {"inner": {"deep": "value"}}},
            {"id": "2", "data": {"inner": {"deep": "other"}}},
        ]
        result = _detect_nested_fields(records)
        assert len(result) == 0


# ---------------------------------------------------------------------------
# TestDedupKeyDetection
# ---------------------------------------------------------------------------


class TestDedupKeyDetection:
    """Tests for _detect_dedup_key()."""

    def test_id_field_detected(self) -> None:
        """Records with unique 'id' field should use it as dedup key."""
        records = [{"id": "a"}, {"id": "b"}, {"id": "c"}]
        result = _detect_dedup_key(["id"], records)
        assert "id" in result

    def test_id_plus_source_detected(self) -> None:
        """Both 'id' and 'source' present should return both."""
        records = [
            {"id": "a", "source": "x"},
            {"id": "b", "source": "y"},
        ]
        result = _detect_dedup_key(["id", "source"], records)
        assert "id" in result
        assert "source" in result

    def test_no_id_falls_back_to_heuristic(self) -> None:
        """Without 'id', should use timestamp + unique string field."""
        records = [
            {"title": "A", "created_at": "2025-01-01"},
            {"title": "B", "created_at": "2025-01-02"},
            {"title": "C", "created_at": "2025-01-03"},
        ]
        result = _detect_dedup_key(["title", "created_at"], records)
        assert len(result) > 0


# ---------------------------------------------------------------------------
# TestDomainClassification
# ---------------------------------------------------------------------------


class TestDomainClassification:
    """Tests for _classify_domain()."""

    def test_message_fields_classify_as_messages(self) -> None:
        """Fields with sender/recipient/content should classify as messages."""
        result = _classify_domain(
            "get_messages",
            ["sender", "recipient", "content", "timestamp"],
            "Get recent messages",
        )
        assert result == "messages"

    def test_health_fields_classify_as_health(self) -> None:
        """Fields with heart_rate/calories should classify as health."""
        result = _classify_domain(
            "get_health_data",
            ["heart_rate", "steps", "calories", "recorded_at"],
            "Get health metrics",
        )
        assert result == "health"

    def test_tool_name_influences_domain(self) -> None:
        """Tool name containing 'email' should influence domain classification."""
        result = _classify_domain(
            "list_emails",
            ["id", "subject", "from", "body_preview"],
            "List recent emails",
        )
        assert result == "email"

    def test_unknown_defaults_to_general(self) -> None:
        """Completely novel fields should default to 'general'."""
        result = _classify_domain(
            "get_recipes",
            ["recipe_name", "cuisine", "prep_minutes"],
            "Get recipes",
        )
        assert result == "general"


# ---------------------------------------------------------------------------
# TestScheduleSuggestion
# ---------------------------------------------------------------------------


class TestScheduleSuggestion:
    """Tests for _suggest_schedule()."""

    def test_messages_every_15min(self) -> None:
        """Messages domain should suggest every_15min."""
        assert _suggest_schedule("messages") == "every_15min"

    def test_health_hourly(self) -> None:
        """Health domain should suggest hourly."""
        assert _suggest_schedule("health") == "hourly"

    def test_general_daily(self) -> None:
        """General domain should suggest daily."""
        assert _suggest_schedule("general") == "daily"


# ---------------------------------------------------------------------------
# TestRuleBasedPass
# ---------------------------------------------------------------------------


class TestRuleBasedPass:
    """Tests for the full rule-based analysis pass."""

    def test_message_records_map_to_raw_messages(
        self, agent: SchemaDiscoveryAgent,
    ) -> None:
        """Message records should map to raw_messages table."""
        result = agent.discover("list_messages", _make_message_records())
        assert result.target_table == "raw_messages"
        assert not result.is_new_table
        assert result.analysis_method == "rules_only"
        assert result.domain == "messages"

    def test_calendar_records_map_to_raw_calendar_events(
        self, agent: SchemaDiscoveryAgent,
    ) -> None:
        """Calendar records should map to raw_calendar_events table."""
        result = agent.discover("list_calendar_events", _make_calendar_records())
        assert result.target_table == "raw_calendar_events"
        assert not result.is_new_table

    def test_unknown_records_create_new_table(
        self, agent: SchemaDiscoveryAgent,
    ) -> None:
        """Novel data should suggest a new table."""
        result = agent.discover("list_recipes", _make_unknown_records())
        assert result.is_new_table
        assert result.target_table.startswith("raw_")

    def test_all_fields_have_sensitivity_tier(
        self, agent: SchemaDiscoveryAgent,
    ) -> None:
        """Every field mapping must have a valid sensitivity tier."""
        result = agent.discover("list_messages", _make_message_records())
        for field in result.fields:
            assert field.sensitivity_tier in (1, 2, 3)

    def test_health_records_high_sensitivity(
        self, agent: SchemaDiscoveryAgent,
    ) -> None:
        """Health records should have tier 3 fields."""
        result = agent.discover("get_health_metrics", _make_health_records())
        tier_3_fields = [f for f in result.fields if f.sensitivity_tier == 3]
        assert len(tier_3_fields) > 0, "Health data should have tier 3 fields"


# ---------------------------------------------------------------------------
# TestLLMFallback
# ---------------------------------------------------------------------------


def _sb_draft(
    *,
    target_table: str = "raw_general",
    is_new_table: bool = False,
    domain: str = "general",
    fields: list[dict] | None = None,
    dedup_key: list[str] | None = None,
):
    """Build a :class:`SchemaDiscoveryDraft` fixture for the SBAgent stub."""
    from src.agents.core.output_types import (
        FieldMappingDraft,
        SchemaDiscoveryDraft,
    )
    return SchemaDiscoveryDraft(
        target_table=target_table,
        is_new_table=is_new_table,
        domain=domain,
        fields=[FieldMappingDraft(**f) for f in (fields or [])],
        dedup_key=dedup_key or ["id"],
    )


class TestLLMFallback:
    """Tests for the LLM (now :class:`SchemaDiscoveryAgent` SBAgent) fallback."""

    def test_llm_called_when_confidence_low(
        self, stub_schema_sbagent,
    ) -> None:
        """SBAgent should be called when rule-based confidence is low."""
        stub_schema_sbagent.return_value = _sb_draft(
            target_table="raw_general", fields=[],
        )
        agent = SchemaDiscoveryAgent(
            existing_tables=_existing_table_schemas(),
            confidence_threshold=0.99,  # Force LLM trigger
        )
        agent.discover("list_stuff", _make_unknown_records())
        stub_schema_sbagent.assert_called_once()

    def test_llm_not_called_when_confidence_high(
        self, stub_schema_sbagent,
    ) -> None:
        """SBAgent should NOT be called when confidence is high enough."""
        agent = SchemaDiscoveryAgent(
            existing_tables=_existing_table_schemas(),
            confidence_threshold=0.01,  # Very low threshold
        )
        agent.discover("list_messages", _make_message_records())
        stub_schema_sbagent.assert_not_called()

    def test_llm_failure_falls_back_to_rule_based(
        self, stub_schema_sbagent,
    ) -> None:
        """When SBAgent raises, fall back to rule-based with a warning."""
        stub_schema_sbagent.side_effect = ConnectionError(
            "agent unavailable",
        )
        agent = SchemaDiscoveryAgent(
            existing_tables=_existing_table_schemas(),
            confidence_threshold=0.99,  # Force LLM trigger
        )
        result = agent.discover("list_stuff", _make_unknown_records())
        assert result.analysis_method == "rules_only"
        assert any("LLM unavailable" in w for w in result.warnings)

    def test_llm_response_merged_correctly(
        self, stub_schema_sbagent,
    ) -> None:
        """Valid SBAgent draft is merged with the rule-based result."""
        stub_schema_sbagent.return_value = _sb_draft(
            target_table="raw_general",
            is_new_table=True,
            domain="general",
            fields=[{
                "source_name": "recipe_name",
                "target_column": "recipe_name",
                "target_type": "VARCHAR",
                "sensitivity_tier": 1,
            }],
        )
        agent = SchemaDiscoveryAgent(
            existing_tables=_existing_table_schemas(),
            confidence_threshold=0.99,
        )
        result = agent.discover("list_recipes", _make_unknown_records())
        assert result.analysis_method == "rules_plus_llm"

    def test_llm_sensitivity_never_lowered(
        self, stub_schema_sbagent,
    ) -> None:
        """The SBAgent cannot lower a sensitivity tier set by rules."""
        stub_schema_sbagent.return_value = _sb_draft(
            target_table="raw_health_metrics",
            fields=[{
                "source_name": "heart_rate",
                "target_column": "heart_rate",
                "target_type": "INTEGER",
                "sensitivity_tier": 1,
            }],
        )
        records = [
            {"id": "1", "heart_rate": 72, "source": "health"},
            {"id": "2", "heart_rate": 68, "source": "health"},
        ]
        agent = SchemaDiscoveryAgent(
            existing_tables=_existing_table_schemas(),
            confidence_threshold=0.99,  # Always trigger LLM
        )
        result = agent.discover("get_health", records)

        heart_field = next(
            (f for f in result.fields if f.source_name == "heart_rate"),
            None,
        )
        assert heart_field is not None
        assert heart_field.sensitivity_tier == 3, \
            "SBAgent should not lower sensitivity tier from 3 to 1"


# ---------------------------------------------------------------------------
# TestMergeStrategy
# ---------------------------------------------------------------------------


class TestMergeStrategy:
    """Tests for the LLM merge strategy."""

    def test_llm_can_upgrade_sensitivity_tier(
        self, stub_schema_sbagent,
    ) -> None:
        """SBAgent suggesting a higher tier is accepted."""
        stub_schema_sbagent.return_value = _sb_draft(
            target_table="raw_general",
            fields=[{
                "source_name": "cuisine",
                "target_column": "cuisine",
                "target_type": "VARCHAR",
                "sensitivity_tier": 2,
            }],
        )
        agent = SchemaDiscoveryAgent(
            existing_tables=_existing_table_schemas(),
            confidence_threshold=0.99,
        )
        result = agent.discover("list_recipes", _make_unknown_records())

        cuisine_field = next(
            (f for f in result.fields if f.source_name == "cuisine"),
            None,
        )
        assert cuisine_field is not None
        assert cuisine_field.sensitivity_tier >= 2

    def test_llm_cannot_downgrade_sensitivity_tier(
        self, stub_schema_sbagent,
    ) -> None:
        """SBAgent suggesting a lower tier is ignored."""
        stub_schema_sbagent.return_value = _sb_draft(
            target_table="raw_messages",
            fields=[{
                "source_name": "sender",
                "target_column": "sender",
                "target_type": "VARCHAR",
                "sensitivity_tier": 1,  # Rules say 2
            }],
        )
        agent = SchemaDiscoveryAgent(
            existing_tables=_existing_table_schemas(),
            confidence_threshold=0.99,
        )
        result = agent.discover("list_messages", _make_message_records())

        sender_field = next(
            (f for f in result.fields if f.source_name == "sender"),
            None,
        )
        assert sender_field is not None
        assert sender_field.sensitivity_tier >= 2

    def test_missing_llm_fields_preserved_from_rule_based(
        self, stub_schema_sbagent,
    ) -> None:
        """Fields omitted by the SBAgent still appear from the rule pass."""
        stub_schema_sbagent.return_value = _sb_draft(
            target_table="raw_messages",
            fields=[{
                "source_name": "id",
                "target_column": "id",
                "target_type": "VARCHAR",
                "sensitivity_tier": 1,
            }],
        )
        agent = SchemaDiscoveryAgent(
            existing_tables=_existing_table_schemas(),
            confidence_threshold=0.99,
        )
        result = agent.discover("list_messages", _make_message_records())
        field_names = {f.source_name for f in result.fields}
        assert "sender" in field_names, \
            "Rule-based fields should be preserved"

    def test_llm_target_table_override_accepted(
        self, stub_schema_sbagent,
    ) -> None:
        """SBAgent suggesting a different valid table is accepted."""
        stub_schema_sbagent.return_value = _sb_draft(
            target_table="raw_notes", fields=[],
        )
        agent = SchemaDiscoveryAgent(
            existing_tables=_existing_table_schemas(),
            confidence_threshold=0.99,
        )
        result = agent.discover(
            "get_documents", _make_unknown_records(),
        )
        assert result.target_table == "raw_notes"


# ---------------------------------------------------------------------------
# TestEdgeCases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    """Tests for edge cases and error handling."""

    def test_empty_records_raises_value_error(
        self, agent: SchemaDiscoveryAgent,
    ) -> None:
        """Empty sample records should raise ValueError."""
        with pytest.raises(ValueError, match="at least one record"):
            agent.discover("test_tool", [])

    def test_single_record_works(
        self, agent: SchemaDiscoveryAgent,
    ) -> None:
        """A single sample record should be sufficient."""
        result = agent.discover("test_tool", [{"id": "1", "title": "Test"}])
        assert len(result.fields) > 0

    def test_records_with_all_none_values(
        self, agent: SchemaDiscoveryAgent,
    ) -> None:
        """Fields with all None values should default to string/VARCHAR."""
        result = agent.discover(
            "test_tool",
            [{"id": "1", "unknown": None}, {"id": "2", "unknown": None}],
        )
        unknown_field = next(
            (f for f in result.fields if f.source_name == "unknown"), None,
        )
        assert unknown_field is not None
        assert unknown_field.source_type == "string"
        assert unknown_field.target_type in ("TEXT", "VARCHAR")

    def test_sparse_records_use_union_of_keys(
        self, agent: SchemaDiscoveryAgent,
    ) -> None:
        """Records with different keys should use the union of all keys."""
        result = agent.discover(
            "test_tool",
            [
                {"id": "1", "name": "Alice"},
                {"id": "2", "email": "bob@test.com"},
                {"id": "3", "name": "Carol", "email": "carol@test.com"},
            ],
        )
        field_names = {f.source_name for f in result.fields}
        assert "id" in field_names
        assert "name" in field_names
        assert "email" in field_names


# ---------------------------------------------------------------------------
# TestToToolTemplate
# ---------------------------------------------------------------------------


class TestToToolTemplate:
    """Tests for to_tool_template() converter."""

    def test_conversion_produces_valid_tool_template(
        self, agent: SchemaDiscoveryAgent,
    ) -> None:
        """DiscoveredMapping should convert to a valid ToolTemplate."""
        mapping = agent.discover("list_messages", _make_message_records())
        template = to_tool_template(mapping)
        assert template.tool_name == "list_messages"
        assert template.tool_type == "data"
        assert template.target_table == mapping.target_table
        assert len(template.fields) == len(mapping.fields)

    def test_conversion_preserves_sensitivity_tiers(
        self, agent: SchemaDiscoveryAgent,
    ) -> None:
        """Converted ToolTemplate should preserve sensitivity tiers."""
        mapping = agent.discover("get_health_metrics", _make_health_records())
        template = to_tool_template(mapping)
        for orig, converted in zip(mapping.fields, template.fields, strict=True):
            assert converted.sensitivity_tier == orig.sensitivity_tier



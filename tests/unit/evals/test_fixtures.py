"""FakeQueryEngine tests.

We verify the per-question keyword matching, the always-match dict
form, and the absent-fixture default. Real ``QueryEngine`` semantics
are exercised elsewhere — here we only check the fixture surface
``BrainAgentV2`` consumes.

sensitivity_tier: N/A
"""

from __future__ import annotations

import pytest

# Importing the fixture pulls in QueryContext only when .query() is
# called, so this module is importable without the full project deps.
from evals.fixtures import FakeQueryEngine


def test_fixture_none_returns_empty_context() -> None:
    pytest.importorskip("src.core.query_engine")
    engine = FakeQueryEngine(None)
    ctx = engine.query("anything?")
    assert ctx.vector_results == []
    assert ctx.structured_data == []
    assert ctx.graph_context == []
    assert ctx.question == "anything?"


def test_fixture_dict_always_matches() -> None:
    pytest.importorskip("src.core.query_engine")
    engine = FakeQueryEngine({
        "structured_data": [
            {"table": "raw_messages", "rows": [{"content": "hi"}]},
        ],
    })
    ctx = engine.query("totally unrelated")
    assert len(ctx.structured_data) == 1


def test_fixture_list_filters_by_match() -> None:
    pytest.importorskip("src.core.query_engine")
    engine = FakeQueryEngine([
        {
            "match": "renovation",
            "structured_data": [
                {"table": "raw_messages", "rows": [{"id": 1}]},
            ],
        },
        {
            "match": "schedule",
            "structured_data": [
                {"table": "raw_calendar_events", "rows": [{"id": 2}]},
            ],
        },
    ])
    ctx_a = engine.query("Tell me about the renovation timeline")
    ctx_b = engine.query("What's on my schedule today?")
    ctx_c = engine.query("Cookbook recipes")
    assert len(ctx_a.structured_data) == 1
    assert ctx_a.structured_data[0]["source_table"] == "raw_messages"
    assert len(ctx_b.structured_data) == 1
    assert ctx_b.structured_data[0]["source_table"] == "raw_calendar_events"
    assert ctx_c.structured_data == []


def test_fixture_match_is_case_insensitive() -> None:
    pytest.importorskip("src.core.query_engine")
    engine = FakeQueryEngine([
        {"match": "RENO", "structured_data": [{"hit": True}]},
    ])
    assert len(engine.query("major renovation").structured_data) == 1


def test_fixture_exposes_none_duck() -> None:
    engine = FakeQueryEngine(None)
    assert engine._duck is None


def test_grouped_rows_flatten_with_source_table() -> None:
    """The convenience ``{table, rows: [...]}`` form must flatten to
    the same row shape ``QueryEngine.query`` returns, so
    ``format_context`` can label sources and populate
    ``BrainResponse.sources``.
    """
    from evals.fixtures import _flatten_structured

    rows = _flatten_structured([
        {
            "table": "raw_messages",
            "rows": [
                {"content": "hi", "sender_name": "Mom"},
                {"content": "yo", "sender_name": "Sam"},
            ],
        },
    ])
    assert len(rows) == 2
    assert all(r["source_table"] == "raw_messages" for r in rows)
    assert all("sensitivity_tier" in r for r in rows)
    assert all("id" in r for r in rows)
    assert rows[0]["id"] != rows[1]["id"]


def test_flat_rows_pass_through_with_defaults() -> None:
    from evals.fixtures import _flatten_structured

    rows = _flatten_structured([
        {"source_table": "raw_messages", "id": "m1", "content": "hi"},
    ])
    assert rows == [
        {
            "source_table": "raw_messages",
            "sensitivity_tier": 2,
            "id": "m1",
            "content": "hi",
        },
    ]


def test_flat_rows_accept_table_alias() -> None:
    from evals.fixtures import _flatten_structured

    rows = _flatten_structured([{"table": "raw_emails", "id": "e1"}])
    assert rows[0]["source_table"] == "raw_emails"

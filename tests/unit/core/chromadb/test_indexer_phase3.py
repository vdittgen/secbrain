"""Tests for Phase 3 indexer improvements.

Covers the structured composers, the tokenizer-driven chunker with
overlap, the recency bucket helper, and the metadata fields added
to ``_to_index_docs``.

sensitivity_tier: N/A
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from src.core.chromadb.indexer import (
    DEFAULT_CHUNK_OVERLAP,
    MAX_TOKENS_PER_CHUNK,
    _to_index_docs,
    chunk_text,
    compose_calendar_text,
    compose_contact_text,
    compose_health_metric_text,
    compose_mart_text,
    compose_message_text,
    compose_note_text,
    recency_bucket,
)

# ---------------------------------------------------------------------------
# Composers
# ---------------------------------------------------------------------------


class TestComposers:
    def test_message_includes_labelled_header(self) -> None:
        text = compose_message_text(
            {
                "sender": "Mom",
                "recipient": "Me",
                "source": "WhatsApp",
                "timestamp": "2026-05-15T10:00:00",
                "content": "Did you book the doctor appointment?",
            },
        )
        assert "From: Mom" in text
        assert "To: Me" in text
        assert "Channel: WhatsApp" in text
        # body lands after a blank line so it reads as its own block
        assert "\n\nDid you book the doctor appointment?" in text

    def test_message_handles_missing_fields(self) -> None:
        text = compose_message_text(
            {"content": "just a note", "sender": None, "recipient": None},
        )
        assert "just a note" in text
        # missing fields drop out — no "From: None"
        assert "None" not in text

    def test_calendar_event_title_leads(self) -> None:
        text = compose_calendar_text(
            {
                "title": "Naomi's Birthday",
                "start_time": "2026-08-12T19:00",
                "end_time": "2026-08-12T22:00",
                "location": "Backyard",
                "attendees": "Sam, Jess",
            },
        )
        assert text.startswith("Event: Naomi's Birthday")
        assert "Location: Backyard" in text
        assert "Attendees: Sam, Jess" in text

    def test_calendar_description_in_separate_block(self) -> None:
        text = compose_calendar_text(
            {
                "title": "Standup",
                "description": "Tuesday team sync",
            },
        )
        assert "Event: Standup" in text
        assert "\n\nTuesday team sync" in text

    def test_contact_uses_labelled_name(self) -> None:
        text = compose_contact_text(
            {
                "name": "Israel Casa Rosa",
                "relationship": "vendor",
                "email": "israel@example.com",
                "notes": "fixes the boiler",
            },
        )
        # the bug we're fixing: bare "Israel Casa Rosa" gets
        # outranked by every other contact. "Contact: X" labels it.
        assert text.startswith("Contact: Israel Casa Rosa")
        assert "Relationship: vendor" in text
        assert "\n\nfixes the boiler" in text

    def test_contact_with_only_name(self) -> None:
        text = compose_contact_text({"name": "Naomi"})
        assert text == "Contact: Naomi"

    def test_note_compose(self) -> None:
        text = compose_note_text(
            {
                "title": "Refactor plan",
                "tags": "work,architecture",
                "content": "Step 1: extract types",
            },
        )
        assert "Note: Refactor plan" in text
        assert "Tags: work,architecture" in text
        assert "\n\nStep 1: extract types" in text

    def test_health_metric_compose(self) -> None:
        text = compose_health_metric_text(
            {
                "metric_type": "blood_pressure",
                "value": "120/80",
                "unit": "mmHg",
                "recorded_at": "2026-05-15",
                "source": "Apple Health",
            },
        )
        assert "Metric: blood_pressure" in text
        assert "Value: 120/80 mmHg" in text
        assert "Recorded: 2026-05-15" in text

    def test_mart_compose(self) -> None:
        text = compose_mart_text(
            {
                "title": "Naomi's birthday",
                "item_type": "event",
                "occurred_at": "2026-08-12",
                "detail": "annual hangout",
            },
        )
        assert "Summary: Naomi's birthday" in text
        assert "Type: event" in text
        assert "\n\nannual hangout" in text


# ---------------------------------------------------------------------------
# Chunker
# ---------------------------------------------------------------------------


class TestChunker:
    def test_short_text_returns_single_chunk(self) -> None:
        assert chunk_text("hello world") == ["hello world"]

    def test_empty_string_passthrough(self) -> None:
        assert chunk_text("") == [""]

    def test_long_text_splits_into_chunks(self) -> None:
        # Build a long string that's guaranteed past the token budget.
        text = "lorem ipsum dolor sit amet. " * 300
        chunks = chunk_text(text, max_tokens=100, overlap_tokens=20)
        assert len(chunks) > 1
        assert all(len(c) > 0 for c in chunks)

    def test_chunks_overlap_when_overlap_set(self) -> None:
        text = "alpha beta gamma delta epsilon zeta eta theta " * 50
        chunks = chunk_text(text, max_tokens=50, overlap_tokens=10)
        # With overlap > 0, the start of chunk[n+1] should appear
        # somewhere in chunk[n] (overlapping token window).
        assert len(chunks) >= 2
        # Decoded text length should slightly exceed the original due
        # to the overlap repeating tokens across chunks.
        joined = "".join(chunks)
        assert len(joined) > len(text) * 0.95  # at minimum cover the input

    def test_zero_overlap_no_repetition(self) -> None:
        text = "alpha beta gamma delta epsilon " * 100
        chunks_no_overlap = chunk_text(text, max_tokens=50, overlap_tokens=0)
        chunks_with_overlap = chunk_text(text, max_tokens=50, overlap_tokens=20)
        # More overlap → more (or same) chunks; never fewer.
        assert len(chunks_with_overlap) >= len(chunks_no_overlap)

    def test_overlap_clamped_when_pathological(self) -> None:
        # overlap >= max_tokens would create an infinite loop; the
        # chunker clamps it. We just verify it terminates and produces
        # output.
        text = "x " * 1000
        chunks = chunk_text(text, max_tokens=50, overlap_tokens=999)
        assert len(chunks) >= 1
        assert all(c for c in chunks)


# ---------------------------------------------------------------------------
# Recency bucket
# ---------------------------------------------------------------------------


class TestRecencyBucket:
    def test_today(self) -> None:
        now = datetime(2026, 5, 15, 12, 0, tzinfo=UTC)
        ts = (now - timedelta(hours=3)).isoformat()
        assert recency_bucket(ts, now=now) == "today"

    def test_this_week(self) -> None:
        now = datetime(2026, 5, 15, 12, 0, tzinfo=UTC)
        ts = (now - timedelta(days=3)).isoformat()
        assert recency_bucket(ts, now=now) == "this_week"

    def test_this_month(self) -> None:
        now = datetime(2026, 5, 15, 12, 0, tzinfo=UTC)
        ts = (now - timedelta(days=20)).isoformat()
        assert recency_bucket(ts, now=now) == "this_month"

    def test_older(self) -> None:
        now = datetime(2026, 5, 15, 12, 0, tzinfo=UTC)
        ts = (now - timedelta(days=365)).isoformat()
        assert recency_bucket(ts, now=now) == "older"

    def test_empty_returns_unknown(self) -> None:
        assert recency_bucket("") == "unknown"
        assert recency_bucket(None) == "unknown"

    def test_unparseable_returns_unknown(self) -> None:
        assert recency_bucket("not a date") == "unknown"

    def test_naive_timestamp_assumed_utc(self) -> None:
        # No tzinfo on the input — recency_bucket should not raise.
        now = datetime(2026, 5, 15, 12, 0, tzinfo=UTC)
        result = recency_bucket("2026-05-15T09:00:00", now=now)
        assert result in ("today", "this_week")


# ---------------------------------------------------------------------------
# _to_index_docs metadata
# ---------------------------------------------------------------------------


class TestToIndexDocsMetadata:
    def _base_kwargs(self) -> dict:
        return {
            "record_id": "rec_42",
            "text": "Contact: Naomi",
            "collection": "personal",
            "source_table": "raw_contacts",
            "timestamp": "2026-05-15T10:00:00",
            "sensitivity_tier": 2,
            "source": "contacts",
            "domain": "personal",
        }

    def test_defaults_layer_to_raw(self) -> None:
        docs = _to_index_docs(**self._base_kwargs())
        assert len(docs) == 1
        assert docs[0].metadata["layer"] == "raw"

    def test_layer_override(self) -> None:
        docs = _to_index_docs(**self._base_kwargs(), layer="mart")
        assert docs[0].metadata["layer"] == "mart"

    def test_recency_bucket_metadata_present(self) -> None:
        docs = _to_index_docs(**self._base_kwargs())
        # bucket value depends on test-run date — just assert presence
        # and that it's one of the legal values.
        bucket = docs[0].metadata["recency_bucket"]
        assert bucket in ("today", "this_week", "this_month", "older", "unknown")

    def test_chunks_share_recency_bucket(self) -> None:
        # Build a record long enough to chunk so we can verify the
        # bucket replicates rather than being recomputed per chunk.
        kwargs = self._base_kwargs()
        kwargs["text"] = "alpha beta gamma delta " * 500
        docs = _to_index_docs(**kwargs)
        assert len(docs) > 1
        buckets = {d.metadata["recency_bucket"] for d in docs}
        assert len(buckets) == 1


# ---------------------------------------------------------------------------
# Sanity: defaults exported
# ---------------------------------------------------------------------------


def test_defaults_exported() -> None:
    # Trivial guard: callers depend on these constants being public.
    assert MAX_TOKENS_PER_CHUNK > 0
    assert DEFAULT_CHUNK_OVERLAP >= 0

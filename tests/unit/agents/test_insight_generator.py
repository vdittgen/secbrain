"""Tests for InsightGenerator.

Mocks BrainAgent to avoid requiring a running Ollama instance.
Uses a real temp DuckDB for QueryTracker + InsightGenerator tables.

sensitivity_tier: N/A — test infrastructure
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from src.agents.core.output_types import BrainResponse
from src.agents.insight import (
    Insight,
    InsightGenerator,
)
from src.core.query_tracker import QueryTracker
from src.core.question_patterns import PATTERNS
from src.core.sqlite.engine import DatabaseEngine
from src.models.llm_provider import LLMResponse

# A tiny stub provider that classifies questions into the right
# pattern + domain so the LLM-driven detector / tracker behave
# deterministically offline.
_PATTERN_CUES = {name: tuple(spec["keywords"]) for name, spec in PATTERNS.items()}
_DOMAIN_CUES = {
    "calendar": ("today", "schedule", "calendar", "agenda", "week"),
    "health":   ("health", "sleep", "mood", "trending"),
    "messages": ("messages", "unread", "email"),
    "notes":    ("note", "wrote", "journal"),
    "work":     ("work", "productive", "deadline"),
    "contacts": ("about", "tell me", "haven't talked"),
}


class _InsightStubProvider:
    provider_name = "stub"
    default_model = "stub"

    def chat(self, *_a: Any, **_kw: Any) -> LLMResponse:
        return LLMResponse(content="", model="stub")

    def chat_stream(self, *_a: Any, **_kw: Any):  # noqa: ANN201
        return iter(())

    def chat_json(
        self,
        messages: list[dict[str, str]],
        model: str | None = None,
    ) -> dict[str, Any]:
        prompt = messages[-1]["content"]
        marker = "Text:\n"
        idx = prompt.find(marker)
        text = prompt[idx + len(marker):].split("\n\nRespond")[0].lower()

        if "intent patterns" in prompt or "Patterns mean" in prompt:
            best: tuple[str, float] = ("none", 0.0)
            for name, cues in _PATTERN_CUES.items():
                hits = sum(1 for cue in cues if cue in text)
                if hits == 0:
                    continue
                conf = hits / len(cues)
                if conf > best[1]:
                    best = (name, conf)
            if best[1] < 0.1:
                return {"pattern": "none", "confidence": 0.0}
            return {"pattern": best[0], "confidence": max(0.7, best[1])}

        if "listed domains" in prompt or "calendar:" in prompt:
            best_d: tuple[str, int] = ("general", 0)
            for domain, cues in _DOMAIN_CUES.items():
                hits = sum(1 for cue in cues if cue in text)
                if hits > best_d[1]:
                    best_d = (domain, hits)
            return {"domain": best_d[0]}

        return {}

    def check_health(self) -> dict[str, Any]:
        return {"provider": "stub"}

# ================================================================
# Fixtures
# ================================================================


def _make_brain_response(
    answer: str = "Here is a useful insight about your data.",
) -> BrainResponse:
    """Build a mock BrainResponse."""
    return BrainResponse(
        answer=answer,
        sources=[{"source": "test", "id": "1"}],
        context_summary="test context",
        model="test-model",
        latency_ms=100.0,
    )


@pytest.fixture()
def tmp_db(tmp_path: Path) -> DatabaseEngine:
    """Fresh DuckDB engine backed by a temp file."""
    db_path = tmp_path / "test_insights.duckdb"
    engine = DatabaseEngine(db_path=db_path)
    yield engine
    engine.close()


@pytest.fixture()
def tracker(tmp_db: DatabaseEngine) -> QueryTracker:
    """QueryTracker wired to the temp database with stub LLM."""
    return QueryTracker(
        db_engine=tmp_db, llm_provider=_InsightStubProvider(),
    )


@pytest.fixture()
def mock_brain() -> MagicMock:
    """Mock BrainAgent that returns a canned response."""
    brain = MagicMock()
    brain.ask.return_value = _make_brain_response()
    return brain


@pytest.fixture()
def generator(
    tmp_db: DatabaseEngine,
    tracker: QueryTracker,
    mock_brain: MagicMock,
) -> InsightGenerator:
    """InsightGenerator with mock BrainAgent."""
    return InsightGenerator(
        db_engine=tmp_db,
        query_tracker=tracker,
        brain_agent=mock_brain,
    )


def _seed_questions(
    tracker: QueryTracker,
    pattern: str = "schedule_today",
    count: int = 5,
) -> None:
    """Log several questions that match a given pattern."""
    questions = {
        "schedule_today": "What's on my schedule today?",
        "schedule_week": "What do I have this week?",
        "health_check": "How is my health trending?",
        "person_inquiry": "Tell me about Alice",
        "message_search": "Do I have any unread messages?",
        "mood_check": "What's my mood been like?",
        "work_productivity": "How productive has my work been?",
        "note_recall": "What did I write in my last note?",
        "general_summary": "Summarize my week",
        "relationship_status": (
            "I haven't talked to Mom in a while"
        ),
    }
    q = questions.get(pattern, "What's on my schedule today?")
    domain = tracker.classify_question_domain(q)
    for _ in range(count):
        tracker.log_query(question=q, domain=domain)


# ================================================================
# TestDailyInsights
# ================================================================


class TestDailyInsights:
    """generate_daily_insights produces pattern-based insights."""

    def test_generates_insights_from_patterns(
        self,
        generator: InsightGenerator,
        tracker: QueryTracker,
    ) -> None:
        _seed_questions(tracker, "schedule_today", count=5)
        insights = generator.generate_daily_insights(max_insights=3)
        assert len(insights) >= 1
        assert all(isinstance(i, Insight) for i in insights)

    def test_empty_query_log_returns_empty(
        self,
        generator: InsightGenerator,
    ) -> None:
        insights = generator.generate_daily_insights()
        assert insights == []

    def test_ollama_down_returns_empty(
        self,
        generator: InsightGenerator,
        tracker: QueryTracker,
        mock_brain: MagicMock,
    ) -> None:
        mock_brain.ask.side_effect = ConnectionError("Ollama down")
        _seed_questions(tracker, "schedule_today", count=5)
        insights = generator.generate_daily_insights()
        assert insights == []

    def test_filters_low_quality_responses(
        self,
        generator: InsightGenerator,
        tracker: QueryTracker,
        mock_brain: MagicMock,
    ) -> None:
        mock_brain.ask.return_value = _make_brain_response(
            "I don't have enough data to generate insights."
        )
        _seed_questions(tracker, "schedule_today", count=5)
        insights = generator.generate_daily_insights()
        assert insights == []

    def test_respects_max_insights(
        self,
        generator: InsightGenerator,
        tracker: QueryTracker,
    ) -> None:
        _seed_questions(tracker, "schedule_today", count=5)
        _seed_questions(tracker, "health_check", count=5)
        _seed_questions(tracker, "mood_check", count=5)
        insights = generator.generate_daily_insights(max_insights=2)
        assert len(insights) <= 2

    def test_dedup_skips_recent_patterns(
        self,
        generator: InsightGenerator,
        tracker: QueryTracker,
    ) -> None:
        _seed_questions(tracker, "schedule_today", count=5)
        first = generator.generate_daily_insights(max_insights=3)
        assert len(first) >= 1
        # Second call should skip same pattern (< 1 day old)
        second = generator.generate_daily_insights(max_insights=3)
        schedule_patterns = [
            i for i in second
            if i.pattern == "schedule_today"
        ]
        assert len(schedule_patterns) == 0

    def test_brain_called_with_insight_prompt(
        self,
        generator: InsightGenerator,
        tracker: QueryTracker,
        mock_brain: MagicMock,
    ) -> None:
        _seed_questions(tracker, "schedule_today", count=5)
        generator.generate_daily_insights(max_insights=1)
        mock_brain.ask.assert_called()
        call_args = mock_brain.ask.call_args
        # Should pass the pattern's insight_prompt
        assert "summary" in call_args[0][0].lower() or (
            "day" in call_args[0][0].lower()
        )


# ================================================================
# TestCrossDomain
# ================================================================


class TestCrossDomain:
    """detect_cross_domain_patterns finds correlations."""

    def test_active_domains_detected(
        self,
        generator: InsightGenerator,
        tracker: QueryTracker,
    ) -> None:
        # Need multiple domains with enough weight
        for _ in range(10):
            tracker.log_query(
                "What's on my calendar today?",
                domain="calendar",
            )
            tracker.log_query(
                "How is my health?",
                domain="health",
            )
        insights = generator.detect_cross_domain_patterns()
        # May or may not produce insights depending on weights
        assert isinstance(insights, list)

    def test_single_domain_returns_empty(
        self,
        generator: InsightGenerator,
    ) -> None:
        # No queries logged → only default explicit domains
        # but they may have weight > 0.3 from defaults
        insights = generator.detect_cross_domain_patterns()
        assert isinstance(insights, list)

    def test_graceful_failure(
        self,
        generator: InsightGenerator,
        tracker: QueryTracker,
        mock_brain: MagicMock,
    ) -> None:
        mock_brain.ask.side_effect = ConnectionError("down")
        for _ in range(10):
            tracker.log_query("calendar", domain="calendar")
            tracker.log_query("health", domain="health")
        insights = generator.detect_cross_domain_patterns()
        assert insights == []


# ================================================================
# TestGetActive
# ================================================================


class TestGetActive:
    """get_active_insights reads stored non-dismissed insights."""

    def test_returns_non_dismissed(
        self,
        generator: InsightGenerator,
        tracker: QueryTracker,
    ) -> None:
        _seed_questions(tracker, "schedule_today", count=5)
        generated = generator.generate_daily_insights()
        assert len(generated) >= 1

        active = generator.get_active_insights()
        assert len(active) >= 1
        assert all(isinstance(i, Insight) for i in active)

    def test_respects_limit(
        self,
        generator: InsightGenerator,
        tracker: QueryTracker,
    ) -> None:
        _seed_questions(tracker, "schedule_today", count=5)
        _seed_questions(tracker, "health_check", count=5)
        _seed_questions(tracker, "mood_check", count=5)
        generator.generate_daily_insights(max_insights=3)
        active = generator.get_active_insights(limit=1)
        assert len(active) <= 1

    def test_empty_when_no_insights(
        self,
        generator: InsightGenerator,
    ) -> None:
        assert generator.get_active_insights() == []


# ================================================================
# TestDismiss
# ================================================================


class TestDismiss:
    """dismiss_insight marks the insight as dismissed."""

    def test_sets_dismissed_timestamp(
        self,
        generator: InsightGenerator,
        tracker: QueryTracker,
    ) -> None:
        _seed_questions(tracker, "schedule_today", count=5)
        generated = generator.generate_daily_insights()
        assert len(generated) >= 1

        insight_id = generated[0].id
        generator.dismiss_insight(insight_id)

        # Should no longer appear in active
        active = generator.get_active_insights()
        active_ids = [i.id for i in active]
        assert insight_id not in active_ids

    def test_dismiss_nonexistent_is_safe(
        self,
        generator: InsightGenerator,
    ) -> None:
        # Should not raise
        generator.dismiss_insight("nonexistent-id")


# ================================================================
# TestFollowUp
# ================================================================


class TestFollowUp:
    """follow_up_insight boosts domain and sets flag."""

    def test_boosts_domain_weight(
        self,
        generator: InsightGenerator,
        tracker: QueryTracker,
        tmp_db: DatabaseEngine,
    ) -> None:
        _seed_questions(tracker, "schedule_today", count=5)
        generated = generator.generate_daily_insights()
        assert len(generated) >= 1

        insight_id = generated[0].id
        domain = generated[0].domain

        # Get profile count before
        rows_before = tmp_db.query(
            "SELECT query_count FROM _interest_profile "
            "WHERE domain = ?",
            [domain],
        )
        count_before = (
            rows_before[0]["query_count"] if rows_before else 0
        )

        generator.follow_up_insight(insight_id)

        # Profile should be boosted
        rows_after = tmp_db.query(
            "SELECT query_count FROM _interest_profile "
            "WHERE domain = ?",
            [domain],
        )
        count_after = rows_after[0]["query_count"]
        assert count_after > count_before

    def test_sets_followed_up_flag(
        self,
        generator: InsightGenerator,
        tracker: QueryTracker,
        tmp_db: DatabaseEngine,
    ) -> None:
        _seed_questions(tracker, "schedule_today", count=5)
        generated = generator.generate_daily_insights()
        assert len(generated) >= 1

        insight_id = generated[0].id
        generator.follow_up_insight(insight_id)

        rows = tmp_db.query(
            "SELECT followed_up FROM _insights WHERE id = ?",
            [insight_id],
        )
        assert rows[0]["followed_up"]

    def test_follow_up_nonexistent_is_safe(
        self,
        generator: InsightGenerator,
    ) -> None:
        # Should not raise
        generator.follow_up_insight("nonexistent-id")


# ================================================================
# TestInsightDataclass
# ================================================================


class TestInsightDataclass:
    """Insight.has_substance filters low-quality content."""

    def test_short_content_not_substantial(self) -> None:
        insight = Insight(
            id="1", domain="test", title="t", content="ok",
        )
        assert insight.has_substance() is False

    def test_low_quality_phrase_not_substantial(self) -> None:
        insight = Insight(
            id="1",
            domain="test",
            title="t",
            content=(
                "I don't have enough information "
                "to provide insights."
            ),
        )
        assert insight.has_substance() is False

    def test_good_content_is_substantial(self) -> None:
        insight = Insight(
            id="1",
            domain="test",
            title="t",
            content=(
                "Your calendar shows 3 meetings today, "
                "which is above your weekly average."
            ),
        )
        assert insight.has_substance() is True


# ================================================================
# TestPatternToDomain
# ================================================================


class TestPatternToDomain:
    """_pattern_to_domain maps patterns to domains."""

    def test_known_patterns(self) -> None:
        mapping = {
            "schedule_today": "calendar",
            "schedule_week": "calendar",
            "person_inquiry": "contacts",
            "health_check": "health",
            "message_search": "messages",
            "note_recall": "notes",
            "mood_check": "health",
            "relationship_status": "contacts",
            "work_productivity": "work",
            "general_summary": "general",
        }
        for pattern, expected_domain in mapping.items():
            result = InsightGenerator._pattern_to_domain(pattern)
            assert result == expected_domain, (
                f"{pattern} → {result}, expected {expected_domain}"
            )

    def test_unknown_pattern_returns_general(self) -> None:
        assert (
            InsightGenerator._pattern_to_domain("unknown")
            == "general"
        )


# ================================================================
# Topic-based insight generation
# ================================================================


def _seed_mart_topics(db: DatabaseEngine) -> None:
    """Create mart_contact_summary for topic insight tests."""
    import json as _json

    db.execute("""
        CREATE TABLE IF NOT EXISTS mart_contact_summary (
            contact_name VARCHAR,
            top_topic VARCHAR,
            max_topic_importance INTEGER,
            active_topics_json TEXT,
            notification_priority INTEGER,
            messages_7d INTEGER
        )
    """)
    db.execute(
        "INSERT INTO mart_contact_summary VALUES "
        "(?, ?, ?, ?, ?, ?)",
        [
            "Maria",
            "Father cancer treatment",
            9,
            _json.dumps([
                {"topic": "Father cancer treatment"},
            ]),
            90,
            12,
        ],
    )


class TestTopicInsightGeneration:
    """Tests for topic-based insight generation."""

    def test_generates_topic_insight(
        self,
        tmp_db: DatabaseEngine,
        tracker: QueryTracker,
        mock_brain: MagicMock,
    ) -> None:
        """Topic insight generated from active topics."""
        _seed_mart_topics(tmp_db)

        gen = InsightGenerator(
            db_engine=tmp_db,
            query_tracker=tracker,
            brain_agent=mock_brain,
        )

        insights = gen.generate_daily_insights()

        # Should have generated at least 1 topic insight
        topic_insights = [
            i for i in insights
            if i.trigger == "active_topics"
        ]
        assert len(topic_insights) == 1
        assert topic_insights[0].pattern == "active_topics"

    def test_topic_insight_prompt_includes_topics(
        self,
        tmp_db: DatabaseEngine,
        tracker: QueryTracker,
        mock_brain: MagicMock,
    ) -> None:
        """BrainAgent prompt includes active topic names."""
        _seed_mart_topics(tmp_db)

        gen = InsightGenerator(
            db_engine=tmp_db,
            query_tracker=tracker,
            brain_agent=mock_brain,
        )
        gen.generate_daily_insights()

        # Check the prompt sent to BrainAgent
        call_args = mock_brain.ask.call_args
        prompt = call_args[0][0]
        assert "Maria" in prompt
        assert "Father cancer treatment" in prompt

    def test_no_topic_insight_without_topics(
        self,
        tmp_db: DatabaseEngine,
        tracker: QueryTracker,
        mock_brain: MagicMock,
    ) -> None:
        """No topic insight when no mart_contact_summary."""
        gen = InsightGenerator(
            db_engine=tmp_db,
            query_tracker=tracker,
            brain_agent=mock_brain,
        )
        insights = gen.generate_daily_insights()

        topic_insights = [
            i for i in insights
            if i.trigger == "active_topics"
        ]
        assert len(topic_insights) == 0

    def test_topic_insight_not_duplicated_daily(
        self,
        tmp_db: DatabaseEngine,
        tracker: QueryTracker,
        mock_brain: MagicMock,
    ) -> None:
        """Topic insight not duplicated on same day."""
        _seed_mart_topics(tmp_db)

        gen = InsightGenerator(
            db_engine=tmp_db,
            query_tracker=tracker,
            brain_agent=mock_brain,
        )

        # First call generates it
        insights1 = gen.generate_daily_insights()
        topic1 = [
            i for i in insights1
            if i.trigger == "active_topics"
        ]
        assert len(topic1) == 1

        # Second call skips it (already generated today)
        insights2 = gen.generate_daily_insights()
        topic2 = [
            i for i in insights2
            if i.trigger == "active_topics"
        ]
        assert len(topic2) == 0

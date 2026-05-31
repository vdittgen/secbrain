"""Tests for query tracker and interest profiler.

Covers domain classification accuracy (50+ sample questions),
weight calculation, profile updates, trend detection, and
override persistence.

sensitivity_tier: N/A — test infrastructure
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from src.core.query_tracker import (
    DEFAULT_INTERESTS,
    QueryTracker,
)
from src.core.sqlite.engine import DatabaseEngine
from src.models.llm_provider import LLMResponse

# ============================================================================
# Stub provider — deterministic domain verdicts
# ============================================================================


# Keyword cues retained ONLY here, in the test fixture, to drive the
# stub LLM.  Production code no longer ships these lists.
_STUB_DOMAIN_CUES: dict[str, tuple[str, ...]] = {
    "calendar": (
        "meeting", "meetings", "calendar", "appointment", "agenda",
        "schedule", "busy", "free", "upcoming", "events",
    ),
    "contacts": (
        "who", "person", "friend", "family", "colleague",
        "relationship", "contact", "talked to", "met with",
    ),
    "health": (
        "health", "sleep", "exercise", "heart rate", "steps", "workout",
        "weight", "mood", "energy", "medication", "doctor", "calories",
        "bpm", "blood pressure", "fitness", "walk",
    ),
    "work": (
        "project", "deadline", "task", "work", "presentation",
        "report", "client", "team", "office",
    ),
    "messages": (
        "message", "messages", "email", "emails", "text", "wrote",
        "conversation", "conversations", "reply", "sent", "thread",
        "chat",
    ),
    "notes": (
        "note", "notes", "wrote down", "idea", "journal", "thought",
        "remember", "reminded", "brainstorm",
    ),
    "files": (
        "file", "files", "document", "pdf", "photo", "download",
        "folder", "saved",
    ),
    "music": (
        "song", "songs", "music", "listen", "played", "track",
        "artist", "playlist", "spotify", "album",
    ),
    "social": (
        "dinner", "party", "birthday", "hangout", "weekend",
        "brunch", "concert", "game night",
    ),
    "finance": (
        "money", "spent", "spend", "budget", "cost", "payment",
        "bill", "subscription", "income", "salary", "expense",
    ),
}


class _StubProvider:
    """Stub LLM that returns the expected domain for a question."""

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
        text = prompt[idx + len(marker):].split("\n\nRespond")[0]
        lower = text.lower()
        best: tuple[str, int] = ("general", 0)
        for domain, cues in _STUB_DOMAIN_CUES.items():
            score = sum(1 for cue in cues if cue in lower)
            if score > best[1]:
                best = (domain, score)
        return {"domain": best[0]}

    def check_health(self) -> dict[str, Any]:
        return {"provider": "stub"}


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture()
def tmp_db(tmp_path: Path) -> DatabaseEngine:
    """Fresh DuckDB engine backed by a temp file."""
    db_path = tmp_path / "test_tracker.duckdb"
    engine = DatabaseEngine(db_path=db_path)
    yield engine
    engine.close()


@pytest.fixture()
def tracker(tmp_db: DatabaseEngine) -> QueryTracker:
    """QueryTracker wired to the temp database with stub LLM."""
    return QueryTracker(db_engine=tmp_db, llm_provider=_StubProvider())


# ============================================================================
# TestDomainClassification — 50+ sample questions
# ============================================================================


class TestDomainClassification:
    """Verify keyword-based domain classification accuracy.

    sensitivity_tier: N/A
    """

    # Calendar questions
    @pytest.mark.parametrize(
        "question",
        [
            "What meetings do I have today?",
            "When is my next appointment?",
            "What's on my calendar this week?",
            "Am I busy tomorrow?",
            "Show my schedule for today",
            "What events are upcoming?",
            "Do I have any free time this week?",
            "What's on my agenda?",
        ],
    )
    def test_calendar_questions(
        self, tracker: QueryTracker, question: str,
    ) -> None:
        assert tracker.classify_question_domain(question) == "calendar"

    # Health questions
    @pytest.mark.parametrize(
        "question",
        [
            "How many steps did I walk today?",
            "What's my heart rate?",
            "How did I sleep last night?",
            "Show my exercise history",
            "What's my blood pressure trend?",
            "Am I getting enough sleep?",
            "How is my fitness this month?",
            "Show me my workout stats",
        ],
    )
    def test_health_questions(
        self, tracker: QueryTracker, question: str,
    ) -> None:
        assert tracker.classify_question_domain(question) == "health"

    # Contacts / People questions
    @pytest.mark.parametrize(
        "question",
        [
            "Who is Alice?",
            "Tell me about my colleague Bob",
            "Who have I talked to recently?",
            "Show my friend list",
            "What's my relationship with Carlos?",
        ],
    )
    def test_contacts_questions(
        self, tracker: QueryTracker, question: str,
    ) -> None:
        assert tracker.classify_question_domain(question) == "contacts"

    # Work questions
    @pytest.mark.parametrize(
        "question",
        [
            "What deadlines are coming up?",
            "Show my project status",
            "What tasks do I need to complete?",
            "Tell me about my client report",
            "What presentations do I have?",
        ],
    )
    def test_work_questions(
        self, tracker: QueryTracker, question: str,
    ) -> None:
        assert tracker.classify_question_domain(question) == "work"

    # Messages questions
    @pytest.mark.parametrize(
        "question",
        [
            "Show recent emails",
            "What messages did I get?",
            "Did anyone text me?",
            "Show my email thread about the proposal",
            "What conversations happened today?",
        ],
    )
    def test_messages_questions(
        self, tracker: QueryTracker, question: str,
    ) -> None:
        assert tracker.classify_question_domain(question) == "messages"

    # Notes questions
    @pytest.mark.parametrize(
        "question",
        [
            "What notes did I write?",
            "Show my journal entries",
            "Did I jot down any ideas?",
            "What was that thought I had?",
            "Show my brainstorm notes",
        ],
    )
    def test_notes_questions(
        self, tracker: QueryTracker, question: str,
    ) -> None:
        assert tracker.classify_question_domain(question) == "notes"

    # Files questions
    @pytest.mark.parametrize(
        "question",
        [
            "Find my PDF about taxes",
            "What documents did I download?",
            "Show files in my folder",
            "Where did I save that photo?",
        ],
    )
    def test_files_questions(
        self, tracker: QueryTracker, question: str,
    ) -> None:
        assert tracker.classify_question_domain(question) == "files"

    # Music questions
    @pytest.mark.parametrize(
        "question",
        [
            "What songs did I listen to?",
            "Show my playlist",
            "Who is the artist I played yesterday?",
            "What music have I been into lately?",
            "Show my Spotify history",
        ],
    )
    def test_music_questions(
        self, tracker: QueryTracker, question: str,
    ) -> None:
        assert tracker.classify_question_domain(question) == "music"

    # Social questions
    @pytest.mark.parametrize(
        "question",
        [
            "What are my weekend plans?",
            "When is the next birthday party?",
            "Do I have dinner plans?",
            "What about game night?",
        ],
    )
    def test_social_questions(
        self, tracker: QueryTracker, question: str,
    ) -> None:
        assert tracker.classify_question_domain(question) == "social"

    # Finance questions
    @pytest.mark.parametrize(
        "question",
        [
            "How much did I spend this month?",
            "What's my budget?",
            "Show my subscription costs",
            "What bills are due?",
            "How much income did I earn?",
        ],
    )
    def test_finance_questions(
        self, tracker: QueryTracker, question: str,
    ) -> None:
        assert tracker.classify_question_domain(question) == "finance"

    # General / fallback questions
    @pytest.mark.parametrize(
        "question",
        [
            "Tell me something interesting",
            "Hello",
            "What can you do?",
            "Thanks for the help",
        ],
    )
    def test_general_questions(
        self, tracker: QueryTracker, question: str,
    ) -> None:
        assert tracker.classify_question_domain(question) == "general"

    def test_case_insensitive(self, tracker: QueryTracker) -> None:
        """Classification is case-insensitive."""
        assert (
            tracker.classify_question_domain("WHAT MEETINGS TODAY?")
            == "calendar"
        )

    def test_empty_question(self, tracker: QueryTracker) -> None:
        """Empty question classifies as general."""
        assert tracker.classify_question_domain("") == "general"


# ============================================================================
# TestLogQuery
# ============================================================================


class TestLogQuery:
    """Verify query logging inserts and updates profile.

    sensitivity_tier: N/A
    """

    def test_single_query_logged(
        self, tracker: QueryTracker, tmp_db: DatabaseEngine,
    ) -> None:
        """A single query creates one log row and one profile row."""
        tracker.log_query(
            question="What meetings today?",
            domain="calendar",
        )

        logs = tmp_db.query("SELECT * FROM _query_log")
        assert len(logs) == 1
        assert logs[0]["domain"] == "calendar"
        assert logs[0]["question"] == "What meetings today?"

        profile = tmp_db.query(
            "SELECT * FROM _interest_profile WHERE domain = 'calendar'",
        )
        assert len(profile) == 1
        assert profile[0]["query_count"] == 1

    def test_multiple_queries_same_domain(
        self, tracker: QueryTracker, tmp_db: DatabaseEngine,
    ) -> None:
        """Multiple queries in one domain increment the count."""
        for i in range(5):
            tracker.log_query(
                question=f"Meeting question {i}",
                domain="calendar",
            )

        logs = tmp_db.query("SELECT COUNT(*) AS n FROM _query_log")
        assert logs[0]["n"] == 5

        profile = tmp_db.query(
            "SELECT query_count FROM _interest_profile "
            "WHERE domain = 'calendar'",
        )
        assert profile[0]["query_count"] == 5

    def test_multiple_domains_tracked_independently(
        self, tracker: QueryTracker, tmp_db: DatabaseEngine,
    ) -> None:
        """Each domain maintains its own count."""
        tracker.log_query(question="q1", domain="calendar")
        tracker.log_query(question="q2", domain="calendar")
        tracker.log_query(question="q3", domain="health")

        rows = tmp_db.query(
            "SELECT domain, query_count FROM _interest_profile "
            "ORDER BY domain",
        )
        by_domain = {r["domain"]: r["query_count"] for r in rows}
        assert by_domain["calendar"] == 2
        assert by_domain["health"] == 1

    def test_sub_topics_and_entities_stored(
        self, tracker: QueryTracker, tmp_db: DatabaseEngine,
    ) -> None:
        """Sub-topics and entities are stored as JSON strings."""
        tracker.log_query(
            question="Tell me about Alice's meetings",
            domain="calendar",
            sub_topics=["calendar", "contacts"],
            entities=["Alice"],
            sources_used=["duckdb", "kuzu"],
        )

        logs = tmp_db.query("SELECT * FROM _query_log")
        assert logs[0]["sub_topics"] == '["calendar", "contacts"]'
        assert logs[0]["entities"] == '["Alice"]'
        assert logs[0]["sources_used"] == '["duckdb", "kuzu"]'

    def test_latency_stored(
        self, tracker: QueryTracker, tmp_db: DatabaseEngine,
    ) -> None:
        """Latency is stored in the log."""
        tracker.log_query(
            question="test", domain="general", latency_ms=1234.5,
        )

        logs = tmp_db.query("SELECT latency_ms FROM _query_log")
        assert logs[0]["latency_ms"] == pytest.approx(1234.5)


# ============================================================================
# TestInterestProfile
# ============================================================================


class TestInterestProfile:
    """Test interest profile weight computation.

    sensitivity_tier: N/A
    """

    def test_empty_db_returns_defaults(
        self, tracker: QueryTracker,
    ) -> None:
        """With no queries, all DEFAULT_INTERESTS appear with 0 count."""
        profile = tracker.get_interest_profile()
        domains = {a.domain for a in profile}

        for d in DEFAULT_INTERESTS:
            assert d["domain"] in domains

        for area in profile:
            assert area.query_count == 0

    def test_queried_domain_ranks_higher(
        self, tracker: QueryTracker,
    ) -> None:
        """After queries, that domain's weight rises."""
        for _ in range(10):
            tracker.log_query(question="health q", domain="health")

        profile = tracker.get_interest_profile()
        # Health should be near the top
        health = next(a for a in profile if a.domain == "health")
        assert health.query_count == 10
        assert health.weight > 0

    def test_more_queries_means_higher_weight(
        self, tracker: QueryTracker,
    ) -> None:
        """Domain with more queries has higher weight."""
        for _ in range(20):
            tracker.log_query(question="cal q", domain="calendar")
        for _ in range(5):
            tracker.log_query(question="health q", domain="health")

        profile = tracker.get_interest_profile()
        cal = next(a for a in profile if a.domain == "calendar")
        health = next(a for a in profile if a.domain == "health")
        assert cal.weight > health.weight

    def test_explicit_domains_get_baseline_boost(
        self, tracker: QueryTracker,
    ) -> None:
        """Explicit domains (dashboard areas) have weight even with 0 queries."""
        profile = tracker.get_interest_profile()

        explicit_areas = [
            a for a in profile if a.explicit
        ]
        non_explicit_areas = [
            a for a in profile if not a.explicit
        ]

        if explicit_areas and non_explicit_areas:
            min_explicit = min(a.weight for a in explicit_areas)
            max_non_explicit = max(a.weight for a in non_explicit_areas)
            # Explicit should rank above non-explicit when both have 0
            assert min_explicit >= max_non_explicit

    def test_override_boosts_weight(
        self, tracker: QueryTracker,
    ) -> None:
        """Manual override raises a domain's weight."""
        profile_auto = tracker.get_interest_profile()
        music_auto = next(
            a for a in profile_auto if a.domain == "music"
        )

        profile_override = tracker.get_interest_profile(
            overrides={"music": 1},
        )
        music_override = next(
            a for a in profile_override if a.domain == "music"
        )

        assert music_override.weight > music_auto.weight

    def test_weights_normalized_0_to_1(
        self, tracker: QueryTracker,
    ) -> None:
        """All weights are in [0.0, 1.0] range."""
        for _ in range(10):
            tracker.log_query(question="cal", domain="calendar")

        profile = tracker.get_interest_profile()
        for area in profile:
            assert 0.0 <= area.weight <= 1.0

    def test_queries_per_week_calculated(
        self, tracker: QueryTracker,
    ) -> None:
        """queries_per_week is derived from recent query count."""
        for _ in range(7):
            tracker.log_query(question="cal", domain="calendar")

        profile = tracker.get_interest_profile()
        cal = next(a for a in profile if a.domain == "calendar")
        # 7 queries in ~0 days; within 30-day window
        assert cal.queries_per_week > 0

    def test_unknown_domain_included(
        self, tracker: QueryTracker,
    ) -> None:
        """A domain not in DEFAULT_INTERESTS still appears if queried."""
        tracker.log_query(question="q", domain="cooking")

        profile = tracker.get_interest_profile()
        cooking = next(
            (a for a in profile if a.domain == "cooking"), None,
        )
        assert cooking is not None
        assert cooking.query_count == 1
        assert cooking.explicit is False


# ============================================================================
# TestDomainStats
# ============================================================================


class TestDomainStats:
    """Test per-domain statistics and trend detection.

    sensitivity_tier: N/A
    """

    def test_empty_db_returns_empty(
        self, tracker: QueryTracker,
    ) -> None:
        """No queries means no stats."""
        stats = tracker.get_domain_stats()
        assert stats == []

    def test_single_domain_stats(
        self, tracker: QueryTracker,
    ) -> None:
        """Stats for a domain with queries."""
        tracker.log_query(question="q1", domain="calendar")
        tracker.log_query(question="q2", domain="calendar")

        stats = tracker.get_domain_stats()
        assert len(stats) == 1
        assert stats[0].domain == "calendar"
        assert stats[0].total_queries == 2
        assert stats[0].last_queried_at is not None

    def test_new_domain_trend(
        self, tracker: QueryTracker,
    ) -> None:
        """Domains with < 3 total queries have trend 'new'."""
        tracker.log_query(question="q1", domain="music")

        stats = tracker.get_domain_stats()
        music = next(s for s in stats if s.domain == "music")
        assert music.trend == "new"

    def test_stats_ordered_by_count(
        self, tracker: QueryTracker,
    ) -> None:
        """Stats are ordered by total queries descending."""
        for _ in range(5):
            tracker.log_query(question="q", domain="calendar")
        for _ in range(2):
            tracker.log_query(question="q", domain="health")

        stats = tracker.get_domain_stats()
        assert stats[0].domain == "calendar"
        assert stats[1].domain == "health"


# ============================================================================
# TestTopQuestions
# ============================================================================


class TestTopQuestions:
    """Test top question pattern retrieval.

    sensitivity_tier: N/A
    """

    def test_empty_db(self, tracker: QueryTracker) -> None:
        """No queries means empty result."""
        assert tracker.get_top_questions() == []

    def test_returns_domain_counts(
        self, tracker: QueryTracker,
    ) -> None:
        """Returns domain frequencies in descending order."""
        for _ in range(5):
            tracker.log_query(question="q", domain="calendar")
        for _ in range(3):
            tracker.log_query(question="q", domain="health")

        top = tracker.get_top_questions(limit=10)
        assert len(top) == 2
        assert top[0]["domain"] == "calendar"
        assert top[0]["count"] == 5
        assert top[1]["domain"] == "health"
        assert top[1]["count"] == 3

    def test_limit_respected(
        self, tracker: QueryTracker,
    ) -> None:
        """Limit parameter caps the result count."""
        for d in ["a", "b", "c", "d", "e"]:
            tracker.log_query(question="q", domain=d)

        top = tracker.get_top_questions(limit=3)
        assert len(top) == 3


# ============================================================================
# TestTableCreation
# ============================================================================


class TestTableCreation:
    """Verify table creation is idempotent.

    sensitivity_tier: N/A
    """

    def test_tables_exist_after_init(
        self, tmp_db: DatabaseEngine,
    ) -> None:
        """Tables are created on QueryTracker init."""
        QueryTracker(db_engine=tmp_db)

        tables = tmp_db.query(
            "SELECT name FROM sqlite_master "
            "WHERE type = 'table' AND name IN ('_query_log', '_interest_profile')"
        )
        names = {t["name"] for t in tables}
        assert "_query_log" in names
        assert "_interest_profile" in names

    def test_double_init_is_safe(
        self, tmp_db: DatabaseEngine,
    ) -> None:
        """Creating QueryTracker twice doesn't error."""
        QueryTracker(db_engine=tmp_db)
        QueryTracker(db_engine=tmp_db)

        tables = tmp_db.query(
            "SELECT name FROM sqlite_master "
            "WHERE type = 'table' AND name IN ('_query_log', '_interest_profile')"
        )
        assert len(tables) == 2


# ============================================================================
# TestDomainKeywords
# ============================================================================


class TestDomainClassifierFallback:
    """Verify the LLM-driven classifier degrades gracefully.

    sensitivity_tier: N/A
    """

    def test_no_provider_returns_general(
        self, tmp_db: DatabaseEngine,
    ) -> None:
        """With no LLM provider AND lazy resolution failing, every
        question routes to ``general`` (safe default)."""

        class _NullProvider:
            provider_name = "null"
            default_model = "null"

            def chat(self, *_a: Any, **_kw: Any) -> LLMResponse:
                return LLMResponse(content="", model="null")

            def chat_stream(self, *_a: Any, **_kw: Any):  # noqa: ANN201
                return iter(())

            def chat_json(self, *_a: Any, **_kw: Any) -> dict[str, Any]:
                raise RuntimeError("LLM offline")

            def check_health(self) -> dict[str, Any]:
                return {"provider": "null"}

        tracker = QueryTracker(
            db_engine=tmp_db, llm_provider=_NullProvider(),
        )
        assert tracker.classify_question_domain(
            "What meetings today?",
        ) == "general"

    def test_unrecognised_domain_falls_back_to_general(
        self, tmp_db: DatabaseEngine,
    ) -> None:
        """LLM hallucinates a non-enum domain → general."""

        class _BadProvider(_StubProvider):
            def chat_json(self, *_a: Any, **_kw: Any) -> dict[str, Any]:
                return {"domain": "astrology"}

        tracker = QueryTracker(
            db_engine=tmp_db, llm_provider=_BadProvider(),
        )
        assert tracker.classify_question_domain(
            "what's my horoscope?",
        ) == "general"

    def test_default_interests_remain_in_classifier_enum(self) -> None:
        """DEFAULT_INTERESTS domains are still recognisable to the
        LLM-driven classifier."""
        from src.core.query_tracker import _DOMAIN_ENUM

        for interest in DEFAULT_INTERESTS:
            assert interest["domain"] in _DOMAIN_ENUM

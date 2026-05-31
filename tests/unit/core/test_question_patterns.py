"""Tests for QuestionPatternDetector.

sensitivity_tier: 1 (no user data)
"""

from __future__ import annotations

from typing import Any

import pytest
from src.core.question_patterns import (
    PATTERNS,
    PatternMatch,
    QuestionPatternDetector,
)
from src.models.llm_provider import LLMResponse

# Stub LLM that maps a question to the right intent pattern via the
# (same) keyword cues the legacy detector used.  Lives only in tests.
_PATTERN_CUES: dict[str, tuple[str, ...]] = {
    name: tuple(spec["keywords"]) for name, spec in PATTERNS.items()
}


class _StubProvider:
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
        best: tuple[str, float] = ("none", 0.0)
        for name, cues in _PATTERN_CUES.items():
            hits = sum(1 for cue in cues if cue in lower)
            if hits == 0:
                continue
            confidence = hits / len(cues)
            if confidence > best[1]:
                best = (name, confidence)
        if best[1] < 0.1:
            return {"pattern": "none", "confidence": 0.0}
        # Boost confidence so it clears the 0.3 detector threshold —
        # the stub is meant to mimic a confident LLM verdict.
        return {"pattern": best[0], "confidence": max(0.6, best[1])}

    def check_health(self) -> dict[str, Any]:
        return {"provider": "stub"}


@pytest.fixture()
def detector() -> QuestionPatternDetector:
    return QuestionPatternDetector(llm_provider=_StubProvider())


# ------------------------------------------------------------------
# TestPatternDetection — parametrized per pattern type
# ------------------------------------------------------------------


class TestPatternDetection:
    """Each pattern type should be detected for representative questions."""

    @pytest.mark.parametrize(
        "question",
        [
            "What do I have today?",
            "What's on my schedule today?",
            "What's my agenda for today?",
            "What's planned for today?",
            "What's happening today?",
        ],
    )
    def test_schedule_today(
        self, detector: QuestionPatternDetector, question: str,
    ) -> None:
        match = detector.detect(question)
        assert match is not None
        assert match.pattern_name == "schedule_today"

    @pytest.mark.parametrize(
        "question",
        [
            "What do I have this week?",
            "What's happening next week?",
            "Any upcoming events?",
            "What's the week ahead look like?",
        ],
    )
    def test_schedule_week(
        self, detector: QuestionPatternDetector, question: str,
    ) -> None:
        match = detector.detect(question)
        assert match is not None
        assert match.pattern_name == "schedule_week"

    @pytest.mark.parametrize(
        "question",
        [
            "Tell me about Alice",
            "Who is John?",
            "What do I know about Sarah?",
            "Have I talked to Bob recently?",
            "When did I last met with Dave?",
        ],
    )
    def test_person_inquiry(
        self, detector: QuestionPatternDetector, question: str,
    ) -> None:
        match = detector.detect(question)
        assert match is not None
        assert match.pattern_name == "person_inquiry"

    @pytest.mark.parametrize(
        "question",
        [
            "How is my health trending?",
            "How did I sleep last night?",
            "How are my steps trending?",
            "What's my heart rate compared to last week?",
            "Any exercise trends?",
        ],
    )
    def test_health_check(
        self, detector: QuestionPatternDetector, question: str,
    ) -> None:
        match = detector.detect(question)
        assert match is not None
        assert match.pattern_name == "health_check"

    @pytest.mark.parametrize(
        "question",
        [
            "Do I have any unread messages?",
            "Are there new messages in my inbox?",
            "What did I miss in my inbox?",
            "Any emails from the team?",
        ],
    )
    def test_message_search(
        self, detector: QuestionPatternDetector, question: str,
    ) -> None:
        match = detector.detect(question)
        assert match is not None
        assert match.pattern_name == "message_search"

    @pytest.mark.parametrize(
        "question",
        [
            "What did I write in my last note?",
            "Any ideas I noted recently?",
            "What did I write in my journal?",
            "Show me my brainstorm ideas",
        ],
    )
    def test_note_recall(
        self, detector: QuestionPatternDetector, question: str,
    ) -> None:
        match = detector.detect(question)
        assert match is not None
        assert match.pattern_name == "note_recall"

    @pytest.mark.parametrize(
        "question",
        [
            "Summarize my week",
            "Give me a recap",
            "What's new since yesterday?",
            "Catch me up on everything",
            "Overview of what happened",
        ],
    )
    def test_general_summary(
        self, detector: QuestionPatternDetector, question: str,
    ) -> None:
        match = detector.detect(question)
        assert match is not None
        assert match.pattern_name == "general_summary"

    @pytest.mark.parametrize(
        "question",
        [
            "How am I feeling emotionally?",
            "Am I feeling stressed or anxious?",
            "What's my mood been like?",
            "Have I been anxious lately?",
        ],
    )
    def test_mood_check(
        self, detector: QuestionPatternDetector, question: str,
    ) -> None:
        match = detector.detect(question)
        assert match is not None
        assert match.pattern_name == "mood_check"

    @pytest.mark.parametrize(
        "question",
        [
            "I haven't talked to Mom in a while",
            "Am I out of touch with anyone?",
            "Should I reach out to my friend?",
            "Which family members haven't I contacted?",
        ],
    )
    def test_relationship_status(
        self, detector: QuestionPatternDetector, question: str,
    ) -> None:
        match = detector.detect(question)
        assert match is not None
        assert match.pattern_name == "relationship_status"

    @pytest.mark.parametrize(
        "question",
        [
            "How productive has my work been?",
            "What are my work deadlines?",
            "What projects am I working on?",
            "Am I too busy with tasks?",
        ],
    )
    def test_work_productivity(
        self, detector: QuestionPatternDetector, question: str,
    ) -> None:
        match = detector.detect(question)
        assert match is not None
        assert match.pattern_name == "work_productivity"


# ------------------------------------------------------------------
# TestPatternConfidence
# ------------------------------------------------------------------


class TestPatternConfidence:
    """Confidence scoring and threshold behavior."""

    def test_confidence_between_0_and_1(
        self, detector: QuestionPatternDetector,
    ) -> None:
        matches = detector.detect_all(
            "What's on my schedule today? Any meetings planned?"
        )
        for m in matches:
            assert 0.0 <= m.confidence <= 1.0

    def test_higher_keyword_overlap_gives_higher_confidence(
        self, detector: QuestionPatternDetector,
    ) -> None:
        # "today schedule planned agenda" hits 4 keywords for schedule_today
        multi_hit = detector.detect(
            "What's on my schedule today? I need my agenda planned."
        )
        single_hit = detector.detect("What about today?")
        assert multi_hit is not None
        assert single_hit is not None
        assert multi_hit.confidence >= single_hit.confidence

    def test_below_threshold_returns_none(
        self, detector: QuestionPatternDetector,
    ) -> None:
        # A question with no pattern keyword hits
        result = detector.detect("Tell me something random")
        assert result is None

    def test_case_insensitive(
        self, detector: QuestionPatternDetector,
    ) -> None:
        match = detector.detect("WHAT IS MY SCHEDULE TODAY?")
        assert match is not None
        assert match.pattern_name == "schedule_today"


# ------------------------------------------------------------------
# TestNoMatchFallback
# ------------------------------------------------------------------


class TestNoMatchFallback:
    """Questions that match no pattern return None."""

    def test_empty_question(
        self, detector: QuestionPatternDetector,
    ) -> None:
        assert detector.detect("") is None

    def test_unrelated_question(
        self, detector: QuestionPatternDetector,
    ) -> None:
        assert detector.detect(
            "What is the capital of France?"
        ) is None

    def test_gibberish(
        self, detector: QuestionPatternDetector,
    ) -> None:
        assert detector.detect("asdf qwerty zxcv") is None


# ------------------------------------------------------------------
# TestDetectAll
# ------------------------------------------------------------------


class TestDetectAll:
    """detect_all returns multiple matches sorted by confidence."""

    def test_returns_multiple_matches(
        self, detector: QuestionPatternDetector,
    ) -> None:
        # "How is my health trending this week?" could match
        # health_check and schedule_week
        matches = detector.detect_all(
            "How is my health trending this week?"
        )
        assert len(matches) >= 1
        # Should be sorted by confidence desc
        for i in range(len(matches) - 1):
            assert matches[i].confidence >= matches[i + 1].confidence

    def test_returns_empty_for_no_match(
        self, detector: QuestionPatternDetector,
    ) -> None:
        assert detector.detect_all("xyzzy") == []

    def test_all_matches_are_pattern_match_instances(
        self, detector: QuestionPatternDetector,
    ) -> None:
        matches = detector.detect_all("What's on my schedule today?")
        for m in matches:
            assert isinstance(m, PatternMatch)


# ------------------------------------------------------------------
# TestEntityExtraction
# ------------------------------------------------------------------


class TestEntityExtraction:
    """extract_entities matches against known contacts or capitalized words."""

    def test_match_known_contacts(
        self, detector: QuestionPatternDetector,
    ) -> None:
        contacts = ["Alice Smith", "Bob Jones", "Charlie"]
        entities = detector.extract_entities(
            "What did Alice Smith say to Bob Jones?",
            known_contacts=contacts,
        )
        assert "Alice Smith" in entities
        assert "Bob Jones" in entities
        assert "Charlie" not in entities

    def test_case_insensitive_contact_match(
        self, detector: QuestionPatternDetector,
    ) -> None:
        contacts = ["Alice"]
        entities = detector.extract_entities(
            "Tell me about alice",
            known_contacts=contacts,
        )
        assert "Alice" in entities

    def test_fallback_capitalized_words(
        self, detector: QuestionPatternDetector,
    ) -> None:
        entities = detector.extract_entities(
            "I talked to Maria and John yesterday"
        )
        assert "Maria" in entities
        assert "John" in entities

    def test_filters_common_words(
        self, detector: QuestionPatternDetector,
    ) -> None:
        entities = detector.extract_entities(
            "What did Alice say about the project?"
        )
        assert "What" not in entities
        assert "The" not in entities
        assert "Alice" in entities

    def test_empty_question(
        self, detector: QuestionPatternDetector,
    ) -> None:
        assert detector.extract_entities("") == []

    def test_no_contacts_no_caps(
        self, detector: QuestionPatternDetector,
    ) -> None:
        assert detector.extract_entities("hello world") == []


# ------------------------------------------------------------------
# TestPatternCompleteness
# ------------------------------------------------------------------


class TestPatternCompleteness:
    """All patterns have required fields."""

    def test_all_patterns_have_required_fields(self) -> None:
        required = {
            "keywords",
            "description",
            "insight_prompt",
            "suggested_followup",
        }
        for name, spec in PATTERNS.items():
            for field in required:
                assert field in spec, (
                    f"Pattern {name!r} missing field {field!r}"
                )

    def test_all_patterns_have_nonempty_keywords(self) -> None:
        for name, spec in PATTERNS.items():
            assert len(spec["keywords"]) >= 3, (
                f"Pattern {name!r} has fewer than 3 keywords"
            )

    def test_pattern_count(self) -> None:
        assert len(PATTERNS) == 10

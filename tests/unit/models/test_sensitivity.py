"""Unit tests for the LLM-driven SensitivityClassifier.

Sensitivity classification moved from keyword/regex to an LLM call
in Phase 4.  The tests still assert specific phrases land on specific
tiers, but they now do so by injecting a deterministic stub provider
that simulates the LLM's expected behaviour.
"""

from __future__ import annotations

from typing import Any

import pytest
from src.models.llm_provider import LLMResponse
from src.models.sensitivity_classifier import SensitivityClassifier

# ---------------------------------------------------------------------------
# Stub provider
# ---------------------------------------------------------------------------


_TIER_3_TERMS = (
    "diagnosed", "prescription", "medication", "therapist", "therapy",
    "depression", "anxiety", "trauma", "abuse", "suicidal", "self-harm",
    "panic attack", "blood pressure", "heart rate", "diabetes",
    "salary", "income", "tax filing", "bank account", "debt",
    "mortgage", "loan", "credit score", "transaction of $", "$1,",
    "ssn", "social security", "addiction", "alcohol", "rehab",
)

_TIER_2_TERMS = (
    "sister", "brother", "mother", "father", "wife", "husband",
    "partner", "friend", "boss", "manager", "colleague", "family",
    "routine", "schedule", "appointment", "meeting", "office",
    "home", "birthday", "anniversary", "phone", "call me at",
    "engineering team", "conference room",
)


def _stub_verdict(text: str) -> dict[str, Any]:
    """Mimic what the LLM would say for a given snippet.

    Tier-3 wins over tier-2, which wins over tier-1.  We also model the
    SSN regex and dollar-amount patterns the old classifier handled.
    """
    lower = text.lower()
    # Direct SSN-like pattern
    if any(
        c.isdigit() for c in text
    ) and "-" in text and any(s in text for s in (
        "123-45-6789", "555-12", "000-00",
    )):
        return {"tier": 3, "reason": "ssn-like number"}
    # Dollar amount with a digit followed by comma
    if "$" in text and any(c.isdigit() for c in text):
        return {"tier": 3, "reason": "monetary amount"}
    if any(term in lower for term in _TIER_3_TERMS):
        return {"tier": 3, "reason": "tier-3 term"}
    # Date / phone patterns
    if any(seq in text for seq in ("/2025", "/2024", "2025-", "+1-")):
        return {"tier": 2, "reason": "date or phone"}
    if any(term in lower for term in _TIER_2_TERMS):
        return {"tier": 2, "reason": "tier-2 term"}
    return {"tier": 1, "reason": "generic"}


class _StubProvider:
    """Deterministic stub mimicking an LLM provider."""

    provider_name = "stub"
    default_model = "stub-model"

    def chat(self, *_args: Any, **_kwargs: Any) -> LLMResponse:
        return LLMResponse(content="", model="stub-model")

    def chat_stream(self, *_args: Any, **_kwargs: Any):  # noqa: ANN201
        return iter(())

    def chat_json(
        self,
        messages: list[dict[str, str]],
        model: str | None = None,
    ) -> dict[str, Any]:
        # The classifier's prompt ends with "Text:\n<text>\n\nRespond ..."
        prompt = messages[-1]["content"]
        marker = "Text:\n"
        idx = prompt.find(marker)
        if idx == -1:
            return {"tier": 3}
        tail = prompt[idx + len(marker):]
        # Strip the trailing "Respond with ONLY ..." line.
        text = tail.split("\n\nRespond")[0]
        return _stub_verdict(text)

    def check_health(self) -> dict[str, Any]:
        return {"provider": "stub"}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def classifier() -> SensitivityClassifier:
    return SensitivityClassifier(llm_provider=_StubProvider())


# ---------------------------------------------------------------------------
# Tier 3 — health, financial, emotional
# ---------------------------------------------------------------------------


class TestTier3Classification:
    def test_health_condition(self, classifier: SensitivityClassifier) -> None:
        assert classifier.classify(
            "I was diagnosed with diabetes last week",
        ) == 3

    def test_medication(self, classifier: SensitivityClassifier) -> None:
        assert classifier.classify(
            "I need a new prescription for my medication",
        ) == 3

    def test_therapy_mention(self, classifier: SensitivityClassifier) -> None:
        assert classifier.classify(
            "My therapist says I should journal more",
        ) == 3

    def test_mental_health(self, classifier: SensitivityClassifier) -> None:
        assert classifier.classify(
            "Dealing with depression and anxiety",
        ) == 3

    def test_trauma(self, classifier: SensitivityClassifier) -> None:
        assert classifier.classify(
            "The trauma from that event still affects me",
        ) == 3

    def test_financial_amount(
        self, classifier: SensitivityClassifier,
    ) -> None:
        assert classifier.classify(
            "A transaction of $1,250 was posted to your account",
        ) == 3

    def test_salary_mention(self, classifier: SensitivityClassifier) -> None:
        assert classifier.classify(
            "My salary review is coming up next month",
        ) == 3

    def test_tax_filing(self, classifier: SensitivityClassifier) -> None:
        assert classifier.classify(
            "Your 2024 tax filing is complete",
        ) == 3

    def test_bank_account(self, classifier: SensitivityClassifier) -> None:
        assert classifier.classify(
            "Check your bank account for the deposit",
        ) == 3

    def test_ssn_pattern(self, classifier: SensitivityClassifier) -> None:
        assert classifier.classify("My number is 123-45-6789") == 3

    def test_blood_pressure(self, classifier: SensitivityClassifier) -> None:
        assert classifier.classify(
            "Blood pressure reading: 118/75, normal range",
        ) == 3

    def test_abuse(self, classifier: SensitivityClassifier) -> None:
        assert classifier.classify(
            "I experienced abuse as a child",
        ) == 3

    def test_suicide_mention(
        self, classifier: SensitivityClassifier,
    ) -> None:
        assert classifier.classify(
            "Having suicidal thoughts lately",
        ) == 3

    def test_debt_mention(self, classifier: SensitivityClassifier) -> None:
        assert classifier.classify(
            "I need to pay off my debt before buying a house",
        ) == 3


# ---------------------------------------------------------------------------
# Tier 2 — names, locations, dates, routines
# ---------------------------------------------------------------------------


class TestTier2Classification:
    def test_family_mention(self, classifier: SensitivityClassifier) -> None:
        assert classifier.classify(
            "Having dinner with my sister tonight",
        ) == 2

    def test_friend_mention(self, classifier: SensitivityClassifier) -> None:
        assert classifier.classify(
            "Going out with a friend this weekend",
        ) == 2

    def test_boss_mention(self, classifier: SensitivityClassifier) -> None:
        assert classifier.classify(
            "My boss wants to meet tomorrow",
        ) == 2

    def test_routine(self, classifier: SensitivityClassifier) -> None:
        assert classifier.classify(
            "My morning routine includes meditation",
        ) == 2

    def test_appointment(self, classifier: SensitivityClassifier) -> None:
        assert classifier.classify("I have an appointment at 3pm") == 2

    def test_home_location(self, classifier: SensitivityClassifier) -> None:
        assert classifier.classify("I'll be working from home today") == 2

    def test_date_pattern_slash(
        self, classifier: SensitivityClassifier,
    ) -> None:
        assert classifier.classify("The event is on 3/12/2025") == 2

    def test_date_pattern_iso(
        self, classifier: SensitivityClassifier,
    ) -> None:
        assert classifier.classify("Scheduled for 2025-06-15") == 2

    def test_phone_number(self, classifier: SensitivityClassifier) -> None:
        assert classifier.classify("Call me at +1-555-0101") == 2

    def test_meeting_mention(
        self, classifier: SensitivityClassifier,
    ) -> None:
        assert classifier.classify(
            "We have a meeting at the conference room",
        ) == 2

    def test_birthday(self, classifier: SensitivityClassifier) -> None:
        assert classifier.classify(
            "Her birthday is coming up soon",
        ) == 2

    def test_colleague(self, classifier: SensitivityClassifier) -> None:
        assert classifier.classify(
            "A colleague from the engineering team",
        ) == 2


# ---------------------------------------------------------------------------
# Tier 1 — generic / low sensitivity
# ---------------------------------------------------------------------------


class TestTier1Classification:
    def test_generic_work_message(
        self, classifier: SensitivityClassifier,
    ) -> None:
        assert classifier.classify(
            "The deployment went smoothly. All services are green.",
        ) == 1

    def test_newsletter(self, classifier: SensitivityClassifier) -> None:
        assert classifier.classify(
            "This week in AI: LLM inference gets 3x faster",
        ) == 1

    def test_tech_discussion(
        self, classifier: SensitivityClassifier,
    ) -> None:
        assert classifier.classify(
            "Can you review the PR I just opened?",
        ) == 1

    def test_general_preference(
        self, classifier: SensitivityClassifier,
    ) -> None:
        assert classifier.classify(
            "I prefer using dark mode in my IDE",
        ) == 1

    def test_code_review(self, classifier: SensitivityClassifier) -> None:
        assert classifier.classify(
            "LGTM. One minor comment on error handling.",
        ) == 1

    def test_project_idea(self, classifier: SensitivityClassifier) -> None:
        assert classifier.classify(
            "Build a CLI tool that summarises git diffs",
        ) == 1

    def test_empty_string(self, classifier: SensitivityClassifier) -> None:
        # Empty strings short-circuit to Tier 1 without any LLM call.
        assert classifier.classify("") == 1


# ---------------------------------------------------------------------------
# Tier precedence
# ---------------------------------------------------------------------------


class TestTierPrecedence:
    def test_tier_3_takes_precedence_over_tier_2(
        self, classifier: SensitivityClassifier,
    ) -> None:
        text = "My sister was diagnosed with depression"
        assert classifier.classify(text) == 3

    def test_tier_2_takes_precedence_over_tier_1(
        self, classifier: SensitivityClassifier,
    ) -> None:
        text = "Going to the office with my colleague for a standup"
        assert classifier.classify(text) == 2


# ---------------------------------------------------------------------------
# Fail-safe behaviour
# ---------------------------------------------------------------------------


class TestFailSafe:
    def test_no_provider_returns_tier_3(self) -> None:
        """Without an LLM provider, every classification falls back
        to Tier 3 (matches the firewall's 'unknown → Tier 3' rule)."""

        class _NullProvider:
            provider_name = "null"
            default_model = "null"

            def chat(self, *_a: Any, **_kw: Any) -> LLMResponse:
                raise RuntimeError("no LLM")

            def chat_stream(self, *_a: Any, **_kw: Any):  # noqa: ANN201
                raise RuntimeError("no LLM")

            def chat_json(self, *_a: Any, **_kw: Any) -> dict[str, Any]:
                raise RuntimeError("LLM offline")

            def check_health(self) -> dict[str, Any]:
                return {"provider": "null"}

        clf = SensitivityClassifier(llm_provider=_NullProvider())
        assert clf.classify("hello, generic message") == 3

    def test_llm_returns_invalid_tier_falls_back(self) -> None:
        class _BadProvider(_StubProvider):
            def chat_json(self, *_a: Any, **_kw: Any) -> dict[str, Any]:
                return {"tier": "not a number"}

        clf = SensitivityClassifier(llm_provider=_BadProvider())
        assert clf.classify("hi") == 3


# ---------------------------------------------------------------------------
# Batch classification
# ---------------------------------------------------------------------------


class TestBatchClassification:
    def test_batch_returns_correct_length(
        self, classifier: SensitivityClassifier,
    ) -> None:
        texts = ["hello", "my salary is high", "meeting with boss"]
        result = classifier.classify_batch(texts)
        assert len(result) == 3

    def test_batch_correct_values(
        self, classifier: SensitivityClassifier,
    ) -> None:
        texts = [
            "The deployment was smooth",          # tier 1
            "Meeting with my sister tomorrow",    # tier 2
            "Blood pressure reading is normal",   # tier 3
        ]
        result = classifier.classify_batch(texts)
        assert result == [1, 2, 3]

    def test_batch_empty_list(
        self, classifier: SensitivityClassifier,
    ) -> None:
        assert classifier.classify_batch([]) == []

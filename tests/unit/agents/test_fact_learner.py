"""Tests for FactLearner — DB-backed wrapper around FactExtractorAgent.

Uses a real temp DuckDB for table creation and CRUD operations. The
LLM step is delegated to :class:`FactExtractorAgent`; tests mock the
agent's ``extract`` method directly via monkeypatch (no raw provider
mocking).

sensitivity_tier: N/A — test infrastructure
"""

from __future__ import annotations

from pathlib import Path

import pytest
from src.agents.core.output_types import LearnedFactBatch, LearnedFactDraft
from src.agents.fact_extractor import FactLearner
from src.agents.fact_extractor.persistence import CATEGORIES
from src.core.llm_helpers import parse_llm_json_array
from src.core.sqlite.engine import DatabaseEngine

# ================================================================
# Fixtures
# ================================================================


@pytest.fixture()
def tmp_db(tmp_path: Path) -> DatabaseEngine:
    """Fresh DuckDB engine backed by a temp file."""
    db_path = tmp_path / "test_facts.duckdb"
    engine = DatabaseEngine(db_path=db_path)
    yield engine
    engine.close()


def _draft(
    *,
    category: str = "preference",
    subject: str = "self",
    predicate: str = "favorite_food",
    content: str = "User's favorite food is sushi",
    sensitivity_tier: int = 1,
) -> LearnedFactDraft:
    """Build a LearnedFactDraft with defaults matching the legacy fixture."""
    return LearnedFactDraft(
        category=category,
        subject=subject,
        predicate=predicate,
        content=content,
        sensitivity_tier=sensitivity_tier,
    )


@pytest.fixture()
def stub_extract(monkeypatch):
    """Monkey-patch ``FactExtractorAgent.extract`` with a controllable stub.

    Tests can set ``stub_extract.return_value`` to a
    :class:`LearnedFactBatch` or ``stub_extract.side_effect`` to an
    exception to simulate LLM failures.
    """
    from unittest.mock import MagicMock
    fake = MagicMock(
        return_value=LearnedFactBatch(facts=[_draft()]),
    )

    def _bound_extract(self, conversation):  # noqa: ARG001
        result = fake(conversation)
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(
        "src.agents.fact_extractor.agent.FactExtractorAgent.extract",
        _bound_extract,
    )
    return fake


@pytest.fixture()
def learner(tmp_db: DatabaseEngine, stub_extract) -> FactLearner:  # noqa: ARG001
    """FactLearner wired to temp DB with a stubbed extractor."""
    return FactLearner(db_engine=tmp_db)


@pytest.fixture()
def learner_bare(tmp_db: DatabaseEngine) -> FactLearner:
    """FactLearner with no LLM stub — read-only / persistence-only tests."""
    return FactLearner(db_engine=tmp_db)


# ================================================================
# Table creation
# ================================================================


class TestTableSetup:
    """Tests for _ensure_table."""

    def test_creates_table(self, tmp_db: DatabaseEngine) -> None:
        _learner = FactLearner(db_engine=tmp_db)
        rows = tmp_db.query(
            "SELECT name FROM sqlite_master "
            "WHERE type = 'table' AND name = '_learned_facts'"
        )
        assert len(rows) == 1

    def test_idempotent(self, tmp_db: DatabaseEngine) -> None:
        FactLearner(db_engine=tmp_db)
        FactLearner(db_engine=tmp_db)  # should not raise


# ================================================================
# Extraction
# ================================================================


class TestExtraction:
    """Tests for extract_facts_from_conversation (LLM-backed path)."""

    def test_extracts_single_fact(self, learner: FactLearner) -> None:
        facts = learner.extract_facts_from_conversation(
            user_messages=["I love sushi, it's my favorite food!"],
            assistant_messages=["Great taste! Sushi is wonderful."],
        )
        assert len(facts) == 1
        assert facts[0].category == "preference"
        assert facts[0].subject == "self"
        assert facts[0].predicate == "favorite_food"
        assert "sushi" in facts[0].content.lower()
        assert facts[0].confidence == 0.8

    def test_extracts_multiple_facts(
        self, learner: FactLearner, stub_extract,
    ) -> None:
        stub_extract.return_value = LearnedFactBatch(facts=[
            _draft(content="User loves sushi"),
            _draft(
                category="relationship",
                subject="Sarah",
                predicate="colleague",
                content="Sarah is the user's colleague",
                sensitivity_tier=2,
            ),
        ])
        facts = learner.extract_facts_from_conversation(
            user_messages=["I had sushi with Sarah from work today"],
            assistant_messages=["Sounds like a nice lunch!"],
        )
        assert len(facts) == 2
        assert facts[1].subject == "Sarah"

    def test_agent_failure_returns_empty(
        self, learner: FactLearner, stub_extract,
    ) -> None:
        stub_extract.side_effect = RuntimeError("agent down")
        facts = learner.extract_facts_from_conversation(
            user_messages=["I love sushi"],
            assistant_messages=["Great!"],
        )
        assert facts == []

    def test_empty_conversation_returns_empty(
        self, learner: FactLearner,
    ) -> None:
        facts = learner.extract_facts_from_conversation(
            user_messages=[""],
            assistant_messages=[""],
        )
        assert facts == []

    def test_max_facts_limit(
        self, learner: FactLearner, stub_extract,
    ) -> None:
        stub_extract.return_value = LearnedFactBatch(facts=[
            _draft(predicate=f"fact_{i}", content=f"Fact number {i} about the user")
            for i in range(10)
        ])
        facts = learner.extract_facts_from_conversation(
            user_messages=["Lots of info about me"],
            assistant_messages=["Interesting!"],
            max_facts=3,
        )
        assert len(facts) == 3

    def test_empty_batch_returns_empty(
        self, learner: FactLearner, stub_extract,
    ) -> None:
        stub_extract.return_value = LearnedFactBatch(facts=[])
        facts = learner.extract_facts_from_conversation(
            user_messages=["Nothing useful here"],
            assistant_messages=["Ok"],
        )
        assert facts == []


# ================================================================
# Read operations
# ================================================================


class TestGetActiveFacts:
    """Tests for get_active_facts."""

    def test_returns_stored_facts(self, learner: FactLearner) -> None:
        learner.extract_facts_from_conversation(
            user_messages=["I love sushi"],
            assistant_messages=["Great!"],
        )
        facts = learner.get_active_facts()
        assert len(facts) == 1
        assert facts[0].content == "User's favorite food is sushi"

    def test_excludes_dismissed(self, learner: FactLearner) -> None:
        stored = learner.extract_facts_from_conversation(
            user_messages=["I love sushi"],
            assistant_messages=["Great!"],
        )
        learner.dismiss_fact(stored[0].id)
        facts = learner.get_active_facts()
        assert facts == []

    def test_excludes_superseded(
        self, learner: FactLearner, stub_extract,
    ) -> None:
        # First extraction (default sushi fact)
        learner.extract_facts_from_conversation(
            user_messages=["I love sushi"],
            assistant_messages=["Great!"],
        )
        # Second extraction with same predicate (supersedes)
        stub_extract.return_value = LearnedFactBatch(facts=[
            _draft(content="User's favorite food is pizza"),
        ])
        learner.extract_facts_from_conversation(
            user_messages=["Actually I prefer pizza now"],
            assistant_messages=["Pizza is great too!"],
        )
        facts = learner.get_active_facts()
        assert len(facts) == 1
        assert "pizza" in facts[0].content.lower()

    def test_filters_by_category(
        self, learner: FactLearner, stub_extract,
    ) -> None:
        stub_extract.return_value = LearnedFactBatch(facts=[
            _draft(content="User loves sushi"),
            _draft(
                category="work",
                predicate="job_title",
                content="User is a software engineer",
                sensitivity_tier=2,
            ),
        ])
        learner.extract_facts_from_conversation(
            user_messages=["I'm a software engineer who loves sushi"],
            assistant_messages=["Cool!"],
        )
        facts = learner.get_active_facts(category="work")
        assert len(facts) == 1
        assert facts[0].category == "work"

    def test_filters_by_confidence(self, learner: FactLearner) -> None:
        learner.extract_facts_from_conversation(
            user_messages=["I love sushi"],
            assistant_messages=["Great!"],
        )
        # Default confidence is 0.8 — should pass 0.5 threshold
        facts = learner.get_active_facts(min_confidence=0.5)
        assert len(facts) == 1
        # But not 0.9 threshold
        facts = learner.get_active_facts(min_confidence=0.9)
        assert facts == []

    def test_empty_table(self, learner_bare: FactLearner) -> None:
        facts = learner_bare.get_active_facts()
        assert facts == []


class TestGetFactsForReview:
    """Tests for get_facts_for_review."""

    def test_returns_unconfirmed_facts(self, learner: FactLearner) -> None:
        learner.extract_facts_from_conversation(
            user_messages=["I love sushi"],
            assistant_messages=["Great!"],
        )
        facts = learner.get_facts_for_review()
        assert len(facts) == 1

    def test_excludes_confirmed(self, learner: FactLearner) -> None:
        stored = learner.extract_facts_from_conversation(
            user_messages=["I love sushi"],
            assistant_messages=["Great!"],
        )
        learner.confirm_fact(stored[0].id)
        facts = learner.get_facts_for_review()
        assert facts == []

    def test_excludes_dismissed(self, learner: FactLearner) -> None:
        stored = learner.extract_facts_from_conversation(
            user_messages=["I love sushi"],
            assistant_messages=["Great!"],
        )
        learner.dismiss_fact(stored[0].id)
        facts = learner.get_facts_for_review()
        assert facts == []


class TestGetFactCount:
    """Tests for get_fact_count."""

    def test_empty(self, learner_bare: FactLearner) -> None:
        counts = learner_bare.get_fact_count()
        assert counts["total"] == 0
        assert counts["confirmed"] == 0
        assert counts["pending_review"] == 0

    def test_with_facts(self, learner: FactLearner) -> None:
        learner.extract_facts_from_conversation(
            user_messages=["I love sushi"],
            assistant_messages=["Great!"],
        )
        counts = learner.get_fact_count()
        assert counts["total"] == 1
        assert counts["pending_review"] == 1
        assert counts["confirmed"] == 0


# ================================================================
# Feedback
# ================================================================


class TestFeedback:
    """Tests for confirm_fact, dismiss_fact, edit_fact."""

    def test_confirm_sets_confidence_to_1(
        self, learner: FactLearner,
    ) -> None:
        stored = learner.extract_facts_from_conversation(
            user_messages=["I love sushi"],
            assistant_messages=["Great!"],
        )
        learner.confirm_fact(stored[0].id)
        facts = learner.get_active_facts()
        assert len(facts) == 1
        assert facts[0].confidence == 1.0
        assert facts[0].confirmed_at is not None

    def test_dismiss_removes_from_active(
        self, learner: FactLearner,
    ) -> None:
        stored = learner.extract_facts_from_conversation(
            user_messages=["I love sushi"],
            assistant_messages=["Great!"],
        )
        learner.dismiss_fact(stored[0].id)
        facts = learner.get_active_facts()
        assert facts == []

    def test_edit_updates_content_and_confirms(
        self, learner: FactLearner,
    ) -> None:
        stored = learner.extract_facts_from_conversation(
            user_messages=["I love sushi"],
            assistant_messages=["Great!"],
        )
        learner.edit_fact(stored[0].id, "User's favorite food is ramen")
        facts = learner.get_active_facts()
        assert len(facts) == 1
        assert "ramen" in facts[0].content
        assert facts[0].confidence == 1.0


# ================================================================
# Contradiction resolution
# ================================================================


class TestContradictionResolution:
    """Tests for _resolve_contradictions."""

    def test_supersedes_old_fact(
        self, learner: FactLearner, stub_extract,
    ) -> None:
        # First fact (default sushi)
        learner.extract_facts_from_conversation(
            user_messages=["I live in Berlin"],
            assistant_messages=["Nice city!"],
        )
        # Second fact with same predicate
        stub_extract.return_value = LearnedFactBatch(facts=[
            _draft(
                category="location",
                content="User now lives in Tokyo",
                sensitivity_tier=2,
            ),
        ])
        learner.extract_facts_from_conversation(
            user_messages=["I moved to Tokyo"],
            assistant_messages=["Exciting!"],
        )
        # Both exist in DB but only newest is active above the threshold
        active_facts = learner.get_active_facts(min_confidence=0.5)
        assert len(active_facts) == 1
        assert "tokyo" in active_facts[0].content.lower()


# ================================================================
# Sensitivity tiers
# ================================================================


class TestSensitivityTier:
    """Tests for sensitivity tier handling."""

    def test_tier_from_extraction(
        self, learner: FactLearner, stub_extract,
    ) -> None:
        stub_extract.return_value = LearnedFactBatch(facts=[
            _draft(
                category="health",
                predicate="medical_condition",
                content="User has asthma",
                sensitivity_tier=3,
            ),
        ])
        facts = learner.extract_facts_from_conversation(
            user_messages=["I have asthma"],
            assistant_messages=["I see."],
        )
        assert facts[0].sensitivity_tier == 3


# ================================================================
# Usage tracking
# ================================================================


class TestUsageTracking:
    """Tests for increment_usage."""

    def test_increments_times_used(self, learner: FactLearner) -> None:
        stored = learner.extract_facts_from_conversation(
            user_messages=["I love sushi"],
            assistant_messages=["Great!"],
        )
        assert stored[0].times_used == 0
        learner.increment_usage([stored[0].id])
        facts = learner.get_active_facts()
        assert facts[0].times_used == 1

    def test_empty_ids_noop(self, learner: FactLearner) -> None:
        learner.increment_usage([])  # should not raise


# ================================================================
# Parsing helpers
# ================================================================


class TestParseExtractionResult:
    """Tests for parse_llm_json_array (still used elsewhere in core)."""

    def test_parses_list(self) -> None:
        result = [{"content": "test", "predicate": "x"}]
        assert parse_llm_json_array(result) == result

    def test_parses_wrapped_dict(self) -> None:
        result = {"facts": [{"content": "test", "predicate": "x"}]}
        assert len(parse_llm_json_array(result)) == 1

    def test_parses_single_fact(self) -> None:
        result = {"content": "test", "predicate": "x"}
        assert len(parse_llm_json_array(result)) == 1

    def test_empty_dict_returns_empty(self) -> None:
        assert parse_llm_json_array({}) == []

    def test_handles_results_key(self) -> None:
        result = {"results": [{"content": "test", "predicate": "x"}]}
        assert len(parse_llm_json_array(result)) == 1


# ================================================================
# Categories
# ================================================================


class TestCategories:
    """Basic sanity checks on category constants."""

    def test_has_expected_categories(self) -> None:
        assert "preference" in CATEGORIES
        assert "relationship" in CATEGORIES
        assert "biographical" in CATEGORIES
        assert "habit" in CATEGORIES
        assert "health" in CATEGORIES
        assert "work" in CATEGORIES
        assert "location" in CATEGORIES

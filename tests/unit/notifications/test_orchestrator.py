"""Tests for BrainNotificationOrchestrator (rule-based).

The orchestrator now uses deterministic rules instead of LLM calls.
Tests verify the rule engine logic directly.

sensitivity_tier: N/A — test infrastructure
"""

from __future__ import annotations

from pathlib import Path

import pytest
from src.core.sqlite.engine import DatabaseEngine
from src.notifications.orchestrator import (
    BrainNotificationOrchestrator,
)
from src.notifications.preference_service import PreferenceService

# ================================================================
# Fixtures
# ================================================================


@pytest.fixture()
def tmp_db(tmp_path: Path) -> DatabaseEngine:
    """Fresh DuckDB engine."""
    db_path = tmp_path / "test_orchestrator.duckdb"
    engine = DatabaseEngine(db_path=db_path)
    yield engine
    engine.close()


@pytest.fixture()
def prefs(tmp_db: DatabaseEngine) -> PreferenceService:
    """PreferenceService wired to temp DB."""
    return PreferenceService(db_engine=tmp_db)


@pytest.fixture()
def orchestrator(
    prefs: PreferenceService,
) -> BrainNotificationOrchestrator:
    """Orchestrator (no BrainAgent needed — rule-based)."""
    return BrainNotificationOrchestrator(
        preference_service=prefs,
    )


# ================================================================
# Pipeline evaluation
# ================================================================


class TestPipelineEvaluation:
    """Tests for evaluate_pipeline_result."""

    def test_failed_pipeline_notifies(
        self, orchestrator: BrainNotificationOrchestrator,
    ) -> None:
        """Failed pipeline → should_notify=True."""
        decision = orchestrator.evaluate_pipeline_result(
            run_result={
                "run_id": "r1",
                "status": "failed",
                "error": "OOM",
            },
            stats={},
        )
        assert decision.should_notify is True
        assert decision.category == "pipeline_summary"
        assert decision.importance_score == 8.0
        assert "failed" in decision.message.lower()

    def test_successful_pipeline_no_notify(
        self, orchestrator: BrainNotificationOrchestrator,
    ) -> None:
        """Routine success → should_notify=False."""
        decision = orchestrator.evaluate_pipeline_result(
            run_result={"run_id": "r2", "status": "success"},
            stats={},
        )
        assert decision.should_notify is False

    def test_skips_when_globally_muted(
        self,
        orchestrator: BrainNotificationOrchestrator,
        prefs: PreferenceService,
    ) -> None:
        """Globally muted → skip even on failure."""
        prefs.mute_all()
        decision = orchestrator.evaluate_pipeline_result(
            run_result={
                "run_id": "r3",
                "status": "failed",
                "error": "err",
            },
            stats={},
        )
        assert decision.should_notify is False
        assert "muted" in decision.reason.lower()

    def test_skips_when_category_disabled(
        self,
        orchestrator: BrainNotificationOrchestrator,
        prefs: PreferenceService,
    ) -> None:
        """Disabled pipeline_summary → should_notify=False."""
        prefs.update_preference(
            "pipeline_summary", enabled=False,
        )
        decision = orchestrator.evaluate_pipeline_result(
            run_result={
                "run_id": "r4",
                "status": "failed",
                "error": "err",
            },
            stats={},
        )
        assert decision.should_notify is False
        assert "disabled" in decision.reason.lower()


# ================================================================
# Action evaluation
# ================================================================


class TestActionEvaluation:
    """Tests for evaluate_action_result."""

    def test_action_success_notifies(
        self, orchestrator: BrainNotificationOrchestrator,
    ) -> None:
        """Successful action → should_notify=True."""
        decision = orchestrator.evaluate_action_result(
            action_result={"status": "success"},
            proposal={
                "proposal_id": "p1",
                "tool_name": "create_event",
            },
        )
        assert decision.should_notify is True
        assert decision.category == "action_results"
        assert decision.importance_score == 6.0

    def test_action_failure_higher_importance(
        self, orchestrator: BrainNotificationOrchestrator,
    ) -> None:
        """Failed action → importance=8."""
        decision = orchestrator.evaluate_action_result(
            action_result={"status": "error"},
            proposal={
                "proposal_id": "p2",
                "tool_name": "send_message",
            },
        )
        assert decision.should_notify is True
        assert decision.importance_score == 8.0
        assert "failed" in decision.message.lower()

    def test_dedupe_key_is_deterministic(
        self, orchestrator: BrainNotificationOrchestrator,
    ) -> None:
        """Same inputs produce the same dedup key."""
        d1 = orchestrator.evaluate_action_result(
            action_result={"status": "success"},
            proposal={"proposal_id": "p3"},
        )
        d2 = orchestrator.evaluate_action_result(
            action_result={"status": "success"},
            proposal={"proposal_id": "p3"},
        )
        assert d1.dedupe_key == d2.dedupe_key
        assert d1.dedupe_key != ""


# ================================================================
# Dedup
# ================================================================


class TestDedup:
    """Dedup integration tests."""

    def test_dedup_blocks_second_notification(
        self,
        orchestrator: BrainNotificationOrchestrator,
        prefs: PreferenceService,
    ) -> None:
        """Sending a notification then evaluating same → dedup."""
        from src.notifications.models import NotificationRecord

        d1 = orchestrator.evaluate_action_result(
            action_result={"status": "success"},
            proposal={
                "proposal_id": "dup_action",
                "tool_name": "test",
            },
        )
        assert d1.should_notify is True

        # Simulate logging the sent notification
        prefs.log_notification(
            NotificationRecord(
                id=prefs.new_record_id(),
                dedupe_key=d1.dedupe_key,
                category=d1.category,
                importance_score=d1.importance_score,
                decision="send",
                delivery_status="sent",
                message=d1.message,
                opt_out_text="",
                source_type="action",
                source_id="dup_action",
            ),
        )

        # Second evaluation should be deduped
        d2 = orchestrator.evaluate_action_result(
            action_result={"status": "success"},
            proposal={
                "proposal_id": "dup_action",
                "tool_name": "test",
            },
        )
        assert d2.should_notify is False
        assert "duplicate" in d2.reason.lower()


# ================================================================
# Insight evaluation
# ================================================================


class TestInsightEvaluation:
    """Tests for evaluate_insight_result."""

    def test_high_importance_insight_notifies(
        self, orchestrator: BrainNotificationOrchestrator,
    ) -> None:
        """Health anomaly insight → should_notify=True."""
        insights = [
            {
                "id": "ins_1",
                "domain": "health",
                "title": "Sleep anomaly detected",
                "importance": 8,
                "content": "Health anomaly: sleep dropped.",
            },
        ]
        decision = orchestrator.evaluate_insight_result(insights)
        assert decision.should_notify is True
        assert decision.importance_score >= 7.0

    def test_generic_insight_no_notify(
        self, orchestrator: BrainNotificationOrchestrator,
    ) -> None:
        """Generic low-importance insight → should_notify=False."""
        insights = [
            {
                "id": "ins_2",
                "domain": "general",
                "title": "You asked about music 3 times",
                "importance": 2,
            },
        ]
        decision = orchestrator.evaluate_insight_result(insights)
        assert decision.should_notify is False

    def test_empty_insights_returns_no_notify(
        self, orchestrator: BrainNotificationOrchestrator,
    ) -> None:
        """Empty insights list → skip."""
        decision = orchestrator.evaluate_insight_result([])
        assert decision.should_notify is False

    def test_passes_insights_as_event_context(
        self, orchestrator: BrainNotificationOrchestrator,
    ) -> None:
        """Insights are included in event context when notifying."""
        insights = [
            {
                "id": "ins_3",
                "domain": "health",
                "title": "Health anomaly urgent",
                "importance": 9,
                "content": "Urgent health anomaly detected.",
            },
        ]
        decision = orchestrator.evaluate_insight_result(insights)
        assert "insights" in decision.event_context

    def test_uses_first_insight_id_for_dedup(
        self, orchestrator: BrainNotificationOrchestrator,
    ) -> None:
        """Dedup key uses first insight ID (deterministic)."""
        insights = [
            {
                "id": "ins_first",
                "domain": "health",
                "title": "Emergency health anomaly",
                "importance": 9,
                "content": "Urgent health anomaly detected.",
            },
            {
                "id": "ins_second",
                "domain": "work",
                "title": "B",
            },
        ]
        d1 = orchestrator.evaluate_insight_result(insights)
        d2 = orchestrator.evaluate_insight_result(insights)
        # Both should produce the same dedup key
        assert d1.dedupe_key == d2.dedupe_key

    def test_skips_when_globally_muted(
        self,
        orchestrator: BrainNotificationOrchestrator,
        prefs: PreferenceService,
    ) -> None:
        """Globally muted → skip."""
        prefs.mute_all()
        decision = orchestrator.evaluate_insight_result(
            [
                {
                    "id": "ins_muted",
                    "domain": "health",
                    "title": "Health anomaly",
                    "importance": 9,
                    "content": "Health anomaly detected.",
                },
            ],
        )
        assert decision.should_notify is False
        assert "muted" in decision.reason.lower()

    def test_insight_boosted_by_db_topic(
        self,
        tmp_db: DatabaseEngine,
        prefs: PreferenceService,
    ) -> None:
        """Insight mentioning a DB contact topic gets boosted score."""
        # Create mart_contact_summary with a high-importance topic
        tmp_db.execute("""
            CREATE TABLE IF NOT EXISTS mart_contact_summary (
                contact_name VARCHAR,
                top_topic VARCHAR,
                max_topic_importance INTEGER,
                active_topics_json VARCHAR,
                messages_7d INTEGER,
                notification_priority INTEGER,
                days_since_last INTEGER
            )
        """)
        tmp_db.execute(
            "INSERT INTO mart_contact_summary VALUES "
            "(?, ?, ?, ?, ?, ?, ?)",
            [
                "Maria",
                "father's cancer treatment",
                9,
                '[{"topic": "father''s cancer treatment"}]',
                5,
                80,
                1,
            ],
        )

        orch = BrainNotificationOrchestrator(
            preference_service=prefs,
            db_engine=tmp_db,
        )

        # This insight mentions Maria — should get boosted
        insights = [
            {
                "id": "ins_maria",
                "domain": "health",
                "title": "Maria update",
                "importance": 2,
                "content": "Maria sent updates about treatment.",
            },
        ]
        decision = orch.evaluate_insight_result(insights)
        # Score: 2 (importance) + 2 (health keyword) + 9 (topic match)
        # = 13 > 7 threshold → should notify
        assert decision.should_notify is True

    def test_insight_not_boosted_without_db(
        self,
        orchestrator: BrainNotificationOrchestrator,
    ) -> None:
        """Without DB, low-importance insight about a person → no notify."""
        insights = [
            {
                "id": "ins_no_db",
                "domain": "general",
                "title": "Maria update",
                "importance": 2,
                "content": "Maria sent updates about treatment.",
            },
        ]
        decision = orchestrator.evaluate_insight_result(insights)
        # Score: 2 (importance) + 2 (treatment keyword) = 4 < 7
        assert decision.should_notify is False


# ================================================================
# Topic update evaluation
# ================================================================


class TestBackwardsCompatNoDb:
    """Orchestrator without db_engine still works for all methods."""

    def test_backwards_compat_no_db(
        self,
        prefs: PreferenceService,
    ) -> None:
        orch = BrainNotificationOrchestrator(
            preference_service=prefs,
        )
        # Pipeline
        d = orch.evaluate_pipeline_result(
            run_result={"status": "failed", "error": "x"},
            stats={},
        )
        assert d.should_notify is True

        # Action
        d = orch.evaluate_action_result(
            action_result={"status": "success"},
            proposal={"tool_name": "test"},
        )
        assert d.should_notify is True

        # Insight (no DB = no topic boost, relies on keywords)
        d = orch.evaluate_insight_result([
            {"id": "i1", "importance": 2, "title": "generic"},
        ])
        assert d.should_notify is False

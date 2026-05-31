"""Tests for the Pipeline Brain smart refresh orchestrator.

Covers:
- RefreshPlan data class operations (add, skip, get_ordered, summary, to_dict)
- PipelineBrain.plan_refresh() tier logic (critical, high, medium, low, skipped)
- _has_stale_sources helper
- _get_models_for_domain helper
- Duration estimation scaling
- Edge cases (empty DB, no stale data, ext models)

sensitivity_tier: 1
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from unittest.mock import MagicMock

from src.pipeline.pipeline_brain import (
    ALWAYS_RUN,
    DOMAIN_MODELS,
    MODEL_SOURCE_TABLES,
    PipelineBrain,
    PlannedModel,
    RefreshPlan,
    SkippedModel,
    _get_models_for_domain,
    _has_stale_sources,
    _map_sqlite_type,
)

# ---------------------------------------------------------------------------
# Helpers — lightweight stubs for QueryTracker and PipelineRunner
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FakeInterestArea:
    """Mimics src.core.query_tracker.InterestArea."""

    domain: str
    label: str
    description: str = ""
    weight: float = 0.0
    query_count: int = 0
    queries_per_week: float = 0.0
    trending: bool = False
    explicit: bool = False
    raw_tables: tuple[str, ...] = ()
    mart: str | None = None


@dataclass(frozen=True)
class FakeDomainStats:
    """Mimics src.core.query_tracker.DomainStats."""

    domain: str
    total_queries: int = 0
    last_queried_at: str | None = None
    trend: str = "stable"
    queries_last_7d: int = 0
    queries_last_30d: int = 0


@dataclass
class FakePipelineEstimate:
    """Mimics src.pipeline.stats.PipelineEstimate."""

    estimated_duration_seconds: float = 60.0
    models_to_process: list[str] | None = None
    estimated_rows: dict[str, int] | None = None
    last_run_at: Any = None
    pending_changes: dict[str, int] | None = None


def _make_tracker(
    interests: list[FakeInterestArea] | None = None,
    domain_stats: list[FakeDomainStats] | None = None,
) -> MagicMock:
    """Build a mock QueryTracker."""
    tracker = MagicMock()
    tracker.get_interest_profile.return_value = interests or []
    tracker.get_domain_stats.return_value = domain_stats or []
    return tracker


def _get_core_model_names() -> list[str]:
    """Load core model names from the pipeline manifest."""
    from src.pipeline.manifest import load_manifest

    manifest = load_manifest()
    return manifest.model_names


def _make_runner(
    pending: dict[str, int] | None = None,
    model_names: list[str] | None = None,
    estimate_seconds: float = 60.0,
) -> MagicMock:
    """Build a mock PipelineRunner."""
    runner = MagicMock()
    runner.get_pending_changes.return_value = pending or {}
    runner._all_model_names = (
        _get_core_model_names() if model_names is None
        else model_names
    )
    runner.dry_run.return_value = FakePipelineEstimate(
        estimated_duration_seconds=estimate_seconds,
    )
    return runner


# ---------------------------------------------------------------------------
# TestRefreshPlan — data class operations
# ---------------------------------------------------------------------------


class TestRefreshPlan:
    """Tests for the RefreshPlan data class."""

    def test_add_appends_planned_model(self) -> None:
        plan = RefreshPlan()
        plan.add("stg_messages", "critical", "Dashboard dep")
        assert len(plan.models) == 1
        assert plan.models[0] == PlannedModel(
            name="stg_messages",
            priority="critical",
            reason="Dashboard dep",
        )

    def test_skip_appends_skipped_model(self) -> None:
        plan = RefreshPlan()
        plan.skip("mart_health", "No new data")
        assert len(plan.skipped) == 1
        assert plan.skipped[0] == SkippedModel(
            name="mart_health",
            reason="No new data",
        )

    def test_get_ordered_sorts_by_priority(self) -> None:
        plan = RefreshPlan()
        plan.add("model_low", "low", "r1")
        plan.add("model_critical", "critical", "r2")
        plan.add("model_high", "high", "r3")
        plan.add("model_medium", "medium", "r4")
        ordered = plan.get_ordered()
        assert ordered == [
            "model_critical",
            "model_high",
            "model_medium",
            "model_low",
        ]

    def test_summary_format(self) -> None:
        plan = RefreshPlan()
        plan.add("m1", "critical", "r")
        plan.add("m2", "critical", "r")
        plan.add("m3", "high", "r")
        plan.skip("m4", "no data")
        plan.skip("m5", "no data")
        result = plan.summary()
        assert "2 critical" in result
        assert "1 high" in result
        assert "0 medium" in result
        assert "0 low" in result
        assert "2 skipped" in result

    def test_to_dict_serialization(self) -> None:
        plan = RefreshPlan(
            estimated_duration_seconds=8.5,
            full_duration_seconds=22.0,
        )
        plan.add("stg_messages", "critical", "Dashboard dep")
        plan.skip("mart_health", "No new data")
        d = plan.to_dict()
        assert len(d["models"]) == 1
        assert d["models"][0]["name"] == "stg_messages"
        assert d["models"][0]["priority"] == "critical"
        assert len(d["skipped"]) == 1
        assert d["estimated_duration_seconds"] == 8.5
        assert d["full_duration_seconds"] == 22.0
        assert isinstance(d["summary"], str)

    def test_empty_plan_get_ordered(self) -> None:
        plan = RefreshPlan()
        assert plan.get_ordered() == []

    def test_empty_plan_summary(self) -> None:
        plan = RefreshPlan()
        result = plan.summary()
        assert "0 critical" in result
        assert "0 skipped" in result


# ---------------------------------------------------------------------------
# TestHasStaleSources
# ---------------------------------------------------------------------------


class TestHasStaleSources:
    """Tests for the _has_stale_sources helper."""

    def test_known_model_with_matching_stale_table(self) -> None:
        assert _has_stale_sources(
            "stg_messages", {"raw_messages"},
        )

    def test_known_model_no_stale_sources(self) -> None:
        assert not _has_stale_sources(
            "stg_messages", {"raw_contacts"},
        )

    def test_known_model_partial_overlap(self) -> None:
        # mart_today depends on raw_calendar_events, raw_messages, raw_notes
        assert _has_stale_sources(
            "mart_today", {"raw_calendar_events"},
        )

    def test_unknown_extension_model_any_stale(self) -> None:
        assert _has_stale_sources(
            "ext_stg_music_spotify", {"raw_messages"},
        )

    def test_unknown_extension_model_empty_stale(self) -> None:
        assert not _has_stale_sources(
            "ext_stg_music_spotify", set(),
        )

    def test_empty_stale_set_always_false_for_known(self) -> None:
        assert not _has_stale_sources(
            "stg_messages", set(),
        )

    def test_health_model_stale_only_on_health_data(self) -> None:
        assert _has_stale_sources(
            "mart_health", {"raw_health_metrics"},
        )
        assert not _has_stale_sources(
            "mart_health", {"raw_messages", "raw_contacts"},
        )


# ---------------------------------------------------------------------------
# TestGetModelsForDomain
# ---------------------------------------------------------------------------


class TestGetModelsForDomain:
    """Tests for _get_models_for_domain helper."""

    def test_calendar_domain(self) -> None:
        available = set(MODEL_SOURCE_TABLES.keys())
        models = _get_models_for_domain("calendar", available)
        assert "stg_calendar_events" in models
        assert "mart_today" in models

    def test_unknown_domain_empty(self) -> None:
        available = set(MODEL_SOURCE_TABLES.keys())
        assert _get_models_for_domain("unknown", available) == []

    def test_filters_by_available(self) -> None:
        # Only staging models available
        available = {"stg_calendar_events", "stg_reminders"}
        models = _get_models_for_domain("calendar", available)
        assert "stg_calendar_events" in models
        assert "mart_today" not in models

    def test_includes_extension_models(self) -> None:
        available = {
            "stg_messages",
            "ext_stg_music_spotify",
            "ext_mart_music_trends",
        }
        models = _get_models_for_domain("music", available)
        assert "ext_stg_music_spotify" in models
        assert "ext_mart_music_trends" in models

    def test_extension_models_not_matched_for_wrong_domain(self) -> None:
        available = {"ext_stg_music_spotify"}
        models = _get_models_for_domain("health", available)
        assert "ext_stg_music_spotify" not in models


# ---------------------------------------------------------------------------
# TestPlanRefresh — full plan generation
# ---------------------------------------------------------------------------


class TestPlanRefresh:
    """Tests for PipelineBrain.plan_refresh() tier logic."""

    def test_no_pending_changes_all_skipped(self) -> None:
        """When no tables have new data, all models are skipped."""
        tracker = _make_tracker()
        runner = _make_runner(pending={
            "raw_messages": 0,
            "raw_calendar_events": 0,
        })
        brain = PipelineBrain(query_tracker=tracker, pipeline_runner=runner)
        plan = brain.plan_refresh()
        assert len(plan.models) == 0
        assert len(plan.skipped) == len(runner._all_model_names)

    def test_tier1_always_includes_dashboard_with_stale(self) -> None:
        """Tier 1 dashboard models are critical when stale."""
        tracker = _make_tracker()
        runner = _make_runner(pending={
            "raw_messages": 10,
            "raw_calendar_events": 5,
            "raw_contacts": 2,
            "raw_notes": 3,
        })
        brain = PipelineBrain(query_tracker=tracker, pipeline_runner=runner)
        plan = brain.plan_refresh()

        planned_names = {m.name for m in plan.models}
        critical_names = {
            m.name for m in plan.models if m.priority == "critical"
        }

        for model in ALWAYS_RUN:
            assert model in planned_names, f"{model} should be planned"
            assert model in critical_names, f"{model} should be critical"

    def test_tier2_top_interest_with_new_data(self) -> None:
        """High-weight interest domains get 'high' priority."""
        interests = [
            FakeInterestArea(
                domain="health",
                label="Health & Wellness",
                weight=0.9,
                query_count=20,
            ),
        ]
        stats = [
            FakeDomainStats(domain="health", queries_last_7d=5),
        ]
        tracker = _make_tracker(interests=interests, domain_stats=stats)
        runner = _make_runner(pending={"raw_health_metrics": 15})
        brain = PipelineBrain(query_tracker=tracker, pipeline_runner=runner)
        plan = brain.plan_refresh()

        high_names = {m.name for m in plan.models if m.priority == "high"}
        assert "stg_health_metrics" in high_names
        assert "mart_health" in high_names

    def test_tier2_limited_to_top_3(self) -> None:
        """Only top 3 interest domains get 'high' priority."""
        interests = [
            FakeInterestArea(domain="health", label="Health", weight=0.9),
            FakeInterestArea(domain="calendar", label="Calendar", weight=0.8),
            FakeInterestArea(domain="work", label="Work", weight=0.7),
            FakeInterestArea(domain="messages", label="Messages", weight=0.6),
        ]
        stats = [
            FakeDomainStats(domain=i.domain, queries_last_7d=5)
            for i in interests
        ]
        tracker = _make_tracker(interests=interests, domain_stats=stats)
        # All tables stale
        pending = {
            "raw_health_metrics": 10,
            "raw_calendar_events": 10,
            "raw_messages": 10,
            "raw_notes": 10,
            "raw_contacts": 10,
            "raw_emails": 10,
            "raw_reminders": 10,
        }
        runner = _make_runner(pending=pending)
        brain = PipelineBrain(query_tracker=tracker, pipeline_runner=runner)
        plan = brain.plan_refresh()

        high_models = [m for m in plan.models if m.priority == "high"]
        # Messages domain (4th) should NOT appear as high — its unique models
        # (int_communications_enriched, mart_communications) should be
        # medium (tier 3) since queries_last_7d > 0
        high_reasons = {m.reason for m in high_models}
        assert not any("Messages" in r for r in high_reasons)

    def test_tier3_recent_query_domain(self) -> None:
        """Domains queried in last 7 days get 'medium' priority."""
        interests = [
            FakeInterestArea(
                domain="notes",
                label="Notes & Ideas",
                weight=0.3,
                query_count=3,
            ),
        ]
        stats = [
            FakeDomainStats(domain="notes", queries_last_7d=2),
        ]
        tracker = _make_tracker(interests=interests, domain_stats=stats)
        runner = _make_runner(pending={"raw_notes": 5})
        brain = PipelineBrain(query_tracker=tracker, pipeline_runner=runner)
        plan = brain.plan_refresh()

        medium_names = {m.name for m in plan.models if m.priority == "medium"}
        assert "stg_notes" in medium_names

    def test_tier3_skips_top_interests(self) -> None:
        """Tier 3 doesn't duplicate models already in tier 2."""
        interests = [
            FakeInterestArea(
                domain="health",
                label="Health",
                weight=0.9,
                query_count=20,
            ),
        ]
        stats = [
            FakeDomainStats(domain="health", queries_last_7d=10),
        ]
        tracker = _make_tracker(interests=interests, domain_stats=stats)
        runner = _make_runner(pending={"raw_health_metrics": 5})
        brain = PipelineBrain(query_tracker=tracker, pipeline_runner=runner)
        plan = brain.plan_refresh()

        # Health models should be high (tier 2), not medium (tier 3)
        health_models = [
            m for m in plan.models
            if "health" in m.name.lower()
        ]
        for m in health_models:
            assert m.priority == "high", (
                f"{m.name} should be high, not {m.priority}"
            )

    def test_tier4_new_data_low_interest(self) -> None:
        """New data in unqueried domain → staging only at 'low' priority."""
        tracker = _make_tracker()  # No interests
        runner = _make_runner(pending={"raw_health_metrics": 50})
        brain = PipelineBrain(query_tracker=tracker, pipeline_runner=runner)
        plan = brain.plan_refresh()

        low_names = {m.name for m in plan.models if m.priority == "low"}
        assert "stg_health_metrics" in low_names
        # Mart should be skipped (not in tier 4)
        planned_names = {m.name for m in plan.models}
        assert "mart_health" not in planned_names

    def test_model_appears_once_highest_priority(self) -> None:
        """A model appearing in multiple tiers uses the highest priority."""
        interests = [
            FakeInterestArea(
                domain="calendar",
                label="Calendar",
                weight=0.9,
            ),
        ]
        stats = [
            FakeDomainStats(domain="calendar", queries_last_7d=5),
        ]
        tracker = _make_tracker(interests=interests, domain_stats=stats)
        runner = _make_runner(pending={"raw_calendar_events": 10})
        brain = PipelineBrain(query_tracker=tracker, pipeline_runner=runner)
        plan = brain.plan_refresh()

        # stg_calendar_events is in ALWAYS_RUN (critical) AND
        # calendar domain (high). Should appear only once, as critical.
        stg_cal = [
            m for m in plan.models
            if m.name == "stg_calendar_events"
        ]
        assert len(stg_cal) == 1
        assert stg_cal[0].priority == "critical"

    def test_duration_estimation_scales(self) -> None:
        """Estimated duration scales with the ratio of planned models."""
        tracker = _make_tracker()
        runner = _make_runner(
            pending={"raw_health_metrics": 5},
            estimate_seconds=60.0,
        )
        brain = PipelineBrain(query_tracker=tracker, pipeline_runner=runner)
        plan = brain.plan_refresh()

        # Only 1 model (stg_health_metrics) planned out of 17 total
        assert plan.estimated_duration_seconds < plan.full_duration_seconds
        assert plan.full_duration_seconds == 60.0

    def test_extension_models_included_when_stale(self) -> None:
        """Extension models are included when any table is stale."""
        model_names = _get_core_model_names() + [
            "ext_stg_music_spotify",
        ]
        interests = [
            FakeInterestArea(
                domain="music",
                label="Music",
                weight=0.9,
            ),
        ]
        stats = [
            FakeDomainStats(domain="music", queries_last_7d=5),
        ]
        tracker = _make_tracker(interests=interests, domain_stats=stats)
        runner = _make_runner(
            pending={"raw_messages": 3},
            model_names=model_names,
        )
        brain = PipelineBrain(query_tracker=tracker, pipeline_runner=runner)
        plan = brain.plan_refresh()

        planned_names = {m.name for m in plan.models}
        assert "ext_stg_music_spotify" in planned_names

    def test_duration_estimation_fallback(self) -> None:
        """Falls back to 60.0 when dry_run raises."""
        tracker = _make_tracker()
        runner = _make_runner(pending={"raw_messages": 5})
        runner.dry_run.side_effect = RuntimeError("DuckDB unavailable")
        brain = PipelineBrain(query_tracker=tracker, pipeline_runner=runner)
        plan = brain.plan_refresh()
        # Should not raise, uses 60.0 fallback
        assert plan.full_duration_seconds == 60.0

    def test_empty_available_models(self) -> None:
        """Handles runner with no models gracefully."""
        tracker = _make_tracker()
        runner = _make_runner(
            pending={"raw_messages": 5},
            model_names=[],
        )
        brain = PipelineBrain(query_tracker=tracker, pipeline_runner=runner)
        plan = brain.plan_refresh()
        assert len(plan.models) == 0
        assert len(plan.skipped) == 0

    def test_all_tables_stale_all_domains_active(self) -> None:
        """Full stale scenario — all models should be planned."""
        interests = [
            FakeInterestArea(domain="calendar", label="Cal", weight=0.9),
            FakeInterestArea(domain="health", label="Health", weight=0.8),
            FakeInterestArea(domain="messages", label="Msgs", weight=0.7),
            FakeInterestArea(domain="contacts", label="People", weight=0.6),
            FakeInterestArea(domain="work", label="Work", weight=0.5),
            FakeInterestArea(domain="notes", label="Notes", weight=0.3),
        ]
        stats = [
            FakeDomainStats(domain=i.domain, queries_last_7d=5)
            for i in interests
        ]
        pending = {
            "raw_messages": 10,
            "raw_notes": 5,
            "raw_contacts": 3,
            "raw_calendar_events": 8,
            "raw_health_metrics": 12,
            "raw_emails": 4,
            "raw_reminders": 2,
        }
        tracker = _make_tracker(interests=interests, domain_stats=stats)
        runner = _make_runner(pending=pending)
        brain = PipelineBrain(query_tracker=tracker, pipeline_runner=runner)
        plan = brain.plan_refresh()

        planned_names = {m.name for m in plan.models}
        # All core models should be planned (various tiers)
        for model in _get_core_model_names():
            assert model in planned_names, f"{model} should be planned"
        assert len(plan.skipped) == 0


# ---------------------------------------------------------------------------
# TestModelSourceTables — constant integrity
# ---------------------------------------------------------------------------


class TestModelSourceTables:
    """Verify MODEL_SOURCE_TABLES covers all core models."""

    def test_all_core_models_have_source_mapping(self) -> None:
        for model in _get_core_model_names():
            assert model in MODEL_SOURCE_TABLES, (
                f"{model} missing from MODEL_SOURCE_TABLES"
            )

    def test_all_source_tables_are_raw_or_intermediate(self) -> None:
        allowed_prefixes = ("raw_", "int_")
        for model, sources in MODEL_SOURCE_TABLES.items():
            for table in sources:
                assert table.startswith(allowed_prefixes), (
                    f"{model} source '{table}' should start with "
                    f"one of {allowed_prefixes}"
                )

    def test_domain_models_reference_valid_models(self) -> None:
        known = set(MODEL_SOURCE_TABLES.keys())
        for domain, models in DOMAIN_MODELS.items():
            for model in models:
                assert model in known, (
                    f"DOMAIN_MODELS[{domain!r}] references unknown model "
                    f"{model!r}"
                )

    def test_always_run_are_valid_models(self) -> None:
        known = set(MODEL_SOURCE_TABLES.keys())
        for model in ALWAYS_RUN:
            assert model in known, (
                f"ALWAYS_RUN contains unknown model {model!r}"
            )


# ---------------------------------------------------------------------------
# TestOnDemandMartGeneration
# ---------------------------------------------------------------------------


class TestOnDemandMartGeneration:
    """Tests for on-demand mart staging in PipelineBrain."""

    def test_stages_new_mart_for_high_interest_domain(self) -> None:
        tracker = _make_tracker(
            interests=[
                FakeInterestArea(
                    domain="music",
                    label="Music",
                    weight=0.9,
                    raw_tables=("raw_listening_history",),
                    mart=None,
                )
            ],
        )

        db = MagicMock()

        def _query(sql: str, params: list[str] | None = None):
            if "COUNT(*) AS n FROM raw_listening_history" in sql:
                return [{"n": 120}]
            if "PRAGMA table_info" in sql:
                return [
                    {"name": "id", "type": "TEXT"},
                    {"name": "track_name", "type": "TEXT"},
                    {"name": "played_at", "type": "TEXT"},
                ]
            return []

        db.query.side_effect = _query

        runner = _make_runner(pending={})
        runner._db = db
        runner._all_model_names = []

        model_gen = MagicMock()
        model_gen.generate.return_value = MagicMock()
        review = MagicMock()
        review.get_staged.return_value = None

        brain = PipelineBrain(
            query_tracker=tracker,
            pipeline_runner=runner,
            model_generator=model_gen,
            review_flow=review,
        )
        domains = brain.check_demand_for_new_marts()

        assert domains == ["music"]
        model_gen.generate.assert_called_once()
        kwargs = model_gen.generate.call_args.kwargs
        assert kwargs["force_full_pipeline"] is True
        review.stage.assert_called_once()

    def test_skips_when_domain_already_staged(self) -> None:
        tracker = _make_tracker(
            interests=[
                FakeInterestArea(
                    domain="music",
                    label="Music",
                    weight=0.9,
                    raw_tables=("raw_listening_history",),
                    mart=None,
                )
            ],
        )
        runner = _make_runner(pending={})
        runner._db = MagicMock()
        runner._all_model_names = []

        model_gen = MagicMock()
        review = MagicMock()
        review.get_staged.return_value = object()

        brain = PipelineBrain(
            query_tracker=tracker,
            pipeline_runner=runner,
            model_generator=model_gen,
            review_flow=review,
        )
        domains = brain.check_demand_for_new_marts()

        assert domains == []
        model_gen.generate.assert_not_called()
        review.stage.assert_not_called()


class TestTypeMapping:
    """Tests for SQLite -> mapping type normalization."""

    def test_text_type_mapping(self) -> None:
        assert _map_sqlite_type("TEXT") == "TEXT"

    def test_numeric_type_mapping(self) -> None:
        assert _map_sqlite_type("REAL") == "REAL"
        assert _map_sqlite_type("INTEGER") == "INTEGER"

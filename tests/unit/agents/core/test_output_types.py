"""Smoke tests for the Pydantic ports of agent output dataclasses.

The classes themselves are declarative; these tests guard against
accidental loosening of constraints (e.g. removing the intensity
range or the literal categories).

sensitivity_tier: N/A
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError
from src.agents.core.output_types import (
    EgressDecision,
    EmotionalLabel,
    InjectionVerdict,
    LearnedFact,
    Plan,
    PlanStep,
    SensitivityVerdict,
    TriageDecision,
)


def test_sensitivity_verdict_rejects_out_of_range_tier() -> None:
    with pytest.raises(ValidationError):
        SensitivityVerdict(tier=4, reason="x")  # type: ignore[arg-type]


def test_emotional_label_clamps_intensity() -> None:
    with pytest.raises(ValidationError):
        EmotionalLabel(
            primary_emotion="joy", intensity=1.5, domain="personal",
        )
    label = EmotionalLabel(
        primary_emotion="joy", intensity=0.5, domain="personal",
    )
    assert label.intensity == 0.5


def test_triage_decision_round_trip() -> None:
    td = TriageDecision(
        message_id="m1", keep=False, reason="promotional",
        is_promo=True,
    )
    blob = td.model_dump_json()
    revived = TriageDecision.model_validate_json(blob)
    assert revived == td


def test_learned_fact_rejects_unknown_category() -> None:
    with pytest.raises(ValidationError):
        LearnedFact(
            id="f1",
            category="not_a_category",  # type: ignore[arg-type]
            subject="user",
            predicate="likes",
            content="coffee",
            confidence=0.9,
            source_type="chat",
            extracted_at="2026-05-11",
        )


def test_injection_verdict_default_safe_category() -> None:
    v = InjectionVerdict(allowed=True, confidence=0.9, reason="clean")
    assert v.category == "safe"


def test_egress_decision_route_literal() -> None:
    with pytest.raises(ValidationError):
        EgressDecision(
            route="elsewhere",  # type: ignore[arg-type]
            max_tier=1,
        )


def test_plan_with_steps() -> None:
    plan = Plan(
        goal="extract topics",
        steps=[
            PlanStep(id="s1", description="read messages"),
            PlanStep(
                id="s2", description="cluster",
                status="in_progress",
            ),
        ],
    )
    assert len(plan.steps) == 2
    assert plan.revision == 0
    assert plan.steps[1].status == "in_progress"


def test_models_are_frozen() -> None:
    td = TriageDecision(
        message_id="m1", keep=False, reason="x",
    )
    with pytest.raises(ValidationError):
        td.keep = True  # type: ignore[misc]

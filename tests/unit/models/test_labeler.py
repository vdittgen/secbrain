"""Unit tests for the EmotionalLabeler.

The LLM step is delegated to :class:`LabelerAgent` (pydantic-ai); these
tests monkeypatch the agent's ``label`` method directly. Pydantic-ai
enforces the literals on ``primary_emotion`` / ``domain`` and the
[0.0, 1.0] range on ``intensity`` at validation time, so the legacy
``_validate_label`` defaulting logic is no longer relevant.

sensitivity_tier: N/A — test infrastructure
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from src.agents.core.output_types import EmotionalLabel
from src.models.labeler import (
    VALID_DOMAINS,
    VALID_EMOTIONS,
    EmotionalLabeler,
)


def _label(
    *,
    primary_emotion: str = "joy",
    intensity: float = 0.8,
    feelings: list[str] | None = None,
    desires: list[str] | None = None,
    actors: list[str] | None = None,
    environment: str = "office",
    domain: str = "work",
) -> EmotionalLabel:
    """Build an :class:`EmotionalLabel` fixture."""
    return EmotionalLabel(
        primary_emotion=primary_emotion,  # type: ignore[arg-type]
        intensity=intensity,
        feelings=feelings if feelings is not None else ["happy", "grateful"],
        desires=desires if desires is not None else ["connection"],
        actors=actors if actors is not None else ["Alice"],
        environment=environment,
        domain=domain,  # type: ignore[arg-type]
    )


@pytest.fixture()
def stub_label(monkeypatch):
    """Monkey-patch ``LabelerAgent.label`` with a controllable stub."""
    fake = MagicMock(return_value=_label())

    def _bound(self, text):  # noqa: ARG001
        result = fake(text)
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(
        "src.agents.labeler.agent.LabelerAgent.label", _bound,
    )
    return fake


# ---------------------------------------------------------------------------
# EmotionalLabeler.label
# ---------------------------------------------------------------------------


class TestLabelerLabel:
    def test_successful_label(self, stub_label) -> None:
        """A valid SBAgent response is projected into a dict."""
        labeler = EmotionalLabeler()
        result = labeler.label("I had a great day at work!")

        assert result is not None
        assert result["primary_emotion"] == "joy"
        assert result["intensity"] == 0.8
        assert result["domain"] == "work"
        assert "happy" in result["feelings"]
        stub_label.assert_called_once()

    def test_returns_none_when_agent_raises(self, stub_label) -> None:
        """Agent raising → labeler returns None."""
        stub_label.side_effect = RuntimeError("connection refused")
        labeler = EmotionalLabeler()
        assert labeler.label("test text") is None

    def test_returns_none_when_agent_returns_none(
        self, stub_label,
    ) -> None:
        """Agent returning None (LLM validation rejected) → None."""
        stub_label.return_value = None
        labeler = EmotionalLabeler()
        assert labeler.label("test text") is None

    def test_empty_text_short_circuits(self, stub_label) -> None:
        """Empty text returns None without invoking the agent."""
        labeler = EmotionalLabeler()
        assert labeler.label("") is None
        assert stub_label.call_count == 0

    def test_passes_text_to_agent(self, stub_label) -> None:
        """The agent receives the raw text deps."""
        labeler = EmotionalLabeler()
        labeler.label("Hello world")
        assert stub_label.call_args.args[0] == "Hello world"

    def test_normalizes_to_dict_shape(self, stub_label) -> None:
        """All seven legacy keys are present in the projection."""
        stub_label.return_value = _label(
            primary_emotion="sadness", intensity=0.5, domain="personal",
        )
        labeler = EmotionalLabeler()
        result = labeler.label("I feel sad")

        assert result is not None
        assert set(result.keys()) == {
            "primary_emotion", "intensity", "feelings", "desires",
            "actors", "environment", "domain",
        }
        assert result["primary_emotion"] == "sadness"
        assert result["domain"] == "personal"


# ---------------------------------------------------------------------------
# EmotionalLabeler.batch_label
# ---------------------------------------------------------------------------


class TestLabelerBatch:
    def test_batch_returns_list(self, stub_label) -> None:
        """batch_label returns one entry per input text."""
        labeler = EmotionalLabeler()
        results = labeler.batch_label(["text one", "text two", "text three"])

        assert len(results) == 3
        assert all(r is not None for r in results)

    def test_batch_mixed_success_and_failure(self, stub_label) -> None:
        """Per-text errors / None responses surface as None entries."""
        stub_label.side_effect = [
            _label(),
            None,
            _label(primary_emotion="fear"),
        ]
        labeler = EmotionalLabeler()
        results = labeler.batch_label(["ok", "fail", "ok2"])

        assert len(results) == 3
        assert results[0] is not None
        assert results[1] is None
        assert results[2] is not None
        assert results[2]["primary_emotion"] == "fear"

    def test_batch_bails_after_three_consecutive_failures(
        self, stub_label,
    ) -> None:
        """Three consecutive Nones fill the rest with None and bail."""
        stub_label.side_effect = [None, None, None]
        labeler = EmotionalLabeler()
        results = labeler.batch_label(
            ["a", "b", "c", "d", "e"],
        )
        assert len(results) == 5
        assert results == [None, None, None, None, None]
        # After 3 failures the loop should short-circuit.
        assert stub_label.call_count == 3

    def test_batch_empty_list(self) -> None:
        """Empty input → empty output, no agent calls."""
        labeler = EmotionalLabeler()
        assert labeler.batch_label([]) == []


# ---------------------------------------------------------------------------
# Constants sanity
# ---------------------------------------------------------------------------


class TestConstants:
    def test_valid_emotions(self) -> None:
        for emotion in (
            "joy", "sadness", "anger", "fear",
            "surprise", "disgust", "trust", "anticipation",
        ):
            assert emotion in VALID_EMOTIONS

    def test_valid_domains(self) -> None:
        for domain in (
            "personal", "work", "health", "social", "spiritual",
        ):
            assert domain in VALID_DOMAINS

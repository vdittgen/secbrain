"""Tests for skill_registry.py — register, get, list, search, execute."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from src.agent_runtime.skills import Skill, SkillRegistry


def _make_skill(
    skill_id: str = "test-skill",
    name: str = "Test Skill",
    description: str = "A test skill",
    fn: callable = lambda: "ok",
) -> Skill:
    return Skill(
        id=skill_id,
        name=name,
        description=description,
        execute_fn=fn,
    )


class TestRegisterAndGet:
    def test_register_and_get(self) -> None:
        registry = SkillRegistry()
        skill = _make_skill()
        registry.register(skill)
        assert registry.get("test-skill") is skill

    def test_get_unknown_returns_none(self) -> None:
        registry = SkillRegistry()
        assert registry.get("nonexistent") is None


class TestListSkills:
    def test_list_empty(self) -> None:
        registry = SkillRegistry()
        assert registry.list_skills() == []

    def test_list_returns_all(self) -> None:
        registry = SkillRegistry()
        registry.register(_make_skill("a", "Alpha", "first"))
        registry.register(_make_skill("b", "Beta", "second"))
        skills = registry.list_skills()
        assert len(skills) == 2
        ids = {s.id for s in skills}
        assert ids == {"a", "b"}


class TestSearch:
    def test_search_by_name(self) -> None:
        registry = SkillRegistry()
        registry.register(_make_skill("a", "Summarize Text", "summarize"))
        registry.register(_make_skill("b", "Extract Dates", "dates"))
        results = registry.search("summar")
        assert len(results) == 1
        assert results[0].id == "a"

    def test_search_by_description(self) -> None:
        registry = SkillRegistry()
        registry.register(_make_skill("a", "Alpha", "handles date extraction"))
        results = registry.search("date")
        assert len(results) == 1

    def test_search_case_insensitive(self) -> None:
        registry = SkillRegistry()
        registry.register(_make_skill("a", "Summarize", "text"))
        results = registry.search("SUMMAR")
        assert len(results) == 1


class TestExecute:
    def test_execute_calls_function(self) -> None:
        registry = SkillRegistry()
        registry.register(_make_skill(fn=lambda text: text.upper()))
        result = registry.execute("test-skill", text="hello")
        assert result == "HELLO"

    def test_execute_unknown_raises(self) -> None:
        registry = SkillRegistry()
        with pytest.raises(KeyError, match="not found"):
            registry.execute("nonexistent")


class TestBuiltinSkills:
    def test_register_builtin_populates_registry(self) -> None:
        registry = SkillRegistry()
        registry.register_builtin_skills()

        assert registry.get("summarize-text") is not None
        assert registry.get("classify-sentiment") is not None
        assert registry.get("extract-dates") is not None
        assert registry.get("format-markdown") is not None
        assert registry.get("classify-emotion") is not None
        assert registry.get("extract-entities") is not None
        assert registry.get("classify-sensitivity") is not None
        assert len(registry.list_skills()) == 7

    def test_extract_dates_finds_iso_dates(self) -> None:
        registry = SkillRegistry()
        registry.register_builtin_skills()
        result = registry.execute(
            "extract-dates",
            text="Meeting on 2025-06-15 confirmed",
        )
        assert "2025-06-15" in result

    def test_format_markdown_returns_string(self) -> None:
        registry = SkillRegistry()
        registry.register_builtin_skills()
        result = registry.execute(
            "format-markdown",
            text="Hello:\n- Item 1\n- Item 2",
        )
        assert isinstance(result, str)
        assert "- Item 1" in result


class TestClassifyEmotionSkill:
    def test_registered(self) -> None:
        registry = SkillRegistry()
        registry.register_builtin_skills()
        skill = registry.get("classify-emotion")
        assert skill is not None
        assert skill.uses_llm is True
        assert skill.category == "text"


class TestExtractEntitiesSkill:
    def test_registered(self) -> None:
        registry = SkillRegistry()
        registry.register_builtin_skills()
        skill = registry.get("extract-entities")
        assert skill is not None
        assert skill.uses_llm is True
        assert skill.category == "analysis"

    def test_regex_extracts_emails(self) -> None:
        registry = SkillRegistry()
        registry.register_builtin_skills()
        result = registry.execute(
            "extract-entities",
            text="Contact alice@company.com or bob@example.org",
        )
        assert "email" in result
        assert "alice@company.com" in result["email"]
        assert "bob@example.org" in result["email"]

    def test_regex_extracts_dates(self) -> None:
        registry = SkillRegistry()
        registry.register_builtin_skills()
        result = registry.execute(
            "extract-entities",
            text="Meeting on 2025-06-15 confirmed",
        )
        assert "date" in result
        assert "2025-06-15" in result["date"]

    def test_regex_extracts_money(self) -> None:
        registry = SkillRegistry()
        registry.register_builtin_skills()
        result = registry.execute(
            "extract-entities",
            text="Transaction of $1,250 posted",
        )
        assert "money" in result
        assert "$1,250" in result["money"]

    def test_returns_dict(self) -> None:
        registry = SkillRegistry()
        registry.register_builtin_skills()
        result = registry.execute(
            "extract-entities",
            text="No entities here just plain text",
        )
        assert isinstance(result, dict)


class TestClassifySensitivitySkill:
    def test_registered(self) -> None:
        registry = SkillRegistry()
        registry.register_builtin_skills()
        skill = registry.get("classify-sensitivity")
        assert skill is not None
        assert skill.uses_llm is False
        assert skill.category == "analysis"

    @staticmethod
    def _patch_classifier(tier: int):
        target = "src.models.sensitivity_classifier.SensitivityClassifier"
        patcher = patch(target)
        mock_cls = patcher.start()
        mock_cls.return_value.classify.return_value = tier
        return patcher

    def test_tier_3_for_health(self) -> None:
        patcher = self._patch_classifier(3)
        try:
            registry = SkillRegistry()
            registry.register_builtin_skills()
            result = registry.execute(
                "classify-sensitivity",
                text="The patient has been diagnosed with diabetes",
            )
            assert result["tier"] == 3
            assert result["label"] == "high"
        finally:
            patcher.stop()

    def test_tier_2_for_personal(self) -> None:
        patcher = self._patch_classifier(2)
        try:
            registry = SkillRegistry()
            registry.register_builtin_skills()
            result = registry.execute(
                "classify-sensitivity",
                text="Meeting with my boss at the office",
            )
            assert result["tier"] == 2
            assert result["label"] == "medium"
        finally:
            patcher.stop()

    def test_tier_1_for_generic(self) -> None:
        patcher = self._patch_classifier(1)
        try:
            registry = SkillRegistry()
            registry.register_builtin_skills()
            result = registry.execute(
                "classify-sensitivity",
                text="The weather is nice today",
            )
            assert result["tier"] == 1
            assert result["label"] == "low"
        finally:
            patcher.stop()

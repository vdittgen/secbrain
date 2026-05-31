"""User-skill placeholder substitution + LLM routing tests.

sensitivity_tier: 1
"""

from __future__ import annotations

from dataclasses import dataclass

from src.agent_runtime.skills import (
    SkillRegistry,
    _render_template,
    register_user_skills_from_db,
)


def test_render_template_substitutes_placeholders() -> None:
    out = _render_template("Hello {{name}} — {{topic}}", {"name": "Sam", "topic": "AI"})
    assert out == "Hello Sam — AI"


def test_render_template_missing_arg_blank() -> None:
    out = _render_template("Hello {{name}}", {})
    assert out == "Hello "


@dataclass
class _Row:
    skill_id: str
    name: str
    description: str
    category: str
    prompt_template: str
    parameters: dict
    uses_llm: bool


class _StubStore:
    def __init__(self, rows: list[_Row]) -> None:
        self._rows = rows

    def list_all(self) -> list[_Row]:
        return list(self._rows)


def test_register_user_skills_no_llm_returns_rendered_prompt() -> None:
    rows = [_Row(
        skill_id="user.greet",
        name="Greet",
        description="greets the user",
        category="text",
        prompt_template="Hi {{name}}!",
        parameters={"name": "the user's name"},
        uses_llm=False,
    )]
    registry = SkillRegistry()
    count = register_user_skills_from_db(registry, _StubStore(rows))
    assert count == 1
    out = registry.execute("user.greet", name="Sam")
    assert out == "Hi Sam!"


def test_register_user_skills_overrides_metadata() -> None:
    rows = [_Row(
        skill_id="user.summarize",
        name="Summarize",
        description="",
        category="analysis",
        prompt_template="Summarize: {{text}}",
        parameters={"text": "the text to summarize"},
        uses_llm=False,
    )]
    registry = SkillRegistry()
    register_user_skills_from_db(registry, _StubStore(rows))
    skill = registry.get("user.summarize")
    assert skill is not None
    assert skill.name == "Summarize"
    assert skill.category == "analysis"
    assert skill.parameters == {"text": "the text to summarize"}

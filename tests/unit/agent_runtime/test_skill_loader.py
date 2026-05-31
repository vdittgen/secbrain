"""Tests for the SKILL.md-based skill loader.

sensitivity_tier: 1
"""

from __future__ import annotations

from pathlib import Path

import pytest
from src.agent_runtime.skill_loader import SkillLoader, build_skill_menu

SAMPLE_SKILL_MD = """\
---
name: Test Skill
description: A test skill for unit tests
version: 1
tags: [test, unit]
sensitivity_tier: 1
source: user
---

## When to Use

When running unit tests.

## Procedure

1. Do the thing
2. Check the result

## Pitfalls

- Don't forget to assert
"""

SAMPLE_SKILL_NO_FM = """\
This skill has no frontmatter.

Just plain markdown.
"""


@pytest.fixture()
def skills_dir(tmp_path: Path) -> Path:
    """Create a temporary skills directory with one sample skill."""
    skill_dir = tmp_path / "test-skill"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(SAMPLE_SKILL_MD)
    return tmp_path


@pytest.fixture()
def loader(skills_dir: Path) -> SkillLoader:
    return SkillLoader(skills_dir=skills_dir, seed_builtins=False)


class TestDiscover:
    def test_finds_skills(self, loader: SkillLoader) -> None:
        skills = loader.discover()
        assert len(skills) >= 1
        ids = [s.id for s in skills]
        assert "test-skill" in ids

    def test_metadata_parsed(self, loader: SkillLoader) -> None:
        meta = loader.get_meta("test-skill")
        assert meta is not None
        assert meta.name == "Test Skill"
        assert meta.description == "A test skill for unit tests"
        assert meta.tags == ("test", "unit")
        assert meta.sensitivity_tier == 1
        assert meta.source == "user"
        assert meta.version == 1

    def test_empty_dir(self, tmp_path: Path) -> None:
        loader = SkillLoader(skills_dir=tmp_path, seed_builtins=False)
        assert loader.discover() == []

    def test_dir_without_skill_md_ignored(self, tmp_path: Path) -> None:
        (tmp_path / "not-a-skill").mkdir()
        (tmp_path / "not-a-skill" / "README.md").write_text("hello")
        loader = SkillLoader(skills_dir=tmp_path, seed_builtins=False)
        assert loader.discover() == []


class TestLoad:
    def test_load_returns_instructions(self, loader: SkillLoader) -> None:
        doc = loader.load("test-skill")
        assert doc is not None
        assert "When running unit tests" in doc.instructions
        assert "## Procedure" in doc.instructions

    def test_load_unknown_returns_none(self, loader: SkillLoader) -> None:
        assert loader.load("nonexistent") is None

    def test_no_frontmatter_still_loads(self, tmp_path: Path) -> None:
        skill_dir = tmp_path / "no-fm"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(SAMPLE_SKILL_NO_FM)
        loader = SkillLoader(skills_dir=tmp_path, seed_builtins=False)
        meta = loader.get_meta("no-fm")
        assert meta is not None
        assert meta.name == "no-fm"
        doc = loader.load("no-fm")
        assert doc is not None
        assert "no frontmatter" in doc.instructions


class TestLoadResource:
    def test_reads_bundled_file(self, skills_dir: Path) -> None:
        templates = skills_dir / "test-skill" / "templates"
        templates.mkdir()
        (templates / "example.md").write_text("# Example template")
        loader = SkillLoader(skills_dir=skills_dir)
        content = loader.load_resource("test-skill", "templates/example.md")
        assert content == "# Example template"

    def test_rejects_path_traversal(self, loader: SkillLoader) -> None:
        result = loader.load_resource("test-skill", "../../etc/passwd")
        assert result is None

    def test_missing_file_returns_none(self, loader: SkillLoader) -> None:
        assert loader.load_resource("test-skill", "nope.txt") is None

    def test_unknown_skill_returns_none(self, loader: SkillLoader) -> None:
        assert loader.load_resource("nope", "file.txt") is None


class TestCreate:
    def test_creates_skill(self, skills_dir: Path) -> None:
        loader = SkillLoader(skills_dir=skills_dir, seed_builtins=False)
        meta = loader.create("My New Skill", SAMPLE_SKILL_MD)
        assert meta.id == "my-new-skill"
        assert (skills_dir / "my-new-skill" / "SKILL.md").exists()

    def test_deduplicates_slug(self, skills_dir: Path) -> None:
        loader = SkillLoader(skills_dir=skills_dir, seed_builtins=False)
        loader.create("Test Skill", SAMPLE_SKILL_MD)
        meta2 = loader.create("Test Skill", SAMPLE_SKILL_MD)
        assert meta2.id.startswith("test-skill")
        assert meta2.id != "test-skill"


class TestUpdate:
    def test_updates_content(self, skills_dir: Path) -> None:
        loader = SkillLoader(skills_dir=skills_dir, seed_builtins=False)
        updated_md = SAMPLE_SKILL_MD.replace(
            "A test skill for unit tests",
            "An updated description",
        )
        meta = loader.update("test-skill", updated_md)
        assert meta.description == "An updated description"

    def test_update_unknown_raises(self, loader: SkillLoader) -> None:
        with pytest.raises(KeyError):
            loader.update("nonexistent", SAMPLE_SKILL_MD)


class TestDelete:
    def test_deletes_skill(self, skills_dir: Path) -> None:
        loader = SkillLoader(skills_dir=skills_dir, seed_builtins=False)
        assert loader.delete("test-skill") is True
        assert loader.get_meta("test-skill") is None
        assert not (skills_dir / "test-skill").exists()

    def test_delete_unknown(self, loader: SkillLoader) -> None:
        assert loader.delete("nonexistent") is False


REMOVED_BUILTIN_MD = """\
---
name: Removed Skill
description: A builtin that was removed from the source
source: builtin
---

Should be pruned.
"""


class TestPruneRemovedBuiltins:
    def test_prunes_removed_builtin(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        builtin_dir = tmp_path / "builtins"
        builtin_dir.mkdir()
        (builtin_dir / "kept-skill").mkdir()
        (builtin_dir / "kept-skill" / "SKILL.md").write_text(SAMPLE_SKILL_MD)

        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()
        (skills_dir / "kept-skill").mkdir()
        (skills_dir / "kept-skill" / "SKILL.md").write_text(SAMPLE_SKILL_MD)
        (skills_dir / "removed-skill").mkdir()
        (skills_dir / "removed-skill" / "SKILL.md").write_text(REMOVED_BUILTIN_MD)

        monkeypatch.setattr(
            "src.agent_runtime.skill_loader.BUILTIN_SKILLS_DIR", builtin_dir,
        )
        loader = SkillLoader(skills_dir=skills_dir, seed_builtins=True)
        ids = [s.id for s in loader.discover()]
        assert "kept-skill" in ids
        assert "removed-skill" not in ids
        assert not (skills_dir / "removed-skill").exists()

    def test_does_not_prune_user_skills(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        builtin_dir = tmp_path / "builtins"
        builtin_dir.mkdir()

        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()
        (skills_dir / "my-skill").mkdir()
        (skills_dir / "my-skill" / "SKILL.md").write_text(SAMPLE_SKILL_MD)

        monkeypatch.setattr(
            "src.agent_runtime.skill_loader.BUILTIN_SKILLS_DIR", builtin_dir,
        )
        loader = SkillLoader(skills_dir=skills_dir, seed_builtins=True)
        ids = [s.id for s in loader.discover()]
        assert "my-skill" in ids


class TestToDict:
    def test_meta_to_dict(self, loader: SkillLoader) -> None:
        meta = loader.get_meta("test-skill")
        assert meta is not None
        d = meta.to_dict()
        assert d["id"] == "test-skill"
        assert d["name"] == "Test Skill"
        assert d["tags"] == ["test", "unit"]

    def test_document_to_dict(self, loader: SkillLoader) -> None:
        doc = loader.load("test-skill")
        assert doc is not None
        d = doc.to_dict()
        assert "instructions" in d
        assert d["name"] == "Test Skill"


REVIEW_SKILL_MD = """\
---
name: Weekly Review
description: Generate a weekly review summarizing messages, events, and action items
version: 1
tags: [productivity, review, weekly, summary, digest]
sensitivity_tier: 2
source: user
---

## When to Use
When the user asks for a weekly summary, digest, or review.

## Procedure
1. Query messages from the past 7 days
2. Query calendar events
3. Summarize into sections
"""


def _patch_skill_dirs(
    monkeypatch: pytest.MonkeyPatch,
    skills_dir: Path,
) -> None:
    """Point both SKILLS_DIR and BUILTIN_SKILLS_DIR at test paths."""
    empty = skills_dir / "__no_builtins__"
    empty.mkdir(exist_ok=True)
    monkeypatch.setattr("src.agent_runtime.skill_loader.SKILLS_DIR", skills_dir)
    monkeypatch.setattr("src.agent_runtime.skill_loader.BUILTIN_SKILLS_DIR", empty)


class TestBuildSkillMenu:
    def test_includes_all_skills(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        (tmp_path / "weekly-review").mkdir()
        (tmp_path / "weekly-review" / "SKILL.md").write_text(REVIEW_SKILL_MD)
        _patch_skill_dirs(monkeypatch, tmp_path)
        result = build_skill_menu()
        assert "## Available Skills" in result
        assert "weekly-review" in result
        assert "load_skill" in result
        assert "## Procedure" not in result

    def test_only_ids_filter(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        (tmp_path / "skill-a").mkdir()
        (tmp_path / "skill-a" / "SKILL.md").write_text(REVIEW_SKILL_MD)
        (tmp_path / "skill-b").mkdir()
        (tmp_path / "skill-b" / "SKILL.md").write_text(
            REVIEW_SKILL_MD.replace("Weekly Review", "Other Skill"),
        )
        _patch_skill_dirs(monkeypatch, tmp_path)
        result = build_skill_menu(only_ids=("skill-a",))
        assert "skill-a" in result
        assert "skill-b" not in result

    def test_tier_filtering(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        (tmp_path / "weekly-review").mkdir()
        (tmp_path / "weekly-review" / "SKILL.md").write_text(REVIEW_SKILL_MD)
        _patch_skill_dirs(monkeypatch, tmp_path)
        result = build_skill_menu(max_tier=1)
        assert result == ""

    def test_empty_returns_empty(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _patch_skill_dirs(monkeypatch, tmp_path)
        assert build_skill_menu() == ""

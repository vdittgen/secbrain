"""TaskCurator CRUD + agent-driven flows.

Exercises the curator in-memory against a real ``DatabaseEngine`` so
the SQL paths are covered alongside the agent stubs.

sensitivity_tier: N/A
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest
from src.agents.core.output_types import (
    GoalBatch,
    GoalDraft,
    HabitBatch,
    HabitDraft,
    TaskCompletionBatch,
    TaskCompletionDraft,
    TaskProposalBatch,
    TaskProposalDraft,
)
from src.agents.tasks import TaskCurator
from src.agents.tasks.persistence import find_topic_id_by_name
from src.core.sqlite.engine import DatabaseEngine


@pytest.fixture()
def db(tmp_path: Path) -> DatabaseEngine:
    return DatabaseEngine(tmp_path / "test.db")


@pytest.fixture()
def curator(db: DatabaseEngine) -> TaskCurator:
    return TaskCurator(db_engine=db)


def test_default_projects_seeded(curator: TaskCurator) -> None:
    projects = curator.list_projects()
    names = {p.name for p in projects}
    assert {"Personal", "Life", "Work"}.issubset(names)


def test_goal_dedup_on_title_and_category(curator: TaskCurator) -> None:
    a = curator.create_goal(title="Ship v1", category="work")
    b = curator.create_goal(title="ship v1", category="work")
    assert a.id == b.id
    # Different category creates a separate goal even with the same title.
    c = curator.create_goal(title="Ship v1", category="personal")
    assert c.id != a.id


def test_create_task_inherits_goal_from_project(
    curator: TaskCurator,
) -> None:
    goal = curator.create_goal(title="Ship v1", category="work")
    project = curator.create_project(
        name="Marketplace", category="work", goal_id=goal.id,
    )
    task = curator.create_task(title="Spec draft", project_id=project.id)
    assert task.goal_id == goal.id


def test_toggle_task_done_flips_state(curator: TaskCurator) -> None:
    t = curator.create_task(title="Buy milk")
    toggled = curator.toggle_task_done(t.id, completion_note="bought it")
    assert toggled is not None
    assert toggled.status == "done"
    assert toggled.completion_note == "bought it"
    assert toggled.completed_at is not None
    back = curator.toggle_task_done(t.id)
    assert back is not None
    assert back.status == "todo"
    assert back.completion_note is None


def test_propose_from_messages_dedups_open_tasks(
    monkeypatch, curator: TaskCurator,
) -> None:
    # Pre-existing open task with the same title — proposer must skip it.
    curator.create_task(title="Send Maria the deck")

    drafts = TaskProposalBatch(tasks=[
        TaskProposalDraft(
            title="Send Maria the deck",
            category="work",
            importance=7,
            source_message_ids=["m1"],
            reason="explicit ask",
        ),
        TaskProposalDraft(
            title="Book offsite flights",
            category="work",
            importance=8,
            source_message_ids=["m2"],
            reason="explicit ask",
        ),
    ])

    fake = MagicMock(return_value=MagicMock(propose=MagicMock(return_value=drafts)))
    monkeypatch.setattr(
        "src.agents.task_proposer.agent.TaskProposerAgent", fake,
    )

    created = curator.propose_from_messages([
        {"id": "m1", "sender": "maria", "content": "send the deck"},
        {"id": "m2", "sender": "boss", "content": "we'll need flights"},
    ])
    titles = {t.title for t in created}
    assert "Book offsite flights" in titles
    assert "Send Maria the deck" not in titles


def test_detect_completions_auto_closes_high_confidence(
    monkeypatch, curator: TaskCurator,
) -> None:
    task = curator.create_task(title="Send Maria the deck")

    verdicts = TaskCompletionBatch(completions=[
        TaskCompletionDraft(
            task_id=task.id,
            evidence_message_id="m9",
            evidence_summary="Maria confirmed receipt",
            confidence=0.95,
        ),
    ])
    monkeypatch.setattr(
        "src.agents.task_completion.agent.TaskCompletionAgent",
        MagicMock(return_value=MagicMock(detect=MagicMock(return_value=verdicts))),
    )

    closed = curator.detect_completions([
        {"id": "m9", "content": "Got the deck, thanks"},
    ])
    assert len(closed) == 1
    assert closed[0].id == task.id
    assert closed[0].status == "done"
    assert closed[0].completion_evidence_id == "m9"


def test_detect_completions_queues_low_confidence(
    monkeypatch, curator: TaskCurator, db: DatabaseEngine,
) -> None:
    task = curator.create_task(title="Send Maria the deck")
    verdicts = TaskCompletionBatch(completions=[
        TaskCompletionDraft(
            task_id=task.id,
            evidence_message_id="m9",
            evidence_summary="maybe done",
            confidence=0.4,
        ),
    ])
    monkeypatch.setattr(
        "src.agents.task_completion.agent.TaskCompletionAgent",
        MagicMock(return_value=MagicMock(detect=MagicMock(return_value=verdicts))),
    )
    closed = curator.detect_completions([{"id": "m9", "content": "..."}])
    assert closed == []
    pending = db.query(
        "SELECT task_id, confidence FROM _task_completion_candidates",
    )
    assert pending and pending[0]["task_id"] == task.id


def test_mine_goals_dedups_and_writes_linked_topic(
    monkeypatch, curator: TaskCurator, db: DatabaseEngine,
) -> None:
    # Seed a topic so the curator can resolve the linked_topic_hint.
    db.execute(
        """CREATE TABLE IF NOT EXISTS _topics (
            id VARCHAR PRIMARY KEY, contact_name VARCHAR NOT NULL,
            topic VARCHAR NOT NULL, description TEXT,
            importance INTEGER, status VARCHAR DEFAULT 'active',
            source VARCHAR, first_seen TEXT, last_seen TEXT,
            sensitivity_tier INTEGER DEFAULT 3,
            category VARCHAR, linked_goal_id VARCHAR
        )""",
    )
    db.execute(
        "INSERT INTO _topics (id, contact_name, topic, description, "
        "importance, status) VALUES "
        "('t1', 'maria', 'hiring a psychologist for the clinic', "
        "'desc', 8, 'active')",
    )

    drafts = GoalBatch(goals=[
        GoalDraft(
            title="Staff the clinic",
            description="hire 2 clinicians",
            category="work",
            horizon="short",
            importance=8,
            why="to scale Repensar",
            source_kind="message",
            source_ref="m1",
            linked_topic_hint="hiring a psychologist",
        ),
    ])
    monkeypatch.setattr(
        "src.agents.goal_extractor.agent.GoalExtractorAgent",
        MagicMock(return_value=MagicMock(extract=MagicMock(return_value=drafts))),
    )
    # Skip the evidence fetchers (they read tables that don't exist yet).
    monkeypatch.setattr(curator, "_fetch_recent_messages", lambda n: [{"id": "m1"}])
    monkeypatch.setattr(curator, "_fetch_recent_notes", lambda n: [])
    monkeypatch.setattr(curator, "_fetch_recent_facts", lambda n: [])

    created = curator.mine_goals()
    assert len(created) == 1
    new_goal = created[0]
    assert new_goal.category == "work"
    assert new_goal.why == "to scale Repensar"

    # Re-run: same draft must dedup, not create a second goal.
    created_again = curator.mine_goals()
    assert created_again == []

    # The linked topic should now point at the new goal.
    rows = db.query(
        "SELECT linked_goal_id FROM _topics WHERE id = 't1'",
    )
    assert rows and rows[0]["linked_goal_id"] == new_goal.id


def test_regenerate_habits_anchors_to_goal_and_drops_user_habits(
    monkeypatch, curator: TaskCurator,
) -> None:
    goal = curator.create_goal(title="Ship v1", category="work", why="to validate")
    user_habit = curator.create_habit(
        title="User-defined ritual", goal_id=goal.id,
    )

    drafts = HabitBatch(habits=[
        HabitDraft(
            title="Skim résumés 10 min",
            cadence="daily",
            preferred_window="morning",
            goal_id=goal.id,
            why="to validate",
            reason="moves the goal",
        ),
        HabitDraft(
            title="Invalid habit",
            cadence="daily",
            preferred_window="any",
            goal_id="bogus",
            why="x",
            reason="x",
        ),
    ])
    monkeypatch.setattr(
        "src.agents.habit_suggester.agent.HabitSuggesterAgent",
        MagicMock(return_value=MagicMock(
            suggest=MagicMock(return_value=HabitBatch(habits=[drafts.habits[0]])),
        )),
    )

    new_habits = curator.regenerate_habits()
    assert len(new_habits) == 1
    assert new_habits[0].goal_id == goal.id
    titles = {h.title for h in curator.list_habits()}
    # User-authored habit survives the regeneration.
    assert user_habit.title in titles
    assert "Skim résumés 10 min" in titles


def test_find_topic_id_by_name_returns_active_match(db: DatabaseEngine) -> None:
    db.execute(
        """CREATE TABLE IF NOT EXISTS _topics (
            id VARCHAR PRIMARY KEY, contact_name VARCHAR NOT NULL,
            topic VARCHAR NOT NULL, description TEXT,
            importance INTEGER, status VARCHAR DEFAULT 'active',
            source VARCHAR, first_seen TEXT, last_seen TEXT,
            sensitivity_tier INTEGER DEFAULT 3
        )""",
    )
    db.execute(
        "INSERT INTO _topics (id, contact_name, topic, description, "
        "importance, status) VALUES "
        "('a', 'x', 'hiring a psychologist', 'd', 8, 'active'), "
        "('b', 'y', 'old hiring', 'd', 6, 'resolved')",
    )
    assert find_topic_id_by_name(db, "hiring a psy") == "a"
    assert find_topic_id_by_name(db, "completely unrelated") is None

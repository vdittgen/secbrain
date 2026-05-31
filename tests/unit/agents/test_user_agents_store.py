"""UserAgentStore CRUD tests.

sensitivity_tier: 1
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from src.agents.user_agents.store import (
    UserAgentStore,
    UserAgentUpsert,
    make_agent_id,
)


@pytest.fixture()
def store(tmp_path: Path) -> UserAgentStore:
    return UserAgentStore(path=tmp_path / "user.sqlite3")


def _sample() -> UserAgentUpsert:
    return UserAgentUpsert(
        name="Research Buddy",
        description="answers research questions",
        system_prompt="You answer the user's research questions.",
        model_route="inherit",
        enabled_skills=("summarize-text",),
        enabled_mcp_tools=("notion:create_page",),
        brain_access=True,
        max_sensitivity_tier=2,
        schedule_cron="0 9 * * *",
        schedule_enabled=True,
    )


def test_insert_round_trip(store: UserAgentStore) -> None:
    row = store.insert(_sample())
    assert row.agent_id == make_agent_id("Research Buddy") == "user.research_buddy"
    assert row.system_prompt.startswith("You answer")
    assert row.enabled_skills == ("summarize-text",)
    assert row.enabled_mcp_tools == ("notion:create_page",)
    assert row.brain_access is True
    assert row.schedule_enabled is True
    assert row.version == 1

    fetched = store.get(row.agent_id)
    assert fetched is not None
    assert fetched.to_dict() == row.to_dict()


def test_insert_collision_suffixes(store: UserAgentStore) -> None:
    first = store.insert(_sample())
    second = store.insert(_sample())
    assert first.agent_id == "user.research_buddy"
    assert second.agent_id == "user.research_buddy_2"


def test_update_bumps_version(store: UserAgentStore) -> None:
    row = store.insert(_sample())
    patch = _sample()
    patch.name = "Research Buddy v2"
    updated = store.update(row.agent_id, patch)
    assert updated.version == 2
    assert updated.name == "Research Buddy v2"


def test_update_unknown_raises(store: UserAgentStore) -> None:
    with pytest.raises(KeyError):
        store.update("user.nope", _sample())


def test_set_schedule(store: UserAgentStore) -> None:
    row = store.insert(_sample())
    cleared = store.set_schedule(row.agent_id, cron=None, enabled=False)
    assert cleared.schedule_cron is None
    assert cleared.schedule_enabled is False


def test_delete(store: UserAgentStore) -> None:
    row = store.insert(_sample())
    assert store.delete(row.agent_id) is True
    assert store.get(row.agent_id) is None
    assert store.delete(row.agent_id) is False


def test_list_all_orders_by_created(store: UserAgentStore) -> None:
    first = store.insert(_sample())
    second_payload = _sample()
    second_payload.name = "Second Agent"
    second = store.insert(second_payload)
    listed = store.list_all()
    assert [r.agent_id for r in listed] == [first.agent_id, second.agent_id]


# ---------------------------------------------------------------------------
# pattern + subagents (orchestrator support)
# ---------------------------------------------------------------------------


def test_single_pattern_is_default(store: UserAgentStore) -> None:
    row = store.insert(_sample())
    assert row.pattern == "single"
    assert row.subagents == ()
    assert row.to_dict()["pattern"] == "single"
    assert row.to_dict()["subagents"] == []


def test_orchestrator_round_trip(store: UserAgentStore) -> None:
    payload = _sample()
    payload.pattern = "orchestrator"
    payload.subagents = ("user.alice", "user.bob")
    row = store.insert(payload)
    assert row.pattern == "orchestrator"
    assert row.subagents == ("user.alice", "user.bob")

    fetched = store.get(row.agent_id)
    assert fetched is not None
    assert fetched.pattern == "orchestrator"
    assert fetched.subagents == ("user.alice", "user.bob")


def test_orchestrator_update_replaces_subagents(store: UserAgentStore) -> None:
    payload = _sample()
    payload.pattern = "orchestrator"
    payload.subagents = ("user.alice",)
    row = store.insert(payload)

    patch = _sample()
    patch.pattern = "orchestrator"
    patch.subagents = ("user.bob", "user.carol")
    updated = store.update(row.agent_id, patch)
    assert updated.pattern == "orchestrator"
    assert updated.subagents == ("user.bob", "user.carol")
    assert updated.version == 2


def test_migration_adds_pattern_and_subagents_to_legacy_db(
    tmp_path: Path,
) -> None:
    """Existing pre-Phase-2 DBs must gain the new columns on open."""
    import sqlite3

    db_path = tmp_path / "legacy.sqlite3"
    legacy_ddl = """
    CREATE TABLE user_agents (
        agent_id            TEXT PRIMARY KEY,
        name                TEXT NOT NULL,
        description         TEXT NOT NULL DEFAULT '',
        system_prompt       TEXT NOT NULL,
        model_route         TEXT NOT NULL DEFAULT 'inherit',
        model_override      TEXT,
        enabled_skills_json TEXT NOT NULL DEFAULT '[]',
        enabled_mcp_tools_json TEXT NOT NULL DEFAULT '[]',
        brain_access        INTEGER NOT NULL DEFAULT 1,
        max_sensitivity_tier INTEGER NOT NULL DEFAULT 2,
        schedule_cron       TEXT,
        schedule_enabled    INTEGER NOT NULL DEFAULT 0,
        created_at          TEXT NOT NULL,
        updated_at          TEXT NOT NULL,
        version             INTEGER NOT NULL DEFAULT 1
    )
    """
    conn = sqlite3.connect(db_path, isolation_level=None)
    conn.execute(legacy_ddl)
    conn.execute(
        """
        INSERT INTO user_agents (
            agent_id, name, description, system_prompt,
            created_at, updated_at
        ) VALUES (
            'user.legacy', 'Legacy', 'old row', 'do stuff',
            '2025-01-01T00:00:00+00:00', '2025-01-01T00:00:00+00:00'
        )
        """,
    )
    conn.close()

    store = UserAgentStore(path=db_path)
    try:
        # Columns now present:
        cur = store._conn.execute("PRAGMA table_info(user_agents)")
        cols = {r[1] for r in cur.fetchall()}
        assert "pattern" in cols
        assert "subagents_json" in cols
        assert "delivery_tools_json" in cols
        # Legacy row defaults to single / empty without manual backfill.
        row = store.get("user.legacy")
        assert row is not None
        assert row.pattern == "single"
        assert row.subagents == ()
        assert row.delivery_tools == ()
    finally:
        store.close()


# ---------------------------------------------------------------------------
# delivery_tools round-trip
# ---------------------------------------------------------------------------


def test_delivery_tools_round_trip(store: UserAgentStore) -> None:
    payload = _sample()
    payload.delivery_tools = (
        "whatsapp:send_message", "apple-mail:send_email",
    )
    row = store.insert(payload)
    assert row.delivery_tools == (
        "whatsapp:send_message", "apple-mail:send_email",
    )
    fetched = store.get(row.agent_id)
    assert fetched is not None
    assert fetched.delivery_tools == row.delivery_tools
    assert fetched.to_dict()["delivery_tools"] == list(row.delivery_tools)


def test_delivery_tools_update_replaces_list(store: UserAgentStore) -> None:
    payload = _sample()
    payload.delivery_tools = ("whatsapp:send_message",)
    row = store.insert(payload)

    patch = _sample()
    patch.delivery_tools = ("apple-mail:send_email",)
    updated = store.update(row.agent_id, patch)
    assert updated.delivery_tools == ("apple-mail:send_email",)
    assert updated.version == 2


# ---------------------------------------------------------------------------
# message_sources → enabled_mcp_tools migration
# ---------------------------------------------------------------------------


def test_migration_converts_message_sources_to_data_tools(
    tmp_path: Path,
) -> None:
    """Legacy ``message_sources`` entries become data-tool entries.

    A row that used to declare ``message_sources=['apple-mail']`` must
    open into a row whose ``enabled_mcp_tools`` includes
    ``apple-mail:list_emails`` and whose stored
    ``message_sources_json`` has been cleared. Idempotent on reopen.
    """
    import sqlite3

    # Build the DB at the current schema first (cheap migration path)
    # then forcibly stamp a legacy value into message_sources_json so
    # the unify-tools migration has something to do.
    db_path = tmp_path / "legacy_sources.sqlite3"
    store = UserAgentStore(path=db_path)
    try:
        store.insert(UserAgentUpsert(
            name="legacy mail watcher",
            description="watches mail",
            system_prompt="do stuff",
            model_route="inherit",
            enabled_mcp_tools=(),
        ))
    finally:
        store.close()
    conn = sqlite3.connect(db_path, isolation_level=None)
    conn.execute(
        "UPDATE user_agents SET message_sources_json = ?",
        (json.dumps(["apple-mail"]),),
    )
    conn.close()

    store = UserAgentStore(path=db_path)
    try:
        rows = store.list_all()
        assert len(rows) == 1
        assert "apple-mail:list_emails" in rows[0].enabled_mcp_tools
        # message_sources_json is now cleared on disk.
        cur = store._conn.execute(
            "SELECT message_sources_json FROM user_agents",
        )
        (raw,) = cur.fetchone()
        assert raw == "[]"
    finally:
        store.close()

    # Reopen — migration must be a no-op now.
    store = UserAgentStore(path=db_path)
    try:
        rows = store.list_all()
        assert "apple-mail:list_emails" in rows[0].enabled_mcp_tools
    finally:
        store.close()

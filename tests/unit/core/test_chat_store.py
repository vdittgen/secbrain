"""Unit tests for the persistent ChatStore.

sensitivity_tier: N/A (test code)
"""

from __future__ import annotations

from pathlib import Path

import pytest
from src.core.chat_store import DEFAULT_TITLE, ChatStore
from src.core.sqlite.engine import DatabaseEngine


@pytest.fixture()
def tmp_db(tmp_path: Path) -> DatabaseEngine:
    engine = DatabaseEngine(db_path=tmp_path / "test_chat.sqlite3")
    yield engine
    engine.close()


@pytest.fixture()
def store(tmp_db: DatabaseEngine) -> ChatStore:
    return ChatStore(tmp_db)


class TestSessionLifecycle:
    def test_create_session_returns_uuid_and_lists_it(
        self, store: ChatStore,
    ) -> None:
        sid = store.create_session()
        assert sid
        sessions = store.list_sessions()
        assert len(sessions) == 1
        assert sessions[0]["id"] == sid
        assert sessions[0]["title"] == DEFAULT_TITLE
        assert sessions[0]["message_count"] == 0
        assert sessions[0]["preview"] is None

    def test_explicit_title_is_kept(self, store: ChatStore) -> None:
        store.create_session(title="Travel planning")
        sessions = store.list_sessions()
        assert sessions[0]["title"] == "Travel planning"

    def test_sessions_ordered_by_recent_activity(
        self, store: ChatStore,
    ) -> None:
        first = store.create_session()
        second = store.create_session()
        store.append_message(first, "user", "Hello first")
        sessions = store.list_sessions()
        assert [s["id"] for s in sessions[:2]] == [first, second]

    def test_delete_removes_session_and_messages(
        self, store: ChatStore,
    ) -> None:
        sid = store.create_session()
        store.append_message(sid, "user", "Hi")
        store.append_message(sid, "assistant", "Hello")
        store.delete_session(sid)
        assert store.list_sessions() == []
        assert store.load_session(sid) == []


class TestAppendAndLoad:
    def test_load_returns_messages_in_order(self, store: ChatStore) -> None:
        sid = store.create_session()
        store.append_message(sid, "user", "Question one")
        store.append_message(sid, "assistant", "Answer one")
        store.append_message(sid, "user", "Question two")

        loaded = store.load_session(sid)
        assert [m["role"] for m in loaded] == ["user", "assistant", "user"]
        assert loaded[0]["content"] == "Question one"
        assert loaded[2]["content"] == "Question two"

    def test_first_user_message_becomes_title(
        self, store: ChatStore,
    ) -> None:
        sid = store.create_session()
        store.append_message(sid, "user", "Plan my Tokyo trip")
        sessions = store.list_sessions()
        assert sessions[0]["title"] == "Plan my Tokyo trip"

    def test_explicit_title_is_not_overwritten(
        self, store: ChatStore,
    ) -> None:
        sid = store.create_session(title="Original")
        store.append_message(sid, "user", "Different question")
        sessions = store.list_sessions()
        assert sessions[0]["title"] == "Original"

    def test_long_title_is_truncated(self, store: ChatStore) -> None:
        sid = store.create_session()
        long_q = "a" * 200
        store.append_message(sid, "user", long_q)
        sessions = store.list_sessions()
        assert len(sessions[0]["title"]) <= 60

    def test_message_without_parts_loads_as_empty_list(
        self, store: ChatStore,
    ) -> None:
        """User messages have no parts; the loader must emit an empty
        list rather than None so the Rust DTO (parts: Vec<Value>) can
        deserialize without error."""
        sid = store.create_session()
        store.append_message(sid, "user", "Hello")
        loaded = store.load_session(sid)
        assert loaded[0]["parts"] == []
        assert loaded[0]["sources"] == []

    def test_parts_and_sources_roundtrip_as_lists(
        self, store: ChatStore,
    ) -> None:
        sid = store.create_session()
        parts = [{"id": "p1", "mime": "text/markdown", "data": "hi"}]
        sources = [{"type": "table", "content": "raw_messages"}]
        store.append_message(
            sid,
            "assistant",
            "",
            parts=parts,
            sources=sources,
            latency_ms=123.4,
            model="gpt-test",
            thinking="trace",
        )
        loaded = store.load_session(sid)
        assert loaded[0]["parts"] == parts
        assert loaded[0]["sources"] == sources
        assert loaded[0]["latency_ms"] == pytest.approx(123.4)
        assert loaded[0]["model"] == "gpt-test"
        assert loaded[0]["thinking"] == "trace"

    def test_message_count_bumps(self, store: ChatStore) -> None:
        sid = store.create_session()
        store.append_message(sid, "user", "x")
        store.append_message(sid, "assistant", "y")
        sessions = store.list_sessions()
        assert sessions[0]["message_count"] == 2

    def test_preview_uses_latest_user_message(
        self, store: ChatStore,
    ) -> None:
        sid = store.create_session()
        store.append_message(sid, "user", "older question")
        store.append_message(sid, "assistant", "answer")
        store.append_message(sid, "user", "newer question")
        sessions = store.list_sessions()
        assert sessions[0]["preview"] == "newer question"

    def test_invalid_role_raises(self, store: ChatStore) -> None:
        sid = store.create_session()
        with pytest.raises(ValueError):
            store.append_message(sid, "system", "nope")

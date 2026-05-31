"""Unit tests for the unified topic-extraction pipeline.

Covers:
- Local single-contact path (default behaviour).
- Remote multi-contact batch path.
- Semantic dedup on remote providers when > 5 topics surface.
- _msg_fingerprint stability across the 30→100 message window.
- sync_topics_table_from_cache hydration into _topics.

sensitivity_tier: N/A — test infrastructure
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from src.core.sqlite.engine import DatabaseEngine
from src.core.topic_loader import sync_topics_table_from_cache
from src.pipeline.intermediate import int_contact_topics


@pytest.fixture()
def tmp_db(tmp_path: Path) -> DatabaseEngine:
    db_path = tmp_path / "test_int_contact_topics.db"
    engine = DatabaseEngine(db_path=db_path)
    yield engine
    engine.close()


def _seed_messages(db: DatabaseEngine) -> None:
    db.execute("""
        CREATE TABLE IF NOT EXISTS raw_messages (
            id TEXT PRIMARY KEY,
            source TEXT,
            sender TEXT,
            sender_name TEXT,
            content TEXT,
            timestamp TEXT,
            is_from_me INTEGER,
            chat_name TEXT,
            is_group INTEGER,
            sensitivity_tier INTEGER DEFAULT 3
        )
    """)
    db.execute("""
        CREATE TABLE IF NOT EXISTS raw_contacts (
            id TEXT PRIMARY KEY,
            name TEXT,
            phone TEXT
        )
    """)
    # Two contacts each with 6 messages in active chats.  User has
    # posted in both ('me' rows below) so the active-chat filter passes.
    for contact, prefix in (("Sarah", "s"), ("Carlos", "c")):
        for i in range(6):
            db.execute(
                "INSERT INTO raw_messages "
                "(id, source, sender, sender_name, content, timestamp,"
                " is_from_me, chat_name, is_group) "
                "VALUES (?, 'whatsapp', ?, ?, ?, datetime('now', '-' || ? || ' days'), "
                "0, ?, 0)",
                [f"{prefix}{i}", contact, contact,
                 f"message {i} from {contact}", str(i + 1), contact],
            )
        db.execute(
            "INSERT INTO raw_messages "
            "(id, source, sender, sender_name, content, timestamp,"
            " is_from_me, chat_name, is_group) "
            "VALUES (?, 'whatsapp', 'me', 'Me', 'ack', "
            "datetime('now', '-1 days'), 1, ?, 0)",
            [f"{prefix}_own", contact],
        )


class TestRuntimeLimits:
    def test_local_default(self, monkeypatch) -> None:
        """When settings.llm_provider is not remote-capable, use small window."""
        monkeypatch.setattr(
            "src.models.llm_provider.load_llm_settings",
            lambda: {"llm_provider": "ollama"},
        )
        lookback, max_msgs, remote = int_contact_topics._runtime_limits()
        assert lookback == 30
        assert max_msgs == 30
        assert remote is False

    def test_remote_capable_expands(self, monkeypatch) -> None:
        """openai_compat unlocks the wider window."""
        monkeypatch.setattr(
            "src.models.llm_provider.load_llm_settings",
            lambda: {"llm_provider": "openai_compat"},
        )
        lookback, max_msgs, remote = int_contact_topics._runtime_limits()
        assert lookback == 90
        assert max_msgs == 100
        assert remote is True

    def test_anthropic_also_remote(self, monkeypatch) -> None:
        monkeypatch.setattr(
            "src.models.llm_provider.load_llm_settings",
            lambda: {"llm_provider": "anthropic"},
        )
        assert int_contact_topics._is_remote_capable() is True

    def test_ollama_is_local(self, monkeypatch) -> None:
        monkeypatch.setattr(
            "src.models.llm_provider.load_llm_settings",
            lambda: {"llm_provider": "ollama"},
        )
        assert int_contact_topics._is_remote_capable() is False


# NOTE: TestMultiContactExtraction and TestSemanticDedup removed
# in Phase F1.5 — the multi-contact batched prompt and the LLM-based
# semantic dedup pass no longer exist. Topic extraction now runs one
# contact at a time through ``TopicExtractorAgent`` (pydantic-ai); a
# future ``TopicDedupAgent`` can restore the merge pass if needed.


class TestFingerprintStability:
    def test_fingerprint_invariant_to_local_window(self) -> None:
        """Same messages, same fingerprint regardless of which cycle
        (30-msg local vs 100-msg remote) computed it."""
        msgs = [
            {"timestamp": f"2026-05-{i:02d}T10:00:00", "content": f"msg {i}"}
            for i in range(1, 50)
        ]
        fp_30 = int_contact_topics._msg_fingerprint(msgs[:30], max_msgs=30)
        fp_30_via_default = int_contact_topics._msg_fingerprint(msgs[:30])
        assert fp_30 == fp_30_via_default


class TestHydrateFromCache:
    def test_sync_inserts_topics_from_cache(
        self, tmp_db: DatabaseEngine,
    ) -> None:
        # Set up the _topics target table (mirrors MessageEvaluator schema)
        tmp_db.execute("""
            CREATE TABLE IF NOT EXISTS _topics (
                id               VARCHAR PRIMARY KEY,
                contact_name     VARCHAR NOT NULL,
                topic            VARCHAR NOT NULL,
                description      TEXT,
                importance       INTEGER DEFAULT 5,
                status           VARCHAR DEFAULT 'active',
                source           VARCHAR DEFAULT 'evaluator',
                first_seen       TEXT,
                last_seen        TEXT,
                message_count    INTEGER DEFAULT 1,
                sensitivity_tier INTEGER DEFAULT 3
            )
        """)
        tmp_db.execute("""
            CREATE TABLE IF NOT EXISTS _contact_topics_cache (
                contact_name TEXT PRIMARY KEY,
                fingerprint  TEXT NOT NULL,
                topics_json  TEXT NOT NULL,
                extracted_at TEXT
            )
        """)
        tmp_db.execute(
            "INSERT INTO _contact_topics_cache VALUES (?, ?, ?, ?)",
            [
                "Sarah",
                "abc",
                json.dumps([
                    {
                        "topic": "construction project",
                        "description": "Q3 site work",
                        "importance": 8,
                        "status": "active",
                    },
                    {
                        "topic": "weekend plans",
                        "description": "small talk",
                        "importance": 3,
                        "status": "active",
                    },
                ]),
                "2026-05-10T10:00:00",
            ],
        )

        inserted = sync_topics_table_from_cache(tmp_db)
        assert inserted == 2

        rows = tmp_db.query(
            "SELECT contact_name, topic, importance, source "
            "FROM _topics ORDER BY topic",
        )
        assert len(rows) == 2
        names = {(r["contact_name"], r["topic"]) for r in rows}
        assert ("Sarah", "construction project") in names
        assert all(r["source"] == "int_contact_topics" for r in rows)

    def test_sync_no_cache_table(
        self, tmp_db: DatabaseEngine,
    ) -> None:
        assert sync_topics_table_from_cache(tmp_db) == 0

    def test_sync_is_idempotent(
        self, tmp_db: DatabaseEngine,
    ) -> None:
        tmp_db.execute("""
            CREATE TABLE IF NOT EXISTS _topics (
                id VARCHAR PRIMARY KEY, contact_name VARCHAR NOT NULL,
                topic VARCHAR NOT NULL, description TEXT,
                importance INTEGER DEFAULT 5, status VARCHAR DEFAULT 'active',
                source VARCHAR DEFAULT 'evaluator',
                first_seen TEXT, last_seen TEXT,
                message_count INTEGER DEFAULT 1,
                sensitivity_tier INTEGER DEFAULT 3
            )
        """)
        tmp_db.execute("""
            CREATE TABLE IF NOT EXISTS _contact_topics_cache (
                contact_name TEXT PRIMARY KEY,
                fingerprint  TEXT NOT NULL,
                topics_json  TEXT NOT NULL,
                extracted_at TEXT
            )
        """)
        tmp_db.execute(
            "INSERT INTO _contact_topics_cache VALUES (?, ?, ?, ?)",
            [
                "Carlos", "fp", json.dumps([
                    {"topic": "deadline next friday", "importance": 7,
                     "status": "active", "description": "Q3"},
                ]),
                "2026-05-10T10:00:00",
            ],
        )
        first = sync_topics_table_from_cache(tmp_db)
        # Second sync should not duplicate
        second = sync_topics_table_from_cache(tmp_db)
        assert first == 1
        rows = tmp_db.query("SELECT COUNT(*) AS c FROM _topics")
        assert rows[0]["c"] == 1
        # Second pass counted attempts, but INSERT OR IGNORE kept the row count
        assert second == 1


# ---------------------------------------------------------------------------
# Email integration
# ---------------------------------------------------------------------------


def _seed_emails(db: DatabaseEngine) -> None:
    """Create raw_emails and raw_contacts with email→name mapping."""
    db.execute("""
        CREATE TABLE IF NOT EXISTS raw_emails (
            id TEXT PRIMARY KEY,
            source TEXT,
            message_id TEXT,
            subject TEXT,
            from_address TEXT,
            to_addresses TEXT,
            date TEXT,
            body_preview TEXT,
            is_read INTEGER,
            folder TEXT,
            labels TEXT,
            sensitivity_tier INTEGER DEFAULT 3,
            created_at TEXT DEFAULT (datetime('now'))
        )
    """)
    db.execute("""
        CREATE TABLE IF NOT EXISTS raw_contacts (
            id TEXT PRIMARY KEY,
            name TEXT,
            email TEXT,
            phone TEXT
        )
    """)
    db.execute(
        "INSERT OR IGNORE INTO raw_contacts (id, name, email) "
        "VALUES ('rc-1', 'Diana Prince', 'diana@example.com')",
    )
    # 6 inbound emails from Diana
    for i in range(6):
        db.execute(
            "INSERT INTO raw_emails "
            "(id, source, subject, from_address, to_addresses, "
            " date, body_preview, folder, sensitivity_tier) "
            "VALUES (?, 'apple_mail', ?, 'diana@example.com', "
            "'[\"user@me.com\"]', "
            "datetime('now', '-' || ? || ' days'), ?, 'Inbox', 3)",
            [f"e-in-{i}", f"Re: Project update {i}",
             str(i + 1), f"email body {i}"],
        )
    # 2 outbound emails from user to Diana (Sent folder)
    for i in range(2):
        db.execute(
            "INSERT INTO raw_emails "
            "(id, source, subject, from_address, to_addresses, "
            " date, body_preview, folder, sensitivity_tier) "
            "VALUES (?, 'apple_mail', ?, 'user@me.com', "
            "'[\"diana@example.com\"]', "
            "datetime('now', '-' || ? || ' days'), ?, 'Sent', 3)",
            [f"e-out-{i}", f"Re: Project update reply {i}",
             str(i + 1), f"my reply {i}"],
        )


class TestEmailIntegration:
    def test_contact_lookup_includes_emails(
        self, tmp_db: DatabaseEngine,
    ) -> None:
        """_build_contact_lookup should include email→name from raw_contacts."""
        _seed_emails(tmp_db)
        lookup = int_contact_topics._build_contact_lookup(tmp_db)
        assert lookup.get("diana@example.com") == "Diana Prince"

    def test_fetch_email_rows_normalizes(
        self, tmp_db: DatabaseEngine,
    ) -> None:
        """_fetch_email_rows should return normalized rows grouped by contact."""
        _seed_emails(tmp_db)
        lookup = int_contact_topics._build_contact_lookup(tmp_db)
        groups = int_contact_topics._fetch_email_rows(
            tmp_db, lookback=30, max_per_contact=100,
            contact_lookup=lookup,
        )
        assert "Diana Prince" in groups
        rows = groups["Diana Prince"]
        assert len(rows) == 8  # 6 inbound + 2 outbound
        inbound = [r for r in rows if r["is_from_me"] == 0]
        outbound = [r for r in rows if r["is_from_me"] == 1]
        assert len(inbound) == 6
        assert len(outbound) == 2
        for r in rows:
            assert "contact_name" in r
            assert "content" in r
            assert "timestamp" in r

    def test_fetch_email_rows_skips_when_no_table(
        self, tmp_db: DatabaseEngine,
    ) -> None:
        """Should return empty dict when raw_emails doesn't exist."""
        groups = int_contact_topics._fetch_email_rows(
            tmp_db, lookback=30, max_per_contact=100,
            contact_lookup={},
        )
        assert groups == {}

    def test_is_sent_folder(self) -> None:
        assert int_contact_topics._is_sent_folder("Sent") is True
        assert int_contact_topics._is_sent_folder("Sent Messages") is True
        assert int_contact_topics._is_sent_folder("Enviados") is True
        assert int_contact_topics._is_sent_folder("Inbox") is False
        assert int_contact_topics._is_sent_folder(None) is False
        assert int_contact_topics._is_sent_folder("") is False

    def test_parse_recipients(self) -> None:
        assert int_contact_topics._parse_recipients(None) == []
        assert int_contact_topics._parse_recipients(
            '["a@b.com", "c@d.com"]',
        ) == ["a@b.com", "c@d.com"]
        assert int_contact_topics._parse_recipients(
            ["a@b.com"],
        ) == ["a@b.com"]
        assert int_contact_topics._parse_recipients(
            "single@email.com",
        ) == ["single@email.com"]

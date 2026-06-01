"""Unit tests for the Kuzu GraphIndexer.

Verifies that GraphIndexer correctly populates the knowledge graph from
DuckDB raw tables (raw_contacts, raw_calendar_events, raw_notes).

All tests use temporary directories — never the real database files.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from src.core.kuzu.engine import GraphEngine
from src.core.kuzu.indexer import GraphIndexer
from src.core.kuzu.schema import create_schema
from src.core.sqlite.engine import DatabaseEngine
from src.core.sqlite.schemas import create_all_tables

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def duck(tmp_path: Path) -> DatabaseEngine:
    """Fresh DuckDB engine with all schemas created."""
    db = DatabaseEngine(db_path=tmp_path / "test.duckdb")
    create_all_tables(db)
    yield db
    db.close()


@pytest.fixture()
def kuzu(tmp_path: Path) -> GraphEngine:
    """Fresh Kuzu engine with schema applied."""
    engine = GraphEngine(db_path=tmp_path / "kuzu_test")
    create_schema(engine)
    yield engine
    engine.close()


@pytest.fixture()
def indexer(duck: DatabaseEngine, kuzu: GraphEngine) -> GraphIndexer:
    """GraphIndexer wired to test DuckDB and Kuzu engines."""
    return GraphIndexer(duckdb=duck, kuzu=kuzu)


def _seed_contacts(duck: DatabaseEngine) -> None:
    """Insert sample contacts into DuckDB."""
    duck.execute("""
        INSERT INTO raw_contacts (id, name, relationship, sensitivity_tier)
        VALUES
            ('c-1', 'Alice Kim', 'colleague', 2),
            ('c-2', 'Bob Torres', 'friend', 2),
            ('c-3', 'Dr. Sarah Chen', 'doctor', 3)
    """)


def _seed_events(duck: DatabaseEngine) -> None:
    """Insert sample calendar events into DuckDB."""
    attendees_1 = json.dumps(["Alice Kim", "Bob Torres"])
    attendees_3 = json.dumps(["Carlos Mendez"])
    duck.execute(f"""
        INSERT INTO raw_calendar_events
            (id, title, start_time, end_time,
             location, attendees, sensitivity_tier)
        VALUES
            ('ev-1', 'Team Stand-up',
             '2025-06-04 09:00:00', '2025-06-04 09:30:00',
             'Zoom', '{attendees_1}', 1),
            ('ev-2', 'Dentist Appointment',
             '2025-06-05 09:00:00', '2025-06-05 10:00:00',
             'Downtown Clinic', NULL, 3),
            ('ev-3', 'Lunch with Carlos',
             '2025-06-06 12:30:00', '2025-06-06 13:30:00',
             'El Rancho', '{attendees_3}', 2)
    """)


def _seed_notes(duck: DatabaseEngine) -> None:
    """Insert sample notes into DuckDB."""
    duck.execute(f"""
        INSERT INTO raw_notes (id, title, content, source, tags, sensitivity_tier)
        VALUES
            ('n-1', 'Arandu Architecture', 'Privacy-first AI OS for personal data.',
             'obsidian', '{json.dumps(["ai", "privacy"])}', 1),
            ('n-2', 'Meeting Notes', 'Discussed Q2 roadmap with the team.',
             'apple_notes', '{json.dumps(["work"])}', 2),
            ('n-3', 'Shopping List', 'Milk, eggs, bread', 'apple_notes', NULL, 1)
    """)


# ---------------------------------------------------------------------------
# Person indexing
# ---------------------------------------------------------------------------


class TestIndexPersons:
    def test_creates_person_nodes(
        self, duck: DatabaseEngine, kuzu: GraphEngine, indexer: GraphIndexer,
    ) -> None:
        """Person nodes should be created from raw_contacts."""
        _seed_contacts(duck)
        counts = indexer.full_reindex()

        assert counts["persons"] == 3
        rows = kuzu.query("MATCH (p:Person) RETURN p.id AS id ORDER BY p.id")
        assert len(rows) == 3
        ids = [r["id"] for r in rows]
        assert "c-1" in ids
        assert "c-2" in ids
        assert "c-3" in ids

    def test_person_properties(
        self, duck: DatabaseEngine, kuzu: GraphEngine, indexer: GraphIndexer,
    ) -> None:
        """Person nodes should have name, relationship, and sensitivity_tier."""
        _seed_contacts(duck)
        indexer.full_reindex()

        rows = kuzu.query(
            "MATCH (p:Person {id: 'c-1'}) "
            "RETURN p.name AS name, p.relationship AS rel, "
            "p.sensitivity_tier AS tier"
        )
        assert rows[0]["name"] == "Alice Kim"
        assert rows[0]["rel"] == "colleague"
        assert rows[0]["tier"] == 2

    def test_full_reindex_is_idempotent(
        self, duck: DatabaseEngine, kuzu: GraphEngine, indexer: GraphIndexer,
    ) -> None:
        """Calling full_reindex twice should not duplicate nodes."""
        _seed_contacts(duck)
        indexer.full_reindex()
        indexer.full_reindex()

        rows = kuzu.query("MATCH (p:Person) RETURN count(p) AS cnt")
        assert rows[0]["cnt"] == 3


# ---------------------------------------------------------------------------
# Event indexing
# ---------------------------------------------------------------------------


class TestIndexEvents:
    def test_creates_event_nodes(
        self, duck: DatabaseEngine, kuzu: GraphEngine, indexer: GraphIndexer,
    ) -> None:
        """Event nodes should be created from raw_calendar_events."""
        _seed_events(duck)
        counts = indexer.full_reindex()

        assert counts["events"] == 3
        rows = kuzu.query("MATCH (e:Event) RETURN e.id AS id ORDER BY e.id")
        assert len(rows) == 3

    def test_event_properties(
        self, duck: DatabaseEngine, kuzu: GraphEngine, indexer: GraphIndexer,
    ) -> None:
        """Event nodes should have title, event_type, and sensitivity_tier."""
        _seed_events(duck)
        indexer.full_reindex()

        rows = kuzu.query(
            "MATCH (e:Event {id: 'ev-1'}) "
            "RETURN e.title AS title, e.event_type AS etype, "
            "e.sensitivity_tier AS tier"
        )
        assert rows[0]["title"] == "Team Stand-up"
        assert rows[0]["etype"] == "calendar"
        assert rows[0]["tier"] == 1


# ---------------------------------------------------------------------------
# Idea indexing
# ---------------------------------------------------------------------------


class TestIndexIdeas:
    def test_creates_idea_nodes(
        self, duck: DatabaseEngine, kuzu: GraphEngine, indexer: GraphIndexer,
    ) -> None:
        """Idea nodes should be created from raw_notes."""
        _seed_notes(duck)
        counts = indexer.full_reindex()

        assert counts["ideas"] == 3
        rows = kuzu.query("MATCH (i:Idea) RETURN i.id AS id ORDER BY i.id")
        assert len(rows) == 3

    def test_idea_properties(
        self, duck: DatabaseEngine, kuzu: GraphEngine, indexer: GraphIndexer,
    ) -> None:
        """Idea nodes should have title, description, domain, and tier."""
        _seed_notes(duck)
        indexer.full_reindex()

        rows = kuzu.query(
            "MATCH (i:Idea {id: 'n-1'}) "
            "RETURN i.title AS title, i.domain AS domain, "
            "i.sensitivity_tier AS tier"
        )
        assert rows[0]["title"] == "Arandu Architecture"
        assert rows[0]["domain"] == "notes"
        assert rows[0]["tier"] == 1


# ---------------------------------------------------------------------------
# Topic indexing
# ---------------------------------------------------------------------------


class TestIndexTopics:
    def test_creates_topic_from_relationship_types(
        self, duck: DatabaseEngine, kuzu: GraphEngine, indexer: GraphIndexer,
    ) -> None:
        """Topics should be created from distinct contact relationship types."""
        _seed_contacts(duck)
        indexer.full_reindex()

        rows = kuzu.query(
            "MATCH (t:Topic) WHERE t.category = 'relationship' "
            "RETURN t.name AS name ORDER BY t.name"
        )
        names = [r["name"] for r in rows]
        assert "Colleague" in names
        assert "Friend" in names
        assert "Doctor" in names

    def test_creates_topic_from_note_tags(
        self, duck: DatabaseEngine, kuzu: GraphEngine, indexer: GraphIndexer,
    ) -> None:
        """Topics should be created from unique note tags."""
        _seed_notes(duck)
        indexer.full_reindex()

        rows = kuzu.query(
            "MATCH (t:Topic) WHERE t.category = 'tag' "
            "RETURN t.name AS name ORDER BY t.name"
        )
        names = [r["name"] for r in rows]
        assert "ai" in names
        assert "privacy" in names
        assert "work" in names


# ---------------------------------------------------------------------------
# Edge indexing: PARTICIPATED_IN
# ---------------------------------------------------------------------------


class TestParticipatedIn:
    def test_creates_edges_from_attendees(
        self, duck: DatabaseEngine, kuzu: GraphEngine, indexer: GraphIndexer,
    ) -> None:
        """PARTICIPATED_IN edges should connect attendees to events."""
        _seed_events(duck)
        counts = indexer.full_reindex()

        # ev-1 has 2 attendees, ev-3 has 1 attendee = 3 edges total
        assert counts["participated_in"] == 3

        rows = kuzu.query(
            "MATCH (p:Person)-[:PARTICIPATED_IN]->(e:Event {id: 'ev-1'}) "
            "RETURN p.name AS name ORDER BY p.name"
        )
        names = [r["name"] for r in rows]
        assert "Alice Kim" in names
        assert "Bob Torres" in names

    def test_creates_person_nodes_for_attendees(
        self, duck: DatabaseEngine, kuzu: GraphEngine, indexer: GraphIndexer,
    ) -> None:
        """Attendees not in raw_contacts should get Person nodes created."""
        _seed_events(duck)
        indexer.full_reindex()

        rows = kuzu.query(
            "MATCH (p:Person {id: 'p-carlos-mendez'}) "
            "RETURN p.name AS name"
        )
        assert len(rows) == 1
        assert rows[0]["name"] == "Carlos Mendez"


# ---------------------------------------------------------------------------
# Edge indexing: TAGGED_WITH
# ---------------------------------------------------------------------------


class TestTaggedWith:
    def test_creates_tagged_with_edges(
        self, duck: DatabaseEngine, kuzu: GraphEngine, indexer: GraphIndexer,
    ) -> None:
        """TAGGED_WITH edges should connect ideas to topics."""
        _seed_notes(duck)
        counts = indexer.full_reindex()

        # n-1 has 2 tags, n-2 has 1 tag, n-3 has no tags = 3 edges total
        assert counts["tagged_with"] == 3

    def test_idea_tagged_with_correct_topic(
        self, duck: DatabaseEngine, kuzu: GraphEngine, indexer: GraphIndexer,
    ) -> None:
        """Arandu note should be tagged with 'ai' and 'privacy'."""
        _seed_notes(duck)
        indexer.full_reindex()

        rows = kuzu.query(
            "MATCH (i:Idea {id: 'n-1'})-[:TAGGED_WITH]->(t:Topic) "
            "RETURN t.name AS name ORDER BY t.name"
        )
        names = [r["name"] for r in rows]
        assert "ai" in names
        assert "privacy" in names


# ---------------------------------------------------------------------------
# Full vs incremental reindex
# ---------------------------------------------------------------------------


class TestReindexModes:
    def test_full_reindex_clears_and_rebuilds(
        self, duck: DatabaseEngine, kuzu: GraphEngine, indexer: GraphIndexer,
    ) -> None:
        """full_reindex should clear existing data and rebuild."""
        _seed_contacts(duck)
        indexer.full_reindex()

        # Remove a contact from DuckDB
        duck.execute("DELETE FROM raw_contacts WHERE id = 'c-3'")
        indexer.full_reindex()

        rows = kuzu.query("MATCH (p:Person) RETURN count(p) AS cnt")
        assert rows[0]["cnt"] == 2

    def test_incremental_adds_new_records(
        self, duck: DatabaseEngine, kuzu: GraphEngine, indexer: GraphIndexer,
    ) -> None:
        """incremental_index should add new records without clearing."""
        _seed_contacts(duck)
        indexer.full_reindex()

        # Add a new contact
        duck.execute("""
            INSERT INTO raw_contacts (id, name, relationship, sensitivity_tier)
            VALUES ('c-4', 'New Person', 'colleague', 2)
        """)
        indexer.incremental_index()

        rows = kuzu.query("MATCH (p:Person) RETURN count(p) AS cnt")
        assert rows[0]["cnt"] == 4

    def test_empty_tables_produce_zero_counts(
        self, kuzu: GraphEngine, indexer: GraphIndexer,
    ) -> None:
        """Indexing empty tables should return zero counts without error."""
        counts = indexer.full_reindex()
        assert counts["persons"] == 0
        assert counts["events"] == 0
        assert counts["ideas"] == 0
        assert counts["topics"] == 0
        assert counts["participated_in"] == 0
        assert counts["tagged_with"] == 0


# ---------------------------------------------------------------------------
# Combined indexing
# ---------------------------------------------------------------------------


class TestCombinedIndexing:
    def test_full_pipeline_populates_all(
        self, duck: DatabaseEngine, kuzu: GraphEngine, indexer: GraphIndexer,
    ) -> None:
        """All seed data should produce nodes and edges."""
        _seed_contacts(duck)
        _seed_events(duck)
        _seed_notes(duck)

        counts = indexer.full_reindex()

        assert counts["persons"] == 3
        assert counts["events"] == 3
        assert counts["ideas"] == 3
        assert counts["topics"] > 0
        assert counts["participated_in"] > 0
        assert counts["tagged_with"] > 0

        # Verify total node count
        rows = kuzu.query("MATCH (n) RETURN count(n) AS cnt")
        total = rows[0]["cnt"]
        expected_min = (
            counts["persons"] + counts["events"] + counts["ideas"]
            + counts["topics"]
        )
        # Additional person nodes from attendees not in contacts
        assert total >= expected_min


# ---------------------------------------------------------------------------
# Pipeline topic indexing
# ---------------------------------------------------------------------------


def _seed_contact_topics(duck: DatabaseEngine) -> None:
    """Create and populate int_contact_topics as the pipeline would."""
    duck.execute("""
        CREATE TABLE IF NOT EXISTS int_contact_topics (
            contact_name     TEXT,
            topic            TEXT,
            description      TEXT,
            importance       TEXT,
            status           TEXT,
            category         TEXT,
            first_seen       TEXT,
            last_seen        TEXT,
            sensitivity_tier TEXT
        )
    """)
    duck.execute("""
        INSERT INTO int_contact_topics
            (contact_name, topic, description, importance,
             status, category, last_seen, sensitivity_tier)
        VALUES
            ('Alice Kim', 'Project Alpha launch', 'Preparing Q3 launch',
             '8', 'active', 'work', '2025-06-10T10:00:00', '3'),
            ('Alice Kim', 'Team offsite planning', 'Venue and agenda',
             '5', 'active', 'work', '2025-06-09T14:00:00', '2'),
            ('Bob Torres', 'Weekend hiking trip', 'Planning Mt. Tamalpais hike',
             '6', 'active', 'personal', '2025-06-08T18:00:00', '2'),
            ('Bob Torres', 'Old project wrap-up', 'Closing docs',
             '3', 'resolved', 'work', '2025-05-01T12:00:00', '2')
    """)


class TestPipelineTopics:
    def test_creates_topic_nodes_from_pipeline(
        self, duck: DatabaseEngine, kuzu: GraphEngine, indexer: GraphIndexer,
    ) -> None:
        """Topic nodes should be created from int_contact_topics."""
        _seed_contact_topics(duck)
        counts = indexer.full_reindex()

        # 3 active topics (resolved topic is excluded)
        assert counts["pipeline_topics"] == 3
        rows = kuzu.query(
            "MATCH (t:Topic) WHERE t.category IN "
            "['work', 'personal', 'conversation'] "
            "RETURN t.name AS name ORDER BY t.name"
        )
        names = [r["name"] for r in rows]
        assert "Project Alpha launch" in names
        assert "Team offsite planning" in names
        assert "Weekend hiking trip" in names

    def test_creates_discusses_edges(
        self, duck: DatabaseEngine, kuzu: GraphEngine, indexer: GraphIndexer,
    ) -> None:
        """DISCUSSES edges should connect persons to their topics."""
        _seed_contact_topics(duck)
        counts = indexer.full_reindex()

        # 3 active topic-contact pairs (resolved excluded)
        assert counts["discusses"] == 3

        rows = kuzu.query(
            "MATCH (p:Person)-[:DISCUSSES]->(t:Topic) "
            "WHERE p.name = 'Alice Kim' "
            "RETURN t.name AS topic ORDER BY t.name"
        )
        topics = [r["topic"] for r in rows]
        assert "Project Alpha launch" in topics
        assert "Team offsite planning" in topics

    def test_excludes_resolved_topics(
        self, duck: DatabaseEngine, kuzu: GraphEngine, indexer: GraphIndexer,
    ) -> None:
        """Resolved topics should not appear in the graph."""
        _seed_contact_topics(duck)
        indexer.full_reindex()

        rows = kuzu.query(
            "MATCH (t:Topic) WHERE t.name = 'Old project wrap-up' "
            "RETURN t"
        )
        assert len(rows) == 0

    def test_skips_when_table_missing(
        self, kuzu: GraphEngine, indexer: GraphIndexer,
    ) -> None:
        """Should return 0 gracefully when int_contact_topics doesn't exist."""
        counts = indexer.full_reindex()
        assert counts["pipeline_topics"] == 0
        assert counts["discusses"] == 0


# ---------------------------------------------------------------------------
# Edge deduplication
# ---------------------------------------------------------------------------


class TestEdgeDeduplication:
    def test_incremental_does_not_duplicate_edges(
        self, duck: DatabaseEngine, kuzu: GraphEngine, indexer: GraphIndexer,
    ) -> None:
        """Calling incremental_index twice should not double edge counts."""
        _seed_events(duck)
        _seed_contact_topics(duck)
        indexer.full_reindex()

        first_participated = kuzu.query(
            "MATCH ()-[r:PARTICIPATED_IN]->() RETURN count(r) AS cnt"
        )[0]["cnt"]
        first_discusses = kuzu.query(
            "MATCH ()-[r:DISCUSSES]->() RETURN count(r) AS cnt"
        )[0]["cnt"]

        indexer.incremental_index()

        second_participated = kuzu.query(
            "MATCH ()-[r:PARTICIPATED_IN]->() RETURN count(r) AS cnt"
        )[0]["cnt"]
        second_discusses = kuzu.query(
            "MATCH ()-[r:DISCUSSES]->() RETURN count(r) AS cnt"
        )[0]["cnt"]

        assert second_participated == first_participated
        assert second_discusses == first_discusses


# ---------------------------------------------------------------------------
# Place indexing
# ---------------------------------------------------------------------------


class TestIndexPlaces:
    def test_creates_place_nodes_from_events(
        self, duck: DatabaseEngine, kuzu: GraphEngine, indexer: GraphIndexer,
    ) -> None:
        """Place nodes should be created from calendar event locations."""
        _seed_events(duck)
        counts = indexer.full_reindex()

        assert counts["places"] >= 2  # Zoom, Downtown Clinic, El Rancho
        rows = kuzu.query("MATCH (p:Place) RETURN p.name AS name")
        names = [r["name"] for r in rows]
        assert any("Zoom" in n for n in names)

    def test_located_at_edges(
        self, duck: DatabaseEngine, kuzu: GraphEngine, indexer: GraphIndexer,
    ) -> None:
        """LOCATED_AT edges should connect events to places."""
        _seed_events(duck)
        counts = indexer.full_reindex()

        assert counts["located_at"] >= 2
        rows = kuzu.query(
            "MATCH (e:Event)-[:LOCATED_AT]->(p:Place) "
            "RETURN e.title AS event, p.name AS place"
        )
        assert len(rows) >= 2


# ---------------------------------------------------------------------------
# Emotion indexing
# ---------------------------------------------------------------------------


def _ensure_message_columns(duck: DatabaseEngine) -> None:
    """Ensure raw_messages has WhatsApp-specific columns.

    The base schema from create_all_tables lacks chat_name and is_group
    (added at runtime by the WhatsApp listener). Add them if missing.
    """
    for col, typedef in (
        ("chat_name", "TEXT"),
        ("is_group", "INTEGER DEFAULT 0"),
    ):
        try:
            duck.execute(
                f"ALTER TABLE raw_messages ADD COLUMN {col} {typedef}",
            )
        except Exception:  # noqa: BLE001
            pass  # column already exists


def _seed_labeled_messages(duck: DatabaseEngine) -> None:
    """Create int_labeled_messages + raw_messages for emotion indexing."""
    _ensure_message_columns(duck)
    duck.execute("""
        CREATE TABLE IF NOT EXISTS int_labeled_messages (
            message_id TEXT, primary_emotion TEXT,
            intensity TEXT, feelings_json TEXT,
            desires_json TEXT, actors_json TEXT,
            environment TEXT, domain TEXT,
            sensitivity_tier TEXT
        )
    """)
    for i in range(4):
        duck.execute(
            "INSERT INTO raw_messages "
            "(id, source, sender, sender_name, recipient, content, "
            "timestamp, is_from_me, chat_name) "
            "VALUES (?, 'whatsapp', 'alice', 'Alice Kim', 'me', "
            "'msg', datetime('now'), 0, 'Alice Kim')",
            [f"m-{i}"],
        )
    duck.execute(
        "INSERT INTO int_labeled_messages "
        "(message_id, primary_emotion, intensity) VALUES "
        "('m-0', 'joy', '0.8'), ('m-1', 'joy', '0.6'), "
        "('m-2', 'sadness', '0.7'), ('m-3', 'sadness', '0.5')",
    )


class TestEmotionIndexing:
    def test_creates_emotion_nodes(
        self, duck: DatabaseEngine, kuzu: GraphEngine, indexer: GraphIndexer,
    ) -> None:
        """Emotion nodes should be created from labeled messages."""
        _seed_labeled_messages(duck)
        counts = indexer.full_reindex()

        assert counts["emotions"] == 2
        rows = kuzu.query(
            "MATCH (e:Emotion) RETURN e.name AS name ORDER BY e.name"
        )
        names = [r["name"] for r in rows]
        assert "Joy" in names
        assert "Sadness" in names

    def test_felt_edges(
        self, duck: DatabaseEngine, kuzu: GraphEngine, indexer: GraphIndexer,
    ) -> None:
        """FELT edges should connect persons to emotions."""
        _seed_labeled_messages(duck)
        counts = indexer.full_reindex()

        assert counts["felt"] == 2  # Alice→Joy, Alice→Sadness
        rows = kuzu.query(
            "MATCH (p:Person)-[:FELT]->(e:Emotion) "
            "RETURN p.name AS person, e.name AS emotion "
            "ORDER BY e.name"
        )
        assert len(rows) == 2


# ---------------------------------------------------------------------------
# KNOWS indexing
# ---------------------------------------------------------------------------


def _seed_group_messages(duck: DatabaseEngine) -> None:
    """Create raw_messages with group chat data for KNOWS indexing."""
    _ensure_message_columns(duck)
    # Group chat with 3 members
    for i, (sender, name) in enumerate([
        ("alice", "Alice Kim"),
        ("bob", "Bob Torres"),
        ("carlos", "Carlos Mendez"),
    ]):
        duck.execute(
            "INSERT INTO raw_messages "
            "(id, source, sender, sender_name, recipient, content, "
            "timestamp, is_from_me, chat_name, is_group) "
            "VALUES (?, 'whatsapp', ?, ?, 'group', "
            "'msg', datetime('now'), 0, 'Team Chat', 1)",
            [f"g-{i}", sender, name],
        )


class TestKnowsIndexing:
    def test_creates_knows_edges_from_groups(
        self, duck: DatabaseEngine, kuzu: GraphEngine, indexer: GraphIndexer,
    ) -> None:
        """KNOWS edges should connect people in the same group chat."""
        _seed_group_messages(duck)
        counts = indexer.full_reindex()

        # 3 people → 3 pairs: A↔B, A↔C, B↔C
        assert counts["knows"] == 3

    def test_knows_no_duplicates(
        self, duck: DatabaseEngine, kuzu: GraphEngine, indexer: GraphIndexer,
    ) -> None:
        """Each pair should only have one KNOWS edge."""
        _seed_group_messages(duck)
        indexer.full_reindex()

        rows = kuzu.query(
            "MATCH ()-[r:KNOWS]->() RETURN count(r) AS cnt"
        )
        assert rows[0]["cnt"] == 3


# ---------------------------------------------------------------------------
# MENTIONED_IN indexing
# ---------------------------------------------------------------------------


class TestMentionedIn:
    def test_person_mentioned_in_event(
        self, duck: DatabaseEngine, kuzu: GraphEngine, indexer: GraphIndexer,
    ) -> None:
        """Person names in event titles create Person→Event MENTIONED_IN."""
        _seed_contacts(duck)
        _seed_events(duck)
        indexer.full_reindex()

        rows = kuzu.query(
            "MATCH (p:Person)-[:MENTIONED_IN]->(e:Event) "
            "RETURN p.name AS person, e.title AS event"
        )
        matched = {r["person"] for r in rows}
        assert "Carlos Mendez" in matched  # "Lunch with Carlos"

    def test_topic_mentioned_in_event(
        self, duck: DatabaseEngine, kuzu: GraphEngine, indexer: GraphIndexer,
    ) -> None:
        """Topic names in event titles create Topic→Event MENTIONED_IN."""
        _seed_events(duck)
        _seed_contact_topics(duck)
        duck.execute("""
            INSERT INTO raw_calendar_events
                (id, title, start_time, end_time, sensitivity_tier)
            VALUES
                ('ev-alpha', 'Project Alpha review',
                 '2025-06-10 14:00:00', '2025-06-10 15:00:00', 2)
        """)
        indexer.full_reindex()

        rows = kuzu.query(
            "MATCH (t:Topic)-[:MENTIONED_IN]->(e:Event) "
            "RETURN t.name AS topic, e.title AS event"
        )
        topics = {r["topic"] for r in rows}
        assert "Project Alpha launch" in topics


# ---------------------------------------------------------------------------
# Self relationships
# ---------------------------------------------------------------------------


class TestSelfRelationships:
    def test_self_has_relationship_with_contacts(
        self, duck: DatabaseEngine, kuzu: GraphEngine, indexer: GraphIndexer,
    ) -> None:
        """Self should have HAS_RELATIONSHIP to active contacts."""
        _seed_contact_topics(duck)
        indexer.full_reindex()

        rows = kuzu.query(
            "MATCH (s:Self)-[:HAS_RELATIONSHIP]->(p:Person) "
            "RETURN p.name AS name ORDER BY p.name"
        )
        names = [r["name"] for r in rows]
        assert "Alice Kim" in names
        assert "Bob Torres" in names

    def test_self_interested_in_topics(
        self, duck: DatabaseEngine, kuzu: GraphEngine, indexer: GraphIndexer,
    ) -> None:
        """Self should have INTERESTED_IN edges to active topics."""
        _seed_contact_topics(duck)
        indexer.full_reindex()

        rows = kuzu.query(
            "MATCH (s:Self)-[:INTERESTED_IN]->(t:Topic) "
            "RETURN t.name AS topic"
        )
        assert len(rows) >= 2

    def test_self_connected_to_places(
        self, duck: DatabaseEngine, kuzu: GraphEngine, indexer: GraphIndexer,
    ) -> None:
        """Self should have CONNECTED_TO edges to places."""
        _seed_events(duck)
        indexer.full_reindex()

        rows = kuzu.query(
            "MATCH (s:Self)-[:CONNECTED_TO]->(p:Place) "
            "RETURN p.name AS place"
        )
        assert len(rows) >= 2

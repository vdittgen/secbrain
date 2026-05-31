"""Graph fixtures for SecBrain Kuzu database.

Mirrors the contacts, calendar events, and concepts from the DuckDB fixtures
into a rich knowledge graph.  Sensitivity tiers are deliberately mixed so the
firewall filtering logic can be exercised during tests.

Node counts  (>=30 total):
  Person   8  (matches DuckDB contacts)
  Event   10  (matches DuckDB calendar events)
  Place    7
  Emotion  6
  Idea     6
  Topic    7
  ─────── ──
  Total   44

Edge counts  (>=50 total):
  KNOWS           10
  PARTICIPATED_IN 14
  FELT            12
  LOCATED_AT       9
  RELATED_TO       8
  MENTIONED_IN     8
  TAGGED_WITH     10
  ─────────────── ──
  Total           71

Usage:
    from src.core.kuzu.engine import GraphEngine
    from src.core.kuzu.schema import create_schema
    from tests.fixtures.kuzu_fixtures import load_all_fixtures

    with GraphEngine() as engine:
        create_schema(engine)
        load_all_fixtures(engine)
"""

from __future__ import annotations

from typing import Any

from src.core.kuzu.engine import GraphEngine

# ---------------------------------------------------------------------------
# Node data
# ---------------------------------------------------------------------------

# (id, name, relationship, sensitivity_tier)
PERSONS = [
    ("p-me", "Me", "self", 2),
    ("p-mom", "Mom", "family", 2),
    ("p-dad", "Dad", "family", 2),
    ("p-sister", "Sister", "family", 3),
    ("p-carlos", "Carlos Mendez", "friend", 2),
    ("p-alice", "Alice Kim", "colleague", 1),
    ("p-bob", "Bob Torres", "colleague", 1),
    ("p-dr-chen", "Dr. Sarah Chen", "doctor", 3),
]

# (id, title, event_type, date, sensitivity_tier)
EVENTS = [
    ("ev-001", "Q2 Planning Session", "work", "2025-06-03 10:00:00", 2),
    ("ev-002", "Dentist Appointment", "health", "2025-06-05 09:00:00", 3),
    ("ev-003", "Lunch with Carlos", "social", "2025-06-06 12:30:00", 2),
    ("ev-004", "Therapy Session", "health", "2025-06-05 18:00:00", 3),
    ("ev-005", "Team Stand-up", "work", "2025-06-04 09:00:00", 1),
    ("ev-006", "Concert - The Midnight", "social", "2025-06-07 20:00:00", 1),
    ("ev-007", "Annual Physical", "health", "2025-06-10 08:30:00", 3),
    ("ev-008", "Flight to New York", "travel", "2025-07-10 07:00:00", 1),
    ("ev-009", "Family Dinner", "social", "2025-06-08 18:00:00", 2),
    ("ev-010", "1-on-1 with Boss", "work", "2025-06-11 14:00:00", 2),
]

# (id, name, place_type, latitude, longitude, sensitivity_tier)
PLACES = [
    ("pl-001", "Conference Room B", "office", 37.7749, -122.4194, 1),
    ("pl-002", "Downtown Dental Clinic", "clinic", 37.7751, -122.4181, 3),
    ("pl-003", "El Rancho Taqueria", "restaurant", 37.7833, -122.4090, 1),
    ("pl-004", "Online - Zoom", "virtual", 0.0, 0.0, 2),
    ("pl-005", "The Fillmore", "venue", 37.7841, -122.4329, 1),
    ("pl-006", "Primary Care Associates", "clinic", 37.7695, -122.4271, 3),
    ("pl-007", "Mom's House", "home", 37.6879, -122.4702, 2),
]

# (id, name, valence, arousal, sensitivity_tier)
EMOTIONS = [
    ("em-001", "Optimism", 0.8, 0.6, 3),
    ("em-002", "Anxiety", -0.7, 0.8, 3),
    ("em-003", "Joy", 0.9, 0.7, 3),
    ("em-004", "Stress", -0.6, 0.9, 3),
    ("em-005", "Pride", 0.8, 0.5, 3),
    ("em-006", "Gratitude", 0.9, 0.3, 3),
]

# (id, title, description, domain, sensitivity_tier)
IDEAS = [
    (
        "id-001",
        "SecBrain",
        "Privacy-first AI operating system for personal data.",
        "software",
        1,
    ),
    (
        "id-002",
        "Git Diff Summariser",
        "CLI tool that turns git diffs into human-readable changelogs via LLM.",
        "software",
        1,
    ),
    (
        "id-003",
        "DuckDB Analytics",
        "Personal analytics using DuckDB for fast SQL on local data.",
        "data",
        1,
    ),
    (
        "id-004",
        "YouTube Channel",
        "Tech content channel covering AI, DuckDB, and local LLMs.",
        "content",
        1,
    ),
    (
        "id-005",
        "Sleep Optimisation",
        "Cutting screens by 10pm to improve sleep quality.",
        "health",
        2,
    ),
    (
        "id-006",
        "Rust Learning Path",
        "Structured plan to reach Rust proficiency by Q3 2025.",
        "learning",
        1,
    ),
]

# (id, name, category, sensitivity_tier)
TOPICS = [
    ("tp-001", "Artificial Intelligence", "technology", 1),
    ("tp-002", "Personal Finance", "finance", 3),
    ("tp-003", "Mental Health", "health", 3),
    ("tp-004", "Software Engineering", "technology", 1),
    ("tp-005", "Fitness & Wellness", "health", 2),
    ("tp-006", "Relationships", "personal", 2),
    ("tp-007", "Productivity", "lifestyle", 1),
]

# ---------------------------------------------------------------------------
# Edge data  (from_id, to_id, weight, timestamp, sensitivity_tier)
# ---------------------------------------------------------------------------

KNOWS_EDGES = [
    ("p-me", "p-mom", 0.9, "2025-01-01 00:00:00", 2),
    ("p-me", "p-dad", 0.9, "2025-01-01 00:00:00", 2),
    ("p-me", "p-sister", 0.9, "2025-01-01 00:00:00", 3),
    ("p-me", "p-carlos", 0.95, "2025-01-01 00:00:00", 2),
    ("p-me", "p-alice", 0.7, "2025-03-01 00:00:00", 1),
    ("p-me", "p-bob", 0.6, "2025-03-01 00:00:00", 1),
    ("p-me", "p-dr-chen", 0.5, "2025-05-28 09:00:00", 3),
    ("p-carlos", "p-me", 0.95, "2025-01-01 00:00:00", 2),
    ("p-alice", "p-bob", 0.7, "2025-03-01 00:00:00", 1),
    ("p-mom", "p-dad", 1.0, "2025-01-01 00:00:00", 2),
]

PARTICIPATED_IN_EDGES = [
    ("p-me", "ev-001", 1.0, "2025-06-03 10:00:00", 2),
    ("p-me", "ev-002", 1.0, "2025-06-05 09:00:00", 3),
    ("p-me", "ev-003", 1.0, "2025-06-06 12:30:00", 2),
    ("p-me", "ev-004", 1.0, "2025-06-05 18:00:00", 3),
    ("p-me", "ev-005", 1.0, "2025-06-04 09:00:00", 1),
    ("p-me", "ev-006", 1.0, "2025-06-07 20:00:00", 1),
    ("p-me", "ev-007", 1.0, "2025-06-10 08:30:00", 3),
    ("p-me", "ev-008", 1.0, "2025-07-10 07:00:00", 1),
    ("p-me", "ev-009", 1.0, "2025-06-08 18:00:00", 2),
    ("p-me", "ev-010", 1.0, "2025-06-11 14:00:00", 2),
    ("p-alice", "ev-001", 0.9, "2025-06-03 10:00:00", 2),
    ("p-alice", "ev-005", 1.0, "2025-06-04 09:00:00", 1),
    ("p-bob", "ev-005", 1.0, "2025-06-04 09:00:00", 1),
    ("p-carlos", "ev-003", 1.0, "2025-06-06 12:30:00", 2),
]

# Person -> Emotion
FELT_EDGES_PERSON = [
    ("p-me", "em-001", 0.7, "2025-06-02 07:30:00", 3),
    ("p-me", "em-002", 0.6, "2025-06-05 18:00:00", 3),
    ("p-me", "em-005", 0.8, "2025-06-03 12:30:00", 3),
    ("p-me", "em-006", 0.9, "2025-06-08 21:00:00", 3),
    ("p-sister", "em-002", 0.8, "2025-05-25 20:30:00", 3),
]

# Event -> Emotion
FELT_EDGES_EVENT = [
    ("ev-009", "em-003", 0.9, "2025-06-08 18:00:00", 3),
    ("ev-006", "em-003", 0.8, "2025-06-07 20:00:00", 3),
    ("ev-004", "em-001", 0.6, "2025-06-05 19:00:00", 3),
    ("ev-001", "em-004", 0.5, "2025-06-03 10:00:00", 3),
    ("ev-007", "em-002", 0.4, "2025-06-10 08:30:00", 3),
    ("ev-010", "em-004", 0.5, "2025-06-11 14:00:00", 3),
    ("ev-005", "em-001", 0.6, "2025-06-04 09:00:00", 3),
]

LOCATED_AT_EDGES = [
    ("ev-001", "pl-001", 1.0, "2025-06-03 10:00:00", 1),
    ("ev-002", "pl-002", 1.0, "2025-06-05 09:00:00", 3),
    ("ev-003", "pl-003", 1.0, "2025-06-06 12:30:00", 1),
    ("ev-004", "pl-004", 1.0, "2025-06-05 18:00:00", 2),
    ("ev-006", "pl-005", 1.0, "2025-06-07 20:00:00", 1),
    ("ev-007", "pl-006", 1.0, "2025-06-10 08:30:00", 3),
    ("ev-009", "pl-007", 1.0, "2025-06-08 18:00:00", 2),
    ("ev-005", "pl-004", 0.8, "2025-06-04 09:00:00", 1),
    ("ev-010", "pl-001", 0.9, "2025-06-11 14:00:00", 2),
]

# Idea -> Topic
RELATED_TO_EDGES_IDEA_TOPIC = [
    ("id-001", "tp-001", 0.95, "2025-05-01 10:00:00", 1),
    ("id-001", "tp-004", 0.9, "2025-05-01 10:00:00", 1),
    ("id-002", "tp-004", 0.85, "2025-05-01 10:00:00", 1),
    ("id-003", "tp-001", 0.8, "2025-05-01 10:00:00", 1),
    ("id-004", "tp-001", 0.7, "2025-05-15 10:00:00", 1),
    ("id-006", "tp-004", 0.8, "2025-04-05 10:00:00", 1),
]

# Idea -> Idea
RELATED_TO_EDGES_IDEA_IDEA = [
    ("id-001", "id-003", 0.9, "2025-05-01 10:00:00", 1),
    ("id-002", "id-001", 0.7, "2025-05-01 10:00:00", 1),
]

# Person -> Event
MENTIONED_IN_EDGES_PERSON = [
    ("p-alice", "ev-001", 0.8, "2025-06-03 10:00:00", 2),
    ("p-carlos", "ev-003", 1.0, "2025-06-06 12:30:00", 2),
    ("p-dr-chen", "ev-007", 1.0, "2025-06-10 08:30:00", 3),
    ("p-mom", "ev-009", 1.0, "2025-06-08 18:00:00", 2),
]

# Topic -> Event
MENTIONED_IN_EDGES_TOPIC = [
    ("tp-003", "ev-004", 1.0, "2025-06-05 18:00:00", 3),
    ("tp-005", "ev-007", 0.9, "2025-06-10 08:30:00", 2),
    ("tp-004", "ev-001", 0.8, "2025-06-03 10:00:00", 1),
    ("tp-007", "ev-010", 0.7, "2025-06-11 14:00:00", 2),
]

# Event -> Topic
TAGGED_WITH_EDGES_EVENT = [
    ("ev-001", "tp-004", 0.9, "2025-06-03 10:00:00", 1),
    ("ev-001", "tp-007", 0.7, "2025-06-03 10:00:00", 1),
    ("ev-004", "tp-003", 1.0, "2025-06-05 18:00:00", 3),
    ("ev-007", "tp-005", 0.9, "2025-06-10 08:30:00", 2),
    ("ev-005", "tp-004", 0.8, "2025-06-04 09:00:00", 1),
    ("ev-009", "tp-006", 0.9, "2025-06-08 18:00:00", 2),
]

# Idea -> Topic
TAGGED_WITH_EDGES_IDEA = [
    ("id-001", "tp-001", 0.95, "2025-05-01 10:00:00", 1),
    ("id-005", "tp-005", 0.8, "2025-05-31 08:00:00", 2),
    ("id-003", "tp-004", 0.85, "2025-05-05 14:00:00", 1),
    ("id-004", "tp-007", 0.7, "2025-05-15 16:00:00", 1),
]

# ---------------------------------------------------------------------------
# Total counts (for test assertions)
# ---------------------------------------------------------------------------

EXPECTED_NODE_COUNTS: dict[str, int] = {
    "Person": len(PERSONS),
    "Event": len(EVENTS),
    "Place": len(PLACES),
    "Emotion": len(EMOTIONS),
    "Idea": len(IDEAS),
    "Topic": len(TOPICS),
}

EXPECTED_EDGE_COUNTS: dict[str, int] = {
    "KNOWS": len(KNOWS_EDGES),
    "PARTICIPATED_IN": len(PARTICIPATED_IN_EDGES),
    "FELT": len(FELT_EDGES_PERSON) + len(FELT_EDGES_EVENT),
    "LOCATED_AT": len(LOCATED_AT_EDGES),
    "RELATED_TO": (len(RELATED_TO_EDGES_IDEA_TOPIC) + len(RELATED_TO_EDGES_IDEA_IDEA)),
    "MENTIONED_IN": (len(MENTIONED_IN_EDGES_PERSON) + len(MENTIONED_IN_EDGES_TOPIC)),
    "TAGGED_WITH": (len(TAGGED_WITH_EDGES_EVENT) + len(TAGGED_WITH_EDGES_IDEA)),
}

# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

_EDGE_PROPS = "{weight: $w, timestamp: timestamp($ts), sensitivity_tier: $tier}"


def _edge_params(
    from_id: str, to_id: str, weight: float, ts: str, tier: int
) -> dict[str, Any]:
    """Build the standard parameter dict for edge insertion queries."""
    return {"from_id": from_id, "to_id": to_id, "w": weight, "ts": ts, "tier": tier}


# ---------------------------------------------------------------------------
# Public loader
# ---------------------------------------------------------------------------


def load_all_fixtures(engine: GraphEngine) -> None:
    """Insert all graph nodes and edges into the database.

    Idempotent: node loaders use MERGE so calling this function a second time
    on the same database will update properties in-place rather than raising a
    duplicate-key error.  Edge loaders use CREATE (Kuzu has no unique
    constraint on rel tables), so they accumulate on repeated calls — use a
    fresh database for test isolation.

    Args:
        engine: An open GraphEngine instance with the schema already applied.
    """
    _load_persons(engine)
    _load_events(engine)
    _load_places(engine)
    _load_emotions(engine)
    _load_ideas(engine)
    _load_topics(engine)
    _load_knows(engine)
    _load_participated_in(engine)
    _load_felt(engine)
    _load_located_at(engine)
    _load_related_to(engine)
    _load_mentioned_in(engine)
    _load_tagged_with(engine)


# ---------------------------------------------------------------------------
# Node loaders
# ---------------------------------------------------------------------------


def _load_persons(engine: GraphEngine) -> None:
    """Insert Person nodes (idempotent via MERGE)."""
    cypher = (
        "MERGE (n:Person {id: $id}) "
        "SET n.name = $name, n.relationship = $rel, n.sensitivity_tier = $tier"
    )
    for p_id, name, relationship, tier in PERSONS:
        engine.execute(
            cypher,
            {"id": p_id, "name": name, "rel": relationship, "tier": tier},
        )


def _load_events(engine: GraphEngine) -> None:
    """Insert Event nodes (idempotent via MERGE)."""
    cypher = (
        "MERGE (n:Event {id: $id}) "
        "SET n.title = $title, n.event_type = $type,"
        " n.date = timestamp($date), n.sensitivity_tier = $tier"
    )
    for ev_id, title, ev_type, date, tier in EVENTS:
        engine.execute(
            cypher,
            {"id": ev_id, "title": title, "type": ev_type, "date": date, "tier": tier},
        )


def _load_places(engine: GraphEngine) -> None:
    """Insert Place nodes (idempotent via MERGE)."""
    cypher = (
        "MERGE (n:Place {id: $id}) "
        "SET n.name = $name, n.place_type = $type,"
        " n.latitude = $lat, n.longitude = $lon, n.sensitivity_tier = $tier"
    )
    for pl_id, name, pl_type, lat, lon, tier in PLACES:
        engine.execute(
            cypher,
            {
                "id": pl_id,
                "name": name,
                "type": pl_type,
                "lat": lat,
                "lon": lon,
                "tier": tier,
            },
        )


def _load_emotions(engine: GraphEngine) -> None:
    """Insert Emotion nodes (idempotent via MERGE)."""
    cypher = (
        "MERGE (n:Emotion {id: $id}) "
        "SET n.name = $name, n.valence = $valence,"
        " n.arousal = $arousal, n.sensitivity_tier = $tier"
    )
    for em_id, name, valence, arousal, tier in EMOTIONS:
        engine.execute(
            cypher,
            {
                "id": em_id,
                "name": name,
                "valence": valence,
                "arousal": arousal,
                "tier": tier,
            },
        )


def _load_ideas(engine: GraphEngine) -> None:
    """Insert Idea nodes (idempotent via MERGE)."""
    cypher = (
        "MERGE (n:Idea {id: $id}) "
        "SET n.title = $title, n.description = $description,"
        " n.domain = $domain, n.sensitivity_tier = $tier"
    )
    for id_id, title, description, domain, tier in IDEAS:
        engine.execute(
            cypher,
            {
                "id": id_id,
                "title": title,
                "description": description,
                "domain": domain,
                "tier": tier,
            },
        )


def _load_topics(engine: GraphEngine) -> None:
    """Insert Topic nodes (idempotent via MERGE)."""
    cypher = (
        "MERGE (n:Topic {id: $id}) "
        "SET n.name = $name, n.category = $cat, n.sensitivity_tier = $tier"
    )
    for tp_id, name, category, tier in TOPICS:
        engine.execute(
            cypher,
            {"id": tp_id, "name": name, "cat": category, "tier": tier},
        )


# ---------------------------------------------------------------------------
# Edge loaders
# ---------------------------------------------------------------------------


def _load_knows(engine: GraphEngine) -> None:
    """Insert KNOWS edges (Person -> Person)."""
    cypher = (
        "MATCH (a:Person {id: $from_id}), (b:Person {id: $to_id}) "
        f"CREATE (a)-[:KNOWS {_EDGE_PROPS}]->(b)"
    )
    for row in KNOWS_EDGES:
        engine.execute(cypher, _edge_params(*row))


def _load_participated_in(engine: GraphEngine) -> None:
    """Insert PARTICIPATED_IN edges (Person -> Event)."""
    cypher = (
        "MATCH (p:Person {id: $from_id}), (e:Event {id: $to_id}) "
        f"CREATE (p)-[:PARTICIPATED_IN {_EDGE_PROPS}]->(e)"
    )
    for row in PARTICIPATED_IN_EDGES:
        engine.execute(cypher, _edge_params(*row))


def _load_felt(engine: GraphEngine) -> None:
    """Insert FELT edges (Person -> Emotion and Event -> Emotion)."""
    p_cypher = (
        "MATCH (p:Person {id: $from_id}), (em:Emotion {id: $to_id}) "
        f"CREATE (p)-[:FELT {_EDGE_PROPS}]->(em)"
    )
    e_cypher = (
        "MATCH (ev:Event {id: $from_id}), (em:Emotion {id: $to_id}) "
        f"CREATE (ev)-[:FELT {_EDGE_PROPS}]->(em)"
    )
    for row in FELT_EDGES_PERSON:
        engine.execute(p_cypher, _edge_params(*row))
    for row in FELT_EDGES_EVENT:
        engine.execute(e_cypher, _edge_params(*row))


def _load_located_at(engine: GraphEngine) -> None:
    """Insert LOCATED_AT edges (Event -> Place)."""
    cypher = (
        "MATCH (ev:Event {id: $from_id}), (pl:Place {id: $to_id}) "
        f"CREATE (ev)-[:LOCATED_AT {_EDGE_PROPS}]->(pl)"
    )
    for row in LOCATED_AT_EDGES:
        engine.execute(cypher, _edge_params(*row))


def _load_related_to(engine: GraphEngine) -> None:
    """Insert RELATED_TO edges (Idea -> Topic and Idea -> Idea)."""
    it_cypher = (
        "MATCH (i:Idea {id: $from_id}), (t:Topic {id: $to_id}) "
        f"CREATE (i)-[:RELATED_TO {_EDGE_PROPS}]->(t)"
    )
    ii_cypher = (
        "MATCH (i1:Idea {id: $from_id}), (i2:Idea {id: $to_id}) "
        f"CREATE (i1)-[:RELATED_TO {_EDGE_PROPS}]->(i2)"
    )
    for row in RELATED_TO_EDGES_IDEA_TOPIC:
        engine.execute(it_cypher, _edge_params(*row))
    for row in RELATED_TO_EDGES_IDEA_IDEA:
        engine.execute(ii_cypher, _edge_params(*row))


def _load_mentioned_in(engine: GraphEngine) -> None:
    """Insert MENTIONED_IN edges (Person -> Event and Topic -> Event)."""
    p_cypher = (
        "MATCH (p:Person {id: $from_id}), (ev:Event {id: $to_id}) "
        f"CREATE (p)-[:MENTIONED_IN {_EDGE_PROPS}]->(ev)"
    )
    t_cypher = (
        "MATCH (t:Topic {id: $from_id}), (ev:Event {id: $to_id}) "
        f"CREATE (t)-[:MENTIONED_IN {_EDGE_PROPS}]->(ev)"
    )
    for row in MENTIONED_IN_EDGES_PERSON:
        engine.execute(p_cypher, _edge_params(*row))
    for row in MENTIONED_IN_EDGES_TOPIC:
        engine.execute(t_cypher, _edge_params(*row))


def _load_tagged_with(engine: GraphEngine) -> None:
    """Insert TAGGED_WITH edges (Event -> Topic and Idea -> Topic)."""
    e_cypher = (
        "MATCH (ev:Event {id: $from_id}), (t:Topic {id: $to_id}) "
        f"CREATE (ev)-[:TAGGED_WITH {_EDGE_PROPS}]->(t)"
    )
    i_cypher = (
        "MATCH (i:Idea {id: $from_id}), (t:Topic {id: $to_id}) "
        f"CREATE (i)-[:TAGGED_WITH {_EDGE_PROPS}]->(t)"
    )
    for row in TAGGED_WITH_EDGES_EVENT:
        engine.execute(e_cypher, _edge_params(*row))
    for row in TAGGED_WITH_EDGES_IDEA:
        engine.execute(i_cypher, _edge_params(*row))

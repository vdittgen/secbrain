"""ChromaDB vector store fixtures for SecBrain.

Indexes a representative subset of the DuckDB raw-data fixtures into the
five domain collections so semantic search is immediately available in dev.

Collection mapping
------------------
- "work"     — work-related messages and notes
- "personal" — personal messages, family notes, gratitude entries
- "health"   — health metric summaries and doctor-related notes
- "social"   — social events, friend interactions
- "ideas"    — idea notes, learning notes, book notes

Every document's metadata includes:
  source          (str)  — origin system / table name
  timestamp       (str)  — ISO-8601 datetime
  sensitivity_tier (int) — 1 / 2 / 3
  domain          (str)  — matches the collection name

Usage:
    from src.core.chromadb.engine import VectorEngine
    from tests.fixtures.chromadb_fixtures import load_all_fixtures

    with VectorEngine() as engine:
        load_all_fixtures(engine)
"""

from __future__ import annotations

from src.core.chromadb.engine import VectorEngine

# ---------------------------------------------------------------------------
# Document data  — (id, text, metadata)
# ---------------------------------------------------------------------------

# "work" collection
_WORK_DOCS: list[tuple[str, str, dict]] = [
    (
        "msg-002",
        "Hey, can you review the PR I just opened? Blocked on the CI failure.",
        {
            "source": "slack",
            "timestamp": "2025-06-02T09:30:00Z",
            "sensitivity_tier": 1,
            "domain": "work",
        },
    ),
    (
        "msg-006",
        "The deployment went smoothly. All services are green.",
        {
            "source": "slack",
            "timestamp": "2025-05-30T17:05:00Z",
            "sensitivity_tier": 1,
            "domain": "work",
        },
    ),
    (
        "msg-010",
        "Can you join the 3pm standup? We need to discuss the scope change.",
        {
            "source": "slack",
            "timestamp": "2025-05-27T14:00:00Z",
            "sensitivity_tier": 1,
            "domain": "work",
        },
    ),
    (
        "msg-014",
        "Great work on the demo yesterday! The client loved the new dashboard.",
        {
            "source": "slack",
            "timestamp": "2025-05-23T09:15:00Z",
            "sensitivity_tier": 1,
            "domain": "work",
        },
    ),
    (
        "msg-018",
        ("The API rate limits are causing prod issues. Should we upgrade the plan?"),
        {
            "source": "slack",
            "timestamp": "2025-05-19T15:45:00Z",
            "sensitivity_tier": 1,
            "domain": "work",
        },
    ),
    (
        "msg-019",
        (
            "Reviewed — LGTM. One minor comment on the error handling,"
            " otherwise good to merge."
        ),
        {
            "source": "gmail",
            "timestamp": "2025-05-18T11:30:00Z",
            "sensitivity_tier": 1,
            "domain": "work",
        },
    ),
    (
        "note-003",
        (
            "Meeting Notes — Q2 Planning. Key decisions:"
            " 1) Ship analytics MVP by end of June."
            " 2) Pause feature work in July for tech debt."
            " 3) Hire one more BE engineer."
        ),
        {
            "source": "obsidian",
            "timestamp": "2025-06-03T12:30:00Z",
            "sensitivity_tier": 1,
            "domain": "work",
        },
    ),
    (
        "note-011",
        (
            "API Design — SecBrain."
            " Use REST for CRUD. Use GraphQL for flexible querying."
            " Keep Tauri commands thin — push logic into Python."
        ),
        {
            "source": "obsidian",
            "timestamp": "2025-05-05T14:00:00Z",
            "sensitivity_tier": 1,
            "domain": "work",
        },
    ),
    (
        "note-015",
        (
            "Career Goals 2025."
            " Get promoted to Staff Engineer by end of year."
            " Speak at one conference."
            " Ship personal open-source project."
        ),
        {
            "source": "obsidian",
            "timestamp": "2025-01-01T09:00:00Z",
            "sensitivity_tier": 2,
            "domain": "work",
        },
    ),
]

# "personal" collection
_PERSONAL_DOCS: list[tuple[str, str, dict]] = [
    (
        "msg-001",
        ("Hi! Quick reminder about the Q2 planning session tomorrow at 10am."),
        {
            "source": "gmail",
            "timestamp": "2025-06-02T08:15:00Z",
            "sensitivity_tier": 2,
            "domain": "personal",
        },
    ),
    (
        "msg-004",
        "Don't forget dinner on Sunday! Your sister is coming too.",
        {
            "source": "imessage",
            "timestamp": "2025-06-01T19:45:00Z",
            "sensitivity_tier": 2,
            "domain": "personal",
        },
    ),
    (
        "msg-016",
        "How's the new job going? Call me when you get a chance.",
        {
            "source": "imessage",
            "timestamp": "2025-05-21T18:00:00Z",
            "sensitivity_tier": 2,
            "domain": "personal",
        },
    ),
    (
        "note-002",
        (
            "Morning Journal — June 2."
            " Feeling tired but optimistic."
            " Yesterday's deployment was stressful but went well."
            " Need to pace myself better this sprint."
        ),
        {
            "source": "apple_notes",
            "timestamp": "2025-06-02T07:30:00Z",
            "sensitivity_tier": 3,
            "domain": "personal",
        },
    ),
    (
        "note-012",
        (
            "Gratitude — May 30."
            " Grateful for: good health this week,"
            " the long walk with dad,"
            " finishing the hard chapter of the Rust book."
        ),
        {
            "source": "apple_notes",
            "timestamp": "2025-05-30T22:00:00Z",
            "sensitivity_tier": 2,
            "domain": "personal",
        },
    ),
    (
        "note-004",
        (
            "Book Notes — Atomic Habits."
            " Identity-based habits: decide who you want to be,"
            " then prove it with small wins."
            " Focus on systems, not goals."
        ),
        {
            "source": "obsidian",
            "timestamp": "2025-04-20T09:00:00Z",
            "sensitivity_tier": 1,
            "domain": "personal",
        },
    ),
    (
        "note-006",
        (
            "Recipe — Chicken Tikka Masala."
            " Marinate chicken 4h in yoghurt + spices."
            " Cook sauce low and slow. Finish with cream."
        ),
        {
            "source": "apple_notes",
            "timestamp": "2025-03-14T19:00:00Z",
            "sensitivity_tier": 1,
            "domain": "personal",
        },
    ),
]

# "health" collection
_HEALTH_DOCS: list[tuple[str, str, dict]] = [
    (
        "msg-003",
        (
            "Following up on my last appointment —"
            " the fatigue hasn't improved."
            " Should I come in again?"
        ),
        {
            "source": "gmail",
            "timestamp": "2025-06-01T14:00:00Z",
            "sensitivity_tier": 3,
            "domain": "health",
        },
    ),
    (
        "msg-011",
        (
            "Reminder: your therapy session is this Thursday at 6pm."
            " Please confirm if you can make it."
        ),
        {
            "source": "gmail",
            "timestamp": "2025-05-26T09:00:00Z",
            "sensitivity_tier": 3,
            "domain": "health",
        },
    ),
    (
        "note-005",
        (
            "Anxiety Triggers."
            " Social situations when I feel underprepared."
            " Performance reviews."
            " Sunday evenings — anticipatory dread."
        ),
        {
            "source": "apple_notes",
            "timestamp": "2025-05-10T21:00:00Z",
            "sensitivity_tier": 3,
            "domain": "health",
        },
    ),
    (
        "note-010",
        (
            "Sleep Log — May 2025."
            " Average sleep: 6.8h."
            " Worst nights correlate with late-night screen time."
            " Cut off screens by 10pm this month."
        ),
        {
            "source": "obsidian",
            "timestamp": "2025-05-31T08:00:00Z",
            "sensitivity_tier": 3,
            "domain": "health",
        },
    ),
    (
        "note-013",
        (
            "Doctor Visit Notes — May 28."
            " BP 118/75 — normal."
            " Vitamin D low: supplement 2000 IU/day."
            " Follow-up in 3 months if fatigue persists."
        ),
        {
            "source": "apple_notes",
            "timestamp": "2025-05-28T10:00:00Z",
            "sensitivity_tier": 3,
            "domain": "health",
        },
    ),
    (
        "hm-001",
        "Heart rate recorded: 72 bpm on 2025-06-01. Source: apple_health.",
        {
            "source": "apple_health",
            "timestamp": "2025-06-01T07:00:00Z",
            "sensitivity_tier": 3,
            "domain": "health",
        },
    ),
    (
        "hm-002",
        "Steps recorded: 9854 steps on 2025-06-01. Source: apple_health.",
        {
            "source": "apple_health",
            "timestamp": "2025-06-01T23:59:00Z",
            "sensitivity_tier": 3,
            "domain": "health",
        },
    ),
    (
        "hm-003",
        "Sleep recorded: 7.2 hours on 2025-06-02. Source: apple_health.",
        {
            "source": "apple_health",
            "timestamp": "2025-06-02T06:30:00Z",
            "sensitivity_tier": 3,
            "domain": "health",
        },
    ),
    (
        "hm-007",
        "Weight recorded: 74.5 kg on 2025-05-30. Source: withings_scale.",
        {
            "source": "withings_scale",
            "timestamp": "2025-05-30T08:00:00Z",
            "sensitivity_tier": 3,
            "domain": "health",
        },
    ),
    (
        "hm-010",
        (
            "Vitamin D level: 22 ng/mL on 2025-05-28."
            " Clinically low — supplement ordered."
        ),
        {
            "source": "clinic",
            "timestamp": "2025-05-28T09:30:00Z",
            "sensitivity_tier": 3,
            "domain": "health",
        },
    ),
]

# "social" collection
_SOCIAL_DOCS: list[tuple[str, str, dict]] = [
    (
        "msg-008",
        (
            "Bro, are you coming to the concert next Friday?"
            " Tickets are almost sold out."
        ),
        {
            "source": "imessage",
            "timestamp": "2025-05-28T21:10:00Z",
            "sensitivity_tier": 2,
            "domain": "social",
        },
    ),
    (
        "msg-012",
        "I've been feeling really anxious lately. Can we talk tonight?",
        {
            "source": "imessage",
            "timestamp": "2025-05-25T20:30:00Z",
            "sensitivity_tier": 3,
            "domain": "social",
        },
    ),
    (
        "msg-020",
        (
            "Just heard you're going through a rough patch."
            " I'm here if you need to talk."
        ),
        {
            "source": "imessage",
            "timestamp": "2025-05-17T22:00:00Z",
            "sensitivity_tier": 3,
            "domain": "social",
        },
    ),
    (
        "note-009",
        (
            "Carlos — Things to Do."
            " Rock climbing gym visit."
            " Try the new ramen spot downtown."
            " Plan a weekend camping trip."
        ),
        {
            "source": "apple_notes",
            "timestamp": "2025-04-01T11:00:00Z",
            "sensitivity_tier": 2,
            "domain": "social",
        },
    ),
]

# "ideas" collection
_IDEAS_DOCS: list[tuple[str, str, dict]] = [
    (
        "note-001",
        (
            "Project Ideas."
            " Build a CLI tool that summarises git diffs"
            " into human-readable changelogs using an LLM."
        ),
        {
            "source": "obsidian",
            "timestamp": "2025-05-01T10:00:00Z",
            "sensitivity_tier": 1,
            "domain": "ideas",
        },
    ),
    (
        "note-007",
        (
            "Budget — June 2025."
            " Rent: $2,100. Subscriptions: $87."
            " Groceries avg: $350."
            " Savings goal: $800/month. Currently on track."
        ),
        {
            "source": "obsidian",
            "timestamp": "2025-06-01T09:00:00Z",
            "sensitivity_tier": 3,
            "domain": "ideas",
        },
    ),
    (
        "note-008",
        (
            "Learning Roadmap — Rust."
            " 1) Complete the book."
            " 2) Build a CLI project."
            " 3) Contribute to one open source Rust crate."
            " Target: Q3 2025."
        ),
        {
            "source": "obsidian",
            "timestamp": "2025-04-05T10:00:00Z",
            "sensitivity_tier": 1,
            "domain": "ideas",
        },
    ),
    (
        "note-014",
        (
            "Content Ideas — YouTube."
            " Ep 1: Building a second brain with AI."
            " Ep 2: DuckDB for personal analytics."
            " Ep 3: Running LLMs locally with Ollama."
        ),
        {
            "source": "obsidian",
            "timestamp": "2025-05-15T16:00:00Z",
            "sensitivity_tier": 1,
            "domain": "ideas",
        },
    ),
    (
        "msg-007",
        (
            "This week in AI:"
            " LLM inference gets 3x faster"
            " with new quantization technique."
        ),
        {
            "source": "gmail",
            "timestamp": "2025-05-29T07:00:00Z",
            "sensitivity_tier": 1,
            "domain": "ideas",
        },
    ),
    (
        "msg-015",
        ("You hit a new personal record this week — 10,000 steps for 7 days in a row!"),
        {
            "source": "gmail",
            "timestamp": "2025-05-22T08:00:00Z",
            "sensitivity_tier": 2,
            "domain": "ideas",
        },
    ),
]

# Registry for tests
EXPECTED_COUNTS: dict[str, int] = {
    "work": len(_WORK_DOCS),
    "personal": len(_PERSONAL_DOCS),
    "health": len(_HEALTH_DOCS),
    "social": len(_SOCIAL_DOCS),
    "ideas": len(_IDEAS_DOCS),
}

_COLLECTION_MAP: dict[str, list[tuple[str, str, dict]]] = {
    "work": _WORK_DOCS,
    "personal": _PERSONAL_DOCS,
    "health": _HEALTH_DOCS,
    "social": _SOCIAL_DOCS,
    "ideas": _IDEAS_DOCS,
}


def load_all_fixtures(engine: VectorEngine) -> None:
    """Upsert all fixture documents into their respective collections.

    Safe to call multiple times (upsert semantics — duplicate IDs overwrite).

    Args:
        engine: An open VectorEngine instance.
    """
    for collection_name, docs in _COLLECTION_MAP.items():
        ids = [d[0] for d in docs]
        texts = [d[1] for d in docs]
        metas = [d[2] for d in docs]
        engine.add_documents(collection_name, texts, metas, ids)

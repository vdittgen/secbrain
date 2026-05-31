"""Realistic sample data for the SecBrain raw-data tables.

Intended for development and testing only — never run against a production
database.  Sensitivity tiers are deliberately mixed to exercise the
permission-filtering code in src-tauri/src/firewall/ (Rust).

Usage:
    from src.core.sqlite.engine import DatabaseEngine
    from src.core.sqlite.schemas import create_all_tables
    from tests.fixtures.sample_data import load_all_fixtures

    with DatabaseEngine() as engine:
        create_all_tables(engine)
        load_all_fixtures(engine)
"""

from __future__ import annotations

import json

from src.core.sqlite.engine import DatabaseEngine

# ---------------------------------------------------------------------------
# Messages  (20 rows, tiers 1-3)
# ---------------------------------------------------------------------------

MESSAGES: list[tuple] = [
    # id, source, sender, recipient, content, timestamp, metadata, tier
    (
        "msg-001",
        "gmail",
        "boss@company.com",
        "me@example.com",
        "Hi! Quick reminder about the Q2 planning session tomorrow at 10am.",
        "2025-06-02T08:15:00Z",
        json.dumps({"thread_id": "th-001", "labels": ["work", "important"]}),
        2,
    ),
    (
        "msg-002",
        "slack",
        "alice@company.com",
        "me@example.com",
        "Hey, can you review the PR I just opened? Blocked on the CI failure.",
        "2025-06-02T09:30:00Z",
        json.dumps({"channel": "#engineering", "workspace": "company"}),
        1,
    ),
    (
        "msg-003",
        "gmail",
        "me@example.com",
        "doctor@healthclinic.com",
        (
            "Following up on my last appointment"
            " — the fatigue hasn't improved. Should I come in again?"
        ),
        "2025-06-01T14:00:00Z",
        json.dumps({"thread_id": "th-002", "labels": ["health"]}),
        3,
    ),
    (
        "msg-004",
        "imessage",
        "mom",
        "me",
        "Don't forget dinner on Sunday! Your sister is coming too.",
        "2025-06-01T19:45:00Z",
        json.dumps({"read": True}),
        2,
    ),
    (
        "msg-005",
        "gmail",
        "bank@notifications.com",
        "me@example.com",
        "Your statement is ready. A transaction of $1,250 was posted to your account.",
        "2025-05-31T06:00:00Z",
        json.dumps({"labels": ["finance"]}),
        3,
    ),
    (
        "msg-006",
        "slack",
        "bob@company.com",
        "me@example.com",
        "The deployment went smoothly. All services are green.",
        "2025-05-30T17:05:00Z",
        json.dumps({"channel": "#ops", "workspace": "company"}),
        1,
    ),
    (
        "msg-007",
        "gmail",
        "newsletter@techblog.com",
        "me@example.com",
        (
            "This week in AI: LLM inference gets 3x faster"
            " with new quantization technique."
        ),
        "2025-05-29T07:00:00Z",
        json.dumps({"labels": ["newsletter"]}),
        1,
    ),
    (
        "msg-008",
        "imessage",
        "best_friend_carlos",
        "me",
        "Bro, are you coming to the concert next Friday? Tickets are almost sold out.",
        "2025-05-28T21:10:00Z",
        json.dumps({"read": True}),
        2,
    ),
    (
        "msg-009",
        "gmail",
        "recruiter@startup.io",
        "me@example.com",
        (
            "I came across your profile and think you'd be"
            " a great fit for a senior role at our company."
        ),
        "2025-05-27T10:30:00Z",
        json.dumps({"labels": ["career"]}),
        2,
    ),
    (
        "msg-010",
        "slack",
        "carol@company.com",
        "me@example.com",
        "Can you join the 3pm standup? We need to discuss the scope change.",
        "2025-05-27T14:00:00Z",
        json.dumps({"channel": "#product", "workspace": "company"}),
        1,
    ),
    (
        "msg-011",
        "gmail",
        "therapist@wellness.com",
        "me@example.com",
        (
            "Reminder: your session is this Thursday at 6pm."
            " Please confirm if you can make it."
        ),
        "2025-05-26T09:00:00Z",
        json.dumps({"labels": ["health", "personal"]}),
        3,
    ),
    (
        "msg-012",
        "imessage",
        "sister",
        "me",
        "I've been feeling really anxious lately. Can we talk tonight?",
        "2025-05-25T20:30:00Z",
        json.dumps({"read": False}),
        3,
    ),
    (
        "msg-013",
        "gmail",
        "accountant@taxservices.com",
        "me@example.com",
        "Your 2024 tax filing is complete. Refund of $2,340 expected within 21 days.",
        "2025-05-24T11:00:00Z",
        json.dumps({"labels": ["finance", "important"]}),
        3,
    ),
    (
        "msg-014",
        "slack",
        "david@company.com",
        "me@example.com",
        "Great work on the demo yesterday! The client loved the new dashboard.",
        "2025-05-23T09:15:00Z",
        json.dumps({"channel": "#general", "workspace": "company"}),
        1,
    ),
    (
        "msg-015",
        "gmail",
        "gymsupport@fitnessapp.com",
        "me@example.com",
        "You hit a new personal record this week — 10,000 steps for 7 days in a row!",
        "2025-05-22T08:00:00Z",
        json.dumps({"labels": ["health", "fitness"]}),
        2,
    ),
    (
        "msg-016",
        "imessage",
        "dad",
        "me",
        "How's the new job going? Call me when you get a chance.",
        "2025-05-21T18:00:00Z",
        json.dumps({"read": True}),
        2,
    ),
    (
        "msg-017",
        "gmail",
        "airline@bookings.com",
        "me@example.com",
        (
            "Your flight to New York on July 10 is confirmed."
            " Check-in opens 24h before departure."
        ),
        "2025-05-20T12:00:00Z",
        json.dumps({"labels": ["travel"]}),
        1,
    ),
    (
        "msg-018",
        "slack",
        "eve@company.com",
        "me@example.com",
        "The API rate limits are causing prod issues. Should we upgrade the plan?",
        "2025-05-19T15:45:00Z",
        json.dumps({"channel": "#engineering", "workspace": "company"}),
        1,
    ),
    (
        "msg-019",
        "gmail",
        "me@example.com",
        "alice@company.com",
        (
            "Reviewed — LGTM. One minor comment on the"
            " error handling, otherwise good to merge."
        ),
        "2025-05-18T11:30:00Z",
        json.dumps({"thread_id": "th-010", "labels": ["work"]}),
        1,
    ),
    (
        "msg-020",
        "imessage",
        "best_friend_carlos",
        "me",
        "Just heard you're going through a rough patch. I'm here if you need to talk.",
        "2025-05-17T22:00:00Z",
        json.dumps({"read": True}),
        3,
    ),
]

# ---------------------------------------------------------------------------
# Calendar events  (10 rows, tiers 1-3)
# ---------------------------------------------------------------------------

CALENDAR_EVENTS: list[tuple] = [
    # id, title, description, start_time, end_time, location, attendees, tier
    (
        "cal-001",
        "Q2 Planning Session",
        "Quarterly roadmap review with leadership.",
        "2025-06-03T10:00:00Z",
        "2025-06-03T12:00:00Z",
        "Conference Room B",
        json.dumps(["boss@company.com", "alice@company.com", "me@example.com"]),
        2,
    ),
    (
        "cal-002",
        "Dentist Appointment",
        "Routine cleaning and check-up.",
        "2025-06-05T09:00:00Z",
        "2025-06-05T10:00:00Z",
        "Downtown Dental Clinic",
        json.dumps(["me@example.com"]),
        3,
    ),
    (
        "cal-003",
        "Lunch with Carlos",
        "Catch up over tacos.",
        "2025-06-06T12:30:00Z",
        "2025-06-06T14:00:00Z",
        "El Rancho Taqueria",
        json.dumps(["best_friend_carlos", "me"]),
        2,
    ),
    (
        "cal-004",
        "Therapy Session",
        "Weekly mental health check-in.",
        "2025-06-05T18:00:00Z",
        "2025-06-05T19:00:00Z",
        "Online — Zoom",
        json.dumps(["therapist@wellness.com", "me@example.com"]),
        3,
    ),
    (
        "cal-005",
        "Team Stand-up",
        "Daily engineering sync.",
        "2025-06-04T09:00:00Z",
        "2025-06-04T09:30:00Z",
        "Slack Huddle",
        json.dumps(
            [
                "alice@company.com",
                "bob@company.com",
                "carol@company.com",
                "me@example.com",
            ]
        ),
        1,
    ),
    (
        "cal-006",
        "Concert — The Midnight",
        "Friday night show with Carlos.",
        "2025-06-07T20:00:00Z",
        "2025-06-07T23:00:00Z",
        "The Fillmore",
        json.dumps(["best_friend_carlos", "me"]),
        1,
    ),
    (
        "cal-007",
        "Annual Physical",
        "Blood work and general check-up.",
        "2025-06-10T08:30:00Z",
        "2025-06-10T09:30:00Z",
        "Primary Care Associates",
        json.dumps(["doctor@healthclinic.com", "me@example.com"]),
        3,
    ),
    (
        "cal-008",
        "Flight to New York",
        "Business trip — client presentation.",
        "2025-07-10T07:00:00Z",
        "2025-07-10T10:30:00Z",
        "SFO → JFK",
        json.dumps(["me@example.com"]),
        1,
    ),
    (
        "cal-009",
        "Family Dinner",
        "Sunday dinner at mom's place.",
        "2025-06-08T18:00:00Z",
        "2025-06-08T21:00:00Z",
        "Mom's House",
        json.dumps(["mom", "dad", "sister", "me"]),
        2,
    ),
    (
        "cal-010",
        "1-on-1 with Boss",
        "Monthly performance review.",
        "2025-06-11T14:00:00Z",
        "2025-06-11T15:00:00Z",
        "Boss's Office",
        json.dumps(["boss@company.com", "me@example.com"]),
        2,
    ),
]

# ---------------------------------------------------------------------------
# Notes  (15 rows, tiers 1-3)
# ---------------------------------------------------------------------------

NOTES: list[tuple] = [
    # id, title, content, source, created_at, updated_at, tags, tier
    (
        "note-001",
        "Project Ideas",
        (
            "Build a CLI tool that summarises git diffs into"
            " human-readable changelogs using an LLM."
        ),
        "obsidian",
        "2025-05-01T10:00:00Z",
        "2025-05-15T12:00:00Z",
        json.dumps(["ideas", "coding", "LLM"]),
        1,
    ),
    (
        "note-002",
        "Morning Journal — June 2",
        (
            "Feeling tired but optimistic. Yesterday's deployment"
            " was stressful but went well."
            " Need to pace myself better this sprint."
        ),
        "apple_notes",
        "2025-06-02T07:30:00Z",
        "2025-06-02T07:30:00Z",
        json.dumps(["journal", "personal"]),
        3,
    ),
    (
        "note-003",
        "Meeting Notes — Q2 Planning",
        (
            "Key decisions: 1) Ship analytics MVP by end of June."
            " 2) Pause feature work in July for tech debt."
            " 3) Hire one more BE engineer."
        ),
        "obsidian",
        "2025-06-03T12:30:00Z",
        "2025-06-03T13:00:00Z",
        json.dumps(["work", "meetings", "planning"]),
        1,
    ),
    (
        "note-004",
        "Book Notes — Atomic Habits",
        (
            "Identity-based habits: decide who you want to be,"
            " then prove it with small wins."
            " Focus on systems, not goals."
        ),
        "obsidian",
        "2025-04-20T09:00:00Z",
        "2025-04-20T09:45:00Z",
        json.dumps(["books", "productivity", "habits"]),
        1,
    ),
    (
        "note-005",
        "Anxiety Triggers",
        (
            "Social situations when I feel underprepared."
            " Performance reviews."
            " Sunday evenings — anticipatory dread."
        ),
        "apple_notes",
        "2025-05-10T21:00:00Z",
        "2025-05-25T20:00:00Z",
        json.dumps(["health", "mental-health", "personal"]),
        3,
    ),
    (
        "note-006",
        "Recipe — Chicken Tikka Masala",
        (
            "Marinate chicken 4h in yoghurt + spices."
            " Cook sauce low and slow. Finish with cream."
        ),
        "apple_notes",
        "2025-03-14T19:00:00Z",
        "2025-03-14T19:30:00Z",
        json.dumps(["recipes", "cooking"]),
        1,
    ),
    (
        "note-007",
        "Budget — June 2025",
        (
            "Rent: $2,100. Subscriptions: $87."
            " Groceries avg: $350."
            " Savings goal: $800/month. Currently on track."
        ),
        "obsidian",
        "2025-06-01T09:00:00Z",
        "2025-06-01T09:20:00Z",
        json.dumps(["finance", "budget"]),
        3,
    ),
    (
        "note-008",
        "Learning Roadmap — Rust",
        (
            "1) Complete the book. 2) Build a CLI project."
            " 3) Contribute to one open source Rust crate."
            " Target: Q3 2025."
        ),
        "obsidian",
        "2025-04-05T10:00:00Z",
        "2025-05-20T10:00:00Z",
        json.dumps(["learning", "rust", "coding"]),
        1,
    ),
    (
        "note-009",
        "Carlos — Things to Do",
        (
            "Rock climbing gym visit."
            " Try the new ramen spot downtown."
            " Plan a weekend camping trip."
        ),
        "apple_notes",
        "2025-04-01T11:00:00Z",
        "2025-05-30T11:00:00Z",
        json.dumps(["friends", "social"]),
        2,
    ),
    (
        "note-010",
        "Sleep Log — May 2025",
        (
            "Average sleep: 6.8h. Worst nights correlate with"
            " late-night screen time."
            " Cut off screens by 10pm this month."
        ),
        "obsidian",
        "2025-05-31T08:00:00Z",
        "2025-05-31T08:15:00Z",
        json.dumps(["health", "sleep", "habits"]),
        3,
    ),
    (
        "note-011",
        "API Design — SecBrain",
        (
            "Use REST for CRUD. Use GraphQL for flexible querying."
            " Keep Tauri commands thin — push logic into Python."
        ),
        "obsidian",
        "2025-05-05T14:00:00Z",
        "2025-06-01T14:00:00Z",
        json.dumps(["work", "secbrain", "architecture"]),
        1,
    ),
    (
        "note-012",
        "Gratitude — May 30",
        (
            "Grateful for: good health this week,"
            " the long walk with dad,"
            " finishing the hard chapter of the Rust book."
        ),
        "apple_notes",
        "2025-05-30T22:00:00Z",
        "2025-05-30T22:00:00Z",
        json.dumps(["journal", "gratitude", "personal"]),
        2,
    ),
    (
        "note-013",
        "Doctor Visit Notes — May 28",
        (
            "BP 118/75 — normal. Vitamin D low:"
            " supplement 2000 IU/day."
            " Follow-up in 3 months if fatigue persists."
        ),
        "apple_notes",
        "2025-05-28T10:00:00Z",
        "2025-05-28T10:30:00Z",
        json.dumps(["health", "doctor"]),
        3,
    ),
    (
        "note-014",
        "Content Ideas — YouTube",
        (
            "Ep 1: Building a second brain with AI."
            " Ep 2: DuckDB for personal analytics."
            " Ep 3: Running LLMs locally with Ollama."
        ),
        "obsidian",
        "2025-05-15T16:00:00Z",
        "2025-05-22T16:00:00Z",
        json.dumps(["content", "youtube", "ideas"]),
        1,
    ),
    (
        "note-015",
        "Career Goals 2025",
        (
            "Get promoted to Staff Engineer by end of year."
            " Speak at one conference."
            " Ship personal open-source project."
        ),
        "obsidian",
        "2025-01-01T09:00:00Z",
        "2025-05-01T09:00:00Z",
        json.dumps(["career", "goals"]),
        2,
    ),
]

# ---------------------------------------------------------------------------
# Health metrics  (10 rows, tier 3)
# ---------------------------------------------------------------------------

HEALTH_METRICS: list[tuple] = [
    # id, metric_type, value, unit, recorded_at, source, tier
    ("hm-001", "heart_rate", 72.0, "bpm", "2025-06-01T07:00:00Z", "apple_health", 3),
    ("hm-002", "steps", 9854.0, "steps", "2025-06-01T23:59:00Z", "apple_health", 3),
    ("hm-003", "sleep_hours", 7.2, "hours", "2025-06-02T06:30:00Z", "apple_health", 3),
    ("hm-004", "heart_rate", 68.0, "bpm", "2025-05-31T07:05:00Z", "apple_health", 3),
    ("hm-005", "steps", 11203.0, "steps", "2025-05-31T23:59:00Z", "garmin", 3),
    ("hm-006", "sleep_hours", 6.1, "hours", "2025-05-31T06:45:00Z", "apple_health", 3),
    ("hm-007", "weight_kg", 74.5, "kg", "2025-05-30T08:00:00Z", "withings_scale", 3),
    (
        "hm-008",
        "blood_pressure_systolic",
        118.0,
        "mmHg",
        "2025-05-28T09:15:00Z",
        "clinic",
        3,
    ),
    (
        "hm-009",
        "blood_pressure_diastolic",
        75.0,
        "mmHg",
        "2025-05-28T09:15:00Z",
        "clinic",
        3,
    ),
    ("hm-010", "vitamin_d", 22.0, "ng/mL", "2025-05-28T09:30:00Z", "clinic", 3),
]

# ---------------------------------------------------------------------------
# Contacts  (8 rows, tiers 2-3)
# ---------------------------------------------------------------------------

CONTACTS: list[tuple] = [
    # id, name, email, phone, relationship, notes, last_contact, tier
    (
        "con-001",
        "Mom",
        "mom@family.com",
        "+1-555-0101",
        "family",
        "Loves gardening. Birthday: March 12.",
        "2025-06-01T20:00:00Z",
        2,
    ),
    (
        "con-002",
        "Dad",
        "dad@family.com",
        "+1-555-0102",
        "family",
        "Retired engineer. Enjoys woodworking.",
        "2025-05-21T18:00:00Z",
        2,
    ),
    (
        "con-003",
        "Sister",
        "sister@family.com",
        "+1-555-0103",
        "family",
        "Lives in Austin. Works in marketing. Dealing with anxiety.",
        "2025-05-25T20:30:00Z",
        3,
    ),
    (
        "con-004",
        "Carlos Mendez",
        "carlos@gmail.com",
        "+1-555-0201",
        "friend",
        "Best friend since college. Into music, rock climbing. Reliable.",
        "2025-05-28T21:00:00Z",
        2,
    ),
    (
        "con-005",
        "Alice Kim",
        "alice@company.com",
        "+1-555-0301",
        "colleague",
        "Senior engineer on the team. Excellent code reviewer.",
        "2025-06-02T09:30:00Z",
        1,
    ),
    (
        "con-006",
        "Dr. Sarah Chen",
        "doctor@healthclinic.com",
        "+1-555-0401",
        "doctor",
        "Primary care physician. Next follow-up: Aug 2025.",
        "2025-05-28T09:00:00Z",
        3,
    ),
    (
        "con-007",
        "James (Therapist)",
        "therapist@wellness.com",
        "+1-555-0501",
        "therapist",
        "Weekly sessions on Thursdays. Focus: anxiety management.",
        "2025-05-22T18:00:00Z",
        3,
    ),
    (
        "con-008",
        "Bob Torres",
        "bob@company.com",
        "+1-555-0302",
        "colleague",
        "DevOps engineer. Go-to person for deployment issues.",
        "2025-05-30T17:05:00Z",
        1,
    ),
]

# ---------------------------------------------------------------------------
# Emails  (10 rows, tiers 1-3)
# ---------------------------------------------------------------------------

EMAILS: list[tuple] = [
    # id, source, message_id, subject, from_address, to_addresses,
    # date, body_preview, is_read, folder, labels, sensitivity_tier
    (
        "email-001",
        "apple-mail",
        "mid-001",
        "Q2 Planning Docs",
        "boss@company.com",
        json.dumps(["me@example.com"]),
        "2025-06-02T08:00:00Z",
        "Attached are the planning documents for tomorrow's session.",
        True,
        "INBOX",
        json.dumps(["work", "important"]),
        2,
    ),
    (
        "email-002",
        "apple-mail",
        "mid-002",
        "PR Review Request",
        "alice@company.com",
        json.dumps(["me@example.com", "bob@company.com"]),
        "2025-06-02T09:45:00Z",
        "Can you both take a look at PR #142? Blocked on CI.",
        False,
        "INBOX",
        json.dumps(["work"]),
        1,
    ),
    (
        "email-003",
        "apple-mail",
        "mid-003",
        "Appointment Follow-up",
        "therapist@wellness.com",
        json.dumps(["me@example.com"]),
        "2025-06-01T10:00:00Z",
        "Following up on our last session — please review the exercises we discussed.",
        True,
        "INBOX",
        json.dumps(["health"]),
        3,
    ),
    (
        "email-004",
        "apple-mail",
        "mid-004",
        "Your Statement is Ready",
        "bank@notifications.com",
        json.dumps(["me@example.com"]),
        "2025-05-31T06:30:00Z",
        "Your May statement is ready. Total balance: $4,250.00. View online.",
        True,
        "INBOX",
        json.dumps(["finance"]),
        3,
    ),
    (
        "email-005",
        "apple-mail",
        "mid-005",
        "This Week in AI",
        "newsletter@techblog.com",
        json.dumps(["me@example.com"]),
        "2025-05-30T07:00:00Z",
        "New quantization technique makes LLM inference 3x faster.",
        True,
        "INBOX",
        json.dumps(["newsletter"]),
        1,
    ),
    (
        "email-006",
        "apple-mail",
        "mid-006",
        "Sunday Dinner Plans",
        "mom@family.com",
        json.dumps(["me@example.com", "sister@family.com"]),
        "2025-06-01T15:00:00Z",
        "Dinner is at 6pm. Your sister is bringing dessert. Can you bring wine?",
        True,
        "INBOX",
        json.dumps(["family"]),
        2,
    ),
    (
        "email-007",
        "apple-mail",
        "mid-007",
        "Re: PR Review Request",
        "me@example.com",
        json.dumps(["alice@company.com"]),
        "2025-06-02T10:15:00Z",
        "LGTM — one minor comment on the error handling.",
        True,
        "Sent",
        json.dumps(["work"]),
        1,
    ),
    (
        "email-008",
        "apple-mail",
        "mid-008",
        "Blood Work Results",
        "doctor@healthclinic.com",
        json.dumps(["me@example.com"]),
        "2025-05-29T11:00:00Z",
        "Your blood work results are in. Vitamin D is low at 22 ng/mL.",
        False,
        "INBOX",
        json.dumps(["health"]),
        3,
    ),
    (
        "email-009",
        "apple-mail",
        "mid-009",
        "Concert Tickets Confirmed",
        "tickets@fillmore.com",
        json.dumps(["me@example.com"]),
        "2025-05-28T14:00:00Z",
        "Your tickets for The Midnight on June 7 are confirmed. Doors at 7pm.",
        True,
        "Archive",
        json.dumps(["events"]),
        1,
    ),
    (
        "email-010",
        "apple-mail",
        "mid-010",
        "Team Offsite Logistics",
        "carol@company.com",
        json.dumps(["me@example.com", "alice@company.com", "bob@company.com"]),
        "2025-05-27T16:00:00Z",
        "Offsite is July 15-17 in Napa. Please confirm attendance by Friday.",
        True,
        "INBOX",
        json.dumps(["work", "travel"]),
        2,
    ),
]

# ---------------------------------------------------------------------------
# Reminders  (8 rows, tiers 1-2)
# ---------------------------------------------------------------------------

REMINDERS: list[tuple] = [
    # id, source, title, due_date, notes, completed, list_name, sensitivity_tier
    (
        "rem-001",
        "apple-calendar",
        "Buy groceries",
        "2025-06-02T18:00:00Z",
        "Milk, eggs, bread, coffee",
        False,
        "Personal",
        1,
    ),
    (
        "rem-002",
        "apple-calendar",
        "Submit expense report",
        "2025-06-03T17:00:00Z",
        "Q1 travel expenses — receipts in Google Drive",
        False,
        "Work",
        1,
    ),
    (
        "rem-003",
        "apple-calendar",
        "Call dentist for follow-up",
        "2025-05-30T10:00:00Z",
        None,
        True,
        "Health",
        2,
    ),
    (
        "rem-004",
        "apple-calendar",
        "Renew gym membership",
        "2025-05-25T09:00:00Z",
        "Check if corporate discount still applies",
        False,
        "Personal",
        1,
    ),
    (
        "rem-005",
        "apple-calendar",
        "Send birthday card to Mom",
        None,
        "Her birthday is March 12",
        False,
        "Family",
        2,
    ),
    (
        "rem-006",
        "apple-calendar",
        "Review PR #142",
        "2025-06-02T12:00:00Z",
        None,
        True,
        "Work",
        1,
    ),
    (
        "rem-007",
        "apple-calendar",
        "Pick up dry cleaning",
        "2025-06-04T17:30:00Z",
        "Suit and two shirts",
        False,
        "Personal",
        1,
    ),
    (
        "rem-008",
        "apple-calendar",
        "Schedule annual physical",
        None,
        "Last checkup was in January — due for another",
        False,
        "Health",
        2,
    ),
]

# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------


def load_all_fixtures(engine: DatabaseEngine) -> None:
    """Insert all sample fixtures into the raw-data tables.

    Existing rows with conflicting primary keys are silently ignored so this
    function is safe to call multiple times (idempotent via OR IGNORE).

    Also runs schema migrations to ensure connector-introduced tables
    (raw_emails, raw_reminders, etc.) exist before loading their data.

    Args:
        engine: An open DatabaseEngine instance pointing at a database that
                already has the schemas applied (call create_all_tables first).
    """
    from src.core.sqlite.migrations import run_migrations

    run_migrations(engine)

    _load_messages(engine)
    _load_calendar_events(engine)
    _load_notes(engine)
    _load_health_metrics(engine)
    _load_contacts(engine)
    _load_emails(engine)
    _load_reminders(engine)


def _load_messages(engine: DatabaseEngine) -> None:
    """Load sample messages."""
    sql = """
        INSERT OR IGNORE INTO raw_messages
            (id, source, sender, recipient, content,
             timestamp, metadata, sensitivity_tier)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """
    for row in MESSAGES:
        engine.execute(sql, list(row))


def _load_calendar_events(engine: DatabaseEngine) -> None:
    """Load sample calendar events."""
    sql = """
        INSERT OR IGNORE INTO raw_calendar_events
            (id, title, description, start_time, end_time,
             location, attendees, sensitivity_tier)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """
    for row in CALENDAR_EVENTS:
        engine.execute(sql, list(row))


def _load_notes(engine: DatabaseEngine) -> None:
    """Load sample notes."""
    sql = """
        INSERT OR IGNORE INTO raw_notes
            (id, title, content, source, created_at, updated_at, tags, sensitivity_tier)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """
    for row in NOTES:
        engine.execute(sql, list(row))


def _load_health_metrics(engine: DatabaseEngine) -> None:
    """Load sample health metrics."""
    sql = """
        INSERT OR IGNORE INTO raw_health_metrics
            (id, metric_type, value, unit, recorded_at, source, sensitivity_tier)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """
    for row in HEALTH_METRICS:
        engine.execute(sql, list(row))


def _load_contacts(engine: DatabaseEngine) -> None:
    """Load sample contacts."""
    sql = """
        INSERT OR IGNORE INTO raw_contacts
            (id, name, email, phone, relationship,
             notes, last_contact, sensitivity_tier)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """
    for row in CONTACTS:
        engine.execute(sql, list(row))


def _load_emails(engine: DatabaseEngine) -> None:
    """Load sample emails."""
    sql = """
        INSERT OR IGNORE INTO raw_emails
            (id, source, message_id, subject, from_address,
             to_addresses, date, body_preview, is_read,
             folder, labels, sensitivity_tier)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """
    for row in EMAILS:
        engine.execute(sql, list(row))


def _load_reminders(engine: DatabaseEngine) -> None:
    """Load sample reminders."""
    sql = """
        INSERT OR IGNORE INTO raw_reminders
            (id, source, title, due_date, notes,
             completed, list_name, sensitivity_tier)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """
    for row in REMINDERS:
        engine.execute(sql, list(row))

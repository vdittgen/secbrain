"""Golden-set seeder.

Two source modes:

* ``--from-log`` pulls recent real questions from ``_query_log``
  (see :mod:`src.core.query_tracker`) and emits a YAML scaffold the
  user labels by hand with the chunk IDs each query *should* surface.
* ``--from-raw`` samples records from raw_* tables, uses the local
  LLM to generate plausible questions that would retrieve each one,
  and pre-fills ``expected_doc_ids`` with the source record IDs.
  Produces a fully-labelled draft in one shot — no human labelling
  needed before the first baseline run.

Both modes deduplicate near-identical phrasings. ``--from-raw`` uses
the local Ollama provider unconditionally so seeding never leaks
record content to a remote endpoint, regardless of chat-provider
settings.

Usage::

    python -m evals.retrieval.seeder --from-log --limit 50 \
        --out /tmp/draft.yaml
    python -m evals.retrieval.seeder --from-raw --samples-per-table 8 \
        --out /tmp/draft.yaml

sensitivity_tier: 1 from-log mode; 2 from-raw (reads message/note bodies into LLM)
"""

from __future__ import annotations

import argparse
import logging
import re
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Source loading
# ---------------------------------------------------------------------------


def load_from_query_log(limit: int) -> list[dict[str, Any]]:
    """Pull the most recent N rows from ``_query_log``.

    sensitivity_tier: 1
    """
    from src.core.sqlite.engine import DatabaseEngine

    duck = DatabaseEngine()
    sql = (
        "SELECT question, domain, asked_at "
        "FROM _query_log ORDER BY asked_at DESC LIMIT ?"
    )
    return duck.query(sql, [limit])


# ---------------------------------------------------------------------------
# from-raw mode: sample records + LLM-generate questions
# ---------------------------------------------------------------------------


@dataclass
class SeededCase:
    """One fully-labelled draft case generated from a raw record.

    sensitivity_tier: 2
    """

    query: str
    expected_doc_id: str
    expected_collection: str
    min_tier_reachable: int
    source_table: str


# Table → (SQL, composer, classifier). Composer + classifier reuse the
# indexer's logic so the embedded text and target collection match
# exactly what ``Indexer.full_reindex`` would produce.
_RAW_SOURCES: list[
    tuple[
        str,
        str,
        Callable[[dict[str, Any]], str],
        Callable[..., str],
        int,
    ]
] = []


def _init_raw_sources() -> None:
    """Lazily populate ``_RAW_SOURCES`` (imports are heavy).

    sensitivity_tier: N/A
    """
    from src.core.chromadb.indexer import (
        classify_calendar_domain,
        classify_contact_domain,
        classify_message_domain,
        classify_note_domain,
        compose_calendar_text,
        compose_contact_text,
        compose_message_text,
        compose_note_text,
    )

    if _RAW_SOURCES:
        return
    _RAW_SOURCES.extend(
        [
            (
                "raw_messages",
                "SELECT id, source, sender, recipient, content, "
                "timestamp, sensitivity_tier FROM raw_messages "
                "ORDER BY random() LIMIT ?",
                compose_message_text,
                classify_message_domain,
                2,
            ),
            (
                "raw_calendar_events",
                "SELECT id, title, description, start_time, end_time, "
                "location, attendees, sensitivity_tier "
                "FROM raw_calendar_events ORDER BY random() LIMIT ?",
                compose_calendar_text,
                classify_calendar_domain,
                2,
            ),
            (
                "raw_notes",
                "SELECT id, title, content, source, tags, "
                "sensitivity_tier FROM raw_notes "
                "ORDER BY random() LIMIT ?",
                compose_note_text,
                classify_note_domain,
                1,
            ),
            (
                "raw_contacts",
                "SELECT id, name, email, relationship, notes, "
                "last_contact, sensitivity_tier FROM raw_contacts "
                "ORDER BY random() LIMIT ?",
                compose_contact_text,
                classify_contact_domain,
                2,
            ),
        ],
    )


_QUESTION_SYSTEM_PROMPT = (
    "You generate retrieval eval queries for a personal AI assistant. "
    "Given one personal record, produce N realistic, conversational "
    "questions the user might naturally ask their assistant that would "
    "surface THIS record. Vary phrasing — direct ask, paraphrase, "
    "partial info, indirect reference. Questions must be answerable "
    "from the record alone. Return JSON: "
    '{"questions": ["q1", "q2", ...]}.'
)


def _generate_questions(
    provider: Any,
    composed_text: str,
    *,
    table: str,
    n: int,
) -> list[str]:
    """LLM-generate ``n`` questions that should retrieve the record.

    Falls back to an empty list on any provider error so seeding
    skips bad records rather than aborting the whole run.

    sensitivity_tier: 2
    """
    user_prompt = (
        f"N={n}. Source table: {table}.\n\nRecord:\n{composed_text}"
    )
    try:
        resp = provider.chat_json(
            messages=[
                {"role": "system", "content": _QUESTION_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("question gen failed for %s: %s", table, exc)
        return []
    qs = resp.get("questions") if isinstance(resp, dict) else None
    if not isinstance(qs, list):
        return []
    return [str(q).strip() for q in qs if str(q).strip()][:n]


def load_from_raw(
    *,
    samples_per_table: int,
    questions_per_record: int,
    include_health: bool,
    model: str,
) -> list[SeededCase]:
    """Sample raw records and LLM-generate plausible queries for each.

    Uses the local Ollama provider unconditionally — record content
    never leaves the box during seeding, regardless of the user's
    chat-provider settings.

    sensitivity_tier: 2 (3 when --include-health)
    """
    from src.core.sqlite.engine import DatabaseEngine
    from src.models.llm_provider import OllamaProvider

    _init_raw_sources()
    duck = DatabaseEngine()
    provider = OllamaProvider(model=model)

    cases: list[SeededCase] = []
    sources = list(_RAW_SOURCES)
    if include_health:
        from src.core.chromadb.indexer import compose_health_metric_text

        sources.append(
            (
                "raw_health_metrics",
                "SELECT id, metric_type, value, unit, recorded_at, "
                "source, sensitivity_tier FROM raw_health_metrics "
                "ORDER BY random() LIMIT ?",
                compose_health_metric_text,
                lambda _row: "health",
                3,
            ),
        )

    for table, sql, composer, classifier, default_tier in sources:
        try:
            rows = duck.query(sql, [samples_per_table])
        except Exception as exc:  # noqa: BLE001
            logger.warning("sampling %s failed: %s", table, exc)
            continue
        for row in rows:
            try:
                text = composer(row)
            except Exception as exc:  # noqa: BLE001
                logger.warning("compose failed (%s): %s", table, exc)
                continue
            domain = classifier(row) if table != "raw_messages" else (
                classifier(row, [])
            )
            tier = int(row.get("sensitivity_tier") or default_tier)
            questions = _generate_questions(
                provider, text, table=table, n=questions_per_record,
            )
            for q in questions:
                cases.append(
                    SeededCase(
                        query=q,
                        expected_doc_id=str(row["id"]),
                        expected_collection=domain,
                        min_tier_reachable=tier,
                        source_table=table,
                    ),
                )
    return cases


# ---------------------------------------------------------------------------
# Dedup
# ---------------------------------------------------------------------------

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def _signature(q: str) -> str:
    """Order-insensitive token bag for crude near-dupe detection.

    sensitivity_tier: N/A
    """
    return " ".join(sorted(_TOKEN_RE.findall(q.lower())))


def dedupe(questions: list[str]) -> list[str]:
    """Drop near-duplicate questions, preserving first-seen order.

    sensitivity_tier: N/A
    """
    seen: set[str] = set()
    out: list[str] = []
    for q in questions:
        q = q.strip()
        if not q:
            continue
        sig = _signature(q)
        if sig in seen:
            continue
        seen.add(sig)
        out.append(q)
    return out


# ---------------------------------------------------------------------------
# YAML emission
# ---------------------------------------------------------------------------


def _slug(q: str, fallback: str) -> str:
    """Filename-safe slug for case names.

    sensitivity_tier: N/A
    """
    return re.sub(r"[^a-z0-9]+", "_", q.lower()).strip("_")[:40] or fallback


def emit_yaml(questions: list[str], domains: list[str]) -> str:
    """Render an unlabelled scaffold from ``--from-log`` rows.

    The user fills in ``expected_doc_ids`` by hand after running each
    query in the app and noting which records *should* have surfaced.
    Hand-written (not yaml.dump) for diff-friendliness + inline notes.

    sensitivity_tier: 1
    """
    lines = [
        "# Draft retrieval golden cases — fill in expected_doc_ids by hand.",
        "#",
        "# For each case: run the query in the app, look at what Brain Agent",
        "# actually returns vs. what SHOULD have come up, and list the record",
        "# IDs the retriever ought to surface. Use base IDs unless you want",
        "# to assert a specific chunk landed.",
        "#",
        "# sensitivity_tier: 1",
        "",
        "name: retrieval_golden_draft",
        "default_k: 10",
        "cases:",
    ]
    for i, (q, d) in enumerate(zip(questions, domains, strict=False), start=1):
        safe_q = q.replace('"', "'")
        lines.extend(
            [
                f"  - name: {_slug(q, f'case_{i}')}",
                f'    query: "{safe_q}"',
                "    expected_doc_ids: []  # TODO: label",
                f"    expected_collections: [{d or 'personal'}]",
                "    min_tier_reachable: 2",
                "    notes: |",
                "      Seeded from _query_log. Replace expected_doc_ids "
                "before use.",
                "",
            ],
        )
    return "\n".join(lines)


def emit_yaml_from_raw(cases: list[SeededCase]) -> str:
    """Render a labelled YAML draft from ``--from-raw`` cases.

    ``expected_doc_ids`` is pre-filled with the source record ID so
    the file is immediately usable as a baseline. Hand-review still
    recommended: the LLM occasionally invents questions that wouldn't
    plausibly surface the record (false positives in the eval).

    sensitivity_tier: 1
    """
    lines = [
        "# Draft retrieval golden cases — auto-labelled from raw records.",
        "#",
        "# Each case was generated by sampling a record from a raw_* table",
        "# and asking the local LLM what questions would naturally retrieve",
        "# that record. expected_doc_ids is pre-filled with the source ID.",
        "#",
        "# Hand-review before locking in as baseline — drop cases where the",
        "# query is too generic (would plausibly retrieve many other records)",
        "# or doesn't actually require this specific record.",
        "#",
        "# sensitivity_tier: 1",
        "",
        "name: retrieval_golden_draft",
        "default_k: 10",
        "cases:",
    ]
    for i, c in enumerate(cases, start=1):
        safe_q = c.query.replace('"', "'")
        safe_id = c.expected_doc_id.replace('"', "'")
        lines.extend(
            [
                f"  - name: {_slug(c.query, f'case_{i}')}",
                f'    query: "{safe_q}"',
                f'    expected_doc_ids: ["{safe_id}"]',
                f"    expected_collections: [{c.expected_collection}]",
                f"    min_tier_reachable: {c.min_tier_reachable}",
                "    notes: |",
                f"      Auto-seeded from {c.source_table}. "
                "Hand-review before baseline lock.",
                "",
            ],
        )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _run_from_log(limit: int) -> tuple[int, str]:
    """Execute ``--from-log`` and return (case_count, yaml_text).

    sensitivity_tier: 1
    """
    rows = load_from_query_log(limit)
    questions = [str(r.get("question", "")) for r in rows]
    domains = [str(r.get("domain", "")) for r in rows]
    seen: set[str] = set()
    unique_q: list[str] = []
    unique_d: list[str] = []
    for q, d in zip(questions, domains, strict=False):
        q = q.strip()
        if not q:
            continue
        sig = _signature(q)
        if sig in seen:
            continue
        seen.add(sig)
        unique_q.append(q)
        unique_d.append(d)
    return len(unique_q), emit_yaml(unique_q, unique_d)


def _run_from_raw(
    samples_per_table: int,
    questions_per_record: int,
    include_health: bool,
    model: str,
) -> tuple[int, str]:
    """Execute ``--from-raw`` and return (case_count, yaml_text).

    sensitivity_tier: 2 (3 with --include-health)
    """
    cases = load_from_raw(
        samples_per_table=samples_per_table,
        questions_per_record=questions_per_record,
        include_health=include_health,
        model=model,
    )
    seen: set[str] = set()
    unique: list[SeededCase] = []
    for c in cases:
        sig = _signature(c.query)
        if not sig or sig in seen:
            continue
        seen.add(sig)
        unique.append(c)
    return len(unique), emit_yaml_from_raw(unique)


def main(argv: list[str] | None = None) -> int:
    """Entry point for ``python -m evals.retrieval.seeder``.

    sensitivity_tier: N/A
    """
    parser = argparse.ArgumentParser(
        description="Seed a retrieval golden-set draft from real records.",
    )
    src = parser.add_mutually_exclusive_group(required=True)
    src.add_argument(
        "--from-log",
        action="store_true",
        help="Pull recent questions from the DuckDB _query_log table.",
    )
    src.add_argument(
        "--from-raw",
        action="store_true",
        help=(
            "Sample raw_* tables and LLM-generate questions (local Ollama, "
            "fully labelled — no manual ID labelling required)."
        ),
    )
    parser.add_argument(
        "--limit", type=int, default=50,
        help="--from-log only: max rows to pull from _query_log.",
    )
    parser.add_argument(
        "--samples-per-table", type=int, default=8,
        help="--from-raw only: rows to sample per raw_* table.",
    )
    parser.add_argument(
        "--questions-per-record", type=int, default=2,
        help="--from-raw only: questions the LLM generates per record.",
    )
    parser.add_argument(
        "--include-health", action="store_true",
        help="--from-raw only: include raw_health_metrics (tier 3).",
    )
    parser.add_argument(
        "--model", default="gemma4:e2b",
        help=(
            "--from-raw only: local Ollama model for question generation "
            "(default: gemma4:e2b, matches the project's fallback). "
            "Must be a model name from `ollama list`."
        ),
    )
    parser.add_argument(
        "--out", type=Path, default=None,
        help=(
            "Write the draft YAML here. The labelled set should live "
            "OUTSIDE the repo (recommended: "
            "~/.arandu/evals/retrieval_golden.yaml) so real record "
            "IDs and names never enter the open-source codebase. "
            "Defaults to stdout when omitted."
        ),
    )
    args = parser.parse_args(argv)

    if args.from_log:
        count, yaml_text = _run_from_log(args.limit)
    else:
        count, yaml_text = _run_from_raw(
            samples_per_table=args.samples_per_table,
            questions_per_record=args.questions_per_record,
            include_health=args.include_health,
            model=args.model,
        )

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(yaml_text, encoding="utf-8")
        sys.stderr.write(f"wrote {count} cases to {args.out}\n")
    else:
        sys.stdout.write(yaml_text)
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())

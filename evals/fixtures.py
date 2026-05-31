"""Lightweight test fixtures for eval tasks.

The Brain Q&A eval needs a ``QueryEngine`` so the orchestrator can
call its ``recall_context`` tool. Running a real engine in evals
would pull in DuckDB + ChromaDB + Kuzu + a populated SQLite, which
breaks hermeticity and forces every case to depend on whatever data
the developer happens to have on disk.

:class:`FakeQueryEngine` returns a canned :class:`QueryContext` per
question. Test datasets supply the context inline under
``inputs.fixture`` so each case is self-contained.

sensitivity_tier: N/A — synthetic data only
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from typing import Any


@dataclass
class _Snippet:
    """One question-shaped fixture entry.

    sensitivity_tier: N/A
    """

    match: re.Pattern[str]
    vector_results: list[dict[str, Any]] = field(default_factory=list)
    structured_data: list[dict[str, Any]] = field(default_factory=list)
    graph_context: list[dict[str, Any]] = field(default_factory=list)


def _coerce_snippets(fixture: Any) -> list[_Snippet]:
    """Translate YAML-loaded fixture into matchable snippets.

    Accepted shapes::

        # always-match
        {vector_results: [...], structured_data: [...]}

        # per-question keyword match
        [
          {match: "renovation",
           structured_data: [{...}]},
          {match: "schedule",
           structured_data: [{...}]},
        ]

    sensitivity_tier: N/A
    """
    if fixture is None:
        return []
    if isinstance(fixture, dict):
        return [_make_snippet(fixture, ".*")]
    if isinstance(fixture, list):
        return [
            _make_snippet(entry, entry.get("match", ".*"))
            for entry in fixture
            if isinstance(entry, dict)
        ]
    return []


def _make_snippet(entry: dict[str, Any], match: str) -> _Snippet:
    """Build one snippet, flattening the convenience YAML shape.

    The real ``QueryContext.structured_data`` is a flat list of row
    dicts, each carrying ``source_table`` and ``sensitivity_tier``
    inline (that's what ``format_context`` and the sources list in
    ``BrainResponse`` rely on). YAML datasets are easier to author
    when rows are grouped under a single ``table:`` key, so we
    accept either shape here:

        # flat (matches QueryEngine.query output)
        structured_data:
          - {source_table: raw_messages, sensitivity_tier: 2,
             id: m1, sender_name: Mom, content: "..."}

        # grouped (translated to flat form)
        structured_data:
          - table: raw_messages
            rows:
              - {sender_name: Mom, content: "..."}

    sensitivity_tier: N/A
    """
    return _Snippet(
        match=re.compile(match, re.IGNORECASE),
        vector_results=list(entry.get("vector_results", []) or []),
        structured_data=_flatten_structured(
            entry.get("structured_data", []) or [],
        ),
        graph_context=list(entry.get("graph_context", []) or []),
    )


def _flatten_structured(raw: list[Any]) -> list[dict[str, Any]]:
    """Flatten ``[{table, rows: [...]}]`` into the row list the
    real ``QueryEngine`` returns.

    Each emitted row carries ``source_table`` and a default
    ``sensitivity_tier`` of 2 unless the dataset overrides it,
    matching the synthetic ingest path. ``id`` defaults to
    ``f"{table}#{i}"`` so the sources list has stable identifiers.

    sensitivity_tier: N/A
    """
    flat: list[dict[str, Any]] = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        if "rows" in entry and isinstance(entry["rows"], list):
            table = entry.get("table", "unknown")
            for idx, row in enumerate(entry["rows"]):
                if not isinstance(row, dict):
                    continue
                flat.append(
                    {
                        "source_table": table,
                        "id": row.get("id", f"{table}#{idx}"),
                        "sensitivity_tier": row.get(
                            "sensitivity_tier", 2,
                        ),
                        **row,
                    },
                )
        else:
            # Already flat; just ensure source_table is set so
            # downstream formatters have something to label with.
            flat.append(
                {
                    "source_table": entry.get(
                        "source_table",
                        entry.get("table", "unknown"),
                    ),
                    "sensitivity_tier": entry.get(
                        "sensitivity_tier", 2,
                    ),
                    **entry,
                },
            )
    return flat


class FakeQueryEngine:
    """Returns canned :class:`QueryContext` results.

    Only the surface :class:`BrainAgentV2` uses is implemented:
    :meth:`query`. The internal ``_duck`` attribute is set to ``None``
    so the ``propose_action`` tool short-circuits when an eval case
    doesn't enable it.

    sensitivity_tier: N/A
    """

    def __init__(self, fixture: Any = None) -> None:
        self._snippets = _coerce_snippets(fixture)
        # Brain's propose_action tool reads ``_duck`` off the engine.
        # Action proposals aren't part of the Q&A eval surface, so a
        # ``None`` here is the right "feature off" signal.
        self._duck = None

    def query(
        self,
        question: str,
        *,
        max_sensitivity_tier: int = 2,
        reference_date: date | None = None,
    ) -> Any:
        """Return a :class:`QueryContext` matching ``question``.

        sensitivity_tier: N/A
        """
        # Import locally so this module can be loaded without the
        # full project import chain (DuckDB, Kuzu, ChromaDB).
        from src.core.query_engine import QueryContext

        del max_sensitivity_tier, reference_date  # unused in fixture
        vec: list[dict[str, Any]] = []
        rows: list[dict[str, Any]] = []
        graph: list[dict[str, Any]] = []
        for snippet in self._snippets:
            if snippet.match.search(question):
                vec.extend(snippet.vector_results)
                rows.extend(snippet.structured_data)
                graph.extend(snippet.graph_context)
        return QueryContext(
            question=question,
            vector_results=vec,
            graph_context=graph,
            structured_data=rows,
            metadata={"source": "evals.fixtures"},
        )


__all__ = ["FakeQueryEngine"]

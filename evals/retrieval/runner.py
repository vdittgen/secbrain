"""Retrieval-quality eval runner.

Loads a golden YAML, executes each query against the live ChromaDB
collections, computes hit@k / MRR / NDCG@k per case and aggregate,
writes a JSON report.

Three modes:

* ``--mode raw`` — bypasses the LLM/rule router and queries all
  collections directly via :class:`VectorEngine.search`. Measures the
  embedding+retrieval ceiling.
* ``--mode hybrid`` — Phase 4 pipeline: vector + BM25 → RRF →
  record-dedup. The mode the Brain Agent uses in production once
  Phase 5 wires the pipeline into ``QueryEngine``.
* ``--mode routed`` — runs the full :class:`QueryEngine.query` path
  including routing, graph fanout, and context assembly. Measures
  end-to-end recall the user actually sees.

Usage::

    python -m evals.retrieval.runner --baseline
    python -m evals.retrieval.runner --mode routed --k 10 --out /tmp/r.json
    python -m evals.retrieval.runner --dataset evals/datasets/retrieval_golden.yaml

Results are written to ``evals/retrieval/results/<tag>.json``. Diff
two runs with ``diff -u`` or a small helper to detect regressions.

sensitivity_tier: 3 (queries hit the live vector store)
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import yaml

from evals.retrieval.metrics import (
    aggregate,
    hit_at_k,
    mrr,
    ndcg_at_k,
    normalise_id,
)

logger = logging.getLogger(__name__)

REPO_DATASET = (
    Path(__file__).resolve().parent.parent / "datasets" / "retrieval_golden.yaml"
)
LOCAL_DATASET = Path.home() / ".arandu" / "evals" / "retrieval_golden.yaml"
# Results JSONs reference real record IDs and query text — same
# privacy posture as the labelled golden YAML. Default to the
# gitignored local location so baselines never leak into the repo.
DEFAULT_RESULTS_DIR = Path.home() / ".arandu" / "evals" / "retrieval_results"


def default_dataset() -> Path:
    """Pick the labelled local override when present; else the repo scaffold.

    The local file lives outside the repo so the user's labelled
    cases (which reference real record IDs and contact names) never
    leak into the open-source codebase. See
    ``evals/datasets/retrieval_golden.yaml`` for the workflow.

    sensitivity_tier: N/A
    """
    return LOCAL_DATASET if LOCAL_DATASET.exists() else REPO_DATASET


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class CaseResult:
    """Per-case retrieval result and metrics.

    sensitivity_tier: 1
    """

    name: str
    query: str
    retrieved_ids: list[str]
    expected_ids: list[str]
    metrics: dict[str, float]
    skipped_reason: str | None = None


@dataclass
class RunReport:
    """Full run report — header + per-case + aggregate.

    sensitivity_tier: 1
    """

    tag: str
    dataset: str
    mode: str
    k: int
    embedding_model: str
    cases: list[CaseResult] = field(default_factory=list)
    aggregate: dict[str, float] = field(default_factory=dict)
    duration_s: float = 0.0


# ---------------------------------------------------------------------------
# Dataset loading
# ---------------------------------------------------------------------------


def load_dataset(path: Path) -> dict[str, Any]:
    """Load the golden YAML.

    sensitivity_tier: 1
    """
    with path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict) or "cases" not in data:
        msg = f"{path}: expected top-level 'cases' list"
        raise ValueError(msg)
    return data


def is_scaffold(case: dict[str, Any]) -> bool:
    """True when the case still holds REPLACE_ME placeholder IDs.

    Scaffolds get skipped instead of failing — they're documentation
    of the schema, not real assertions.

    sensitivity_tier: N/A
    """
    return any("REPLACE_ME" in str(i) for i in case.get("expected_doc_ids", []))


# ---------------------------------------------------------------------------
# Retrieval back-ends
# ---------------------------------------------------------------------------


def _build_engines() -> tuple[Any, Any]:
    """Open the live ChromaDB + DuckDB engines.

    Returns ``(chroma, duck_or_none)``. DuckDB is only needed for the
    routed mode.

    sensitivity_tier: N/A
    """
    from src.core.chromadb.engine import VectorEngine

    chroma = VectorEngine()
    duck = None
    try:
        from src.core.sqlite.engine import DatabaseEngine

        duck = DatabaseEngine()
    except Exception as exc:  # noqa: BLE001
        logger.warning("DuckDB unavailable, routed mode will be limited: %s", exc)
    return chroma, duck


def _embedding_model_name(chroma: Any) -> str:
    """Best-effort lookup of the embedding model identifier.

    sensitivity_tier: N/A
    """
    fn = getattr(chroma, "_embedding_fn", None)
    if fn is None:
        return "unknown"
    return (
        getattr(fn, "model_name", None)
        or getattr(fn, "_model", None)
        or type(fn).__name__
    )


def _retrieve_raw(
    chroma: Any,
    query: str,
    k: int,
    max_tier: int,
    collections: list[str] | None,
) -> list[str]:
    """Search every requested collection and return IDs by ascending distance.

    Pulls ``k`` per collection then re-sorts globally — the same
    ceiling-recall shape as the current ``_vector_search`` at
    ``src/core/query_engine.py:977`` but without the per-collection
    truncation to 3.

    sensitivity_tier: 3
    """
    from src.core.chromadb.engine import COLLECTION_NAMES

    where = {"sensitivity_tier": {"$lte": max_tier}}
    targets = collections or list(COLLECTION_NAMES)
    hits: list[dict[str, Any]] = []
    for name in targets:
        try:
            for r in chroma.search(name, query, n_results=k, where=where):
                r["collection"] = name
                hits.append(r)
        except Exception as exc:  # noqa: BLE001
            logger.warning("search failed for %s: %s", name, exc)
    hits.sort(key=lambda r: r.get("distance", float("inf")))
    return [h["id"] for h in hits[:k]]


def _retrieve_routed(
    chroma: Any,
    duck: Any,
    query: str,
    k: int,
    max_tier: int,
) -> list[str]:
    """Run the full QueryEngine path and return the assembled vector IDs.

    sensitivity_tier: 3
    """
    if duck is None:
        return []
    from src.core.query_engine import QueryEngine

    engine = QueryEngine(duckdb=duck, chromadb=chroma)
    ctx = engine.query(query, max_context_items=k, max_sensitivity_tier=max_tier)
    out: list[str] = []
    for r in getattr(ctx, "vector_results", []) or []:
        rid = r.get("id") if isinstance(r, dict) else getattr(r, "id", None)
        if rid:
            out.append(str(rid))
    return out


def _retrieve_hybrid(
    chroma: Any,
    duck: Any,
    query: str,
    k: int,
    max_tier: int,
    collections: list[str] | None,
) -> list[str]:
    """Run the Phase 4 hybrid pipeline (vector + BM25 → RRF → dedup).

    Returns chunk IDs in fused-rank order, deduped to one chunk per
    source record.

    sensitivity_tier: 3
    """
    if duck is None:
        return []
    from src.core.retrieval.pipeline import HybridSearch

    pipeline = HybridSearch(chroma=chroma, sqlite_db=duck)
    hits = pipeline.search(
        query, top_k=k, max_tier=max_tier, collections=collections,
    )
    return [h.id for h in hits]


# ---------------------------------------------------------------------------
# Per-case execution
# ---------------------------------------------------------------------------


def run_case(
    case: dict[str, Any],
    *,
    chroma: Any,
    duck: Any,
    mode: str,
    k: int,
) -> CaseResult:
    """Execute one case and return its scored result.

    sensitivity_tier: 3
    """
    name = str(case.get("name") or "(unnamed)")
    query = str(case.get("query") or "")
    expected = [str(x) for x in (case.get("expected_doc_ids") or [])]
    collections = case.get("expected_collections")
    max_tier = int(case.get("min_tier_reachable", 3))

    if is_scaffold(case):
        return CaseResult(
            name=name,
            query=query,
            retrieved_ids=[],
            expected_ids=expected,
            metrics={"hit_at_k": 0.0, "mrr": 0.0, "ndcg_at_k": 0.0},
            skipped_reason="scaffold (REPLACE_ME ids — label real cases)",
        )

    if mode == "raw":
        retrieved = _retrieve_raw(
            chroma, query, k=k, max_tier=max_tier, collections=collections,
        )
    elif mode == "hybrid":
        retrieved = _retrieve_hybrid(
            chroma, duck, query, k=k, max_tier=max_tier, collections=collections,
        )
    elif mode == "routed":
        retrieved = _retrieve_routed(
            chroma, duck, query, k=k, max_tier=max_tier,
        )
    else:
        msg = f"unknown mode: {mode}"
        raise ValueError(msg)

    metrics = {
        "hit_at_k": hit_at_k(retrieved, expected, k=k),
        "mrr": mrr(retrieved, expected, k=k),
        "ndcg_at_k": ndcg_at_k(retrieved, expected, k=k),
    }
    return CaseResult(
        name=name,
        query=query,
        retrieved_ids=[normalise_id(r) for r in retrieved],
        expected_ids=expected,
        metrics=metrics,
    )


# ---------------------------------------------------------------------------
# Top-level run
# ---------------------------------------------------------------------------


def run(
    dataset_path: Path,
    *,
    mode: str = "raw",
    k: int = 10,
    tag: str = "manual",
) -> RunReport:
    """Run the full golden set and return the aggregated report.

    sensitivity_tier: 3
    """
    data = load_dataset(dataset_path)
    cases = data.get("cases", [])
    k = int(data.get("default_k", k)) if "default_k" in data else k

    chroma, duck = _build_engines()
    embedding_model = _embedding_model_name(chroma)

    started = time.perf_counter()
    case_results: list[CaseResult] = []
    for case in cases:
        case_results.append(
            run_case(case, chroma=chroma, duck=duck, mode=mode, k=k),
        )
    duration = time.perf_counter() - started

    scored = [c.metrics for c in case_results if c.skipped_reason is None]
    return RunReport(
        tag=tag,
        dataset=str(dataset_path),
        mode=mode,
        k=k,
        embedding_model=str(embedding_model),
        cases=case_results,
        aggregate=aggregate(scored),
        duration_s=duration,
    )


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def _report_to_json(report: RunReport) -> str:
    return json.dumps(asdict(report), indent=2, sort_keys=True)


def _render_table(report: RunReport) -> str:
    lines = [
        f"dataset:         {report.dataset}",
        f"mode:            {report.mode}",
        f"k:               {report.k}",
        f"embedding model: {report.embedding_model}",
        f"duration:        {report.duration_s:.2f}s",
        "",
        "case                                  hit  mrr   ndcg  status",
        "-" * 70,
    ]
    for c in report.cases:
        status = c.skipped_reason or ""
        lines.append(
            f"{c.name[:36].ljust(36)}  "
            f"{c.metrics['hit_at_k']:>3.1f}  "
            f"{c.metrics['mrr']:>4.2f}  "
            f"{c.metrics['ndcg_at_k']:>4.2f}  "
            f"{status[:24]}",
        )
    lines.append("-" * 70)
    if report.aggregate:
        agg = report.aggregate
        lines.append(
            "AGGREGATE                             "
            f"{agg.get('hit_at_k', 0):>3.1f}  "
            f"{agg.get('mrr', 0):>4.2f}  "
            f"{agg.get('ndcg_at_k', 0):>4.2f}  "
            f"({len([c for c in report.cases if c.skipped_reason is None])} scored)",
        )
    else:
        lines.append("AGGREGATE: no scored cases (all scaffolds — label real ones)")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    """Entry point for ``python -m evals.retrieval.runner``.

    sensitivity_tier: N/A
    """
    parser = argparse.ArgumentParser(
        description="Run retrieval-quality evals against the live vector store.",
    )
    parser.add_argument(
        "--dataset",
        type=Path,
        default=None,
        help=(
            f"Golden YAML (default: local override "
            f"{LOCAL_DATASET} when present, else repo scaffold "
            f"{REPO_DATASET})"
        ),
    )
    parser.add_argument(
        "--mode",
        choices=("raw", "hybrid", "routed"),
        default="raw",
        help=(
            "raw = direct VectorEngine.search; "
            "hybrid = vector + BM25 RRF (Phase 4); "
            "routed = full QueryEngine"
        ),
    )
    parser.add_argument("--k", type=int, default=10)
    parser.add_argument(
        "--tag",
        default="manual",
        help="Label written into the report (e.g. baseline, phase1, phase3).",
    )
    parser.add_argument(
        "--baseline",
        action="store_true",
        help="Shorthand for --tag baseline --out results/baseline.json",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Write JSON report here (defaults to stdout JSON when --json).",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit JSON to stdout instead of the text table.",
    )
    args = parser.parse_args(argv)

    if args.baseline:
        args.tag = "baseline"
        if args.out is None:
            args.out = DEFAULT_RESULTS_DIR / "baseline.json"

    dataset = args.dataset or default_dataset()
    report = run(dataset, mode=args.mode, k=args.k, tag=args.tag)

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(_report_to_json(report), encoding="utf-8")
        sys.stderr.write(f"wrote {args.out}\n")

    sys.stdout.write(
        _report_to_json(report) if args.json else _render_table(report),
    )
    sys.stdout.flush()
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())

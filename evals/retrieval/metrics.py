"""Retrieval-quality metrics.

Pure functions over ranked ID lists. All metrics treat any ID in
``expected`` as binary-relevant (relevance = 1) and the rest as
irrelevant (relevance = 0). Chunks belonging to the same source
record are normalised to their record_id before comparison so a
case that expects ``msg_42`` matches whether the retriever returned
``msg_42`` or ``msg_42-chunk-3``.

sensitivity_tier: N/A
"""

from __future__ import annotations

import math

CHUNK_SUFFIX = "-chunk-"


def normalise_id(doc_id: str) -> str:
    """Strip ``-chunk-N`` suffix so chunk IDs collapse to the base record.

    sensitivity_tier: N/A
    """
    idx = doc_id.find(CHUNK_SUFFIX)
    return doc_id if idx < 0 else doc_id[:idx]


def hit_at_k(
    retrieved: list[str],
    expected: list[str],
    k: int = 10,
) -> float:
    """1.0 if any expected ID appears in the first ``k`` retrieved IDs.

    sensitivity_tier: N/A
    """
    if not expected:
        return 0.0
    want = {normalise_id(e) for e in expected}
    seen = {normalise_id(r) for r in retrieved[:k]}
    return 1.0 if want & seen else 0.0


def mrr(
    retrieved: list[str],
    expected: list[str],
    k: int | None = None,
) -> float:
    """Mean reciprocal rank of the first hit. 0.0 when no expected ID lands.

    sensitivity_tier: N/A
    """
    if not expected:
        return 0.0
    want = {normalise_id(e) for e in expected}
    limit = len(retrieved) if k is None else min(k, len(retrieved))
    for rank, rid in enumerate(retrieved[:limit], start=1):
        if normalise_id(rid) in want:
            return 1.0 / rank
    return 0.0


def ndcg_at_k(
    retrieved: list[str],
    expected: list[str],
    k: int = 10,
) -> float:
    """Binary-relevance NDCG@k.

    DCG = sum_{i=1..k} rel_i / log2(i+1).
    IDCG = DCG of the optimal ranking (all expected IDs first, capped at k).

    sensitivity_tier: N/A
    """
    if not expected:
        return 0.0
    want = {normalise_id(e) for e in expected}
    dcg = 0.0
    for i, rid in enumerate(retrieved[:k], start=1):
        if normalise_id(rid) in want:
            dcg += 1.0 / math.log2(i + 1)
    ideal_hits = min(len(want), k)
    idcg = sum(1.0 / math.log2(i + 1) for i in range(1, ideal_hits + 1))
    return dcg / idcg if idcg > 0 else 0.0


def aggregate(per_case: list[dict[str, float]]) -> dict[str, float]:
    """Mean each metric across cases. Empty input returns zeros.

    sensitivity_tier: N/A
    """
    if not per_case:
        return {}
    keys = per_case[0].keys()
    return {
        k: sum(c[k] for c in per_case) / len(per_case) for k in keys
    }

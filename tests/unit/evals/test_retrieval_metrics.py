"""Unit tests for :mod:`evals.retrieval.metrics`.

sensitivity_tier: N/A
"""

from __future__ import annotations

import math

from evals.retrieval.metrics import (
    CHUNK_SUFFIX,
    aggregate,
    hit_at_k,
    mrr,
    ndcg_at_k,
    normalise_id,
)

# ---------------------------------------------------------------------------
# normalise_id
# ---------------------------------------------------------------------------


def test_normalise_id_strips_chunk_suffix() -> None:
    assert normalise_id(f"msg_42{CHUNK_SUFFIX}0") == "msg_42"
    assert normalise_id(f"msg_42{CHUNK_SUFFIX}7") == "msg_42"


def test_normalise_id_idempotent_on_bare_id() -> None:
    assert normalise_id("msg_42") == "msg_42"


# ---------------------------------------------------------------------------
# hit_at_k
# ---------------------------------------------------------------------------


def test_hit_at_k_finds_expected_in_top_k() -> None:
    assert hit_at_k(["a", "b", "c"], ["c"], k=10) == 1.0


def test_hit_at_k_misses_beyond_k() -> None:
    assert hit_at_k(["a", "b", "c"], ["c"], k=2) == 0.0


def test_hit_at_k_collapses_chunk_ids() -> None:
    # Retriever returned a chunk; case expects the base record.
    assert hit_at_k([f"msg_42{CHUNK_SUFFIX}3"], ["msg_42"], k=10) == 1.0


def test_hit_at_k_empty_expected_is_zero() -> None:
    assert hit_at_k(["a"], [], k=10) == 0.0


# ---------------------------------------------------------------------------
# mrr
# ---------------------------------------------------------------------------


def test_mrr_first_hit_at_rank_1() -> None:
    assert mrr(["a", "b"], ["a"]) == 1.0


def test_mrr_first_hit_at_rank_2() -> None:
    assert mrr(["x", "a"], ["a"]) == 0.5


def test_mrr_no_hit_is_zero() -> None:
    assert mrr(["x", "y"], ["a"]) == 0.0


def test_mrr_respects_k_cutoff() -> None:
    assert mrr(["x", "y", "a"], ["a"], k=2) == 0.0


# ---------------------------------------------------------------------------
# ndcg_at_k
# ---------------------------------------------------------------------------


def test_ndcg_at_k_perfect_ranking() -> None:
    assert ndcg_at_k(["a", "b", "c"], ["a", "b", "c"], k=3) == 1.0


def test_ndcg_at_k_early_hits_score_higher_than_late_hits() -> None:
    # Hits earlier in the list contribute more DCG. With binary
    # relevance + full overlap + |retrieved| == |expected| NDCG is
    # order-insensitive, so the test forces partial overlap to expose
    # the ranking sensitivity.
    early = ndcg_at_k(["a", "b", "x", "y"], ["a", "b"], k=4)
    late = ndcg_at_k(["x", "y", "a", "b"], ["a", "b"], k=4)
    assert late < early


def test_ndcg_at_k_single_hit_at_rank_1() -> None:
    # DCG = 1/log2(2) = 1.0; IDCG = 1.0; NDCG = 1.0.
    assert ndcg_at_k(["a"], ["a"], k=10) == 1.0


def test_ndcg_at_k_single_hit_at_rank_3() -> None:
    # DCG = 1/log2(4) = 0.5; IDCG = 1.0.
    val = ndcg_at_k(["x", "y", "a"], ["a"], k=10)
    assert math.isclose(val, 0.5)


def test_ndcg_at_k_no_hit_is_zero() -> None:
    assert ndcg_at_k(["x"], ["a"], k=10) == 0.0


# ---------------------------------------------------------------------------
# aggregate
# ---------------------------------------------------------------------------


def test_aggregate_means_each_metric() -> None:
    per_case = [
        {"hit_at_k": 1.0, "mrr": 1.0, "ndcg_at_k": 1.0},
        {"hit_at_k": 0.0, "mrr": 0.0, "ndcg_at_k": 0.0},
    ]
    agg = aggregate(per_case)
    assert agg == {"hit_at_k": 0.5, "mrr": 0.5, "ndcg_at_k": 0.5}


def test_aggregate_empty_returns_empty_dict() -> None:
    assert aggregate([]) == {}

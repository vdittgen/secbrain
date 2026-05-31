"""Tests for :mod:`src.core.retrieval.fusion`.

sensitivity_tier: N/A
"""

from __future__ import annotations

import pytest
from src.core.retrieval.fusion import (
    dedupe_by_record,
    reciprocal_rank_fusion,
)


class TestReciprocalRankFusion:
    def test_empty_returns_empty(self) -> None:
        assert reciprocal_rank_fusion([]) == []

    def test_single_list_preserves_order(self) -> None:
        out = reciprocal_rank_fusion([["a", "b", "c"]], k=60)
        ids = [d for d, _ in out]
        assert ids == ["a", "b", "c"]

    def test_agreement_boosts_score(self) -> None:
        # Both rankings agree on "a" at rank 1 → score = 2 * (1/61).
        # "b" appears at rank 2 in one list only → score = 1/62.
        out = reciprocal_rank_fusion(
            [["a", "b"], ["a"]],
            k=60,
        )
        scores = dict(out)
        assert scores["a"] > scores["b"]
        assert abs(scores["a"] - 2 / 61) < 1e-9

    def test_disagreement_blends(self) -> None:
        # "a" is rank 1 in list 1, absent in list 2.
        # "b" is rank 2 in list 1, rank 1 in list 2.
        # b should score higher despite being lower in the first list.
        out = reciprocal_rank_fusion([["a", "b"], ["b", "a"]], k=60)
        scores = dict(out)
        # Symmetric — both should tie.
        assert abs(scores["a"] - scores["b"]) < 1e-9

    def test_weights_applied(self) -> None:
        # Bias list 1 by 2x; "a" wins even though it's only in list 1.
        out = reciprocal_rank_fusion(
            [["a"], ["b"]],
            k=60,
            weights=[2.0, 1.0],
        )
        scores = dict(out)
        assert scores["a"] > scores["b"]

    def test_weights_length_mismatch_raises(self) -> None:
        with pytest.raises(ValueError):
            reciprocal_rank_fusion([["a"], ["b"]], weights=[1.0])

    def test_sorted_desc(self) -> None:
        out = reciprocal_rank_fusion(
            [["a", "b", "c", "d"], ["c", "b", "a"]],
        )
        scores = [s for _, s in out]
        assert scores == sorted(scores, reverse=True)


class TestDedupeByRecord:
    def test_keeps_first_per_record(self) -> None:
        ranked = [
            ("rec_1-chunk-0", 0.9),
            ("rec_1-chunk-1", 0.8),
            ("rec_2-chunk-0", 0.7),
        ]
        out = dedupe_by_record(ranked)
        assert [r[0] for r in out] == ["rec_1-chunk-0", "rec_2-chunk-0"]

    def test_no_chunk_suffix_passthrough(self) -> None:
        ranked = [("rec_a", 0.9), ("rec_b", 0.8)]
        out = dedupe_by_record(ranked)
        assert out == ranked

    def test_explicit_mapping(self) -> None:
        ranked = [("c1", 0.9), ("c2", 0.8), ("c3", 0.7)]
        mapping = {"c1": "doc_x", "c2": "doc_x", "c3": "doc_y"}
        out = dedupe_by_record(ranked, mapping)
        assert [r[0] for r in out] == ["c1", "c3"]

    def test_empty(self) -> None:
        assert dedupe_by_record([]) == []

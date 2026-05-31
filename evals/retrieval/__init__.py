"""Retrieval-quality evaluation harness.

Numeric metrics (hit@k, MRR, NDCG@k) over a golden set of
(query, expected chunk IDs) pairs. Distinct from the pydantic-evals
agent suites in ``evals/datasets/`` — those grade per-case
pass/fail; retrieval evals report aggregate scores so changes to
the embedding model, chunking, reranker, or routing are measurable
across the overhaul phases.

sensitivity_tier: 1 (queries are user-provided; chunk IDs reference user data)
"""

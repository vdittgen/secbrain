"""Tests for :class:`ChromaEmbeddingFunctionAdapter`.

Verifies the Phase 1 adapter that bridges
:class:`src.models.embedding_provider.EmbeddingProvider` to
ChromaDB's :class:`EmbeddingFunction` interface.

sensitivity_tier: N/A
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import numpy as np
from src.core.chromadb.embedding import ChromaEmbeddingFunctionAdapter
from src.models.embedding_provider import (
    EmbeddingProvider,
    EmbeddingUnavailableError,
)


class _FakeProvider(EmbeddingProvider):
    """Provider stub recording calls for assertions.

    sensitivity_tier: N/A
    """

    def __init__(
        self,
        vectors: list[list[float]],
        raises: Exception | None = None,
    ) -> None:
        self._vectors = vectors
        self._raises = raises
        self.calls: list[Any] = []

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        self.calls.append(("docs", texts))
        if self._raises is not None:
            raise self._raises
        return self._vectors[: len(texts)]

    def embed_query(self, text: str) -> list[float]:
        self.calls.append(("query", text))
        if self._raises is not None:
            raise self._raises
        return self._vectors[0]

    @property
    def model_name(self) -> str:
        return "fake-model"

    @property
    def provider_name(self) -> str:
        return "fake"

    @property
    def dimension(self) -> int:
        return len(self._vectors[0]) if self._vectors else 0


class TestAdapterHappyPath:
    def test_forwards_to_provider(self) -> None:
        p = _FakeProvider([[0.1] * 4, [0.2] * 4])
        adapter = ChromaEmbeddingFunctionAdapter(p)
        out = adapter(["doc1", "doc2"])
        assert len(out) == 2
        assert p.calls == [("docs", ["doc1", "doc2"])]
        assert adapter.is_using_provider is True
        assert adapter.model_name == "fake-model"

    def test_exposes_provider(self) -> None:
        p = _FakeProvider([[0.0]])
        adapter = ChromaEmbeddingFunctionAdapter(p)
        assert adapter.provider is p


class TestAdapterFallback:
    def test_unavailable_triggers_default_embedder(self) -> None:
        p = _FakeProvider(
            [],
            raises=EmbeddingUnavailableError("nope"),
        )
        adapter = ChromaEmbeddingFunctionAdapter(p)
        # Patch the lazy default to avoid pulling the real model.
        fake_default = MagicMock(return_value=[[0.5] * 3])
        adapter._fallback = fake_default  # type: ignore[assignment]
        out = adapter(["x"])
        # ChromaDB's EmbeddingFunction wrapper normalises the return
        # to a numpy array, so compare element-wise.
        assert np.array_equal(np.asarray(out), np.asarray([[0.5] * 3]))
        assert adapter.is_using_provider is False
        fake_default.assert_called_once_with(["x"])

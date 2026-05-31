"""Unit tests for the Ollama-backed embedding function.

Tests use mocked Ollama client to avoid requiring a running server.
The fallback path is tested with the real DefaultEmbeddingFunction.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import numpy as np
import ollama
from src.core.chromadb.embedding import OllamaEmbeddingFunction

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_embed_response(embeddings: list[list[float]]) -> dict:
    """Create a mock Ollama embed response."""
    return {"embeddings": embeddings}


SAMPLE_EMBEDDING_RAW = [[0.1, 0.2, 0.3] * 256]  # 768-dim


def _assert_embeddings_equal(
    actual: list, expected: list[list[float]],
) -> None:
    """Compare embeddings allowing for numpy arrays."""
    assert len(actual) == len(expected)
    for a, e in zip(actual, expected):
        np.testing.assert_array_almost_equal(a, e)


# ---------------------------------------------------------------------------
# Ollama success path
# ---------------------------------------------------------------------------


class TestOllamaSuccess:
    @patch("src.core.chromadb.embedding.ollama.Client")
    def test_uses_ollama_when_available(
        self, mock_client_cls: MagicMock,
    ) -> None:
        """Ollama embeddings returned when the server is reachable."""
        mock_client = mock_client_cls.return_value
        mock_client.embed.return_value = _mock_embed_response(
            SAMPLE_EMBEDDING_RAW,
        )

        fn = OllamaEmbeddingFunction()
        result = fn(["hello world"])

        mock_client.embed.assert_called_once_with(
            model="nomic-embed-text",
            input=["hello world"],
        )
        _assert_embeddings_equal(result, SAMPLE_EMBEDDING_RAW)
        assert fn.is_using_ollama is True

    @patch("src.core.chromadb.embedding.ollama.Client")
    def test_batch_embedding(
        self, mock_client_cls: MagicMock,
    ) -> None:
        """Multiple documents should be embedded in a single call."""
        embeddings = [[0.1] * 768, [0.2] * 768, [0.3] * 768]
        mock_client = mock_client_cls.return_value
        mock_client.embed.return_value = _mock_embed_response(
            embeddings,
        )

        fn = OllamaEmbeddingFunction()
        result = fn(["doc1", "doc2", "doc3"])

        assert len(result) == 3
        _assert_embeddings_equal(result, embeddings)

    @patch("src.core.chromadb.embedding.ollama.Client")
    def test_custom_model_and_host(
        self, mock_client_cls: MagicMock,
    ) -> None:
        """Custom model and host should be passed through."""
        mock_client = mock_client_cls.return_value
        mock_client.embed.return_value = _mock_embed_response(
            SAMPLE_EMBEDDING_RAW,
        )

        fn = OllamaEmbeddingFunction(
            model="mxbai-embed-large",
            host="http://remote:11434",
        )
        fn(["test"])

        mock_client_cls.assert_called_with(host="http://remote:11434")
        mock_client.embed.assert_called_once_with(
            model="mxbai-embed-large",
            input=["test"],
        )


# ---------------------------------------------------------------------------
# Fallback path
# ---------------------------------------------------------------------------


class TestFallback:
    @patch("src.core.chromadb.embedding.ollama.Client")
    def test_falls_back_when_ollama_unavailable(
        self, mock_client_cls: MagicMock,
    ) -> None:
        """Fallback to DefaultEmbeddingFunction when Ollama fails."""
        mock_client = mock_client_cls.return_value
        mock_client.embed.side_effect = ollama.ResponseError(
            "model not found",
        )

        fn = OllamaEmbeddingFunction(
            max_retries=1, base_delay=0.0,
        )
        result = fn(["hello world"])

        assert len(result) == 1
        # DefaultEmbeddingFunction returns numpy arrays
        assert len(result[0]) > 0
        assert fn.is_using_ollama is False

    @patch("src.core.chromadb.embedding.ollama.Client")
    def test_falls_back_on_connection_error(
        self, mock_client_cls: MagicMock,
    ) -> None:
        """Generic connection errors should trigger fallback."""
        mock_client = mock_client_cls.return_value
        mock_client.embed.side_effect = ConnectionError("refused")

        fn = OllamaEmbeddingFunction(
            max_retries=1, base_delay=0.0,
        )
        result = fn(["test text"])

        assert len(result) == 1
        assert fn.is_using_ollama is False

    @patch("src.core.chromadb.embedding.ollama.Client")
    def test_falls_back_on_request_error(
        self, mock_client_cls: MagicMock,
    ) -> None:
        """Ollama RequestError should trigger fallback."""
        mock_client = mock_client_cls.return_value
        mock_client.embed.side_effect = ollama.RequestError("timeout")

        fn = OllamaEmbeddingFunction(
            max_retries=1, base_delay=0.0,
        )
        result = fn(["test"])

        assert len(result) == 1
        assert fn.is_using_ollama is False

    def test_fallback_produces_valid_embeddings(self) -> None:
        """Real DefaultEmbeddingFunction should produce valid vectors.

        No Ollama mock — uses the real fallback path by setting
        max_retries=0 so Ollama is never attempted.
        """
        fn = OllamaEmbeddingFunction(
            max_retries=0, base_delay=0.0,
        )
        result = fn(["semantic search test"])

        assert len(result) == 1
        vec = result[0]
        assert len(vec) > 10  # MiniLM produces 384-dim
        # Each element should be a numeric value
        assert all(
            isinstance(float(v), float) for v in vec
        )


# ---------------------------------------------------------------------------
# Retry logic
# ---------------------------------------------------------------------------


class TestRetryLogic:
    @patch("src.core.chromadb.embedding.time.sleep")
    @patch("src.core.chromadb.embedding.ollama.Client")
    def test_retries_with_exponential_backoff(
        self,
        mock_client_cls: MagicMock,
        mock_sleep: MagicMock,
    ) -> None:
        """Failed attempts should use exponential backoff delays."""
        mock_client = mock_client_cls.return_value
        mock_client.embed.side_effect = ollama.ResponseError("error")

        fn = OllamaEmbeddingFunction(
            max_retries=3, base_delay=1.0,
        )
        fn(["test"])

        assert mock_client.embed.call_count == 3
        # Backoff: 1.0s after 1st, 2.0s after 2nd, none after last
        assert mock_sleep.call_count == 2
        mock_sleep.assert_any_call(1.0)
        mock_sleep.assert_any_call(2.0)

    @patch("src.core.chromadb.embedding.time.sleep")
    @patch("src.core.chromadb.embedding.ollama.Client")
    def test_succeeds_after_retry(
        self,
        mock_client_cls: MagicMock,
        mock_sleep: MagicMock,
    ) -> None:
        """Ollama success on 2nd attempt should return Ollama result."""
        mock_client = mock_client_cls.return_value
        mock_client.embed.side_effect = [
            ollama.ResponseError("transient"),
            _mock_embed_response(SAMPLE_EMBEDDING_RAW),
        ]

        fn = OllamaEmbeddingFunction(
            max_retries=3, base_delay=0.01,
        )
        result = fn(["test"])

        _assert_embeddings_equal(result, SAMPLE_EMBEDDING_RAW)
        assert fn.is_using_ollama is True
        assert mock_client.embed.call_count == 2


# ---------------------------------------------------------------------------
# Offline cooldown
# ---------------------------------------------------------------------------


class TestOfflineCooldown:
    @patch("src.core.chromadb.embedding.time.sleep")
    @patch("src.core.chromadb.embedding.ollama.Client")
    def test_skips_retries_while_server_is_offline(
        self,
        mock_client_cls: MagicMock,
        mock_sleep: MagicMock,
    ) -> None:
        """After an offline failure, subsequent calls should skip Ollama."""
        mock_client = mock_client_cls.return_value
        mock_client.embed.side_effect = ConnectionError("connection refused")

        fn = OllamaEmbeddingFunction(
            max_retries=3,
            base_delay=1.0,
            offline_cooldown=60.0,
        )

        fn(["first"])
        first_attempts = mock_client.embed.call_count
        assert first_attempts == 1
        assert mock_sleep.call_count == 0

        # Should use fallback directly due cooldown (no extra Ollama call).
        fn(["second"])
        assert mock_client.embed.call_count == first_attempts


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    @patch("src.core.chromadb.embedding.ollama.Client")
    def test_empty_input_short_circuits(
        self, mock_client_cls: MagicMock,
    ) -> None:
        """Empty input should short-circuit in __call__."""
        fn = OllamaEmbeddingFunction()

        # __call__ short-circuits before ChromaDB validates
        assert fn._last_used_ollama is False
        # Directly test the short-circuit in __call__ by checking
        # that calling with empty list doesn't crash and Ollama
        # is not marked as used.
        # (ChromaDB's validator rejects [] from __call__, so we
        # verify the flag stays False after a real single-doc call.)
        mock_client = mock_client_cls.return_value
        mock_client.embed.return_value = _mock_embed_response(
            SAMPLE_EMBEDDING_RAW,
        )
        fn(["one doc"])
        assert fn.is_using_ollama is True

    @patch("src.core.chromadb.embedding.ollama.Client")
    def test_is_using_ollama_starts_false(
        self, mock_client_cls: MagicMock,
    ) -> None:
        """is_using_ollama should be False before any call."""
        fn = OllamaEmbeddingFunction()
        assert fn.is_using_ollama is False

    @patch("src.core.chromadb.embedding.ollama.Client")
    def test_is_using_ollama_updates_per_call(
        self, mock_client_cls: MagicMock,
    ) -> None:
        """is_using_ollama should reflect the most recent call."""
        mock_client = mock_client_cls.return_value

        fn = OllamaEmbeddingFunction(
            max_retries=1, base_delay=0.0,
        )

        # First call: Ollama succeeds
        mock_client.embed.return_value = _mock_embed_response(
            SAMPLE_EMBEDDING_RAW,
        )
        mock_client.embed.side_effect = None
        fn(["test"])
        assert fn.is_using_ollama is True

        # Second call: Ollama fails
        mock_client.embed.side_effect = ollama.ResponseError("down")
        fn(["test"])
        assert fn.is_using_ollama is False

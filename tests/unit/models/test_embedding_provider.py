"""Tests for :mod:`src.models.embedding_provider`.

Mocked Ollama / OpenAI clients so the suite runs without a server.

sensitivity_tier: N/A
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock, patch

import ollama
import pytest
from src.models.embedding_provider import (
    DEFAULT_OLLAMA_MODEL,
    DEFAULT_OPENAI_MODEL,
    EmbeddingUnavailableError,
    OllamaEmbeddingProvider,
    OpenAIEmbeddingProvider,
    VoyageEmbeddingProvider,
    create_embedding_provider_from_settings,
)

# ---------------------------------------------------------------------------
# OllamaEmbeddingProvider
# ---------------------------------------------------------------------------


class TestOllamaProvider:
    @patch("src.models.embedding_provider.ollama.Client")
    def test_embed_documents_returns_vectors(
        self, mock_client_cls: MagicMock,
    ) -> None:
        client = mock_client_cls.return_value
        client.embed.return_value = {
            "embeddings": [[0.1] * 768, [0.2] * 768],
        }
        p = OllamaEmbeddingProvider()
        vecs = p.embed_documents(["a", "b"])
        assert len(vecs) == 2
        assert len(vecs[0]) == 768
        client.embed.assert_called_once_with(
            model=DEFAULT_OLLAMA_MODEL, input=["a", "b"],
        )

    @patch("src.models.embedding_provider.ollama.Client")
    def test_embed_query_returns_single_vector(
        self, mock_client_cls: MagicMock,
    ) -> None:
        client = mock_client_cls.return_value
        client.embed.return_value = {"embeddings": [[0.1] * 768]}
        p = OllamaEmbeddingProvider()
        vec = p.embed_query("hello")
        assert len(vec) == 768

    @patch("src.models.embedding_provider.ollama.Client")
    def test_empty_input_returns_empty(
        self, mock_client_cls: MagicMock,
    ) -> None:
        client = mock_client_cls.return_value
        p = OllamaEmbeddingProvider()
        assert p.embed_documents([]) == []
        client.embed.assert_not_called()

    @patch("src.models.embedding_provider.ollama.Client")
    def test_unreachable_raises_after_one_attempt(
        self, mock_client_cls: MagicMock,
    ) -> None:
        client = mock_client_cls.return_value
        client.embed.side_effect = ollama.RequestError(
            "failed to connect",
        )
        p = OllamaEmbeddingProvider()
        with pytest.raises(EmbeddingUnavailableError):
            p.embed_documents(["x"])
        # unreachable shortcuts the retry loop
        assert client.embed.call_count == 1

    @patch("src.models.embedding_provider.ollama.Client")
    def test_offline_cooldown_blocks_subsequent_calls(
        self, mock_client_cls: MagicMock,
    ) -> None:
        client = mock_client_cls.return_value
        client.embed.side_effect = ollama.RequestError(
            "connection refused",
        )
        p = OllamaEmbeddingProvider()
        with pytest.raises(EmbeddingUnavailableError):
            p.embed_documents(["x"])
        # Second call within cooldown raises without re-hitting Ollama
        with pytest.raises(EmbeddingUnavailableError):
            p.embed_documents(["y"])
        # client.embed only called for the first attempt
        assert client.embed.call_count == 1

    @patch("src.models.embedding_provider.ollama.Client")
    def test_dimension_property_uses_known_model_map(
        self, _mock: MagicMock,
    ) -> None:
        p = OllamaEmbeddingProvider(model="bge-m3")
        assert p.dimension == 1024

    @patch("src.models.embedding_provider.ollama.Client")
    def test_dimension_property_probes_unknown_model(
        self, mock_client_cls: MagicMock,
    ) -> None:
        client = mock_client_cls.return_value
        client.embed.return_value = {"embeddings": [[0.5] * 512]}
        p = OllamaEmbeddingProvider(model="some-unknown-model")
        assert p.dimension == 512

    @patch("src.models.embedding_provider.ollama.Client")
    def test_provider_metadata(self, _mock: MagicMock) -> None:
        p = OllamaEmbeddingProvider(model="bge-m3")
        assert p.provider_name == "ollama"
        assert p.model_name == "bge-m3"


# ---------------------------------------------------------------------------
# OpenAIEmbeddingProvider
# ---------------------------------------------------------------------------


class _FakeOpenAIData:
    def __init__(self, embedding: list[float]) -> None:
        self.embedding = embedding


class _FakeOpenAIResponse:
    def __init__(self, vectors: list[list[float]]) -> None:
        self.data = [_FakeOpenAIData(v) for v in vectors]


class TestOpenAIProvider:
    def _build(
        self,
        vectors: list[list[float]],
        **kwargs: Any,
    ) -> tuple[OpenAIEmbeddingProvider, MagicMock]:
        fake_openai = MagicMock()
        fake_client = MagicMock()
        fake_client.embeddings.create.return_value = (
            _FakeOpenAIResponse(vectors)
        )
        fake_openai.OpenAI.return_value = fake_client
        with patch.dict(
            "sys.modules", {"openai": fake_openai},
        ):
            p = OpenAIEmbeddingProvider(api_key="sk-test", **kwargs)
        return p, fake_client

    def test_missing_sdk_raises_unavailable(self) -> None:
        with patch.dict(
            "sys.modules",
            {"openai": None},
        ), pytest.raises(EmbeddingUnavailableError):
            OpenAIEmbeddingProvider(api_key="sk-test")

    def test_embed_documents_passes_dimensions(self) -> None:
        p, client = self._build(
            [[0.1] * 1024], dimensions=1024,
        )
        out = p.embed_documents(["a"])
        assert len(out[0]) == 1024
        client.embeddings.create.assert_called_once_with(
            model=DEFAULT_OPENAI_MODEL,
            input=["a"],
            dimensions=1024,
        )

    def test_embed_query_returns_first_vector(self) -> None:
        p, _ = self._build([[0.42] * 3072])
        v = p.embed_query("q")
        assert len(v) == 3072

    def test_failure_wraps_in_unavailable(self) -> None:
        p, client = self._build([[0.0]])
        client.embeddings.create.side_effect = RuntimeError("oops")
        with pytest.raises(EmbeddingUnavailableError):
            p.embed_documents(["x"])

    def test_provider_metadata(self) -> None:
        p, _ = self._build([[0.0]])
        assert p.provider_name == "openai"
        assert p.model_name == DEFAULT_OPENAI_MODEL

    def test_redacts_inputs_before_remote_call(self, tmp_path: Any) -> None:
        """Names + emails are redacted before the API sees them."""
        from src.models.redaction_registry import (
            reset_redaction_registry_for_tests,
        )
        reset_redaction_registry_for_tests(
            path=tmp_path / "redaction.sqlite",
        )
        p, client = self._build([[0.0] * 8])
        p.embed_documents([
            "Alice ate lunch at noon",
            "Email her at alice@example.com",
        ])
        sent = client.embeddings.create.call_args.kwargs["input"]
        assert all("Alice" not in t for t in sent)
        assert all("alice@example.com" not in t for t in sent)
        assert any("__PERSON" in t for t in sent)
        assert any("__EMAIL" in t for t in sent)

    def test_chunks_large_batches_to_provider_limit(self, tmp_path: Any) -> None:
        """Batches above the chunk size split into multiple API calls.

        Regression: many providers cap ``/embeddings`` at 1024 inputs
        and return HTTP 422 above that. Without chunking, a full reindex
        of a 2k+ doc corpus failed; the ChromaDB adapter then silently
        fell back to ``all-MiniLM-L6-v2`` and corrupted the index.
        """
        from src.models.redaction_registry import (
            reset_redaction_registry_for_tests,
        )
        reset_redaction_registry_for_tests(
            path=tmp_path / "redaction.sqlite",
        )

        call_inputs: list[list[str]] = []

        def fake_create(**kwargs):
            call_inputs.append(list(kwargs["input"]))
            return _FakeOpenAIResponse(
                [[0.0] * 4] * len(kwargs["input"]),
            )

        fake_openai = MagicMock()
        fake_client = MagicMock()
        fake_client.embeddings.create.side_effect = fake_create
        fake_openai.OpenAI.return_value = fake_client
        with patch.dict("sys.modules", {"openai": fake_openai}):
            p = OpenAIEmbeddingProvider(
                api_key="sk-test", batch_chunk=128,
            )

        texts = [f"doc {i}" for i in range(300)]
        out = p.embed_documents(texts)
        assert len(out) == 300
        # 300 items / 128 per chunk → 3 calls (128, 128, 44).
        assert [len(b) for b in call_inputs] == [128, 128, 44]

    def test_chunk_failure_includes_batch_range_in_error(
        self, tmp_path: Any,
    ) -> None:
        """When one batch fails, the error names which slice — easier to debug."""
        from src.models.redaction_registry import (
            reset_redaction_registry_for_tests,
        )
        reset_redaction_registry_for_tests(
            path=tmp_path / "redaction.sqlite",
        )

        calls = {"n": 0}

        def fake_create(**kwargs):
            calls["n"] += 1
            if calls["n"] == 2:
                raise RuntimeError("422 array_above_max_length")
            return _FakeOpenAIResponse(
                [[0.0] * 4] * len(kwargs["input"]),
            )

        fake_openai = MagicMock()
        fake_client = MagicMock()
        fake_client.embeddings.create.side_effect = fake_create
        fake_openai.OpenAI.return_value = fake_client
        with patch.dict("sys.modules", {"openai": fake_openai}):
            p = OpenAIEmbeddingProvider(
                api_key="sk-test", batch_chunk=10,
            )

        with pytest.raises(EmbeddingUnavailableError) as excinfo:
            p.embed_documents([f"doc {i}" for i in range(25)])
        assert "[10:20]" in str(excinfo.value)
        assert "of 25" in str(excinfo.value)

    def test_redaction_opt_out_passes_raw(self, tmp_path: Any) -> None:
        """``redact=False`` skips the redactor (for already-redacted callers)."""
        from src.models.redaction_registry import (
            reset_redaction_registry_for_tests,
        )
        reset_redaction_registry_for_tests(
            path=tmp_path / "redaction.sqlite",
        )
        p, client = self._build([[0.0]], redact=False)
        p.embed_documents(["Alice ate lunch"])
        sent = client.embeddings.create.call_args.kwargs["input"]
        assert sent == ["Alice ate lunch"]


# ---------------------------------------------------------------------------
# Voyage stub
# ---------------------------------------------------------------------------


class TestVoyageStub:
    def test_init_raises_not_implemented(self) -> None:
        with pytest.raises(NotImplementedError):
            VoyageEmbeddingProvider()


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def _write_settings(tmp_path: Any, body: dict[str, Any]) -> Any:
    """Write a fake settings.json and patch SETTINGS_PATH to point at it.

    sensitivity_tier: N/A
    """
    p = tmp_path / "settings.json"
    p.write_text(json.dumps(body), encoding="utf-8")
    return p


class TestFactory:
    @patch("src.models.embedding_provider.ollama.Client")
    def test_no_settings_defaults_to_ollama(
        self, _mock: MagicMock, tmp_path: Any,
    ) -> None:
        p = _write_settings(tmp_path, {})
        with patch(
            "src.models.embedding_provider.SETTINGS_PATH", p,
        ):
            provider = create_embedding_provider_from_settings()
        assert provider.provider_name == "ollama"
        assert provider.model_name == DEFAULT_OLLAMA_MODEL

    @patch("src.models.embedding_provider.ollama.Client")
    def test_chat_ollama_picks_ollama_embedder(
        self, _mock: MagicMock, tmp_path: Any,
    ) -> None:
        p = _write_settings(tmp_path, {"llm_provider": "ollama"})
        with patch(
            "src.models.embedding_provider.SETTINGS_PATH", p,
        ):
            provider = create_embedding_provider_from_settings()
        assert provider.provider_name == "ollama"

    @patch("src.models.embedding_provider.ollama.Client")
    def test_chat_remote_with_mirror_disabled_picks_ollama(
        self, _mock: MagicMock, tmp_path: Any,
    ) -> None:
        p = _write_settings(
            tmp_path,
            {
                "llm_provider": "openai_compat",
                "embedding_remote_when_chat_remote": False,
            },
        )
        with patch(
            "src.models.embedding_provider.SETTINGS_PATH", p,
        ):
            provider = create_embedding_provider_from_settings()
        assert provider.provider_name == "ollama"

    @patch("src.models.embedding_provider.ollama.Client")
    def test_chat_remote_without_api_key_falls_back_to_ollama(
        self, _mock: MagicMock, tmp_path: Any,
    ) -> None:
        p = _write_settings(
            tmp_path, {"llm_provider": "openai_compat"},
        )
        with patch(
            "src.models.embedding_provider.SETTINGS_PATH", p,
        ):
            provider = create_embedding_provider_from_settings()
        # No API key in settings → falls back to ollama
        assert provider.provider_name == "ollama"

    @patch("src.models.embedding_provider.ollama.Client")
    def test_explicit_ollama_override_wins(
        self, _mock: MagicMock, tmp_path: Any,
    ) -> None:
        p = _write_settings(
            tmp_path,
            {
                "llm_provider": "openai_compat",
                "llm_api_key": "sk-key",
                "embedding_provider": "ollama",
                "embedding_model_local": "bge-m3",
            },
        )
        with patch(
            "src.models.embedding_provider.SETTINGS_PATH", p,
        ):
            provider = create_embedding_provider_from_settings()
        assert provider.provider_name == "ollama"
        assert provider.model_name == "bge-m3"

    def test_chat_remote_with_api_key_picks_openai(
        self, tmp_path: Any,
    ) -> None:
        p = _write_settings(
            tmp_path,
            {
                "llm_provider": "openai_compat",
                "llm_api_key": "sk-key",
            },
        )
        fake_openai = MagicMock()
        fake_openai.OpenAI.return_value = MagicMock()
        with patch.dict("sys.modules", {"openai": fake_openai}), patch(
            "src.models.embedding_provider.SETTINGS_PATH", p,
        ):
            provider = create_embedding_provider_from_settings()
        assert provider.provider_name == "openai"
        assert provider.model_name == DEFAULT_OPENAI_MODEL

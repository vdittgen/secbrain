"""Unit tests for the local LLM provider abstraction.

Tests cover OllamaProvider and the factory function. All tests mock
external dependencies so no running servers are required.
"""

from __future__ import annotations

import sys
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest
from src.models.llm_provider import (
    LLMResponse,
    _create_ollama_provider,
    create_provider_from_settings,
    load_llm_settings,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_ollama_response(content: str) -> MagicMock:
    """Build a mock Ollama chat response."""
    resp = MagicMock()
    resp.message.content = content
    return resp


# ---------------------------------------------------------------------------
# LLMResponse
# ---------------------------------------------------------------------------


class TestLLMResponse:
    def test_frozen_dataclass(self) -> None:
        resp = LLMResponse(content="hello", model="test")
        assert resp.content == "hello"
        assert resp.model == "test"
        with pytest.raises(AttributeError):
            resp.content = "changed"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# OllamaProvider
# ---------------------------------------------------------------------------


@contextmanager
def _noop_lock(**_kwargs: object):  # noqa: ANN204
    """No-op context manager replacing ``ollama_lock`` in tests."""
    yield


class TestOllamaProvider:
    @pytest.fixture(autouse=True)
    def _mock_lock(self) -> None:  # noqa: ANN204
        """Replace ollama_lock with a no-op so tests don't block."""
        with patch(
            "src.models.ollama_lock.ollama_lock", _noop_lock,
        ):
            yield

    def _make_provider(
        self,
        mock_client: MagicMock,
        model: str = "test:latest",
        max_retries: int = 3,
        base_delay: float = 0.01,
    ) -> object:
        """Create an OllamaProvider with a mocked client."""
        mock_ollama = MagicMock()
        mock_ollama.Client.return_value = mock_client
        with patch.dict(sys.modules, {"ollama": mock_ollama}):
            from src.models.llm_provider import OllamaProvider

            provider = OllamaProvider(
                model=model,
                max_retries=max_retries,
                base_delay=base_delay,
            )
        # Stub out preemption and lock so tests don't depend on
        # signal files or the real Ollama lock.
        provider._preempt_guard = lambda: None  # noqa: SLF001
        provider._interactive_cleanup = lambda: None  # noqa: SLF001
        return provider

    def test_chat_returns_response(self) -> None:
        mock_client = MagicMock()
        mock_client.chat.return_value = _mock_ollama_response("Hi there")
        provider = self._make_provider(mock_client)

        result = provider.chat([{"role": "user", "content": "hello"}])

        assert isinstance(result, LLMResponse)
        assert result.content == "Hi there"
        assert result.model == "test:latest"

    def test_chat_with_model_override(self) -> None:
        mock_client = MagicMock()
        mock_client.chat.return_value = _mock_ollama_response("ok")
        provider = self._make_provider(mock_client, model="default:7b")

        provider.chat(
            [{"role": "user", "content": "hi"}],
            model="other:13b",
        )

        call_args = mock_client.chat.call_args
        assert call_args.kwargs["model"] == "other:13b"

    def test_chat_retry_on_failure(self) -> None:
        mock_client = MagicMock()
        mock_client.chat.side_effect = [
            Exception("connection error"),
            _mock_ollama_response("recovered"),
        ]
        provider = self._make_provider(
            mock_client, max_retries=2, base_delay=0.01,
        )

        result = provider.chat([{"role": "user", "content": "hello"}])
        assert result.content == "recovered"

    def test_chat_returns_empty_on_exhausted_retries(self) -> None:
        mock_client = MagicMock()
        mock_client.chat.side_effect = Exception("always fails")
        provider = self._make_provider(
            mock_client, max_retries=2, base_delay=0.01,
        )

        result = provider.chat([{"role": "user", "content": "hello"}])
        assert result.content == ""

    def test_chat_json_returns_dict(self) -> None:
        mock_client = MagicMock()
        mock_client.chat.return_value = _mock_ollama_response(
            '{"key": "value"}',
        )
        provider = self._make_provider(mock_client)

        result = provider.chat_json(
            [{"role": "user", "content": "respond as json"}],
        )

        assert result == {"key": "value"}
        call_args = mock_client.chat.call_args
        # format="json" sent via Ollama native JSON constraint.
        assert call_args.kwargs["format"] == "json"

    def test_chat_json_returns_empty_on_bad_json(self) -> None:
        mock_client = MagicMock()
        mock_client.chat.return_value = _mock_ollama_response(
            "not json at all",
        )
        provider = self._make_provider(
            mock_client, max_retries=1,
        )

        result = provider.chat_json(
            [{"role": "user", "content": "respond"}],
        )
        assert result == {}

    def test_provider_name_and_model(self) -> None:
        provider = self._make_provider(MagicMock(), model="llama3.1:8b")
        assert provider.provider_name == "ollama"
        assert provider.default_model == "llama3.1:8b"

    def test_check_health_reachable(self) -> None:
        mock_client = MagicMock()
        model_info = MagicMock()
        model_info.model = "llama3.1:8b"
        model_list = MagicMock()
        model_list.models = [model_info]
        mock_client.list.return_value = model_list

        provider = self._make_provider(
            mock_client, model="llama3.1:8b",
        )
        health = provider.check_health()

        assert health["server_reachable"] is True
        assert health["chat_model_status"] == "available"

    def test_check_health_unreachable(self) -> None:
        mock_client = MagicMock()
        mock_client.list.side_effect = Exception("connection refused")

        provider = self._make_provider(
            mock_client, model="llama3.1:8b",
        )
        health = provider.check_health()

        assert health["server_reachable"] is False


class TestFactory:
    def test_defaults_to_ollama(self) -> None:
        with patch(
            "src.models.llm_provider.SETTINGS_PATH",
        ) as mock_path:
            mock_path.exists.return_value = False
            mock_ollama = MagicMock()
            with patch.dict(sys.modules, {"ollama": mock_ollama}):
                provider = create_provider_from_settings()
            assert provider.provider_name == "ollama"

    def test_non_ollama_setting_still_yields_ollama(self) -> None:
        # SecBrain is Ollama-only: any llm_provider value resolves
        # to the local Ollama provider.
        settings = {"llm_provider": "anthropic"}
        with (
            patch(
                "src.models.llm_provider.load_llm_settings",
                return_value=settings,
            ),
            patch.dict(sys.modules, {"ollama": MagicMock()}),
        ):
            provider = create_provider_from_settings()
            assert provider.provider_name == "ollama"

    def test_create_ollama_provider_uses_settings(self) -> None:
        settings = {
            "llm_host": "http://localhost:9999",
            "llm_model": "mistral:7b",
        }
        mock_ollama = MagicMock()
        with patch.dict(sys.modules, {"ollama": mock_ollama}):
            provider = _create_ollama_provider(settings)
        assert provider.default_model == "mistral:7b"

    def test_load_llm_settings_missing_file(self) -> None:
        with patch(
            "src.models.llm_provider.SETTINGS_PATH",
        ) as mock_path:
            mock_path.exists.return_value = False
            result = load_llm_settings()
            assert result == {}


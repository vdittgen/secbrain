"""Unit tests for OllamaManager.

All tests mock the Ollama client so no running Ollama instance is required.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from src.models.ollama_manager import (
    ModelStatus,
    OllamaManager,
)


def _make_model_entry(name: str) -> MagicMock:
    """Create a mock model list entry."""
    entry = MagicMock()
    entry.model = name
    return entry


def _make_model_list(names: list[str]) -> MagicMock:
    """Create a mock client.list() response."""
    result = MagicMock()
    result.models = [_make_model_entry(n) for n in names]
    return result


class TestCheckHealth:
    @patch("src.models.ollama_manager.ollama.Client")
    def test_server_reachable_with_models(
        self,
        mock_cls: MagicMock,
    ) -> None:
        """Server up with matching models → AVAILABLE."""
        client = mock_cls.return_value
        client.list.return_value = _make_model_list(
            ["llama3.3:70b", "nomic-embed-text"],
        )
        mgr = OllamaManager()
        status = mgr.check_health()

        assert status.server_reachable is True
        assert status.chat_model_status == ModelStatus.AVAILABLE
        assert status.embed_model_status == ModelStatus.AVAILABLE

    @patch("src.models.ollama_manager.ollama.Client")
    def test_server_offline(
        self,
        mock_cls: MagicMock,
    ) -> None:
        """Server unreachable → OFFLINE for all models."""
        client = mock_cls.return_value
        client.list.side_effect = ConnectionError("refused")
        mgr = OllamaManager()
        status = mgr.check_health()

        assert status.server_reachable is False
        assert status.chat_model_status == ModelStatus.OFFLINE
        assert status.embed_model_status == ModelStatus.OFFLINE

    @patch("src.models.ollama_manager.ollama.Client")
    def test_model_not_found(
        self,
        mock_cls: MagicMock,
    ) -> None:
        """Server up but model not pulled → NOT_FOUND."""
        client = mock_cls.return_value
        client.list.return_value = _make_model_list(["mistral:7b"])
        mgr = OllamaManager()
        status = mgr.check_health()

        assert status.server_reachable is True
        assert status.chat_model_status == ModelStatus.NOT_FOUND

    @patch("src.models.ollama_manager.ollama.Client")
    def test_partial_match_by_base_name(
        self,
        mock_cls: MagicMock,
    ) -> None:
        """Model with different tag but same base → AVAILABLE."""
        client = mock_cls.return_value
        client.list.return_value = _make_model_list(
            ["llama3.3:latest"],
        )
        mgr = OllamaManager()
        status = mgr.check_health()

        assert status.chat_model_status == ModelStatus.AVAILABLE


class TestPreloadModel:
    @patch("src.models.ollama_manager.ollama.Client")
    def test_preload_success(
        self,
        mock_cls: MagicMock,
    ) -> None:
        """Successful preload returns True."""
        client = mock_cls.return_value
        client.chat.return_value = MagicMock()
        mgr = OllamaManager()

        assert mgr.preload_model() is True
        client.chat.assert_called_once()
        call_kwargs = client.chat.call_args
        assert call_kwargs.kwargs["keep_alive"] == "10m"

    @patch("src.models.ollama_manager.ollama.Client")
    def test_preload_failure(
        self,
        mock_cls: MagicMock,
    ) -> None:
        """Failed preload returns False."""
        client = mock_cls.return_value
        client.chat.side_effect = ConnectionError("refused")
        mgr = OllamaManager()

        assert mgr.preload_model() is False


class TestGetStatusDict:
    @patch("src.models.ollama_manager.ollama.Client")
    def test_returns_serializable_dict(
        self,
        mock_cls: MagicMock,
    ) -> None:
        """get_status_dict returns JSON-safe string values."""
        client = mock_cls.return_value
        client.list.return_value = _make_model_list(
            ["llama3.1:8b"],
        )
        mgr = OllamaManager()
        d = mgr.get_status_dict()

        assert isinstance(d["server_reachable"], bool)
        assert isinstance(d["chat_model_status"], str)
        assert d["chat_model_status"] in (
            "unknown",
            "offline",
            "not_found",
            "available",
        )

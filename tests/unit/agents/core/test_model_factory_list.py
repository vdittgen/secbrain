"""Tests for ``list_models()`` — chat-first sorting + endpoint resolution.

sensitivity_tier: N/A
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest
from src.agents.core import model_factory
from src.agents.core.model_factory import (
    ModelEndpoint,
    _chat_rank,
    list_models,
)


@dataclass
class _FakeModel:
    id: str


@dataclass
class _FakeList:
    data: list[_FakeModel]


def _install_fake_openai(monkeypatch: pytest.MonkeyPatch, ids: list[str]) -> dict:
    captured: dict[str, Any] = {}

    class _FakeModels:
        def list(self) -> _FakeList:
            captured["list_called"] = True
            return _FakeList([_FakeModel(i) for i in ids])

    class _FakeClient:
        def __init__(self, *, base_url: str, api_key: str) -> None:
            captured["base_url"] = base_url
            captured["api_key"] = api_key
            self.models = _FakeModels()

    import sys
    import types
    fake_openai = types.ModuleType("openai")
    fake_openai.OpenAI = _FakeClient  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "openai", fake_openai)
    return captured


def _install_endpoints(
    monkeypatch: pytest.MonkeyPatch,
    *,
    remote_base: str = "https://api.deepinfra.com/v1/openai",
    local_base: str = "http://localhost:11434/v1",
) -> None:
    monkeypatch.setattr(
        model_factory, "remote_endpoint",
        lambda: ModelEndpoint(
            route="remote",
            base_url=remote_base,
            model_name="default",
            api_key="rkey",
        ),
    )
    monkeypatch.setattr(
        model_factory, "local_endpoint",
        lambda: ModelEndpoint(
            route="local",
            base_url=local_base,
            model_name="default",
            api_key="lkey",
        ),
    )


# ---------------------------- _chat_rank -----------------------------------


def test_chat_rank_recognizes_deepseek() -> None:
    assert _chat_rank("deepseek-ai/DeepSeek-V3.1") == 0


def test_chat_rank_recognizes_qwen() -> None:
    assert _chat_rank("Qwen/Qwen3.6-35B-A3B") == 0


def test_chat_rank_recognizes_meta_llama() -> None:
    assert _chat_rank("meta-llama/Llama-3.1-70B-Instruct") == 0


def test_chat_rank_demotes_image_models() -> None:
    assert _chat_rank("black-forest-labs/FLUX-2-klein-9b") == 2


def test_chat_rank_demotes_audio_models() -> None:
    assert _chat_rank("openai/whisper-large-v3") == 2


def test_chat_rank_demotes_embedding_models_even_with_chat_prefix() -> None:
    # Qwen/* is a chat prefix, but the id says it's an embedding model
    assert _chat_rank("Qwen/Qwen3-Embedding-8B") == 2


def test_chat_rank_demotes_image_models_even_with_chat_prefix() -> None:
    assert _chat_rank("Qwen/Qwen-Image-Edit") == 2


def test_chat_rank_unknown_prefix_gets_middle_bucket() -> None:
    assert _chat_rank("vendor/some-new-chat-model") == 1


# ---------------------------- list_models ----------------------------------


def test_list_models_returns_sorted_chat_first(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_endpoints(monkeypatch)
    _install_fake_openai(
        monkeypatch,
        [
            "black-forest-labs/FLUX-2-klein-9b",
            "deepseek-ai/DeepSeek-V3.1",
            "Qwen/Qwen3.6-35B-A3B",
            "openai/whisper-large-v3",
            "meta-llama/Llama-3.1-70B-Instruct",
        ],
    )
    result = list_models("remote")
    # Chat-likely first (alphabetic within group), then everything else
    assert result == [
        "Qwen/Qwen3.6-35B-A3B",
        "deepseek-ai/DeepSeek-V3.1",
        "meta-llama/Llama-3.1-70B-Instruct",
        "black-forest-labs/FLUX-2-klein-9b",
        "openai/whisper-large-v3",
    ]


def test_list_models_uses_remote_endpoint_by_default_for_inherit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_endpoints(monkeypatch)
    captured = _install_fake_openai(monkeypatch, ["x/y"])
    list_models("inherit")
    assert captured["base_url"] == "https://api.deepinfra.com/v1/openai"


def test_list_models_uses_local_endpoint_for_local_route(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_endpoints(monkeypatch)
    captured = _install_fake_openai(monkeypatch, ["x/y"])
    list_models("local")
    assert captured["base_url"] == "http://localhost:11434/v1"


def test_list_models_rejects_unknown_route(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_endpoints(monkeypatch)
    with pytest.raises(ValueError, match="Unknown route"):
        list_models("bogus")


def test_list_models_wraps_sdk_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_endpoints(monkeypatch)

    class _FailingModels:
        def list(self) -> _FakeList:
            raise RuntimeError("network down")

    class _FailingClient:
        def __init__(self, **_kw: Any) -> None:
            self.models = _FailingModels()

    import sys
    import types
    fake_openai = types.ModuleType("openai")
    fake_openai.OpenAI = _FailingClient  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "openai", fake_openai)

    with pytest.raises(RuntimeError, match="failed to list models"):
        list_models("remote")


def test_list_models_skips_entries_without_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_endpoints(monkeypatch)

    @dataclass
    class _Bad:
        # No id attribute / id=None
        pass

    class _Models:
        def list(self) -> _FakeList:
            return _FakeList(
                [_FakeModel("deepseek-ai/x"), _Bad()],  # type: ignore[list-item]
            )

    class _Client:
        def __init__(self, **_kw: Any) -> None:
            self.models = _Models()

    import sys
    import types
    fake_openai = types.ModuleType("openai")
    fake_openai.OpenAI = _Client  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "openai", fake_openai)

    assert list_models("remote") == ["deepseek-ai/x"]

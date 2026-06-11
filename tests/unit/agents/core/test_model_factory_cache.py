"""ModelFactory caching — endpoint-aware rebuild semantics.

A long-lived process must not keep using a model built around
credentials or settings that have since changed (e.g. a bearer token
with an hourly expiry): the cache is keyed on the RESOLVED endpoint,
not just (route, override).

sensitivity_tier: N/A
"""

from __future__ import annotations

import pytest
from src.agents.core import model_factory
from src.agents.core.model_factory import ModelEndpoint, ModelFactory


@pytest.fixture()
def factory(monkeypatch: pytest.MonkeyPatch) -> ModelFactory:
    built: list[ModelEndpoint] = []

    def fake_build(endpoint: ModelEndpoint) -> object:
        built.append(endpoint)
        return object()

    monkeypatch.setattr(
        model_factory, "_build_pydantic_ai_model", fake_build,
    )
    f = ModelFactory()
    f._built = built  # type: ignore[attr-defined] — test hook
    return f


def _endpoint(api_key: str) -> ModelEndpoint:
    return ModelEndpoint(
        route="local",
        base_url="http://localhost:11434/v1",
        model_name="llama3.1:70b",
        api_key=api_key,
    )


def test_get_reuses_model_while_endpoint_unchanged(
    factory: ModelFactory, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        factory, "endpoint_for", lambda route, model_override=None: _endpoint("k1"),
    )
    first = factory.get("local")
    second = factory.get("local")
    assert first is second
    assert len(factory._built) == 1  # type: ignore[attr-defined]


def test_get_rebuilds_when_endpoint_drifts(
    factory: ModelFactory, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Credential rotation (new api_key) must invalidate the cache —
    otherwise an expired bearer stays pinned until process restart."""
    keys = iter(["k1", "k1", "k2"])
    monkeypatch.setattr(
        factory,
        "endpoint_for",
        lambda route, model_override=None: _endpoint(next(keys)),
    )
    first = factory.get("local")
    same = factory.get("local")
    rotated = factory.get("local")
    assert first is same
    assert rotated is not first
    assert len(factory._built) == 2  # type: ignore[attr-defined]


def test_reset_drops_cache(
    factory: ModelFactory, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        factory, "endpoint_for", lambda route, model_override=None: _endpoint("k1"),
    )
    first = factory.get("local")
    factory.reset()
    rebuilt = factory.get("local")
    assert rebuilt is not first

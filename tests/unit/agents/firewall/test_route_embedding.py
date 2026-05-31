"""Tests for :meth:`EgressFirewall.route_embedding`.

sensitivity_tier: N/A
"""

from __future__ import annotations

import pytest
from src.agents.firewall.egress_firewall import (
    EgressFirewall,
    EgressPolicy,
    EmbeddingEndpoint,
    EmbeddingRequest,
)


@pytest.fixture
def remote_default_firewall() -> EgressFirewall:
    return EgressFirewall(
        policy=EgressPolicy(
            routing="remote-default", local_inference_for_sensitive=False,
        ),
    )


@pytest.fixture
def local_only_firewall() -> EgressFirewall:
    return EgressFirewall(
        policy=EgressPolicy(
            routing="local-only", local_inference_for_sensitive=True,
        ),
    )


class TestLocalOnly:
    def test_tier1_stays_local(self, local_only_firewall: EgressFirewall) -> None:
        ep = local_only_firewall.route_embedding(
            EmbeddingRequest(sensitivity_tier=1),
        )
        assert ep.provider == "local_ollama"
        assert ep.requires_redaction is False

    def test_tier3_stays_local(self, local_only_firewall: EgressFirewall) -> None:
        ep = local_only_firewall.route_embedding(
            EmbeddingRequest(sensitivity_tier=3),
        )
        assert ep.provider == "local_ollama"
        # local-only never redacts (the redactor exists to protect
        # remote egress; local stays on-device).
        assert ep.requires_redaction is False


class TestRemoteDefault:
    def test_tier1_remote_no_redaction(
        self, remote_default_firewall: EgressFirewall,
    ) -> None:
        ep = remote_default_firewall.route_embedding(
            EmbeddingRequest(sensitivity_tier=1),
        )
        assert ep.provider == "remote_openai"
        assert ep.requires_redaction is False

    def test_tier2_remote_with_redaction(
        self, remote_default_firewall: EgressFirewall,
    ) -> None:
        ep = remote_default_firewall.route_embedding(
            EmbeddingRequest(sensitivity_tier=2),
        )
        assert ep.provider == "remote_openai"
        assert ep.requires_redaction is True

    def test_tier3_remote_with_redaction(
        self, remote_default_firewall: EgressFirewall,
    ) -> None:
        ep = remote_default_firewall.route_embedding(
            EmbeddingRequest(sensitivity_tier=3),
        )
        assert ep.provider == "remote_openai"
        assert ep.requires_redaction is True


class TestEdgeCases:
    def test_tier_clamped_low(
        self, remote_default_firewall: EgressFirewall,
    ) -> None:
        # Tier 0 should clamp up to 1, not crash.
        ep = remote_default_firewall.route_embedding(
            EmbeddingRequest(sensitivity_tier=0),
        )
        assert ep.requires_redaction is False

    def test_tier_clamped_high(
        self, remote_default_firewall: EgressFirewall,
    ) -> None:
        ep = remote_default_firewall.route_embedding(
            EmbeddingRequest(sensitivity_tier=99),
        )
        assert ep.requires_redaction is True

    def test_returns_embedding_endpoint_type(
        self, remote_default_firewall: EgressFirewall,
    ) -> None:
        ep = remote_default_firewall.route_embedding(
            EmbeddingRequest(sensitivity_tier=2),
        )
        assert isinstance(ep, EmbeddingEndpoint)

    def test_is_query_flag_does_not_affect_routing(
        self, remote_default_firewall: EgressFirewall,
    ) -> None:
        doc = remote_default_firewall.route_embedding(
            EmbeddingRequest(sensitivity_tier=2, is_query=False),
        )
        query = remote_default_firewall.route_embedding(
            EmbeddingRequest(sensitivity_tier=2, is_query=True),
        )
        assert doc.provider == query.provider
        assert doc.requires_redaction == query.requires_redaction

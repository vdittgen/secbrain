"""Unit tests for DataLayer lazy initialization.

Verifies that engines are NOT created during __init__ and are only
instantiated on first property access.  Also tests the warmup() and
close() methods with partially-initialized state.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from src.core.data_layer import DataLayer


@pytest.fixture()
def layer(tmp_path: Path) -> DataLayer:
    """Return a DataLayer backed by a temp directory."""
    return DataLayer(base_path=tmp_path / "sb_data")


# -----------------------------------------------------------------
# Lazy init
# -----------------------------------------------------------------


class TestLazyInit:
    def test_init_does_not_create_engines(
        self, layer: DataLayer
    ) -> None:
        assert layer._duck is None
        assert layer._kuzu is None
        assert layer._chroma is None
        assert layer._indexer is None

    def test_duckdb_creates_only_duckdb(
        self, layer: DataLayer
    ) -> None:
        _ = layer.duckdb
        assert layer._duck is not None
        assert layer._kuzu is None
        assert layer._chroma is None

    def test_kuzu_creates_only_kuzu(
        self, layer: DataLayer
    ) -> None:
        _ = layer.kuzu
        assert layer._duck is None
        assert layer._kuzu is not None
        assert layer._chroma is None

    def test_chromadb_creates_only_chromadb(
        self, layer: DataLayer
    ) -> None:
        _ = layer.chromadb
        assert layer._duck is None
        assert layer._kuzu is None
        assert layer._chroma is not None

    def test_indexer_creates_duckdb_and_chromadb(
        self, layer: DataLayer
    ) -> None:
        _ = layer.indexer
        assert layer._duck is not None
        assert layer._chroma is not None
        assert layer._kuzu is None
        assert layer._indexer is not None


# -----------------------------------------------------------------
# Warmup
# -----------------------------------------------------------------


class TestWarmup:
    def test_warmup_creates_all_engines(
        self, layer: DataLayer
    ) -> None:
        layer.warmup()
        assert layer._duck is not None
        assert layer._kuzu is not None
        assert layer._chroma is not None
        assert layer._indexer is not None

    def test_warmup_is_idempotent(
        self, layer: DataLayer
    ) -> None:
        layer.warmup()
        duck = layer._duck
        kuzu = layer._kuzu
        chroma = layer._chroma

        layer.warmup()
        assert layer._duck is duck
        assert layer._kuzu is kuzu
        assert layer._chroma is chroma


# -----------------------------------------------------------------
# Close with partial init
# -----------------------------------------------------------------


class TestClosePartialInit:
    def test_close_no_engines(
        self, layer: DataLayer
    ) -> None:
        """Close with zero engines initialized — should not raise."""
        layer.close()

    def test_close_duckdb_only(
        self, layer: DataLayer
    ) -> None:
        """Close after only DuckDB was initialized."""
        _ = layer.duckdb
        layer.close()

    def test_close_all_engines(
        self, layer: DataLayer
    ) -> None:
        """Close after all engines initialized."""
        layer.warmup()
        layer.close()


# -----------------------------------------------------------------
# Property returns same instance
# -----------------------------------------------------------------


class TestPropertyIdentity:
    def test_duckdb_returns_same_instance(
        self, layer: DataLayer
    ) -> None:
        a = layer.duckdb
        b = layer.duckdb
        assert a is b

    def test_kuzu_returns_same_instance(
        self, layer: DataLayer
    ) -> None:
        a = layer.kuzu
        b = layer.kuzu
        assert a is b

    def test_chromadb_returns_same_instance(
        self, layer: DataLayer
    ) -> None:
        a = layer.chromadb
        b = layer.chromadb
        assert a is b

    def test_indexer_returns_same_instance(
        self, layer: DataLayer
    ) -> None:
        a = layer.indexer
        b = layer.indexer
        assert a is b

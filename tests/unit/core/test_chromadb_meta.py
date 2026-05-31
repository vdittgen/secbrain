"""Tests for :mod:`src.core.chromadb.meta`.

sensitivity_tier: N/A
"""

from __future__ import annotations

import json
from pathlib import Path

from src.core.chromadb.meta import (
    META_FILENAME,
    EmbeddingMeta,
    check_compatibility,
    current_meta,
    read_meta,
    write_meta,
)


def test_read_meta_returns_none_when_missing(tmp_path: Path) -> None:
    assert read_meta(tmp_path) is None


def test_write_then_read_roundtrip(tmp_path: Path) -> None:
    meta = current_meta("ollama", "nomic-embed-text", 768)
    write_meta(tmp_path, meta)
    loaded = read_meta(tmp_path)
    assert loaded is not None
    assert loaded.provider == "ollama"
    assert loaded.model_name == "nomic-embed-text"
    assert loaded.dimension == 768
    assert loaded.created_at == meta.created_at


def test_write_meta_atomic_replace(tmp_path: Path) -> None:
    """Sentinel should be a single rename, not a partial write."""
    meta = current_meta("ollama", "bge-m3", 1024)
    write_meta(tmp_path, meta)
    assert (tmp_path / META_FILENAME).exists()
    # No leftover .tmp files.
    assert not list(tmp_path.glob(".embedding_meta.*.tmp"))


def test_read_meta_returns_none_on_malformed_json(tmp_path: Path) -> None:
    (tmp_path / META_FILENAME).write_text("{ not json", encoding="utf-8")
    assert read_meta(tmp_path) is None


def test_read_meta_returns_none_on_missing_fields(tmp_path: Path) -> None:
    (tmp_path / META_FILENAME).write_text(
        json.dumps({"provider": "ollama"}), encoding="utf-8",
    )
    assert read_meta(tmp_path) is None


def test_check_compatibility_first_run_writes_sentinel(tmp_path: Path) -> None:
    """No sentinel → returns None and writes one for next launch."""
    assert check_compatibility(tmp_path, "ollama", "nomic-embed-text", 768) is None
    stored = read_meta(tmp_path)
    assert stored is not None
    assert stored.model_name == "nomic-embed-text"


def test_check_compatibility_matching_returns_none(tmp_path: Path) -> None:
    write_meta(tmp_path, current_meta("ollama", "nomic-embed-text", 768))
    assert check_compatibility(tmp_path, "ollama", "nomic-embed-text", 768) is None


def test_check_compatibility_model_mismatch_returns_stored(tmp_path: Path) -> None:
    write_meta(tmp_path, current_meta("ollama", "nomic-embed-text", 768))
    mismatch = check_compatibility(tmp_path, "ollama", "bge-m3", 1024)
    assert isinstance(mismatch, EmbeddingMeta)
    assert mismatch.model_name == "nomic-embed-text"


def test_check_compatibility_provider_mismatch_returns_stored(
    tmp_path: Path,
) -> None:
    write_meta(tmp_path, current_meta("ollama", "nomic-embed-text", 768))
    mismatch = check_compatibility(
        tmp_path, "openai", "text-embedding-3-large", 3072,
    )
    assert isinstance(mismatch, EmbeddingMeta)
    assert mismatch.provider == "ollama"


def test_check_compatibility_dimension_mismatch_returns_stored(
    tmp_path: Path,
) -> None:
    # Same model name but different dim (shouldn't happen in practice
    # but a defensive check guards against MODEL_DIMENSIONS drift).
    write_meta(tmp_path, current_meta("ollama", "nomic-embed-text", 768))
    mismatch = check_compatibility(tmp_path, "ollama", "nomic-embed-text", 1024)
    assert isinstance(mismatch, EmbeddingMeta)
    assert mismatch.dimension == 768

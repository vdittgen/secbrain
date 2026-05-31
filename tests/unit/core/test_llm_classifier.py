"""Unit tests for LLMClassifier — the shared subjective-decision helper.

sensitivity_tier: N/A — test infrastructure
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from src.core.llm_classifier import LLMClassifier, _fingerprint
from src.core.sqlite.engine import DatabaseEngine


@pytest.fixture()
def tmp_db(tmp_path: Path) -> DatabaseEngine:
    db_path = tmp_path / "test_llm_classifier.db"
    engine = DatabaseEngine(db_path=db_path)
    yield engine
    engine.close()


def _provider(return_value: Any) -> MagicMock:
    p = MagicMock()
    p.chat_json.return_value = return_value
    return p


class TestFingerprint:
    def test_kind_and_text_both_matter(self) -> None:
        a = _fingerprint("domain", "hello")
        b = _fingerprint("pattern", "hello")
        c = _fingerprint("domain", "world")
        assert a != b
        assert a != c

    def test_stable_across_calls(self) -> None:
        assert _fingerprint("x", "y") == _fingerprint("x", "y")


class TestClassify:
    def test_returns_provider_dict(
        self, tmp_db: DatabaseEngine,
    ) -> None:
        prov = _provider({"domain": "calendar"})
        clf = LLMClassifier(prov, tmp_db)
        out = clf.classify(
            kind="domain", text="meeting tomorrow",
            schema={"domain": "<enum>"},
        )
        assert out == {"domain": "calendar"}
        assert prov.chat_json.call_count == 1

    def test_caches_subsequent_calls(
        self, tmp_db: DatabaseEngine,
    ) -> None:
        prov = _provider({"domain": "calendar"})
        clf = LLMClassifier(prov, tmp_db)
        clf.classify(
            kind="domain", text="meeting tomorrow",
            schema={"domain": "<enum>"},
        )
        # Second call should hit the cache, not the provider.
        prov.chat_json.reset_mock()
        out = clf.classify(
            kind="domain", text="meeting tomorrow",
            schema={"domain": "<enum>"},
        )
        assert out == {"domain": "calendar"}
        assert prov.chat_json.call_count == 0

    def test_different_kind_misses_cache(
        self, tmp_db: DatabaseEngine,
    ) -> None:
        prov = _provider({"verdict": "x"})
        clf = LLMClassifier(prov, tmp_db)
        clf.classify(
            kind="domain", text="same text",
            schema={"verdict": "x"},
        )
        prov.chat_json.reset_mock()
        clf.classify(
            kind="other_kind", text="same text",
            schema={"verdict": "x"},
        )
        assert prov.chat_json.call_count == 1

    def test_empty_text_returns_none(
        self, tmp_db: DatabaseEngine,
    ) -> None:
        prov = _provider({"x": 1})
        clf = LLMClassifier(prov, tmp_db)
        assert clf.classify(
            kind="domain", text="", schema={"x": "y"},
        ) is None
        prov.chat_json.assert_not_called()

    def test_llm_error_returns_none(
        self, tmp_db: DatabaseEngine,
    ) -> None:
        prov = MagicMock()
        prov.chat_json.side_effect = RuntimeError("network died")
        clf = LLMClassifier(prov, tmp_db)
        assert clf.classify(
            kind="domain", text="hi", schema={"domain": "x"},
        ) is None

    def test_non_dict_response_returns_none(
        self, tmp_db: DatabaseEngine,
    ) -> None:
        prov = _provider("not a dict")
        clf = LLMClassifier(prov, tmp_db)
        assert clf.classify(
            kind="domain", text="hi", schema={"domain": "x"},
        ) is None

    def test_no_provider_returns_none(
        self, tmp_db: DatabaseEngine,
    ) -> None:
        clf = LLMClassifier(None, tmp_db)
        assert clf.classify(
            kind="domain", text="hi", schema={"domain": "x"},
        ) is None

    def test_no_db_still_works(self) -> None:
        prov = _provider({"x": 1})
        clf = LLMClassifier(prov, db_engine=None)
        out = clf.classify(
            kind="kind", text="hi", schema={"x": "y"},
        )
        assert out == {"x": 1}

"""Unit tests for the DuckDB query cache.

Tests the QueryCache class in isolation and its integration with DatabaseEngine.
All tests use temporary databases — no real data is touched.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest
from src.core.sqlite.engine import DatabaseEngine, QueryCache

# ---------------------------------------------------------------------------
# QueryCache unit tests
# ---------------------------------------------------------------------------


class TestQueryCache:
    def test_cache_hit_returns_same_result(self) -> None:
        """Cached result should be returned on subsequent get()."""
        cache = QueryCache(maxsize=10, ttl_seconds=60.0)
        result = [{"n": 1}, {"n": 2}]
        cache.put("SELECT n FROM t", None, result)

        cached = cache.get("SELECT n FROM t", None)
        assert cached == result

    def test_cache_miss_returns_none(self) -> None:
        """get() on a missing key should return None."""
        cache = QueryCache(maxsize=10, ttl_seconds=60.0)
        assert cache.get("SELECT 1", None) is None

    def test_cache_ttl_expiry(self) -> None:
        """Entries should expire after the TTL elapses."""
        cache = QueryCache(maxsize=10, ttl_seconds=0.05)
        cache.put("SELECT 1", None, [{"x": 1}])

        assert cache.get("SELECT 1", None) is not None
        time.sleep(0.06)
        assert cache.get("SELECT 1", None) is None

    def test_cache_lru_eviction(self) -> None:
        """Oldest entry should be evicted when maxsize is exceeded."""
        cache = QueryCache(maxsize=2, ttl_seconds=60.0)
        cache.put("q1", None, [{"a": 1}])
        cache.put("q2", None, [{"b": 2}])
        cache.put("q3", None, [{"c": 3}])

        # q1 should have been evicted
        assert cache.get("q1", None) is None
        assert cache.get("q2", None) is not None
        assert cache.get("q3", None) is not None

    def test_lru_access_refreshes_position(self) -> None:
        """Accessing an entry should refresh its LRU position."""
        cache = QueryCache(maxsize=2, ttl_seconds=60.0)
        cache.put("q1", None, [{"a": 1}])
        cache.put("q2", None, [{"b": 2}])

        # Access q1 to refresh it
        cache.get("q1", None)

        # Adding q3 should evict q2 (not q1, since q1 was recently accessed)
        cache.put("q3", None, [{"c": 3}])
        assert cache.get("q1", None) is not None
        assert cache.get("q2", None) is None

    def test_invalidate_clears_all(self) -> None:
        """invalidate() should remove all entries."""
        cache = QueryCache(maxsize=10, ttl_seconds=60.0)
        cache.put("q1", None, [{"a": 1}])
        cache.put("q2", [1], [{"b": 2}])

        cache.invalidate()
        assert cache.get("q1", None) is None
        assert cache.get("q2", [1]) is None

    def test_cache_stats(self) -> None:
        """stats() should report hits, misses, and size accurately."""
        cache = QueryCache(maxsize=10, ttl_seconds=60.0)
        cache.put("q1", None, [{"a": 1}])

        cache.get("q1", None)  # hit
        cache.get("q1", None)  # hit
        cache.get("q2", None)  # miss

        stats = cache.stats()
        assert stats["hits"] == 2
        assert stats["misses"] == 1
        assert stats["size"] == 1
        assert stats["maxsize"] == 10
        assert stats["hit_rate"] == pytest.approx(2 / 3)

    def test_different_params_different_keys(self) -> None:
        """Same SQL with different params should be separate cache entries."""
        cache = QueryCache(maxsize=10, ttl_seconds=60.0)
        cache.put("SELECT * FROM t WHERE id = ?", [1], [{"id": 1}])
        cache.put("SELECT * FROM t WHERE id = ?", [2], [{"id": 2}])

        r1 = cache.get("SELECT * FROM t WHERE id = ?", [1])
        r2 = cache.get("SELECT * FROM t WHERE id = ?", [2])
        assert r1 == [{"id": 1}]
        assert r2 == [{"id": 2}]


# ---------------------------------------------------------------------------
# DatabaseEngine cache integration tests
# ---------------------------------------------------------------------------


@pytest.fixture()
def tmp_db(tmp_path: Path) -> DatabaseEngine:
    """Open a fresh DatabaseEngine backed by a temp file."""
    db_path = tmp_path / "test_cache.duckdb"
    engine = DatabaseEngine(db_path=db_path)
    yield engine
    engine.close()


class TestDatabaseEngineCache:
    def test_query_caches_result(self, tmp_db: DatabaseEngine) -> None:
        """Repeated identical queries should return cached results."""
        tmp_db.execute("CREATE TABLE nums (n INTEGER)")
        tmp_db.execute("INSERT INTO nums VALUES (1), (2)")

        r1 = tmp_db.query("SELECT n FROM nums ORDER BY n")
        r2 = tmp_db.query("SELECT n FROM nums ORDER BY n")
        assert r1 == r2

        stats = tmp_db.cache_stats()
        assert stats["hits"] >= 1

    def test_execute_invalidates_cache(self, tmp_db: DatabaseEngine) -> None:
        """execute() (DDL/DML) should clear the query cache."""
        tmp_db.execute("CREATE TABLE t (x INTEGER)")
        tmp_db.execute("INSERT INTO t VALUES (1)")
        tmp_db.query("SELECT x FROM t")

        assert tmp_db.cache_stats()["size"] == 1

        tmp_db.execute("INSERT INTO t VALUES (2)")
        assert tmp_db.cache_stats()["size"] == 0

    def test_invalidate_cache_method(self, tmp_db: DatabaseEngine) -> None:
        """invalidate_cache() should clear all cached queries."""
        tmp_db.execute("CREATE TABLE t (x INTEGER)")
        tmp_db.execute("INSERT INTO t VALUES (1)")
        tmp_db.query("SELECT x FROM t")

        tmp_db.invalidate_cache()
        assert tmp_db.cache_stats()["size"] == 0

    def test_cache_reflects_fresh_data_after_invalidation(
        self,
        tmp_db: DatabaseEngine,
    ) -> None:
        """After invalidation, query should return updated data."""
        tmp_db.execute("CREATE TABLE t (x INTEGER)")
        tmp_db.execute("INSERT INTO t VALUES (1)")

        r1 = tmp_db.query("SELECT x FROM t")
        assert r1 == [{"x": 1}]

        tmp_db.execute("INSERT INTO t VALUES (2)")
        r2 = tmp_db.query("SELECT x FROM t ORDER BY x")
        assert r2 == [{"x": 1}, {"x": 2}]

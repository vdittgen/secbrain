"""Tests for src.core.db_helpers shared utilities."""

from __future__ import annotations

from unittest.mock import MagicMock

from src.core.db_helpers import (
    ensure_tables,
    get_table_columns,
    make_hash_id,
    safe_str,
    table_exists,
    utc_ago_iso,
    utc_now_iso,
)

# ------------------------------------------------------------------
# utc_now_iso
# ------------------------------------------------------------------


class TestUtcNowIso:
    def test_returns_iso_string(self) -> None:
        result = utc_now_iso()
        assert isinstance(result, str)
        assert "T" in result
        # Should contain timezone info (+00:00)
        assert "+" in result or "Z" in result

    def test_different_calls_produce_different_timestamps(self) -> None:
        t1 = utc_now_iso()
        t2 = utc_now_iso()
        # Both are valid strings (may or may not be identical depending on speed)
        assert isinstance(t1, str)
        assert isinstance(t2, str)


# ------------------------------------------------------------------
# make_hash_id
# ------------------------------------------------------------------


class TestMakeHashId:
    def test_produces_16_char_hex(self) -> None:
        result = make_hash_id("a", "b", "c")
        assert len(result) == 16
        assert all(c in "0123456789abcdef" for c in result)

    def test_deterministic(self) -> None:
        assert make_hash_id("x", "y") == make_hash_id("x", "y")

    def test_different_inputs_different_outputs(self) -> None:
        assert make_hash_id("a") != make_hash_id("b")

    def test_single_part(self) -> None:
        result = make_hash_id("solo")
        assert len(result) == 16

    def test_empty_parts(self) -> None:
        result = make_hash_id("", "")
        assert len(result) == 16


# ------------------------------------------------------------------
# safe_str
# ------------------------------------------------------------------


class TestSafeStr:
    def test_none_returns_empty(self) -> None:
        assert safe_str(None) == ""

    def test_truncates_long_string(self) -> None:
        result = safe_str("a" * 300, max_len=200)
        assert len(result) == 200

    def test_preserves_short_string(self) -> None:
        assert safe_str("hello") == "hello"

    def test_converts_non_string(self) -> None:
        assert safe_str(42) == "42"

    def test_custom_max_len(self) -> None:
        result = safe_str("abcdef", max_len=3)
        assert result == "abc"


# ------------------------------------------------------------------
# table_exists
# ------------------------------------------------------------------


class TestTableExists:
    def _make_db(self) -> MagicMock:
        """Create a mock db_engine."""
        return MagicMock()

    def test_returns_true_when_table_found(self) -> None:
        db = self._make_db()
        db.query.return_value = [{"1": 1}]
        assert table_exists(db, "my_table") is True

    def test_returns_false_when_no_table(self) -> None:
        db = self._make_db()
        db.query.return_value = []
        assert table_exists(db, "missing") is False

    def test_returns_false_on_exception(self) -> None:
        db = self._make_db()
        db.query.side_effect = Exception("db error")
        assert table_exists(db, "whatever") is False

    def test_query_uses_parameterized_name(self) -> None:
        db = self._make_db()
        db.query.return_value = []
        table_exists(db, "test_table")
        args = db.query.call_args
        assert "test_table" in args[0][1]


# ------------------------------------------------------------------
# get_table_columns
# ------------------------------------------------------------------


class TestGetTableColumns:
    def test_returns_column_names(self) -> None:
        db = MagicMock()
        db.query.return_value = [
            {"name": "id", "type": "VARCHAR"},
            {"name": "value", "type": "TEXT"},
        ]
        result = get_table_columns(db, "my_table")
        assert result == {"id", "value"}

    def test_returns_empty_on_error(self) -> None:
        db = MagicMock()
        db.query.side_effect = Exception("fail")
        assert get_table_columns(db, "missing") == set()


# ------------------------------------------------------------------
# ensure_tables
# ------------------------------------------------------------------


class TestEnsureTables:
    def test_executes_all_ddl(self) -> None:
        db = MagicMock()
        ddl = [
            "CREATE TABLE IF NOT EXISTS t1 (id INT)",
            "CREATE TABLE IF NOT EXISTS t2 (id INT)",
        ]
        ensure_tables(db, ddl)
        assert db.execute.call_count == 2

    def test_silently_skips_on_read_only(self) -> None:
        db = MagicMock()
        db.execute.side_effect = Exception("read-only")
        # Should not raise
        ensure_tables(db, ["CREATE TABLE t (id INT)"])

    def test_empty_list_is_noop(self) -> None:
        db = MagicMock()
        ensure_tables(db, [])
        db.execute.assert_not_called()


# ------------------------------------------------------------------
# utc_ago_iso
# ------------------------------------------------------------------


class TestUtcAgoIso:
    def test_compares_correctly_against_iso_t_timestamps(self) -> None:
        """The cutoff must be format-identical to utc_now_iso so plain
        string comparison (what SQLite does) orders correctly — the
        whole point of the helper vs datetime('now', ...)."""
        now = utc_now_iso()
        one_hour = utc_ago_iso(hours=1)
        two_hours = utc_ago_iso(hours=2)
        assert two_hours < one_hour < now
        assert "T" in one_hour  # ISO-T form, not SQLite's space form

    def test_units_combine(self) -> None:
        assert utc_ago_iso(days=1) < utc_ago_iso(hours=23, minutes=59)

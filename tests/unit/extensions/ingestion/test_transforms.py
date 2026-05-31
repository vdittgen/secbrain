"""Tests for ingestion field transform functions."""

from __future__ import annotations

from src.extensions.ingestion.transforms import (
    apply_transform,
    iso_to_timestamp,
    json_array,
    json_serialize,
    lowercase,
    to_bool,
    to_float,
    to_int,
    trim,
    unix_to_timestamp,
)


class TestIsoToTimestamp:
    def test_valid_iso(self) -> None:
        assert iso_to_timestamp("2025-06-02T10:30:00") == "2025-06-02T10:30:00"

    def test_iso_with_timezone(self) -> None:
        result = iso_to_timestamp("2025-06-02T10:30:00+05:00")
        assert result == "2025-06-02T10:30:00+05:00"

    def test_iso_with_z_suffix(self) -> None:
        result = iso_to_timestamp("2025-06-02T10:30:00Z")
        assert result == "2025-06-02T10:30:00Z"

    def test_iso_space_separator(self) -> None:
        result = iso_to_timestamp("2025-06-02 10:30:00")
        assert result == "2025-06-02 10:30:00"

    def test_none_returns_none(self) -> None:
        assert iso_to_timestamp(None) is None

    def test_invalid_string_returns_none(self) -> None:
        assert iso_to_timestamp("not-a-date") is None

    def test_integer_returns_none(self) -> None:
        assert iso_to_timestamp(12345) is None


class TestUnixToTimestamp:
    def test_seconds(self) -> None:
        result = unix_to_timestamp(1717300000)
        assert result is not None
        assert "2024-06-02" in result

    def test_milliseconds(self) -> None:
        result = unix_to_timestamp(1717300000000)
        assert result is not None
        assert "2024-06-02" in result

    def test_none_returns_none(self) -> None:
        assert unix_to_timestamp(None) is None

    def test_string_number(self) -> None:
        result = unix_to_timestamp("1717300000")
        assert result is not None
        assert "2024" in result

    def test_non_numeric_returns_none(self) -> None:
        assert unix_to_timestamp("hello") is None


class TestJsonSerialize:
    def test_dict(self) -> None:
        result = json_serialize({"a": 1})
        assert result == '{"a": 1}'

    def test_list(self) -> None:
        result = json_serialize([1, 2])
        assert result == "[1, 2]"

    def test_string(self) -> None:
        result = json_serialize("hello")
        assert result == '"hello"'

    def test_none_returns_none(self) -> None:
        assert json_serialize(None) is None


class TestJsonArray:
    def test_list_input(self) -> None:
        result = json_array(["a", "b"])
        assert result == '["a", "b"]'

    def test_string_json_array(self) -> None:
        result = json_array('["x", "y"]')
        assert result == '["x", "y"]'

    def test_single_value_wrapped(self) -> None:
        result = json_array("single")
        assert result == '["single"]'

    def test_none_returns_none(self) -> None:
        assert json_array(None) is None


class TestToInt:
    def test_string(self) -> None:
        assert to_int("42") == 42

    def test_float_truncated(self) -> None:
        assert to_int(42.9) == 42

    def test_none_returns_none(self) -> None:
        assert to_int(None) is None

    def test_non_numeric_returns_none(self) -> None:
        assert to_int("abc") is None


class TestToFloat:
    def test_string(self) -> None:
        assert to_float("3.14") == 3.14

    def test_int(self) -> None:
        assert to_float(42) == 42.0

    def test_none_returns_none(self) -> None:
        assert to_float(None) is None


class TestToBool:
    def test_true_string(self) -> None:
        assert to_bool("true") is True

    def test_false_string(self) -> None:
        assert to_bool("false") is False

    def test_one_zero(self) -> None:
        assert to_bool(1) is True
        assert to_bool(0) is False

    def test_none_returns_none(self) -> None:
        assert to_bool(None) is None


class TestTrim:
    def test_strips_whitespace(self) -> None:
        assert trim("  hello  ") == "hello"

    def test_none_returns_none(self) -> None:
        assert trim(None) is None

    def test_non_string_returns_none(self) -> None:
        assert trim(42) is None


class TestLowercase:
    def test_mixed_case(self) -> None:
        assert lowercase("Hello World") == "hello world"

    def test_none_returns_none(self) -> None:
        assert lowercase(None) is None


class TestApplyTransform:
    def test_none_name_passes_through(self) -> None:
        assert apply_transform(None, "hello") == "hello"

    def test_known_transform(self) -> None:
        assert apply_transform("to_int", "42") == 42

    def test_unknown_transform_returns_none(self) -> None:
        assert apply_transform("nonexistent", "value") is None

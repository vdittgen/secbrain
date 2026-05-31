"""Tests for src.core.llm_helpers shared LLM parsing utilities."""

from __future__ import annotations

from unittest.mock import MagicMock

from src.core.llm_helpers import (
    parse_llm_json_array,
    parse_llm_json_dict,
    safe_chat_json,
)

# ------------------------------------------------------------------
# parse_llm_json_array
# ------------------------------------------------------------------


class TestParseLlmJsonArray:
    def test_raw_list(self) -> None:
        result = parse_llm_json_array([{"a": 1}, {"b": 2}])
        assert len(result) == 2
        assert result[0]["a"] == 1

    def test_dict_with_facts_key(self) -> None:
        result = parse_llm_json_array({"facts": [{"x": 1}]})
        assert result == [{"x": 1}]

    def test_dict_with_results_key(self) -> None:
        result = parse_llm_json_array({"results": [{"y": 2}]})
        assert result == [{"y": 2}]

    def test_dict_with_items_key(self) -> None:
        result = parse_llm_json_array({"items": [{"z": 3}]})
        assert result == [{"z": 3}]

    def test_dict_with_evaluations_key(self) -> None:
        result = parse_llm_json_array(
            {"evaluations": [{"score": 8}]},
        )
        assert result == [{"score": 8}]

    def test_single_dict_wrapped(self) -> None:
        """A dict with multiple keys becomes a single-item list."""
        result = parse_llm_json_array(
            {"name": "Alice", "score": 5},
        )
        assert result == [{"name": "Alice", "score": 5}]

    def test_empty_dict(self) -> None:
        result = parse_llm_json_array({})
        assert result == []

    def test_string_with_json_array(self) -> None:
        result = parse_llm_json_array('[{"a": 1}]')
        assert result == [{"a": 1}]

    def test_string_with_markdown_fences(self) -> None:
        raw = '```json\n[{"a": 1}]\n```'
        result = parse_llm_json_array(raw)
        assert result == [{"a": 1}]

    def test_string_with_extra_text(self) -> None:
        raw = 'Here are the results:\n[{"a": 1}]\nDone.'
        result = parse_llm_json_array(raw)
        assert result == [{"a": 1}]

    def test_invalid_string(self) -> None:
        result = parse_llm_json_array("not json at all")
        assert result == []

    def test_none_input(self) -> None:
        result = parse_llm_json_array(None)
        assert result == []

    def test_integer_input(self) -> None:
        result = parse_llm_json_array(42)
        assert result == []


# ------------------------------------------------------------------
# parse_llm_json_dict
# ------------------------------------------------------------------


class TestParseLlmJsonDict:
    def test_raw_dict(self) -> None:
        result = parse_llm_json_dict({"key": "value"})
        assert result == {"key": "value"}

    def test_string_json(self) -> None:
        result = parse_llm_json_dict('{"key": "value"}')
        assert result == {"key": "value"}

    def test_string_with_fences(self) -> None:
        raw = '```json\n{"key": "value"}\n```'
        result = parse_llm_json_dict(raw)
        assert result == {"key": "value"}

    def test_invalid_string(self) -> None:
        result = parse_llm_json_dict("not json")
        assert result == {}

    def test_none_input(self) -> None:
        result = parse_llm_json_dict(None)
        assert result == {}

    def test_list_input(self) -> None:
        result = parse_llm_json_dict([1, 2, 3])
        assert result == {}


# ------------------------------------------------------------------
# safe_chat_json
# ------------------------------------------------------------------


class TestSafeChatJson:
    def test_returns_llm_result(self) -> None:
        provider = MagicMock()
        provider.chat_json.return_value = {"answer": "yes"}
        result = safe_chat_json(
            provider, [{"role": "user", "content": "hi"}],
        )
        assert result == {"answer": "yes"}

    def test_returns_empty_on_error(self) -> None:
        provider = MagicMock()
        provider.chat_json.side_effect = Exception("LLM down")
        result = safe_chat_json(
            provider, [{"role": "user", "content": "hi"}],
        )
        assert result == {}

    def test_returns_empty_when_provider_is_none(self) -> None:
        result = safe_chat_json(
            None, [{"role": "user", "content": "hi"}],
        )
        assert result == {}

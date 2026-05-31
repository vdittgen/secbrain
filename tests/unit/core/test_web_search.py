"""Unit tests for src.core.web_search.

sensitivity_tier: N/A — test infrastructure
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from src.core.web_search import (
    MAX_WEB_CONTEXT_CHARS,
    WebSearchResponse,
    WebSearchResult,
    format_web_results,
    is_personal_question,
    search_web,
    web_results_to_sources,
)

# ------------------------------------------------------------------
# is_personal_question
# ------------------------------------------------------------------


class TestIsPersonalQuestion:
    def test_general_question(self) -> None:
        assert not is_personal_question("What is the capital of France?")

    def test_general_when(self) -> None:
        assert not is_personal_question(
            "When is Women's Day in Brazil?",
        )

    def test_personal_my(self) -> None:
        assert is_personal_question("What is my schedule today?")

    def test_personal_i_have(self) -> None:
        assert is_personal_question("What meetings do I have?")

    def test_personal_mine(self) -> None:
        assert is_personal_question("Show notes that are mine")

    def test_personal_me(self) -> None:
        assert is_personal_question("Tell me about my contacts")

    def test_personal_i_am(self) -> None:
        assert is_personal_question("I am looking for my files")

    def test_empty_string(self) -> None:
        assert not is_personal_question("")


# ------------------------------------------------------------------
# format_web_results
# ------------------------------------------------------------------


class TestFormatWebResults:
    def test_empty_results(self) -> None:
        resp = WebSearchResponse(query="test", results=[])
        assert format_web_results(resp) == ""

    def test_formats_correctly(self) -> None:
        resp = WebSearchResponse(
            query="quantum computing",
            results=[
                WebSearchResult(
                    title="QC 101",
                    body="Qubits explained.",
                    url="https://example.com/qc",
                ),
            ],
        )
        text = format_web_results(resp)
        assert "Web Search Results" in text
        assert "[WEB] QC 101" in text
        assert "Qubits explained." in text
        assert "https://example.com/qc" in text

    def test_truncates_long_results(self) -> None:
        results = [
            WebSearchResult(
                title=f"Result {i}",
                body="x" * 2000,
                url=f"https://example.com/{i}",
            )
            for i in range(10)
        ]
        resp = WebSearchResponse(query="test", results=results)
        text = format_web_results(resp)
        assert len(text) <= MAX_WEB_CONTEXT_CHARS + 50  # +slack
        assert "[... truncated]" in text

    def test_multiple_results(self) -> None:
        resp = WebSearchResponse(
            query="test",
            results=[
                WebSearchResult(
                    title="A", body="Body A", url="https://a.com",
                ),
                WebSearchResult(
                    title="B", body="Body B", url="https://b.com",
                ),
            ],
        )
        text = format_web_results(resp)
        assert "[WEB] A" in text
        assert "[WEB] B" in text


# ------------------------------------------------------------------
# web_results_to_sources
# ------------------------------------------------------------------


class TestWebResultsToSources:
    def test_creates_source_dicts(self) -> None:
        resp = WebSearchResponse(
            query="test",
            results=[
                WebSearchResult(
                    title="Title",
                    body="Body",
                    url="https://example.com",
                ),
            ],
        )
        sources = web_results_to_sources(resp)
        assert len(sources) == 1
        assert sources[0]["type"] == "web"
        assert sources[0]["sensitivity_tier"] == 1
        assert sources[0]["url"] == "https://example.com"
        assert sources[0]["id"] == "web-0"

    def test_empty_results(self) -> None:
        resp = WebSearchResponse(query="test", results=[])
        assert web_results_to_sources(resp) == []


# ------------------------------------------------------------------
# search_web
# ------------------------------------------------------------------


class TestSearchWeb:
    def test_success(self) -> None:
        """Mock DDGS to return results."""
        mock_ddgs = MagicMock()
        mock_ddgs.__enter__ = MagicMock(return_value=mock_ddgs)
        mock_ddgs.__exit__ = MagicMock(return_value=False)
        mock_ddgs.text.return_value = [
            {
                "title": "Result 1",
                "body": "Body 1",
                "href": "https://r1.com",
            },
        ]

        with patch(
            "duckduckgo_search.DDGS",
            return_value=mock_ddgs,
        ):
            resp = search_web("test query")

        assert isinstance(resp, WebSearchResponse)
        assert resp.query == "test query"
        assert len(resp.results) == 1
        assert resp.results[0].title == "Result 1"
        assert resp.results[0].url == "https://r1.com"

    def test_handles_import_error(self) -> None:
        """If duckduckgo_search is not installed, returns empty."""
        with patch.dict(
            "sys.modules", {"duckduckgo_search": None},
        ):
            resp = search_web("test query")
        assert isinstance(resp, WebSearchResponse)
        assert resp.query == "test query"

    def test_handles_exception(self) -> None:
        """Network errors return empty response."""
        mock_ddgs = MagicMock()
        mock_ddgs.__enter__ = MagicMock(return_value=mock_ddgs)
        mock_ddgs.__exit__ = MagicMock(return_value=False)
        mock_ddgs.text.side_effect = RuntimeError("fail")

        with patch(
            "duckduckgo_search.DDGS",
            return_value=mock_ddgs,
        ):
            resp = search_web("test")
        assert isinstance(resp, WebSearchResponse)
        assert resp.results == []

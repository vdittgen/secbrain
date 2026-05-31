"""Unit tests for `src.agents.brain.parts.split_answer_into_parts`.

The splitter routes assistant output into typed message parts so the
chat renderer can mount the right component. These tests pin down the
contract that the brain agent and the frontend both rely on.

sensitivity_tier: 1
"""

from __future__ import annotations

from src.agents.brain.parts import split_answer_into_parts


def test_plain_markdown_returns_single_part():
    answer = "Here is your **summary** for today.\n\n- one\n- two\n"
    parts = split_answer_into_parts(answer)
    assert len(parts) == 1
    assert parts[0].mime == "text/markdown"
    assert parts[0].data == answer


def test_empty_answer_returns_empty_list():
    assert split_answer_into_parts("") == []


def test_mermaid_fence_emits_code_and_panel_preview():
    answer = (
        "Here's the relationship map:\n\n"
        "```mermaid\n"
        "graph LR\nA --> B\n"
        "```\n\n"
        "Hope that helps."
    )
    parts = split_answer_into_parts(answer)
    # Prose, the preserved code fence (renders as markdown), the
    # rendered diagram (auto-opens in the side panel), and the tail.
    assert [p.mime for p in parts] == [
        "text/markdown",
        "text/markdown",
        "text/vnd.mermaid",
        "text/markdown",
    ]
    assert parts[1].data == "```mermaid\ngraph LR\nA --> B\n```"
    mermaid = parts[2]
    assert mermaid.data == "graph LR\nA --> B"
    assert mermaid.title == "mermaid"
    assert mermaid.display == "panel"


def test_vega_lite_fence_emits_code_and_panel_preview():
    spec = '{"mark": "bar", "data": {"values": []}}'
    answer = (
        "Here is the chart:\n\n"
        "```vega-lite\n"
        f"{spec}\n"
        "```\n"
    )
    parts = split_answer_into_parts(answer)
    assert [p.mime for p in parts] == [
        "text/markdown",
        "text/markdown",
        "application/vnd.vega-lite+json",
    ]
    assert parts[1].data == f"```vega-lite\n{spec}\n```"
    chart = parts[2]
    assert chart.display == "panel"
    assert chart.data == spec


def test_html_fence_emits_code_and_panel_preview():
    plain_html = "Sample:\n\n```html\n<p>Hi</p>\n```\n"
    parts = split_answer_into_parts(plain_html)
    # Each ```html fence produces three parts: the prose before it,
    # the original fence preserved as markdown (so the source shows
    # inline as a syntax-highlighted code block), and the sandboxed
    # rendered preview that auto-opens in the side panel.
    assert [p.mime for p in parts] == [
        "text/markdown",
        "text/markdown",
        "text/html",
    ]
    assert parts[1].data == "```html\n<p>Hi</p>\n```"
    assert parts[2].data == "<p>Hi</p>"
    assert parts[2].display == "panel"

    # The legacy `runnable` info-string keyword is still accepted; the
    # preserved fence keeps it so syntax highlighting is unchanged.
    runnable_html = "Sample:\n\n```html runnable\n<p>Hi</p>\n```\n"
    parts = split_answer_into_parts(runnable_html)
    assert [p.mime for p in parts] == [
        "text/markdown",
        "text/markdown",
        "text/html",
    ]
    assert parts[1].data == "```html runnable\n<p>Hi</p>\n```"


def test_unknown_fence_stays_inline():
    answer = (
        "Some prose.\n\n"
        "```python\nprint('hi')\n```\n\n"
        "More prose."
    )
    parts = split_answer_into_parts(answer)
    # ```python is a normal code fence — let the markdown renderer
    # dispatch it to its CodeBlock; do not extract.
    assert len(parts) == 1
    assert parts[0].mime == "text/markdown"
    assert "print('hi')" in parts[0].data


def test_file_fence_routes_pdf_by_extension():
    answer = (
        "See the report:\n\n"
        "```file\n"
        "/Users/me/report.pdf\n"
        "```\n"
    )
    parts = split_answer_into_parts(answer)
    # prose + preserved fence (markdown) + the typed artifact part.
    assert [p.mime for p in parts] == [
        "text/markdown",
        "text/markdown",
        "application/pdf",
    ]
    pdf = parts[2]
    assert pdf.data == "/Users/me/report.pdf"
    assert pdf.display == "panel"
    # `file` info-string is suppressed so the chip can fall back to
    # the MIME-derived "PDF preview" label.
    assert pdf.title == ""


def test_file_fence_routes_office_docs_by_extension():
    cases = {
        "doc.docx": (
            "application/vnd.openxmlformats-officedocument"
            ".wordprocessingml.document"
        ),
        "sheet.xlsx": (
            "application/vnd.openxmlformats-officedocument"
            ".spreadsheetml.sheet"
        ),
        "deck.pptx": (
            "application/vnd.openxmlformats-officedocument"
            ".presentationml.presentation"
        ),
    }
    for path, expected_mime in cases.items():
        answer = f"```file\n{path}\n```\n"
        parts = split_answer_into_parts(answer)
        typed = [p for p in parts if p.mime == expected_mime]
        assert len(typed) == 1, f"expected one {expected_mime} for {path}"
        assert typed[0].data == path
        assert typed[0].display == "panel"


def test_file_fence_routes_image_audio_video():
    cases = {
        "photo.png": "image/png",
        "cover.jpg": "image/jpeg",
        "song.mp3": "audio/mpeg",
        "clip.mp4": "video/mp4",
    }
    for path, expected_mime in cases.items():
        answer = f"```file\n{path}\n```\n"
        parts = split_answer_into_parts(answer)
        assert any(p.mime == expected_mime for p in parts), (
            f"missing {expected_mime} part for {path}"
        )


def test_file_fence_strips_query_and_fragment_when_sniffing():
    answer = (
        "```file\nhttps://example.com/report.pdf?token=abc#page=2\n```\n"
    )
    parts = split_answer_into_parts(answer)
    pdf = next(p for p in parts if p.mime == "application/pdf")
    assert pdf.data == "https://example.com/report.pdf?token=abc#page=2"


def test_file_fence_with_unknown_extension_stays_inline():
    answer = (
        "```file\n"
        "/Users/me/archive.zip\n"
        "```\n"
    )
    parts = split_answer_into_parts(answer)
    # Unknown extension → no typed part, fence stays in the markdown
    # stream as a plain code block.
    assert len(parts) == 1
    assert parts[0].mime == "text/markdown"
    assert "archive.zip" in parts[0].data


def test_file_fence_with_empty_body_stays_inline():
    answer = "```file\n\n```\n"
    parts = split_answer_into_parts(answer)
    assert len(parts) == 1
    assert parts[0].mime == "text/markdown"


def test_consecutive_special_blocks_with_no_prose_between():
    answer = (
        "```mermaid\nA --> B\n```\n"
        "```mermaid\nC --> D\n```"
    )
    parts = split_answer_into_parts(answer)
    # Each fence emits a code-fence markdown part + the typed artifact.
    mimes = [p.mime for p in parts]
    assert mimes == [
        "text/markdown",
        "text/vnd.mermaid",
        "text/markdown",
        "text/vnd.mermaid",
    ]
    assert parts[1].data == "A --> B"
    assert parts[3].data == "C --> D"


def test_sensitivity_tier_is_propagated_to_parts():
    answer = "Here:\n\n```mermaid\nA --> B\n```\n"
    parts = split_answer_into_parts(answer, sensitivity_tier=3)
    for p in parts:
        assert p.sensitivity_tier == 3

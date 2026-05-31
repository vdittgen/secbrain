"""Tests for the Apple bridge ``create_event`` arg normalisation.

The bridge ingests parameters extracted by an LLM, so it must tolerate
the messy shapes that LLMs produce — JSON ``null`` decoded to Python
``None``, the literal string ``"None"`` / ``"null"``, missing keys,
whitespace, and so on. These were the cause of the in-app
``Invalid isoformat string: 'None'`` failure when the user asked for
a tennis event without an explicit end time.

We don't actually invoke ``osascript``; the AppleScript runner is
patched out so each test exercises only the argument normalisation
and the script-building inputs.

sensitivity_tier: 1
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest
from src.extensions.bridges.apple import server


@pytest.fixture
def captured_script() -> dict[str, Any]:
    """Patch ``_run_osascript`` and ``_calendar_create_script`` to
    record their inputs without touching the host shell."""
    captured: dict[str, Any] = {}

    def fake_build(
        title: str,
        start_epoch: int,
        end_epoch: int,
        location: str,
        notes: str,
    ) -> str:
        captured["title"] = title
        captured["start_epoch"] = start_epoch
        captured["end_epoch"] = end_epoch
        captured["location"] = location
        captured["notes"] = notes
        return "FAKE-SCRIPT"

    def fake_run(_script: str) -> str:
        return "FAKE-UID-1234\n"

    with (
        patch.object(server, "_calendar_create_script", fake_build),
        patch.object(server, "_run_osascript", fake_run),
        patch.object(server, "_ensure_app_running", lambda *_a, **_k: None),
    ):
        yield captured


class TestArgStrNormalisation:
    """``_arg_str`` is the choke point — every LLM-produced string
    field for every Apple tool passes through it."""

    def test_missing_key_returns_none(self) -> None:
        assert server._arg_str({}, "title") is None

    def test_python_none_returns_none(self) -> None:
        assert server._arg_str({"title": None}, "title") is None

    def test_literal_none_string_returns_none(self) -> None:
        assert server._arg_str({"title": "None"}, "title") is None

    def test_literal_null_string_returns_none(self) -> None:
        assert server._arg_str({"title": "null"}, "title") is None

    def test_whitespace_returns_none(self) -> None:
        assert server._arg_str({"title": "   "}, "title") is None

    def test_real_value_passes_through(self) -> None:
        assert server._arg_str({"title": "Play Tennis"}, "title") == (
            "Play Tennis"
        )

    def test_strips_surrounding_whitespace(self) -> None:
        assert server._arg_str({"title": "  hi  "}, "title") == "hi"


class TestParseIsoToEpoch:
    """``_parse_iso_to_epoch`` used to crash with
    ``Invalid isoformat string: 'None'`` when the LLM returned a literal
    ``"None"`` string. It must now collapse those to ``None``."""

    def test_none_input(self) -> None:
        assert server._parse_iso_to_epoch(None) is None

    def test_empty_input(self) -> None:
        assert server._parse_iso_to_epoch("") is None
        assert server._parse_iso_to_epoch("   ") is None

    def test_literal_none_string(self) -> None:
        assert server._parse_iso_to_epoch("None") is None
        assert server._parse_iso_to_epoch("null") is None

    def test_iso_date_only(self) -> None:
        # 2026-05-22 at local midnight is a real epoch.
        assert isinstance(server._parse_iso_to_epoch("2026-05-22"), int)

    def test_iso_with_z_suffix(self) -> None:
        assert isinstance(
            server._parse_iso_to_epoch("2026-05-22T07:00:00Z"),
            int,
        )


class TestCreateEventArguments:
    """End-to-end of the argument-handling path for ``create_event``."""

    def test_happy_path(self, captured_script: dict[str, Any]) -> None:
        result = server.create_event({
            "title": "Play Tennis with Tiago",
            "start_time": "2026-05-23T07:00:00Z",
            "end_time": "2026-05-23T08:00:00Z",
        })
        assert result["success"] is True
        assert result["title"] == "Play Tennis with Tiago"
        assert captured_script["title"] == "Play Tennis with Tiago"
        assert captured_script["end_epoch"] > captured_script["start_epoch"]

    def test_missing_end_time_defaults_to_one_hour_window(
        self, captured_script: dict[str, Any],
    ) -> None:
        """The regression: the LLM emitted no ``end_time`` and the
        bridge crashed with ``Invalid isoformat string: 'None'``. It
        must now default to start + 1 hour and succeed."""
        result = server.create_event({
            "title": "Play Tennis with Tiago",
            "start_time": "2026-05-23T07:00:00Z",
            "end_time": None,
        })
        assert result["success"] is True
        assert (
            captured_script["end_epoch"] - captured_script["start_epoch"]
            == 3600
        )

    def test_literal_none_string_end_time(
        self, captured_script: dict[str, Any],
    ) -> None:
        """Same shape as above but the LLM emitted the literal string
        ``"None"`` instead of JSON null."""
        result = server.create_event({
            "title": "Play Tennis",
            "start_time": "2026-05-23T07:00:00Z",
            "end_time": "None",
        })
        assert result["success"] is True
        assert (
            captured_script["end_epoch"] - captured_script["start_epoch"]
            == 3600
        )

    def test_missing_start_time_defaults_to_soon(
        self, captured_script: dict[str, Any],
    ) -> None:
        result = server.create_event({"title": "Open block"})
        assert result["success"] is True
        # Default window is 1 hour.
        assert (
            captured_script["end_epoch"] - captured_script["start_epoch"]
            == 3600
        )

    def test_empty_title_rejected(self) -> None:
        with pytest.raises(ValueError, match="non-empty title"):
            server.create_event({"title": "   "})

    def test_end_before_start_is_corrected(
        self, captured_script: dict[str, Any],
    ) -> None:
        server.create_event({
            "title": "Misordered",
            "start_time": "2026-05-23T07:00:00Z",
            "end_time": "2026-05-23T06:00:00Z",
        })
        assert (
            captured_script["end_epoch"] - captured_script["start_epoch"]
            == 3600
        )

    def test_location_and_description_normalised(
        self, captured_script: dict[str, Any],
    ) -> None:
        """Both fields used to inherit the same ``"None"`` bug."""
        server.create_event({
            "title": "Coffee",
            "start_time": "2026-05-23T09:00:00Z",
            "end_time": "2026-05-23T10:00:00Z",
            "location": None,
            "description": "None",
        })
        assert captured_script["location"] == ""
        assert captured_script["notes"] == ""


class TestCalendarScriptShape:
    """Smoke-test ``_calendar_create_script`` produces the working
    shape on macOS 26: gate on Calendar being running, pick a writable
    calendar, and create the event in one shot with start/end dates in
    the property record (two-pass assignment trips Tahoe's autosave
    with ``-10025 "No end date has been set"``)."""

    def test_script_launches_calendar(self) -> None:
        # The cold-start race against macOS's async LaunchServices is
        # closed by a readiness gate: launch only if not already running,
        # then poll ``is running`` before sending the ``tell`` block.
        script = server._calendar_create_script(
            "Tennis", 100, 200, "", "",
        )
        assert 'tell application "Calendar" to launch' in script
        assert 'application "Calendar" is running' in script

    def test_script_filters_writable_calendars(self) -> None:
        script = server._calendar_create_script(
            "Tennis", 100, 200, "", "",
        )
        assert "writable of cal" in script
        assert "subscribed of cal" in script

    def test_script_creates_event_in_one_shot_with_dates(self) -> None:
        script = server._calendar_create_script(
            "Tennis", 100, 200, "", "",
        )
        # One-shot property record — the dates must be on the ``make
        # new event`` call so Calendar.app's autosave sees a complete
        # event and doesn't raise ``-10025``.
        assert "start date:startDate" in script
        assert "end date:endDate" in script
        # The two-pass form is what triggered the Tahoe regression; it
        # MUST NOT appear in the script.
        assert "set start date of newEvent to startDate" not in script
        assert "set end date of newEvent to endDate" not in script


class TestEnsureAppRunning:
    """``_ensure_app_running`` is the Python-side counterpart to the
    AppleScript readiness gate. It must (a) pre-launch the target app
    via ``open -g -a`` so LaunchServices is engaged, and (b) poll until
    the app reports ``running`` before letting the caller proceed."""

    def test_create_event_calls_ensure_app_running(self) -> None:
        calls: list[tuple[Any, ...]] = []

        def fake_ensure(app: str, **_kwargs: Any) -> None:
            calls.append((app,))

        def fake_run(_script: str) -> str:
            # Verify ensure ran before the create script — there must be
            # exactly one ensure call recorded by the time osascript is
            # invoked, and it must target Calendar.
            assert calls == [("Calendar",)]
            return "UID-1"

        with (
            patch.object(server, "_ensure_app_running", fake_ensure),
            patch.object(server, "_run_osascript", fake_run),
        ):
            result = server.create_event({
                "title": "Tennis",
                "start_time": "2026-05-23T07:00:00Z",
                "end_time": "2026-05-23T08:00:00Z",
            })
        assert result["success"] is True
        assert calls == [("Calendar",)]

    def test_ensure_app_running_pre_launches_with_open(self) -> None:
        """``open -g -a`` is what binds the call to LaunchServices; the
        helper must invoke it (``-g`` keeps the app in the background so
        it doesn't steal focus from the SecondBrain window)."""
        seen: list[list[str]] = []

        def fake_subprocess_run(cmd: list[str], **_kwargs: Any) -> Any:
            seen.append(cmd)

            class _Done:
                returncode = 0
                stdout = ""
                stderr = ""

            return _Done()

        with (
            patch.object(server.subprocess, "run", fake_subprocess_run),
            patch.object(server, "_run_osascript", lambda _s: "true"),
        ):
            server._ensure_app_running("Calendar")
        assert seen and seen[0][:4] == ["open", "-g", "-a", "Calendar"]

    def test_ensure_app_running_times_out(self) -> None:
        """If the app never flips to ``running`` the helper must raise
        with a descriptive message so the chat UI surfaces it instead of
        hanging or silently masking the failure."""

        class _Done:
            returncode = 0
            stdout = ""
            stderr = ""

        with (
            patch.object(
                server.subprocess,
                "run",
                lambda *_a, **_k: _Done(),
            ),
            # Probe always reports ``false`` — the app never becomes
            # ready within the deadline.
            patch.object(server, "_run_osascript", lambda _s: "false"),
        ):
            with pytest.raises(RuntimeError, match="did not become ready"):
                server._ensure_app_running(
                    "Calendar",
                    timeout_s=0.05,
                    poll_interval_s=0.01,
                )

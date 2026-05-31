"""Unit tests for the Mission Control dashboard CLI subcommands.

Drives ``cli_main`` end-to-end with a temp data dir, checking the
JSON contracts the Tauri layer parses. The Brain LLM is monkey-patched
out so tests don't hit the network — we verify the cache fallback +
data assembly logic only.

sensitivity_tier: 2
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from src.core.cli import main as cli_main


def _run(
    cli_args: list[str],
    data_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> dict | list:
    """Invoke cli_main and return parsed JSON from stdout."""
    rc = cli_main(["--data-dir", str(data_dir), *cli_args])
    out = capsys.readouterr().out.strip()
    assert rc == 0, f"cli returned {rc}; stdout={out}"
    assert out, "expected JSON on stdout"
    return json.loads(out.splitlines()[-1])


# ---------------------------------------------------------------------
# get-daily-brief
# ---------------------------------------------------------------------


def test_daily_brief_empty_day_uses_fallback(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With no events/replies/threads, the brief skips the LLM call."""
    # Point the brief cache at a writable temp location.
    monkeypatch.setattr(
        "src.core.cli._DASHBOARD_BRIEF_CACHE_PATH",
        tmp_path / "brief_cache.json",
    )
    payload = _run(["get-daily-brief"], tmp_path, capsys)
    assert isinstance(payload, dict)
    assert payload["brief"]
    # The fallback narrates an open day; doesn't mention specific items.
    assert "open" in payload["brief"].lower()
    assert payload["source_counts"]["events"] == 0
    assert payload["source_counts"]["pending_replies"] == 0


def test_daily_brief_caches_between_calls(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Second invocation reads from the cache file (same brief)."""
    cache_path = tmp_path / "brief_cache.json"
    monkeypatch.setattr(
        "src.core.cli._DASHBOARD_BRIEF_CACHE_PATH", cache_path,
    )
    first = _run(["get-daily-brief"], tmp_path, capsys)
    assert cache_path.exists()
    second = _run(["get-daily-brief"], tmp_path, capsys)
    assert first["brief"] == second["brief"]
    assert first["generated_at"] == second["generated_at"]


def test_daily_brief_force_bypasses_cache(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``--force`` writes a new cache entry (new generated_at)."""
    cache_path = tmp_path / "brief_cache.json"
    monkeypatch.setattr(
        "src.core.cli._DASHBOARD_BRIEF_CACHE_PATH", cache_path,
    )
    first = _run(["get-daily-brief"], tmp_path, capsys)
    # Hand-edit the cache so we can prove --force overwrites it.
    cached = json.loads(cache_path.read_text())
    cached["generated_at"] = "1970-01-01T00:00:00+00:00"
    cache_path.write_text(json.dumps(cached))
    forced = _run(["get-daily-brief", "--force"], tmp_path, capsys)
    assert forced["generated_at"] != "1970-01-01T00:00:00+00:00"
    assert forced["brief"] == first["brief"]  # same data → same fallback


# ---------------------------------------------------------------------
# get-active-threads
# ---------------------------------------------------------------------


def test_active_threads_empty(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    """Fresh DB with no marts returns an empty list, not an error."""
    payload = _run(["get-active-threads"], tmp_path, capsys)
    assert payload == []


def test_active_threads_honors_limit(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    """The ``--limit`` argument is forwarded through."""
    payload = _run(
        ["get-active-threads", "--limit", "5"], tmp_path, capsys,
    )
    assert isinstance(payload, list)
    assert len(payload) <= 5


# ---------------------------------------------------------------------
# get-agent-stream
# ---------------------------------------------------------------------


def test_agent_stream_returns_three_slots(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    """Even on a fresh DB the three slots are always present."""
    payload = _run(["get-agent-stream"], tmp_path, capsys)
    assert isinstance(payload, dict)
    assert payload["running"] == []  # Rust merges its tasks in
    assert isinstance(payload["awaiting_review"], list)
    assert isinstance(payload["recently_completed"], list)


# ---------------------------------------------------------------------
# get-suggested-actions
# ---------------------------------------------------------------------


def test_suggested_actions_falls_back_on_empty_state(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    """With no data, returns a generic non-empty chip list."""
    payload = _run(["get-suggested-actions"], tmp_path, capsys)
    assert isinstance(payload, dict)
    chips = payload["chips"]
    assert len(chips) >= 1
    for chip in chips:
        assert chip["label"]
        assert chip["prefilled_prompt"]


def test_suggested_actions_honors_limit(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    payload = _run(
        ["get-suggested-actions", "--limit", "2"], tmp_path, capsys,
    )
    assert len(payload["chips"]) <= 2


# ---------------------------------------------------------------------
# get-domain-summary (Phase 2)
# ---------------------------------------------------------------------


@pytest.mark.parametrize("domain", ["work", "personal", "health"])
def test_domain_summary_shape(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    domain: str,
) -> None:
    """All three domains return the same DTO shape on a fresh DB."""
    payload = _run(
        ["get-domain-summary", "--domain", domain], tmp_path, capsys,
    )
    assert isinstance(payload, dict)
    assert payload["domain"] == domain
    assert isinstance(payload["items"], list)
    assert isinstance(payload["open_loops"], list)


def test_domain_summary_rejects_unknown_domain(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    """argparse choices reject domains outside the known set."""
    with pytest.raises(SystemExit) as exc_info:
        from src.core.cli import main as cli_main

        cli_main([
            "--data-dir", str(tmp_path),
            "get-domain-summary", "--domain", "money",
        ])
    # argparse exits with code 2 on invalid choices.
    assert exc_info.value.code == 2


# ---------------------------------------------------------------------
# Reply origin propagation — source channel + original message id
# ---------------------------------------------------------------------


def _seed_pending_reply(
    tmp_path: Path,
    *,
    reply_id: str,
    message_id: str,
    source: str,
    contact_name: str,
    domain: str,
    importance: int = 9,
    reason: str = "",
) -> None:
    """Insert one row into ``_pending_replies``.

    Goes through ``ProactiveIntelligence`` once first so the table
    exists (it's created on demand by ``_ensure_tables``).
    """
    from src.agents.proactive import ProactiveIntelligence
    from src.core.data_layer import DataLayer

    layer = DataLayer(base_path=tmp_path)
    layer.initialize()
    ProactiveIntelligence(db_engine=layer.duckdb)  # creates table
    layer.duckdb.execute(
        "INSERT INTO _pending_replies "
        "(id, message_id, source, contact_name, domain, "
        " preview, importance, reason, message_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            reply_id, message_id, source, contact_name, domain,
            "Oi! Vai regar as plantas?", importance, reason,
            "2026-05-22T08:00:00Z",
        ],
    )


def test_today_board_carries_source_and_message_id(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    """The Today's Loops card must propagate the inbound channel +
    original message id so the Chat / Brain can hard-lock the reply
    action to the same platform."""
    _seed_pending_reply(
        tmp_path,
        reply_id="r-elmara",
        message_id="raw-msg-42",
        source="whatsapp",
        contact_name="Elmara Dittgen",
        domain="personal",
        reason="Asked about watering plants",
    )
    payload = _run(["today-board"], tmp_path, capsys)

    loops = payload["todays_loops"]
    assert len(loops) >= 1
    elmara = next(
        loop for loop in loops if "Elmara" in loop["label"]
    )
    assert elmara["source"] == "whatsapp"
    assert elmara["message_id"] == "raw-msg-42"
    assert elmara["contact_name"] == "Elmara Dittgen"


def test_domain_summary_open_loops_carry_source_and_message_id(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    """The domain Open Loops list (Your Life > Personal etc.) must
    carry the same metadata so its Draft reply button routes through
    the right channel."""
    _seed_pending_reply(
        tmp_path,
        reply_id="r-elmara",
        message_id="raw-msg-42",
        source="whatsapp",
        contact_name="Elmara Dittgen",
        domain="personal",
        reason="Asked about watering plants",
    )
    payload = _run(
        ["get-domain-summary", "--domain", "personal"], tmp_path, capsys,
    )
    loops = payload["open_loops"]
    assert len(loops) >= 1
    elmara = next(
        loop for loop in loops if "Elmara" in loop["label"]
    )
    assert elmara["source"] == "whatsapp"
    assert elmara["message_id"] == "raw-msg-42"
    assert elmara["contact_name"] == "Elmara Dittgen"

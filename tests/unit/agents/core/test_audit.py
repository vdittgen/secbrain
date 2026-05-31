"""SHA-256 audit chain integrity tests.

Mirrors the assurance contract of the Rust ``AuditLogger`` in
``src-tauri/src/firewall/audit.rs``: appends chain correctly, tampering
is detected, ``hash_payload`` is content-addressed.

sensitivity_tier: N/A
"""

from __future__ import annotations

from pathlib import Path

from src.agents.core.audit import GENESIS_HASH, AuditChain, hash_payload


def test_first_entry_links_to_genesis(tmp_path: Path) -> None:
    chain = AuditChain(path=tmp_path / "audit.jsonl")
    chain.append(
        event_type="prompt_scan",
        agent_id="firewall.injection",
        decision="allow",
        payload_hash=hash_payload("hello"),
    )
    entries = chain.recent(10)
    assert len(entries) == 1
    assert entries[0]["previous_hash"] == GENESIS_HASH


def test_chain_links_subsequent_entries(tmp_path: Path) -> None:
    chain = AuditChain(path=tmp_path / "audit.jsonl")
    for i in range(3):
        chain.append(
            event_type="agent_run",
            agent_id="triage",
            decision="ok",
            payload_hash=hash_payload(f"p{i}"),
        )
    # Newest first.
    entries = chain.recent(10)
    assert len(entries) == 3
    assert entries[0]["previous_hash"] != GENESIS_HASH
    assert chain.verify() is True


def test_tampering_breaks_chain(tmp_path: Path) -> None:
    path = tmp_path / "audit.jsonl"
    chain = AuditChain(path=path)
    for marker in ("a", "b", "c"):
        chain.append(
            event_type="agent_run", agent_id="x",
            decision="ok", payload_hash=marker * 64,
        )
    assert chain.verify()
    # Tamper a middle entry — the trailing entry's previous_hash will no
    # longer match the recomputed hash of the modified line, so the
    # chain detects the change.
    lines = path.read_text().splitlines()
    lines[1] = lines[1].replace('"ok"', '"BAD"', 1)
    path.write_text("\n".join(lines) + "\n")
    assert chain.verify() is False


def test_tampering_with_bad_previous_hash(tmp_path: Path) -> None:
    path = tmp_path / "audit.jsonl"
    chain = AuditChain(path=path)
    chain.append(
        event_type="agent_run", agent_id="x",
        decision="ok", payload_hash="a" * 64,
    )
    # Forge an unchained second entry directly.
    path.write_text(path.read_text() + '{"previous_hash":"deadbeef"}\n')
    assert chain.verify() is False


def test_hash_payload_deterministic() -> None:
    assert hash_payload("hello") == hash_payload("hello")
    assert hash_payload("hello") != hash_payload("hellx")


def test_empty_chain_verifies(tmp_path: Path) -> None:
    chain = AuditChain(path=tmp_path / "audit.jsonl")
    assert chain.verify() is True
    assert chain.recent(10) == []


def _concurrent_append_worker(path_str: str, count: int) -> None:
    """Top-level so ``multiprocessing`` (spawn) can pickle it.

    Each process constructs its own ``AuditChain`` over the shared
    path and appends ``count`` entries. ``fcntl.flock(LOCK_EX)``
    inside ``append()`` serializes the read-last-hash + write
    critical section across processes.
    """
    chain = AuditChain(path=Path(path_str))
    for _ in range(count):
        chain.append(
            event_type="agent_run", agent_id="stress",
            decision="ok", payload_hash="0" * 64,
        )


def test_concurrent_appenders_keep_chain_valid(tmp_path: Path) -> None:
    """Regression: pre-fix, multiple Python processes appending to
    the same audit.jsonl could read the same ``last_hash``, then each
    write a new entry claiming it as ``previous_hash``. The second
    entry's ``previous_hash`` no longer matched ``hash(prior_line)``,
    so ``verify()`` flipped to False at that point.

    With ``fcntl.flock(LOCK_EX)`` around the critical section, the
    chain must survive heavy parallel append load.
    """
    import multiprocessing as mp

    path = tmp_path / "audit.jsonl"
    procs_n = 8
    per_proc = 25
    ctx = mp.get_context("spawn")
    procs = [
        ctx.Process(
            target=_concurrent_append_worker,
            args=(str(path), per_proc),
        )
        for _ in range(procs_n)
    ]
    for p in procs:
        p.start()
    for p in procs:
        p.join(timeout=30)
        assert p.exitcode == 0, f"worker exited with {p.exitcode}"

    chain = AuditChain(path=path)
    assert chain.verify() is True, "chain must remain valid under concurrent appenders"
    # Sanity-check that all writes landed.
    assert len(chain.recent(procs_n * per_proc + 10)) == procs_n * per_proc

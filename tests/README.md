# Tests

Layout mirrors `src/` 1:1. When adding a test, decide the tier first.

## Tiers

| Tier | What it touches | Where to add |
|---|---|---|
| **unit** | Pure code, no I/O. DB, network, and LLM calls are mocked. Fast (< 50ms each). | `tests/unit/<package>/test_<module>.py` |
| **integration** | Real embedded DBs (SQLite, Kuzu, ChromaDB) + real pipeline executor. **No real LLM** — use the fakes in `tests/fixtures/`. | `tests/integration/test_<area>.py` |
| **e2e** | Full slice: ingestion → pipeline → query/action. May use real Ollama if available; otherwise skip. One file per user journey. | `tests/e2e/test_<journey>.py` |

A test that needs both a real DB and a real LLM belongs in `e2e/`, not `integration/`.

## Naming

`test_<module>.py` mirrors `src/<module>.py`. After the `refactor/ddd-review-cleanup` reorg:

```
src/agent_runtime/runner.py            ↔  tests/unit/agent_runtime/test_runner.py
src/extensions/mcp/client.py           ↔  tests/unit/extensions/mcp/test_client.py
src/extensions/connectors/catalog.py   ↔  tests/unit/extensions/connectors/test_catalog.py
src/extensions/bridges/whatsapp/listener.py  ↔  tests/unit/extensions/bridges/whatsapp/test_listener.py
```

If you cannot place a new test by mirroring, the test probably crosses a boundary and belongs in `integration/` or `e2e/`.

## Fixtures

| File | What it provides |
|---|---|
| `tests/fixtures/sample_data.py` | Realistic SQLite raw-table rows with mixed sensitivity tiers |
| `tests/fixtures/kuzu_fixtures.py` | Pre-populated Kuzu graph (people, events, places) |
| `tests/fixtures/chromadb_fixtures.py` | Pre-embedded ChromaDB documents |

Fixtures shared across more than one file should live in `conftest.py`. Adding the same setup to multiple test files is a smell.

## What's intentionally missing

- `tests/unit/firewall/` — firewall is Rust; tested via `cargo test --all`.
- `tests/unit/interface/` — frontend tested via Vitest, not pytest.

## Backlog (see `docs/CODEBASE_REVIEW.md` §7)

These four files are large enough to be hard to navigate; splitting them into per-feature files is a P1 refactor:

- `tests/unit/notifications/test_reply_handler.py` (1,757 LOC / 73 tests)
- `tests/unit/extensions/ingestion/test_adapter.py` (1,529 LOC / 44 tests)
- `tests/unit/agents/test_proactive_intelligence.py` (1,380 LOC / 55 tests)
- `tests/unit/extensions/mcp/test_installer.py` (1,101 LOC)

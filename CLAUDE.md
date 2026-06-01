# Arandu

Privacy-first AI operating system that runs as a native desktop app.
Open source (Apache-2.0), local inference only (Ollama).

## Architecture
- **App shell**: Tauri (Rust backend + web frontend)
- **Analytical DB**: SQLite (embedded, WAL mode)
- **Graph DB**: Kuzu (embedded, relationships/entities)
- **Vector search**: ChromaDB (embedded, semantic similarity)
- **Pipeline**: Manifest-driven Python (staging → intermediate → marts)
- **LLM**: Local Ollama (all inference stays on device). Routing policy lives in `src/agents/firewall/egress_firewall.py`; see `docs/PRIVACY.md`. The provider factory in `src/models/llm_provider.py` builds the local Ollama provider — there is no remote/cloud provider in this codebase.
- **Frontend**: React + Tailwind inside Tauri webview
- **Languages**: Rust (firewall, IPC), Python (pipeline, ML, agents), TypeScript (UI)

## Top-level packages
| Package | Bounded context |
|---|---|
| `src/core/` | Storage (sqlite/kuzu/chromadb), query engine, data layer, CLI dispatcher |
| `src/agents/` | Brain Agent, fact learner, insight generator, proactive intelligence, message triage/eval |
| `src/agent_runtime/` | Sandboxed agent runner, context, sensitivity guard, skills (3rd-party isolation) |
| `src/extensions/mcp/` | MCP protocol: client, installer, tool classifier |
| `src/extensions/connectors/` | Connector lifecycle: catalog, registry, manager, scheduler, requirements |
| `src/extensions/bridges/` | Native bridges: `apple/`, `whatsapp/` |
| `src/extensions/ingestion/` | Sync engine, adapters, transforms, schema discovery, model generator |
| `src/extensions/builtin/` | Built-in agents (weekly_digest, relationship_tracker) |
| `src/notifications/` | Orchestrator, notifier, reply handler, preferences |
| `src/pipeline/` | Manifest, runner, executor, brain, auditor, worker |
| `src/models/` | LLM provider abstraction, voice, sensitivity classifier |
| `src/interface/` | React frontend (pages, components, hooks) |
| `src-tauri/src/firewall/` | Audit chain (Rust reader of `~/.arandu/data/audit.jsonl`) |

Detailed file table → `docs/FILE_MAP.md`.

## Commands
- Build: `cargo tauri build`
- Dev: `cargo tauri dev`
- Test Python: `python -m pytest tests/ -v`
- Test Rust: `cargo test --all`
- Lint: `ruff check src/ && cargo clippy`
- Pipeline: `python -m src.pipeline.worker run`

## Coding standards
- Functional programming + SOLID. Don't over-engineer.
- Rust: follow Clippy. `Result<T, E>`. No `unwrap()` in production.
- Python: type hints required. Ruff. Docstrings on public functions.
- TypeScript: strict mode. Functional components only.
- Every function that touches user data MUST carry a `sensitivity_tier` annotation.
- Always branch from `main`; open a PR per phase. Ask before committing.
- No keyword-based filters — use LLM evals for non-trivial decisions.

## Sensitivity tiers
- **Tier 1** (low): preferences, interests. Auto-approved for agents.
- **Tier 2** (medium): habits, routines, people names. Requires agent consent (cacheable).
- **Tier 3** (high): health, finances, emotions, traumas. Per-request approval, never cached.
- Every column in every pipeline model MUST have `sensitivity_tier` metadata.

## Model selection
All agents run against the single local Ollama model configured in
`~/.arandu/settings.json` (`llm_model`). `src/agents/core/model_tiers.py`
exposes `tier_model_for()`, which returns `None` for every agent in
Arandu — i.e. no per-agent model overrides; everything inherits the
one local model. (The map is an extension point, left empty here.)

## Conventions
- Branch: `feature/[day]-[component]` or `refactor/<area>`.
- Commits: conventional (`feat:`, `fix:`, `docs:`, `test:`, `refactor:`).
- Database files live in `~/.arandu/data/` (NOT the project root, NOT `~/.arandu/data/`).
- New IPC commands: see recipe below.

## Top pitfalls
1. **Data path is `~/.arandu/data/`** — not `~/.arandu/data/`.
2. **`threading.Lock` is not reentrant** — use `_unlocked` helper methods for nested calls.
3. **Embeddings follow the chat provider** — Ollama chat → Ollama embeddings. The active model/dimension is recorded in `~/.arandu/data/chromadb/.embedding_meta.json`; switching models requires running `python -m src.core.chromadb.migrate` to rebuild the index.
4. **`dedupInvoke()` is NOT a cache** — only deduplicates concurrent in-flight requests.
5. **`isStale` defaults to `true`** when `pipelineStatus` is null.
6. **Only one Baileys connection per phone** — all sends route through the listener's outbox IPC.
7. **Self-chat uses `@lid` JID**, not `@s.whatsapp.net`. Use `resolve_self_lid()` from `bridges/whatsapp/paths.py`.
8. **Audit chain is append-only** — no delete API; modifications break the SHA-256 chain.
9. **Extension models MUST use `ext_` prefix** (`ext_stg_*` / `ext_int_*` / `ext_mart_*`); enforced by `SensitivityGuard`.
10. **`ask` / `ask-stream` are write commands** — `QueryTracker` logs every query.
11. **All inference stays local** — every tier runs on Ollama. The `EgressFirewall` routing policy and the `redaction_registry.py` placeholder system exist as extension points and are pass-through here. Never bypass `chat_via_firewalls` for "convenience". See `docs/PRIVACY.md`.
12. **Agent base classes live in `src/agents/core/`** — `SBAgent`, `SBOrchestrator`, `SBDeepAgent`. New LLM-using components MUST subclass one of these. Raw `LLMProvider` is being phased out.
13. **Firewall agents are non-editable** — `InjectionFirewall` and `EgressFirewall` live in `src/agents/firewall/`. The Agents page renders them as locked cards; the registry refuses `update_agent_config` for them.

## Multi-file recipes

### Add an IPC command
1. `src-tauri/src/commands/types.rs` — DTO struct(s) with `Serialize, Deserialize`
2. `src-tauri/src/commands/mod.rs` — `#[tauri::command]` calling `call_python_cli()`
3. `src-tauri/src/lib.rs` — register in `invoke_handler![]`
4. `src/core/cli.py` — add CLI subcommand handler (JSON to stdout)
5. Frontend — `dedupInvoke()` or `useAsyncData()`

### Add a pipeline model
1. Add `.sql` to `src/pipeline/{staging,intermediate,marts}/`. Every column needs `sensitivity_tier` metadata.
2. Register in `pipeline_manifest.json` (name, layer, source_tables, depends_on, audits).
3. Test in `tests/unit/pipeline/`.
4. Apply: `python -m src.pipeline.worker run`.

### Add a built-in agent
1. `src/extensions/builtin/{agent_id}/manifest.yaml`
2. `src/extensions/builtin/{agent_id}/agent.py` — subclass `BrainAgent` from `src.agent_runtime.base`
3. `__init__.py`
4. Tests in `tests/unit/extensions/builtin/`
5. Write tables MUST follow `ext_{agent_id}_*` pattern. Use `AgentContext`; no direct DB. `SensitivityGuard` enforces tier access.

### Add a dashboard widget
1. Inline functional component in `Dashboard.tsx` with `readonly` props
2. Fetch via `useAsyncData`
3. Pass freshness props to `FreshnessIndicator`
4. Skeleton loading state — see `ScheduleWidget`

## Pre-commit checklist
```bash
npx tsc --noEmit          # Frontend types
ruff check src/ tests/    # Python lint
python -m pytest tests/   # Python tests
cargo clippy && cargo test --all   # Rust
```

## Type sources of truth
| Location | Role |
|---|---|
| `src-tauri/src/commands/types.rs` | Rust DTOs — source of truth |
| `src/core/cli.py` | Python JSON output — must match Rust |
| `src/interface/hooks/*.ts` | TypeScript types — must match Rust |

## Python environment
- Python 3.11.4 (`.python-version`), venv: `.venv/`
- Core deps in `pyproject.toml`: `kuzu`, `chromadb`, `ollama`, `sqlmesh`
- Optional: `arandu[voice]`/`[voice-fallback]`
- Dev: `pytest`, `ruff` (line-length=88, rules E F I N W UP)

## Pointers
- `docs/ARCHITECTURE.md` — system design
- `docs/FILE_MAP.md` — full file inventory + IPC commands + frontend patterns
- `tests/README.md` — test taxonomy and naming

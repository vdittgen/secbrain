# Contributing to Arandu

Thanks for your interest in contributing! This guide covers everything you need to get started.

## Code of Conduct

This project has a [Code of Conduct](CODE_OF_CONDUCT.md). By participating,
you are expected to uphold it. Please report unacceptable behavior to the
contact listed there.

## License

By contributing to Arandu, you agree that your contributions will be
licensed under the Apache License, Version 2.0 (see [LICENSE](LICENSE)).
Per Section 5 of the Apache-2.0 license, any Contribution intentionally
submitted for inclusion in the Work shall be under the terms and conditions
of this License, without any additional terms or conditions.

We use a lightweight DCO (Developer Certificate of Origin). Please sign off
your commits with `git commit -s` to certify that you have the right to
submit the contribution under our license.

## Prerequisites

| Tool | Version | Install |
|------|---------|---------|
| Python | 3.10+ | [python.org](https://www.python.org/downloads/) or `pyenv install 3.11` |
| Rust | stable (2021 edition) | [rustup.rs](https://rustup.rs/) |
| Node.js | 18+ | [nodejs.org](https://nodejs.org/) |
| Ollama | latest | [ollama.ai](https://ollama.ai/) |

## Dev Environment Setup

```bash
# 1. Clone the repo
git clone https://github.com/vdittgen/arandu.git
cd arandu

# 2. Python environment
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

# 3. Node dependencies
npm install

# 4. Pull the default LLM
ollama pull gemma4:e2b

# 5. Initialize the databases with sample data
python -m src.core.cli init

# 6. Verify everything works
python -m pytest tests/ -v          # 402 tests
cargo test --all --manifest-path src-tauri/Cargo.toml  # 29 tests
npx tsc --noEmit                    # Type check
ruff check src/                     # Lint check

# 7. Start development
cargo tauri dev
```

## Code Style

### Python

- **Formatter/Linter:** Ruff (`ruff check src/ --fix && ruff format src/`)
- **Line length:** 88 characters
- **Type hints:** Required on all function signatures
- **Docstrings:** Required on all public functions (Google-style)
- **Imports:** Use `from __future__ import annotations` in every module
- **No bare `except:`** — Always catch specific exceptions

```python
def query_messages(
    self,
    limit: int = 10,
    max_sensitivity_tier: int = 2,
) -> list[dict[str, Any]]:
    """Retrieve recent messages filtered by sensitivity tier.

    Args:
        limit: Maximum number of messages to return.
        max_sensitivity_tier: Highest tier to include (1-3).

    Returns:
        List of message dicts with id, sender, content, and tier.

    sensitivity_tier: 2
    """
```

### Rust

- **Linter:** Clippy (`cargo clippy` — follow all suggestions)
- **Formatter:** `cargo fmt`
- **Error handling:** Use `Result<T, E>` for all fallible operations. No `.unwrap()` in production code.
- **Comments:** Document public functions with `///` doc comments

### TypeScript

- **Strict mode:** Enabled in `tsconfig.json`
- **Components:** Functional React components only. No class components.
- **Type checker:** `npx tsc --noEmit` must pass with zero errors

## Branch Naming

```
feature/[day]-[component]
```

Examples:
- `feature/d1-sqlite-setup`
- `feature/d5-brain-agent`
- `feature/d7-code-quality`

For non-sprint work:
- `fix/audit-log-rotation`
- `docs/architecture-update`

## Commit Messages

We use [Conventional Commits](https://www.conventionalcommits.org/):

```
feat(d5): brain agent with hybrid GraphRAG retrieval
fix(firewall): handle expired consent cache entries
test(d6): end-to-end integration tests for full data flow
docs(d7): README, CONTRIBUTING, ARCHITECTURE, and LICENSE
refactor(d7): code quality pass, lint fixes, and security review
```

Prefixes: `feat:`, `fix:`, `test:`, `docs:`, `refactor:`, `chore:`

## Pull Request Process

1. **Always branch from `main`** — never push directly
2. **Create a PR** for every change, no matter how small
3. **Include a description** of what changed and why
4. **Ensure all checks pass:**
   - `ruff check src/` — zero errors
   - `cargo clippy` — zero warnings
   - `npx tsc --noEmit` — zero errors
   - `python -m pytest tests/ -v` — all pass
   - `cargo test --all` — all pass
5. **Request review** before merging

## The Sensitivity Tier Rule

This is the single most important convention in the codebase.

### Every column MUST have a sensitivity tier

In every pipeline model (`.sql`), every column must be annotated with its sensitivity tier:

| Tier | Level | Examples | Agent Access |
|------|-------|----------|--------------|
| 1 | Public | Preferences, interests, UI state | Auto-approved |
| 2 | Personal | Names, routines, schedules, contacts | Requires consent |
| 3 | Sensitive | Health, finances, emotions, traumas | Per-request approval only |

### Every data-touching function MUST declare its tier

Any function that reads, writes, or processes user data must include a `sensitivity_tier` annotation in its docstring:

```python
def label(self, text: str) -> dict[str, Any] | None:
    """Classify a single text into emotional labels.

    sensitivity_tier: 3
    """
```

```rust
/// Retrieve recent messages for the dashboard.
///
/// # sensitivity_tier: 2
#[tauri::command]
pub fn get_recent_messages(...) -> Result<Vec<Message>, String> {
```

### Why this matters

The firewall enforces `WHERE sensitivity_tier <= ?` on every database query. If a column is missing its tier annotation, it defaults to tier 3 (most restrictive) — which means agents can't access it without explicit per-request user approval. Proper annotation ensures the right balance between usability and privacy.

## Running Tests

```bash
# All Python tests (unit + integration + e2e)
python -m pytest tests/ -v

# Just unit tests
python -m pytest tests/unit/ -v

# Just integration tests
python -m pytest tests/integration/ -v

# With coverage
python -m pytest tests/ --cov=src --cov-report=term-missing

# Rust tests
cargo test --all --manifest-path src-tauri/Cargo.toml

# TypeScript type check
npx tsc --noEmit

# Full lint suite
ruff check src/ && cargo clippy --manifest-path src-tauri/Cargo.toml && npx tsc --noEmit
```

## Project Structure

```
arandu/
├── src/
│   ├── core/               # Database engines and data layer
│   │   ├── sqlite/         #   SQLite engine, schemas, migrations
│   │   ├── kuzu/           #   Kuzu graph engine, schema, fixtures
│   │   ├── chromadb/       #   ChromaDB vector engine, embeddings, indexer
│   │   ├── data_layer.py   #   Facade coordinating all three engines
│   │   ├── query_engine.py #   Hybrid GraphRAG retrieval
│   │   └── cli.py          #   CLI entry point (Tauri bridge target)
│   ├── pipeline/           # Manifest-driven data transformation pipeline
│   │   ├── staging/        #   Raw → cleaned (stg_*)
│   │   ├── intermediate/   #   Enrichment and joins (int_*)
│   │   └── marts/          #   Business logic, final tables (mart_*)
│   ├── agents/             # AI agent system
│   │   ├── brain_agent.py  #   Main conversational agent
│   │   ├── registry/       #   Agent registration
│   │   └── sandbox/        #   Agent execution sandbox
│   ├── firewall/           # Python-side firewall (reserved)
│   ├── models/             # ML models
│   │   ├── labeler.py      #   Emotional labeling via Ollama
│   │   └── sensitivity_classifier.py
│   └── interface/          # React frontend
│       ├── App.tsx         #   Router and layout
│       ├── pages/          #   Dashboard, Chat, Explorer, Settings
│       └── components/     #   Sidebar, TopBar, PermissionModal, etc.
├── src-tauri/              # Tauri/Rust backend
│   └── src/
│       ├── lib.rs          #   Tauri command registration
│       ├── commands/       #   IPC command handlers + Python bridge
│       └── firewall/       #   Engine, classifier, consent, audit
├── tests/
│   ├── unit/               # Unit tests by module
│   ├── integration/        # Cross-module integration tests
│   └── e2e/                # End-to-end flow tests
├── docs/                   # Architecture and design documents
├── CLAUDE.md               # AI coding assistant instructions
├── CONTRIBUTING.md          # This file
└── LICENSE                  # Apache-2.0 License
```

## Questions?

Open an issue or start a discussion. We're happy to help you get started.

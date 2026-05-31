# Changelog

All notable changes to SecondBrain OS will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/), and this project adheres to [Semantic Versioning](https://semver.org/).

## [0.5.0-beta.1] - 2026-05-13

First public beta. Transitions the app out of the alpha track. The
focus of this release is a complete modernization of the agentic
stack onto `pydantic-ai` — every LLM call inside the agents now flows
through a typed SBAgent, the scheduler, and the egress + injection
firewalls. No raw `LLMProvider` calls remain outside the sandboxed
third-party agent runtime.

### Changed

**Agentic stack** (the headline of this release)

- **Brain v2 is the only path.** The legacy `BrainAgent` class and
  the `brain_v2` settings flag are gone. `BrainAgentV2` (an
  `SBOrchestrator` on `pydantic-ai`) handles every `ask` /
  `ask_stream` / chat / profile call. Existing `brain_v2` keys in
  `settings.json` are silently ignored.
- **All five legacy orchestrators relocated and modernized.**
  `FactLearner`, `MessageTriager`, `InsightGenerator`,
  `MessageEvaluator`, and `ProactiveIntelligence` moved to
  `src/agents/{fact_extractor,triage,insight,message_eval,proactive}/persistence.py`.
  Each delegates its LLM step to its matching SBAgent
  (`FactExtractorAgent`, `TriageAgent`, `InsightAgent`,
  `MessageEvaluatorAgent`, plus `PendingReplyAgent` /
  `ContactContextAgent` / `ActionableEventsAgent` for proactive).
- **Notification-intent migration:** the keyword-based
  `_detect_notification_intent` flow is replaced by a pydantic-ai
  `update_notification_preferences` tool on `BrainAgentV2`. The LLM
  picks the tool when the user asks about preferences.
- **Brain v2 action proposals.** Brain ships a new `propose_action`
  tool that emits structured `action_proposal` stream chunks. The
  full MCP action-confirmation flow (proposal → user confirm → MCP
  execute) now goes through the firewall + scheduler path.
- **Pipeline LLM calls modernized.** `LLMRouter`, `EmotionalLabeler`,
  `int_contact_topics`, `schema_discovery`, and `model_generator`
  now route through `QueryRouterAgent`, `LabelerAgent`,
  `TopicExtractorAgent`, the SBAgent `SchemaDiscoveryAgent`, and
  `ModelGeneratorAgent` respectively.

**WhatsApp + reply handler**

- `ReplyHandler`, the WhatsApp listener, and the terminal `chat_cli`
  all run on `BrainAgentV2`. The reply handler's action-detection
  loop consumes the new `action_proposal` chunk shape.

**Internals**

- New shared modules `src/agents/brain/context.py` and
  `src/agents/brain/actions.py` hold the Brain context-formatting
  helpers and the action-proposal primitives that used to live in
  `brain_agent.py`. The `ActionProposal` dataclass moves here.
- `src/agents/__init__.py` no longer re-exports the legacy
  `BrainAgent`. `BrainResponse` is re-exported from
  `src/agents/core/output_types.py`.
- New `src/agents/proactive/` package with
  `ProactiveIntelligence` (orchestrator + persistence) plus the
  four pydantic-style dataclasses (`PendingReply`,
  `ContactContext`, `ActionableEvent`, `TopicDigestEntry`).

**App version display**

- The `About` section in Settings reads the version dynamically via
  `getVersion()` from `@tauri-apps/api/app` instead of a hard-coded
  literal. One source of truth now (`tauri.conf.json`).

### Removed

- `src/agents/brain_agent.py` (legacy `BrainAgent` class, ~1,164
  lines).
- Five top-level legacy orchestrator files (`fact_learner.py`,
  `message_triage.py`, `insight_generator.py`,
  `message_evaluator.py`, `proactive_intelligence.py`) — relocated
  under their SBAgent subdirectories.
- `_detect_notification_intent` keyword-based flow and the five
  associated `_NOTIF_*_KEYWORDS` frozensets.
- The legacy `is_brain_v2_enabled()` flag function.
- `EmotionalLabeler.generate_digest()` — dead code; no production
  callers, only tests.
- 19+ legacy LLM prompt constants spread across `query_engine`,
  `labeler`, `int_contact_topics`, `schema_discovery`, and
  `model_generator`. Their content lives in frozen prompt files
  under `src/models/prompts/` (loaded by the corresponding
  SBAgent) instead.

### Migration notes

- `~/.secbrain/settings.json` keys that referenced `brain_v2` or
  pre-Phase-A1 paths are silently ignored — no migration step
  required.
- Database schemas are unchanged. `_learned_facts`, `_triage_log`,
  `_insights`, `_pending_replies`, `_contact_contexts`,
  `_actionable_events`, `_proactive_state`, `_evaluated_messages`,
  `_message_notifications`, `_topics` are all written by the same
  classes, just relocated.

## [0.1.0-alpha] - 2026-02-23

First alpha release. All core systems functional with sample data.

### Added

**Data Engine**
- DuckDB embedded analytical database with 6 raw-data schemas (messages, calendar events, notes, health metrics, contacts, files)
- Kuzu graph database with entity-relationship schema (Person, Event, Place, Emotion, Idea, Topic nodes and typed edges)
- ChromaDB vector store with Ollama embeddings (`nomic-embed-text`) and topic-based collections (personal, work, health, social, ideas)
- SQLMesh transformation pipeline with 13 models across three layers:
  - Staging (5 models): data cleaning, validation, and derived fields
  - Intermediate (4 models): enrichment, joins, emotional labeling, daily summaries
  - Marts (4 models): dashboard feed, health analytics, relationship insights, work summaries
- Every column in every model annotated with sensitivity tier (1-3)

**AI & ML**
- Emotional labeling system using Ollama (`llama3.1:8b`) with structured JSON output
- Sensitivity classifier for automatic tier assignment
- Hybrid GraphRAG query engine combining vector search, graph traversal, and structured SQL
- Brain Agent with context-aware LLM responses grounded in user data
- Source attribution in every response

**Security & Privacy**
- Rust-based firewall engine with three-tier sensitivity classification
- Consent management system with TTL-based caching (Tier 2) and per-request approval (Tier 3)
- Append-only audit log with SHA-256 hash chaining for tamper detection
- Field-level data scoping (agents receive only requested fields)
- 100% local execution — zero external network calls (only localhost Ollama)

**User Interface**
- Native macOS app via Tauri 2 (Rust backend + React webview)
- Dashboard with today's events, messages, and notes
- Chat interface for natural language queries
- Data explorer with sensitivity tier filtering
- Settings page (LLM model, data directory, theme, max sensitivity tier)
- Permission modal for agent consent requests
- Dark mode support

**Developer Experience**
- Full test suite: 402 Python tests + 29 Rust tests + TypeScript type checks
- CI pipeline (GitHub Actions) for Python, Rust, and TypeScript
- Comprehensive documentation: README, CONTRIBUTING, ARCHITECTURE
- Conventional commits, branch naming conventions, PR workflow
- Sample fixture data across all data types for development and testing

### Infrastructure
- Tauri-Python bridge via subprocess CLI for clean language separation
- Python CLI entry point (`python -m src.core.cli`) supporting init, status, reset, query, and ask commands
- Data stored in `~/.secbrain/data/` (DuckDB, Kuzu, ChromaDB, audit log)
- Settings persisted to `~/.secbrain/settings.json`

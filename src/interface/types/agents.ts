// Frontend types mirroring src-tauri/src/commands/types.rs for the
// Pydantic AI agent registry. Keep field names + casing in sync with
// the Rust DTOs.
//
// sensitivity_tier: 1

export interface PydanticAgentConfig {
  readonly system_prompt: string;
  readonly model_route: string;
  readonly model_override: string | null;
  /** Concrete LLM model name actually used (override or route default). */
  readonly resolved_model: string | null;
  readonly enabled_tools: ReadonlyArray<string>;
  readonly enabled_skills: ReadonlyArray<string>;
  readonly version: number;
  /** Post-batch delivery hook tool ids. Populated for user-authored
   * agents only; always ``[]`` for built-ins. */
  readonly delivery_tools: ReadonlyArray<string>;
}

export interface PydanticAgentRow {
  readonly agent_id: string;
  readonly name: string;
  readonly description: string;
  readonly category: string;
  readonly parent_agent: string | null;
  readonly tier: "SYSTEM" | "INTERACTIVE" | "PROACTIVE" | "BACKGROUND";
  readonly max_sensitivity_tier: number;
  readonly editable: boolean;
  readonly pattern: "single" | "orchestrator" | "deep";
  readonly output_schema: string;
  readonly available_tools: ReadonlyArray<string>;
  readonly available_skills: ReadonlyArray<string>;
  readonly tags: ReadonlyArray<string>;
  /** Sub-agent ids this agent delegates to. Empty unless the agent is
   * an orchestrator (or deep). Lets the UI render the architecture
   * without instantiating the factory. */
  readonly subagents: ReadonlyArray<string>;
  readonly config: PydanticAgentConfig;
  /** Pre-AI-edit snapshot of system_prompt; non-null only when the
   * prompt engineer most recently applied a rewrite and the user has
   * not yet reverted. ``null`` for built-in agents. */
  readonly pre_ai_system_prompt?: string | null;
  /** Companion snapshot of the description. */
  readonly pre_ai_description?: string | null;
}

export interface PydanticAgentListResponse {
  readonly agents: ReadonlyArray<PydanticAgentRow>;
}

export interface PydanticAgentResponse {
  readonly agent: PydanticAgentRow;
}

export interface PydanticAgentPatch {
  system_prompt?: string;
  model_route?: string;
  model_override?: string | null;
  enabled_tools?: ReadonlyArray<string>;
  enabled_skills?: ReadonlyArray<string>;
  /** Post-batch delivery hook tool ids. Only accepted for
   * user-authored agents. */
  delivery_tools?: ReadonlyArray<string>;
}

// ---------------------------------------------------------------------------
// Eval status (Phase 5b)
// ---------------------------------------------------------------------------

export type AgentEvalStatus =
  | "pending"
  | "running"
  | "passed"
  | "failed"
  | "skipped"
  | "error";

export interface AgentEvalFailedCase {
  readonly case: string;
  readonly evaluator: string;
  readonly reason: string;
}

export interface AgentEvalRun {
  readonly run_id: string;
  readonly agent_id: string;
  readonly suite: string | null;
  readonly trigger: "auto" | "manual" | "model_change_proposal";
  readonly started_at: string;
  readonly finished_at: string | null;
  readonly status: AgentEvalStatus;
  readonly cases_total: number;
  readonly cases_passed: number;
  readonly cases_failed: number;
  readonly failed_cases: ReadonlyArray<AgentEvalFailedCase>;
  readonly error: string | null;
}

export interface AgentEvalRunResponse {
  readonly run: AgentEvalRun;
}

export interface AgentEvalProposalResponse {
  readonly run: AgentEvalRun;
  readonly proposed_override: string;
}

export interface AgentEvalStatusResponse {
  readonly latest: AgentEvalRun | null;
  readonly history?: ReadonlyArray<AgentEvalRun>;
}

// ---------------------------------------------------------------------------
// Privacy v2: local-inference opt-in toggle
// ---------------------------------------------------------------------------

export interface LocalInferenceEvalFailure {
  readonly agent_id: string;
  readonly status: AgentEvalStatus;
  readonly failed_cases?: ReadonlyArray<AgentEvalFailedCase>;
  readonly error?: string | null;
}

export interface LocalInferenceEvalResult {
  readonly agent_id: string;
  readonly status: AgentEvalStatus;
  readonly cases_total: number;
  readonly cases_passed: number;
  readonly cases_failed: number;
}

export interface LocalInferenceToggleResponse {
  readonly status: "ok" | "eval_failed";
  readonly enabled: boolean;
  readonly failures?: ReadonlyArray<LocalInferenceEvalFailure>;
  readonly results?: ReadonlyArray<LocalInferenceEvalResult>;
}

// ---------------------------------------------------------------------------
// Per-agent input/output run log
// ---------------------------------------------------------------------------

export interface AgentRunLogEntry {
  readonly id: number;
  readonly agent_id: string;
  readonly ts: string;
  readonly input: string | null;
  readonly output: string | null;
  readonly duration_ms: number | null;
  readonly route: string | null;
  readonly status: "ok" | "error";
  readonly error: string | null;
}

export interface AgentActivityResponse {
  readonly agent_id: string;
  readonly entries: ReadonlyArray<AgentRunLogEntry>;
}

// ---------------------------------------------------------------------------
// Eval datasets (Phase 5c)
// ---------------------------------------------------------------------------

export interface AgentEvalDatasetCase {
  readonly name: string;
  readonly inputs: string;
  readonly expected_output: string | null;
  readonly evaluators: ReadonlyArray<string>;
}

export interface AgentEvalDataset {
  readonly agent_id: string;
  readonly suite: string | null;
  readonly source: "builtin" | "user" | "none";
  readonly path: string | null;
  readonly content: string | null;
  readonly parsed_cases: ReadonlyArray<AgentEvalDatasetCase>;
  readonly exists: boolean;
}

export interface DatasetValidationReport {
  readonly valid: boolean;
  readonly errors: ReadonlyArray<string>;
  readonly proposals: ReadonlyArray<string>;
  readonly firewall_verdict: "allow" | "warn" | "block";
}

export interface DatasetValidationResponse {
  readonly report: DatasetValidationReport;
  readonly persisted: boolean;
}

export interface UnsavedAgentSpec {
  readonly name: string;
  readonly description: string;
  readonly system_prompt: string;
  readonly max_sensitivity_tier: number;
  readonly output_schema?: string | null;
  readonly available_tools?: ReadonlyArray<string>;
}

export type DatasetEvalStrategy =
  | "deterministic"
  | "llm_judge"
  | "hybrid";

export type DatasetOutputShape =
  | "structured"
  | "prose"
  | "classification"
  | "mixed"
  | "unknown";

export interface DatasetSuggestion {
  readonly can_create: boolean;
  readonly reason_if_not: string | null;
  readonly purpose_summary: string;
  readonly output_shape: DatasetOutputShape;
  readonly eval_strategy: DatasetEvalStrategy;
  readonly dataset_yaml: string;
  readonly case_count: number;
  readonly confidence: number;
  readonly notes: ReadonlyArray<string>;
  readonly improvement_hints: ReadonlyArray<string>;
  /**
   * One-line additions the user should append to their system prompt
   * so the LLM produces tokens / language / format the dataset
   * expects. Empty when the prompt already pins what the cases test.
   */
  readonly system_prompt_additions: ReadonlyArray<string>;
}

export interface DatasetSuggestionResponse {
  readonly suggestion: DatasetSuggestion;
  readonly existing_case_names: ReadonlyArray<string>;
  readonly has_existing_dataset: boolean;
}

// ---------------------------------------------------------------------------
// Model picker
// ---------------------------------------------------------------------------

export type ModelRoute = "remote" | "local";

export interface ModelOption {
  readonly model_id: string;
  readonly route: ModelRoute;
  readonly rationale: string;
}

export interface ModelRecommendation {
  readonly can_recommend: boolean;
  readonly reason_if_not: string | null;
  readonly purpose_summary: string;
  readonly best_overall: ModelOption | null;
  readonly cost_effective: ModelOption | null;
  readonly notes: ReadonlyArray<string>;
  readonly improvement_hints: ReadonlyArray<string>;
  readonly confidence: number;
}

export interface ModelRecommendationResponse {
  readonly recommendation: ModelRecommendation;
  readonly available_remote_models: ReadonlyArray<string>;
  readonly available_local_models: ReadonlyArray<string>;
}

export interface ModelPickerFailedCase {
  readonly name: string;
  readonly evaluator: string;
  readonly reason: string;
}

export interface ModelPickerPriorAttempt {
  readonly model_id: string;
  readonly route: ModelRoute;
  readonly failed_cases: ReadonlyArray<ModelPickerFailedCase>;
}

export interface ModelPickerSpec {
  name: string;
  description: string;
  system_prompt: string;
  max_sensitivity_tier: number;
  output_schema?: string | null;
  enabled_skills: ReadonlyArray<string>;
  enabled_mcp_tools: ReadonlyArray<string>;
  agent_id?: string | null;
  /** Ids the picker has already proposed and the user tested+rejected. */
  excluded_models?: ReadonlyArray<string>;
  /** Per-rejected model: the cases it failed and why. */
  prior_attempts?: ReadonlyArray<ModelPickerPriorAttempt>;
}

// ---------------------------------------------------------------------------
// Prompt engineer (meta-agent)
// ---------------------------------------------------------------------------

export type PromptImprovementCategory =
  | "clarity"
  | "expected_output"
  | "language"
  | "format"
  | "scope"
  | "safety";

export type PromptImprovementTarget = "system_prompt" | "description";

export interface PromptImprovement {
  readonly category: PromptImprovementCategory;
  readonly original_snippet: string;
  readonly suggested_replacement: string;
  readonly rationale: string;
  readonly target: PromptImprovementTarget;
}

export interface PromptSuggestion {
  readonly can_improve: boolean;
  readonly reason_if_not: string | null;
  readonly improved_system_prompt: string;
  readonly improved_description: string;
  readonly system_prompt_additions: ReadonlyArray<string>;
  readonly improvements: ReadonlyArray<PromptImprovement>;
  readonly change_summary: string;
  readonly confidence: number;
  readonly notes: ReadonlyArray<string>;
}

export interface PromptSuggestionResponse {
  readonly suggestion: PromptSuggestion;
}

export interface PromptEngineerEvalFailure {
  readonly name: string;
  readonly evaluator: string;
  readonly reason: string;
}

export interface PromptEngineerSpec {
  name: string;
  description: string;
  system_prompt: string;
  max_sensitivity_tier: number;
  output_schema?: string | null;
  available_tools?: ReadonlyArray<string>;
  available_skills?: ReadonlyArray<string>;
  enabled_mcp_tools?: ReadonlyArray<string>;
  agent_id?: string | null;
  has_dataset?: boolean;
  prior_eval_failures?: ReadonlyArray<PromptEngineerEvalFailure>;
}

// ---------------------------------------------------------------------------
// User-authored agents (Phase 5c)
// ---------------------------------------------------------------------------

export interface UserAgentRow {
  readonly agent_id: string;
  readonly name: string;
  readonly description: string;
  readonly system_prompt: string;
  readonly model_route: string;
  readonly model_override: string | null;
  readonly enabled_skills: ReadonlyArray<string>;
  /** Catalog tool ids (`connector_id:tool_name`) the agent is wired
   * to. Includes BOTH data tools (sources, runner-pulled) and action
   * tools (LLM-callable mid-run). The runner uses catalog
   * ``tool_type`` to decide which bucket each entry belongs to. */
  readonly enabled_mcp_tools: ReadonlyArray<string>;
  readonly brain_access: boolean;
  readonly max_sensitivity_tier: number;
  readonly schedule_cron: string | null;
  readonly schedule_enabled: boolean;
  readonly created_at: string;
  readonly updated_at: string;
  readonly version: number;
  /** Pre-AI-edit snapshot of the system prompt — populated when the
   * prompt engineer most recently applied a rewrite. ``null`` when no
   * revert is pending. */
  readonly pre_ai_system_prompt: string | null;
  /** Companion snapshot of the description. */
  readonly pre_ai_description: string | null;
  /** ``"single"`` (default) or ``"orchestrator"``. Orchestrator rows
   * delegate to the agents in ``subagents`` via SBOrchestrator. */
  readonly pattern: "single" | "orchestrator";
  /** Sub-agent ids the orchestrator may delegate to. Empty for single. */
  readonly subagents: ReadonlyArray<string>;
  /** Action-typed catalog tool ids the runner invokes as a post-batch
   * delivery hook. Independent of ``enabled_mcp_tools`` — delivery is
   * never exposed to the LLM during per-item runs. */
  readonly delivery_tools: ReadonlyArray<string>;
}

export interface UserAgentStatus {
  readonly agent_id: string;
  readonly schedule_cron: string | null;
  readonly schedule_enabled: boolean;
  /** Data-typed entries of ``enabled_mcp_tools`` that drive the
   * batch runner each tick. Empty ⇒ schedule-only agent. */
  readonly enabled_data_tools: ReadonlyArray<string>;
  /** Tool ids dispatched by the post-batch delivery hook. */
  readonly delivery_tools: ReadonlyArray<string>;
  readonly last_run_at: string | null;
  readonly last_status: string | null;
  readonly last_error: string | null;
  readonly next_run_at: string | null;
  readonly pending_count: number;
}

export interface DeliveryCallRecord {
  readonly tool_id: string;
  /** "success" | "error" */
  readonly status: string;
  readonly error: string | null;
  readonly result_preview?: string | null;
}

export interface BatchRunSummary {
  readonly agent_id: string;
  /** "batch" | "generic" */
  readonly mode: string;
  readonly checked: number;
  readonly processed: number;
  readonly errors: number;
  readonly skipped: number;
  readonly run_ids: ReadonlyArray<string>;
  readonly error_messages: ReadonlyArray<string>;
  /** Post-batch delivery dispatch outcomes — one per ``delivery_tools``
   * invocation. Empty when no delivery tools are configured or the
   * hook was skipped (no items processed). */
  readonly delivery_calls: ReadonlyArray<DeliveryCallRecord>;
}

export interface UserAgentInput {
  name: string;
  description: string;
  system_prompt: string;
  model_route: string;
  model_override: string | null;
  enabled_skills: ReadonlyArray<string>;
  enabled_mcp_tools: ReadonlyArray<string>;
  brain_access: boolean;
  max_sensitivity_tier: number;
  schedule_cron: string | null;
  schedule_enabled: boolean;
  /** Optional — Rust defaults to ``"single"`` when omitted. */
  pattern?: "single" | "orchestrator";
  /** Optional — Rust defaults to ``[]`` when omitted. Required when
   * ``pattern`` is ``"orchestrator"``. */
  subagents?: ReadonlyArray<string>;
  /** Optional — action-typed catalog tool ids to invoke as the
   * post-batch delivery hook. Rust defaults to ``[]``. */
  delivery_tools?: ReadonlyArray<string>;
  /** When true, mark all existing source items as already processed
   * so the agent only picks up new data from creation time onward. */
  skip_backfill?: boolean;
}

export interface UserAgentResponse {
  readonly agent: PydanticAgentRow;
  readonly user_row: UserAgentRow;
}

export interface McpToolEntry {
  readonly connector_id: string;
  readonly connector_name: string;
  readonly tool_name: string;
  readonly display_name: string;
  readonly description: string;
  /** ``"action"`` (LLM-callable) or ``"data"`` (poller that feeds
   * ``target_table``). The unified picker splits each connector card
   * into Sources (data) / Tools (action) / Delivery (action) rows
   * based on this. */
  readonly tool_type: "action" | "data";
  /** Set on data tools; the SQLite table the poller writes to. */
  readonly target_table: string | null;
  /** JSON Schema of the tool's input. Empty object when the catalog
   * has none. The Delivery row uses this to flag tools with complex
   * schemas that may not deliver cleanly. */
  readonly input_schema: Record<string, unknown>;
}

/** Back-compat alias. New code should use ``McpToolEntry`` directly. */
export type McpActionToolEntry = McpToolEntry;

export interface McpActionToolListResponse {
  readonly tools: ReadonlyArray<McpToolEntry>;
}

// ---------------------------------------------------------------------------
// Skills (Phase 5c)
// ---------------------------------------------------------------------------

export interface SkillSummary {
  readonly id: string;
  readonly name: string;
  readonly description: string;
  readonly tags?: readonly string[];
  readonly sensitivity_tier?: number;
  readonly source?: string;
}

export interface SkillDetail {
  readonly skill_id: string;
  readonly name: string;
  readonly description: string;
  readonly category: string;
  readonly prompt_template: string;
  readonly parameters: Record<string, string>;
  readonly uses_llm: boolean;
  readonly builtin: boolean;
}

export interface SkillDetailResponse {
  readonly skill: SkillDetail;
}

export interface UserSkillInput {
  name: string;
  description: string;
  category: string;
  prompt_template: string;
  parameters: Record<string, string>;
  uses_llm: boolean;
}

export interface UserSkillMutationResponse {
  readonly skill: SkillDetail;
}

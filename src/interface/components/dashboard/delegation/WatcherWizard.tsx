/**
 * Watcher creation wizard — multi-step guided flow that produces a
 * fully-configured user agent from a Command Bar delegation prompt.
 *
 * Replaces the old single-screen DelegationModal. Four steps:
 *   1. What & When — name, prompt, schedule
 *   2. Notify Where — delivery tool selection
 *   3. Access & Model — brain, sensitivity, model, skills
 *   4. Review & Create — summary + automated prompt enhancement,
 *      agent creation, and eval dataset generation
 *
 * sensitivity_tier: 2
 */

import type { JSX } from "react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import {
  ArrowLeft,
  ArrowRight,
  Bell,
  Brain,
  Check,
  ChevronRight,
  CircleCheck,
  CircleDot,
  Eye,
  Loader2,
  Settings2,
  Sparkles,
  X,
  Zap,
} from "lucide-react";

import { useAsyncData } from "../../../hooks/useAsyncData";
import { dedupInvoke } from "../../../utils/requestDedup";
import ModelPicker from "../../ModelPicker";
import type { DelegationIntent } from "../../../utils/delegationIntent";
import type {
  DatasetSuggestionResponse,
  DatasetValidationResponse,
  McpActionToolListResponse,
  McpToolEntry,
  PromptEngineerSpec,
  PromptSuggestionResponse,
  SkillSummary,
  UserAgentInput,
  UserAgentResponse,
} from "../../../types/agents";
import { SCHEDULE_PRESETS } from "../../../pages/agents/shared/constants";

// ── Types ────────────────────────────────────────────────────────

type Step = 0 | 1 | 2 | 3;

const STEP_META: ReadonlyArray<{
  readonly label: string;
  readonly icon: typeof Eye;
}> = [
  { label: "What & When", icon: Eye },
  { label: "Notify", icon: Bell },
  { label: "Access", icon: Settings2 },
  { label: "Review", icon: Zap },
];

type CreationPhase =
  | "idle"
  | "enhancing"
  | "creating"
  | "evals"
  | "done"
  | "error";

interface WatcherWizardProps {
  readonly intent: DelegationIntent;
  readonly onClose: () => void;
  readonly onCreated: (agentId: string) => void;
}

// ── Watcher-specific schedule presets (always-on, no "Off") ──────

const WATCHER_SCHEDULES = SCHEDULE_PRESETS.filter((p) => p.cron !== null);

// ── Helpers ──────────────────────────────────────────────────────

function groupToolsByConnector(
  tools: ReadonlyArray<McpToolEntry>,
  toolType: "data" | "action",
): ReadonlyArray<{
  readonly connectorId: string;
  readonly connectorName: string;
  readonly tools: ReadonlyArray<McpToolEntry>;
}> {
  const byId = new Map<
    string,
    { name: string; tools: McpToolEntry[] }
  >();
  for (const t of tools) {
    if (t.tool_type !== toolType) continue;
    const entry = byId.get(t.connector_id) ?? {
      name: t.connector_name,
      tools: [],
    };
    entry.tools.push(t);
    byId.set(t.connector_id, entry);
  }
  return [...byId.entries()]
    .map(([id, v]) => ({
      connectorId: id,
      connectorName: v.name,
      tools: v.tools,
    }))
    .sort((a, b) => a.connectorName.localeCompare(b.connectorName));
}

const DELIVERY_KEYWORDS =
  /\b(send|notify|post|message|reply|forward|deliver|alert|push|write_message)\b/i;

function isDeliveryViable(tool: McpToolEntry): boolean {
  if (tool.tool_type !== "action") return false;
  const nameOrDesc = `${tool.tool_name} ${tool.display_name} ${tool.description}`;
  if (!DELIVERY_KEYWORDS.test(nameOrDesc)) return false;
  const schema = (tool.input_schema ?? {}) as Record<string, unknown>;
  const required = (schema.required ?? []) as ReadonlyArray<string>;
  if (required.length === 0) return true;
  const props = (schema.properties ?? {}) as Record<
    string,
    { type?: string }
  >;
  return required.every((k) => props[k]?.type === "string");
}

function groupDeliveryToolsByConnector(
  tools: ReadonlyArray<McpToolEntry>,
): ReadonlyArray<{
  readonly connectorId: string;
  readonly connectorName: string;
  readonly tools: ReadonlyArray<McpToolEntry>;
}> {
  const byId = new Map<
    string,
    { name: string; tools: McpToolEntry[] }
  >();
  for (const t of tools) {
    if (!isDeliveryViable(t)) continue;
    const entry = byId.get(t.connector_id) ?? {
      name: t.connector_name,
      tools: [],
    };
    entry.tools.push(t);
    byId.set(t.connector_id, entry);
  }
  return [...byId.entries()]
    .map(([id, v]) => ({
      connectorId: id,
      connectorName: v.name,
      tools: v.tools,
    }))
    .sort((a, b) => a.connectorName.localeCompare(b.connectorName));
}

// ── Main component ───────────────────────────────────────────────

function WatcherWizard({
  intent,
  onClose,
  onCreated,
}: WatcherWizardProps): JSX.Element {
  // Step navigation
  const [step, setStep] = useState<Step>(0);

  // Step 1 — What & When
  const [name, setName] = useState(intent.suggestedName);
  const [prompt, setPrompt] = useState(intent.prompt);
  const [schedule, setSchedule] = useState<string>(() => {
    const match = WATCHER_SCHEDULES.find(
      (p) => p.cron === intent.suggestedCron,
    );
    return match?.label ?? WATCHER_SCHEDULES[0].label;
  });
  const [customCron, setCustomCron] = useState(intent.suggestedCron);

  // Step 1 cont. — Sources
  const [sourceTools, setSourceTools] = useState<string[]>([]);
  const [skipBackfill, setSkipBackfill] = useState(true);

  // Step 2 — Notify Where
  const [deliveryTools, setDeliveryTools] = useState<string[]>([]);

  // Step 3 — Access & Model
  const [brainAccess, setBrainAccess] = useState(true);
  const maxTier = 2;
  const [modelRoute, setModelRoute] = useState("inherit");
  const [modelOverride, setModelOverride] = useState("");
  const [enabledSkills, setEnabledSkills] = useState<string[]>([]);

  // Step 4 — Creation flow
  const [creationPhase, setCreationPhase] = useState<CreationPhase>("idle");
  const [creationError, setCreationError] = useState<string | null>(null);
  const [enhancedPrompt, setEnhancedPrompt] = useState<string | null>(null);
  const [evalCaseCount, setEvalCaseCount] = useState<number | null>(null);

  // Async data for Step 2 & 3
  const toolsData = useAsyncData(
    useCallback(
      () => dedupInvoke<McpActionToolListResponse>("list_mcp_action_tools"),
      [],
    ),
  );
  const skillsData = useAsyncData(
    useCallback(
      () => dedupInvoke<ReadonlyArray<SkillSummary>>("list_skills_v2"),
      [],
    ),
  );

  const allTools = toolsData.data?.tools ?? [];

  const sourceToolGroups = useMemo(
    () => groupToolsByConnector(allTools, "data"),
    [allTools],
  );

  const connectorGroups = useMemo(
    () => groupDeliveryToolsByConnector(allTools),
    [allTools],
  );
  const skills: ReadonlyArray<SkillSummary> = Array.isArray(skillsData.data)
    ? skillsData.data
    : [];

  // Resolved cron value
  const resolvedCron = useMemo(() => {
    const preset = WATCHER_SCHEDULES.find((p) => p.label === schedule);
    return preset?.cron ?? customCron;
  }, [schedule, customCron]);

  // System prompt composed from the user's request
  const systemPrompt = useMemo(
    () =>
      [
        "You are a Watcher agent created from a Command Bar delegation.",
        "On each scheduled run, decide whether the user needs to be",
        "notified about a development matching their request below.",
        "Use the brain tool to query the user's data.",
        "",
        "If something matters, return a short summary the dashboard can",
        "surface. If nothing has changed, return an empty summary —",
        "do not invent activity.",
        "",
        "User's request:",
        prompt,
      ].join("\n"),
    [prompt],
  );

  // Validation per step
  const canAdvance = useMemo(() => {
    switch (step) {
      case 0:
        return (
          name.trim().length > 0
          && prompt.trim().length > 0
          && (sourceTools.length > 0 || !toolsData.isLoading)
        );
      case 1:
        return true;
      case 2:
        return true;
      case 3:
        return creationPhase === "idle" || creationPhase === "done";
      default:
        return false;
    }
  }, [step, name, prompt, creationPhase]);

  const next = useCallback(() => {
    if (step < 3 && canAdvance) setStep((s) => (s + 1) as Step);
  }, [step, canAdvance]);

  const back = useCallback(() => {
    if (step > 0) setStep((s) => (s - 1) as Step);
  }, [step]);

  // Toggle a source tool
  const toggleSource = useCallback((toolId: string) => {
    setSourceTools((prev) =>
      prev.includes(toolId)
        ? prev.filter((id) => id !== toolId)
        : [...prev, toolId],
    );
  }, []);

  // Toggle a delivery tool
  const toggleDelivery = useCallback((toolId: string) => {
    setDeliveryTools((prev) =>
      prev.includes(toolId)
        ? prev.filter((id) => id !== toolId)
        : [...prev, toolId],
    );
  }, []);

  // Toggle a skill
  const toggleSkill = useCallback((skillId: string) => {
    setEnabledSkills((prev) =>
      prev.includes(skillId)
        ? prev.filter((id) => id !== skillId)
        : [...prev, skillId],
    );
  }, []);

  // ── Creation flow ────────────────────────────────────────────

  const [enhanceError, setEnhanceError] = useState<string | null>(null);
  const [evalError, setEvalError] = useState<string | null>(null);

  const create = useCallback(async () => {
    setCreationPhase("enhancing");
    setCreationError(null);
    setEnhanceError(null);
    setEvalError(null);

    let finalPrompt = systemPrompt;
    let finalDesc = `Created from dashboard — "${prompt.trim().slice(0, 80)}"`;

    // Step A: Prompt enhancement (best-effort)
    try {
      const spec: PromptEngineerSpec = {
        name: name.trim(),
        description: finalDesc,
        system_prompt: systemPrompt,
        max_sensitivity_tier: maxTier,
        agent_id: null,
        available_tools: [],
        available_skills: enabledSkills,
        enabled_mcp_tools: sourceTools,
        has_dataset: false,
      };
      const resp = await invoke<PromptSuggestionResponse>(
        "suggest_prompt_improvements",
        { spec },
      );
      if (resp.suggestion.can_improve) {
        finalPrompt = resp.suggestion.improved_system_prompt;
        finalDesc = resp.suggestion.improved_description;
        setEnhancedPrompt(finalPrompt);
      }
    } catch (err) {
      setEnhanceError(
        err instanceof Error ? err.message : String(err),
      );
    }

    // Step B: Create agent
    setCreationPhase("creating");
    let agentId: string;
    try {
      const input: UserAgentInput = {
        name: name.trim(),
        description: finalDesc,
        system_prompt: finalPrompt,
        model_route: modelRoute,
        model_override: modelOverride.trim() || null,
        enabled_skills: enabledSkills,
        enabled_mcp_tools: sourceTools,
        brain_access: brainAccess,
        max_sensitivity_tier: maxTier,
        schedule_cron: resolvedCron,
        schedule_enabled: true,
        pattern: "single",
        subagents: [],
        delivery_tools: deliveryTools,
        skip_backfill: skipBackfill,
      };
      const created = await invoke<UserAgentResponse>("create_user_agent", {
        input,
      });
      agentId = created.agent.agent_id;
    } catch (err) {
      setCreationPhase("error");
      setCreationError(
        err instanceof Error ? err.message : String(err),
      );
      return;
    }

    // Step C: Eval dataset (best-effort)
    // Use unsavedSpec instead of agentId because each call_python_cli
    // spawns a fresh Python process that won't have the just-created
    // agent in its in-memory registry.
    setCreationPhase("evals");
    try {
      const unsavedSpec = {
        name: name.trim(),
        description: finalDesc,
        system_prompt: finalPrompt,
        max_sensitivity_tier: maxTier,
      };
      const resp = await invoke<DatasetSuggestionResponse>(
        "suggest_eval_dataset",
        { agentId: null, unsavedSpec },
      );
      if (resp.suggestion.can_create) {
        const uploaded = await invoke<DatasetValidationResponse>(
          "upload_user_eval_dataset",
          { agentId, content: resp.suggestion.dataset_yaml },
        );
        if (uploaded.persisted) {
          setEvalCaseCount(resp.suggestion.case_count);
        }
      }
    } catch (err) {
      setEvalError(
        err instanceof Error ? err.message : String(err),
      );
    }

    setCreationPhase("done");
    onCreated(agentId);
  }, [
    systemPrompt,
    prompt,
    name,
    maxTier,
    enabledSkills,
    sourceTools,
    skipBackfill,
    deliveryTools,
    modelRoute,
    modelOverride,
    brainAccess,
    resolvedCron,
    onCreated,
  ]);

  // Keyboard: Enter to advance, Escape to close
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [onClose]);

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label="Create a Watcher agent"
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4"
      onClick={onClose}
    >
      <div
        className="flex w-full max-w-lg flex-col rounded-4 border border-hairline bg-surface shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between border-b border-hairline px-5 py-3">
          <div className="flex items-center gap-2">
            <Sparkles className="h-5 w-5 text-indigo" strokeWidth={1.6} />
            <h3 className="text-base font-semibold text-ink">
              New Watcher
            </h3>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close"
            className="rounded-1 p-1 text-muted hover:bg-bg-2 hover:text-ink"
          >
            <X className="h-4 w-4" strokeWidth={1.6} />
          </button>
        </div>

        {/* Step indicator */}
        <div className="flex items-center justify-center gap-1 border-b border-hairline/60 px-5 py-2">
          {STEP_META.map((meta, i) => {
            const done = i < step;
            const active = i === step;
            const Icon = meta.icon;
            return (
              <button
                key={meta.label}
                type="button"
                onClick={() => {
                  if (i < step) setStep(i as Step);
                }}
                disabled={i > step}
                className={`flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[11px] transition-colors ${
                  active
                    ? "bg-indigo-soft text-indigo"
                    : done
                      ? "text-ink hover:bg-surface-2"
                      : "text-muted/50"
                }`}
              >
                {done ? (
                  <Check className="h-3 w-3 text-success" strokeWidth={2} />
                ) : (
                  <Icon className="h-3 w-3" strokeWidth={1.6} />
                )}
                <span className="hidden sm:inline">{meta.label}</span>
              </button>
            );
          })}
        </div>

        {/* Step content */}
        <div className="flex-1 overflow-auto px-5 py-4">
          {step === 0 && (
            <StepWhatWhen
              name={name}
              onName={setName}
              prompt={prompt}
              onPrompt={setPrompt}
              schedule={schedule}
              onSchedule={setSchedule}
              customCron={customCron}
              onCustomCron={setCustomCron}
              sourceToolGroups={sourceToolGroups}
              sourceTools={sourceTools}
              onToggleSource={toggleSource}
              loadingSources={toolsData.isLoading}
              skipBackfill={skipBackfill}
              onSkipBackfill={setSkipBackfill}
            />
          )}
          {step === 1 && (
            <StepNotify
              connectorGroups={connectorGroups}
              deliveryTools={deliveryTools}
              onToggle={toggleDelivery}
              loading={toolsData.isLoading}
            />
          )}
          {step === 2 && (
            <StepAccess
              brainAccess={brainAccess}
              onBrainAccess={setBrainAccess}
              modelRoute={modelRoute}
              onModelRoute={setModelRoute}
              modelOverride={modelOverride}
              onModelOverride={setModelOverride}
              skills={skills}
              enabledSkills={enabledSkills}
              onToggleSkill={toggleSkill}
            />
          )}
          {step === 3 && (
            <StepReview
              name={name}
              prompt={prompt}
              schedule={schedule}
              resolvedCron={resolvedCron}
              sourceTools={sourceTools}
              deliveryTools={deliveryTools}
              brainAccess={brainAccess}
              modelRoute={modelRoute}
              modelOverride={modelOverride}
              enabledSkills={enabledSkills}
              creationPhase={creationPhase}
              creationError={creationError}
              enhanceError={enhanceError}
              evalError={evalError}
              enhancedPrompt={enhancedPrompt}
              evalCaseCount={evalCaseCount}
            />
          )}
        </div>

        {/* Footer */}
        <div className="flex items-center justify-between border-t border-hairline px-5 py-3">
          <div>
            {step > 0 && creationPhase === "idle" && (
              <button
                type="button"
                onClick={back}
                className="flex items-center gap-1 rounded-2 px-3 py-1.5 text-xs text-muted transition-colors hover:text-ink"
              >
                <ArrowLeft className="h-3 w-3" strokeWidth={1.6} />
                Back
              </button>
            )}
          </div>
          <div className="flex items-center gap-2">
            {creationPhase === "done" ? (
              <button
                type="button"
                onClick={onClose}
                className="flex items-center gap-1.5 rounded-2 bg-success px-3 py-1.5 text-xs font-medium text-white transition-colors hover:bg-success/90"
              >
                <Check className="h-3 w-3" strokeWidth={1.6} />
                Done
              </button>
            ) : step < 3 ? (
              <button
                type="button"
                onClick={next}
                disabled={!canAdvance}
                className="flex items-center gap-1.5 rounded-2 bg-indigo px-3 py-1.5 text-xs font-medium text-white transition-colors hover:bg-indigo-2 disabled:opacity-50"
              >
                Next
                <ArrowRight className="h-3 w-3" strokeWidth={1.6} />
              </button>
            ) : (
              <button
                type="button"
                onClick={create}
                disabled={
                  creationPhase !== "idle" && creationPhase !== "error"
                }
                className="flex items-center gap-1.5 rounded-2 bg-indigo px-3 py-1.5 text-xs font-medium text-white transition-colors hover:bg-indigo-2 disabled:opacity-50"
              >
                {creationPhase !== "idle" && creationPhase !== "error" ? (
                  <Loader2
                    className="h-3 w-3 animate-spin"
                    strokeWidth={1.6}
                  />
                ) : (
                  <Sparkles className="h-3 w-3" strokeWidth={1.6} />
                )}
                Create Watcher
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

// ── Step 1: What & When ──────────────────────────────────────────

function StepWhatWhen({
  name,
  onName,
  prompt,
  onPrompt,
  schedule,
  onSchedule,
  customCron,
  onCustomCron,
  sourceToolGroups,
  sourceTools,
  onToggleSource,
  loadingSources,
  skipBackfill,
  onSkipBackfill,
}: {
  readonly name: string;
  readonly onName: (v: string) => void;
  readonly prompt: string;
  readonly onPrompt: (v: string) => void;
  readonly schedule: string;
  readonly onSchedule: (v: string) => void;
  readonly customCron: string;
  readonly onCustomCron: (v: string) => void;
  readonly sourceToolGroups: ReadonlyArray<{
    readonly connectorId: string;
    readonly connectorName: string;
    readonly tools: ReadonlyArray<McpToolEntry>;
  }>;
  readonly sourceTools: ReadonlyArray<string>;
  readonly onToggleSource: (toolId: string) => void;
  readonly loadingSources: boolean;
  readonly skipBackfill: boolean;
  readonly onSkipBackfill: (v: boolean) => void;
}): JSX.Element {
  const isCustom = !WATCHER_SCHEDULES.some((p) => p.label === schedule);
  const sourceSet = useMemo(() => new Set(sourceTools), [sourceTools]);

  return (
    <div className="space-y-3">
      <p className="text-xs text-muted">
        Describe what the watcher should look for, pick a data source,
        and choose how often it should check.
      </p>

      <label className="block">
        <span className="text-[11px] uppercase tracking-[0.06em] text-muted">
          Name
        </span>
        <input
          type="text"
          value={name}
          onChange={(e) => onName(e.target.value)}
          placeholder="e.g. Inbox bill watcher"
          className="mt-1 w-full rounded-2 border border-hairline bg-bg-2 px-3 py-2 text-sm text-ink outline-none focus:border-indigo focus:shadow-glow"
        />
      </label>

      <label className="block">
        <span className="text-[11px] uppercase tracking-[0.06em] text-muted">
          What to watch for
        </span>
        <textarea
          value={prompt}
          onChange={(e) => onPrompt(e.target.value)}
          rows={3}
          placeholder="e.g. watch my inbox for bills or payment reminders"
          className="mt-1 w-full resize-none rounded-2 border border-hairline bg-bg-2 px-3 py-2 text-sm text-ink outline-none focus:border-indigo focus:shadow-glow"
        />
      </label>

      <div className="block">
        <span className="text-[11px] uppercase tracking-[0.06em] text-muted">
          Data source
        </span>
        {loadingSources ? (
          <div className="mt-1 flex items-center gap-2 text-[12px] text-muted">
            <Loader2 className="h-3 w-3 animate-spin" strokeWidth={1.6} />
            Loading sources...
          </div>
        ) : sourceToolGroups.length === 0 ? (
          <p className="mt-1 text-[12px] text-muted">
            No data sources available. The watcher will use Brain
            context only.
          </p>
        ) : (
          <div className="mt-1.5 flex flex-wrap gap-1.5">
            {sourceToolGroups.flatMap((group) =>
              group.tools.map((t) => {
                const id = `${t.connector_id}:${t.tool_name}`;
                const on = sourceSet.has(id);
                return (
                  <button
                    type="button"
                    key={id}
                    onClick={() => onToggleSource(id)}
                    title={t.description}
                    className={`rounded-full border px-2.5 py-1 text-[11px] transition-colors ${
                      on
                        ? "border-indigo bg-indigo-soft text-indigo"
                        : "border-hairline text-muted hover:text-ink"
                    }`}
                  >
                    {group.connectorName}: {t.display_name}
                  </button>
                );
              }),
            )}
          </div>
        )}
      </div>

      {sourceTools.length > 0 && (
        <label className="flex items-center gap-2 text-[12px] text-ink">
          <input
            type="checkbox"
            checked={skipBackfill}
            onChange={(e) => onSkipBackfill(e.target.checked)}
          />
          Start from now (skip existing records)
        </label>
      )}

      <label className="block">
        <span className="text-[11px] uppercase tracking-[0.06em] text-muted">
          How often
        </span>
        <select
          value={
            WATCHER_SCHEDULES.some((p) => p.label === schedule)
              ? schedule
              : "custom"
          }
          onChange={(e) => {
            if (e.target.value === "custom") {
              onSchedule("custom");
            } else {
              onSchedule(e.target.value);
              const preset = WATCHER_SCHEDULES.find(
                (p) => p.label === e.target.value,
              );
              if (preset?.cron) onCustomCron(preset.cron);
            }
          }}
          className="mt-1 w-full rounded-2 border border-hairline bg-bg-2 px-3 py-2 text-sm text-ink outline-none focus:border-indigo focus:shadow-glow"
        >
          {WATCHER_SCHEDULES.map((p) => (
            <option key={p.label} value={p.label}>
              {p.label}
            </option>
          ))}
          <option value="custom">Custom cron</option>
        </select>
        {isCustom && (
          <input
            type="text"
            value={customCron}
            onChange={(e) => onCustomCron(e.target.value)}
            placeholder="min hour dom mon dow"
            className="mt-1.5 w-full rounded-2 border border-hairline bg-bg-2 px-3 py-2 font-mono text-xs text-muted outline-none focus:border-indigo focus:shadow-glow focus:text-ink"
          />
        )}
      </label>
    </div>
  );
}

// ── Step 2: Notify Where ─────────────────────────────────────────

function StepNotify({
  connectorGroups,
  deliveryTools,
  onToggle,
  loading,
}: {
  readonly connectorGroups: ReadonlyArray<{
    readonly connectorId: string;
    readonly connectorName: string;
    readonly tools: ReadonlyArray<McpToolEntry>;
  }>;
  readonly deliveryTools: ReadonlyArray<string>;
  readonly onToggle: (toolId: string) => void;
  readonly loading: boolean;
}): JSX.Element {
  const deliverySet = useMemo(
    () => new Set(deliveryTools),
    [deliveryTools],
  );

  return (
    <div className="space-y-3">
      <p className="text-xs text-muted">
        Pick where the watcher should send notifications. Results
        always appear on the dashboard; add delivery channels below
        for push notifications.
      </p>

      <div className="flex items-center gap-2 rounded-2 border border-indigo/30 bg-indigo-soft px-3 py-2 text-[12px] text-indigo">
        <CircleCheck className="h-3.5 w-3.5 shrink-0" strokeWidth={1.6} />
        Dashboard (always on)
      </div>

      {loading && (
        <div className="flex items-center gap-2 text-[12px] text-muted">
          <Loader2 className="h-3 w-3 animate-spin" strokeWidth={1.6} />
          Loading connectors...
        </div>
      )}

      {!loading && connectorGroups.length === 0 && (
        <p className="text-[12px] text-muted">
          No connectors configured. The watcher will post results to
          the dashboard only. You can add delivery channels later from
          the Agents page.
        </p>
      )}

      {!loading &&
        connectorGroups.map((group) => (
          <ConnectorDeliveryCard
            key={group.connectorId}
            group={group}
            deliverySet={deliverySet}
            onToggle={onToggle}
          />
        ))}
    </div>
  );
}

function ConnectorDeliveryCard({
  group,
  deliverySet,
  onToggle,
}: {
  readonly group: {
    readonly connectorId: string;
    readonly connectorName: string;
    readonly tools: ReadonlyArray<McpToolEntry>;
  };
  readonly deliverySet: ReadonlySet<string>;
  readonly onToggle: (toolId: string) => void;
}): JSX.Element {
  const [open, setOpen] = useState(() =>
    group.tools.some((t) =>
      deliverySet.has(`${t.connector_id}:${t.tool_name}`),
    ),
  );

  const selectedCount = group.tools.filter((t) =>
    deliverySet.has(`${t.connector_id}:${t.tool_name}`),
  ).length;

  return (
    <div className="rounded-2 border border-hairline bg-surface/30">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center justify-between gap-2 px-3 py-2 text-left hover:bg-surface/40"
      >
        <div className="flex items-center gap-2">
          <ChevronRight
            strokeWidth={1.6}
            size={12}
            className={`text-muted transition-transform ${open ? "rotate-90" : ""}`}
          />
          <span className="text-[12px] font-medium text-ink">
            {group.connectorName}
          </span>
        </div>
        {selectedCount > 0 && (
          <span className="rounded-full bg-indigo-soft px-2 py-0.5 text-[10px] text-indigo">
            {selectedCount} selected
          </span>
        )}
      </button>
      {open && (
        <div className="flex flex-wrap gap-1.5 border-t border-hairline/60 px-3 py-2">
          {group.tools.map((t) => {
            const id = `${t.connector_id}:${t.tool_name}`;
            const on = deliverySet.has(id);
            return (
              <button
                type="button"
                key={id}
                onClick={() => onToggle(id)}
                title={t.description}
                className={`rounded-full border px-2.5 py-0.5 text-[11px] transition-colors ${
                  on
                    ? "border-amber bg-amber/10 text-amber"
                    : "border-hairline text-muted hover:text-ink"
                }`}
              >
                {t.display_name}
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}

// ── Step 3: Access & Model ───────────────────────────────────────

function StepAccess({
  brainAccess,
  onBrainAccess,
  modelRoute,
  onModelRoute,
  modelOverride,
  onModelOverride,
  skills,
  enabledSkills,
  onToggleSkill,
}: {
  readonly brainAccess: boolean;
  readonly onBrainAccess: (v: boolean) => void;
  readonly modelRoute: string;
  readonly onModelRoute: (v: string) => void;
  readonly modelOverride: string;
  readonly onModelOverride: (v: string) => void;
  readonly skills: ReadonlyArray<SkillSummary>;
  readonly enabledSkills: ReadonlyArray<string>;
  readonly onToggleSkill: (id: string) => void;
}): JSX.Element {
  return (
    <div className="space-y-3">
      <p className="text-xs text-muted">
        Defaults work for most watchers. Adjust if you need to
        restrict data access or use a specific model.
      </p>

      <label className="flex items-center gap-2.5 rounded-2 border border-hairline px-3 py-2.5 text-[12px] text-ink">
        <input
          type="checkbox"
          checked={brainAccess}
          onChange={(e) => onBrainAccess(e.target.checked)}
        />
        <div>
          <div className="flex items-center gap-1.5 font-medium">
            <Brain className="h-3.5 w-3.5 text-indigo" strokeWidth={1.6} />
            Brain access
          </div>
          <div className="mt-0.5 text-[11px] text-muted">
            Let the watcher read your personal context (messages,
            calendar, notes).
          </div>
        </div>
      </label>

      <div className="grid grid-cols-2 gap-3">
        <label className="block">
          <span className="text-[11px] uppercase tracking-[0.06em] text-muted">
            Model route
          </span>
          <select
            value={modelRoute}
            onChange={(e) => onModelRoute(e.target.value)}
            className="mt-1 w-full rounded-2 border border-hairline bg-bg-2 px-3 py-2 text-[12px] text-ink outline-none focus:border-indigo focus:shadow-glow"
          >
            <option value="inherit">inherit (default)</option>
            <option value="local">local (Ollama)</option>
          </select>
        </label>
        <div className="block">
          <span className="text-[11px] uppercase tracking-[0.06em] text-muted">
            Model override
          </span>
          <div className="mt-1">
            <ModelPicker
              value={modelOverride}
              onChange={onModelOverride}
              route={modelRoute || "inherit"}
              placeholder="optional"
            />
          </div>
        </div>
      </div>

      {skills.length > 0 && (
        <fieldset className="rounded-2 border border-hairline p-2.5">
          <legend className="px-1 text-[11px] uppercase tracking-[0.06em] text-muted">
            Skills
          </legend>
          <div className="flex flex-wrap gap-1.5">
            {skills.map((s) => {
              const on = enabledSkills.includes(s.id);
              return (
                <button
                  type="button"
                  key={s.id}
                  onClick={() => onToggleSkill(s.id)}
                  className={`rounded-full border px-2.5 py-0.5 text-[11px] transition-colors ${
                    on
                      ? "border-indigo bg-indigo-soft text-indigo"
                      : "border-hairline text-muted hover:text-ink"
                  }`}
                >
                  {s.name}
                </button>
              );
            })}
          </div>
        </fieldset>
      )}
    </div>
  );
}

// ── Step 4: Review & Create ──────────────────────────────────────

function StepReview({
  name,
  prompt,
  schedule,
  resolvedCron,
  sourceTools,
  deliveryTools,
  brainAccess,
  modelRoute,
  modelOverride,
  enabledSkills,
  creationPhase,
  creationError,
  enhanceError,
  evalError,
  enhancedPrompt,
  evalCaseCount,
}: {
  readonly name: string;
  readonly prompt: string;
  readonly schedule: string;
  readonly resolvedCron: string;
  readonly sourceTools: ReadonlyArray<string>;
  readonly deliveryTools: ReadonlyArray<string>;
  readonly brainAccess: boolean;
  readonly modelRoute: string;
  readonly modelOverride: string;
  readonly enabledSkills: ReadonlyArray<string>;
  readonly creationPhase: CreationPhase;
  readonly creationError: string | null;
  readonly enhanceError: string | null;
  readonly evalError: string | null;
  readonly enhancedPrompt: string | null;
  readonly evalCaseCount: number | null;
}): JSX.Element {
  const isCustom = !WATCHER_SCHEDULES.some((p) => p.label === schedule);

  return (
    <div className="space-y-3">
      {creationPhase === "idle" && (
        <>
          <p className="text-xs text-muted">
            Review your watcher. On create, the prompt will be
            automatically enhanced and eval cases generated.
          </p>

          {/* Summary card */}
          <div className="space-y-2 rounded-2 border border-hairline bg-surface/30 px-3 py-2.5 text-[12px]">
            <SummaryRow label="Name" value={name} />
            <SummaryRow label="Watches for" value={prompt} />
            <SummaryRow
              label="Sources"
              value={
                sourceTools.length > 0
                  ? sourceTools
                      .map((id) => id.split(":").pop() ?? id)
                      .join(", ")
                  : "Brain only"
              }
            />
            <SummaryRow
              label="Schedule"
              value={isCustom ? `Custom (${resolvedCron})` : schedule}
            />
            <SummaryRow
              label="Notify via"
              value={
                deliveryTools.length > 0
                  ? `Dashboard + ${deliveryTools.length} channel${deliveryTools.length > 1 ? "s" : ""}`
                  : "Dashboard only"
              }
            />
            <SummaryRow
              label="Brain access"
              value={brainAccess ? "Yes" : "No"}
            />
            <SummaryRow
              label="Model"
              value={
                modelOverride
                  ? `${modelRoute} / ${modelOverride}`
                  : modelRoute
              }
            />
            {enabledSkills.length > 0 && (
              <SummaryRow
                label="Skills"
                value={enabledSkills.join(", ")}
              />
            )}
          </div>

          {/* What will happen */}
          <div className="rounded-2 border border-hairline/60 bg-bg-2/50 px-3 py-2.5 text-[11px] text-muted">
            <div className="font-medium text-ink">On create:</div>
            <ul className="mt-1 space-y-0.5">
              <li className="flex items-center gap-1.5">
                <Sparkles className="h-3 w-3 text-indigo" strokeWidth={1.6} />
                Enhance prompt with the prompt engineer
              </li>
              <li className="flex items-center gap-1.5">
                <CircleDot
                  className="h-3 w-3 text-indigo"
                  strokeWidth={1.6}
                />
                Create the watcher agent
              </li>
              <li className="flex items-center gap-1.5">
                <Zap className="h-3 w-3 text-indigo" strokeWidth={1.6} />
                Generate eval dataset automatically
              </li>
            </ul>
          </div>
        </>
      )}

      {/* Progress overlay */}
      {creationPhase !== "idle" && (
        <div className="space-y-2">
          <CreationStep
            label="Enhancing prompt"
            status={
              creationPhase === "enhancing"
                ? "running"
                : enhanceError
                  ? "error"
                  : enhancedPrompt
                    ? "done"
                    : "done"
            }
            detail={
              enhanceError
                ? "Skipped — using original prompt"
                : enhancedPrompt
                  ? "Prompt improved"
                  : undefined
            }
          />
          <CreationStep
            label="Creating agent"
            status={
              creationPhase === "enhancing"
                ? "pending"
                : creationPhase === "creating"
                  ? "running"
                  : creationPhase === "error"
                    ? "error"
                    : "done"
            }
          />
          <CreationStep
            label="Generating eval dataset — this may take a minute"
            status={
              creationPhase === "enhancing" ||
              creationPhase === "creating"
                ? "pending"
                : creationPhase === "evals"
                  ? "running"
                  : evalError
                    ? "error"
                    : creationPhase === "done"
                      ? "done"
                      : "pending"
            }
            detail={
              evalError
                ? "Skipped — generate manually from Agents page"
                : evalCaseCount !== null
                  ? `${evalCaseCount} cases created`
                  : undefined
            }
          />

          {creationPhase === "error" && creationError && (
            <div className="rounded-2 border border-amber/60 bg-amber/10 px-3 py-2 text-[12px] text-amber">
              {creationError}
            </div>
          )}

          {creationPhase === "done" && (
            <div className="flex items-center gap-2 rounded-2 border border-success/40 bg-success/10 px-3 py-2.5 text-[12px] text-success">
              <CircleCheck className="h-4 w-4" strokeWidth={1.6} />
              <span className="font-medium">
                Watcher "{name}" is live and scheduled.
                {enhanceError && " Prompt can be improved from the Edit page."}
              </span>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function SummaryRow({
  label,
  value,
}: {
  readonly label: string;
  readonly value: string;
}): JSX.Element {
  return (
    <div className="flex items-start gap-2">
      <span className="w-24 shrink-0 text-[11px] text-muted">
        {label}
      </span>
      <span className="text-ink">{value}</span>
    </div>
  );
}

function CreationStep({
  label,
  status,
  detail,
}: {
  readonly label: string;
  readonly status: "pending" | "running" | "done" | "error";
  readonly detail?: string;
}): JSX.Element {
  return (
    <div
      className={`flex items-center gap-2.5 rounded-2 border px-3 py-2 text-[12px] ${
        status === "running"
          ? "border-indigo/40 bg-indigo-soft text-indigo"
          : status === "done"
            ? "border-success/40 bg-success/10 text-success"
            : status === "error"
              ? "border-amber/40 bg-amber/10 text-amber"
              : "border-hairline text-muted"
      }`}
    >
      {status === "running" && (
        <Loader2 className="h-3.5 w-3.5 animate-spin" strokeWidth={1.6} />
      )}
      {status === "done" && (
        <Check className="h-3.5 w-3.5" strokeWidth={2} />
      )}
      {status === "error" && (
        <X className="h-3.5 w-3.5" strokeWidth={2} />
      )}
      {status === "pending" && (
        <CircleDot className="h-3.5 w-3.5 opacity-40" strokeWidth={1.6} />
      )}
      <div>
        <span>{label}</span>
        {detail && (
          <span className="ml-1.5 text-[11px] opacity-80">
            — {detail}
          </span>
        )}
      </div>
    </div>
  );
}

export default WatcherWizard;

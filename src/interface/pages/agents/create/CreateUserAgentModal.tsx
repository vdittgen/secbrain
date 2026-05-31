// Create-user-agent modal. Migrated from the legacy Agents.tsx — same
// behaviour, separate file to keep the page shell readable.
//
// sensitivity_tier: 1

import type { JSX } from "react";
import { useCallback, useMemo, useRef, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import {
  CircleCheck,
  Loader2,
  Plus,
  Sparkles,
  Wand2,
  X,
} from "lucide-react";

import { useAsyncData } from "../../../hooks/useAsyncData";
import { dedupInvoke } from "../../../utils/requestDedup";
import ModelPicker from "../../../components/ModelPicker";
import ModelSuggestionPanel from "../../../components/ModelSuggestionPanel";
import PromptEngineerModal from "../../../components/PromptEngineerModal";
import type {
  DatasetValidationResponse,
  McpActionToolListResponse,
  McpToolEntry,
  PydanticAgentRow,
  SkillSummary,
  UnsavedAgentSpec,
  UserAgentInput,
  UserAgentResponse,
} from "../../../types/agents";
import { ConnectorBindings } from "../ConnectorBindings";
import { SCHEDULE_PRESETS } from "../shared/constants";
import { SuggestDatasetModal } from "../shared/EvalDatasetPanel";

interface CreateUserAgentModalProps {
  readonly open: boolean;
  readonly onClose: () => void;
  readonly onCreated: () => void;
  readonly availableAgents: ReadonlyArray<PydanticAgentRow>;
}

export function CreateUserAgentModal({
  open,
  onClose,
  onCreated,
  availableAgents,
}: CreateUserAgentModalProps): JSX.Element | null {
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [systemPrompt, setSystemPrompt] = useState(
    "You are a helpful assistant.\n",
  );
  const [modelRoute, setModelRoute] = useState("inherit");
  const [modelOverride, setModelOverride] = useState("");
  const [brainAccess, setBrainAccess] = useState(true);
  const [maxTier, setMaxTier] = useState(2);
  const [enabledSkills, setEnabledSkills] = useState<string[]>([]);
  const [enabledMcpTools, setEnabledMcpTools] = useState<string[]>([]);
  const [deliveryTools, setDeliveryTools] = useState<string[]>([]);
  const [schedule, setSchedule] = useState<string>("Off");
  const [pattern, setPattern] = useState<"single" | "orchestrator">("single");
  const [subagents, setSubagents] = useState<string[]>([]);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [suggestModalOpen, setSuggestModalOpen] = useState(false);
  const [stashedDatasetYaml, setStashedDatasetYaml] = useState<string | null>(
    null,
  );
  const [promptEngineerOpen, setPromptEngineerOpen] = useState(false);
  const [promptOfferOpen, setPromptOfferOpen] = useState(false);
  const promptOfferSkippedRef = useRef(false);

  const eligibleSubagents = useMemo(
    () =>
      availableAgents
        .filter((a) => a.pattern === "single")
        .slice()
        .sort((a, b) => a.name.localeCompare(b.name)),
    [availableAgents],
  );

  const skillsData = useAsyncData(useCallback(
    () => dedupInvoke<ReadonlyArray<SkillSummary>>("list_skills_v2"),
    [],
  ));
  const toolsData = useAsyncData(useCallback(
    () => dedupInvoke<McpActionToolListResponse>("list_mcp_action_tools"),
    [],
  ));

  const unsavedSpec: UnsavedAgentSpec = useMemo(() => ({
    name: name.trim(),
    description: description.trim(),
    system_prompt: systemPrompt,
    max_sensitivity_tier: maxTier,
  }), [name, description, systemPrompt, maxTier]);

  const handleSuggestionAccepted = useCallback((yamlContent: string) => {
    setStashedDatasetYaml(yamlContent);
    setSuggestModalOpen(false);
  }, []);

  const proceedCreate = useCallback(async () => {
    setSaving(true);
    setError(null);
    try {
      const cron = SCHEDULE_PRESETS.find((p) => p.label === schedule)?.cron
        ?? null;
      const input: UserAgentInput = {
        name: name.trim(),
        description: description.trim(),
        system_prompt: systemPrompt,
        model_route: modelRoute,
        model_override: modelOverride.trim() ? modelOverride.trim() : null,
        enabled_skills: enabledSkills,
        enabled_mcp_tools: enabledMcpTools,
        brain_access: brainAccess,
        max_sensitivity_tier: maxTier,
        schedule_cron: cron,
        schedule_enabled: schedule !== "Off",
        pattern,
        subagents: pattern === "orchestrator" ? subagents : [],
        delivery_tools: deliveryTools,
      };
      const created = await invoke<UserAgentResponse>(
        "create_user_agent",
        { input },
      );
      if (stashedDatasetYaml && created.agent?.agent_id) {
        try {
          await invoke<DatasetValidationResponse>(
            "upload_user_eval_dataset",
            { agentId: created.agent.agent_id, content: stashedDatasetYaml },
          );
        } catch (e: unknown) {
          setError(
            "Agent created, but dataset upload failed: "
              + (e instanceof Error ? e.message : String(e)),
          );
        }
      }
      onCreated();
      onClose();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  }, [
    name, description, systemPrompt, modelRoute, modelOverride, brainAccess,
    maxTier, enabledSkills, enabledMcpTools, deliveryTools, schedule,
    stashedDatasetYaml, pattern, subagents, onCreated, onClose,
  ]);

  const submit = useCallback(() => {
    if (promptOfferSkippedRef.current) {
      void proceedCreate();
      return;
    }
    setPromptOfferOpen(true);
  }, [proceedCreate]);

  if (!open) return null;

  const tools: ReadonlyArray<McpToolEntry> = toolsData.data?.tools ?? [];
  const skills: ReadonlyArray<SkillSummary> = skillsData.data ?? [];

  return (
    <div className="fixed inset-0 z-40 flex items-center justify-center bg-black/40 p-4">
      <div className="flex max-h-full w-full max-w-2xl flex-col rounded-4 border border-hairline bg-surface shadow-xl">
        <div className="flex items-center justify-between border-b border-hairline px-5 py-3">
          <h2 className="text-base font-semibold text-ink">
            New user agent
          </h2>
          <button
            type="button"
            onClick={onClose}
            className="rounded-md p-1 text-muted hover:bg-surface"
          >
            <X size={14} />
          </button>
        </div>
        <div className="flex-1 space-y-3 overflow-auto px-5 py-4">
          <label className="block">
            <span className="text-[11px] text-muted">Name *</span>
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="My Research Assistant"
              className="mt-1 w-full rounded-md border border-hairline bg-surface px-2 py-1.5 text-[12px] text-ink"
            />
          </label>
          <label className="block">
            <span className="text-[11px] text-muted">Description</span>
            <input
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="What does this agent do?"
              className="mt-1 w-full rounded-md border border-hairline bg-surface px-2 py-1.5 text-[12px] text-ink"
            />
          </label>
          <div className="block">
            <span className="text-[11px] text-muted">Pattern</span>
            <div className="mt-1 inline-flex overflow-hidden rounded-md border border-hairline">
              {(["single", "orchestrator"] as const).map((p) => {
                const active = pattern === p;
                return (
                  <button
                    key={p}
                    type="button"
                    onClick={() => setPattern(p)}
                    className={
                      "px-3 py-1 text-[12px] capitalize "
                      + (active
                        ? "bg-indigo text-white"
                        : "bg-surface text-muted hover:text-ink")
                    }
                  >
                    {p}
                  </button>
                );
              })}
            </div>
            <p className="mt-1 text-[11px] text-muted">
              {pattern === "single"
                ? "Plain agent. Calls skills, MCP tools, and (optionally) Brain context."
                : "Orchestrator. Picks among the sub-agents you select to assemble its answer."}
            </p>
          </div>
          <div>
            <div className="flex items-center justify-between">
              <span className="text-[11px] text-muted">
                System prompt *
              </span>
              <button
                type="button"
                onClick={() => setPromptEngineerOpen(true)}
                disabled={!name.trim() || !systemPrompt.trim()}
                className="inline-flex items-center gap-1 rounded-md border border-indigo/60 px-2 py-0.5 text-[11px] text-indigo hover:bg-indigo-soft disabled:opacity-50"
              >
                <Sparkles size={11} />
                Improve prompts
              </button>
            </div>
            <textarea
              value={systemPrompt}
              onChange={(e) => setSystemPrompt(e.target.value)}
              spellCheck={false}
              className="mt-1 h-36 w-full resize-y rounded-md border border-hairline bg-surface p-2 font-mono text-[12px] text-ink/90"
            />
          </div>
          <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
            <label className="block">
              <span className="text-[11px] text-muted">Model route</span>
              <select
                value={modelRoute}
                onChange={(e) => setModelRoute(e.target.value)}
                className="mt-1 w-full rounded-md border border-hairline bg-surface px-2 py-1.5 text-[12px] text-ink"
              >
                <option value="inherit">inherit (global default)</option>
                <option value="local">local (Ollama)</option>
              </select>
            </label>
            <div className="block">
              <span className="text-[11px] text-muted">Model override</span>
              <div className="mt-1">
                <ModelPicker
                  value={modelOverride}
                  onChange={setModelOverride}
                  route={modelRoute || "inherit"}
                  placeholder="optional"
                />
              </div>
            </div>
          </div>
          <ModelSuggestionPanel
            spec={{
              name,
              description,
              system_prompt: systemPrompt,
              max_sensitivity_tier: maxTier,
              enabled_skills: enabledSkills,
              enabled_mcp_tools: enabledMcpTools,
            }}
            onApply={(option) => {
              setModelRoute(option.route);
              setModelOverride(option.model_id);
            }}
          />
          <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
            <label className="flex items-center gap-2 text-[12px] text-ink">
              <input
                type="checkbox"
                checked={brainAccess}
                onChange={(e) => setBrainAccess(e.target.checked)}
              />
              Allow Brain recall (read personal context)
            </label>
            <label className="block">
              <span className="text-[11px] text-muted">
                Max sensitivity tier
              </span>
              <select
                value={maxTier}
                onChange={(e) => setMaxTier(Number(e.target.value))}
                className="mt-1 w-full rounded-md border border-hairline bg-surface px-2 py-1.5 text-[12px] text-ink"
              >
                <option value={1}>1 — preferences only</option>
                <option value={2}>2 — habits / names / schedule</option>
                <option value={3}>3 — health / finance / emotions</option>
              </select>
            </label>
          </div>
          <fieldset className="rounded-md border border-hairline p-2">
            <legend className="px-1 text-[11px] text-muted">Skills</legend>
            {skills.length === 0
              ? <span className="text-[11px] text-muted">No skills registered.</span>
              : (
                <div className="flex flex-wrap gap-2">
                  {skills.map((s) => {
                    const on = enabledSkills.includes(s.id);
                    return (
                      <button
                        type="button"
                        key={s.id}
                        onClick={() =>
                          setEnabledSkills((prev) =>
                            on ? prev.filter((x) => x !== s.id) : [...prev, s.id]
                          )}
                        className={`rounded-full border px-2 py-0.5 text-[11px] ${on ? "border-indigo bg-indigo-soft text-indigo" : "border-hairline text-muted"}`}
                      >
                        {s.name}
                      </button>
                    );
                  })}
                </div>
              )}
          </fieldset>
          <fieldset className="rounded-md border border-hairline p-2">
            <legend className="px-1 text-[11px] text-muted">
              Connectors
            </legend>
            <ConnectorBindings
              availableTools={tools}
              enabledTools={enabledMcpTools}
              deliveryTools={deliveryTools}
              onChange={(next) => {
                setEnabledMcpTools([...next.enabledTools]);
                setDeliveryTools([...next.deliveryTools]);
              }}
            />
          </fieldset>
          {pattern === "orchestrator" && (
            <fieldset className="rounded-md border border-hairline p-2">
              <legend className="px-1 text-[11px] text-muted">
                Sub-agents *
              </legend>
              {eligibleSubagents.length === 0
                ? (
                  <span className="text-[11px] text-muted">
                    No eligible sub-agents — create at least one
                    single-pattern agent first.
                  </span>
                )
                : (
                  <div className="flex flex-wrap gap-2">
                    {eligibleSubagents.map((sub) => {
                      const on = subagents.includes(sub.agent_id);
                      return (
                        <button
                          type="button"
                          key={sub.agent_id}
                          onClick={() =>
                            setSubagents((prev) =>
                              on
                                ? prev.filter((id) => id !== sub.agent_id)
                                : [...prev, sub.agent_id]
                            )}
                          className={
                            "rounded-full border px-2 py-0.5 text-[11px] "
                            + (on
                              ? "border-indigo bg-indigo-soft text-indigo"
                              : "border-hairline text-muted")
                          }
                          title={sub.description || sub.agent_id}
                        >
                          {sub.name}
                          <span className="ml-1 text-[10px] opacity-60">
                            ({sub.agent_id})
                          </span>
                        </button>
                      );
                    })}
                  </div>
                )}
              {subagents.length === 0 && eligibleSubagents.length > 0 && (
                <p className="mt-1 text-[11px] text-amber">
                  Pick at least one sub-agent.
                </p>
              )}
            </fieldset>
          )}
          <label className="block">
            <span className="text-[11px] text-muted">Schedule</span>
            <select
              value={schedule}
              onChange={(e) => setSchedule(e.target.value)}
              className="mt-1 w-full rounded-md border border-hairline bg-surface px-2 py-1.5 text-[12px] text-ink"
            >
              {SCHEDULE_PRESETS.map((p) => (
                <option key={p.label} value={p.label}>{p.label}</option>
              ))}
            </select>
          </label>
          <div className="rounded-md border border-hairline bg-surface/30 px-3 py-2 text-[12px]">
            <div className="flex items-center justify-between gap-2">
              <div>
                <div className="text-ink">Starter eval dataset</div>
                <div className="text-[11px] text-muted">
                  Optional. The Dataset Creator reads your name,
                  description, and prompt to propose cases the agent must
                  pass.
                </div>
              </div>
              <button
                type="button"
                disabled={
                  !unsavedSpec.name || !unsavedSpec.system_prompt.trim()
                }
                onClick={() => setSuggestModalOpen(true)}
                className="inline-flex items-center gap-1 rounded-md border border-indigo/60 px-2.5 py-1 text-[11px] text-indigo hover:bg-indigo-soft disabled:opacity-50"
              >
                <Wand2 size={11} />
                {stashedDatasetYaml ? "Re-suggest" : "Suggest dataset"}
              </button>
            </div>
            {stashedDatasetYaml && (
              <div className="mt-1 flex items-center gap-2 text-[11px] text-success">
                <CircleCheck size={11} />
                Dataset prepared — will be saved with the agent.
                <button
                  type="button"
                  onClick={() => setStashedDatasetYaml(null)}
                  className="ml-1 text-muted hover:text-ink"
                >
                  (discard)
                </button>
              </div>
            )}
          </div>
          {error && (
            <div className="rounded-md border border-amber/60 bg-amber/10 px-3 py-2 text-[12px] text-amber">
              {error}
            </div>
          )}
        </div>
        <div className="flex items-center justify-end gap-2 border-t border-hairline px-5 py-3">
          <button
            type="button"
            onClick={onClose}
            className="rounded-md border border-hairline px-3 py-1.5 text-[12px] text-muted hover:bg-surface"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={submit}
            disabled={
              saving
              || !name.trim()
              || !systemPrompt.trim()
              || (pattern === "orchestrator" && subagents.length === 0)
            }
            className="inline-flex items-center gap-1 rounded-md bg-indigo px-3 py-1.5 text-[12px] text-white hover:bg-indigo/90 disabled:opacity-50"
          >
            {saving
              ? <Loader2 size={12} className="animate-spin" />
              : <Plus size={12} />}
            Create agent
          </button>
        </div>
      </div>
      {suggestModalOpen && (
        <SuggestDatasetModal
          agentId={null}
          appending={false}
          unsavedSpec={unsavedSpec}
          onClose={() => setSuggestModalOpen(false)}
          onAccepted={handleSuggestionAccepted}
          onApplyPromptAdditions={(text) => {
            setSystemPrompt((prev) => {
              const base = prev.trimEnd();
              const sep = base.endsWith(".") || base === "" ? "\n" : "\n";
              return `${base}${sep}\n${text}\n`;
            });
          }}
        />
      )}
      {promptEngineerOpen && (
        <PromptEngineerModal
          agentId={null}
          currentName={name}
          currentDescription={description}
          currentSystemPrompt={systemPrompt}
          currentMaxTier={maxTier}
          availableSkills={enabledSkills}
          enabledMcpTools={enabledMcpTools}
          hasDataset={Boolean(stashedDatasetYaml)}
          onClose={() => {
            setPromptEngineerOpen(false);
            promptOfferSkippedRef.current = true;
          }}
          onApplyRewrite={(p, d) => {
            setSystemPrompt(p);
            setDescription(d);
            setPromptEngineerOpen(false);
            promptOfferSkippedRef.current = true;
          }}
          onApplyAdditions={(text) => {
            setSystemPrompt((prev) => {
              const base = prev.trimEnd();
              return `${base}\n\n${text}\n`;
            });
            setPromptEngineerOpen(false);
            promptOfferSkippedRef.current = true;
          }}
        />
      )}
      {promptOfferOpen && (
        <OfferImproveDialog
          onSkip={() => {
            promptOfferSkippedRef.current = true;
            setPromptOfferOpen(false);
            void proceedCreate();
          }}
          onAccept={() => {
            setPromptOfferOpen(false);
            setPromptEngineerOpen(true);
          }}
        />
      )}
    </div>
  );
}

function OfferImproveDialog({
  onSkip,
  onAccept,
}: {
  readonly onSkip: () => void;
  readonly onAccept: () => void;
}): JSX.Element {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
      <div className="w-full max-w-md rounded-4 border border-hairline bg-surface p-5 shadow-xl">
        <div className="flex items-center gap-2 text-sm font-medium text-ink">
          <Sparkles size={14} className="text-indigo" />
          Improve prompts first?
        </div>
        <p className="mt-2 text-[12px] text-muted">
          Our prompt engineer can rewrite this agent's system prompt and
          description for clarity, expected output, language pinning,
          format strictness, and scope. You can review the diff and
          accept or skip.
        </p>
        <div className="mt-4 flex items-center justify-end gap-2">
          <button
            type="button"
            onClick={onSkip}
            className="rounded-md border border-hairline px-3 py-1.5 text-[12px] text-muted hover:bg-surface"
          >
            Skip — create as-is
          </button>
          <button
            type="button"
            onClick={onAccept}
            className="inline-flex items-center gap-1 rounded-md bg-indigo px-3 py-1.5 text-[12px] text-white hover:bg-indigo/90"
          >
            <Sparkles size={12} />
            Yes, improve first
          </button>
        </div>
      </div>
    </div>
  );
}

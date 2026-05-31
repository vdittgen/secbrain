// Edit mode — user-agent only. Renders identity, model, connectors,
// schedule, and advanced sections. State is owned by `useAgentDraft`
// in the parent so the persistent SaveBar can pick it up.
//
// sensitivity_tier: 1

import type { JSX } from "react";
import { useCallback, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import { Loader2, Sparkles, Undo2 } from "lucide-react";

import { Zap } from "lucide-react";
import { useAsyncData } from "../../../hooks/useAsyncData";
import { dedupInvoke } from "../../../utils/requestDedup";
import ModelPicker from "../../../components/ModelPicker";
import ModelSuggestionPanel from "../../../components/ModelSuggestionPanel";
import type {
  McpActionToolListResponse,
  McpToolEntry,
  PydanticAgentRow,
  SkillSummary,
  UserAgentResponse,
} from "../../../types/agents";
import { ConnectorBindings } from "../ConnectorBindings";
import type { UseAgentDraft } from "../hooks/useAgentDraft";

interface EditPaneProps {
  readonly row: PydanticAgentRow;
  readonly draft: UseAgentDraft;
  readonly onChanged: () => void;
  readonly onOpenPromptEngineer: () => void;
}

export function EditPane({
  row,
  draft,
  onChanged,
  onOpenPromptEngineer,
}: EditPaneProps): JSX.Element {
  const [reverting, setReverting] = useState(false);
  const [confirmRevert, setConfirmRevert] = useState(false);
  const [revertError, setRevertError] = useState<string | null>(null);
  const revertAvailable = Boolean(
    row.pre_ai_system_prompt || row.pre_ai_description,
  );

  const toolsData = useAsyncData(useCallback(
    () => dedupInvoke<McpActionToolListResponse>("list_mcp_action_tools"),
    [],
  ));
  const availableTools: ReadonlyArray<McpToolEntry> =
    toolsData.data?.tools ?? [];

  const skillsData = useAsyncData(useCallback(
    () => dedupInvoke<ReadonlyArray<SkillSummary>>("list_skills_v2"),
    [],
  ));
  const availableSkills: ReadonlyArray<SkillSummary> = skillsData.data ?? [];

  // Two-step inline confirm — window.confirm() is unreliable in the Tauri
  // v2 webview without the dialog plugin.
  const revertAiEdit = useCallback(async () => {
    if (!confirmRevert) {
      setConfirmRevert(true);
      return;
    }
    setConfirmRevert(false);
    setReverting(true);
    setRevertError(null);
    try {
      const resp = await invoke<UserAgentResponse>(
        "revert_user_agent_ai_edit",
        { agentId: row.agent_id },
      );
      draft.setPrompt(resp.agent.config.system_prompt);
      onChanged();
    } catch (e: unknown) {
      setRevertError(e instanceof Error ? e.message : String(e));
    } finally {
      setReverting(false);
    }
  }, [row.agent_id, draft, onChanged, confirmRevert]);

  return (
    <div className="space-y-4">
      <section className="rounded-md border border-hairline bg-surface p-3">
        <SectionHeader title="Identity & behaviour">
          <div className="flex items-center gap-1">
            {revertAvailable && (
              <button
                type="button"
                onClick={revertAiEdit}
                onBlur={() => setConfirmRevert(false)}
                disabled={reverting}
                title={
                  confirmRevert
                    ? "Click again to confirm"
                    : "Restore the prompt + description as they were before the most recent prompt-engineer apply."
                }
                className={`inline-flex items-center gap-1 rounded-md px-2 py-0.5 text-[11px] disabled:opacity-50 ${
                  confirmRevert
                    ? "border border-danger/60 bg-danger/10 text-danger"
                    : "border border-hairline text-muted hover:bg-surface"
                }`}
              >
                {reverting
                  ? <Loader2 size={11} className="animate-spin" />
                  : <Undo2 size={11} />}
                {confirmRevert ? "Click again to confirm" : "Revert AI edits"}
              </button>
            )}
            <button
              type="button"
              onClick={onOpenPromptEngineer}
              className="inline-flex items-center gap-1 rounded-md border border-indigo/60 px-2 py-0.5 text-[11px] text-indigo hover:bg-indigo-soft"
            >
              <Sparkles size={11} />
              Improve prompts
            </button>
          </div>
        </SectionHeader>
        <label className="mt-2 block">
          <span className="text-[11px] text-muted">System prompt</span>
          <textarea
            className="mt-1 h-48 w-full resize-y rounded-md border border-hairline bg-surface p-2 font-mono text-[12px] text-ink/90 focus:border-indigo focus:outline-none"
            value={draft.draft.prompt}
            onChange={(e) => draft.setPrompt(e.target.value)}
            spellCheck={false}
          />
        </label>
        {revertError && (
          <div className="mt-2 rounded-md border border-amber/60 bg-amber/10 px-3 py-2 text-[11px] text-amber">
            {revertError}
          </div>
        )}
      </section>

      <section className="rounded-md border border-hairline bg-surface p-3">
        <SectionHeader title="Model" />
        <div className="mt-2 grid grid-cols-1 gap-3 md:grid-cols-2">
          <label className="block">
            <span className="text-[11px] text-muted">Route</span>
            <select
              value={draft.draft.modelRoute}
              onChange={(e) => draft.setModelRoute(e.target.value)}
              className="mt-1 w-full rounded-md border border-hairline bg-surface px-2 py-1.5 text-[12px] text-ink"
            >
              <option value="inherit">inherit (global default)</option>
              <option value="local">local (Ollama)</option>
            </select>
          </label>
          <div className="block">
            <span className="text-[11px] text-muted">
              Model override (optional)
            </span>
            <div className="mt-1">
              <ModelPicker
                value={draft.draft.modelOverride}
                onChange={draft.setModelOverride}
                route={draft.draft.modelRoute || "inherit"}
                placeholder="e.g. llama3.1:70b"
              />
            </div>
          </div>
        </div>
        <div className="mt-2 text-[11px] text-muted">
          Resolved model:
          <span className="ml-2 font-mono text-ink/90">
            {row.config.resolved_model ?? "default"}
          </span>
          <span className="ml-2 text-muted/80">
            (used for runs and evals)
          </span>
        </div>
        <div className="mt-3">
          <ModelSuggestionPanel
            spec={{
              name: row.name,
              description: row.description,
              system_prompt: draft.draft.prompt,
              max_sensitivity_tier: row.max_sensitivity_tier,
              output_schema: row.output_schema || null,
              enabled_skills: row.config.enabled_skills,
              enabled_mcp_tools: row.config.enabled_tools,
              agent_id: row.agent_id,
            }}
            onApply={(option) => {
              draft.setModelRoute(option.route);
              draft.setModelOverride(option.model_id);
            }}
          />
        </div>
      </section>

      <section className="rounded-md border border-hairline bg-surface p-3">
        <SectionHeader title="Connectors" />
        <p className="mt-1 text-[11px] text-muted">
          Bind MCP tools to one or more roles. Selections persist with
          this agent's other edits.
        </p>
        <div className="mt-2">
          <ConnectorBindings
            availableTools={availableTools}
            enabledTools={draft.draft.enabledTools}
            deliveryTools={draft.draft.deliveryTools}
            onChange={(next) => {
              draft.setEnabledTools(next.enabledTools);
              draft.setDeliveryTools(next.deliveryTools);
            }}
          />
        </div>
      </section>

      <section className="rounded-md border border-hairline bg-surface p-3">
        <SectionHeader title="Skills" />
        <p className="mt-1 text-[11px] text-muted">
          Enable skills to give this agent procedural knowledge.
          The agent will see a skill menu and can load instructions on demand.
        </p>
        <div className="mt-2 flex flex-wrap gap-2">
          {availableSkills.length === 0 ? (
            <span className="text-[11px] text-muted">No skills installed.</span>
          ) : (
            availableSkills.map((s) => {
              const on = draft.draft.enabledSkills.includes(s.id);
              return (
                <button
                  type="button"
                  key={s.id}
                  onClick={() =>
                    draft.setEnabledSkills(
                      on
                        ? draft.draft.enabledSkills.filter((x) => x !== s.id)
                        : [...draft.draft.enabledSkills, s.id],
                    )}
                  className={`inline-flex items-center gap-1 rounded-full border px-2.5 py-1 text-[11px] transition-colors ${
                    on
                      ? "border-indigo bg-indigo-soft text-indigo"
                      : "border-hairline text-muted hover:border-indigo/40 hover:text-ink"
                  }`}
                >
                  <Zap className="h-3 w-3" />
                  {s.name}
                </button>
              );
            })
          )}
        </div>
      </section>

      {draft.error && (
        <div className="rounded-md border border-amber/60 bg-amber/10 px-3 py-2 text-[12px] text-amber">
          {draft.error}
        </div>
      )}
    </div>
  );
}

function SectionHeader({
  title,
  children,
}: {
  readonly title: string;
  readonly children?: JSX.Element;
}): JSX.Element {
  return (
    <div className="flex items-center justify-between gap-3">
      <div className="text-[12px] font-medium uppercase tracking-wide text-muted">
        {title}
      </div>
      {children}
    </div>
  );
}

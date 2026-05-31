// Detail pane (right column). Owns:
//   - mode tab state (overview / edit / evals / architecture)
//   - the user-agent edit draft (via useAgentDraft)
//   - the save-flow gates (PromptEngineerModal + ModelChangeEvalModal)
//   - the persistent SaveBar
//
// sensitivity_tier: 1

import type { JSX } from "react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import { Eye, Network, Pencil, ScrollText } from "lucide-react";

import ModelChangeEvalModal from "../../../components/ModelChangeEvalModal";
import PromptEngineerModal from "../../../components/PromptEngineerModal";
import type {
  PydanticAgentRow,
  UserAgentResponse,
} from "../../../types/agents";
import { useAgentDraft } from "../hooks/useAgentDraft";
import { useAgentEval } from "../hooks/useAgentEval";
import { isUserAgent } from "../shared/utils";
import { DetailHeader } from "./DetailHeader";
import { SaveBar } from "./SaveBar";
import { OverviewPane } from "./OverviewPane";
import { EditPane } from "./EditPane";
import { EvalsAndRunsPane } from "./EvalsAndRunsPane";
import { ArchitecturePane } from "./ArchitecturePane";

export type DetailMode = "overview" | "edit" | "evals" | "architecture";

interface AgentDetailPaneProps {
  readonly row: PydanticAgentRow;
  readonly allAgents: ReadonlyArray<PydanticAgentRow>;
  readonly refreshKey: number;
  readonly mode: DetailMode;
  readonly onModeChange: (mode: DetailMode) => void;
  readonly onChanged: () => void;
  readonly onDeleted: () => void;
}

export function AgentDetailPane({
  row,
  allAgents,
  refreshKey,
  mode,
  onModeChange,
  onChanged,
  onDeleted,
}: AgentDetailPaneProps): JSX.Element {
  const evalStatus = useAgentEval(row.agent_id, refreshKey);
  const draft = useAgentDraft(row, onChanged, () => void evalStatus.poll());

  const [promptEngineerOpen, setPromptEngineerOpen] = useState(false);
  const [modelEvalOpen, setModelEvalOpen] = useState(false);
  const pendingSaveAfterEngineerRef = useRef(false);

  const isUser = isUserAgent(row);
  const isOrchestrator =
    row.pattern === "orchestrator" || row.pattern === "deep";

  // Hide modes that don't apply to this row.
  const modes = useMemo(() => {
    const items: ReadonlyArray<{
      key: DetailMode;
      label: string;
      icon: JSX.Element;
      hidden?: boolean;
      disabled?: boolean;
      disabledReason?: string;
    }> = [
      { key: "overview", label: "Overview", icon: <Eye size={12} /> },
      {
        key: "edit",
        label: "Edit",
        icon: <Pencil size={12} />,
        disabled: !isUser,
        disabledReason: "Built-in and locked agents are read-only on this page.",
      },
      { key: "evals", label: "Evals & runs", icon: <ScrollText size={12} /> },
      {
        key: "architecture",
        label: "Architecture",
        icon: <Network size={12} />,
        hidden: !isOrchestrator,
      },
    ];
    return items.filter((m) => !m.hidden);
  }, [isUser, isOrchestrator]);

  // If we're in a mode that's no longer valid for the selected agent,
  // fall back to overview.
  useEffect(() => {
    const current = modes.find((m) => m.key === mode);
    if (!current || current.disabled) onModeChange("overview");
  }, [mode, modes, onModeChange]);

  const handleSaveClick = useCallback(() => {
    if (!draft.dirty) return;
    const gate = draft.decideGate();
    if (gate.kind === "model_change_eval") {
      setModelEvalOpen(true);
      return;
    }
    if (gate.kind === "prompt_engineer") {
      pendingSaveAfterEngineerRef.current = true;
      setPromptEngineerOpen(true);
      return;
    }
    void draft.commit();
  }, [draft]);

  const handleDiscard = useCallback(() => {
    draft.reset(row);
  }, [draft, row]);

  const applyPromptEngineerRewrite = useCallback(async (
    newSystemPrompt: string,
    newDescription: string,
  ) => {
    try {
      await invoke<UserAgentResponse>("apply_prompt_engineer_edit", {
        agentId: row.agent_id,
        systemPrompt: newSystemPrompt,
        description: newDescription,
      });
      draft.setPrompt(newSystemPrompt);
      draft.skipPromptOffer();
      setPromptEngineerOpen(false);
      onChanged();
      void evalStatus.poll();
    } catch (e: unknown) {
      // surface via draft.error by re-throwing isn't possible; show alert
      window.alert(
        "Failed to apply prompt rewrite: "
          + (e instanceof Error ? e.message : String(e)),
      );
    }
  }, [row.agent_id, draft, onChanged, evalStatus]);

  const applyPromptEngineerAdditions = useCallback(async (
    appendedText: string,
  ) => {
    const trimmed = appendedText.trim();
    if (!trimmed) return;
    const combined =
      draft.draft.prompt.replace(/\s+$/u, "") + "\n\n" + trimmed + "\n";
    await applyPromptEngineerRewrite(combined, row.description);
  }, [draft.draft.prompt, row.description, applyPromptEngineerRewrite]);

  return (
    <div className="flex h-full flex-col overflow-hidden">
      <DetailHeader
        row={row}
        onRefresh={onChanged}
        onDeleted={onDeleted}
      />
      <div className="flex shrink-0 items-center gap-1 border-b border-hairline bg-surface/40 px-2">
        {modes.map((m) => {
          const active = m.key === mode;
          const disabled = m.disabled;
          return (
            <button
              key={m.key}
              type="button"
              role="tab"
              aria-selected={active}
              disabled={disabled}
              onClick={() => onModeChange(m.key)}
              title={disabled ? m.disabledReason : undefined}
              className={[
                "inline-flex items-center gap-1.5 border-b-2 px-3 py-2 text-[12px] transition-colors",
                active
                  ? "border-indigo text-ink"
                  : "border-transparent text-muted hover:text-ink",
                disabled ? "cursor-not-allowed opacity-50" : "",
              ].join(" ")}
            >
              {m.icon}
              {m.label}
            </button>
          );
        })}
      </div>
      <div className="flex-1 overflow-auto px-4 py-4">
        {mode === "overview" && (
          <OverviewPane
            row={row}
            refreshKey={refreshKey}
            onChanged={onChanged}
          />
        )}
        {mode === "edit" && isUser && (
          <EditPane
            row={row}
            draft={draft}
            onChanged={onChanged}
            onOpenPromptEngineer={() => setPromptEngineerOpen(true)}
          />
        )}
        {mode === "evals" && (
          <EvalsAndRunsPane
            row={row}
            refreshKey={refreshKey}
            onChanged={onChanged}
          />
        )}
        {mode === "architecture" && (
          <ArchitecturePane row={row} allAgents={allAgents} />
        )}
      </div>
      {mode === "edit" && isUser && (
        <SaveBar
          dirty={draft.dirty}
          dirtyCount={draft.dirtyCount}
          saving={draft.saving}
          onDiscard={handleDiscard}
          onSave={handleSaveClick}
        />
      )}
      {promptEngineerOpen && (
        <PromptEngineerModal
          agentId={row.agent_id}
          currentName={row.name}
          currentDescription={row.description}
          currentSystemPrompt={draft.draft.prompt}
          currentMaxTier={row.max_sensitivity_tier}
          availableTools={row.available_tools}
          availableSkills={row.available_skills}
          enabledMcpTools={row.config.enabled_tools}
          hasDataset={Boolean(
            evalStatus.run
              && evalStatus.run.cases_total > 0
              && evalStatus.run.status !== "skipped",
          )}
          onClose={() => {
            setPromptEngineerOpen(false);
            if (pendingSaveAfterEngineerRef.current) {
              pendingSaveAfterEngineerRef.current = false;
              draft.skipPromptOffer();
              void draft.commit();
            }
          }}
          onApplyRewrite={(p, d) => void applyPromptEngineerRewrite(p, d)}
          onApplyAdditions={(text) =>
            void applyPromptEngineerAdditions(text)}
        />
      )}
      {modelEvalOpen && (
        <ModelChangeEvalModal
          agentId={row.agent_id}
          agentName={row.name}
          proposedOverride={draft.normalisedOverride}
          proposedRoute={
            draft.draft.modelRoute === "remote"
              || draft.draft.modelRoute === "local"
              ? draft.draft.modelRoute
              : undefined
          }
          currentOverride={row.config.model_override}
          hasDataset={Boolean(
            evalStatus.run
              && evalStatus.run.cases_total > 0
              && evalStatus.run.status !== "skipped",
          )}
          datasetCaseCount={evalStatus.run ? evalStatus.run.cases_total : null}
          onConfirmed={async (finalOverride, finalRoute) => {
            await draft.commit(finalOverride, finalRoute);
            setModelEvalOpen(false);
          }}
          onClose={() => setModelEvalOpen(false)}
          pickerSpec={{
            name: row.name,
            description: row.description,
            system_prompt: draft.draft.prompt,
            max_sensitivity_tier: row.max_sensitivity_tier,
            output_schema: row.output_schema || null,
            enabled_skills: row.config.enabled_skills,
            enabled_mcp_tools: row.config.enabled_tools,
            agent_id: row.agent_id,
          }}
        />
      )}
    </div>
  );
}

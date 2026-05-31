// Header for the right-hand detail pane. Shows title, badges, and the
// primary "agent-scoped" actions (Run eval, Delete) that should be
// available regardless of which mode tab is active.
//
// sensitivity_tier: 1

import type { JSX } from "react";
import { useCallback, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import {
  Bot,
  Loader2,
  Lock,
  Play,
  Trash2,
} from "lucide-react";
import type {
  AgentEvalRunResponse,
  PydanticAgentRow,
} from "../../../types/agents";
import { TIER_DOT, TIER_LABELS } from "../shared/constants";
import { isUserAgent } from "../shared/utils";

interface DetailHeaderProps {
  readonly row: PydanticAgentRow;
  readonly onRefresh: () => void;
  readonly onDeleted: () => void;
}

export function DetailHeader({
  row,
  onRefresh,
  onDeleted,
}: DetailHeaderProps): JSX.Element {
  const [running, setRunning] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const ownsRow = isUserAgent(row);

  const runEval = useCallback(async () => {
    setRunning(true);
    setError(null);
    try {
      await invoke<AgentEvalRunResponse>("run_agent_eval", {
        agentId: row.agent_id,
      });
      onRefresh();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setRunning(false);
    }
  }, [row.agent_id, onRefresh]);

  // Two-step inline confirm. window.confirm() is unreliable in the Tauri
  // v2 webview without the dialog plugin — it returns falsy synchronously
  // and the delete never runs.
  const deleteSelf = useCallback(async () => {
    if (!confirmDelete) {
      setConfirmDelete(true);
      return;
    }
    setConfirmDelete(false);
    setDeleting(true);
    setError(null);
    try {
      await invoke("delete_user_agent", { agentId: row.agent_id });
      onDeleted();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setDeleting(false);
    }
  }, [row.agent_id, confirmDelete, onDeleted]);

  return (
    <div className="border-b border-hairline bg-surface/40 px-4 py-3">
      <div className="flex items-start justify-between gap-3">
        <div
          className="flex h-16 w-16 shrink-0 items-center justify-center rounded-[16px] text-[26px] font-semibold text-white"
          style={{
            background:
              "linear-gradient(135deg, var(--indigo) 0%, oklch(0.62 0.18 250) 100%)",
            boxShadow:
              "0 2px 12px oklch(0.55 0.20 265 / 0.3), 0 1px 0 oklch(1 0 0 / 0.2) inset",
            letterSpacing: "-0.02em",
          }}
        >
          {row.name[0]}
        </div>
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <Bot size={16} className="text-indigo" />
            <h2 className="truncate text-base font-medium text-ink">
              {row.name}
            </h2>
            {!row.editable && (
              <span className="inline-flex items-center gap-1 rounded-full border border-hairline px-2 py-0.5 text-[10px] text-muted">
                <Lock size={9} /> locked
              </span>
            )}
            {row.editable && !ownsRow && (
              <span className="rounded-full border border-hairline px-2 py-0.5 text-[10px] text-muted">
                built-in
              </span>
            )}
            {ownsRow && (
              <span className="rounded-full border border-indigo/40 px-2 py-0.5 text-[10px] text-indigo">
                yours
              </span>
            )}
            <span className="inline-flex items-center gap-1 text-[10px] text-muted">
              <span
                className={`h-1.5 w-1.5 rounded-full ${TIER_DOT[row.tier]}`}
              />
              {TIER_LABELS[row.tier]}
            </span>
          </div>
          <p className="mt-0.5 text-[12px] text-muted">
            {row.description || "—"}
          </p>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          <button
            type="button"
            onClick={runEval}
            disabled={running}
            className="inline-flex items-center gap-1 rounded-md border border-hairline px-2.5 py-1 text-[12px] text-ink hover:bg-surface disabled:opacity-50"
            title="Re-run the eval suite for this agent"
          >
            {running
              ? <Loader2 size={12} className="animate-spin" />
              : <Play size={12} />}
            Run eval
          </button>
          {ownsRow && (
            <button
              type="button"
              onClick={deleteSelf}
              onBlur={() => setConfirmDelete(false)}
              disabled={deleting}
              className={`inline-flex items-center gap-1 rounded-md px-2.5 py-1 text-[12px] disabled:opacity-50 ${
                confirmDelete
                  ? "border border-danger/60 bg-danger/10 text-danger hover:bg-danger/20"
                  : "border border-amber/40 text-amber hover:bg-amber/10"
              }`}
              title={confirmDelete ? "Click again to confirm" : undefined}
            >
              {deleting
                ? <Loader2 size={12} className="animate-spin" />
                : <Trash2 size={12} />}
              {confirmDelete ? "Click again to confirm" : "Delete"}
            </button>
          )}
        </div>
      </div>
      {error && (
        <div className="mt-2 rounded-md border border-amber/60 bg-amber/10 px-3 py-2 text-[11px] text-amber">
          {error}
        </div>
      )}
    </div>
  );
}

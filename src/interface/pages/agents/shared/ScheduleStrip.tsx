// Schedule + run-now + last-status strip for one user agent. Lifted
// from the legacy Agents.tsx.
//
// sensitivity_tier: 1

import type { JSX } from "react";
import { useCallback, useEffect, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import {
  CircleCheck,
  CircleDashed,
  CircleX,
  Clock,
  Loader2,
  Play,
  Save,
  Settings2,
  X,
} from "lucide-react";
import { useAsyncData } from "../../../hooks/useAsyncData";
import type {
  BatchRunSummary,
  UserAgentStatus,
} from "../../../types/agents";
import { SCHEDULE_PRESETS } from "./constants";
import { cronToLabel, formatRelative } from "./utils";

interface EditScheduleModalProps {
  readonly agentId: string;
  readonly initial: UserAgentStatus;
  readonly onClose: () => void;
  readonly onSaved: () => void;
}

function EditScheduleModal({
  agentId,
  initial,
  onClose,
  onSaved,
}: EditScheduleModalProps): JSX.Element {
  const [cron, setCron] = useState<string | null>(initial.schedule_cron);
  const [enabled, setEnabled] = useState<boolean>(initial.schedule_enabled);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const save = useCallback(async () => {
    setSaving(true);
    setError(null);
    try {
      await invoke("set_user_agent_schedule", { agentId, cron, enabled });
      onSaved();
      onClose();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  }, [agentId, cron, enabled, onSaved, onClose]);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
      <div className="w-full max-w-md rounded-4 border border-hairline bg-surface shadow-xl">
        <div className="flex items-center justify-between border-b border-hairline px-5 py-3">
          <h2 className="flex items-center gap-2 text-base font-semibold text-ink">
            <Clock size={14} className="text-indigo" />
            Edit schedule
          </h2>
          <button
            type="button"
            onClick={onClose}
            className="rounded-md p-1 text-muted hover:bg-surface"
          >
            <X size={14} />
          </button>
        </div>

        <div className="space-y-4 px-5 py-4">
          <label className="flex items-center gap-2 text-[12px] text-ink">
            <input
              type="checkbox"
              checked={enabled}
              onChange={(e) => setEnabled(e.target.checked)}
            />
            Run on a schedule
          </label>

          <label className="block text-[12px] text-ink">
            <span className="text-muted">Cron preset</span>
            <select
              value={cron ?? ""}
              onChange={(e) => setCron(e.target.value || null)}
              disabled={!enabled}
              className="mt-1 w-full rounded-md border border-hairline bg-surface px-2 py-1.5 text-[12px] text-ink disabled:opacity-50"
            >
              {SCHEDULE_PRESETS.map((p) => (
                <option key={p.label} value={p.cron ?? ""}>
                  {p.label}
                </option>
              ))}
              {cron && !SCHEDULE_PRESETS.some((p) => p.cron === cron) && (
                <option value={cron}>{cron} (custom)</option>
              )}
            </select>
          </label>

          <p className="text-[11px] text-muted">
            Source bindings, callable tools and delivery tools are edited
            in the Connectors section of the agent's Edit tab.
          </p>

          {error && (
            <div className="rounded-md border border-amber/60 bg-amber/10 px-3 py-2 text-[11px] text-amber">
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
            onClick={save}
            disabled={saving}
            className="inline-flex items-center gap-1 rounded-md bg-indigo px-3 py-1.5 text-[12px] text-white hover:bg-indigo/90 disabled:opacity-50"
          >
            {saving
              ? <Loader2 size={12} className="animate-spin" />
              : <Save size={12} />}
            Save
          </button>
        </div>
      </div>
    </div>
  );
}

interface ScheduleStripProps {
  readonly agentId: string;
  readonly refreshKey: number;
}

export function ScheduleStrip({
  agentId,
  refreshKey,
}: ScheduleStripProps): JSX.Element {
  const fetcher = useCallback(
    () => invoke<UserAgentStatus>("get_user_agent_status", { agentId }),
    [agentId],
  );
  const { data, status, refetch } = useAsyncData(fetcher);
  const [running, setRunning] = useState(false);
  const [runError, setRunError] = useState<string | null>(null);
  const [lastSummary, setLastSummary] = useState<BatchRunSummary | null>(null);
  const [editOpen, setEditOpen] = useState(false);
  const [now, setNow] = useState<number>(() => Date.now());

  useEffect(() => {
    const id = window.setInterval(() => setNow(Date.now()), 60_000);
    return () => window.clearInterval(id);
  }, []);

  useEffect(() => {
    refetch();
  }, [refreshKey, refetch]);

  const runNow = useCallback(async () => {
    setRunning(true);
    setRunError(null);
    setLastSummary(null);
    try {
      const summary = await invoke<BatchRunSummary>("run_user_agent_now", {
        agentId,
      });
      setLastSummary(summary);
    } catch (e: unknown) {
      setRunError(e instanceof Error ? e.message : String(e));
    } finally {
      setRunning(false);
      refetch();
    }
  }, [agentId, refetch]);

  if (status === "loading" && !data) {
    return (
      <div className="rounded-md border border-hairline bg-surface/40 px-3 py-2 text-[11px] text-muted">
        Loading schedule…
      </div>
    );
  }
  if (!data) {
    return (
      <div className="rounded-md border border-hairline bg-surface/40 px-3 py-2 text-[11px] text-muted">
        Schedule status unavailable.
      </div>
    );
  }

  const hasSources = data.enabled_data_tools.length > 0;
  const hasDelivery = data.delivery_tools.length > 0;
  const sourceLabel = data.enabled_data_tools
    .map((id) => id.split(":")[0])
    .filter((v, i, arr) => arr.indexOf(v) === i)
    .join(", ");
  const deliveryLabel = data.delivery_tools
    .map((id) => id.split(":")[0])
    .filter((v, i, arr) => arr.indexOf(v) === i)
    .join(", ");
  const modeLabel = !data.schedule_enabled
    ? "Manual only"
    : hasSources
      ? `Scheduled batch · ${sourceLabel}`
        + (hasDelivery ? ` · delivers via ${deliveryLabel}` : "")
      : "Scheduled (no source)";

  const lastStatusIcon = data.last_status === "success"
    ? <CircleCheck size={11} className="text-success" />
    : data.last_status === "error"
      ? <CircleX size={11} className="text-amber" />
      : <CircleDashed size={11} className="text-muted" />;

  return (
    <div className="rounded-md border border-hairline bg-surface/40 px-3 py-2 text-[11px] text-ink">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex flex-wrap items-center gap-2">
          <Clock size={12} className="text-indigo" />
          <span className="font-medium">{modeLabel}</span>
          {data.schedule_enabled && (
            <>
              <span className="text-muted">·</span>
              <span>{cronToLabel(data.schedule_cron)}</span>
            </>
          )}
          {data.schedule_enabled && data.next_run_at && (
            <>
              <span className="text-muted">·</span>
              <span className="text-muted">
                Next run {formatRelative(data.next_run_at, now)}
              </span>
            </>
          )}
        </div>
        <div className="flex items-center gap-2">
          {hasSources && (
            <span
              className={`rounded-full border px-2 py-0.5 text-[10px] ${
                data.pending_count > 0
                  ? "border-indigo/60 text-indigo"
                  : "border-hairline text-muted"
              }`}
              title="Unprocessed messages waiting for this agent"
            >
              {data.pending_count} pending
            </span>
          )}
          <button
            type="button"
            onClick={runNow}
            disabled={running}
            className="inline-flex items-center gap-1 rounded-md border border-indigo/60 px-2 py-1 text-[11px] text-indigo hover:bg-indigo-soft disabled:opacity-50"
            title="Run this agent now (processes the unprocessed backlog if sources are bound)"
          >
            {running
              ? <Loader2 size={11} className="animate-spin" />
              : <Play size={11} />}
            Run now
          </button>
          <button
            type="button"
            onClick={() => setEditOpen(true)}
            className="inline-flex items-center gap-1 rounded-md border border-hairline px-2 py-1 text-[11px] text-muted hover:bg-surface"
            title="Edit schedule"
          >
            <Settings2 size={11} />
            Edit
          </button>
        </div>
      </div>
      <div className="mt-1 flex flex-wrap items-center gap-2 text-[11px] text-muted">
        {lastStatusIcon}
        <span>
          Last run:{" "}
          {data.last_run_at ? formatRelative(data.last_run_at, now) : "never"}
          {data.last_status ? ` · ${data.last_status}` : ""}
        </span>
        {lastSummary && (
          <span>
            · this run: {lastSummary.processed} processed
            {lastSummary.errors > 0 ? `, ${lastSummary.errors} errors` : ""}
            {lastSummary.delivery_calls.length > 0 && (() => {
              const total = lastSummary.delivery_calls.length;
              const errs = lastSummary.delivery_calls.filter(
                (c) => c.status === "error",
              ).length;
              return `, delivered to ${total - errs}/${total} tool(s)`;
            })()}
          </span>
        )}
        {runError && <span className="text-amber">· {runError}</span>}
      </div>
      {editOpen && (
        <EditScheduleModal
          agentId={agentId}
          initial={data}
          onClose={() => setEditOpen(false)}
          onSaved={refetch}
        />
      )}
    </div>
  );
}

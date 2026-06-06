/**
 * Pipeline refresh modal with 3 steps: Estimate, Processing, Complete.
 *
 * Displayed when the user clicks "Refresh Now" or presses Cmd+R.
 * Shows estimation, real-time progress via Tauri events, and a completion summary.
 *
 * sensitivity_tier: 1 (infrastructure metrics only)
 */

import {
  RefreshCw,
  Check,
  AlertTriangle,
  Clock,
  Database,
  X,
  Zap,
  Loader2,
  ChevronDown,
  ChevronUp,
  Minimize2,
} from "lucide-react";
import { useState } from "react";
import type {
  PipelineProgressState,
  CompletedModel,
  RefreshPlanData,
} from "../hooks/usePipelineProgress";
import { formatRelativeTime } from "../utils/timeFormat";

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

interface PipelineRefreshModalProps {
  readonly state: PipelineProgressState;
  readonly onStartRun: (trigger?: string, mode?: string) => void;
  readonly onCancel: () => void;
  readonly onClose: () => void;
  readonly onRetry: () => void;
  readonly onForceRefresh: () => void;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Format seconds as "Xs" or "Xm Ys". */
function formatDuration(seconds: number): string {
  if (seconds < 60) return `${Math.round(seconds)}s`;
  const mins = Math.floor(seconds / 60);
  const secs = Math.round(seconds % 60);
  return secs > 0 ? `${mins}m ${secs}s` : `${mins}m`;
}

/** Human-friendly raw table name. */
function friendlyTableName(name: string): string {
  return name
    .replace("raw_", "")
    .replace(/_/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

/** Human-friendly model name. */
function friendlyModelName(name: string): string {
  const parts = name.split(".");
  return parts[parts.length - 1].replace(/_/g, " ");
}

/** Total pending changes count. */
function totalPending(changes: Record<string, number>): number {
  return Object.values(changes).reduce(
    (sum, n) => sum + Math.max(0, n),
    0,
  );
}

/** Total rows across completed models. */
function totalRows(models: readonly CompletedModel[]): number {
  return models.reduce((sum, m) => sum + Math.max(0, m.rows), 0);
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function EstimatingStep() {
  return (
    <div className="flex flex-col items-center gap-4 py-8">
      <Loader2 strokeWidth={1.6} className="h-8 w-8 animate-spin text-indigo" />
      <p className="text-sm text-muted">Checking for changes...</p>
    </div>
  );
}

/** Priority tier indicator colors. */
const PRIORITY_COLORS: Record<string, string> = {
  critical: "bg-danger",
  high: "bg-orange-400",
  medium: "bg-amber",
  low: "bg-muted/60",
};

const PRIORITY_LABELS: Record<string, string> = {
  critical: "Dashboard",
  high: "Top interests",
  medium: "Recent activity",
  low: "New data only",
};

/** Groups planned models by priority and renders a compact breakdown. */
function PlanBreakdown({
  plan,
}: {
  readonly plan: RefreshPlanData;
}) {
  const [showSkipped, setShowSkipped] = useState(false);

  const groups: Record<string, readonly { name: string; reason: string }[]> =
    {};
  for (const m of plan.models) {
    const list = groups[m.priority] ?? [];
    groups[m.priority] = [...list, m];
  }

  const orderedPriorities = ["critical", "high", "medium", "low"];

  return (
    <div className="space-y-3">
      {orderedPriorities.map((priority) => {
        const models = groups[priority];
        if (!models || models.length === 0) return null;
        return (
          <div key={priority} className="space-y-1">
            <div className="flex items-center gap-1.5 text-xs font-medium text-ink">
              <span
                className={`inline-block h-2 w-2 rounded-full ${PRIORITY_COLORS[priority]}`}
              />
              {PRIORITY_LABELS[priority] ?? priority} ({models.length})
            </div>
            <div className="pl-4 text-[11px] text-muted">
              {models.map((m) => friendlyModelName(m.name)).join(", ")}
            </div>
          </div>
        );
      })}

      {plan.skipped.length > 0 && (
        <div className="space-y-1">
          <button
            onClick={() => setShowSkipped((v) => !v)}
            className="flex items-center gap-1.5 text-xs text-muted hover:text-ink"
          >
            <span className="inline-block h-2 w-2 rounded-full bg-hairline" />
            Skipped ({plan.skipped.length})
            {showSkipped ? (
              <ChevronUp strokeWidth={1.6} className="h-3 w-3" />
            ) : (
              <ChevronDown strokeWidth={1.6} className="h-3 w-3" />
            )}
          </button>
          {showSkipped && (
            <div className="pl-4 text-[11px] text-muted">
              {plan.skipped
                .map((s) => friendlyModelName(s.name))
                .join(", ")}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function EstimateStep({
  state,
  onStartRun,
  onClose,
  onForceRefresh,
}: {
  readonly state: PipelineProgressState;
  readonly onStartRun: (trigger?: string, mode?: string) => void;
  readonly onClose: () => void;
  readonly onForceRefresh: () => void;
}) {
  const estimate = state.estimate;
  if (!estimate) return null;

  const pending = estimate.pending_changes;
  const total = totalPending(pending);
  const hasChanges = total > 0;
  const lastRunAt = estimate.last_run?.completed_at ?? null;

  if (!hasChanges) {
    return (
      <>
        <div className="flex flex-col items-center gap-3 py-6">
          <div className="flex h-12 w-12 items-center justify-center rounded-full bg-success/15">
            <Check strokeWidth={1.6} className="h-6 w-6 text-success" />
          </div>
          <p className="text-sm font-medium text-ink">
            Your data is already up to date!
          </p>
          {lastRunAt && (
            <p className="text-xs text-muted">
              Last refreshed {formatRelativeTime(lastRunAt)}
            </p>
          )}
        </div>
        <div className="flex justify-end gap-2 border-t border-hairline px-5 py-4">
          <button
            onClick={onClose}
            className="rounded-2 border border-hairline px-4 py-2 text-xs text-ink hover:bg-surface"
          >
            Close
          </button>
          <button
            onClick={() => onForceRefresh()}
            className="flex items-center gap-1.5 rounded-2 border border-hairline px-4 py-2 text-xs text-muted hover:bg-surface hover:text-ink"
          >
            <Zap strokeWidth={1.6} className="h-3 w-3" />
            Force Refresh Anyway
          </button>
        </div>
      </>
    );
  }

  const changeSummary = Object.entries(pending)
    .filter(([, n]) => n > 0)
    .sort(([, a], [, b]) => b - a);

  const plan = state.plan;

  return (
    <>
      <div className="space-y-4 px-5 pb-4">
        <p className="text-sm font-medium text-ink">
          {plan ? "Smart Refresh" : "Ready to refresh your data"}
        </p>

        {/* Plan breakdown (when available) */}
        {plan && plan.models.length > 0 ? (
          <div className="rounded-2 bg-surface/60 p-3">
            <PlanBreakdown plan={plan} />
          </div>
        ) : (
          /* Fallback: raw changes detected */
          <div className="rounded-2 bg-surface/60 p-3">
            <p className="mb-2 flex items-center gap-1.5 text-xs font-medium text-ink">
              <Database strokeWidth={1.6} className="h-3 w-3 text-indigo" />
              Changes detected:
            </p>
            <ul className="space-y-1 pl-5">
              {changeSummary.map(([table, count]) => (
                <li
                  key={table}
                  className="text-xs text-muted"
                >
                  {count} new{" "}
                  {friendlyTableName(table).toLowerCase()}
                </li>
              ))}
            </ul>
          </div>
        )}

        {/* Models to process + estimated time */}
        <div className="flex items-center gap-4 text-xs text-muted">
          <span className="flex items-center gap-1">
            <RefreshCw strokeWidth={1.6} className="h-3 w-3" />
            Models to process:{" "}
            {plan ? plan.models.length : (estimate.pending_changes ? 13 : 0)}
          </span>
        </div>

        <div className="flex items-center gap-1.5 text-xs text-muted">
          <Clock strokeWidth={1.6} className="h-3 w-3" />
          {plan ? (
            <>
              ~{formatDuration(plan.estimated_duration_seconds)}
              <span className="text-[11px]">
                (vs ~{formatDuration(plan.full_duration_seconds)}{" "}
                for all)
              </span>
            </>
          ) : (
            <>
              Estimated time: ~
              {formatDuration(estimate.estimated_refresh_time)}
              {estimate.last_run && (
                <span className="text-[11px]">
                  (based on recent refreshes averaging{" "}
                  {formatDuration(estimate.last_run.duration_seconds)}
                  )
                </span>
              )}
            </>
          )}
        </div>
      </div>

      <div className="flex justify-end gap-2 border-t border-hairline px-5 py-4">
        <button
          onClick={onClose}
          className="rounded-2 border border-hairline px-4 py-2 text-xs text-ink hover:bg-surface"
        >
          Cancel
        </button>
        {plan && plan.models.length > 0 ? (
          <>
            <button
              onClick={() => onStartRun("manual", "full")}
              className="flex items-center gap-1.5 rounded-2 border border-hairline px-4 py-2 text-xs text-muted hover:bg-surface hover:text-ink"
            >
              <RefreshCw strokeWidth={1.6} className="h-3 w-3" />
              Run All
            </button>
            <button
              onClick={() => onStartRun("manual", "smart")}
              className="flex items-center gap-1.5 rounded-2 bg-indigo px-4 py-2 text-xs font-medium text-white hover:bg-indigo/80"
            >
              <Zap strokeWidth={1.6} className="h-3 w-3" />
              Run Smart
            </button>
          </>
        ) : (
          <button
            onClick={() => onStartRun("manual", "full")}
            className="flex items-center gap-1.5 rounded-2 bg-indigo px-4 py-2 text-xs font-medium text-white hover:bg-indigo/80"
          >
            <RefreshCw strokeWidth={1.6} className="h-3 w-3" />
            Refresh Now
          </button>
        )}
      </div>
    </>
  );
}

function ProcessingStep({
  state,
  onCancel,
  onMinimize,
}: {
  readonly state: PipelineProgressState;
  readonly onCancel: () => void;
  readonly onMinimize: () => void;
}) {
  const progress =
    state.totalSteps > 0
      ? Math.round((state.stepIndex / state.totalSteps) * 100)
      : 0;

  const eta =
    state.estimate && state.elapsedSeconds > 0
      ? Math.max(
          0,
          Math.round(
            state.estimate.estimated_refresh_time - state.elapsedSeconds,
          ),
        )
      : null;

  return (
    <>
      <div className="space-y-4 px-5 pb-5">
        {/* Progress bar */}
        <div className="space-y-2">
          <div className="flex items-center justify-between text-xs">
            <span className="text-muted">
              {state.stepIndex} / {state.totalSteps} models
            </span>
            <span className="text-muted">{progress}%</span>
          </div>
          <div className="h-2 overflow-hidden rounded-full bg-surface">
            <div
              className="h-full rounded-full bg-indigo transition-all duration-300"
              style={{ width: `${progress}%` }}
            />
          </div>
        </div>

        {/* Current step */}
        <div className="flex items-center gap-2 text-xs text-ink">
          <RefreshCw strokeWidth={1.6} className="h-3 w-3 animate-spin text-indigo" />
          {state.currentModel
            ? `Processing ${friendlyModelName(state.currentModel)}...`
            : "Starting pipeline..."}
        </div>

        {/* Elapsed / ETA */}
        <div className="flex items-center gap-4 text-[11px] text-muted">
          <span>Elapsed: {formatDuration(state.elapsedSeconds)}</span>
          {eta !== null && eta > 0 && (
            <span>ETA: ~{formatDuration(eta)}</span>
          )}
        </div>

        {/* Completed models */}
        {state.completedModels.length > 0 && (
          <div className="max-h-32 space-y-1 overflow-y-auto rounded-2 bg-surface/60 p-3">
            {state.completedModels.map((m, i) => (
              <div
                key={i}
                className="flex items-center gap-2 text-[11px] text-muted"
              >
                <Check strokeWidth={1.6} className="h-3 w-3 text-success" />
                <span>{friendlyModelName(m.model)}</span>
                <span className="ml-auto">{m.rows} rows</span>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Footer actions */}
      <div className="flex justify-end gap-2 border-t border-hairline px-5 py-3">
        <button
          onClick={onCancel}
          className="rounded-2 border border-hairline px-4 py-2 text-xs text-muted hover:bg-surface hover:text-ink"
        >
          Cancel
        </button>
        <button
          onClick={onMinimize}
          className="flex items-center gap-1.5 rounded-2 bg-indigo px-4 py-2 text-xs font-medium text-white hover:bg-indigo/80"
          title="Hide this dialog but keep the refresh running. Reopen from the sync pill in the top bar."
        >
          <Minimize2 strokeWidth={1.6} className="h-3 w-3" />
          Run in background
        </button>
      </div>
    </>
  );
}

function CancelledStep({
  state,
  onClose,
  onRetry,
}: {
  readonly state: PipelineProgressState;
  readonly onClose: () => void;
  readonly onRetry: () => void;
}) {
  return (
    <>
      <div className="space-y-4 px-5 pb-4">
        <div className="flex flex-col items-center gap-3 py-4">
          <div className="flex h-12 w-12 items-center justify-center rounded-full bg-amber/15">
            <X strokeWidth={1.6} className="h-6 w-6 text-amber" />
          </div>
          <p className="text-sm font-medium text-ink">Refresh cancelled</p>
          <p className="text-center text-xs text-muted">
            {state.completedModels.length} of {state.totalSteps} models were
            updated.
          </p>
        </div>
      </div>
      <div className="flex justify-end gap-2 border-t border-hairline px-5 py-4">
        <button
          onClick={onClose}
          className="rounded-2 border border-hairline px-4 py-2 text-xs text-ink hover:bg-surface"
        >
          Close
        </button>
        <button
          onClick={onRetry}
          className="flex items-center gap-1.5 rounded-2 bg-indigo px-4 py-2 text-xs font-medium text-white hover:bg-indigo/80"
        >
          <RefreshCw strokeWidth={1.6} className="h-3 w-3" />
          Retry Full Refresh
        </button>
      </div>
    </>
  );
}

function CompleteStep({
  state,
  onClose,
}: {
  readonly state: PipelineProgressState;
  readonly onClose: () => void;
}) {
  const total = totalRows(state.completedModels);

  return (
    <>
      <div className="space-y-4 px-5 pb-4">
        {/* Success header */}
        <div className="flex flex-col items-center gap-3 py-4">
          <div className="flex h-12 w-12 items-center justify-center rounded-full bg-success/15">
            <Check strokeWidth={1.6} className="h-6 w-6 text-success" />
          </div>
          <p className="text-sm font-medium text-ink">
            Refresh complete
            {state.durationSeconds !== null &&
              ` in ${formatDuration(state.durationSeconds)}`}
          </p>
        </div>

        {/* Index warning — marts succeeded but vector/graph index failed */}
        {state.indexWarning && (
          <div className="flex items-start gap-2 rounded-2 border border-amber/30 bg-amber/10 p-3 text-xs text-amber">
            <AlertTriangle
              strokeWidth={1.6}
              className="mt-0.5 h-4 w-4 shrink-0"
            />
            <div>
              <p className="font-medium">
                Data updated, but search index didn't refresh
              </p>
              <p className="mt-0.5 text-amber/90">{state.indexWarning}</p>
            </div>
          </div>
        )}

        {/* Summary */}
        {state.completedModels.length > 0 && (
          <div className="space-y-1 rounded-2 bg-surface/60 p-3">
            <p className="mb-2 text-xs font-medium text-ink">Summary</p>
            <p className="text-xs text-muted">
              {total} rows updated across {state.completedModels.length} models
            </p>
            <div className="mt-2 max-h-32 space-y-1 overflow-y-auto">
              {state.completedModels
                .filter((m) => m.rows > 0)
                .map((m, i) => (
                  <div
                    key={i}
                    className="flex items-center justify-between text-[11px] text-muted"
                  >
                    <span>{friendlyModelName(m.model)}</span>
                    <span>{m.rows} rows</span>
                  </div>
                ))}
            </div>
          </div>
        )}
      </div>

      <div className="flex justify-end border-t border-hairline px-5 py-4">
        <button
          onClick={onClose}
          className="rounded-2 bg-indigo px-4 py-2 text-xs font-medium text-white hover:bg-indigo/80"
        >
          Done
        </button>
      </div>
    </>
  );
}

function ErrorStep({
  state,
  onRetry,
  onClose,
}: {
  readonly state: PipelineProgressState;
  readonly onRetry: () => void;
  readonly onClose: () => void;
}) {
  const [showDetails, setShowDetails] = useState(false);

  return (
    <>
      <div className="space-y-4 px-5 pb-4">
        <div className="flex flex-col items-center gap-3 py-4">
          <div className="flex h-12 w-12 items-center justify-center rounded-full bg-amber/15">
            <AlertTriangle strokeWidth={1.6} className="h-6 w-6 text-amber" />
          </div>
          <p className="text-sm font-medium text-ink">Refresh failed</p>
          <p className="text-center text-xs text-muted">
            {state.error ?? "An unknown error occurred"}
          </p>
        </div>

        {state.error && (
          <button
            onClick={() => setShowDetails((v) => !v)}
            className="flex w-full items-center justify-center gap-1 text-[11px] text-muted hover:text-ink"
          >
            {showDetails ? (
              <ChevronUp strokeWidth={1.6} className="h-3 w-3" />
            ) : (
              <ChevronDown strokeWidth={1.6} className="h-3 w-3" />
            )}
            {showDetails ? "Hide details" : "View details"}
          </button>
        )}

        {showDetails && state.error && (
          <pre className="max-h-32 overflow-auto rounded-2 bg-surface/60 p-3 text-[11px] text-muted">
            {state.error}
          </pre>
        )}
      </div>

      <div className="flex justify-end gap-2 border-t border-hairline px-5 py-4">
        <button
          onClick={onClose}
          className="rounded-2 border border-hairline px-4 py-2 text-xs text-ink hover:bg-surface"
        >
          Close
        </button>
        <button
          onClick={onRetry}
          className="flex items-center gap-1.5 rounded-2 bg-indigo px-4 py-2 text-xs font-medium text-white hover:bg-indigo/80"
        >
          <RefreshCw strokeWidth={1.6} className="h-3 w-3" />
          Retry
        </button>
      </div>
    </>
  );
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

function PipelineRefreshModal({
  state,
  onStartRun,
  onCancel,
  onClose,
  onRetry,
  onForceRefresh,
}: PipelineRefreshModalProps) {
  const title =
    state.step === "processing"
      ? "Refreshing data..."
      : state.step === "complete"
        ? "Refresh complete"
        : state.step === "cancelled"
          ? "Refresh cancelled"
          : state.step === "error"
            ? "Refresh failed"
            : "Data Refresh";

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
      <div className="mx-4 w-full max-w-lg rounded-5 bg-surface shadow-2xl">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-hairline px-5 py-4">
          <div className="flex items-center gap-2">
            <Database strokeWidth={1.6} className="h-4 w-4 text-indigo" />
            <h3 className="text-sm font-semibold text-ink">{title}</h3>
          </div>
          <button
            onClick={onClose}
            className="rounded-2 p-1 text-muted hover:bg-surface hover:text-ink"
          >
            <X strokeWidth={1.6} className="h-4 w-4" />
          </button>
        </div>

        {/* Step content */}
        {state.step === "estimating" && <EstimatingStep />}

        {state.step === "estimate" && (
          <EstimateStep
            state={state}
            onStartRun={onStartRun}
            onClose={onClose}
            onForceRefresh={onForceRefresh}
          />
        )}

        {state.step === "processing" && (
          <ProcessingStep
            state={state}
            onCancel={onCancel}
            onMinimize={onClose}
          />
        )}

        {state.step === "complete" && (
          <CompleteStep state={state} onClose={onClose} />
        )}

        {state.step === "cancelled" && (
          <CancelledStep state={state} onClose={onClose} onRetry={onRetry} />
        )}

        {state.step === "error" && (
          <ErrorStep state={state} onRetry={onRetry} onClose={onClose} />
        )}

        {/* Keyboard shortcut hint */}
        {(state.step === "estimating" || state.step === "estimate") && (
          <div className="px-5 pb-3">
            <p className="text-center text-[10px] text-muted/60">
              Press Cmd+R to open this dialog from anywhere
            </p>
          </div>
        )}
      </div>
    </div>
  );
}

export default PipelineRefreshModal;

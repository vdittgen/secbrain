/**
 * Pipeline status bar for the Dashboard top area.
 *
 * Shows one of four visual states:
 * - Fresh:   "Data is up to date — last processed 5 min ago"
 * - Stale:   "8 new items to process — est. ~12 sec  [Refresh Now]"
 * - Running: "Processing... — ~8 sec remaining"
 * - Failed:  "Last refresh failed — [Retry] [View Error]"
 *
 * sensitivity_tier: 1 (infrastructure metrics only)
 */

import { useState } from "react";
import { RefreshCw, AlertTriangle, ChevronDown, ChevronUp } from "lucide-react";
import { formatRelativeTime } from "../utils/timeFormat";

interface PipelineStatusBarProps {
  readonly lastCompletedAt: string | null;
  readonly isStale: boolean;
  readonly runState: "idle" | "running" | "failed";
  readonly runError: string | null;
  readonly totalPending: number;
  readonly estimatedDuration: number;
  readonly onRefresh: () => void;
}

function PipelineStatusBar({
  lastCompletedAt,
  isStale,
  runState,
  runError,
  totalPending,
  estimatedDuration,
  onRefresh,
}: PipelineStatusBarProps) {
  const [errorExpanded, setErrorExpanded] = useState(false);

  // Running state
  if (runState === "running") {
    const estLabel =
      estimatedDuration > 0
        ? `~${Math.round(estimatedDuration)}s remaining`
        : "";

    return (
      <div className="flex items-center justify-between rounded-2 border border-indigo/30 bg-indigo/5 px-4 py-2.5">
        <span className="text-xs text-ink">
          Processing...{estLabel && ` \u2014 ${estLabel}`}
        </span>
        <button
          disabled
          className="flex items-center gap-1.5 rounded-md px-3 py-1 text-xs text-muted opacity-50"
        >
          <RefreshCw strokeWidth={1.6} className="h-3 w-3 animate-spin" />
          Refreshing
        </button>
      </div>
    );
  }

  // Failed state
  if (runState === "failed") {
    return (
      <div className="rounded-2 border border-amber/40 bg-amber/8">
        <div className="flex items-center justify-between px-4 py-2.5">
          <span className="flex items-center gap-1.5 text-xs text-amber">
            <AlertTriangle strokeWidth={1.6} className="h-3 w-3" />
            Last refresh failed
          </span>
          <div className="flex items-center gap-2">
            {runError && (
              <button
                onClick={() => setErrorExpanded((v) => !v)}
                className="flex items-center gap-1 rounded-md px-2 py-1 text-xs text-muted hover:text-ink"
              >
                {errorExpanded ? (
                  <ChevronUp strokeWidth={1.6} className="h-3 w-3" />
                ) : (
                  <ChevronDown strokeWidth={1.6} className="h-3 w-3" />
                )}
                View Error
              </button>
            )}
            <button
              onClick={onRefresh}
              className="flex items-center gap-1.5 rounded-md bg-amber/15 px-3 py-1 text-xs text-amber hover:bg-amber/25"
            >
              <RefreshCw strokeWidth={1.6} className="h-3 w-3" />
              Retry
            </button>
          </div>
        </div>
        {errorExpanded && runError && (
          <div className="border-t border-amber-soft px-4 py-2">
            <p className="text-xs text-muted">{runError}</p>
          </div>
        )}
      </div>
    );
  }

  // Stale state
  if (isStale) {
    const estLabel =
      estimatedDuration > 0
        ? `est. ~${Math.round(estimatedDuration)}s`
        : "";

    return (
      <div className="flex items-center gap-3 rounded-2 border border-amber-soft bg-amber/5 px-4 py-2.5">
        <span className="min-w-0 flex-1 truncate text-xs text-ink">
          {totalPending > 0
            ? `${totalPending} new items to process`
            : "New data available"}
          {estLabel && ` \u2014 ${estLabel}`}
          {" \u00b7 "}
          {lastCompletedAt
            ? `last processed ${formatRelativeTime(lastCompletedAt)}`
            : "never processed"}
        </span>
        <button
          onClick={onRefresh}
          className="flex shrink-0 items-center gap-1.5 rounded-pill border border-hairline-2 bg-surface px-3 py-1.5 text-xs font-medium text-indigo shadow-1 transition-colors hover:bg-bg-2"
        >
          <RefreshCw strokeWidth={1.6} className="h-3 w-3" />
          Refresh Now
        </button>
      </div>
    );
  }

  // Fresh state
  if (lastCompletedAt) {
    return (
      <div className="flex items-center px-1 py-1">
        <span className="text-[11px] text-success">
          Data is up to date &middot; last processed{" "}
          {formatRelativeTime(lastCompletedAt)}
        </span>
      </div>
    );
  }

  // No data yet — show a way to trigger the first run
  return (
    <div className="flex items-center justify-between rounded-2 border border-hairline bg-surface px-4 py-2.5">
      <span className="text-xs text-muted">
        Pipeline has not run yet
      </span>
      <button
        onClick={onRefresh}
        className="flex items-center gap-1.5 rounded-md bg-indigo-soft px-3 py-1 text-xs text-indigo hover:bg-indigo-soft"
      >
        <RefreshCw strokeWidth={1.6} className="h-3 w-3" />
        Refresh Now
      </button>
    </div>
  );
}

export default PipelineStatusBar;

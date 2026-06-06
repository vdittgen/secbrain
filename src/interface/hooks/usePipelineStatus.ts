/**
 * Hook for polling pipeline status and managing pipeline run triggers.
 *
 * Polls `get_pipeline_status` every 30s and provides a `triggerRefresh`
 * callback that starts a background pipeline run, polling for its result.
 *
 * sensitivity_tier: 1 (infrastructure metrics only)
 */

import { useState, useEffect, useCallback, useRef } from "react";
import { dedupInvoke } from "../utils/requestDedup";

// ---------------------------------------------------------------------------
// Types matching Rust backend (types.rs)
// ---------------------------------------------------------------------------

interface PipelineRunSummary {
  run_id: string;
  started_at: string;
  completed_at: string;
  duration_seconds: number;
  status: string;
  models_processed: string[];
  rows_processed: Record<string, number>;
  rows_changed: Record<string, number>;
  trigger: string;
  error: string | null;
  // Re-index outcomes recorded after marts complete. A run can be a
  // "success" at producing marts while a vector/graph index failed.
  vector_index_status: string | null;
  graph_index_status: string | null;
  index_error: string | null;
}

interface PipelineStatus {
  last_run: PipelineRunSummary | null;
  is_stale: boolean;
  pending_changes: Record<string, number>;
  estimated_refresh_time: number;
}

interface PipelineRunStarted {
  run_id: string;
  status: string;
}

interface PipelineRunResult {
  run_id: string;
  status: string;
  result: PipelineRunSummary | null;
}

// ---------------------------------------------------------------------------
// Hook return type
// ---------------------------------------------------------------------------

export interface PipelineStatusHook {
  readonly pipelineStatus: PipelineStatus | null;
  readonly runState: "idle" | "running" | "failed";
  readonly runError: string | null;
  readonly triggerRefresh: () => void;
  readonly lastCompletedAt: string | null;
  readonly isStale: boolean;
  readonly totalPending: number;
  /** True when the last run failed OR a vector/graph index stage failed. */
  readonly anyStageFailing: boolean;
  /** Human-readable reason for the failing stage, when known. */
  readonly stageFailureReason: string | null;
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const STATUS_POLL_MS = 30_000;
const RUN_POLL_MS = 2_000;

// ---------------------------------------------------------------------------
// Hook implementation
// ---------------------------------------------------------------------------

export function usePipelineStatus(): PipelineStatusHook {
  const [pipelineStatus, setPipelineStatus] = useState<PipelineStatus | null>(
    null,
  );
  const [runState, setRunState] = useState<"idle" | "running" | "failed">(
    "idle",
  );
  const [runError, setRunError] = useState<string | null>(null);

  const mountedRef = useRef(true);
  const runPollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // -- Fetch pipeline status ------------------------------------------------

  const fetchStatus = useCallback(async () => {
    try {
      const status = await dedupInvoke<PipelineStatus>("get_pipeline_status");
      if (mountedRef.current) {
        setPipelineStatus(status);
      }
    } catch {
      // Silently ignore — dashboard stays functional without pipeline info.
    }
  }, []);

  // -- Poll status on mount + interval --------------------------------------

  useEffect(() => {
    mountedRef.current = true;

    fetchStatus();
    const interval = setInterval(fetchStatus, STATUS_POLL_MS);

    return () => {
      mountedRef.current = false;
      clearInterval(interval);
      if (runPollRef.current) {
        clearInterval(runPollRef.current);
      }
    };
  }, [fetchStatus]);

  // -- Re-fetch when pipeline refresh completes (modal or auto-refresh) -----

  useEffect(() => {
    const handler = () => fetchStatus();
    window.addEventListener("arandu:pipeline-refreshed", handler);
    return () =>
      window.removeEventListener("arandu:pipeline-refreshed", handler);
  }, [fetchStatus]);

  // -- Trigger a pipeline run -----------------------------------------------

  const triggerRefresh = useCallback(async () => {
    if (runState === "running") return;

    setRunState("running");
    setRunError(null);

    try {
      const started = await dedupInvoke<PipelineRunStarted>(
        "trigger_pipeline_run",
      );
      const runId = started.run_id;

      // Poll for run result every 2s
      runPollRef.current = setInterval(async () => {
        try {
          const result = await dedupInvoke<PipelineRunResult>(
            "get_pipeline_run_result",
            { run_id: runId },
          );

          if (!mountedRef.current) {
            if (runPollRef.current) clearInterval(runPollRef.current);
            return;
          }

          if (result.status === "completed") {
            if (runPollRef.current) clearInterval(runPollRef.current);
            runPollRef.current = null;

            if (result.result?.status === "failed") {
              setRunState("failed");
              setRunError(result.result.error ?? "Pipeline run failed");
            } else {
              setRunState("idle");
            }

            // Re-fetch status after completion
            fetchStatus();
          } else if (
            result.status === "failed" ||
            result.status === "not_found"
          ) {
            if (runPollRef.current) clearInterval(runPollRef.current);
            runPollRef.current = null;
            setRunState("failed");
            setRunError(
              result.result?.error ?? "Pipeline run failed unexpectedly",
            );
          }
        } catch {
          // Keep polling — transient errors are expected
        }
      }, RUN_POLL_MS);
    } catch (err) {
      if (mountedRef.current) {
        setRunState("failed");
        setRunError(
          err instanceof Error ? err.message : "Failed to start pipeline run",
        );
      }
    }
  }, [runState, fetchStatus]);

  // -- Derived values -------------------------------------------------------

  const lastCompletedAt = pipelineStatus?.last_run?.completed_at ?? null;
  // Default to stale when status is unknown (fetch failed or loading)
  const isStale = pipelineStatus ? pipelineStatus.is_stale : !lastCompletedAt;
  const totalPending = pipelineStatus
    ? Object.values(pipelineStatus.pending_changes).reduce(
        (sum, n) => sum + Math.max(n, 0),
        0,
      )
    : 0;

  // Default to false when status is unknown (loading / fetch failed) so
  // we don't false-alarm on first paint.
  const lastRun = pipelineStatus?.last_run ?? null;
  const vectorFailed = lastRun?.vector_index_status === "error";
  const graphFailed = lastRun?.graph_index_status === "error";
  const runFailed = lastRun?.status === "failed";
  const anyStageFailing = runFailed || vectorFailed || graphFailed;
  let stageFailureReason: string | null = null;
  if (runFailed) {
    stageFailureReason = lastRun?.error ?? "Pipeline run failed";
  } else if (vectorFailed || graphFailed) {
    const stages = [
      vectorFailed ? "vector" : null,
      graphFailed ? "graph" : null,
    ]
      .filter(Boolean)
      .join(" & ");
    stageFailureReason =
      lastRun?.index_error ?? `${stages} index failed`;
  }

  return {
    pipelineStatus,
    runState,
    runError,
    triggerRefresh,
    lastCompletedAt,
    isStale,
    totalPending,
    anyStageFailing,
    stageFailureReason,
  };
}

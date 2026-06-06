/**
 * Hook for managing pipeline refresh with streaming progress.
 *
 * Drives the 3-step PipelineRefreshModal: estimate → processing → complete.
 * Listens to `pipeline-progress` Tauri events for real-time progress updates.
 *
 * sensitivity_tier: 1 (infrastructure metrics only)
 */

import { useState, useRef, useCallback, useEffect } from "react";
import { invoke } from "@tauri-apps/api/core";
import { listen, type UnlistenFn } from "@tauri-apps/api/event";
import { dedupInvoke } from "../utils/requestDedup";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface PipelineProgressEvent {
  readonly type:
    | "started"
    | "sqlmesh_running"
    | "model_start"
    | "model_complete"
    | "done"
    | "cancelled"
    | "error"
    | "plan"
    | "reindexing"
    | "reindex_complete"
    | "reindex_error"
    | "graph_reindexing"
    | "graph_reindex_complete"
    | "graph_reindex_error";
  readonly model_name: string | null;
  readonly step_index: number;
  readonly total_steps: number;
  readonly status: string;
  readonly elapsed_seconds: number;
  readonly rows_processed: number | null;
  readonly run_id?: string;
  readonly duration_seconds?: number;
  readonly error?: string;
  readonly models_completed?: number;
  readonly total_models?: number;
}

interface PipelineRunStarted {
  readonly run_id: string;
  readonly status: string;
}

interface PipelineStatus {
  readonly last_run: {
    readonly completed_at: string;
    readonly duration_seconds: number;
  } | null;
  readonly is_stale: boolean;
  readonly pending_changes: Record<string, number>;
  readonly estimated_refresh_time: number;
}

export interface PlannedModelData {
  readonly name: string;
  readonly priority: string;
  readonly reason: string;
}

export interface SkippedModelData {
  readonly name: string;
  readonly reason: string;
}

export interface RefreshPlanData {
  readonly models: readonly PlannedModelData[];
  readonly skipped: readonly SkippedModelData[];
  readonly estimated_duration_seconds: number;
  readonly full_duration_seconds: number;
  readonly summary: string;
}

export type ModalStep =
  | "idle"
  | "estimating"
  | "estimate"
  | "processing"
  | "minimized"
  | "complete"
  | "cancelled"
  | "error";

export interface CompletedModel {
  readonly model: string;
  readonly rows: number;
}

export interface PipelineProgressState {
  readonly step: ModalStep;
  readonly estimate: PipelineStatus | null;
  readonly plan: RefreshPlanData | null;
  readonly currentModel: string | null;
  readonly stepIndex: number;
  readonly totalSteps: number;
  readonly elapsedSeconds: number;
  readonly completedModels: readonly CompletedModel[];
  readonly error: string | null;
  readonly runId: string | null;
  readonly durationSeconds: number | null;
  /**
   * Set when the marts completed but the vector/graph re-index (which
   * runs after "done") reported a failure — e.g. an embedding
   * dimension mismatch. Non-fatal: the run is still "complete".
   */
  readonly indexWarning: string | null;
}

export interface UsePipelineProgressResult extends PipelineProgressState {
  readonly openModal: () => void;
  readonly startRun: (trigger?: string, mode?: string) => Promise<void>;
  readonly cancelRun: () => Promise<void>;
  readonly closeModal: () => void;
  readonly retry: () => void;
}

// ---------------------------------------------------------------------------
// Initial state
// ---------------------------------------------------------------------------

const INITIAL_STATE: PipelineProgressState = {
  step: "idle",
  estimate: null,
  plan: null,
  currentModel: null,
  stepIndex: 0,
  totalSteps: 0,
  elapsedSeconds: 0,
  completedModels: [],
  error: null,
  runId: null,
  durationSeconds: null,
  indexWarning: null,
};

// ---------------------------------------------------------------------------
// Hook
// ---------------------------------------------------------------------------

export function usePipelineProgress(): UsePipelineProgressResult {
  const [state, setState] = useState<PipelineProgressState>(INITIAL_STATE);
  const unlistenRef = useRef<UnlistenFn | null>(null);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const startTimeRef = useRef<number>(0);
  const mountedRef = useRef(true);

  // Track mount state
  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  // Clean up event listener
  const cleanupListener = useCallback(() => {
    if (unlistenRef.current) {
      unlistenRef.current();
      unlistenRef.current = null;
    }
  }, []);

  // Clean up elapsed timer
  const cleanupTimer = useCallback(() => {
    if (timerRef.current) {
      clearInterval(timerRef.current);
      timerRef.current = null;
    }
  }, []);

  // Clean up everything on unmount
  useEffect(() => {
    return () => {
      cleanupListener();
      cleanupTimer();
    };
  }, [cleanupListener, cleanupTimer]);

  // ------------------------------------------------------------------
  // openModal — fetch estimation
  // ------------------------------------------------------------------

  const openModal = useCallback(() => {
    // If the pipeline is running in the background, restore the modal.
    if (state.step === "minimized") {
      setState((prev) => ({ ...prev, step: "processing" }));
      return;
    }

    setState({ ...INITIAL_STATE, step: "estimating" });

    Promise.all([
      dedupInvoke<PipelineStatus>("get_pipeline_status"),
      dedupInvoke<RefreshPlanData>("get_refresh_plan").catch(
        () => null,
      ),
    ])
      .then(([status, plan]) => {
        if (mountedRef.current) {
          setState((prev) => ({
            ...prev,
            step: "estimate",
            estimate: status,
            plan,
          }));
        }
      })
      .catch((err) => {
        if (mountedRef.current) {
          setState((prev) => ({
            ...prev,
            step: "error",
            error:
              err instanceof Error
                ? err.message
                : "Failed to fetch pipeline status",
          }));
        }
      });
  }, []);

  // ------------------------------------------------------------------
  // startRun — begin streaming pipeline execution
  // ------------------------------------------------------------------

  const startRun = useCallback(
    async (trigger: string = "manual", mode: string = "full") => {
      cleanupListener();
      cleanupTimer();

      startTimeRef.current = Date.now();
      setState((prev) => ({
        ...prev,
        step: "processing",
        currentModel: null,
        stepIndex: 0,
        totalSteps: prev.estimate?.estimated_refresh_time
          ? prev.totalSteps
          : 13,
        elapsedSeconds: 0,
        completedModels: [],
        error: null,
        runId: null,
        durationSeconds: null,
        indexWarning: null,
      }));

      // Start elapsed timer (1s tick)
      timerRef.current = setInterval(() => {
        if (mountedRef.current) {
          setState((prev) => {
            if (prev.step !== "processing" && prev.step !== "minimized") return prev;
            return {
              ...prev,
              elapsedSeconds: Math.round(
                (Date.now() - startTimeRef.current) / 1000,
              ),
            };
          });
        }
      }, 1000);

      // Set up event listener BEFORE invoking command
      unlistenRef.current = await listen<PipelineProgressEvent>(
        "pipeline-progress",
        (event) => {
          if (!mountedRef.current) return;
          const chunk = event.payload;

          switch (chunk.type) {
            case "started":
              setState((prev) => ({
                ...prev,
                totalSteps: chunk.total_steps,
              }));
              break;

            case "sqlmesh_running":
              setState((prev) => ({
                ...prev,
                currentModel: "SQLMesh pipeline",
                totalSteps: chunk.total_steps,
              }));
              break;

            case "model_start":
              setState((prev) => ({
                ...prev,
                currentModel: chunk.model_name,
                totalSteps: chunk.total_steps,
              }));
              break;

            case "model_complete":
              setState((prev) => ({
                ...prev,
                stepIndex: chunk.step_index,
                totalSteps: chunk.total_steps,
                completedModels: [
                  ...prev.completedModels,
                  {
                    model: chunk.model_name ?? "unknown",
                    rows: chunk.rows_processed ?? 0,
                  },
                ],
              }));
              break;

            case "done":
              // Marts are done, but the vector/graph re-index runs
              // *after* this event. Keep the listener alive so a
              // reindex_error can still surface as a warning; the
              // listener is torn down by closeModal / startRun / unmount.
              cleanupTimer();
              setState((prev) => ({
                ...prev,
                step: "complete",
                stepIndex: chunk.total_steps,
                runId: chunk.run_id ?? null,
                durationSeconds: chunk.duration_seconds ?? null,
                elapsedSeconds: Math.round(
                  (Date.now() - startTimeRef.current) / 1000,
                ),
              }));
              break;

            case "reindex_error":
            case "graph_reindex_error":
              // Non-fatal: the run stays "complete"; we just annotate it
              // so the modal can show that an index stage failed.
              setState((prev) => ({
                ...prev,
                indexWarning: chunk.error ?? "Index update failed",
              }));
              break;

            case "cancelled":
              cleanupTimer();
              cleanupListener();
              setState((prev) => ({
                ...prev,
                step: "cancelled",
                elapsedSeconds: Math.round(
                  (Date.now() - startTimeRef.current) / 1000,
                ),
              }));
              break;

            case "error":
              cleanupTimer();
              cleanupListener();
              setState((prev) => ({
                ...prev,
                step: "error",
                error: chunk.error ?? "Pipeline execution failed",
              }));
              break;

            case "plan":
              setState((prev) => ({
                ...prev,
                plan: chunk as unknown as RefreshPlanData,
              }));
              break;
          }
        },
      );

      // Fire the streaming command (now returns PipelineRunStarted)
      try {
        const started = await invoke<PipelineRunStarted>(
          "trigger_pipeline_run_stream",
          { trigger, mode },
        );
        if (mountedRef.current) {
          setState((prev) => ({ ...prev, runId: started.run_id }));
        }
      } catch (err) {
        cleanupTimer();
        cleanupListener();
        if (mountedRef.current) {
          setState((prev) => ({
            ...prev,
            step: "error",
            error:
              err instanceof Error
                ? err.message
                : typeof err === "string"
                  ? err
                  : "Failed to start pipeline run",
          }));
        }
      }
    },
    [cleanupListener, cleanupTimer],
  );

  // ------------------------------------------------------------------
  // cancelRun — send SIGTERM to the worker
  // ------------------------------------------------------------------

  const cancelRun = useCallback(async () => {
    try {
      await invoke("cancel_pipeline_run");
    } catch {
      // Process may have already exited — ignore.
    }
  }, []);

  // ------------------------------------------------------------------
  // closeModal — reset and notify widgets
  // ------------------------------------------------------------------

  const closeModal = useCallback(() => {
    if (state.step === "processing") {
      // Hide the modal but keep the pipeline running and listener active.
      // The user can reopen via openModal which will restore "processing".
      setState((prev) => ({ ...prev, step: "minimized" }));
      return;
    }

    cleanupListener();
    cleanupTimer();
    const wasComplete = state.step === "complete";
    setState(INITIAL_STATE);

    // Notify widgets to re-fetch after a successful run
    if (wasComplete) {
      window.dispatchEvent(new CustomEvent("arandu:pipeline-refreshed"));
    }
  }, [cleanupListener, cleanupTimer, state.step]);

  // ------------------------------------------------------------------
  // retry — restart the run
  // ------------------------------------------------------------------

  const retry = useCallback(() => {
    startRun();
  }, [startRun]);

  return {
    ...state,
    openModal,
    startRun,
    cancelRun,
    closeModal,
    retry,
  };
}

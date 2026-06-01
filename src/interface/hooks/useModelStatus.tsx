/**
 * Shared local-model status, exposed via Context so every consumer
 * (Sidebar indicator, Chat-header indicator, the global error banner)
 * reads one probe instead of each running its own polling loop.
 *
 * Combines three signals:
 *  - the `ollama-preload` background task (present while the configured
 *    model is being pulled and/or loaded into memory),
 *  - `get_ollama_status` (server reachability + whether the configured
 *    chat model is available locally), and
 *  - `get_model_pull_progress` (live download percent while a pull runs).
 *
 * Detection keys on the task `id` ("ollama-preload"), not its label, so it
 * is robust to label changes.
 *
 * Mount <ModelStatusProvider> once (App's post-onboarding tree); consumers
 * call useModelStatus(). Outside a provider the hook falls back to a safe
 * "unknown" status with a no-op refresh.
 *
 * sensitivity_tier: 1 (infrastructure — model name and status only)
 */

import {
  useState,
  useEffect,
  useCallback,
  createContext,
  useContext,
  type ReactNode,
} from "react";
import { invoke } from "@tauri-apps/api/core";
import { useBackgroundTasks } from "./useBackgroundTasks";

export type ModelState =
  | "loading" // pulling/loading the model into memory
  | "ready" // server reachable and model available
  | "missing" // server reachable but model not pulled
  | "offline" // server reachable check ran, server is down
  | "backend-error" // the status probe itself could not run
  | "unknown"; // not yet probed

interface OllamaStatusResponse {
  readonly server_reachable: boolean;
  readonly chat_model: string;
  readonly chat_model_status: string;
  /** Set only when the probe itself failed (CLI crash / bad output). */
  readonly probe_error?: string | null;
}

interface PullProgress {
  readonly model: string;
  readonly status: string;
  readonly completed: number;
  readonly total: number;
  readonly percent: number;
}

export interface ModelStatus {
  readonly state: ModelState;
  readonly model: string;
  /** Download percent (0–100) while a pull is in flight, else null. */
  readonly percent: number | null;
  /** Human-readable detail for error states (offline / backend-error). */
  readonly detail: string | null;
  /** Force an immediate status re-probe (used by the banner's Retry). */
  readonly refresh: () => void;
}

const PRELOAD_TASK_ID = "ollama-preload";
const STATUS_POLL_MS = 5_000;
const PROGRESS_POLL_MS = 1_500;

const UNKNOWN_STATUS: ModelStatus = {
  state: "unknown",
  model: "",
  percent: null,
  detail: null,
  refresh: () => {},
};

const ModelStatusContext = createContext<ModelStatus>(UNKNOWN_STATUS);

/**
 * Runs the single polling loop and derives the shared model status.
 * Internal to this module — mount it via <ModelStatusProvider>.
 */
function useModelStatusProbe(): ModelStatus {
  const tasks = useBackgroundTasks();
  const [status, setStatus] = useState<OllamaStatusResponse | null>(null);
  const [progress, setProgress] = useState<PullProgress | null>(null);

  const probe = useCallback(async () => {
    try {
      const result = await invoke<OllamaStatusResponse>("get_ollama_status");
      setStatus(result);
    } catch {
      // The IPC call itself failed (backend not ready yet) — leave prior
      // status in place rather than flashing an error during startup.
    }
  }, []);

  useEffect(() => {
    probe();
    const timer = setInterval(probe, STATUS_POLL_MS);
    return () => clearInterval(timer);
  }, [probe]);

  useEffect(() => {
    let cancelled = false;
    const poll = async () => {
      try {
        const result = await invoke<PullProgress | null>(
          "get_model_pull_progress",
        );
        if (!cancelled) setProgress(result);
      } catch {
        // Ignore — no active pull.
      }
    };
    poll();
    const timer = setInterval(poll, PROGRESS_POLL_MS);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, []);

  const downloading = progress !== null;
  const preparing = downloading || tasks.some((t) => t.id === PRELOAD_TASK_ID);
  const model = progress?.model || status?.chat_model || "";

  let state: ModelState;
  let detail: string | null = null;
  if (preparing) {
    state = "loading";
  } else if (!status) {
    state = "unknown";
  } else if (status.probe_error) {
    // The probe couldn't run — a setup/backend problem, not a down server.
    state = "backend-error";
    detail = status.probe_error;
  } else if (!status.server_reachable) {
    state = "offline";
    detail = "Arandu can't reach your local Ollama server.";
  } else if (status.chat_model_status === "available") {
    state = "ready";
  } else if (status.chat_model_status === "not_found") {
    state = "missing";
  } else {
    state = "offline";
    detail = "The local model is unavailable.";
  }

  return {
    state,
    model,
    percent: downloading ? progress.percent : null,
    detail,
    refresh: probe,
  };
}

/**
 * Provides one shared model-status probe to all descendants. Mount once,
 * high enough to cover every consumer (Layout + routed pages).
 */
export function ModelStatusProvider({ children }: { children: ReactNode }) {
  const status = useModelStatusProbe();
  return (
    <ModelStatusContext.Provider value={status}>
      {children}
    </ModelStatusContext.Provider>
  );
}

/** Read the shared model status. Safe (returns "unknown") outside a provider. */
export function useModelStatus(): ModelStatus {
  return useContext(ModelStatusContext);
}

/**
 * Hook exposing a simple "is the local model ready?" state for status
 * indicators (Sidebar, Chat header).
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
 * sensitivity_tier: 1 (infrastructure — model name and status only)
 */

import { useState, useEffect } from "react";
import { invoke } from "@tauri-apps/api/core";
import { useBackgroundTasks } from "./useBackgroundTasks";

export type ModelState =
  | "loading" // pulling/loading the model into memory
  | "ready" // server reachable and model available
  | "missing" // server reachable but model not pulled
  | "offline" // server unreachable
  | "unknown"; // not yet probed

interface OllamaStatusResponse {
  readonly server_reachable: boolean;
  readonly chat_model: string;
  readonly chat_model_status: string;
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
}

const PRELOAD_TASK_ID = "ollama-preload";
const STATUS_POLL_MS = 5_000;
const PROGRESS_POLL_MS = 1_500;

export function useModelStatus(): ModelStatus {
  const tasks = useBackgroundTasks();
  const [status, setStatus] = useState<OllamaStatusResponse | null>(null);
  const [progress, setProgress] = useState<PullProgress | null>(null);

  useEffect(() => {
    let cancelled = false;
    const poll = async () => {
      try {
        const result = await invoke<OllamaStatusResponse>("get_ollama_status");
        if (!cancelled) setStatus(result);
      } catch {
        // Backend may not be ready yet — leave prior status in place.
      }
    };
    poll();
    const timer = setInterval(poll, STATUS_POLL_MS);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, []);

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
  if (preparing) {
    state = "loading";
  } else if (!status) {
    state = "unknown";
  } else if (!status.server_reachable) {
    state = "offline";
  } else if (status.chat_model_status === "available") {
    state = "ready";
  } else if (status.chat_model_status === "not_found") {
    state = "missing";
  } else {
    state = "offline";
  }

  return { state, model, percent: downloading ? progress.percent : null };
}

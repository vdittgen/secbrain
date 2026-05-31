/**
 * Hook for polling active background tasks from the Rust backend.
 *
 * Polls every 3 seconds while the component is mounted and returns
 * the current list of running tasks with their elapsed time.
 *
 * sensitivity_tier: 1 (infrastructure)
 */

import { useState, useEffect, useRef } from "react";
import { invoke } from "@tauri-apps/api/core";

export interface BackgroundTask {
  readonly id: string;
  readonly label: string;
  readonly started_at: string;
}

const POLL_INTERVAL_MS = 3_000;

export function useBackgroundTasks(): readonly BackgroundTask[] {
  const [tasks, setTasks] = useState<readonly BackgroundTask[]>([]);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    let cancelled = false;

    const poll = async () => {
      try {
        const result = await invoke<BackgroundTask[]>("get_active_tasks");
        if (!cancelled) setTasks(result);
      } catch {
        // Silently ignore — backend may not be ready yet
      }
    };

    poll();
    timerRef.current = setInterval(poll, POLL_INTERVAL_MS);

    return () => {
      cancelled = true;
      if (timerRef.current) clearInterval(timerRef.current);
    };
  }, []);

  return tasks;
}

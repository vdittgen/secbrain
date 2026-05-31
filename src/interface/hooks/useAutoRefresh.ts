/**
 * Hook for automatic background pipeline refreshes.
 *
 * Reads settings, schedules interval-based refreshes, and handles
 * refresh-on-launch. Background runs use smart mode so auto refreshes
 * prioritize high-interest models by default.
 *
 * sensitivity_tier: 1
 */

import { useEffect, useRef, useCallback } from "react";
import { useAsyncData } from "./useAsyncData";
import { dedupInvoke } from "../utils/requestDedup";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface AppSettings {
  readonly auto_refresh_enabled: boolean;
  readonly auto_refresh_interval_minutes: number;
  readonly refresh_on_launch: boolean;
}

// ---------------------------------------------------------------------------
// Hook
// ---------------------------------------------------------------------------

export function useAutoRefresh(): void {
  const settingsResult = useAsyncData<AppSettings>(
    useCallback(() => dedupInvoke<AppSettings>("get_settings"), []),
  );

  const launchDoneRef = useRef(false);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  /** Trigger a background smart pipeline run (no modal). */
  const triggerBackground = useCallback(async () => {
    try {
      await dedupInvoke("trigger_pipeline_run_stream", {
        trigger: "auto",
        mode: "smart",
      });
      // The usePipelineStatus hook polls every 30s and will detect
      // the new run. After completion, the status poll picks up
      // the updated staleness/freshness.
    } catch {
      // Silent failure for background refreshes — no user impact.
    }
  }, []);

  // -- Refresh on launch: 30s after mount ------------------------------------

  useEffect(() => {
    const settings = settingsResult.data;
    if (!settings?.refresh_on_launch || launchDoneRef.current) return;

    const timer = setTimeout(() => {
      launchDoneRef.current = true;
      triggerBackground();
    }, 30_000);

    return () => clearTimeout(timer);
  }, [settingsResult.data, triggerBackground]);

  // -- Scheduled refresh interval --------------------------------------------

  useEffect(() => {
    const settings = settingsResult.data;

    // Clear any existing interval
    if (intervalRef.current) {
      clearInterval(intervalRef.current);
      intervalRef.current = null;
    }

    if (!settings?.auto_refresh_enabled) return;

    const ms = settings.auto_refresh_interval_minutes * 60 * 1000;
    intervalRef.current = setInterval(triggerBackground, ms);

    return () => {
      if (intervalRef.current) {
        clearInterval(intervalRef.current);
        intervalRef.current = null;
      }
    };
  }, [settingsResult.data, triggerBackground]);
}

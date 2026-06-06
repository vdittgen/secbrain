/**
 * Hook for the unified system-health surface.
 *
 * Polls the `get_system_health` aggregator (single backend payload that
 * composes connector / pipeline / graph / vector state) and exposes the
 * overall verdict, the data-flow stages, and the actionable issue list.
 * This is the one source of truth the TopBar indicator + Health panel
 * read, replacing the previously-scattered status hooks.
 *
 * sensitivity_tier: 1 (infrastructure metrics only)
 */

import { useState, useEffect, useCallback, useRef } from "react";
import { dedupInvoke } from "../utils/requestDedup";
import type { StageStatus, Overall } from "../utils/healthStatus";

export interface HealthAction {
  readonly label: string;
  readonly kind:
    | "retry_connector"
    | "run_pipeline"
    | "run_migrate"
    | "open_route";
  readonly target: string | null;
}

export interface HealthIssue {
  readonly id: string;
  readonly stage: string;
  readonly severity: "warning" | "error";
  readonly title: string;
  readonly detail: string;
  readonly action?: HealthAction | null;
}

export interface HealthStage {
  readonly id: string;
  readonly label: string;
  readonly status: StageStatus;
  readonly summary: string;
  readonly last_run_at: string | null;
  readonly route: string;
}

export interface SystemHealth {
  readonly overall: Overall;
  readonly stages: readonly HealthStage[];
  readonly issues: readonly HealthIssue[];
}

const POLL_MS = 30_000;

export interface SystemHealthHook {
  readonly health: SystemHealth | null;
  readonly overall: Overall | null;
  readonly stages: readonly HealthStage[];
  readonly issues: readonly HealthIssue[];
  readonly errorCount: number;
  readonly warnCount: number;
  readonly refetch: () => void;
}

export function useSystemHealth(): SystemHealthHook {
  const [health, setHealth] = useState<SystemHealth | null>(null);
  const mountedRef = useRef(true);

  const refetch = useCallback(async () => {
    try {
      const h = await dedupInvoke<SystemHealth>("get_system_health");
      if (mountedRef.current) setHealth(h);
    } catch {
      // Leave the last good value; the indicator stays neutral on failure.
    }
  }, []);

  useEffect(() => {
    mountedRef.current = true;
    refetch();
    const interval = setInterval(refetch, POLL_MS);
    const onRefreshed = () => refetch();
    window.addEventListener("arandu:pipeline-refreshed", onRefreshed);
    return () => {
      mountedRef.current = false;
      clearInterval(interval);
      window.removeEventListener("arandu:pipeline-refreshed", onRefreshed);
    };
  }, [refetch]);

  const issues = health?.issues ?? [];
  return {
    health,
    overall: health?.overall ?? null,
    stages: health?.stages ?? [],
    issues,
    errorCount: issues.filter((i) => i.severity === "error").length,
    warnCount: issues.filter((i) => i.severity === "warning").length,
    refetch,
  };
}

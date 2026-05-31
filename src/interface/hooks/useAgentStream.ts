/**
 * Agent stream hook — live agent activity for the Mission Control panel.
 *
 * Polls every 5s while there are running tasks; backs off to 30s when
 * everything is idle. Cleaned up on unmount.
 *
 * sensitivity_tier: 2
 */

import { useCallback, useEffect, useRef } from "react";
import { dedupInvoke } from "../utils/requestDedup";
import { useAsyncData, type AsyncDataResult } from "./useAsyncData";

export interface AgentProgress {
  readonly current: number;
  readonly total: number;
  readonly eta_seconds: number | null;
}

export interface AgentRunning {
  readonly task_id: string;
  readonly agent_name: string;
  readonly label: string;
  readonly progress: AgentProgress | null;
  readonly started_at: string;
}

export interface AgentReview {
  readonly id: string;
  readonly agent_name: string;
  readonly summary: string;
  readonly kind: "reply" | "insight";
  readonly payload_ref: string;
}

export interface AgentCompleted {
  readonly id: string;
  readonly agent_name: string;
  readonly summary: string;
  readonly finished_at: string;
}

export interface AgentStream {
  readonly running: ReadonlyArray<AgentRunning>;
  readonly awaiting_review: ReadonlyArray<AgentReview>;
  readonly recently_completed: ReadonlyArray<AgentCompleted>;
}

const FAST_POLL_MS = 5_000;
const SLOW_POLL_MS = 30_000;

export function useAgentStream(): AsyncDataResult<AgentStream> {
  const fetcher = useCallback(
    () => dedupInvoke<AgentStream>("get_agent_stream"),
    [],
  );
  const result = useAsyncData<AgentStream>(fetcher);
  const { refetch, data } = result;
  const runningCount = data?.running.length ?? 0;
  const refetchRef = useRef(refetch);
  refetchRef.current = refetch;

  useEffect(() => {
    const interval = runningCount > 0 ? FAST_POLL_MS : SLOW_POLL_MS;
    const id = window.setInterval(() => refetchRef.current(), interval);
    return () => window.clearInterval(id);
  }, [runningCount]);

  return result;
}

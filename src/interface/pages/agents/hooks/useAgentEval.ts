// Hook: fetch + poll the latest eval run for a single agent.
//
// sensitivity_tier: 1

import { useCallback, useEffect, useRef, useState } from "react";
import { dedupInvoke } from "../../../utils/requestDedup";
import type {
  AgentEvalRun,
  AgentEvalStatusResponse,
} from "../../../types/agents";
import { POLL_INTERVAL_MS, POLL_TIMEOUT_MS } from "../shared/constants";

interface EvalState {
  readonly run: AgentEvalRun | null;
  readonly loading: boolean;
  readonly polling: boolean;
}

export interface UseAgentEval extends EvalState {
  readonly refresh: () => Promise<void>;
  readonly poll: () => Promise<void>;
}

export function useAgentEval(agentId: string, refreshKey = 0): UseAgentEval {
  const [run, setRun] = useState<AgentEvalRun | null>(null);
  const [loading, setLoading] = useState(true);
  const [polling, setPolling] = useState(false);
  const pollingRef = useRef(false);

  const fetchLatest = useCallback(async () => {
    if (!agentId) return null;
    const resp = await dedupInvoke<AgentEvalStatusResponse>(
      "get_agent_eval_status",
      { agentId, limit: 1 },
    );
    setRun(resp.latest);
    return resp.latest;
  }, [agentId]);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      await fetchLatest();
    } finally {
      setLoading(false);
    }
  }, [fetchLatest]);

  useEffect(() => {
    void refresh();
  }, [refresh, refreshKey]);

  const poll = useCallback(async () => {
    if (pollingRef.current) return;
    pollingRef.current = true;
    setPolling(true);
    const start = Date.now();
    try {
      while (Date.now() - start < POLL_TIMEOUT_MS) {
        const latest = await fetchLatest();
        if (
          latest && latest.status !== "pending" && latest.status !== "running"
        ) {
          return;
        }
        await new Promise((r) => setTimeout(r, POLL_INTERVAL_MS));
      }
    } finally {
      pollingRef.current = false;
      setPolling(false);
    }
  }, [fetchLatest]);

  return { run, loading, polling, refresh, poll };
}

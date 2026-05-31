/**
 * Daily brief hook — server-cached LLM synthesis of today.
 *
 * The backend caches the brief by (date, last pipeline completed_at).
 * Mounting this hook does NOT trigger an LLM call when the cache is
 * fresh; only `regenerate()` forces a new synthesis.
 *
 * sensitivity_tier: 3
 */

import { useCallback } from "react";
import { dedupInvoke } from "../utils/requestDedup";
import { useAsyncData, type AsyncDataResult } from "./useAsyncData";

export interface BriefSourceCounts {
  readonly events: number;
  readonly threads: number;
  readonly pending_replies: number;
  readonly actionable_events: number;
}

export interface DailyBrief {
  readonly brief: string;
  readonly generated_at: string;
  readonly source_counts: BriefSourceCounts;
}

export interface DailyBriefResult extends AsyncDataResult<DailyBrief> {
  /** Force a fresh LLM call and refresh the cache. */
  readonly regenerate: () => Promise<void>;
}

export function useDailyBrief(): DailyBriefResult {
  const fetcher = useCallback(
    () => dedupInvoke<DailyBrief>("get_daily_brief"),
    [],
  );
  const result = useAsyncData<DailyBrief>(fetcher);
  const { refetch } = result;
  const regenerate = useCallback(async () => {
    await dedupInvoke<DailyBrief>("get_daily_brief", { force: true });
    refetch();
  }, [refetch]);
  return { ...result, regenerate };
}

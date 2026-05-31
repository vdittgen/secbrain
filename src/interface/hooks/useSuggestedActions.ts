/**
 * Suggested actions hook — Command Bar chips derived from current state.
 *
 * Pure template generation server-side; no LLM call. Refetches on
 * pipeline-refresh so chips reflect the user's freshest data.
 *
 * sensitivity_tier: 2
 */

import { useCallback } from "react";
import { dedupInvoke } from "../utils/requestDedup";
import { useAsyncData, type AsyncDataResult } from "./useAsyncData";

export interface SuggestedChip {
  readonly label: string;
  readonly prefilled_prompt: string;
}

export interface SuggestedActions {
  readonly chips: ReadonlyArray<SuggestedChip>;
}

export function useSuggestedActions(): AsyncDataResult<SuggestedActions> {
  const fetcher = useCallback(
    () => dedupInvoke<SuggestedActions>("get_suggested_actions"),
    [],
  );
  return useAsyncData<SuggestedActions>(fetcher);
}

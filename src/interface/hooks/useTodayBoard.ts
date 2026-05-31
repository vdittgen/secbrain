/**
 * Hook for the Mission Control "Today" board.
 *
 * Mirrors `src-tauri/src/commands/types.rs::TodayBoard`. Slices the
 * persisted daily schedule into Now / Up Next / Loops in the Python
 * CLI handler, so this hook is a thin async wrapper.
 *
 * sensitivity_tier: 3
 */

import { useCallback } from "react";
import { dedupInvoke } from "../utils/requestDedup";
import { useAsyncData, type AsyncDataResult } from "./useAsyncData";
import type { ScheduleSlot } from "./useDailySchedule";

export interface TodayLoop {
  readonly id: string;
  readonly kind: string;
  readonly label: string;
  readonly context: string;
  readonly importance: number;
  readonly age_days: number;
  readonly source?: string | null;
  readonly message_id?: string | null;
  readonly contact_name?: string | null;
}

export interface TodayBoard {
  readonly now: ReadonlyArray<ScheduleSlot>;
  readonly up_next: ReadonlyArray<ScheduleSlot>;
  readonly todays_loops: ReadonlyArray<TodayLoop>;
  readonly rationale: string;
  readonly schedule_date: string | null;
}

export function useTodayBoard(): AsyncDataResult<TodayBoard> {
  const fetcher = useCallback(
    () => dedupInvoke<TodayBoard>("get_today_board"),
    [],
  );
  return useAsyncData<TodayBoard>(fetcher);
}

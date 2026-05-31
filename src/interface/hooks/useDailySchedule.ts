/**
 * Hook for the daily schedule.
 *
 * Mirrors `src-tauri/src/commands/types.rs::DailySchedule`.
 *
 * sensitivity_tier: 2
 */

import { useCallback } from "react";
import { invoke } from "@tauri-apps/api/core";
import { dedupInvoke } from "../utils/requestDedup";
import { useAsyncData, type AsyncDataResult } from "./useAsyncData";
import type { GoalCategory } from "./useGoals";

export type ScheduleSlotKind = "event" | "task" | "habit";

export interface ScheduleSlot {
  readonly kind: ScheduleSlotKind;
  readonly ref_id: string;
  readonly title: string;
  readonly start: string;
  readonly end: string;
  readonly why: string;
  readonly category: GoalCategory | null;
  readonly goal_id: string | null;
  readonly goal_title: string | null;
}

export interface DailySchedule {
  readonly schedule_date: string;
  readonly slots: ReadonlyArray<ScheduleSlot>;
  readonly unscheduled_overflow: ReadonlyArray<string>;
  readonly rationale: string;
  readonly category_balance: Readonly<Record<string, number>>;
  readonly generated_at: string;
  readonly sensitivity_tier: number;
}

export function useDailySchedule(
  scheduleDate?: string,
): AsyncDataResult<DailySchedule | null> {
  const fetcher = useCallback(
    () =>
      dedupInvoke<DailySchedule | null>("get_daily_schedule", {
        scheduleDate: scheduleDate ?? null,
      }),
    [scheduleDate],
  );
  return useAsyncData<DailySchedule | null>(fetcher);
}

export async function regenerateDailySchedule(
  scheduleDate?: string,
): Promise<DailySchedule | null> {
  return invoke<DailySchedule | null>("regenerate_daily_schedule", {
    scheduleDate: scheduleDate ?? null,
  });
}

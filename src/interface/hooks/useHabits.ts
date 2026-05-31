/**
 * Hooks for habits — atomic-habits style, each anchored to a goal.
 *
 * Mirrors `src-tauri/src/commands/types.rs::Habit`.
 *
 * sensitivity_tier: 1
 */

import { useCallback } from "react";
import { invoke } from "@tauri-apps/api/core";
import { dedupInvoke } from "../utils/requestDedup";
import { useAsyncData, type AsyncDataResult } from "./useAsyncData";

export type HabitCadence = "daily" | "weekly" | "specific_days";
export type HabitWindow = "morning" | "midday" | "evening" | "any";
export type HabitDay = "mon" | "tue" | "wed" | "thu" | "fri" | "sat" | "sun";

export interface Habit {
  readonly id: string;
  readonly title: string;
  readonly goal_id: string;
  readonly cadence: HabitCadence;
  readonly days_of_week: ReadonlyArray<HabitDay | string>;
  readonly preferred_window: HabitWindow;
  readonly why: string;
  readonly source: "user" | "brain";
  readonly status: "active" | "paused";
  readonly created_at: string;
  readonly sensitivity_tier: number;
}

export interface HabitCreatePayload {
  readonly title: string;
  readonly goal_id: string;
  readonly cadence?: HabitCadence;
  readonly days_of_week?: ReadonlyArray<HabitDay | string>;
  readonly preferred_window?: HabitWindow;
  readonly why?: string;
}

export function useHabits(
  filters: { status?: "active" | "paused" | null; goal_id?: string | null } = {
    status: "active",
  },
): AsyncDataResult<Habit[]> {
  const { status, goal_id } = filters;
  const fetcher = useCallback(
    () =>
      dedupInvoke<Habit[]>("list_habits", {
        status: status ?? null,
        goalId: goal_id ?? null,
      }),
    [status, goal_id],
  );
  return useAsyncData<Habit[]>(fetcher);
}

export async function createHabit(
  payload: HabitCreatePayload,
): Promise<Habit> {
  return invoke<Habit>("create_habit", { payload });
}

export async function toggleHabit(id: string): Promise<void> {
  await invoke("toggle_habit", { id });
}

export async function deleteHabit(id: string): Promise<void> {
  await invoke("delete_habit", { id });
}

export async function regenerateHabits(): Promise<Habit[]> {
  return invoke<Habit[]>("regenerate_habits");
}

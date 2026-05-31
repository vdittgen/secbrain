/**
 * Hook for per-goal progress: rolled-up topics, tasks due today, open
 * task count, 7-day evidence, habit streak. Mirrors
 * `src-tauri/src/commands/types.rs::GoalProgress`.
 *
 * sensitivity_tier: 3
 */

import { useCallback } from "react";
import { dedupInvoke } from "../utils/requestDedup";
import { useAsyncData, type AsyncDataResult } from "./useAsyncData";
import type { Task } from "./useTasks";
import type { Habit } from "./useHabits";

export interface GoalTopic {
  readonly topic_id: string;
  readonly title: string;
  readonly importance: number;
  readonly last_activity: string | null;
  readonly contact_name: string | null;
}

export interface GoalProgress {
  readonly goal_id: string;
  readonly rolled_up_topics: ReadonlyArray<GoalTopic>;
  readonly tasks_today: ReadonlyArray<Task>;
  readonly tasks_open: number;
  readonly overdue_tasks: number;
  readonly tasks_done_7d: number;
  readonly habits_today: ReadonlyArray<Habit>;
  readonly habit_streak_days: number;
  readonly last_evidence_at: string | null;
}

export function useGoalProgress(
  goalId: string | null,
): AsyncDataResult<GoalProgress | null> {
  const fetcher = useCallback(
    () =>
      goalId
        ? dedupInvoke<GoalProgress>("get_goal_progress", { goalId })
        : Promise.resolve(null),
    [goalId],
  );
  return useAsyncData<GoalProgress | null>(fetcher);
}

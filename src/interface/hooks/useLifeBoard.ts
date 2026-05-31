/**
 * Hook for the unified LifeBoard — goals + today's actions + domain
 * shape per Work / Personal / Health column in one IPC call.
 *
 * Replaces the previous pattern of stitching `useGoals` together with
 * three `useDomainSummary` calls on the client. Goals come pre-sorted
 * by `urgency_score` (most pressing first); `today_actions` rolls up
 * every active goal's `tasks_today` + `habits_today` so the dashboard
 * can render the day's concrete moves next to that domain's events.
 *
 * sensitivity_tier: 3
 */

import { useCallback } from "react";
import { dedupInvoke } from "../utils/requestDedup";
import { useAsyncData, type AsyncDataResult } from "./useAsyncData";
import type { Goal } from "./useGoals";
import type { DomainItem, DomainOpenLoop } from "./useDomainSummary";

export type LifeBoardDomainName = "work" | "personal" | "health";

export interface TodayAction {
  readonly id: string;
  readonly kind: "task" | "habit";
  readonly title: string;
  readonly goal_id: string;
  readonly goal_title: string;
  readonly when: string | null;
  readonly preferred_window: string | null;
}

export interface TodayProgress {
  readonly total: number;
  readonly done: number;
}

export interface LifeBoardDomain {
  readonly domain: LifeBoardDomainName;
  readonly goals: ReadonlyArray<Goal>;
  readonly today_actions: ReadonlyArray<TodayAction>;
  readonly today_progress: Readonly<Record<string, TodayProgress>>;
  readonly items: ReadonlyArray<DomainItem>;
  readonly open_loops: ReadonlyArray<DomainOpenLoop>;
}

export interface LifeBoard {
  readonly domains: ReadonlyArray<LifeBoardDomain>;
}

export function useLifeBoard(): AsyncDataResult<LifeBoard> {
  const fetcher = useCallback(
    () => dedupInvoke<LifeBoard>("get_life_board"),
    [],
  );
  return useAsyncData<LifeBoard>(fetcher);
}

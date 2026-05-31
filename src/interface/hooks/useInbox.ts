/**
 * Hook for the unified inbox: pending replies + tasks + habits.
 *
 * Mirrors `src-tauri/src/commands/types.rs::Inbox`. The inbox is the
 * single action surface for all "things I need to do today" — pending
 * replies from contacts, tasks due/overdue/scheduled, and active habits.
 *
 * sensitivity_tier: 3
 */

import { useCallback } from "react";
import { invoke } from "@tauri-apps/api/core";
import { dedupInvoke } from "../utils/requestDedup";
import { useAsyncData, type AsyncDataResult } from "./useAsyncData";
import type { GoalTopic } from "./useGoalProgress";

export type InboxDomain = "work" | "personal" | "health";

export interface InboxReply {
  readonly id: string;
  readonly message_id: string;
  readonly source: string;
  readonly contact_name: string;
  readonly domain: string;
  readonly preview: string;
  readonly importance: number;
  readonly reason: string;
  readonly message_at: string;
  readonly detected_at: string;
  readonly sensitivity_tier: number;
}

export interface InboxTask {
  readonly id: string;
  readonly title: string;
  readonly goal_id: string | null;
  readonly goal_title: string | null;
  readonly category: string | null;
  readonly importance: number;
  readonly due_at: string | null;
  readonly scheduled_for: string | null;
  readonly status: string;
  readonly notes: string | null;
  readonly source: string | null;
}

export interface InboxHabit {
  readonly id: string;
  readonly title: string;
  readonly goal_id: string;
  readonly goal_title: string | null;
  readonly category: string | null;
  readonly preferred_window: string | null;
  readonly cadence: string | null;
}

export interface Inbox {
  readonly replies: ReadonlyArray<InboxReply>;
  readonly tasks: ReadonlyArray<InboxTask>;
  readonly habits: ReadonlyArray<InboxHabit>;
  readonly topics: ReadonlyArray<GoalTopic>;
}

export interface UseInboxFilters {
  readonly domain?: InboxDomain | null;
  readonly topic?: string | null;
}

export function useInbox(
  filters: UseInboxFilters = {},
): AsyncDataResult<Inbox> {
  const { domain = null, topic = null } = filters;
  const fetcher = useCallback(
    () =>
      dedupInvoke<Inbox>("list_inbox", {
        domain,
        topic,
      }),
    [domain, topic],
  );
  return useAsyncData<Inbox>(fetcher);
}

export async function dismissPendingReply(id: string): Promise<void> {
  await invoke("dismiss_pending_reply", { id });
}

export async function toggleTaskDone(taskId: string): Promise<void> {
  await invoke("toggle_task_done", { taskId });
}

export async function toggleHabit(habitId: string): Promise<void> {
  await invoke("toggle_habit", { habitId });
}

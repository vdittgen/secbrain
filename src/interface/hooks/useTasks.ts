/**
 * Hooks for tasks (and subtasks).
 *
 * Mirrors `src-tauri/src/commands/types.rs::Task`.
 *
 * sensitivity_tier: 2
 */

import { useCallback } from "react";
import { invoke } from "@tauri-apps/api/core";
import { dedupInvoke } from "../utils/requestDedup";
import { useAsyncData, type AsyncDataResult } from "./useAsyncData";

export type TaskStatus = "todo" | "in_progress" | "done" | "cancelled";
export type TaskSource = "user" | "brain" | "message" | "event";

export interface Task {
  readonly id: string;
  readonly title: string;
  readonly project_id: string | null;
  readonly parent_task_id: string | null;
  readonly goal_id: string | null;
  readonly notes: string;
  readonly status: TaskStatus;
  readonly importance: number;
  readonly due_at: string | null;
  readonly scheduled_for: string | null;
  readonly source: TaskSource;
  readonly source_ref: string | null;
  readonly completion_note: string | null;
  readonly completion_evidence_id: string | null;
  readonly completed_at: string | null;
  readonly created_at: string;
  readonly updated_at: string;
  readonly sensitivity_tier: number;
}

export interface TaskCreatePayload {
  readonly title: string;
  readonly project_id?: string | null;
  readonly parent_task_id?: string | null;
  readonly goal_id?: string | null;
  readonly notes?: string;
  readonly importance?: number;
  readonly due_at?: string | null;
}

export interface UseTasksFilters {
  readonly status?: TaskStatus | null;
  readonly project_id?: string | null;
  readonly goal_id?: string | null;
  readonly parent_task_id?: string | null;
}

export function useTasks(
  filters: UseTasksFilters = {},
): AsyncDataResult<Task[]> {
  const { status, project_id, goal_id, parent_task_id } = filters;
  const fetcher = useCallback(
    () =>
      dedupInvoke<Task[]>("list_tasks", {
        status: status ?? null,
        projectId: project_id ?? null,
        goalId: goal_id ?? null,
        parentTaskId: parent_task_id ?? null,
      }),
    [status, project_id, goal_id, parent_task_id],
  );
  return useAsyncData<Task[]>(fetcher);
}

export async function createTask(payload: TaskCreatePayload): Promise<Task> {
  return invoke<Task>("create_task", { payload });
}

export async function updateTask(
  id: string,
  patch: Record<string, unknown>,
): Promise<Task | null> {
  return invoke<Task | null>("update_task", { id, patch });
}

export async function toggleTaskDone(
  id: string,
  note?: string | null,
): Promise<Task | null> {
  return invoke<Task | null>("toggle_task_done", {
    id,
    note: note ?? null,
  });
}

export async function deleteTask(id: string): Promise<void> {
  await invoke("delete_task", { id });
}

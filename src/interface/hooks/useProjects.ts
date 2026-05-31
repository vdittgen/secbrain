/**
 * Hooks for projects.
 *
 * Mirrors `src-tauri/src/commands/types.rs::Project`.
 *
 * sensitivity_tier: 2
 */

import { useCallback } from "react";
import { invoke } from "@tauri-apps/api/core";
import { dedupInvoke } from "../utils/requestDedup";
import { useAsyncData, type AsyncDataResult } from "./useAsyncData";
import type { GoalCategory } from "./useGoals";

export interface Project {
  readonly id: string;
  readonly name: string;
  readonly category: GoalCategory;
  readonly topic_id: string | null;
  readonly goal_id: string | null;
  readonly status: "active" | "archived";
  readonly color: string | null;
  readonly created_at: string;
  readonly updated_at: string;
  readonly sensitivity_tier: number;
}

export interface ProjectCreatePayload {
  readonly name: string;
  readonly category?: GoalCategory;
  readonly goal_id?: string | null;
}

export function useProjects(
  filters: { status?: "active" | "archived" | null; category?: GoalCategory | null } = {
    status: "active",
  },
): AsyncDataResult<Project[]> {
  const { status, category } = filters;
  const fetcher = useCallback(
    () =>
      dedupInvoke<Project[]>("list_projects", {
        status: status ?? null,
        category: category ?? null,
      }),
    [status, category],
  );
  return useAsyncData<Project[]>(fetcher);
}

export async function createProject(
  payload: ProjectCreatePayload,
): Promise<Project> {
  return invoke<Project>("create_project", { payload });
}

export async function archiveProject(id: string): Promise<void> {
  await invoke("archive_project", { id });
}

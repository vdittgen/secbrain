/**
 * Origin of a "Work on this" click from the Inbox task/habit rows.
 * Carries the task ID and optional goal ID so the Chat agent seeds
 * the task + goal details into context and helps the user complete it.
 *
 * Mirrors `src-tauri/src/commands/types.rs::TaskContext`.
 *
 * sensitivity_tier: 2
 */

export interface TaskContext {
  readonly task_id: string;
  readonly goal_id?: string | null;
}

export function buildTaskContext(input: {
  readonly task_id?: string | null;
  readonly goal_id?: string | null;
}): TaskContext | undefined {
  if (!input.task_id) {
    return undefined;
  }
  return {
    task_id: input.task_id,
    goal_id: input.goal_id ?? null,
  };
}

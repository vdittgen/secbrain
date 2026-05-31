/**
 * Tasks page.
 *
 * Left rail: project list grouped by category. Center: tasks for the
 * selected project (or all open tasks when none selected) grouped by
 * status. Right rail: detail of the focused task — notes, evidence
 * chain, due date, parent project/goal.
 *
 * sensitivity_tier: 3
 */

import { useCallback, useMemo, useState } from "react";
import {
  AlarmClock,
  Check,
  CheckSquare,
  Clock,
  Plus,
  Quote,
  Sparkles,
  User,
  UserPlus,
} from "lucide-react";
import Card from "../components/dashboard/Card";
import { Skeleton } from "../components/LoadingState";
import {
  createTask,
  toggleTaskDone,
  useTasks,
  type Task,
} from "../hooks/useTasks";
import { useProjects, type Project } from "../hooks/useProjects";
import { useGoals, type Goal, type GoalCategory } from "../hooks/useGoals";

type TaskGroup = "today" | "this_week" | "later" | "done";

interface TaskFormState {
  title: string;
  project_id: string;
  due_at: string;
  importance: number;
}

function bucketForTask(task: Task): TaskGroup {
  if (task.status === "done") return "done";
  if (!task.due_at) return "later";
  const due = new Date(task.due_at).getTime();
  if (Number.isNaN(due)) return "later";
  const now = Date.now();
  const day = 24 * 3600 * 1000;
  if (due - now <= day) return "today";
  if (due - now <= 7 * day) return "this_week";
  return "later";
}

const GROUP_LABELS: Record<TaskGroup, string> = {
  today: "Today",
  this_week: "This week",
  later: "Later",
  done: "Done",
};

function ImportanceDot({ value }: { readonly value: number }) {
  if (value >= 8) return <span className="h-2 w-2 rounded-full bg-danger" />;
  if (value >= 5) return <span className="h-2 w-2 rounded-full bg-amber" />;
  return <span className="h-2 w-2 rounded-full bg-hairline" />;
}

function TaskRow({
  task,
  selected,
  onSelect,
  onRefetch,
}: {
  readonly task: Task;
  readonly selected: boolean;
  readonly onSelect: () => void;
  readonly onRefetch: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const toggle = useCallback(
    async (e: React.MouseEvent) => {
      e.stopPropagation();
      setBusy(true);
      try {
        await toggleTaskDone(task.id);
        onRefetch();
      } finally {
        setBusy(false);
      }
    },
    [task.id, onRefetch],
  );

  const isBrain = task.source === "brain" || task.source === "message";

  return (
    <li
      onClick={onSelect}
      className={`group flex cursor-pointer items-start gap-3 rounded-2 border p-3 ${
        selected
          ? "border-indigo bg-indigo/5"
          : "border-hairline bg-surface hover:bg-bg-2"
      } ${isBrain && task.status !== "done" ? "border-l-4 border-l-indigo" : ""}`}
    >
      <button
        type="button"
        onClick={toggle}
        disabled={busy}
        className={`mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center rounded border-2 transition-colors ${
          task.status === "done"
            ? "border-indigo bg-indigo text-white"
            : "border-muted bg-bg-2 hover:border-indigo"
        }`}
        title="Toggle done"
      >
        {task.status === "done" && <Check className="h-3 w-3" />}
      </button>
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <span
            className={`truncate text-sm ${
              task.status === "done"
                ? "text-muted line-through"
                : "text-ink"
            }`}
          >
            {task.title}
          </span>
          <ImportanceDot value={task.importance} />
        </div>
        {task.completion_note && (
          <p className="mt-0.5 text-[11px] text-muted">
            ✓ {task.completion_note}
          </p>
        )}
        {task.due_at && task.status !== "done" && (
          <p className="mt-0.5 text-[11px] text-muted">
            Due {new Date(task.due_at).toLocaleDateString()}
          </p>
        )}
        <div className="mt-1 flex items-center gap-1 text-[10px] text-muted">
          {isBrain ? (
            <Sparkles className="h-3 w-3" />
          ) : (
            <User className="h-3 w-3" />
          )}
          {task.source}
        </div>
      </div>
    </li>
  );
}

function ProjectRail({
  projects,
  selectedId,
  onSelect,
}: {
  readonly projects: ReadonlyArray<Project>;
  readonly selectedId: string | null;
  readonly onSelect: (id: string | null) => void;
}) {
  const grouped = useMemo(() => {
    const map: Record<GoalCategory, Project[]> = {
      personal: [],
      life: [],
      work: [],
    };
    for (const p of projects) {
      if (p.category in map) map[p.category as GoalCategory].push(p);
    }
    return map;
  }, [projects]);

  return (
    <Card title="Projects">
      <button
        type="button"
        onClick={() => onSelect(null)}
        className={`mb-3 w-full rounded px-2 py-1.5 text-left text-xs ${
          selectedId === null
            ? "bg-indigo-soft text-indigo"
            : "text-muted hover:text-ink"
        }`}
      >
        All open tasks
      </button>
      {(["personal", "life", "work"] as const).map((cat) => (
        <div key={cat} className="mb-3 last:mb-0">
          <p className="mb-1 text-[10px] uppercase tracking-wide text-muted">
            {cat}
          </p>
          {grouped[cat].length === 0 ? (
            <p className="text-xs text-muted/60">—</p>
          ) : (
            <ul className="space-y-0.5">
              {grouped[cat].map((p) => (
                <li key={p.id}>
                  <button
                    type="button"
                    onClick={() => onSelect(p.id)}
                    className={`w-full truncate rounded px-2 py-1 text-left text-xs ${
                      selectedId === p.id
                        ? "bg-indigo-soft text-indigo"
                        : "text-ink hover:bg-bg-2"
                    }`}
                  >
                    {p.name}
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      ))}
    </Card>
  );
}

function NewTaskModal({
  open,
  onClose,
  projects,
  defaultProjectId,
  onCreated,
}: {
  readonly open: boolean;
  readonly onClose: () => void;
  readonly projects: ReadonlyArray<Project>;
  readonly defaultProjectId: string | null;
  readonly onCreated: (t: Task) => void;
}) {
  const [form, setForm] = useState<TaskFormState>({
    title: "",
    project_id: defaultProjectId ?? "",
    due_at: "",
    importance: 5,
  });
  const [submitting, setSubmitting] = useState(false);

  if (!open) return null;

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!form.title.trim()) return;
    setSubmitting(true);
    try {
      const t = await createTask({
        title: form.title.trim(),
        project_id: form.project_id || null,
        due_at: form.due_at ? new Date(form.due_at).toISOString() : null,
        importance: form.importance,
      });
      onCreated(t);
      setForm({ title: "", project_id: defaultProjectId ?? "", due_at: "", importance: 5 });
      onClose();
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60">
      <form
        onSubmit={submit}
        className="w-full max-w-md space-y-3 rounded-4 border border-hairline bg-surface p-5"
      >
        <h3 className="text-sm font-semibold text-ink">New task</h3>
        <label className="block space-y-1">
          <span className="text-[11px] uppercase tracking-wide text-muted">
            Title
          </span>
          <input
            autoFocus
            placeholder="What needs to be done?"
            value={form.title}
            onChange={(e) => setForm({ ...form, title: e.target.value })}
            className="w-full rounded border border-hairline bg-bg-2 px-3 py-2 text-sm text-ink"
          />
        </label>
        <label className="block space-y-1">
          <span className="text-[11px] uppercase tracking-wide text-muted">
            Project
          </span>
          <select
            value={form.project_id}
            onChange={(e) => setForm({ ...form, project_id: e.target.value })}
            className="w-full rounded border border-hairline bg-bg-2 px-2 py-1.5 text-xs text-ink"
          >
            <option value="">No project</option>
            {projects.map((p) => (
              <option key={p.id} value={p.id}>
                {p.category} · {p.name}
              </option>
            ))}
          </select>
        </label>
        <div className="flex gap-2">
          <label className="block flex-1 space-y-1">
            <span className="text-[11px] uppercase tracking-wide text-muted">
              Due date
            </span>
            <input
              type="datetime-local"
              value={form.due_at}
              onChange={(e) => setForm({ ...form, due_at: e.target.value })}
              className="w-full rounded border border-hairline bg-bg-2 px-2 py-1.5 text-xs text-ink"
            />
          </label>
          <label className="block w-20 space-y-1">
            <span className="text-[11px] uppercase tracking-wide text-muted">
              Importance
            </span>
            <input
              type="number"
              min={1}
              max={10}
              value={form.importance}
              onChange={(e) => setForm({ ...form, importance: Number(e.target.value) })}
              className="w-full rounded border border-hairline bg-bg-2 px-2 py-1.5 text-xs text-ink"
            />
          </label>
        </div>
        <div className="flex justify-end gap-2">
          <button
            type="button"
            onClick={onClose}
            className="rounded border border-hairline px-3 py-1.5 text-xs text-muted hover:text-ink"
          >
            Cancel
          </button>
          <button
            type="submit"
            disabled={submitting || !form.title.trim()}
            className="rounded bg-indigo px-3 py-1.5 text-xs text-white disabled:opacity-60"
          >
            {submitting ? "Saving…" : "Create"}
          </button>
        </div>
      </form>
    </div>
  );
}

const DOMAIN_COLORS: Record<GoalCategory, { bg: string; text: string; rail: string }> = {
  personal: { bg: "bg-indigo-soft", text: "text-indigo", rail: "var(--indigo)" },
  life: { bg: "bg-green-soft", text: "text-green", rail: "var(--green, oklch(0.62 0.17 145))" },
  work: { bg: "bg-amber-soft", text: "text-amber", rail: "var(--amber)" },
};

function DetailPanel({
  task,
  goal,
  project,
  onDeleted: _onDeleted,
  onRefetch,
}: {
  readonly task: Task;
  readonly goal: Goal | null;
  readonly project: Project | null;
  readonly onDeleted: () => void;
  readonly onRefetch: () => void;
}) {
  void _onDeleted; // reserved for future use
  const [busy, setBusy] = useState(false);

  const isOverdue =
    task.due_at &&
    task.status !== "done" &&
    new Date(task.due_at).getTime() < Date.now();

  const domain: GoalCategory =
    goal?.category ?? project?.category ?? "personal";
  const domainColor = DOMAIN_COLORS[domain];

  const isBrain = task.source === "brain" || task.source === "message";

  return (
    <div
      className="rounded-3 border border-hairline p-5"
      style={{
        background: "oklch(1 0 0 / 0.55)",
        backdropFilter: "blur(20px)",
      }}
    >
      <div className="space-y-5">
        {/* Eyebrow + title */}
        <div>
          <p className="text-[10px] uppercase tracking-wide text-muted">
            Selected task
          </p>
          <h3 className="mt-1 text-[24px] font-semibold leading-tight text-ink">
            {task.title}
          </h3>
          {/* Pills row */}
          <div className="mt-2 flex flex-wrap items-center gap-1.5">
            <span
              className={`rounded-full px-2.5 py-0.5 text-[10px] font-medium ${domainColor.bg} ${domainColor.text}`}
            >
              {domain}
            </span>
            {isOverdue && (
              <span className="rounded-full bg-danger/10 px-2.5 py-0.5 text-[10px] font-medium text-danger">
                overdue
              </span>
            )}
          </div>
        </div>

        {/* Brain's reasoning (uses notes) */}
        {task.notes && (
          <div>
            <p className="text-[10px] uppercase tracking-wide text-muted">
              Brain&apos;s reasoning
            </p>
            <blockquote
              className="mt-1.5 rounded-r-2 py-2.5 pl-3 pr-3"
              style={{
                borderLeft: "3px solid var(--indigo)",
                background: "oklch(0.95 0.02 265 / 0.25)",
              }}
            >
              <p className="text-[13.5px] leading-relaxed text-ink/90">
                {task.notes.split(/(\bimportance\b)/i).map((part, i) =>
                  /importance/i.test(part) ? (
                    <span key={i} className="font-bold text-indigo">
                      {part}
                    </span>
                  ) : (
                    <span key={i}>{part}</span>
                  ),
                )}{" "}
                <span className="font-bold text-indigo">
                  Importance {task.importance}/10.
                </span>
              </p>
            </blockquote>
          </div>
        )}

        {/* Completion note / evidence */}
        {task.completion_note && (
          <div>
            <p className="text-[10px] uppercase tracking-wide text-muted">
              Evidence
            </p>
            <div className="mt-1.5 rounded-2 bg-bg-2 p-3">
              <div className="flex items-center gap-1.5 text-[10px] text-muted">
                <Quote className="h-3 w-3" />
                <span className="uppercase tracking-wide">
                  {task.source === "brain" || task.source === "message"
                    ? "Brain evidence"
                    : "Completion note"}
                </span>
              </div>
              <p className="mt-1 text-[12.5px] italic text-ink/80">
                {task.completion_note}
              </p>
              {task.completion_evidence_id && (
                <p className="mt-1 font-mono text-[10px] text-muted">
                  ref: {task.completion_evidence_id}
                </p>
              )}
            </div>
          </div>
        )}

        {/* Source evidence for brain-proposed tasks */}
        {isBrain && task.source_ref && !task.completion_note && (
          <div>
            <p className="text-[10px] uppercase tracking-wide text-muted">
              Evidence
            </p>
            <div className="mt-1.5 rounded-2 bg-bg-2 p-3">
              <div className="flex items-center gap-1.5 text-[10px] text-muted">
                <Quote className="h-3 w-3" />
                <span className="uppercase tracking-wide">{task.source}</span>
              </div>
              <p className="mt-1 text-[12.5px] italic text-ink/80">
                {task.source_ref}
              </p>
            </div>
          </div>
        )}

        {/* Linked goal */}
        {goal && (
          <div>
            <p className="text-[10px] uppercase tracking-wide text-muted">
              Linked goal
            </p>
            <div
              className="mt-1.5 flex overflow-hidden rounded-2 border border-hairline bg-surface"
            >
              <div
                className="w-1.5 shrink-0"
                style={{ background: domainColor.rail }}
              />
              <div className="flex-1 p-3">
                <p className="text-[13px] font-medium text-ink">
                  {goal.title}
                </p>
                <p className="mt-0.5 text-[11px] text-muted">
                  {goal.category} · {goal.horizon}-term ·{" "}
                  {goal.target_date
                    ? `target ${new Date(goal.target_date).toLocaleDateString()}`
                    : "no target date"}
                </p>
              </div>
            </div>
          </div>
        )}

        {/* Due date if not overdue — informational */}
        {task.due_at && !isOverdue && task.status !== "done" && (
          <p className="flex items-center gap-1.5 text-[11px] text-muted">
            <Clock className="h-3 w-3" />
            Due {new Date(task.due_at).toLocaleDateString()}
          </p>
        )}

        {/* Action stack */}
        <div className="space-y-2 pt-1">
          <button
            type="button"
            className="flex w-full items-center justify-center gap-2 rounded-2 bg-indigo px-4 py-2.5 text-[13px] font-medium text-white hover:bg-indigo/90"
          >
            <Sparkles className="h-4 w-4" />
            Draft reply with Brain
          </button>
          <button
            type="button"
            disabled={busy || task.status === "done"}
            onClick={async () => {
              setBusy(true);
              try {
                await toggleTaskDone(task.id);
                onRefetch();
              } finally {
                setBusy(false);
              }
            }}
            className="flex w-full items-center justify-center gap-2 rounded-2 border border-hairline bg-surface px-4 py-2.5 text-[13px] font-medium text-ink hover:bg-bg-2 disabled:opacity-50"
          >
            <Check className="h-4 w-4" />
            {task.status === "done" ? "Already done" : "Mark done"}
          </button>
          <div className="flex gap-2">
            <button
              type="button"
              className="flex flex-1 items-center justify-center gap-1.5 rounded-2 px-3 py-2 text-[12px] text-muted hover:bg-bg-2 hover:text-ink"
            >
              <AlarmClock className="h-3.5 w-3.5" />
              Snooze 24h
            </button>
            <button
              type="button"
              className="flex flex-1 items-center justify-center gap-1.5 rounded-2 px-3 py-2 text-[12px] text-muted hover:bg-bg-2 hover:text-ink"
            >
              <UserPlus className="h-3.5 w-3.5" />
              Reassign
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

function Tasks() {
  const projects = useProjects({ status: "active" });
  const goals = useGoals({ status: "active" });
  const [selectedProjectId, setSelectedProjectId] = useState<string | null>(
    null,
  );
  const tasks = useTasks(
    selectedProjectId
      ? { project_id: selectedProjectId, parent_task_id: null }
      : { parent_task_id: null },
  );
  const [showNew, setShowNew] = useState(false);
  const [selectedTaskId, setSelectedTaskId] = useState<string | null>(null);

  const selected = useMemo(
    () => (tasks.data ?? []).find((t) => t.id === selectedTaskId) ?? null,
    [tasks.data, selectedTaskId],
  );

  const selectedGoal = useMemo(
    () =>
      selected?.goal_id
        ? (goals.data ?? []).find((g) => g.id === selected.goal_id) ?? null
        : null,
    [selected, goals.data],
  );

  const selectedProject = useMemo(
    () =>
      selected?.project_id
        ? (projects.data ?? []).find((p) => p.id === selected.project_id) ?? null
        : null,
    [selected, projects.data],
  );

  const grouped = useMemo(() => {
    const map: Record<TaskGroup, Task[]> = {
      today: [],
      this_week: [],
      later: [],
      done: [],
    };
    for (const t of tasks.data ?? []) {
      map[bucketForTask(t)].push(t);
    }
    return map;
  }, [tasks.data]);

  return (
    <div className="flex-1 space-y-4 overflow-y-auto p-5">
      <header className="flex items-center justify-between">
        <div>
          <h2
            className="text-[44px] font-bold leading-none"
            style={{
              background: "linear-gradient(135deg, var(--ink), var(--ink-2))",
              WebkitBackgroundClip: "text",
              WebkitTextFillColor: "transparent",
              backgroundClip: "text",
            }}
          >
            Tasks
          </h2>
          <p className="mt-1 text-sm text-muted">
            Grouped under projects. The Brain proposes tasks from your
            messages and marks them done when it sees the evidence.
          </p>
        </div>
        <button
          type="button"
          onClick={() => setShowNew(true)}
          className="flex items-center gap-1 rounded bg-indigo px-3 py-1.5 text-xs text-white"
        >
          <Plus className="h-3.5 w-3.5" strokeWidth={1.6} /> New task
        </button>
      </header>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-[1fr_3fr_2fr]">
        <ProjectRail
          projects={projects.data ?? []}
          selectedId={selectedProjectId}
          onSelect={setSelectedProjectId}
        />
        <Card
          title="Open tasks"
          icon={<CheckSquare className="h-4 w-4 text-indigo" />}
        >
          {tasks.isLoading && tasks.data === null ? (
            <div className="space-y-2">
              {[1, 2, 3].map((i) => (
                <Skeleton key={i} className="h-12 w-full" />
              ))}
            </div>
          ) : (tasks.data ?? []).length === 0 ? (
            <p className="py-6 text-center text-xs text-muted">
              No tasks here yet. Create one or let the Brain mine some from
              your recent messages.
            </p>
          ) : (
            (["today", "this_week", "later", "done"] as const).map((g) =>
              grouped[g].length === 0 ? null : (
                <div key={g} className="mb-4 last:mb-0">
                  <p className="mb-1 text-[10px] uppercase tracking-wide text-muted">
                    {GROUP_LABELS[g]}
                  </p>
                  <ul className="space-y-2">
                    {grouped[g].map((t) => (
                      <TaskRow
                        key={t.id}
                        task={t}
                        selected={selectedTaskId === t.id}
                        onSelect={() => setSelectedTaskId(t.id)}
                        onRefetch={tasks.refetch}
                      />
                    ))}
                  </ul>
                </div>
              ),
            )
          )}
        </Card>
        <div>
          {selected ? (
            <DetailPanel
              task={selected}
              goal={selectedGoal}
              project={selectedProject}
              onDeleted={() => {
                setSelectedTaskId(null);
                tasks.refetch();
              }}
              onRefetch={tasks.refetch}
            />
          ) : (
            <Card title="Pick a task">
              <p className="py-6 text-center text-xs text-muted">
                Select a task to see its notes, completion evidence (if any),
                and detail controls.
              </p>
            </Card>
          )}
        </div>
      </div>

      <NewTaskModal
        open={showNew}
        onClose={() => setShowNew(false)}
        projects={projects.data ?? []}
        defaultProjectId={selectedProjectId}
        onCreated={() => tasks.refetch()}
      />
    </div>
  );
}

export default Tasks;

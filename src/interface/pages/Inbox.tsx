/**
 * Inbox — the unified action surface for all "things to do today".
 *
 * Three item types, one prioritized page:
 *   - Pending replies → "Draft reply" + "Mark replied"
 *   - Tasks due/overdue/scheduled today → "Work on this" + "Mark done"
 *   - Active habits → "Start" + "Done"
 *
 * Optional ?topic= query string scopes replies to one conversation
 * thread (used by the Goals page drill-down).
 *
 * sensitivity_tier: 3
 */

import { useEffect, useMemo, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import {
  ArrowRight,
  Check,
  Inbox as InboxIcon,
  Layers,
  ListTodo,
  MessageSquare,
  Repeat,
} from "lucide-react";
import Card from "../components/dashboard/Card";
import { Skeleton } from "../components/LoadingState";
import {
  dismissPendingReply,
  toggleHabit,
  toggleTaskDone,
  useInbox,
  type InboxDomain,
  type InboxHabit,
  type InboxReply,
  type InboxTask,
} from "../hooks/useInbox";
import { buildReplyContext } from "../hooks/useReplyContext";
import { buildTaskContext } from "../hooks/useTaskContext";
import { formatRelativeTime } from "../utils/timeFormat";

type Bucket = "urgent" | "soon" | "ambient";

const BUCKET_LABELS: Record<Bucket, string> = {
  urgent: "Urgent (importance ≥ 8)",
  soon: "Soon (importance 5–7)",
  ambient: "Ambient",
};

function bucketFor(importance: number): Bucket {
  if (importance >= 8) return "urgent";
  if (importance >= 5) return "soon";
  return "ambient";
}

function ageBadge(messageAt: string): string {
  if (!messageAt) return "—";
  const ms = Date.now() - new Date(messageAt).getTime();
  if (Number.isNaN(ms)) return "—";
  const days = Math.floor(ms / (24 * 3600 * 1000));
  if (days <= 0) return "today";
  if (days === 1) return "1d";
  if (days <= 6) return `${days}d`;
  if (days <= 13) return "1w+";
  return `${Math.floor(days / 7)}w+`;
}

function GoalChip({ title }: { readonly title: string | null }) {
  if (!title) return null;
  return (
    <span className="rounded-pill bg-indigo-soft px-1.5 py-0.5 text-[10px] text-indigo-2">
      {title}
    </span>
  );
}

function SourceTag({ source }: { readonly source: string }) {
  const s = source.toLowerCase();
  const cls =
    s === "whatsapp"
      ? "bg-[oklch(0.96_0.04_145)] text-[oklch(0.38_0.10_145)]"
      : s === "gmail"
        ? "bg-[oklch(0.96_0.04_30)] text-[oklch(0.42_0.10_30)]"
        : "bg-indigo-soft text-indigo-2";
  return (
    <span className={`rounded-pill px-1.5 py-0.5 text-[10.5px] uppercase ${cls}`}>
      {source}
    </span>
  );
}

function ReplyRow({
  reply,
  onDismissed,
}: {
  readonly reply: InboxReply;
  readonly onDismissed: () => void;
}) {
  const navigate = useNavigate();
  const [busy, setBusy] = useState(false);

  const onDraft = () =>
    navigate("/chat", {
      state: {
        prefilled: `Draft a reply to ${reply.contact_name} about: ${
          reply.reason || reply.preview
        }`,
        autoSubmit: true,
        replyContext: buildReplyContext({
          source: reply.source,
          message_id: reply.message_id,
          contact_name: reply.contact_name,
        }),
      },
    });

  const onMarkReplied = async () => {
    setBusy(true);
    try {
      await dismissPendingReply(reply.id);
    } finally {
      setBusy(false);
      onDismissed();
    }
  };

  const isUrgent = reply.importance >= 8;

  return (
    <li
      className={`grid grid-cols-[20px_1fr_auto] items-start gap-3 rounded-3 border bg-surface p-3 shadow-1 transition hover:-translate-y-px hover:shadow-2 ${
        isUrgent
          ? "border-[oklch(0.85_0.06_25)] bg-gradient-to-br from-danger-soft to-surface"
          : "border-hairline"
      }`}
    >
      <MessageSquare className="mt-0.5 h-4 w-4 text-muted" strokeWidth={1.6} />
      <div className="min-w-0">
        <div className="flex items-center gap-2">
          {isUrgent && (
            <span className="inline-block h-[7px] w-[7px] shrink-0 rounded-full bg-[crimson]" />
          )}
          <span className="truncate text-sm font-medium text-ink">
            {reply.contact_name}
          </span>
          <SourceTag source={reply.source} />
          <span className="text-[10px] text-muted">
            {ageBadge(reply.message_at)}
          </span>
        </div>
        {reply.reason && (
          <p className="mt-1 text-xs italic text-muted">
            {reply.reason}
          </p>
        )}
        {reply.preview && (
          <p className="mt-1 line-clamp-2 text-xs text-ink">
            {reply.preview}
          </p>
        )}
        {reply.message_at && (
          <p className="mt-1 text-[10px] text-faint">
            last activity {formatRelativeTime(reply.message_at)}
          </p>
        )}
      </div>
      <div className="flex shrink-0 flex-col gap-1">
        <button
          type="button"
          onClick={onDraft}
          className="flex items-center gap-1 rounded-md bg-indigo-soft px-2 py-1 text-[11px] text-indigo-2 hover:bg-indigo/25"
        >
          Draft reply <ArrowRight className="h-3 w-3" strokeWidth={1.6} />
        </button>
        <button
          type="button"
          disabled={busy}
          onClick={onMarkReplied}
          className="flex items-center gap-1 rounded-md border border-hairline px-2 py-1 text-[11px] text-muted hover:text-ink disabled:opacity-60"
        >
          <Check className="h-3 w-3" strokeWidth={1.6} />
          Mark replied
        </button>
      </div>
    </li>
  );
}

function TaskRow({
  task,
  onChanged,
}: {
  readonly task: InboxTask;
  readonly onChanged: () => void;
}) {
  const navigate = useNavigate();
  const [busy, setBusy] = useState(false);

  const isOverdue =
    task.due_at &&
    new Date(task.due_at).getTime() < new Date().setHours(0, 0, 0, 0);

  const onWork = () =>
    navigate("/chat", {
      state: {
        prefilled: `Help me work on: ${task.title}`,
        autoSubmit: true,
        taskContext: buildTaskContext({
          task_id: task.id,
          goal_id: task.goal_id,
        }),
      },
    });

  const onDone = async () => {
    setBusy(true);
    try {
      await toggleTaskDone(task.id);
    } finally {
      setBusy(false);
      onChanged();
    }
  };

  return (
    <li className="grid grid-cols-[20px_1fr_auto] items-start gap-3 rounded-3 border border-hairline bg-surface p-3 shadow-1 transition hover:-translate-y-px hover:shadow-2">
      <ListTodo className="mt-0.5 h-4 w-4 text-muted" strokeWidth={1.6} />
      <div className="min-w-0">
        <div className="flex items-center gap-2">
          <span className="truncate text-sm font-medium text-ink">
            {task.title}
          </span>
          <GoalChip title={task.goal_title} />
          {isOverdue && (
            <span className="rounded-pill bg-danger-soft px-1.5 py-0.5 text-[10px] text-danger">
              overdue
            </span>
          )}
        </div>
        {task.notes && (
          <p className="mt-1 line-clamp-2 text-xs text-ink">
            {task.notes}
          </p>
        )}
        {task.due_at && (
          <p className="mt-1 text-[10px] text-faint">
            due {formatRelativeTime(task.due_at)}
          </p>
        )}
      </div>
      <div className="flex shrink-0 flex-col gap-1">
        <button
          type="button"
          onClick={onWork}
          className="flex items-center gap-1 rounded-md bg-indigo-soft px-2 py-1 text-[11px] text-indigo-2 hover:bg-indigo/25"
        >
          Work on this <ArrowRight className="h-3 w-3" strokeWidth={1.6} />
        </button>
        <button
          type="button"
          disabled={busy}
          onClick={onDone}
          className="flex items-center gap-1 rounded-md border border-hairline px-2 py-1 text-[11px] text-muted hover:text-ink disabled:opacity-60"
        >
          <Check className="h-3 w-3" strokeWidth={1.6} />
          Mark done
        </button>
      </div>
    </li>
  );
}

function HabitRow({
  habit,
  onChanged,
}: {
  readonly habit: InboxHabit;
  readonly onChanged: () => void;
}) {
  const navigate = useNavigate();
  const [busy, setBusy] = useState(false);

  const onStart = () =>
    navigate("/chat", {
      state: {
        prefilled: `Help me with my habit: ${habit.title}`,
        autoSubmit: true,
        taskContext: buildTaskContext({
          task_id: habit.id,
          goal_id: habit.goal_id,
        }),
      },
    });

  const onDone = async () => {
    setBusy(true);
    try {
      await toggleHabit(habit.id);
    } finally {
      setBusy(false);
      onChanged();
    }
  };

  return (
    <li className="grid grid-cols-[20px_1fr_auto] items-start gap-3 rounded-3 border border-hairline bg-surface p-3 shadow-1 transition hover:-translate-y-px hover:shadow-2">
      <Repeat className="mt-0.5 h-4 w-4 text-muted" strokeWidth={1.6} />
      <div className="min-w-0">
        <div className="flex items-center gap-2">
          <span className="truncate text-sm font-medium text-ink">
            {habit.title}
          </span>
          <GoalChip title={habit.goal_title} />
          {habit.preferred_window && habit.preferred_window !== "any" && (
            <span className="text-[10px] text-muted">
              {habit.preferred_window}
            </span>
          )}
        </div>
      </div>
      <div className="flex shrink-0 flex-col gap-1">
        <button
          type="button"
          onClick={onStart}
          className="flex items-center gap-1 rounded-md bg-indigo-soft px-2 py-1 text-[11px] text-indigo-2 hover:bg-indigo/25"
        >
          Start <ArrowRight className="h-3 w-3" strokeWidth={1.6} />
        </button>
        <button
          type="button"
          disabled={busy}
          onClick={onDone}
          className="flex items-center gap-1 rounded-md border border-hairline px-2 py-1 text-[11px] text-muted hover:text-ink disabled:opacity-60"
        >
          <Check className="h-3 w-3" strokeWidth={1.6} />
          Done
        </button>
      </div>
    </li>
  );
}

type ItemTab = "all" | "replies" | "tasks" | "habits";

const ITEM_TABS: ReadonlyArray<{
  readonly key: ItemTab;
  readonly label: string;
  readonly icon: typeof MessageSquare;
}> = [
  { key: "all", label: "All", icon: InboxIcon },
  { key: "replies", label: "Threads", icon: MessageSquare },
  { key: "tasks", label: "Tasks", icon: ListTodo },
  { key: "habits", label: "Habits", icon: Repeat },
];

const DOMAIN_TABS: ReadonlyArray<{
  readonly key: InboxDomain | "all";
  readonly label: string;
}> = [
  { key: "all", label: "All" },
  { key: "work", label: "Work" },
  { key: "personal", label: "Personal" },
  { key: "health", label: "Health" },
];

function Inbox() {
  const location = useLocation();
  const navigate = useNavigate();
  const topicFromQuery = useMemo(() => {
    const params = new URLSearchParams(location.search);
    return params.get("topic");
  }, [location.search]);

  const [domain, setDomain] = useState<InboxDomain | "all">("all");
  const [itemTab, setItemTab] = useState<ItemTab>("all");

  // When scoped to a topic, only replies make sense — reset tab.
  useEffect(() => {
    if (topicFromQuery) {
      setItemTab("replies");
    }
  }, [topicFromQuery]);

  const inbox = useInbox({
    domain: domain === "all" ? null : domain,
    topic: topicFromQuery,
  });

  useEffect(() => {
    const handler = () => inbox.refetch();
    window.addEventListener("secbrain:proactive-refreshed", handler);
    window.addEventListener("secbrain:pipeline-refreshed", handler);
    return () => {
      window.removeEventListener(
        "secbrain:proactive-refreshed", handler,
      );
      window.removeEventListener(
        "secbrain:pipeline-refreshed", handler,
      );
    };
  }, [inbox]);

  const replies = inbox.data?.replies ?? [];
  const tasks = inbox.data?.tasks ?? [];
  const habits = inbox.data?.habits ?? [];
  const topics = inbox.data?.topics ?? [];

  const showReplies = itemTab === "all" || itemTab === "replies";
  const showTasks = itemTab === "all" || itemTab === "tasks";
  const showHabits = itemTab === "all" || itemTab === "habits";

  const grouped = useMemo(() => {
    const map: Record<Bucket, InboxReply[]> = {
      urgent: [],
      soon: [],
      ambient: [],
    };
    for (const r of replies) {
      map[bucketFor(r.importance)].push(r);
    }
    return map;
  }, [replies]);

  const totalItems = replies.length + tasks.length + habits.length;
  const visibleItems =
    (showReplies ? replies.length : 0) +
    (showTasks ? tasks.length : 0) +
    (showHabits ? habits.length : 0);

  return (
    <div className="flex-1 space-y-4 overflow-y-auto p-5">
      <header className="flex items-center justify-between">
        <div>
          <h2
            className="flex items-center gap-3 text-[44px] font-bold leading-none"
            style={{
              background: "linear-gradient(135deg, var(--ink), var(--ink-2))",
              WebkitBackgroundClip: "text",
              WebkitTextFillColor: "transparent",
              backgroundClip: "text",
            }}
          >
            <InboxIcon className="h-8 w-8 text-indigo" strokeWidth={1.6} />
            Inbox
          </h2>
          <p className="mt-1 text-sm text-muted">
            {topicFromQuery
              ? `Scoped to topic: ${topicFromQuery}`
              : "Everything you need to do today — replies, tasks, and habits."}
          </p>
        </div>
        {topicFromQuery && (
          <button
            type="button"
            onClick={() => navigate("/inbox")}
            className="rounded border border-hairline px-3 py-1 text-xs text-muted hover:text-ink"
          >
            Clear topic filter
          </button>
        )}
      </header>

      <div className="flex items-center gap-4">
        {!topicFromQuery && (
          <div role="tablist" aria-label="Domain" className="flex">
            {DOMAIN_TABS.map((tab) => {
              const isActive = tab.key === domain;
              return (
                <button
                  key={tab.key}
                  type="button"
                  role="tab"
                  aria-selected={isActive}
                  onClick={() => setDomain(tab.key)}
                  className={`-mb-px border-b-2 px-3 py-1.5 text-xs transition-colors ${
                    isActive
                      ? "border-indigo text-indigo-2"
                      : "border-transparent text-muted hover:text-ink"
                  }`}
                >
                  {tab.label}
                </button>
              );
            })}
          </div>
        )}

        <div className="h-4 w-px bg-hairline" />

        <div role="tablist" aria-label="Item type" className="flex">
          {ITEM_TABS.map((tab) => {
            const isActive = tab.key === itemTab;
            const count =
              tab.key === "all" ? totalItems
              : tab.key === "replies" ? replies.length
              : tab.key === "tasks" ? tasks.length
              : habits.length;
            return (
              <button
                key={tab.key}
                type="button"
                role="tab"
                aria-selected={isActive}
                onClick={() => setItemTab(tab.key)}
                className={`-mb-px flex items-center gap-1 border-b-2 px-2 py-1.5 text-xs transition-colors ${
                  isActive
                    ? "border-indigo text-indigo-2"
                    : "border-transparent text-muted hover:text-ink"
                }`}
              >
                <tab.icon className="h-3 w-3" strokeWidth={1.6} />
                {tab.label}
                {count > 0 && (
                  <span className="ml-0.5 text-[10px]">({count})</span>
                )}
              </button>
            );
          })}
        </div>
      </div>

      {inbox.isLoading && !inbox.data ? (
        <div className="space-y-2">
          <Skeleton className="h-16 w-full" />
          <Skeleton className="h-16 w-full" />
          <Skeleton className="h-16 w-full" />
        </div>
      ) : visibleItems === 0 ? (
        <Card>
          <p className="py-6 text-center text-sm text-muted">
            {topicFromQuery
              ? "No pending replies for this thread."
              : "Inbox zero — nothing pending in this scope."}
          </p>
        </Card>
      ) : (
        <>
          {showReplies && replies.length > 0 && (
            <section className="space-y-2">
              {itemTab === "all" && (
                <h3 className="flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wider text-muted">
                  <MessageSquare className="h-3 w-3" />
                  Threads · {replies.length}
                </h3>
              )}
              {(["urgent", "soon", "ambient"] as const).map((b) =>
                grouped[b].length === 0 ? null : (
                  <div key={b} className="space-y-2">
                    <h4 className="text-[10px] uppercase tracking-wide text-muted/70">
                      {BUCKET_LABELS[b]} · {grouped[b].length}
                    </h4>
                    <ul className="space-y-2">
                      {grouped[b].map((r) => (
                        <ReplyRow
                          key={r.id}
                          reply={r}
                          onDismissed={inbox.refetch}
                        />
                      ))}
                    </ul>
                  </div>
                ),
              )}
            </section>
          )}

          {showTasks && tasks.length > 0 && (
            <section className="space-y-2">
              <h3 className="flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wider text-muted">
                <ListTodo className="h-3 w-3" />
                Tasks · {tasks.length}
              </h3>
              <ul className="space-y-2">
                {tasks.map((t) => (
                  <TaskRow
                    key={t.id}
                    task={t}
                    onChanged={inbox.refetch}
                  />
                ))}
              </ul>
            </section>
          )}

          {showHabits && habits.length > 0 && (
            <section className="space-y-2">
              <h3 className="flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wider text-muted">
                <Repeat className="h-3 w-3" />
                Habits · {habits.length}
              </h3>
              <ul className="space-y-2">
                {habits.map((h) => (
                  <HabitRow
                    key={h.id}
                    habit={h}
                    onChanged={inbox.refetch}
                  />
                ))}
              </ul>
            </section>
          )}
        </>
      )}

      {topics.length > 0 && !topicFromQuery && showReplies && (
        <Card
          title="Active conversations"
          icon={<Layers className="h-4 w-4 text-indigo" />}
        >
          <p className="mb-2 text-[11px] text-muted">
            Click to scope the inbox to one conversation thread.
          </p>
          <ul className="space-y-1">
            {topics.map((t) => (
              <li key={t.topic_id}>
                <button
                  type="button"
                  onClick={() =>
                    navigate(`/inbox?topic=${encodeURIComponent(t.title)}`)
                  }
                  className="flex w-full items-center justify-between gap-2 rounded border border-hairline bg-bg-2 px-2 py-1.5 text-left text-xs hover:border-indigo"
                >
                  <span className="truncate text-ink">
                    {t.title}
                    {t.contact_name && (
                      <span className="text-muted">
                        {" "}— {t.contact_name}
                      </span>
                    )}
                  </span>
                  <span className="text-[10px] text-muted">
                    importance {t.importance}
                  </span>
                </button>
              </li>
            ))}
          </ul>
        </Card>
      )}
    </div>
  );
}

export default Inbox;

import { useState } from "react";
import { Plus, Search, Trash2, MessageSquare } from "lucide-react";
import { Skeleton } from "../LoadingState";
import { formatRelativeTime } from "../../utils/timeFormat";

export interface ChatSessionSummary {
  readonly id: string;
  readonly title: string;
  readonly created_at: string;
  readonly updated_at: string;
  readonly message_count: number;
  readonly preview?: string | null;
}

interface SessionsPanelProps {
  readonly sessions: ReadonlyArray<ChatSessionSummary>;
  readonly activeId: string | null;
  readonly isLoading: boolean;
  readonly onSelect: (id: string) => void;
  readonly onNew: () => void;
  readonly onDelete: (id: string) => void;
}

export function SessionsPanel({
  sessions,
  activeId,
  isLoading,
  onSelect,
  onNew,
  onDelete,
}: SessionsPanelProps) {
  const [filter, setFilter] = useState("");

  const filtered = filter.trim()
    ? sessions.filter((s) =>
        s.title.toLowerCase().includes(filter.trim().toLowerCase()),
      )
    : sessions;

  return (
    <aside className="frosted flex h-full w-60 shrink-0 flex-col border-r border-hairline px-3 pt-3">
      <div className="flex items-center justify-between gap-2 pb-2">
        <h3 className="text-xs font-semibold uppercase tracking-wide text-muted">
          Chats
        </h3>
        <button
          onClick={onNew}
          title="Start a new chat"
          className="flex h-7 w-7 items-center justify-center rounded-2 text-muted hover:bg-surface hover:text-ink"
        >
          <Plus className="h-4 w-4" strokeWidth={1.6} />
        </button>
      </div>

      <div className="relative pb-2">
        <Search className="pointer-events-none absolute left-2 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted" strokeWidth={1.6} />
        <input
          type="text"
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          placeholder="Filter chats"
          className="w-full rounded-2 bg-surface px-7 py-1.5 text-xs text-ink placeholder-muted outline-none focus:ring-1 focus:ring-indigo"
        />
      </div>

      <div className="flex-1 space-y-1 overflow-y-auto pr-0.5">
        {isLoading ? (
          <>
            <Skeleton className="h-12 w-full" />
            <Skeleton className="h-12 w-full" />
            <Skeleton className="h-12 w-full" />
          </>
        ) : filtered.length === 0 ? (
          <p className="px-2 pt-4 text-center text-[11px] text-muted">
            {sessions.length === 0
              ? "No chats yet. Start a new one."
              : "No chats match your filter."}
          </p>
        ) : (
          filtered.map((s) => (
            <SessionRow
              key={s.id}
              session={s}
              active={s.id === activeId}
              onSelect={onSelect}
              onDelete={onDelete}
            />
          ))
        )}
      </div>
    </aside>
  );
}

function SessionRow({
  session,
  active,
  onSelect,
  onDelete,
}: {
  readonly session: ChatSessionSummary;
  readonly active: boolean;
  readonly onSelect: (id: string) => void;
  readonly onDelete: (id: string) => void;
}) {
  const [confirming, setConfirming] = useState(false);

  const handleDeleteClick = (e: React.MouseEvent) => {
    // Stop the row's onClick from firing — otherwise React's event
    // bubble runs onSelect first and the user navigates into the chat
    // they were trying to delete.
    e.stopPropagation();
    if (confirming) {
      onDelete(session.id);
    } else {
      setConfirming(true);
      window.setTimeout(() => setConfirming(false), 3000);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      onSelect(session.id);
    }
  };

  // The row used to be a single <button> with a nested <span role="button">
  // for delete. HTML disallows nested interactive elements; browsers
  // collapsed the inner click into the outer one so clicking the trash
  // would either select the chat or do nothing depending on event order.
  // Switching the row to a <div role="button"> with a real <button> for
  // the trash lets stopPropagation actually do its job.
  return (
    <div
      role="button"
      tabIndex={0}
      onClick={() => onSelect(session.id)}
      onKeyDown={handleKeyDown}
      className={`group flex w-full cursor-pointer items-start gap-2 rounded-2 px-2 py-2 text-left transition-colors ${
        active
          ? "bg-surface text-ink"
          : "text-muted hover:bg-surface hover:text-ink"
      }`}
    >
      <MessageSquare className="mt-0.5 h-3.5 w-3.5 shrink-0" strokeWidth={1.6} />
      <div className="min-w-0 flex-1">
        <div className="truncate text-xs font-medium">{session.title}</div>
        {session.preview && (
          <div className="truncate text-[10px] text-muted">
            {session.preview}
          </div>
        )}
        <div className="text-[10px] text-muted">
          {formatRelativeTime(session.updated_at)}
        </div>
      </div>
      <button
        type="button"
        onClick={handleDeleteClick}
        aria-label={confirming ? "Confirm delete" : "Delete chat"}
        title={confirming ? "Click again to confirm" : "Delete chat"}
        className={`flex h-6 w-6 shrink-0 items-center justify-center rounded text-muted opacity-0 transition-opacity group-hover:opacity-100 hover:bg-hairline hover:text-danger ${
          confirming ? "opacity-100 text-danger" : ""
        }`}
      >
        <Trash2 className="h-3 w-3" strokeWidth={1.6} />
      </button>
    </div>
  );
}

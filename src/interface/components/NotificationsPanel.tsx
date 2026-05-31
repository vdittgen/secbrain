/**
 * Notifications panel — opens beneath the TopBar bell.
 *
 * Lists the most recent notification log entries with a relative
 * timestamp, the category, and the message. Click-outside or Escape
 * closes the panel. Marking-as-seen happens in the parent when the
 * panel opens.
 *
 * sensitivity_tier: 2
 */

import { useEffect, useRef } from "react";
import { Inbox as InboxIcon } from "lucide-react";
import type { NotificationRecord } from "../hooks/useNotifications";

interface NotificationsPanelProps {
  readonly notifications: readonly NotificationRecord[];
  readonly isLoading: boolean;
  readonly error: string | null;
  readonly onClose: () => void;
}

function formatRelative(iso: string): string {
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return "";
  const diffMs = Date.now() - then;
  const minutes = Math.round(diffMs / 60_000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.round(hours / 24);
  if (days < 7) return `${days}d ago`;
  return new Date(iso).toLocaleDateString();
}

function NotificationRow({ n }: { readonly n: NotificationRecord }) {
  return (
    <li className="space-y-1 rounded-md border border-hairline bg-bg-2/40 px-3 py-2">
      <div className="flex items-center justify-between gap-2 text-[10px] uppercase tracking-wide text-muted">
        <span>{n.category}</span>
        <span>{formatRelative(n.created_at)}</span>
      </div>
      <p className="text-xs text-ink">{n.message}</p>
    </li>
  );
}

function NotificationsPanel({
  notifications,
  isLoading,
  error,
  onClose,
}: NotificationsPanelProps) {
  const rootRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const handleMouseDown = (event: MouseEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) onClose();
    };
    const handleKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    document.addEventListener("mousedown", handleMouseDown);
    document.addEventListener("keydown", handleKey);
    return () => {
      document.removeEventListener("mousedown", handleMouseDown);
      document.removeEventListener("keydown", handleKey);
    };
  }, [onClose]);

  return (
    <div
      ref={rootRef}
      className="absolute right-0 top-full z-50 mt-2 w-80 rounded-2 border border-hairline bg-surface p-3 shadow-xl"
      role="dialog"
      aria-label="Notifications"
    >
      <div className="mb-2 flex items-center justify-between">
        <span className="text-xs font-medium text-ink">Notifications</span>
        <span className="text-[10px] uppercase tracking-wide text-muted">
          Last {notifications.length || 0}
        </span>
      </div>

      {error ? (
        <p className="py-6 text-center text-xs text-amber">
          Couldn't load notifications.
        </p>
      ) : isLoading && notifications.length === 0 ? (
        <p className="py-6 text-center text-xs text-muted">Loading…</p>
      ) : notifications.length === 0 ? (
        <div className="flex flex-col items-center gap-2 py-6 text-muted">
          <InboxIcon strokeWidth={1.6} className="h-5 w-5" />
          <p className="text-xs">No recent notifications.</p>
        </div>
      ) : (
        <ul className="max-h-96 space-y-1.5 overflow-y-auto pr-1">
          {notifications.map((n) => (
            <NotificationRow key={n.id} n={n} />
          ))}
        </ul>
      )}
    </div>
  );
}

export default NotificationsPanel;

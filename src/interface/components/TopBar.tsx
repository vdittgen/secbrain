import { useCallback, useContext, useState } from "react";
import { useLocation } from "react-router-dom";
import { Bell, RefreshCw } from "lucide-react";
import PrivacyIndicator from "./PrivacyIndicator";
import NotificationsPanel from "./NotificationsPanel";
import { useNotifications } from "../hooks/useNotifications";
import { usePipelineStatus } from "../hooks/usePipelineStatus";
import { PipelineRefreshContext } from "./Layout";
import { formatRelativeTime } from "../utils/timeFormat";

const pageTitles: Record<string, string> = {
  "/": "Dashboard",
  "/chat": "Chat",
  "/inbox": "Inbox",
  "/goals": "Goals",
  "/tasks": "Tasks",
  "/data": "Data",
  "/agents": "Agents",
  "/skills": "Skills",
  "/connectors": "Connectors",
  "/settings": "Settings",
  "/profile": "Profile",
};

function PipelinePill() {
  const pipeline = usePipelineStatus();
  const { openRefreshModal } = useContext(PipelineRefreshContext);

  if (pipeline.runState === "running") {
    return (
      <button
        type="button"
        onClick={openRefreshModal}
        className="inline-flex items-center gap-1.5 rounded-pill bg-indigo-soft px-3 py-1.5 text-[12.5px] font-medium text-indigo transition-colors hover:bg-indigo/15"
        title="Show refresh progress"
      >
        <RefreshCw className="h-3 w-3 animate-spin" strokeWidth={1.6} />
        Syncing…
      </button>
    );
  }

  // A failing stage (run failed, or vector/graph index failed) takes
  // priority over the normal stale/fresh states — the user needs to
  // know data isn't fully flowing even if marts are "synced".
  if (pipeline.anyStageFailing) {
    return (
      <button
        type="button"
        onClick={openRefreshModal}
        className="inline-flex items-center gap-1.5 rounded-pill bg-danger/10 px-3 py-1.5 text-[12.5px] font-medium text-danger transition-colors hover:bg-danger/15"
        title={pipeline.stageFailureReason ?? "A pipeline stage is failing"}
      >
        <span className="h-1.5 w-1.5 rounded-full bg-danger" />
        Sync issue
      </button>
    );
  }

  if (pipeline.isStale) {
    return (
      <button
        type="button"
        onClick={openRefreshModal}
        className="inline-flex items-center gap-1.5 rounded-pill bg-amber-soft px-3 py-1.5 text-[12.5px] font-medium transition-colors hover:bg-amber/15"
        style={{ color: "oklch(0.36 0.10 70)" }}
        title={`${pipeline.totalPending} items pending`}
      >
        <RefreshCw className="h-3 w-3" strokeWidth={1.6} />
        {pipeline.lastCompletedAt
          ? `Synced ${formatRelativeTime(pipeline.lastCompletedAt)}`
          : "Needs sync"}
      </button>
    );
  }

  if (pipeline.lastCompletedAt) {
    return (
      <button
        type="button"
        onClick={openRefreshModal}
        className="inline-flex items-center gap-1.5 rounded-pill bg-success-soft px-3 py-1.5 text-[12.5px] font-medium transition-colors hover:bg-success/15"
        style={{ color: "oklch(0.36 0.10 155)" }}
        title="Run sync now"
      >
        <span className="h-1.5 w-1.5 rounded-full bg-success" />
        Synced {formatRelativeTime(pipeline.lastCompletedAt)}
      </button>
    );
  }

  return null;
}

function TopBar() {
  const { pathname } = useLocation();
  const title = pageTitles[pathname] ?? "Arandu";

  const notifications = useNotifications();
  const [open, setOpen] = useState(false);

  const togglePanel = useCallback(() => {
    setOpen((wasOpen) => {
      const nowOpen = !wasOpen;
      if (nowOpen) notifications.markAllSeen();
      return nowOpen;
    });
  }, [notifications]);

  const closePanel = useCallback(() => setOpen(false), []);

  const badge = notifications.unreadCount;
  const badgeLabel = badge > 9 ? "9+" : String(badge);

  return (
    <header className="frosted flex h-14 shrink-0 items-center gap-3 border-b border-hairline px-6">
      <nav className="flex items-center gap-2 text-[13.5px] font-medium">
        <span className="text-ink-2">Arandu</span>
        <span className="text-faint">/</span>
        <span className="text-ink">{title}</span>
      </nav>

      <div className="ml-auto flex items-center gap-2">
        <PipelinePill />
        <PrivacyIndicator />

        <div className="relative">
          <button
            type="button"
            onClick={togglePanel}
            aria-label={
              badge > 0
                ? `Notifications, ${badge} unread`
                : "Notifications"
            }
            aria-expanded={open}
            className="inline-flex h-8 w-8 items-center justify-center rounded-2 text-ink-2 transition-colors hover:bg-bg-2 hover:text-ink"
          >
            <Bell className="h-4 w-4" strokeWidth={1.6} />
            {badge > 0 && (
              <span
                className="absolute -right-0.5 -top-0.5 flex h-4 min-w-4 items-center justify-center rounded-full bg-danger px-1 text-[10px] font-medium text-white"
                aria-hidden="true"
              >
                {badgeLabel}
              </span>
            )}
          </button>

          {open && (
            <NotificationsPanel
              notifications={notifications.data ?? []}
              isLoading={notifications.isLoading}
              error={notifications.error}
              onClose={closePanel}
            />
          )}
        </div>
      </div>
    </header>
  );
}

export default TopBar;

import { useCallback, useState } from "react";
import { useLocation } from "react-router-dom";
import { Bell } from "lucide-react";
import PrivacyIndicator from "./PrivacyIndicator";
import NotificationsPanel from "./NotificationsPanel";
import { useNotifications } from "../hooks/useNotifications";
import SystemHealthIndicator from "./SystemHealthIndicator";

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
        <SystemHealthIndicator />
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

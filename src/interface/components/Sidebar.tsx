import { useState, useEffect } from "react";
import { NavLink } from "react-router-dom";
import {
  LayoutDashboard,
  MessageSquare,
  Layers,
  Bot,
  Zap,
  Plug,
  Settings,
  CheckSquare,
  Target,
  Inbox,
  ChevronLeft,
  ChevronRight,
  Loader2,
} from "lucide-react";
import { useBackgroundTasks, type BackgroundTask } from "../hooks/useBackgroundTasks";
import { usePipelineStatus } from "../hooks/usePipelineStatus";
import { ModelStatusIndicator } from "./ModelStatusIndicator";
import { formatElapsedTime, formatRelativeTime } from "../utils/timeFormat";

const ICON_STROKE = 1.6;

interface NavSection {
  readonly label: string;
  readonly items: ReadonlyArray<{
    readonly to: string;
    readonly label: string;
    readonly icon: typeof LayoutDashboard;
  }>;
}

const navSections: ReadonlyArray<NavSection> = [
  {
    label: "Today",
    items: [
      { to: "/", label: "Dashboard", icon: LayoutDashboard },
      { to: "/inbox", label: "Inbox", icon: Inbox },
      { to: "/chat", label: "Chat", icon: MessageSquare },
    ],
  },
  {
    label: "Domain",
    items: [
      { to: "/goals", label: "Goals", icon: Target },
      { to: "/tasks", label: "Tasks", icon: CheckSquare },
    ],
  },
  {
    label: "Brain",
    items: [
      { to: "/agents", label: "Agents", icon: Bot },
      { to: "/skills", label: "Skills", icon: Zap },
      { to: "/data", label: "Data", icon: Layers },
      { to: "/connectors", label: "Connectors", icon: Plug },
      { to: "/settings", label: "Settings", icon: Settings },
    ],
  },
];

interface SidebarProps {
  readonly collapsed: boolean;
  readonly onToggle: () => void;
}

function TaskRow({ task, collapsed }: { readonly task: BackgroundTask; readonly collapsed: boolean }) {
  const [elapsed, setElapsed] = useState(() => formatElapsedTime(task.started_at));

  useEffect(() => {
    const timer = setInterval(() => setElapsed(formatElapsedTime(task.started_at)), 1000);
    return () => clearInterval(timer);
  }, [task.started_at]);

  return (
    <div className="flex items-center gap-2 px-3 py-1" title={`${task.label} (${elapsed})`}>
      <Loader2 className="h-3.5 w-3.5 shrink-0 animate-spin text-indigo" strokeWidth={ICON_STROKE} />
      {!collapsed && (
        <div className="flex min-w-0 flex-1 items-center justify-between">
          <span className="truncate text-[11px] text-muted">{task.label}</span>
          <span className="ml-1 shrink-0 font-mono text-[10px] tabular-nums text-faint">{elapsed}</span>
        </div>
      )}
    </div>
  );
}

function BackgroundTaskIndicator({ collapsed }: { readonly collapsed: boolean }) {
  const tasks = useBackgroundTasks();

  if (tasks.length === 0) return null;

  return (
    <div className="border-t border-hairline py-1.5">
      {tasks.map((task) => (
        <TaskRow key={task.id} task={task} collapsed={collapsed} />
      ))}
    </div>
  );
}

function syncIndicator(pipeline: ReturnType<typeof usePipelineStatus>): {
  readonly label: string;
  readonly dotClass: string;
  readonly dotShadow: string;
} {
  if (pipeline.runState === "running") {
    return {
      label: "Syncing…",
      dotClass: "bg-indigo animate-pulse",
      dotShadow: "0 0 0 3px oklch(0.55 0.20 265 / 0.18)",
    };
  }
  if (pipeline.isStale) {
    return {
      label: pipeline.lastCompletedAt
        ? `Synced ${formatRelativeTime(pipeline.lastCompletedAt)}`
        : "Needs sync",
      dotClass: "bg-amber",
      dotShadow: "0 0 0 3px oklch(0.75 0.15 70 / 0.18)",
    };
  }
  if (pipeline.lastCompletedAt) {
    return {
      label: `Synced ${formatRelativeTime(pipeline.lastCompletedAt)}`,
      dotClass: "bg-success",
      dotShadow: "0 0 0 3px oklch(0.62 0.16 155 / 0.18)",
    };
  }
  return {
    label: "Not synced",
    dotClass: "bg-muted",
    dotShadow: "none",
  };
}

function Sidebar({ collapsed, onToggle }: SidebarProps) {
  const pipeline = usePipelineStatus();
  const sync = syncIndicator(pipeline);

  return (
    <aside
      className={`frosted flex h-screen flex-col border-r border-hairline transition-all duration-200 ${
        collapsed ? "w-16" : "w-[248px]"
      }`}
    >
      {/* Brand */}
      <div className="flex items-center gap-3 px-4 pb-5 pt-6">
        <img
          src="/icon.svg"
          alt="SecBrain"
          className="h-8 w-8 shrink-0 rounded-[9px]"
        />
        {!collapsed && (
          <span className="text-[17px] font-semibold tracking-tight text-ink">
            SecBrain
          </span>
        )}
      </div>

      {/* Navigation */}
      <nav className="flex-1 overflow-y-auto px-4">
        {navSections.map((section) => (
          <div key={section.label}>
            {!collapsed && (
              <div className="px-3 pb-2 pt-4 text-[11px] font-semibold uppercase tracking-[0.06em] text-faint">
                {section.label}
              </div>
            )}
            <div className="space-y-0.5">
              {section.items.map(({ to, label, icon: Icon }) => (
                <NavLink
                  key={to}
                  to={to}
                  end={to === "/"}
                  className={({ isActive }) =>
                    `flex items-center gap-3 rounded-2 px-3 py-2 text-[14px] font-medium transition-colors ${
                      isActive
                        ? "bg-surface text-indigo-2 shadow-1"
                        : "text-ink-2 hover:bg-bg-2 hover:text-ink"
                    }`
                  }
                >
                  {({ isActive }) => (
                    <>
                      <Icon
                        className={`h-[18px] w-[18px] shrink-0 ${isActive ? "text-indigo" : "text-muted"}`}
                        strokeWidth={ICON_STROKE}
                      />
                      {!collapsed && <span style={{ letterSpacing: "-0.005em" }}>{label}</span>}
                    </>
                  )}
                </NavLink>
              ))}
            </div>
          </div>
        ))}
      </nav>

      <BackgroundTaskIndicator collapsed={collapsed} />

      <div className="border-t border-hairline px-3 py-1.5">
        <ModelStatusIndicator collapsed={collapsed} />
      </div>

      {/* Collapse toggle */}
      <button
        onClick={onToggle}
        className="flex items-center justify-center border-t border-hairline py-3 text-muted hover:text-ink"
      >
        {collapsed ? (
          <ChevronRight className="h-4 w-4" strokeWidth={ICON_STROKE} />
        ) : (
          <ChevronLeft className="h-4 w-4" strokeWidth={ICON_STROKE} />
        )}
      </button>

      {/* User card */}
      <div className="border-t border-hairline px-4 py-3">
        <div className="flex items-center gap-2.5 rounded-3 border border-hairline bg-surface p-3 shadow-1">
          <div
            className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-[13px] font-semibold text-white"
            style={{
              background: "linear-gradient(135deg, var(--personal-ink), var(--indigo))",
            }}
          >
            {collapsed ? "U" : "V"}
          </div>
          {!collapsed && (
            <div className="min-w-0">
              <div className="text-[13.5px] font-semibold tracking-tight text-ink">Vinicius</div>
              <div className="flex items-center gap-1.5 text-[11.5px] text-muted">
                <span
                  className={`h-1.5 w-1.5 rounded-full ${sync.dotClass}`}
                  style={{ boxShadow: sync.dotShadow }}
                />
                {sync.label}
              </div>
            </div>
          )}
        </div>
        {!collapsed && (
          <div className="mt-2.5 flex items-center gap-2 border-t border-hairline px-1 pt-2.5 text-[11.5px] font-medium tracking-tight text-muted">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} className="shrink-0 text-success">
              <path d="M18.36 6.64a9 9 0 1 1-12.73 0M12 2v10" />
            </svg>
            <span>Keep-awake on</span>
            <NavLink to="/settings" className="ml-auto text-[11.5px] font-medium text-indigo-2 hover:underline">
              Manage
            </NavLink>
          </div>
        )}
      </div>
    </aside>
  );
}

export default Sidebar;

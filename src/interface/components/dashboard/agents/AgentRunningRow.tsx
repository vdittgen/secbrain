/**
 * One running-agent row in the Mission Control "Agents at Work" panel.
 *
 * Shows label, optional progress bar, and elapsed time. The progress
 * field is reserved for future per-task progress reporting; for now,
 * tasks only carry a label and started_at.
 *
 * sensitivity_tier: 1
 */

import { Loader } from "lucide-react";
import type { AgentRunning } from "../../../hooks/useAgentStream";
import { formatElapsedTime } from "../../../utils/timeFormat";

interface AgentRunningRowProps {
  readonly task: AgentRunning;
}

function AgentRunningRow({ task }: AgentRunningRowProps) {
  const progress = task.progress;
  const progressPct =
    progress && progress.total > 0
      ? Math.min(100, (progress.current / progress.total) * 100)
      : null;

  return (
    <li className="rounded-2 bg-bg-2 px-3 py-2">
      <div className="flex items-center gap-2">
        <Loader className="h-3.5 w-3.5 shrink-0 animate-spin text-indigo" strokeWidth={1.6} />
        <span className="flex-1 truncate text-xs text-ink">
          {task.label}
        </span>
        <span className="shrink-0 text-[11px] text-muted">
          {formatElapsedTime(task.started_at)}
        </span>
      </div>
      {progressPct !== null && (
        <div className="mt-1.5 flex items-center gap-2">
          <div className="h-1 flex-1 overflow-hidden rounded-pill bg-hairline">
            <div
              className="h-full bg-indigo transition-[width] duration-500"
              style={{ width: `${progressPct}%` }}
            />
          </div>
          <span className="shrink-0 text-[10px] text-muted">
            {progress!.current}/{progress!.total}
            {progress!.eta_seconds !== null &&
              ` · ~${progress!.eta_seconds}s left`}
          </span>
        </div>
      )}
    </li>
  );
}

export default AgentRunningRow;

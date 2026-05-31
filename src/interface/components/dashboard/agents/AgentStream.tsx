/**
 * Bento "Agents" card — compact summary for the dashboard grid.
 *
 * Shows: running count (big number) + current agent label + elapsed,
 * plus a 3-column sub-stat row (Scheduled / Background / Interactive).
 *
 * sensitivity_tier: 2
 */

import { Link } from "react-router-dom";
import { Activity } from "lucide-react";
import Card from "../Card";
import { Skeleton } from "../../LoadingState";
import type { AgentStream as AgentStreamData } from "../../../hooks/useAgentStream";
import { formatElapsedTime } from "../../../utils/timeFormat";

interface AgentStreamProps {
  readonly stream: AgentStreamData | null;
  readonly isLoading: boolean;
}

function AgentStream({ stream, isLoading }: AgentStreamProps) {
  if (isLoading && !stream) {
    return (
      <Card
        title="Agents"
        icon={<Activity className="h-4 w-4 text-indigo" strokeWidth={1.6} />}
      >
        <Skeleton className="h-20 w-full" />
      </Card>
    );
  }

  const data = stream ?? { running: [], awaiting_review: [], recently_completed: [] };
  const runningCount = data.running.length;
  const topRunning = data.running[0];

  return (
    <div className="flex h-full flex-col rounded-4 border border-hairline bg-surface p-5 shadow-1">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-1.5">
          <span
            className="h-1.5 w-1.5 rounded-full"
            style={{
              background: runningCount > 0 ? "var(--success)" : "var(--muted)",
              boxShadow: runningCount > 0 ? "0 0 0 3px var(--success-soft)" : "none",
            }}
          />
          <span className="text-[12px] font-semibold text-muted" style={{ letterSpacing: "-0.005em" }}>
            Agents
          </span>
        </div>
        <Link to="/agents" className="text-[12.5px] font-medium text-indigo-2 hover:underline">
          Open →
        </Link>
      </div>

      <div className="mt-2 flex items-center gap-3.5">
        <span className="text-[38px] font-semibold leading-none text-ink" style={{ letterSpacing: "-0.03em" }}>
          {runningCount}
        </span>
        <span className="text-[18px] font-medium text-muted">running</span>
      </div>

      {topRunning && (
        <div className="mt-1.5 text-[12.5px] leading-snug text-muted">
          <span className="font-medium text-indigo">{topRunning.label}</span>
          <br />
          started {formatElapsedTime(topRunning.started_at)} ago
        </div>
      )}

      {!topRunning && (
        <p className="mt-1.5 text-[12.5px] text-muted">All agents idle</p>
      )}

      <div className="mt-auto grid grid-cols-3 gap-3 border-t border-hairline pt-3 text-[12px]" style={{ marginTop: topRunning ? "14px" : "auto" }}>
        <div>
          <span className="text-muted">Scheduled</span>
          <span className="ml-1 font-semibold text-ink">·</span>
          <span className="ml-1 font-semibold text-ink">{data.recently_completed.length}</span>
        </div>
        <div>
          <span className="text-muted">Background</span>
          <span className="ml-1 font-semibold text-ink">·</span>
          <span className="ml-1 font-semibold text-ink">{data.running.length}</span>
        </div>
        <div>
          <span className="text-muted">Interactive</span>
          <span className="ml-1 font-semibold text-ink">·</span>
          <span className="ml-1 font-semibold text-ink">{data.awaiting_review.length}</span>
        </div>
      </div>
    </div>
  );
}

export default AgentStream;

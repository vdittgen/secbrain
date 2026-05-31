// Recent-runs table for one agent. Lifted from the legacy Agents.tsx.
//
// sensitivity_tier: 1

import type { JSX } from "react";
import { Fragment, useCallback, useEffect, useState } from "react";
import { CircleCheck, CircleX } from "lucide-react";
import { dedupInvoke } from "../../../utils/requestDedup";
import type {
  AgentActivityResponse,
  AgentRunLogEntry,
} from "../../../types/agents";
import { formatDurationMs, formatRunTimestamp } from "./utils";

interface AgentActivityPanelProps {
  readonly agentId: string;
  readonly refreshKey?: number;
}

export function AgentActivityPanel({
  agentId,
  refreshKey = 0,
}: AgentActivityPanelProps): JSX.Element {
  const [entries, setEntries] = useState<ReadonlyArray<AgentRunLogEntry>>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [expandedId, setExpandedId] = useState<number | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const resp = await dedupInvoke<AgentActivityResponse>(
        "get_agent_activity",
        { agentId, limit: 1000 },
      );
      setEntries(resp.entries);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, [agentId]);

  useEffect(() => {
    void load();
  }, [load, refreshKey]);

  if (loading && entries.length === 0) {
    return (
      <div className="rounded-md border border-hairline bg-surface px-3 py-2 text-[11px] text-muted">
        Loading recent runs…
      </div>
    );
  }
  if (error) {
    return (
      <div className="rounded-md border border-amber/60 bg-amber/10 px-3 py-2 text-[11px] text-amber">
        Failed to load recent runs: {error}
      </div>
    );
  }
  if (entries.length === 0) {
    return (
      <div className="rounded-md border border-hairline bg-surface px-3 py-2 text-[11px] text-muted">
        No runs recorded yet for this agent.
      </div>
    );
  }

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <span className="text-[11px] text-muted">
          Showing {entries.length} of last 1000 runs
        </span>
        <button
          type="button"
          onClick={() => void load()}
          className="rounded-md border border-hairline px-2 py-1 text-[11px] text-muted hover:bg-surface"
        >
          Refresh
        </button>
      </div>
      <div className="max-h-96 overflow-auto rounded-md border border-hairline bg-surface">
        <table className="w-full text-[11px]">
          <thead className="sticky top-0 bg-surface text-muted">
            <tr>
              <th className="px-2 py-1 text-left font-medium">When</th>
              <th className="px-2 py-1 text-left font-medium">Status</th>
              <th className="px-2 py-1 text-left font-medium">Route</th>
              <th className="px-2 py-1 text-left font-medium">Duration</th>
              <th className="px-2 py-1 text-left font-medium">Input</th>
              <th className="px-2 py-1" />
            </tr>
          </thead>
          <tbody>
            {entries.map((entry) => {
              const open = expandedId === entry.id;
              const inputPreview = (entry.input ?? "").slice(0, 80);
              const inputTrunc = (entry.input ?? "").length > 80;
              return (
                <Fragment key={entry.id}>
                  <tr className="border-t border-hairline/40 hover:bg-surface/50">
                    <td className="whitespace-nowrap px-2 py-1 font-mono text-ink/80">
                      {formatRunTimestamp(entry.ts)}
                    </td>
                    <td className="px-2 py-1">
                      {entry.status === "ok"
                        ? (
                          <span className="inline-flex items-center gap-1 text-success">
                            <CircleCheck size={10} /> ok
                          </span>
                        )
                        : (
                          <span className="inline-flex items-center gap-1 text-amber">
                            <CircleX size={10} /> error
                          </span>
                        )}
                    </td>
                    <td className="px-2 py-1 text-muted">
                      {entry.route ?? "—"}
                    </td>
                    <td className="whitespace-nowrap px-2 py-1 text-muted">
                      {formatDurationMs(entry.duration_ms)}
                    </td>
                    <td className="max-w-xs truncate px-2 py-1 text-ink/80">
                      {inputPreview}
                      {inputTrunc && "…"}
                    </td>
                    <td className="px-2 py-1 text-right">
                      <button
                        type="button"
                        onClick={() => setExpandedId(open ? null : entry.id)}
                        className="rounded-md border border-hairline px-2 py-0.5 text-[10px] text-muted hover:bg-surface"
                      >
                        {open ? "Hide" : "View"}
                      </button>
                    </td>
                  </tr>
                  {open && (
                    <tr>
                      <td colSpan={6} className="bg-surface/30 px-2 py-2">
                        <div className="space-y-2">
                          <div>
                            <div className="text-[10px] uppercase tracking-wide text-muted">
                              Input
                            </div>
                            <pre className="mt-1 max-h-48 overflow-auto whitespace-pre-wrap rounded-md border border-hairline bg-surface p-2 font-mono text-[11px] text-ink/90">
                              {entry.input ?? "(empty)"}
                            </pre>
                          </div>
                          <div>
                            <div className="text-[10px] uppercase tracking-wide text-muted">
                              Output
                            </div>
                            <pre className="mt-1 max-h-48 overflow-auto whitespace-pre-wrap rounded-md border border-hairline bg-surface p-2 font-mono text-[11px] text-ink/90">
                              {entry.output ?? "(no output)"}
                            </pre>
                          </div>
                          {entry.error && (
                            <div>
                              <div className="text-[10px] uppercase tracking-wide text-amber">
                                Error
                              </div>
                              <pre className="mt-1 max-h-32 overflow-auto whitespace-pre-wrap rounded-md border border-amber/40 bg-amber/10 p-2 font-mono text-[11px] text-amber">
                                {entry.error}
                              </pre>
                            </div>
                          )}
                        </div>
                      </td>
                    </tr>
                  )}
                </Fragment>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

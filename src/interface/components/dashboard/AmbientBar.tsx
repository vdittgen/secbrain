/**
 * Ambient system-state bar — collapsed pipeline + DB health.
 *
 * Collapsed by default: a single low-contrast row.
 * Expanded: database health row. Persists open/closed in localStorage
 * so the choice survives reloads.
 *
 * sensitivity_tier: 1
 */

import { useCallback, useEffect, useState } from "react";
import { ChevronDown, ChevronUp, Loader2 } from "lucide-react";
import { dedupInvoke } from "../../utils/requestDedup";
import { useAsyncData } from "../../hooks/useAsyncData";
import { useOnboardingFollowupContext } from "../../App";

const STORAGE_KEY = "dashboard:ambient_expanded";

interface DbStats {
  readonly healthy: boolean;
  readonly total_sqlite_rows: number;
  readonly total_kuzu_nodes: number;
  readonly total_chroma_docs: number;
}

function AmbientBar() {
  const [expanded, setExpanded] = useState(() => {
    try {
      return window.localStorage.getItem(STORAGE_KEY) === "1";
    } catch {
      return false;
    }
  });

  useEffect(() => {
    try {
      window.localStorage.setItem(STORAGE_KEY, expanded ? "1" : "0");
    } catch {
      // localStorage may be unavailable in some embeds — non-fatal.
    }
  }, [expanded]);

  const statsFetcher = useCallback(
    () => dedupInvoke<DbStats>("get_database_stats"),
    [],
  );
  const stats = useAsyncData<DbStats>(statsFetcher);
  const followup = useOnboardingFollowupContext();

  const dbHealthy = stats.data?.healthy ?? true;
  const totalRecords = stats.data
    ? stats.data.total_sqlite_rows +
      stats.data.total_kuzu_nodes +
      stats.data.total_chroma_docs
    : 0;

  return (
    <div className="rounded-2 border border-hairline bg-surface">
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        aria-expanded={expanded}
        className="flex w-full items-center justify-between px-4 py-2 text-[11px] text-muted transition-colors hover:text-ink"
      >
        <span className="flex items-center gap-3">
          {followup?.running && (
            <>
              <span className="flex items-center gap-1.5 text-indigo">
                <Loader2 className="h-3 w-3 animate-spin" strokeWidth={1.6} />
                Setting up {followup.done}/{followup.total}
                {followup.current ? ` · ${followup.current}` : ""}
              </span>
              <span>·</span>
            </>
          )}
          <span className={dbHealthy ? "text-muted" : "text-danger"}>
            DB {dbHealthy ? "ok" : "issue"}
          </span>
          {totalRecords > 0 && (
            <>
              <span>·</span>
              <span>{totalRecords.toLocaleString()} records</span>
            </>
          )}
        </span>
        {expanded ? (
          <ChevronUp className="h-3.5 w-3.5" strokeWidth={1.6} />
        ) : (
          <ChevronDown className="h-3.5 w-3.5" strokeWidth={1.6} />
        )}
      </button>

      {expanded && stats.data && (
        <div className="space-y-3 border-t border-hairline px-4 py-3">
          <div className="text-[11px] text-muted">
            {totalRecords.toLocaleString()} records ·{" "}
            {stats.data.total_sqlite_rows.toLocaleString()} rows,{" "}
            {stats.data.total_kuzu_nodes.toLocaleString()} graph nodes,{" "}
            {stats.data.total_chroma_docs.toLocaleString()} embeddings
          </div>
        </div>
      )}
    </div>
  );
}

export default AmbientBar;

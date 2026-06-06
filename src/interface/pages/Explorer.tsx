/**
 * Explorer page — generic viewer for all ingested raw data tables.
 *
 * Dynamically discovers raw_* tables from DuckDB and renders each as
 * an expandable card with row count and sample data. No hardcoded
 * table-specific components — new connectors appear automatically.
 *
 * sensitivity_tier: 2 (displays user data from raw tables)
 */

import { useState, useCallback, useMemo } from "react";
import { Search, RefreshCw, Database } from "lucide-react";
import { SkeletonTable } from "../components/LoadingState";
import {
  TableCard,
  TierLegend,
  formatCount,
  type TableInfo,
} from "../components/GenericDataTable";
import { useAsyncData } from "../hooks/useAsyncData";
import { dedupInvoke } from "../utils/requestDedup";

// ---------------------------------------------------------------------------
// Explorer
// ---------------------------------------------------------------------------

function Explorer() {
  const [search, setSearch] = useState("");
  const [expandedTable, setExpandedTable] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);

  // Fetch all raw tables
  const tablesResult = useAsyncData<TableInfo[]>(
    useCallback(
      () => dedupInvoke<TableInfo[]>("list_tables", { prefix: "raw_" }),
      [],
    ),
  );

  // Filter tables by search
  const filteredTables = useMemo(() => {
    const tables = tablesResult.data ?? [];
    if (!search.trim()) return tables;
    const q = search.toLowerCase();
    return tables.filter((t) => t.table_name.toLowerCase().includes(q));
  }, [tablesResult.data, search]);

  // Total row count across all raw tables
  const totalRows = useMemo(
    () => (tablesResult.data ?? []).reduce((sum, t) => sum + t.row_count, 0),
    [tablesResult.data],
  );

  async function handleRefresh() {
    setRefreshing(true);
    try {
      await tablesResult.refetch();
    } finally {
      setRefreshing(false);
    }
  }

  function toggleTable(name: string) {
    setExpandedTable((prev) => (prev === name ? null : name));
  }

  return (
    <div className="flex flex-col gap-4 p-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <div className="flex items-center gap-3">
            <h1 className="text-[28px] font-semibold leading-tight" style={{ background: "linear-gradient(135deg, var(--ink), var(--ink-2))", WebkitBackgroundClip: "text", WebkitTextFillColor: "transparent", backgroundClip: "text" }}>
              Data Sources
            </h1>
          </div>
          <p className="mt-1 text-xs text-muted">
            {tablesResult.data
              ? `${tablesResult.data.length} tables · ${formatCount(totalRows)} total rows`
              : "Loading…"}
          </p>
        </div>

        <div className="flex items-center gap-3">
          <TierLegend />
          <button
            onClick={handleRefresh}
            disabled={refreshing}
            className="flex items-center gap-1.5 rounded-2 bg-surface px-3 py-1.5 text-xs text-muted hover:text-ink transition-colors"
          >
            <RefreshCw
              className={`h-3.5 w-3.5 ${refreshing ? "animate-spin" : ""}`}
            />
            Refresh
          </button>
        </div>
      </div>

      {/* Search */}
      <div className="flex items-center gap-2 rounded-2 border border-hairline bg-surface/30 px-3 py-2">
        <Search className="h-4 w-4 text-muted" strokeWidth={1.6} />
        <input
          type="text"
          placeholder="Search tables…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="flex-1 bg-transparent text-sm text-ink placeholder-muted outline-none"
        />
        {search && (
          <button
            onClick={() => setSearch("")}
            className="text-xs text-muted hover:text-ink"
          >
            Clear
          </button>
        )}
      </div>

      {/* Loading state */}
      {tablesResult.isLoading && <SkeletonTable />}

      {/* Error state */}
      {tablesResult.error && (
        <div className="rounded-2 border border-amber/30 bg-amber/10 px-4 py-3 text-xs text-amber">
          Failed to load tables: {tablesResult.error}
        </div>
      )}

      {/* Table list */}
      {tablesResult.data && (
        <div className="flex flex-col gap-2">
          {filteredTables.length === 0 ? (
            <div className="flex flex-col items-center gap-2 py-12 text-muted">
              <Database className="h-8 w-8 opacity-40" />
              <p className="text-sm">
                {search
                  ? "No tables match your search"
                  : "No raw data tables found. Connect a data source to get started."}
              </p>
            </div>
          ) : (
            filteredTables.map((table) => (
              <TableCard
                key={table.table_name}
                info={table}
                expanded={expandedTable === table.table_name}
                onToggle={() => toggleTable(table.table_name)}
              />
            ))
          )}
        </div>
      )}
    </div>
  );
}

export default Explorer;

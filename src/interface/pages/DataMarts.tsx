/**
 * Data Models page — aggregate overview of pipeline output tables.
 *
 * Groups tables by pipeline layer and shows row counts, column counts,
 * and column schemas. No sample data — just structural metadata.
 *
 * sensitivity_tier: 1 (metadata only, no user data displayed)
 */

import { useState, useCallback, useMemo } from "react";
import {
  Search,
  RefreshCw,
  Layers,
  ChevronRight,
} from "lucide-react";
import { SkeletonTable } from "../components/LoadingState";
import FreshnessIndicator from "../components/FreshnessIndicator";
import {
  formatTableName,
  formatCount,
  type TableInfo,
  type ColumnInfo,
} from "../components/GenericDataTable";
import { useAsyncData } from "../hooks/useAsyncData";
import { usePipelineStatus } from "../hooks/usePipelineStatus";
import { dedupInvoke } from "../utils/requestDedup";

interface PipelineModel {
  readonly name: string;
  readonly layer: string;
  readonly model_type: string;
  readonly depends_on: readonly string[];
}

type DataModelRow = TableInfo & { readonly materialized: boolean };

const NOT_BUILT_TOOLTIP =
  "Registered in the pipeline manifest but no rows have been produced yet — usually means upstream tables are empty.";

// ---------------------------------------------------------------------------
// Layer definitions
// ---------------------------------------------------------------------------

interface LayerDef {
  readonly prefix: string;
  readonly label: string;
  readonly description: string;
}

const LAYERS: readonly LayerDef[] = [
  {
    prefix: "stg_",
    label: "Staging",
    description: "Cleaned and type-cast raw data with sensitivity annotations",
  },
  {
    prefix: "int_",
    label: "Intermediate",
    description: "Joined and enriched data across sources",
  },
  {
    prefix: "mart_",
    label: "Marts",
    description: "Query-ready analytical views for specific domains",
  },
  {
    prefix: "ext_",
    label: "Extensions",
    description: "Auto-generated models from custom connectors and agents",
  },
] as const;

// ---------------------------------------------------------------------------
// Type badge color
// ---------------------------------------------------------------------------

function typeColor(dtype: string): string {
  const t = dtype.toUpperCase();
  if (t.includes("TIMESTAMP")) return "text-indigo";
  if (t.includes("INT") || t.includes("FLOAT") || t.includes("DOUBLE") || t.includes("DECIMAL"))
    return "text-emerald-400";
  if (t.includes("BOOL")) return "text-amber";
  return "text-muted";
}

// ---------------------------------------------------------------------------
// TableRow — compact aggregate row
// ---------------------------------------------------------------------------

function TableRow({
  info,
  expanded,
  onToggle,
}: {
  readonly info: DataModelRow;
  readonly expanded: boolean;
  readonly onToggle: () => void;
}) {
  const { label, prefix } = formatTableName(info.table_name);
  const isGhost = !info.materialized;

  return (
    <div
      className={`rounded-2 border overflow-hidden ${
        isGhost
          ? "border-dashed border-hairline/60 bg-surface/10"
          : "border-hairline bg-surface/30"
      }`}
    >
      <button
        className={`flex w-full items-center gap-3 px-4 py-2.5 text-left transition-colors ${
          isGhost ? "cursor-default" : "hover:bg-surface/50"
        }`}
        onClick={isGhost ? undefined : onToggle}
        disabled={isGhost}
        title={isGhost ? NOT_BUILT_TOOLTIP : undefined}
      >
        {isGhost ? (
          <span className="h-3.5 w-3.5 shrink-0" aria-hidden />
        ) : (
          <ChevronRight strokeWidth={1.6}
            className={`h-3.5 w-3.5 shrink-0 text-muted transition-transform ${
              expanded ? "rotate-90" : ""
            }`}
          />
        )}
        <div className="flex-1 min-w-0 flex items-center gap-2">
          <span
            className={`text-sm font-medium ${
              isGhost ? "text-muted" : "text-ink"
            }`}
          >
            {label}
          </span>
          {prefix && (
            <span className="rounded bg-surface px-1.5 py-0.5 text-[10px] font-mono text-muted">
              {prefix}
            </span>
          )}
        </div>
        {isGhost ? (
          <span className="shrink-0 rounded-full bg-surface px-2.5 py-0.5 text-[11px] font-medium text-muted">
            not built yet
          </span>
        ) : (
          <>
            <span className="shrink-0 font-mono text-[11px] text-muted">
              {info.column_count} cols
            </span>
            <span className="shrink-0 rounded-pill bg-indigo-soft px-2.5 py-0.5 text-xs font-medium text-indigo-2">
              {formatCount(info.row_count)}
            </span>
          </>
        )}
      </button>

      {/* Expanded: column schema */}
      {expanded && !isGhost && (
        <div className="border-t border-hairline px-4 py-3">
          <div className="text-[11px] font-medium uppercase tracking-wider text-muted mb-2">
            Columns
          </div>
          <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 gap-x-4 gap-y-1">
            {info.columns.map((col: ColumnInfo) => (
              <div key={col.name} className="flex items-center gap-1.5 text-xs">
                <span className="text-ink truncate">{col.name}</span>
                <span className={`text-[10px] ${typeColor(col.type)}`}>
                  {col.type}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// LayerSection
// ---------------------------------------------------------------------------

function LayerSection({
  layer,
  tables,
  expandedTable,
  onToggleTable,
}: {
  readonly layer: LayerDef;
  readonly tables: readonly DataModelRow[];
  readonly expandedTable: string | null;
  readonly onToggleTable: (name: string) => void;
}) {
  const [collapsed, setCollapsed] = useState(false);
  const totalRows = tables.reduce((sum, t) => sum + t.row_count, 0);
  const ghostCount = tables.reduce(
    (n, t) => (t.materialized ? n : n + 1),
    0,
  );

  if (tables.length === 0) return null;

  return (
    <div>
      <button
        className="flex w-full items-center gap-2 px-1 py-2 text-left"
        onClick={() => setCollapsed((c) => !c)}
      >
        <ChevronRight strokeWidth={1.6}
          className={`h-4 w-4 text-muted transition-transform ${
            collapsed ? "" : "rotate-90"
          }`}
        />
        <h2 className="text-[28px] font-semibold text-ink">{layer.label}</h2>
        <span className="font-mono text-[11px] text-muted">
          {tables.length} tables · {formatCount(totalRows)} rows
          {ghostCount > 0 ? ` · ${ghostCount} not built yet` : ""}
        </span>
      </button>
      {!collapsed && (
        <>
          <p className="ml-7 mb-2 text-[11px] text-muted">
            {layer.description}
          </p>
          <div className="ml-3 flex flex-col gap-1.5">
            {tables.map((table) => (
              <TableRow
                key={table.table_name}
                info={table}
                expanded={expandedTable === table.table_name}
                onToggle={() => onToggleTable(table.table_name)}
              />
            ))}
          </div>
        </>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// DataMarts
// ---------------------------------------------------------------------------

function DataMarts() {
  const [search, setSearch] = useState("");
  const [expandedTable, setExpandedTable] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);

  // Fetch ALL non-raw tables in one call (filter client-side)
  const tablesResult = useAsyncData<TableInfo[]>(
    useCallback(
      () => dedupInvoke<TableInfo[]>("list_tables", { prefix: "" }),
      [],
    ),
  );

  // Fetch the pipeline manifest so we can surface registered-but-
  // unmaterialized models alongside the live tables.
  const modelsResult = useAsyncData<PipelineModel[]>(
    useCallback(
      () => dedupInvoke<PipelineModel[]>("list_pipeline_models"),
      [],
    ),
  );

  // Pipeline freshness
  const { pipelineStatus } = usePipelineStatus();
  const lastSyncedAt = pipelineStatus?.last_run?.completed_at;
  const isStale = pipelineStatus?.is_stale ?? true;
  const isRunning = pipelineStatus
    ? pipelineStatus.pending_changes !== undefined &&
      Object.keys(pipelineStatus.pending_changes).length > 0
    : false;

  // Group tables by layer, excluding raw tables. Merges live tables from
  // SQLite with manifest entries so models that haven't materialized yet
  // still appear (marked as "not built yet").
  const layerGroups = useMemo(() => {
    const allTables = tablesResult.data ?? [];
    const allModels = modelsResult.data ?? [];

    const realRows: DataModelRow[] = allTables
      .filter((t) => !t.table_name.startsWith("raw_"))
      .map((t) => ({ ...t, materialized: true }));

    const materializedNames = new Set(realRows.map((r) => r.table_name));
    const ghostRows: DataModelRow[] = allModels
      .filter(
        (m) =>
          !m.name.startsWith("raw_") && !materializedNames.has(m.name),
      )
      .map((m) => ({
        table_name: m.name,
        row_count: 0,
        column_count: 0,
        columns: [],
        materialized: false,
      }));

    const allRows: DataModelRow[] = [...realRows, ...ghostRows];

    const filtered = search.trim()
      ? allRows.filter((t) =>
          t.table_name.toLowerCase().includes(search.toLowerCase()),
        )
      : allRows;

    return LAYERS.map((layer) => ({
      layer,
      tables: filtered
        .filter((t) => t.table_name.startsWith(layer.prefix))
        .slice()
        .sort((a, b) => a.table_name.localeCompare(b.table_name)),
    })).filter((g) => g.tables.length > 0);
  }, [tablesResult.data, modelsResult.data, search]);

  // Totals
  const totalTables = layerGroups.reduce((s, g) => s + g.tables.length, 0);
  const totalRows = layerGroups.reduce(
    (s, g) => s + g.tables.reduce((ts, t) => ts + t.row_count, 0),
    0,
  );

  async function handleRefresh() {
    setRefreshing(true);
    try {
      await Promise.all([tablesResult.refetch(), modelsResult.refetch()]);
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
            <h1
              className="text-[28px] font-semibold leading-tight"
              style={{
                background: "linear-gradient(135deg, var(--ink), var(--ink-2))",
                WebkitBackgroundClip: "text",
                WebkitTextFillColor: "transparent",
                backgroundClip: "text",
              }}
            >
              Data Models
            </h1>
            <FreshnessIndicator
              timestamp={lastSyncedAt ?? null}
              isStale={isStale}
              isRunning={isRunning}
            />
          </div>
          <p className="mt-1 text-xs text-muted">
            {tablesResult.data && modelsResult.data
              ? `${totalTables} tables · ${formatCount(totalRows)} total rows`
              : "Loading\u2026"}
          </p>
        </div>

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

      {/* Search */}
      <div className="flex items-center gap-2 rounded-2 border border-hairline bg-surface/30 px-3 py-2">
        <Search className="h-4 w-4 text-muted" strokeWidth={1.6} />
        <input
          type="text"
          placeholder="Search models…"
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
      {(tablesResult.isLoading || modelsResult.isLoading) && <SkeletonTable />}

      {/* Error state */}
      {(tablesResult.error || modelsResult.error) && (
        <div className="rounded-2 border border-amber/30 bg-amber/10 px-4 py-3 text-xs text-amber">
          Failed to load tables:{" "}
          {tablesResult.error ?? modelsResult.error}
        </div>
      )}

      {/* Table layers */}
      {tablesResult.data && modelsResult.data && (
        <div className="flex flex-col gap-4">
          {layerGroups.length === 0 ? (
            <div className="flex flex-col items-center gap-2 py-12 text-muted">
              <Layers className="h-8 w-8 opacity-40" />
              <p className="text-sm">
                {search
                  ? "No models match your search"
                  : "No pipeline models found. Run the pipeline to generate data models."}
              </p>
            </div>
          ) : (
            layerGroups.map(({ layer, tables }) => (
              <LayerSection
                key={layer.prefix}
                layer={layer}
                tables={tables}
                expandedTable={expandedTable}
                onToggleTable={toggleTable}
              />
            ))
          )}
        </div>
      )}
    </div>
  );
}

export default DataMarts;

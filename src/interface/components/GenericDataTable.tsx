/**
 * Generic data table components for browsing any DuckDB table.
 *
 * Shared between the Explorer (raw tables) and Data Marts pages.
 * Renders column definitions dynamically from information_schema metadata.
 *
 * sensitivity_tier: 2 (displays user data from any table)
 */

import { Fragment, useState, useMemo, useCallback } from "react";
import {
  ChevronUp,
  ChevronDown,
  ChevronRight,
  Lock,
  Database,
  Search,
} from "lucide-react";
import { dedupInvoke } from "../utils/requestDedup";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface ColumnInfo {
  readonly name: string;
  readonly type: string;
  /** Per-column sensitivity tier. Falls back to the row's tier when absent. */
  readonly tier?: number;
}

export interface TableInfo {
  readonly table_name: string;
  readonly row_count: number;
  readonly column_count: number;
  readonly columns: readonly ColumnInfo[];
}

export interface TableSample {
  readonly table_name: string;
  readonly total_rows: number;
  readonly columns: readonly ColumnInfo[];
  readonly rows: readonly Record<string, unknown>[];
}

type SortDir = "asc" | "desc";

const PAGE_SIZE = 25;

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Format raw table names for display. */
export function formatTableName(name: string): {
  label: string;
  prefix: string;
} {
  const match = name.match(/^(raw|stg|int|mart|ext)_(.+)$/);
  if (!match) return { label: name, prefix: "" };
  const [, prefix, rest] = match;
  const label = rest
    .replace(/_/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase());
  return { label, prefix };
}

/** Format a row count with thousand separators. */
export function formatCount(n: number): string {
  return n.toLocaleString();
}

/** Check if a value looks like a timestamp string. */
function isTimestamp(val: unknown): boolean {
  if (typeof val !== "string") return false;
  return /^\d{4}-\d{2}-\d{2}[T ]/.test(val);
}

/** Format a cell value for display. */
function formatCell(val: unknown, colType: string): string {
  if (val === null || val === undefined) return "—";
  if (typeof val === "boolean") return val ? "Yes" : "No";
  if (typeof val === "object") return JSON.stringify(val);
  const s = String(val);
  if (
    colType.toUpperCase().includes("TIMESTAMP") ||
    isTimestamp(val)
  ) {
    try {
      return new Date(s).toLocaleString();
    } catch {
      return s;
    }
  }
  return s;
}

/** Truncate long strings for table display. */
function truncate(s: string, maxLen: number = 80): string {
  if (s.length <= maxLen) return s;
  return s.slice(0, maxLen) + "…";
}

/** Protect tier-3 values. */
function protectValue(
  val: unknown,
  tier: number,
  unlocked: boolean,
): string {
  if (tier >= 3 && !unlocked) return "[Protected]";
  return formatCell(val, "");
}

/** Per-column tier wins; otherwise fall back to the row's tier. */
function effectiveTier(col: ColumnInfo, rowTier: number): number {
  return typeof col.tier === "number" ? col.tier : rowTier;
}

// ---------------------------------------------------------------------------
// TierDot
// ---------------------------------------------------------------------------

function TierDot({ tier }: { readonly tier: number }) {
  if (tier >= 3) {
    return (
      <span className="flex items-center gap-0.5" title="Sensitive (Tier 3)">
        <span className="inline-block h-2 w-2 rounded-full bg-danger" />
        <Lock strokeWidth={1.6} className="h-2.5 w-2.5 text-danger" />
      </span>
    );
  }
  if (tier === 2) {
    return (
      <span
        className="inline-block h-2 w-2 rounded-full bg-amber"
        title="Personal (Tier 2)"
      />
    );
  }
  return (
    <span
      className="inline-block h-2 w-2 rounded-full bg-success"
      title="Public (Tier 1)"
    />
  );
}

// ---------------------------------------------------------------------------
// SortHeader
// ---------------------------------------------------------------------------

function SortHeader({
  label,
  column,
  sortColumn,
  sortDir,
  onSort,
}: {
  readonly label: string;
  readonly column: string;
  readonly sortColumn: string;
  readonly sortDir: SortDir;
  readonly onSort: (col: string) => void;
}) {
  const active = sortColumn === column;
  return (
    <button
      className="flex items-center gap-1 text-[11px] font-medium uppercase tracking-wider text-muted hover:text-ink"
      onClick={() => onSort(column)}
    >
      {label}
      {active &&
        (sortDir === "asc" ? (
          <ChevronUp strokeWidth={1.6} className="h-3 w-3" />
        ) : (
          <ChevronDown strokeWidth={1.6} className="h-3 w-3" />
        ))}
    </button>
  );
}

// ---------------------------------------------------------------------------
// PaginationControls
// ---------------------------------------------------------------------------

function PaginationControls({
  page,
  totalItems,
  onPageChange,
}: {
  readonly page: number;
  readonly totalItems: number;
  readonly onPageChange: (p: number) => void;
}) {
  const totalPages = Math.max(1, Math.ceil(totalItems / PAGE_SIZE));
  const start = page * PAGE_SIZE + 1;
  const end = Math.min((page + 1) * PAGE_SIZE, totalItems);

  return (
    <div className="flex items-center justify-between border-t border-hairline px-4 py-2 text-xs text-muted">
      <span>
        {totalItems > 0
          ? `${start}–${end} of ${formatCount(totalItems)}`
          : "No rows"}
      </span>
      <div className="flex items-center gap-2">
        <button
          disabled={page === 0}
          onClick={() => onPageChange(page - 1)}
          className="rounded px-2 py-1 hover:bg-surface disabled:opacity-30"
        >
          Prev
        </button>
        <span>
          Page {page + 1} / {totalPages}
        </span>
        <button
          disabled={page >= totalPages - 1}
          onClick={() => onPageChange(page + 1)}
          className="rounded px-2 py-1 hover:bg-surface disabled:opacity-30"
        >
          Next
        </button>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// GenericDataTable
// ---------------------------------------------------------------------------

/**
 * Renders any table's sample data with dynamic columns.
 *
 * sensitivity_tier: 2
 */
export function GenericDataTable({
  data,
  search,
  pageSize = PAGE_SIZE,
}: {
  readonly data: TableSample;
  readonly search: string;
  readonly pageSize?: number;
}) {
  const [page, setPage] = useState(0);
  const [sortCol, setSortCol] = useState("");
  const [sortDir, setSortDir] = useState<SortDir>("desc");
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [unlockedIds, setUnlockedIds] = useState<Set<string>>(new Set());

  // Determine which columns to show (skip id, limit to reasonable count)
  const visibleColumns = useMemo(() => {
    const cols = data.columns.filter(
      (c) => c.name !== "id" && c.name !== "created_at",
    );
    // Show sensitivity_tier first, then the rest
    const tierCol = cols.find((c) => c.name === "sensitivity_tier");
    const otherCols = cols.filter((c) => c.name !== "sensitivity_tier");
    const result = tierCol ? [tierCol, ...otherCols] : otherCols;
    return result.slice(0, 8); // cap at 8 visible columns
  }, [data.columns]);

  // Get row ID (use 'id' column or fallback to index)
  const getRowId = useCallback(
    (row: Record<string, unknown>, idx: number): string => {
      return row.id != null ? String(row.id) : `row-${idx}`;
    },
    [],
  );

  // Filter rows by search
  const filtered = useMemo(() => {
    if (!search.trim()) return [...data.rows];
    const q = search.toLowerCase();
    return data.rows.filter((row) =>
      visibleColumns.some((col) => {
        const val = row[col.name];
        return val != null && String(val).toLowerCase().includes(q);
      }),
    );
  }, [data.rows, search, visibleColumns]);

  // Sort
  const sorted = useMemo(() => {
    if (!sortCol) return filtered;
    return [...filtered].sort((a, b) => {
      const va = a[sortCol];
      const vb = b[sortCol];
      if (va == null && vb == null) return 0;
      if (va == null) return 1;
      if (vb == null) return -1;
      const cmp = String(va).localeCompare(String(vb));
      return sortDir === "asc" ? cmp : -cmp;
    });
  }, [filtered, sortCol, sortDir]);

  // Paginate
  const pageRows = sorted.slice(page * pageSize, (page + 1) * pageSize);

  function handleSort(col: string) {
    if (sortCol === col) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortCol(col);
      setSortDir("desc");
    }
  }

  function toggleExpand(id: string) {
    setExpandedId((prev) => (prev === id ? null : id));
  }

  function toggleUnlock(id: string) {
    setUnlockedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  if (data.rows.length === 0) {
    return (
      <div className="flex flex-col items-center gap-2 py-12 text-muted">
        <Database strokeWidth={1.6} className="h-8 w-8 opacity-40" />
        <p className="text-sm">No data in this table yet</p>
      </div>
    );
  }

  return (
    <div>
      <div className="overflow-x-auto">
        <table className="w-full text-left text-xs">
          <thead>
            <tr className="border-b border-hairline">
              <th className="px-3 py-2 w-6" />
              {visibleColumns.map((col) => (
                <th key={col.name} className="px-3 py-2">
                  {col.name === "sensitivity_tier" ? (
                    <span className="text-[11px] font-medium uppercase tracking-wider text-muted">
                      Tier
                    </span>
                  ) : (
                    <SortHeader
                      label={col.name.replace(/_/g, " ")}
                      column={col.name}
                      sortColumn={sortCol}
                      sortDir={sortDir}
                      onSort={handleSort}
                    />
                  )}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {pageRows.map((row, idx) => {
              const rowId = getRowId(row, page * pageSize + idx);
              const isExpanded = expandedId === rowId;
              const rowTier = typeof row.sensitivity_tier === "number"
                ? row.sensitivity_tier
                : 1;
              const isUnlocked = unlockedIds.has(rowId);
              const hasSensitiveCol = data.columns.some(
                (c) => effectiveTier(c, rowTier) >= 3,
              );

              return (
                <Fragment key={rowId}>
                  <tr
                    className="border-b border-hairline/50 hover:bg-surface/30 cursor-pointer"
                    onClick={() => toggleExpand(rowId)}
                  >
                    <td className="px-3 py-2">
                      <ChevronRight strokeWidth={1.6}
                        className={`h-3 w-3 text-muted transition-transform ${
                          isExpanded ? "rotate-90" : ""
                        }`}
                      />
                    </td>
                    {visibleColumns.map((col) => {
                      const cellTier = effectiveTier(col, rowTier);
                      return (
                        <td key={col.name} className="px-3 py-2 text-ink">
                          {col.name === "sensitivity_tier" ? (
                            <TierDot tier={rowTier} />
                          ) : cellTier >= 3 && !isUnlocked ? (
                            <span className="text-muted italic">
                              [Protected]
                            </span>
                          ) : (
                            <span title={String(row[col.name] ?? "")}>
                              {truncate(formatCell(row[col.name], col.type))}
                            </span>
                          )}
                        </td>
                      );
                    })}
                  </tr>
                  {isExpanded && (
                    <tr className="border-b border-hairline bg-surface/20">
                      <td
                        colSpan={visibleColumns.length + 1}
                        className="px-6 py-3"
                      >
                        <div className="flex items-center justify-between mb-2">
                          <span className="text-[11px] font-medium uppercase tracking-wider text-muted">
                            Row Details
                          </span>
                          {hasSensitiveCol && (
                            <button
                              onClick={(e) => {
                                e.stopPropagation();
                                toggleUnlock(rowId);
                              }}
                              className="text-[11px] text-indigo hover:underline"
                            >
                              {isUnlocked
                                ? "Re-lock"
                                : "Unlock sensitive fields"}
                            </button>
                          )}
                        </div>
                        <div className="grid grid-cols-2 gap-x-6 gap-y-1 text-xs">
                          {data.columns.map((col) => {
                            const cellTier = effectiveTier(col, rowTier);
                            return (
                              <div key={col.name} className="flex gap-2">
                                <span className="text-muted shrink-0 w-32 truncate">
                                  {col.name}:
                                </span>
                                <span className="text-ink break-all">
                                  {col.name === "sensitivity_tier" ? (
                                    <TierDot tier={rowTier} />
                                  ) : (
                                    protectValue(
                                      formatCell(row[col.name], col.type),
                                      cellTier,
                                      isUnlocked,
                                    )
                                  )}
                                </span>
                              </div>
                            );
                          })}
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

      <PaginationControls
        page={page}
        totalItems={sorted.length}
        onPageChange={setPage}
      />
    </div>
  );
}

// ---------------------------------------------------------------------------
// TableCard
// ---------------------------------------------------------------------------

/**
 * Expandable card for a single table: name, row count, columns.
 * Loads sample data on first expand.
 *
 * sensitivity_tier: 2
 */
export function TableCard({
  info,
  expanded,
  onToggle,
}: {
  readonly info: TableInfo;
  readonly expanded: boolean;
  readonly onToggle: () => void;
}) {
  const [sample, setSample] = useState<TableSample | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState("");

  const { label, prefix } = formatTableName(info.table_name);

  // Load sample data on first expand
  const handleToggle = useCallback(async () => {
    if (!expanded && !sample && !loading) {
      setLoading(true);
      setError(null);
      try {
        const result = await dedupInvoke<TableSample>("query_table", {
          table: info.table_name,
          limit: 50,
          offset: 0,
        });
        setSample(result);
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err));
      } finally {
        setLoading(false);
      }
    }
    onToggle();
  }, [expanded, sample, loading, info.table_name, onToggle]);

  return (
    <div className="rounded-2 border border-hairline bg-surface/30 overflow-hidden">
      {/* Card header */}
      <button
        className="flex w-full items-center gap-3 px-4 py-3 text-left hover:bg-surface/50 transition-colors"
        onClick={handleToggle}
      >
        <ChevronRight strokeWidth={1.6}
          className={`h-4 w-4 shrink-0 text-muted transition-transform ${
            expanded ? "rotate-90" : ""
          }`}
        />
        <Database strokeWidth={1.6} className="h-4 w-4 shrink-0 text-indigo" />
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <span className="text-sm font-medium text-ink">{label}</span>
            {prefix && (
              <span className="rounded bg-surface px-1.5 py-0.5 text-[10px] font-mono text-muted">
                {prefix}
              </span>
            )}
          </div>
          <div className="text-[11px] text-muted mt-0.5">
            {info.column_count} columns
          </div>
        </div>
        <span className="shrink-0 rounded-full bg-indigo-soft px-2.5 py-0.5 text-xs font-medium text-indigo">
          {formatCount(info.row_count)} rows
        </span>
      </button>

      {/* Expanded content */}
      {expanded && (
        <div className="border-t border-hairline">
          {loading && (
            <div className="flex items-center justify-center py-8 text-sm text-muted">
              Loading sample data…
            </div>
          )}
          {error && (
            <div className="px-4 py-3 text-xs text-amber">
              Failed to load: {error}
            </div>
          )}
          {sample && (
            <>
              {/* Search within table */}
              <div className="flex items-center gap-2 border-b border-hairline/50 px-4 py-2">
                <Search strokeWidth={1.6} className="h-3.5 w-3.5 text-muted" />
                <input
                  type="text"
                  placeholder="Filter rows…"
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                  className="flex-1 bg-transparent text-xs text-ink placeholder-muted outline-none"
                />
                {search && (
                  <button
                    onClick={() => setSearch("")}
                    className="text-[10px] text-muted hover:text-ink"
                  >
                    Clear
                  </button>
                )}
              </div>
              <GenericDataTable data={sample} search={search} />
            </>
          )}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// TierLegend
// ---------------------------------------------------------------------------

/** Compact tier legend bar for page headers. */
export function TierLegend() {
  return (
    <div className="flex items-center gap-4 text-[11px] text-muted">
      <span className="flex items-center gap-1">
        <span className="inline-block h-2 w-2 rounded-full bg-success" />
        Public
      </span>
      <span className="flex items-center gap-1">
        <span className="inline-block h-2 w-2 rounded-full bg-amber" />
        Personal
      </span>
      <span className="flex items-center gap-1">
        <span className="inline-block h-2 w-2 rounded-full bg-danger" />
        <Lock strokeWidth={1.6} className="h-2.5 w-2.5" />
        Sensitive
      </span>
    </div>
  );
}

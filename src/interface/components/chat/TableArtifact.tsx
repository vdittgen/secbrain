/**
 * Tabular artifact for `application/vnd.secbrain.table+json`.
 *
 * Spec shape:
 *   { columns: [{ name, type?, sensitivity_tier? }], rows: [{ ... }] }
 *
 * Supports per-column sort, copy-as-CSV, and per-cell sensitivity
 * masking — Tier 3 cells render as a "•••" pill until clicked.
 *
 * sensitivity_tier: varies (per-column annotations from the spec)
 */

import { useMemo, useState } from "react";
import { ChevronDown, ChevronUp, Copy, Eye, EyeOff } from "lucide-react";
import type { ArtifactRendererProps } from "./registry";

interface TableColumn {
  readonly name: string;
  readonly type?: string;
  readonly sensitivity_tier?: 1 | 2 | 3;
}

interface TableSpec {
  readonly columns: ReadonlyArray<TableColumn>;
  readonly rows: ReadonlyArray<Record<string, unknown>>;
  readonly caption?: string;
}

type SortDir = "asc" | "desc";

function parseSpec(data: unknown): TableSpec | null {
  let spec: unknown = data;
  if (typeof data === "string") {
    try {
      spec = JSON.parse(data);
    } catch {
      return null;
    }
  }
  if (!spec || typeof spec !== "object") return null;
  const obj = spec as TableSpec;
  if (!Array.isArray(obj.columns) || !Array.isArray(obj.rows)) return null;
  return obj;
}

function toCsv(spec: TableSpec): string {
  const escape = (v: unknown): string => {
    const s = v == null ? "" : String(v);
    return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
  };
  const header = spec.columns.map((c) => escape(c.name)).join(",");
  const body = spec.rows
    .map((row) => spec.columns.map((c) => escape(row[c.name])).join(","))
    .join("\n");
  return `${header}\n${body}`;
}

export function TableArtifact({ part }: ArtifactRendererProps) {
  const spec = useMemo(() => parseSpec(part.data), [part.data]);
  const [sortBy, setSortBy] = useState<string | null>(null);
  const [sortDir, setSortDir] = useState<SortDir>("asc");
  const [revealed, setRevealed] = useState<Set<string>>(new Set());

  const sortedRows = useMemo(() => {
    if (!spec) return [];
    if (!sortBy) return spec.rows;
    const dir = sortDir === "asc" ? 1 : -1;
    return [...spec.rows].sort((a, b) => {
      const av = a[sortBy];
      const bv = b[sortBy];
      if (av == null && bv == null) return 0;
      if (av == null) return -dir;
      if (bv == null) return dir;
      if (typeof av === "number" && typeof bv === "number") {
        return (av - bv) * dir;
      }
      return String(av).localeCompare(String(bv)) * dir;
    });
  }, [spec, sortBy, sortDir]);

  if (!spec) {
    return (
      <div className="text-xs text-amber">Invalid table spec.</div>
    );
  }

  const onSort = (name: string) => {
    if (sortBy === name) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortBy(name);
      setSortDir("asc");
    }
  };

  const toggleReveal = (key: string) => {
    setRevealed((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  };

  return (
    <div>
      <div className="mb-1 flex items-center justify-between">
        <span className="text-[11px] text-muted">
          {spec.rows.length} row{spec.rows.length !== 1 && "s"}
          {spec.caption && ` · ${spec.caption}`}
        </span>
        <button
          onClick={() => navigator.clipboard.writeText(toCsv(spec))}
          className="flex items-center gap-1 rounded px-1.5 py-0.5 text-[11px] text-muted hover:bg-surface hover:text-ink"
          title="Copy as CSV"
        >
          <Copy strokeWidth={1.6} className="h-3 w-3" /> CSV
        </button>
      </div>
      <div className="max-h-96 overflow-auto">
        <table className="min-w-full border-collapse text-xs">
          <thead className="sticky top-0 bg-surface/80 backdrop-blur">
            <tr>
              {spec.columns.map((c) => (
                <th
                  key={c.name}
                  onClick={() => onSort(c.name)}
                  className="cursor-pointer select-none border-b border-hairline px-2 py-1 text-left font-medium text-ink"
                  title={c.type ?? ""}
                >
                  <span className="inline-flex items-center gap-1">
                    {c.name}
                    {sortBy === c.name &&
                      (sortDir === "asc" ? (
                        <ChevronUp strokeWidth={1.6} className="h-3 w-3" />
                      ) : (
                        <ChevronDown strokeWidth={1.6} className="h-3 w-3" />
                      ))}
                  </span>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {sortedRows.map((row, rIdx) => (
              <tr key={rIdx} className="odd:bg-surface/20">
                {spec.columns.map((c) => {
                  const key = `${rIdx}:${c.name}`;
                  const tier = c.sensitivity_tier ?? 1;
                  const masked =
                    tier >= 3 && !revealed.has(key) && row[c.name] != null;
                  return (
                    <td
                      key={c.name}
                      className="border-b border-hairline/60 px-2 py-1 align-top"
                    >
                      {masked ? (
                        <button
                          onClick={() => toggleReveal(key)}
                          className="flex items-center gap-1 rounded bg-amber/20 px-1.5 py-0.5 text-[10px] text-danger hover:bg-amber-soft"
                          title="Click to reveal sensitive value"
                        >
                          <EyeOff strokeWidth={1.6} className="h-3 w-3" />
                          •••
                        </button>
                      ) : tier >= 3 && revealed.has(key) ? (
                        <button
                          onClick={() => toggleReveal(key)}
                          className="flex items-center gap-1 text-left"
                          title="Click to hide"
                        >
                          <Eye strokeWidth={1.6} className="h-3 w-3 shrink-0 text-muted" />
                          <span>{String(row[c.name] ?? "")}</span>
                        </button>
                      ) : (
                        String(row[c.name] ?? "")
                      )}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

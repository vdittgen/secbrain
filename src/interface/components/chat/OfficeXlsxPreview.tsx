/**
 * Spreadsheet preview for
 * `application/vnd.openxmlformats-officedocument.spreadsheetml.sheet`
 * parts.
 *
 * Pipeline: fetch the .xlsx as ArrayBuffer → SheetJS XLSX.read →
 * render a tab strip for sheet selection + the active sheet through
 * XLSX.utils.sheet_to_html → rehype-sanitize → dangerouslySetInnerHTML.
 *
 * Tier 3 + remote URL → Lock card. Local paths flow through Tauri's
 * asset protocol via resolveUrl.
 *
 * sensitivity_tier: varies
 */

import { useEffect, useMemo, useState } from "react";
import { AlertCircle, Lock } from "lucide-react";
import rehypeSanitize, { defaultSchema } from "rehype-sanitize";
import { unified } from "unified";
import rehypeParse from "rehype-parse";
import rehypeStringify from "rehype-stringify";
import type { WorkBook } from "xlsx";
import type { ArtifactRendererProps } from "./registry";
import { isRemote, parseSpec, resolveUrl } from "./docHelpers";

const SCHEMA = {
  ...defaultSchema,
  tagNames: [
    ...(defaultSchema.tagNames ?? []),
    "table",
    "thead",
    "tbody",
    "tr",
    "th",
    "td",
  ],
  attributes: {
    ...defaultSchema.attributes,
    "*": [
      ...(defaultSchema.attributes?.["*"] ?? []),
      "style",
      "colspan",
      "rowspan",
    ],
  },
};

async function sanitizeHtml(rawHtml: string): Promise<string> {
  const file = await unified()
    .use(rehypeParse, { fragment: true })
    .use(rehypeSanitize, SCHEMA)
    .use(rehypeStringify)
    .process(rawHtml);
  return String(file);
}

export function OfficeXlsxPreview({ part }: ArtifactRendererProps) {
  const spec = useMemo(() => parseSpec(part.data), [part.data]);
  const tier = part.sensitivity_tier ?? 2;
  const [workbook, setWorkbook] = useState<WorkBook | null>(null);
  const [activeSheet, setActiveSheet] = useState<string | null>(null);
  const [activeHtml, setActiveHtml] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Load the workbook once.
  useEffect(() => {
    if (!spec) return;
    if (tier >= 3 && isRemote(spec.url)) return;
    let cancelled = false;
    void (async () => {
      try {
        const res = await fetch(resolveUrl(spec.url));
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const buf = await res.arrayBuffer();
        const XLSX = await import("xlsx");
        const wb = XLSX.read(buf, { type: "array" });
        if (cancelled) return;
        setWorkbook(wb);
        setActiveSheet(wb.SheetNames[0] ?? null);
      } catch (err) {
        if (cancelled) return;
        setError(err instanceof Error ? err.message : String(err));
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [spec, tier]);

  // Re-render the active sheet whenever the selection changes.
  useEffect(() => {
    if (!workbook || !activeSheet) {
      setActiveHtml(null);
      return;
    }
    const sheet = workbook.Sheets[activeSheet];
    if (!sheet) {
      setActiveHtml(null);
      return;
    }
    let cancelled = false;
    void (async () => {
      const XLSX = await import("xlsx");
      const raw = XLSX.utils.sheet_to_html(sheet);
      const safe = await sanitizeHtml(raw);
      if (cancelled) return;
      setActiveHtml(safe);
    })();
    return () => {
      cancelled = true;
    };
  }, [workbook, activeSheet]);

  if (!spec) {
    return (
      <div className="text-xs text-amber">Invalid document reference.</div>
    );
  }
  if (tier >= 3 && isRemote(spec.url)) {
    return (
      <div className="flex items-start gap-2 rounded border border-amber/40 bg-amber-soft p-2 text-xs text-ink">
        <Lock strokeWidth={1.6} className="mt-0.5 h-3.5 w-3.5 shrink-0 text-danger" />
        <span>Remote documents are blocked for sensitive content.</span>
      </div>
    );
  }
  if (error) {
    return (
      <div className="flex items-start gap-2 text-xs text-amber">
        <AlertCircle strokeWidth={1.6} className="mt-0.5 h-3.5 w-3.5 shrink-0" />
        <span>Couldn&apos;t render spreadsheet: {error}</span>
      </div>
    );
  }
  if (!workbook) {
    return (
      <div className="text-xs text-muted">Loading spreadsheet…</div>
    );
  }
  if (workbook.SheetNames.length === 0) {
    return (
      <div className="text-xs text-muted">Spreadsheet has no sheets.</div>
    );
  }
  return (
    <div className="flex flex-col gap-2">
      {workbook.SheetNames.length > 1 && (
        <div className="flex flex-wrap gap-1 border-b border-hairline">
          {workbook.SheetNames.map((name) => {
            const active = name === activeSheet;
            return (
              <button
                key={name}
                type="button"
                onClick={() => setActiveSheet(name)}
                className={`rounded-t px-2 py-1 text-xs transition-colors ${
                  active
                    ? "border-b-2 border-indigo bg-surface text-ink"
                    : "text-muted hover:bg-surface hover:text-ink"
                }`}
              >
                {name}
              </button>
            );
          })}
        </div>
      )}
      <div className="overflow-x-auto">
        {activeHtml === null ? (
          <div className="text-xs text-muted">Rendering sheet…</div>
        ) : (
          <div
            className="doc-content"
            dangerouslySetInnerHTML={{ __html: activeHtml }}
          />
        )}
      </div>
    </div>
  );
}

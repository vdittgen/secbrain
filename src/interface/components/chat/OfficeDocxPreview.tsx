/**
 * Word document preview for
 * `application/vnd.openxmlformats-officedocument.wordprocessingml.document`
 * parts.
 *
 * Pipeline: fetch the .docx as ArrayBuffer → mammoth.convertToHtml →
 * rehype-sanitize (same strict schema MarkdownRenderer uses) →
 * dangerouslySetInnerHTML. mammoth is lazy-loaded inside the effect so
 * the initial chat bundle stays small.
 *
 * Tier 3 + remote URL → Lock card (no fetch). Local paths flow through
 * Tauri's asset protocol via `resolveUrl`.
 *
 * sensitivity_tier: varies
 */

import { useEffect, useMemo, useState } from "react";
import { AlertCircle, Lock } from "lucide-react";
import rehypeSanitize, { defaultSchema } from "rehype-sanitize";
import { unified } from "unified";
import rehypeParse from "rehype-parse";
import rehypeStringify from "rehype-stringify";
import type { ArtifactRendererProps } from "./registry";
import { isRemote, parseSpec, resolveUrl } from "./docHelpers";

// Match the MarkdownRenderer schema closely so the same allow-list of
// tags/attributes governs rendered docx content. The Word HTML output
// uses tables, headings, lists, inline spans with style — all already
// whitelisted via defaultSchema.
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
    "del",
    "ins",
    "sup",
    "sub",
  ],
  attributes: {
    ...defaultSchema.attributes,
    "*": [
      ...(defaultSchema.attributes?.["*"] ?? []),
      "style",
    ],
  },
  protocols: {
    ...defaultSchema.protocols,
    href: ["http", "https", "mailto"],
    src: ["http", "https", "data"],
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

export function OfficeDocxPreview({ part }: ArtifactRendererProps) {
  const spec = useMemo(() => parseSpec(part.data), [part.data]);
  const tier = part.sensitivity_tier ?? 2;
  const [html, setHtml] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!spec) return;
    if (tier >= 3 && isRemote(spec.url)) return;
    let cancelled = false;
    void (async () => {
      try {
        const res = await fetch(resolveUrl(spec.url));
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const buf = await res.arrayBuffer();
        const mammoth = await import("mammoth");
        const result = await mammoth.convertToHtml({ arrayBuffer: buf });
        const safe = await sanitizeHtml(result.value);
        if (cancelled) return;
        setHtml(safe);
      } catch (err) {
        if (cancelled) return;
        setError(err instanceof Error ? err.message : String(err));
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [spec, tier]);

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
        <span>Couldn&apos;t render document: {error}</span>
      </div>
    );
  }
  if (html === null) {
    return (
      <div className="text-xs text-muted">Loading document…</div>
    );
  }
  return (
    <div
      className="doc-content"
      dangerouslySetInnerHTML={{ __html: html }}
    />
  );
}

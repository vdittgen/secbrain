/**
 * Citation list for `application/vnd.secbrain.citation+json` parts.
 *
 * Accepts either an array of sources directly in `data` or
 * `{ sources: [...] }`. Each source can carry a `sensitivity_tier`,
 * a `content` preview, and an optional `type`/`title`/`url`. This is
 * a refactor of the legacy `SourcesSection` in Chat.tsx so the same
 * UI is reachable both from `msg.sources` (legacy) and a citation
 * part (new).
 *
 * sensitivity_tier: varies
 */

import { useMemo, useState } from "react";
import { ChevronDown, ChevronRight, ExternalLink } from "lucide-react";
import type { ArtifactRendererProps } from "./registry";

export interface Source {
  readonly type?: string;
  readonly title?: string;
  readonly url?: string;
  readonly content?: string;
  readonly sensitivity_tier?: number;
  readonly [key: string]: unknown;
}

const TIER_BADGE: Record<number, { label: string; cls: string }> = {
  1: { label: "PUBLIC", cls: "bg-success-soft text-success" },
  2: { label: "PERSONAL", cls: "bg-amber-soft text-amber" },
  3: { label: "SENSITIVE", cls: "bg-danger-soft text-danger" },
};

function parseSources(data: unknown): Source[] {
  if (Array.isArray(data)) return data as Source[];
  if (data && typeof data === "object" && "sources" in data) {
    const arr = (data as { sources?: unknown }).sources;
    if (Array.isArray(arr)) return arr as Source[];
  }
  if (typeof data === "string") {
    try {
      return parseSources(JSON.parse(data));
    } catch {
      return [];
    }
  }
  return [];
}

/** Reusable list view; consumed by both the part renderer and Chat.tsx. */
export function SourceList({ sources }: { readonly sources: ReadonlyArray<Source> }) {
  if (sources.length === 0) return null;
  return (
    <ul className="space-y-1.5">
      {sources.map((src, i) => {
        const badge = TIER_BADGE[src.sensitivity_tier ?? 1];
        const label = src.title ?? src.content ?? src.type ?? "Unknown source";
        return (
          <li
            key={i}
            className="flex items-start gap-2 rounded-1 bg-bg-2 px-2 py-1.5 text-xs text-muted"
          >
            <span
              className={`shrink-0 rounded-1 px-1.5 py-0.5 text-[10px] font-semibold uppercase ${badge.cls}`}
            >
              {badge.label}
            </span>
            <span className="flex-1 break-words">{label}</span>
            {src.url && (
              <a
                href={src.url}
                target="_blank"
                rel="noopener noreferrer"
                className="text-indigo hover:underline"
                title={src.url}
              >
                <ExternalLink className="h-3 w-3" strokeWidth={1.6} />
              </a>
            )}
          </li>
        );
      })}
    </ul>
  );
}

export function CitationCards({ part }: ArtifactRendererProps) {
  const sources = useMemo(() => parseSources(part.data), [part.data]);
  const [open, setOpen] = useState(false);
  if (sources.length === 0) return null;
  return (
    <div>
      <button
        onClick={() => setOpen((o) => !o)}
        className="flex items-center gap-1 text-xs text-muted hover:text-ink"
      >
        {open ? (
          <ChevronDown className="h-3 w-3" strokeWidth={1.6} />
        ) : (
          <ChevronRight className="h-3 w-3" strokeWidth={1.6} />
        )}
        {sources.length} source{sources.length !== 1 && "s"} used
      </button>
      {open && (
        <div className="mt-1.5">
          <SourceList sources={sources} />
        </div>
      )}
    </div>
  );
}

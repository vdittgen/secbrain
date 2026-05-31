/**
 * Collapsible "thinking" trace.
 *
 * Used both for `application/vnd.secbrain.thinking+json` parts (when
 * persisted) and for live `thinking` chunks streamed from the brain
 * agent. Always collapsed by default — reasoning traces are noisy.
 *
 * sensitivity_tier: 3 (reasoning can echo Tier 3 inputs)
 */

import { useMemo, useState } from "react";
import { Brain, ChevronDown, ChevronRight } from "lucide-react";
import type { ArtifactRendererProps } from "./registry";

function asText(data: unknown): string {
  if (typeof data === "string") return data;
  if (data && typeof data === "object" && "text" in data) {
    const t = (data as { text?: unknown }).text;
    if (typeof t === "string") return t;
  }
  return "";
}

export function ThinkingBlock({ part }: ArtifactRendererProps) {
  const text = useMemo(() => asText(part.data), [part.data]);
  const [open, setOpen] = useState(false);
  if (!text) return null;
  return (
    <div className="my-1">
      <button
        onClick={() => setOpen((o) => !o)}
        className="flex items-center gap-1 text-xs text-muted hover:text-ink"
      >
        {open ? (
          <ChevronDown className="h-3 w-3" strokeWidth={1.6} />
        ) : (
          <ChevronRight className="h-3 w-3" strokeWidth={1.6} />
        )}
        <Brain className="h-3 w-3" strokeWidth={1.6} />
        {open ? "Hide reasoning" : "Show reasoning"}
      </button>
      {open && (
        <pre className="mt-1 max-h-64 overflow-auto whitespace-pre-wrap rounded-2 bg-bg-2 p-2 font-mono text-[11px] text-muted">
          {text}
        </pre>
      )}
    </div>
  );
}

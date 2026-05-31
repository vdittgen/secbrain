/**
 * Right-hand panel that hosts large artifacts (charts, HTML widgets,
 * PDFs, code) while the chat keeps streaming. Similar to Claude's
 * Artifacts pane: one focused part at a time, with quick toggles to
 * recently-opened parts.
 *
 * sensitivity_tier: 1 (renders parts whose own tier is preserved)
 */

import { Suspense } from "react";
import { Loader2, X } from "lucide-react";
import type { MessagePart, SensitivityTier } from "../../types/chat";
import { getRenderer } from "./registry";

const TIER_LABEL: Record<SensitivityTier, { label: string; cls: string }> = {
  1: { label: "PUBLIC", cls: "bg-success-soft text-success" },
  2: { label: "PERSONAL", cls: "bg-amber-soft text-amber" },
  3: { label: "SENSITIVE", cls: "bg-danger-soft text-danger" },
};

interface ArtifactSidePanelProps {
  readonly part: MessagePart;
  readonly history: ReadonlyArray<MessagePart>;
  readonly onSelect: (part: MessagePart) => void;
  readonly onClose: () => void;
}

export function ArtifactSidePanel({
  part,
  history,
  onSelect,
  onClose,
}: ArtifactSidePanelProps) {
  const Renderer = getRenderer(part.mime);
  const tier = (part.sensitivity_tier ?? 2) as SensitivityTier;
  const tierBadge = TIER_LABEL[tier];

  return (
    <aside className="flex h-full w-[480px] shrink-0 flex-col border-l border-hairline bg-surface/30">
      <div className="flex items-center justify-between gap-2 border-b border-hairline px-3 py-2">
        <div className="flex min-w-0 items-center gap-2">
          <span className="truncate text-sm font-medium text-ink">
            {part.title || part.mime}
          </span>
          <span
            className={`shrink-0 rounded-1 px-1.5 py-0.5 text-[10px] font-semibold uppercase ${tierBadge.cls}`}
          >
            {tierBadge.label}
          </span>
        </div>
        <button
          onClick={onClose}
          className="rounded-1 p-1 text-muted hover:bg-surface hover:text-ink"
          title="Close panel"
        >
          <X className="h-4 w-4" strokeWidth={1.6} />
        </button>
      </div>

      {history.length > 1 && (
        <div className="flex gap-1 overflow-x-auto border-b border-hairline px-3 py-1.5">
          {history.map((p) => (
            <button
              key={p.id}
              onClick={() => onSelect(p)}
              className={`shrink-0 rounded-1 px-2 py-0.5 text-[11px] ${
                p.id === part.id
                  ? "bg-indigo-soft text-indigo"
                  : "text-muted hover:bg-surface hover:text-ink"
              }`}
            >
              {p.title || p.mime}
            </button>
          ))}
        </div>
      )}

      <div className="flex-1 overflow-auto px-3 py-3">
        <Suspense
          fallback={
            <div className="flex items-center gap-2 text-xs text-muted">
              <Loader2 className="h-3 w-3 animate-spin" strokeWidth={1.6} />
              Loading…
            </div>
          }
        >
          <Renderer part={part} />
        </Suspense>
      </div>
    </aside>
  );
}

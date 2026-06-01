/**
 * Chrome around any artifact: title, copy/download/expand actions,
 * sensitivity badge, and an error boundary. Each MessagePart on an
 * assistant message renders inside one of these frames.
 *
 * Borderless markdown is the special case: when the part is the
 * default `text/markdown` body, the frame collapses to a plain
 * container so the chat bubble still feels light.
 *
 * sensitivity_tier: 1
 */

import { Component, Suspense } from "react";
import type { ReactNode } from "react";
import {
  AlertCircle,
  Copy,
  Download,
  ExternalLink,
  Loader2,
} from "lucide-react";
import type { MessagePart, SensitivityTier } from "../../types/chat";
import { getRenderer, shouldOpenInPanel } from "./registry";

interface ArtifactFrameProps {
  readonly part: MessagePart;
  readonly onOpenInPanel?: (part: MessagePart) => void;
}

const TIER_LABEL: Record<SensitivityTier, { label: string; cls: string }> = {
  1: { label: "PUBLIC", cls: "bg-success-soft text-success" },
  2: { label: "PERSONAL", cls: "bg-amber-soft text-amber" },
  3: { label: "SENSITIVE", cls: "bg-danger-soft text-danger" },
};

function isPlainMarkdownBody(part: MessagePart): boolean {
  return (
    part.mime === "text/markdown" &&
    !part.title &&
    part.display !== "panel"
  );
}

function copyText(data: string | object): void {
  const text =
    typeof data === "string" ? data : JSON.stringify(data, null, 2);
  void navigator.clipboard.writeText(text);
}

function downloadPart(part: MessagePart): void {
  const isText = typeof part.data === "string";
  const blob = new Blob(
    [isText ? (part.data as string) : JSON.stringify(part.data, null, 2)],
    { type: part.mime || "text/plain" },
  );
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = part.title || filenameForMime(part.mime, part.id);
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

function filenameForMime(mime: string, id: string): string {
  if (mime === "text/markdown") return `${id}.md`;
  if (mime === "text/html") return `${id}.html`;
  if (mime === "text/vnd.mermaid") return `${id}.mmd`;
  if (mime === "application/vnd.vega-lite+json") return `${id}.json`;
  if (mime.startsWith("text/x-")) return `${id}.${mime.slice("text/x-".length)}`;
  return id;
}

export function ArtifactFrame({ part, onOpenInPanel }: ArtifactFrameProps) {
  const Renderer = getRenderer(part.mime);
  const tier = (part.sensitivity_tier ?? 2) as SensitivityTier;
  const tierBadge = TIER_LABEL[tier];
  const wantsPanel = shouldOpenInPanel(part);

  // Default markdown body: render bare to keep chat bubbles lightweight.
  if (isPlainMarkdownBody(part)) {
    return (
      <ArtifactErrorBoundary partId={part.id}>
        <Suspense fallback={<RendererFallback />}>
          <Renderer part={part} onOpenInPanel={onOpenInPanel} />
        </Suspense>
      </ArtifactErrorBoundary>
    );
  }

  return (
    <div className="my-2 overflow-hidden rounded-2 border border-hairline bg-surface">
      <div className="flex items-center justify-between gap-2 border-b border-hairline bg-bg-2 px-3 py-1.5">
        <div className="flex min-w-0 items-center gap-2">
          <span className="truncate text-xs font-medium text-ink">
            {part.title || prettyMimeLabel(part.mime)}
          </span>
          <span
            className={`shrink-0 rounded-1 px-1.5 py-0.5 text-[10px] font-semibold uppercase ${tierBadge.cls}`}
            title="Sensitivity tier"
          >
            {tierBadge.label}
          </span>
          {part.streaming && (
            <Loader2 className="h-3 w-3 shrink-0 animate-spin text-muted" strokeWidth={1.6} />
          )}
        </div>
        <div className="flex items-center gap-1">
          <IconButton
            label="Copy"
            onClick={() => copyText(part.data)}
            icon={<Copy className="h-3.5 w-3.5" strokeWidth={1.6} />}
          />
          <IconButton
            label="Download"
            onClick={() => downloadPart(part)}
            icon={<Download className="h-3.5 w-3.5" strokeWidth={1.6} />}
          />
          {onOpenInPanel && !wantsPanel && (
            <IconButton
              label="Open in panel"
              onClick={() => onOpenInPanel(part)}
              icon={<ExternalLink className="h-3.5 w-3.5" strokeWidth={1.6} />}
            />
          )}
        </div>
      </div>

      <div className="px-3 py-2">
        {wantsPanel ? (
          <PanelStub
            part={part}
            onOpen={() => onOpenInPanel?.(part)}
          />
        ) : (
          <ArtifactErrorBoundary partId={part.id}>
            <Suspense fallback={<RendererFallback />}>
              <Renderer part={part} onOpenInPanel={onOpenInPanel} />
            </Suspense>
          </ArtifactErrorBoundary>
        )}
      </div>
    </div>
  );
}

function prettyMimeLabel(mime: string): string {
  if (mime === "text/markdown") return "Markdown";
  if (mime === "text/html") return "HTML preview";
  if (mime === "text/vnd.mermaid") return "Diagram";
  if (mime === "application/vnd.vega-lite+json") return "Chart";
  if (mime === "application/vnd.arandu.table+json") return "Table";
  if (mime === "application/vnd.arandu.plan+json") return "Plan";
  if (mime === "application/vnd.arandu.thinking+json") return "Thinking";
  if (mime === "application/vnd.arandu.citation+json") return "Sources";
  if (mime === "application/pdf") return "PDF preview";
  if (mime.includes("wordprocessingml")) return "Word document";
  if (mime.includes("spreadsheetml")) return "Spreadsheet";
  if (mime.includes("presentationml")) return "Presentation";
  if (mime.startsWith("text/x-")) return mime.slice("text/x-".length).toUpperCase();
  if (mime.startsWith("image/")) return "Image";
  if (mime.startsWith("audio/")) return "Audio";
  if (mime.startsWith("video/")) return "Video";
  return mime;
}

function IconButton({
  label,
  onClick,
  icon,
}: {
  readonly label: string;
  readonly onClick: () => void;
  readonly icon: ReactNode;
}) {
  return (
    <button
      type="button"
      title={label}
      onClick={onClick}
      className="rounded-1 p-1 text-muted transition-colors hover:bg-surface hover:text-ink"
    >
      {icon}
    </button>
  );
}

function PanelStub({
  part,
  onOpen,
}: {
  readonly part: MessagePart;
  readonly onOpen: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onOpen}
      className="flex w-full items-center justify-between rounded-2 bg-bg-2 px-3 py-2 text-left text-xs text-muted hover:bg-surface-2"
    >
      <span>
        {part.title || prettyMimeLabel(part.mime)} · Open in side panel
      </span>
      <ExternalLink className="h-3.5 w-3.5" strokeWidth={1.6} />
    </button>
  );
}

function RendererFallback() {
  return (
    <div className="flex items-center gap-2 text-xs text-muted">
      <Loader2 className="h-3 w-3 animate-spin" strokeWidth={1.6} />
      Loading renderer…
    </div>
  );
}

interface ErrorBoundaryProps {
  readonly partId: string;
  readonly children: ReactNode;
}

interface ErrorBoundaryState {
  readonly error: Error | null;
}

class ArtifactErrorBoundary extends Component<
  ErrorBoundaryProps,
  ErrorBoundaryState
> {
  state: ErrorBoundaryState = { error: null };

  static getDerivedStateFromError(error: Error): ErrorBoundaryState {
    return { error };
  }

  componentDidCatch(error: Error): void {
    console.warn(
      `[ArtifactFrame] Renderer for part ${this.props.partId} threw:`,
      error,
    );
  }

  render(): ReactNode {
    if (this.state.error) {
      return (
        <div className="flex items-center gap-2 text-xs text-amber">
          <AlertCircle className="h-3.5 w-3.5" strokeWidth={1.6} />
          Couldn&apos;t render this artifact.
        </div>
      );
    }
    return this.props.children;
  }
}

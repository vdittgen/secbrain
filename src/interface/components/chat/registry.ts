/**
 * Artifact renderer registry.
 *
 * Maps a MessagePart `mime` string to a React component that renders it.
 * Lookup matches by exact MIME first, then by prefix (`image/`, `audio/`,
 * `video/`, `text/x-`). Anything unknown falls back to MarkdownRenderer
 * — a strict win over the legacy plain-text bubble for unstructured text.
 *
 * Keep imports cheap. Heavy renderers (shiki, mermaid, react-vega,
 * pdfjs-dist) should lazy-load inside their component so the initial
 * chat bundle stays small.
 *
 * sensitivity_tier: 1 (this file is a routing table)
 */

import type { ComponentType, LazyExoticComponent } from "react";
import { lazy } from "react";
import type { MessagePart } from "../../types/chat";

export interface ArtifactRendererProps {
  readonly part: MessagePart;
  /** Invoked when the user clicks "Open in panel" on a renderer. */
  readonly onOpenInPanel?: (part: MessagePart) => void;
}

export type ArtifactRenderer =
  | ComponentType<ArtifactRendererProps>
  | LazyExoticComponent<ComponentType<ArtifactRendererProps>>;

// Eager renderers — small and used on every assistant message.
import { MarkdownRenderer } from "./MarkdownRenderer";
import { CitationCards } from "./CitationCards";
import { ThinkingBlock } from "./ThinkingBlock";
import { PlanCard } from "./PlanCard";

// Lazy renderers — pulled in only when an artifact of this kind appears.
const CodeBlock = lazy(() =>
  import("./CodeBlock").then((m) => ({ default: m.CodeBlock })),
);
const MermaidArtifact = lazy(() =>
  import("./MermaidArtifact").then((m) => ({ default: m.MermaidArtifact })),
);
const ChartArtifact = lazy(() =>
  import("./ChartArtifact").then((m) => ({ default: m.ChartArtifact })),
);
const TableArtifact = lazy(() =>
  import("./TableArtifact").then((m) => ({ default: m.TableArtifact })),
);
const HtmlSandbox = lazy(() =>
  import("./HtmlSandbox").then((m) => ({ default: m.HtmlSandbox })),
);
const MediaArtifact = lazy(() =>
  import("./MediaArtifact").then((m) => ({ default: m.MediaArtifact })),
);
const DocumentPreview = lazy(() =>
  import("./DocumentPreview").then((m) => ({ default: m.DocumentPreview })),
);
const OfficeDocxPreview = lazy(() =>
  import("./OfficeDocxPreview").then((m) => ({ default: m.OfficeDocxPreview })),
);
const OfficeXlsxPreview = lazy(() =>
  import("./OfficeXlsxPreview").then((m) => ({ default: m.OfficeXlsxPreview })),
);
const OfficePptxPreview = lazy(() =>
  import("./OfficePptxPreview").then((m) => ({ default: m.OfficePptxPreview })),
);

const EXACT: Record<string, ArtifactRenderer> = {
  "text/markdown": MarkdownRenderer,
  "text/vnd.mermaid": MermaidArtifact,
  "text/html": HtmlSandbox,
  "application/vnd.vega-lite+json": ChartArtifact,
  "application/vnd.secbrain.table+json": TableArtifact,
  "application/vnd.secbrain.citation+json": CitationCards,
  "application/vnd.secbrain.plan+json": PlanCard,
  "application/vnd.secbrain.thinking+json": ThinkingBlock,
  "application/pdf": DocumentPreview,
  "application/vnd.openxmlformats-officedocument.wordprocessingml.document":
    OfficeDocxPreview,
  "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet":
    OfficeXlsxPreview,
  "application/vnd.openxmlformats-officedocument.presentationml.presentation":
    OfficePptxPreview,
};

// Prefix matches (longest-prefix wins via ordering).
const PREFIX: ReadonlyArray<[string, ArtifactRenderer]> = [
  ["text/x-", CodeBlock],
  ["image/", MediaArtifact],
  ["audio/", MediaArtifact],
  ["video/", MediaArtifact],
];

/** Returns the renderer component for a given MIME. Never returns null;
 * unknown MIMEs render as markdown so plain text still renders cleanly. */
export function getRenderer(mime: string): ArtifactRenderer {
  if (mime in EXACT) return EXACT[mime];
  for (const [prefix, renderer] of PREFIX) {
    if (mime.startsWith(prefix)) return renderer;
  }
  return MarkdownRenderer;
}

/** Whether the artifact should auto-open in the side panel. */
export function shouldOpenInPanel(part: MessagePart): boolean {
  return part.display === "panel";
}

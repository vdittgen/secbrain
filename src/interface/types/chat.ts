/**
 * Shared chat types.
 *
 * Mirrors `src/agents/core/output_types.MessagePart` and the
 * `ChatMessage` struct in `src-tauri/src/commands/types.rs`. The chat
 * `brain-stream` channel streams `MessagePart`s incrementally; the
 * artifact renderer registry on the frontend mounts a component per
 * `mime`.
 *
 * sensitivity_tier: varies (carries user-derived content)
 */

export type SensitivityTier = 1 | 2 | 3;

export interface MessagePart {
  /** Stable id within a single message; lets streaming chunks target a part. */
  readonly id: string;
  /**
   * MIME type the renderer registry keys on. Common values:
   * - `text/markdown` (default)
   * - `text/x-python` / `text/x-sql` / `text/x-shell` / etc.
   * - `text/vnd.mermaid`
   * - `text/html`
   * - `application/vnd.vega-lite+json`
   * - `application/vnd.secbrain.table+json`
   * - `application/vnd.secbrain.citation+json`
   * - `application/vnd.secbrain.plan+json`
   * - `image/*`, `audio/*`, `video/*`
   * - `application/pdf`
   */
  readonly mime: string;
  readonly title?: string;
  /**
   * String for textual MIMEs, object for JSON specs. May arrive empty
   * and grow incrementally via `part_chunk` streaming chunks.
   */
  data: string | object;
  readonly display?: "inline" | "panel";
  readonly sensitivity_tier?: SensitivityTier;
  readonly metadata?: Record<string, unknown>;
  /** Runtime-only: true while chunks are still arriving. */
  streaming?: boolean;
}

/**
 * Common MIME constants. Strings are the source of truth — these aliases
 * exist only to catch typos.
 */
export const MIME = {
  MARKDOWN: "text/markdown",
  HTML: "text/html",
  MERMAID: "text/vnd.mermaid",
  VEGA_LITE: "application/vnd.vega-lite+json",
  TABLE: "application/vnd.secbrain.table+json",
  CITATION: "application/vnd.secbrain.citation+json",
  PLAN: "application/vnd.secbrain.plan+json",
  PDF: "application/pdf",
  DOCX:
    "application/vnd.openxmlformats-officedocument" +
    ".wordprocessingml.document",
  XLSX:
    "application/vnd.openxmlformats-officedocument" +
    ".spreadsheetml.sheet",
  PPTX:
    "application/vnd.openxmlformats-officedocument" +
    ".presentationml.presentation",
} as const;

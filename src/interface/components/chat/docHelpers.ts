/**
 * Shared helpers for `application/*` document renderers (PDF, docx,
 * xlsx, pptx). Centralises the spec-parsing and remote-URL gate so
 * every renderer enforces the same privacy boundary.
 *
 * sensitivity_tier: 1 (this file is plumbing, not user data)
 */

import { convertFileSrc } from "@tauri-apps/api/core";

export interface DocSpec {
  readonly url: string;
  /** Optional page index — PDF-specific; ignored by other renderers. */
  readonly page?: number;
}

/** Accept either a bare URL string or `{ url, page? }` in `part.data`. */
export function parseSpec(data: unknown): DocSpec | null {
  if (typeof data === "string") return { url: data };
  if (data && typeof data === "object" && "url" in data) {
    const obj = data as DocSpec;
    if (typeof obj.url === "string") return obj;
  }
  return null;
}

/** Distinguishes a remote http(s) URL from a local path or data/blob URL. */
export function isRemote(url: string): boolean {
  return /^https?:/i.test(url);
}

/**
 * Map a local filesystem path to a tauri:// URL the webview can fetch.
 * Pass-through for URLs that are already addressable (http/https/data/blob).
 */
export function resolveUrl(url: string): string {
  if (/^(?:https?:|data:|blob:)/i.test(url)) return url;
  return convertFileSrc(url);
}

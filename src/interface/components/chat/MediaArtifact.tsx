/**
 * Image / audio / video renderer.
 *
 * Accepts either:
 *   - a string `data` containing a URL (http(s):, data:, or a local path)
 *   - an object `data` with { url, alt?, width?, height? }
 *
 * Local paths under the data directory are converted via Tauri's
 * `convertFileSrc`. Tier 3 content must be a local file — we refuse
 * to load remote URLs for sensitive parts.
 *
 * sensitivity_tier: varies
 */

import { useMemo, useState } from "react";
import { convertFileSrc } from "@tauri-apps/api/core";
import { Lock, X } from "lucide-react";
import type { ArtifactRendererProps } from "./registry";

interface MediaSpec {
  readonly url: string;
  readonly alt?: string;
  readonly width?: number;
  readonly height?: number;
}

function parseSpec(data: unknown): MediaSpec | null {
  if (typeof data === "string") {
    return { url: data };
  }
  if (data && typeof data === "object" && "url" in data) {
    const obj = data as MediaSpec;
    if (typeof obj.url === "string") return obj;
  }
  return null;
}

function isRemoteUrl(url: string): boolean {
  return /^https?:/i.test(url);
}

function resolveUrl(url: string): string {
  if (/^(?:https?:|data:|blob:)/i.test(url)) return url;
  // Treat anything else as a filesystem path.
  return convertFileSrc(url);
}

export function MediaArtifact({ part }: ArtifactRendererProps) {
  const spec = useMemo(() => parseSpec(part.data), [part.data]);
  const tier = part.sensitivity_tier ?? 2;
  const [lightbox, setLightbox] = useState(false);

  if (!spec) {
    return (
      <div className="text-xs text-amber">Invalid media reference.</div>
    );
  }

  if (tier >= 3 && isRemoteUrl(spec.url)) {
    return (
      <div className="flex items-start gap-2 rounded border border-amber/40 bg-amber-soft p-2 text-xs text-ink">
        <Lock strokeWidth={1.6} className="mt-0.5 h-3.5 w-3.5 shrink-0 text-danger" />
        <span>
          Remote media is blocked for sensitive content. Save the file
          locally to preview.
        </span>
      </div>
    );
  }

  const src = resolveUrl(spec.url);

  if (part.mime.startsWith("image/")) {
    return (
      <>
        <button
          type="button"
          onClick={() => setLightbox(true)}
          className="block max-w-full"
        >
          <img
            src={src}
            alt={spec.alt ?? part.title ?? "image"}
            width={spec.width}
            height={spec.height}
            loading="lazy"
            className="max-h-96 max-w-full rounded object-contain"
          />
        </button>
        {lightbox && (
          <div
            className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 p-6"
            onClick={() => setLightbox(false)}
          >
            <button
              className="absolute right-3 top-3 rounded bg-surface p-1.5 text-ink hover:bg-hairline"
              onClick={() => setLightbox(false)}
              title="Close"
            >
              <X strokeWidth={1.6} className="h-4 w-4" />
            </button>
            <img
              src={src}
              alt={spec.alt ?? "preview"}
              className="max-h-full max-w-full rounded object-contain"
              onClick={(e) => e.stopPropagation()}
            />
          </div>
        )}
      </>
    );
  }
  if (part.mime.startsWith("audio/")) {
    return (
      <audio
        controls
        src={src}
        preload="metadata"
        className="w-full"
      />
    );
  }
  if (part.mime.startsWith("video/")) {
    return (
      <video
        controls
        src={src}
        preload="metadata"
        className="max-h-96 w-full rounded"
      />
    );
  }
  return null;
}

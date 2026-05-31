/**
 * PowerPoint preview for
 * `application/vnd.openxmlformats-officedocument.presentationml.presentation`
 * parts.
 *
 * No good production-quality client-side PPTX renderer exists, so this
 * is a deliberately scoped text + thumbnail preview: enough to skim a
 * deck without leaving the app, but NOT a faithful visual render of
 * shapes, fonts, or layout. Pipeline:
 *
 *   .pptx ArrayBuffer
 *     → JSZip (lazy)
 *     → docProps/thumbnail.{jpeg|png} → blob URL (one image, usually slide 1)
 *     → ppt/slides/slide*.xml → DOMParser → <a:t> text per <a:p> paragraph
 *
 * Tier 3 + remote URL → Lock card. Local paths flow through Tauri's
 * asset protocol via resolveUrl.
 *
 * sensitivity_tier: varies
 */

import { useEffect, useMemo, useState } from "react";
import { AlertCircle, Lock } from "lucide-react";
import type { ArtifactRendererProps } from "./registry";
import { isRemote, parseSpec, resolveUrl } from "./docHelpers";

const DRAWINGML_NS = "http://schemas.openxmlformats.org/drawingml/2006/main";

interface Slide {
  readonly index: number;
  readonly lines: ReadonlyArray<string>;
}

interface ParsedDeck {
  readonly slides: ReadonlyArray<Slide>;
  readonly thumbnailUrl: string | null;
}

function extractSlideLines(slideXml: string): string[] {
  const doc = new DOMParser().parseFromString(slideXml, "text/xml");
  if (doc.querySelector("parsererror")) return [];
  const paragraphs = doc.getElementsByTagNameNS(DRAWINGML_NS, "p");
  const lines: string[] = [];
  for (const p of Array.from(paragraphs)) {
    const texts = p.getElementsByTagNameNS(DRAWINGML_NS, "t");
    const line = Array.from(texts)
      .map((t) => t.textContent ?? "")
      .join("")
      .trim();
    if (line) lines.push(line);
  }
  return lines;
}

function slideNumber(path: string): number {
  const match = /slide(\d+)\.xml$/i.exec(path);
  return match ? parseInt(match[1], 10) : Number.MAX_SAFE_INTEGER;
}

export function OfficePptxPreview({ part }: ArtifactRendererProps) {
  const spec = useMemo(() => parseSpec(part.data), [part.data]);
  const tier = part.sensitivity_tier ?? 2;
  const [deck, setDeck] = useState<ParsedDeck | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!spec) return;
    if (tier >= 3 && isRemote(spec.url)) return;
    let cancelled = false;
    let createdUrl: string | null = null;
    void (async () => {
      try {
        const res = await fetch(resolveUrl(spec.url));
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const buf = await res.arrayBuffer();
        const JSZipModule = await import("jszip");
        const JSZip = JSZipModule.default;
        const zip = await JSZip.loadAsync(buf);

        // Thumbnail: most pptx files embed one in docProps/.
        let thumbnailUrl: string | null = null;
        const thumb =
          zip.file("docProps/thumbnail.jpeg") ??
          zip.file("docProps/thumbnail.jpg") ??
          zip.file("docProps/thumbnail.png");
        if (thumb) {
          const blob = await thumb.async("blob");
          createdUrl = URL.createObjectURL(blob);
          thumbnailUrl = createdUrl;
        }

        // Slides: ppt/slides/slide{N}.xml — sorted by N to preserve order.
        const slidePaths = Object.keys(zip.files)
          .filter((p) => /^ppt\/slides\/slide\d+\.xml$/i.test(p))
          .sort((a, b) => slideNumber(a) - slideNumber(b));

        const slides: Slide[] = [];
        for (const path of slidePaths) {
          const xml = await zip.files[path].async("string");
          slides.push({ index: slideNumber(path), lines: extractSlideLines(xml) });
        }

        if (cancelled) {
          if (createdUrl) URL.revokeObjectURL(createdUrl);
          return;
        }
        setDeck({ slides, thumbnailUrl });
      } catch (err) {
        if (cancelled) return;
        setError(err instanceof Error ? err.message : String(err));
      }
    })();
    return () => {
      cancelled = true;
      if (createdUrl) URL.revokeObjectURL(createdUrl);
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
        <span>Couldn&apos;t render presentation: {error}</span>
      </div>
    );
  }
  if (!deck) {
    return (
      <div className="text-xs text-muted">Loading presentation…</div>
    );
  }
  if (deck.slides.length === 0) {
    return (
      <div className="text-xs text-muted">Presentation has no slides.</div>
    );
  }
  return (
    <div className="flex flex-col gap-3">
      {deck.thumbnailUrl && (
        <div className="flex flex-col gap-1">
          <img
            src={deck.thumbnailUrl}
            alt="Slide thumbnail"
            className="max-w-full rounded border border-hairline"
          />
          <p className="text-[10px] text-muted">
            Thumbnail (typically slide 1). Text preview below covers all
            slides — visual layout is not rendered.
          </p>
        </div>
      )}
      <ol className="flex flex-col gap-2">
        {deck.slides.map((slide) => (
          <li
            key={slide.index}
            className="rounded border border-hairline bg-surface/40 p-2"
          >
            <div className="mb-1 text-[10px] uppercase tracking-wide text-muted">
              Slide {slide.index}
            </div>
            {slide.lines.length === 0 ? (
              <p className="text-xs italic text-muted">(no text)</p>
            ) : (
              <>
                <div className="text-sm font-semibold text-ink">
                  {slide.lines[0]}
                </div>
                {slide.lines.length > 1 && (
                  <ul className="mt-1 list-disc pl-5 text-sm text-ink">
                    {slide.lines.slice(1).map((line, i) => (
                      <li key={i}>{line}</li>
                    ))}
                  </ul>
                )}
              </>
            )}
          </li>
        ))}
      </ol>
    </div>
  );
}

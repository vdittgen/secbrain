/**
 * PDF preview for `application/pdf` parts.
 *
 * Accepts either a URL string in `data` or `{ url, page? }`. pdfjs is
 * lazy-loaded; we render a single page inline by default and rely on
 * the surrounding ArtifactFrame to offer "Open in panel" for full doc
 * viewing.
 *
 * sensitivity_tier: varies
 */

import { useEffect, useMemo, useRef, useState } from "react";
import { AlertCircle, Lock } from "lucide-react";
import type { ArtifactRendererProps } from "./registry";
import { isRemote, parseSpec, resolveUrl } from "./docHelpers";

export function DocumentPreview({ part }: ArtifactRendererProps) {
  const spec = useMemo(() => parseSpec(part.data), [part.data]);
  const tier = part.sensitivity_tier ?? 2;
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const [pageCount, setPageCount] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!spec) return;
    if (tier >= 3 && isRemote(spec.url)) return;
    let cancelled = false;
    void (async () => {
      try {
        const pdfjs = await import("pdfjs-dist");
        // Worker via blob to avoid build-time worker path config.
        const workerSrc =
          "https://cdn.jsdelivr.net/npm/pdfjs-dist@4.5.136/build/pdf.worker.min.mjs";
        try {
          (pdfjs as unknown as { GlobalWorkerOptions: { workerSrc: string } })
            .GlobalWorkerOptions.workerSrc = workerSrc;
        } catch {
          // ignore — some builds ship a worker already
        }
        const doc = await pdfjs.getDocument({ url: resolveUrl(spec.url) })
          .promise;
        if (cancelled) return;
        setPageCount(doc.numPages);
        const page = await doc.getPage(spec.page ?? 1);
        const viewport = page.getViewport({ scale: 1.0 });
        const canvas = canvasRef.current;
        if (!canvas) return;
        const ctx = canvas.getContext("2d");
        if (!ctx) return;
        canvas.width = viewport.width;
        canvas.height = viewport.height;
        await page.render({ canvasContext: ctx, viewport }).promise;
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
    return <div className="text-xs text-amber">Invalid document reference.</div>;
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
        <span>Couldn&apos;t render PDF: {error}</span>
      </div>
    );
  }
  return (
    <div>
      <canvas ref={canvasRef} className="max-w-full rounded" />
      {pageCount != null && pageCount > 1 && (
        <p className="mt-1 text-[11px] text-muted">
          Page {spec.page ?? 1} of {pageCount}
        </p>
      )}
    </div>
  );
}

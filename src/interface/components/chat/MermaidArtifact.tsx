/**
 * Mermaid diagram renderer.
 *
 * Mermaid is lazily imported, initialized once with `securityLevel: "strict"`
 * (no HTML, no clickable JS links), and renders each diagram to SVG.
 *
 * sensitivity_tier: varies
 */

import { useEffect, useId, useMemo, useRef, useState } from "react";
import { AlertCircle } from "lucide-react";
import type { ArtifactRendererProps } from "./registry";

let mermaidInitPromise: Promise<typeof import("mermaid").default> | null = null;

async function getMermaid() {
  if (mermaidInitPromise) return mermaidInitPromise;
  mermaidInitPromise = (async () => {
    const mermaid = (await import("mermaid")).default;
    mermaid.initialize({
      startOnLoad: false,
      securityLevel: "strict",
      theme: "dark",
      themeVariables: {
        background: "#243447",
        primaryColor: "#2E86AB",
        primaryTextColor: "#E0E7EE",
        lineColor: "#8899AA",
      },
    });
    return mermaid;
  })();
  return mermaidInitPromise;
}

export function MermaidArtifact({ part }: ArtifactRendererProps) {
  const source = useMemo(
    () => (typeof part.data === "string" ? part.data : ""),
    [part.data],
  );
  const id = useId().replace(/[^a-zA-Z0-9_-]/g, "");
  const containerRef = useRef<HTMLDivElement | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!source || part.streaming) return;
    let cancelled = false;
    void (async () => {
      try {
        const mermaid = await getMermaid();
        const { svg } = await mermaid.render(`mmd-${id}`, source);
        if (cancelled) return;
        if (containerRef.current) {
          containerRef.current.innerHTML = svg;
        }
        setError(null);
      } catch (err) {
        if (cancelled) return;
        const msg = err instanceof Error ? err.message : String(err);
        setError(msg);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [source, id, part.streaming]);

  if (part.streaming) {
    return (
      <pre className="overflow-x-auto rounded bg-surface/40 p-2 text-xs text-muted">
        {source}
      </pre>
    );
  }

  if (error) {
    return (
      <div className="flex items-start gap-2 text-xs text-amber">
        <AlertCircle strokeWidth={1.6} className="mt-0.5 h-3.5 w-3.5 shrink-0" />
        <span>Couldn&apos;t render diagram: {error}</span>
      </div>
    );
  }

  return (
    <div
      ref={containerRef}
      className="flex justify-center overflow-x-auto py-1"
    />
  );
}

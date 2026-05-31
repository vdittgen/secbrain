/**
 * Vega-Lite chart renderer.
 *
 * Accepts a Vega-Lite spec (string or object) in `part.data` and renders
 * it via react-vega. Rejects specs that reference remote `data.url`
 * endpoints — charts must inline their data or load from local sources
 * so we never leak intent through cross-origin requests.
 *
 * sensitivity_tier: varies
 */

import { lazy, Suspense, useMemo } from "react";
import { AlertCircle, Loader2 } from "lucide-react";
import type { ArtifactRendererProps } from "./registry";

const VegaLite = lazy(() =>
  import("react-vega").then((m) => ({ default: m.VegaLite })),
);

function parseSpec(data: unknown): { spec: object | null; error?: string } {
  let spec: unknown = data;
  if (typeof data === "string") {
    try {
      spec = JSON.parse(data);
    } catch (err) {
      return { spec: null, error: (err as Error).message };
    }
  }
  if (!spec || typeof spec !== "object") {
    return { spec: null, error: "Spec is empty." };
  }
  // Block remote data URLs (privacy: don't let LLM-emitted specs phone home).
  const specObj = spec as { data?: { url?: string } };
  const url = specObj.data?.url;
  if (typeof url === "string" && /^https?:/i.test(url)) {
    return {
      spec: null,
      error: "Remote data URLs are blocked; inline the data instead.",
    };
  }
  return { spec: spec as object };
}

export function ChartArtifact({ part }: ArtifactRendererProps) {
  const { spec, error } = useMemo(() => parseSpec(part.data), [part.data]);

  if (part.streaming) {
    return (
      <div className="flex items-center gap-2 text-xs text-muted">
        <Loader2 strokeWidth={1.6} className="h-3 w-3 animate-spin" />
        Receiving chart spec…
      </div>
    );
  }
  if (error || !spec) {
    return (
      <div className="flex items-start gap-2 text-xs text-amber">
        <AlertCircle strokeWidth={1.6} className="mt-0.5 h-3.5 w-3.5 shrink-0" />
        <span>Couldn&apos;t render chart: {error ?? "invalid spec"}</span>
      </div>
    );
  }
  const responsiveSpec = {
    width: "container",
    background: "transparent",
    config: {
      axis: { labelColor: "#E0E7EE", titleColor: "#E0E7EE" },
      legend: { labelColor: "#E0E7EE", titleColor: "#E0E7EE" },
      title: { color: "#E0E7EE" },
      view: { stroke: "#2A3A4C" },
    },
    ...(spec as Record<string, unknown>),
  };
  return (
    <Suspense
      fallback={
        <div className="flex items-center gap-2 text-xs text-muted">
          <Loader2 strokeWidth={1.6} className="h-3 w-3 animate-spin" />
          Loading chart engine…
        </div>
      }
    >
      <div className="w-full">
        <VegaLite
          spec={responsiveSpec as never}
          actions={{ export: true, source: false, compiled: false, editor: false }}
        />
      </div>
    </Suspense>
  );
}

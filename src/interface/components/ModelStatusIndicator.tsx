/**
 * Compact local-model status indicator (spinner / coloured dot + label).
 *
 * Used in the Sidebar footer (persistent) and the Chat header so the user
 * can tell at a glance whether the model is loading, ready, or unavailable.
 * While a model is downloading it shows the live percent and a thin
 * progress bar (important for large models like the 70B default).
 *
 * sensitivity_tier: 1 (infrastructure — model name and status only)
 */

import { Loader2 } from "lucide-react";
import { useModelStatus, type ModelState } from "../hooks/useModelStatus";

const META: Record<ModelState, { readonly text: string; readonly dot: string }> = {
  loading: { text: "Loading model…", dot: "bg-faint" },
  ready: { text: "Model ready", dot: "bg-success" },
  missing: { text: "Model not installed", dot: "bg-amber" },
  offline: { text: "Model offline", dot: "bg-faint" },
  unknown: { text: "Checking model…", dot: "bg-faint" },
};

export function ModelStatusIndicator({
  collapsed = false,
}: {
  readonly collapsed?: boolean;
}) {
  const { state, model, percent } = useModelStatus();
  const meta = META[state];

  const downloading = state === "loading" && percent !== null;
  const label = downloading
    ? `Downloading model… ${Math.round(percent)}%`
    : state === "ready" && model
      ? `${model} ready`
      : meta.text;

  const icon =
    state === "loading" ? (
      <Loader2
        className="h-3.5 w-3.5 shrink-0 animate-spin text-indigo"
        strokeWidth={1.6}
      />
    ) : (
      <span className={`h-2 w-2 shrink-0 rounded-full ${meta.dot}`} />
    );

  // Collapsed sidebar: icon only.
  if (collapsed) {
    return (
      <div className="flex items-center gap-1.5" title={label}>
        {icon}
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-1" title={label}>
      <div className="flex items-center gap-1.5">
        {icon}
        <span className="truncate text-[11px] text-muted">{label}</span>
      </div>
      {downloading && (
        <div className="h-1 w-full overflow-hidden rounded-full bg-hairline">
          <div
            className="h-full rounded-full bg-indigo transition-all duration-500"
            style={{ width: `${Math.max(2, Math.round(percent))}%` }}
          />
        </div>
      )}
    </div>
  );
}

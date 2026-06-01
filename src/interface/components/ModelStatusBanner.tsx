/**
 * Top-of-app error banner shown when the local model is unreachable.
 *
 * Distinguishes two failure modes the user needs to act on differently:
 *  - `offline`        — the status probe ran and reported Ollama down, so
 *                       the fix is "start your Ollama server".
 *  - `backend-error`  — the status probe itself couldn't run (CLI crash /
 *                       broken Python env), so "offline" would be a lie;
 *                       we surface the raw detail and point at setup.
 *
 * Non-blocking and dismissable: the rest of the app stays usable. Dismissal
 * is per-episode — once the model recovers, a later failure shows again.
 * Rendered by Layout above the Outlet so it appears on every route.
 *
 * sensitivity_tier: 1 (infrastructure — model status only)
 */

import { useState, useEffect } from "react";
import { AlertTriangle, RefreshCw } from "lucide-react";
import { useModelStatus } from "../hooks/useModelStatus";

export function ModelStatusBanner() {
  const { state, detail, refresh } = useModelStatus();
  const [dismissed, setDismissed] = useState(false);

  const isError = state === "offline" || state === "backend-error";

  // Reset the dismissal once the model is healthy again, so a *new* failure
  // episode re-surfaces the banner instead of staying hidden forever.
  useEffect(() => {
    if (!isError) setDismissed(false);
  }, [isError]);

  if (!isError || dismissed) return null;

  const isBackendError = state === "backend-error";
  const title = isBackendError
    ? "Local model unavailable"
    : "Local model offline";
  const hint = isBackendError
    ? "The status check couldn't run — this is usually a setup or environment problem rather than the server being down."
    : "Start your local Ollama server to resume chatting and running agents.";

  return (
    <div className="border-b border-danger/30 bg-danger-soft px-10 py-3">
      <div className="flex items-start gap-3">
        <AlertTriangle
          strokeWidth={1.6}
          className="mt-0.5 h-4 w-4 shrink-0 text-danger"
        />
        <div className="flex flex-1 flex-col gap-1">
          <p className="text-[13px] font-semibold text-ink">{title}</p>
          <p className="text-[12px] text-ink-2">{hint}</p>
          {detail && (
            <p className="mt-0.5 font-mono text-[11px] text-ink-2/80">
              {detail}
            </p>
          )}
        </div>
        <div className="flex shrink-0 items-center gap-2">
          <button
            onClick={refresh}
            className="flex items-center gap-1.5 rounded-pill bg-danger px-3 py-1.5 text-[11px] font-medium text-white transition-colors hover:bg-danger/90"
          >
            <RefreshCw strokeWidth={1.8} className="h-3 w-3" />
            Retry
          </button>
          <button
            onClick={() => setDismissed(true)}
            className="rounded-pill border border-hairline px-3 py-1.5 text-[11px] font-medium text-ink transition-colors hover:bg-surface"
          >
            Dismiss
          </button>
        </div>
      </div>
    </div>
  );
}

export default ModelStatusBanner;

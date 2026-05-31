/**
 * Research-extended banner.
 *
 * Renders inside `StreamingBubble` when the reflective runner promotes
 * a chat run to `interactive_deep` (or starts in `background_deep`).
 * Shows a one-line reason from self-review and a Stop button that
 * asks the orchestrator to wrap up with the context it already has.
 *
 * Non-blocking by design: the stream keeps running underneath. Clicking
 * Stop fires `requestStop()` from `useStreamingChat`; the user sees the
 * `userStopRequested` flag flip immediately while the Python side
 * picks up the cancel flag at its next reflection checkpoint.
 *
 * sensitivity_tier: 1 (only carries a short user-facing reason string)
 */

import { Loader2, StopCircle } from "lucide-react";

interface ResearchExtendedBannerProps {
  readonly reason: string;
  readonly userStopRequested: boolean;
  readonly onStop: () => void;
}

export function ResearchExtendedBanner({
  reason,
  userStopRequested,
  onStop,
}: ResearchExtendedBannerProps) {
  return (
    <div className="mt-2 flex items-center justify-between gap-3 rounded border border-amber/40 bg-amber-soft px-3 py-2 text-xs text-ink">
      <div className="flex min-w-0 items-center gap-2">
        <Loader2
          strokeWidth={1.6}
          className="h-4 w-4 shrink-0 animate-spin text-amber"
        />
        <div className="min-w-0">
          <p className="font-medium">Researching deeper…</p>
          {reason ? (
            <p className="mt-0.5 truncate text-muted">{reason}</p>
          ) : null}
        </div>
      </div>
      <button
        type="button"
        onClick={onStop}
        disabled={userStopRequested}
        className="flex shrink-0 items-center gap-1 rounded border border-amber/40 px-2 py-1 text-xs font-medium text-ink hover:bg-amber/10 disabled:cursor-not-allowed disabled:opacity-60"
      >
        <StopCircle strokeWidth={1.6} className="h-3.5 w-3.5" />
        {userStopRequested ? "Wrapping up…" : "Stop research"}
      </button>
    </div>
  );
}

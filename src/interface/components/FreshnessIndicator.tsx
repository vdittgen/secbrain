/**
 * Reusable freshness indicator: colored dot + relative time label.
 *
 * Shows the data freshness state visually, re-rendering every 30s
 * so the relative time label stays up to date.
 *
 * Color coding:
 * - Green dot: fresh (no pending changes)
 * - Yellow dot + "N new": has pending changes but not stale
 * - Orange dot + "Stale — last updated Xh ago": stale with pending changes
 * - Gray dot + "Never": pipeline has never run
 * - Blue pulsing dot: currently running
 *
 * sensitivity_tier: N/A (UI infrastructure)
 */

import { useReducer, useEffect } from "react";
import { formatRelativeTime } from "../utils/timeFormat";

const REFRESH_MS = 30_000;

interface FreshnessIndicatorProps {
  readonly timestamp: string | null;
  readonly isStale: boolean;
  readonly pendingChanges?: number;
  readonly isRunning?: boolean;
  readonly className?: string;
}

function FreshnessIndicator({
  timestamp,
  isStale,
  pendingChanges = 0,
  isRunning = false,
  className = "",
}: FreshnessIndicatorProps) {
  // Force re-render every 30s so relative time label stays fresh
  const [, forceUpdate] = useReducer((x: number) => x + 1, 0);

  useEffect(() => {
    const interval = setInterval(forceUpdate, REFRESH_MS);
    return () => clearInterval(interval);
  }, []);

  let dotColor: string;
  let label: string;

  if (isRunning) {
    dotColor = "bg-indigo animate-pulse";
    label = "Updating...";
  } else if (isStale && pendingChanges > 0 && timestamp) {
    // Orange: stale with pending changes
    dotColor = "bg-orange-400 animate-pulse";
    label = `Stale \u2014 last updated ${formatRelativeTime(timestamp)}`;
  } else if (isStale && !timestamp) {
    // Gray: never run
    dotColor = "bg-muted";
    label = "Never";
  } else if (isStale && timestamp) {
    // Orange: stale without pending count
    dotColor = "bg-orange-400";
    label = `Stale \u2014 ${formatRelativeTime(timestamp)}`;
  } else if (pendingChanges > 0 && timestamp) {
    // Yellow: has pending changes but not stale yet
    dotColor = "bg-amber";
    label = `${pendingChanges} new`;
  } else if (timestamp) {
    // Green: fresh, no pending
    dotColor = "bg-success";
    label = `Updated ${formatRelativeTime(timestamp)}`;
  } else {
    dotColor = "bg-muted";
    label = "Never";
  }

  return (
    <span
      className={`inline-flex items-center gap-1.5 text-[11px] ${className}`}
    >
      <span className={`h-1.5 w-1.5 rounded-full ${dotColor}`} />
      <span className="text-muted">{label}</span>
    </span>
  );
}

export default FreshnessIndicator;

/**
 * Shared time formatting utilities.
 *
 * sensitivity_tier: N/A (UI infrastructure)
 */

/**
 * Format a timestamp string as a human-readable relative time.
 *
 * @param ts - ISO 8601 timestamp string.
 * @returns Relative time string like "just now", "3m ago", "2h ago", "1d ago".
 */
/**
 * Format an ISO timestamp as elapsed time from now.
 *
 * @param ts - ISO 8601 timestamp string (start time).
 * @returns Elapsed string like "12s", "2m 30s", "1h 5m".
 */
export function formatElapsedTime(ts: string): string {
  try {
    const elapsed = Math.max(0, Math.floor((Date.now() - new Date(ts).getTime()) / 1000));
    if (elapsed < 60) return `${elapsed}s`;
    const mins = Math.floor(elapsed / 60);
    const secs = elapsed % 60;
    if (mins < 60) return secs > 0 ? `${mins}m ${secs}s` : `${mins}m`;
    const hours = Math.floor(mins / 60);
    const remMins = mins % 60;
    return remMins > 0 ? `${hours}h ${remMins}m` : `${hours}h`;
  } catch {
    return "";
  }
}

export function formatRelativeTime(ts: string): string {
  try {
    const diff = Date.now() - new Date(ts).getTime();
    const mins = Math.floor(diff / 60_000);
    if (mins < 1) return "just now";
    if (mins < 60) return `${mins}m ago`;
    const hours = Math.floor(mins / 60);
    if (hours < 24) return `${hours}h ago`;
    return `${Math.floor(hours / 24)}d ago`;
  } catch {
    return "";
  }
}

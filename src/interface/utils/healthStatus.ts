/**
 * Shared status vocabulary for the unified system-health surface.
 *
 * One place defines what each status means visually (dot colour + text
 * colour + label) so every indicator speaks the same language instead
 * of each component inventing its own green/amber/red wording.
 *
 * sensitivity_tier: N/A (UI infrastructure)
 */

export type StageStatus = "ok" | "working" | "warning" | "error" | "idle";
export type Overall = "healthy" | "degraded" | "failing";

interface StatusToken {
  readonly dot: string;
  readonly text: string;
  readonly label: string;
}

export const STAGE_TOKENS: Record<StageStatus, StatusToken> = {
  ok: { dot: "bg-success", text: "text-success", label: "OK" },
  working: { dot: "bg-indigo animate-pulse", text: "text-indigo", label: "Working" },
  warning: { dot: "bg-amber", text: "text-amber", label: "Warning" },
  error: { dot: "bg-danger", text: "text-danger", label: "Error" },
  idle: { dot: "bg-muted", text: "text-muted", label: "Idle" },
};

interface OverallToken {
  readonly dot: string;
  readonly text: string;
  readonly pill: string;
  readonly label: string;
}

export const OVERALL_TOKENS: Record<Overall, OverallToken> = {
  healthy: {
    dot: "bg-success",
    text: "text-success",
    pill: "bg-success-soft hover:bg-success/15",
    label: "Healthy",
  },
  degraded: {
    dot: "bg-amber",
    text: "text-amber",
    pill: "bg-amber-soft hover:bg-amber/15",
    label: "Degraded",
  },
  failing: {
    dot: "bg-danger",
    text: "text-danger",
    pill: "bg-danger/10 hover:bg-danger/15",
    label: "Issues",
  },
};

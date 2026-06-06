/**
 * Unified health dropdown — the single place that answers
 * "is everything working, and if not, what's broken and how do I fix it?"
 *
 * Renders the data-flow stage strip (Connectors -> Ingest -> Transform ->
 * Graph -> Vectors) and the actionable issue list. Opened from the TopBar
 * SystemHealthIndicator. Mirrors the NotificationsPanel dropdown pattern.
 *
 * sensitivity_tier: 1 (infrastructure status only)
 */

import { RefreshCw, AlertTriangle, XCircle, ChevronRight } from "lucide-react";
import type { SystemHealthHook, HealthAction } from "../hooks/useSystemHealth";
import { STAGE_TOKENS } from "../utils/healthStatus";

function HealthPanel({
  health,
  onClose,
  onRefresh,
  onAction,
}: {
  readonly health: SystemHealthHook;
  readonly onClose: () => void;
  readonly onRefresh: () => void;
  readonly onAction: (action: HealthAction) => void;
}) {
  const { overall, stages, issues } = health;

  return (
    <div className="absolute right-0 top-full z-50 mt-2 w-[360px] overflow-hidden rounded-2 border border-hairline bg-surface shadow-lg">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-hairline px-4 py-3">
        <span className="text-[13px] font-semibold text-ink">
          {overall === "failing"
            ? "Needs attention"
            : overall === "degraded"
              ? "Running — minor issues"
              : "All systems healthy"}
        </span>
        <button
          type="button"
          onClick={onRefresh}
          className="inline-flex items-center gap-1.5 rounded-2 bg-bg-2 px-2.5 py-1 text-[11px] font-medium text-ink-2 transition-colors hover:bg-hairline"
        >
          <RefreshCw className="h-3 w-3" strokeWidth={1.6} />
          Refresh now
        </button>
      </div>

      {/* Pipeline stage strip */}
      <div className="flex items-stretch gap-1 overflow-x-auto px-3 py-3">
        {stages.map((stage, i) => {
          const token = STAGE_TOKENS[stage.status];
          return (
            <div key={stage.id} className="flex items-center gap-1">
              <button
                type="button"
                onClick={() => {
                  onAction({
                    label: "",
                    kind: "open_route",
                    target: stage.route,
                  });
                  onClose();
                }}
                className="flex min-w-[64px] flex-col items-center gap-1 rounded-2 px-2 py-1.5 transition-colors hover:bg-bg-2"
                title={stage.summary}
              >
                <span className={`h-2 w-2 rounded-full ${token.dot}`} />
                <span className="text-[11px] font-medium text-ink">
                  {stage.label}
                </span>
                <span className="max-w-[72px] truncate text-[10px] text-muted">
                  {stage.summary}
                </span>
              </button>
              {i < stages.length - 1 && (
                <ChevronRight
                  className="h-3 w-3 shrink-0 text-faint"
                  strokeWidth={1.6}
                />
              )}
            </div>
          );
        })}
      </div>

      {/* Issues */}
      <div className="max-h-[320px] overflow-y-auto border-t border-hairline">
        {issues.length === 0 ? (
          <p className="px-4 py-6 text-center text-xs text-muted">
            No issues detected.
          </p>
        ) : (
          issues.map((issue) => {
            const Icon = issue.severity === "error" ? XCircle : AlertTriangle;
            const color =
              issue.severity === "error" ? "text-danger" : "text-amber";
            return (
              <div
                key={issue.id}
                className="flex items-start gap-2 border-b border-hairline px-4 py-3 last:border-b-0"
              >
                <Icon
                  className={`mt-0.5 h-4 w-4 shrink-0 ${color}`}
                  strokeWidth={1.6}
                />
                <div className="min-w-0 flex-1">
                  <p className="text-[12.5px] font-medium text-ink">
                    {issue.title}
                  </p>
                  <p className="mt-0.5 text-[11px] leading-snug text-muted">
                    {issue.detail}
                  </p>
                </div>
                {issue.action && (
                  <button
                    type="button"
                    onClick={() => issue.action && onAction(issue.action)}
                    className="shrink-0 rounded-2 bg-bg-2 px-2.5 py-1 text-[11px] font-medium text-ink-2 transition-colors hover:bg-hairline"
                  >
                    {issue.action.label}
                  </button>
                )}
              </div>
            );
          })
        )}
      </div>
    </div>
  );
}

export default HealthPanel;

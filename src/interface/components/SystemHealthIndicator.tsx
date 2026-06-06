/**
 * Single TopBar health indicator — replaces the old pipeline pill.
 *
 * Shows one colour-coded verdict (Healthy / Degraded / N issues) and a
 * "Syncing…" state while a run is active. Click opens the HealthPanel
 * with the pipeline stage strip + actionable issues. This is the one
 * glanceable status; everything else defers to its panel.
 *
 * sensitivity_tier: 1 (infrastructure status only)
 */

import { useState, useContext, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import { invoke } from "@tauri-apps/api/core";
import { RefreshCw } from "lucide-react";
import { useSystemHealth, type HealthAction } from "../hooks/useSystemHealth";
import { usePipelineStatus } from "../hooks/usePipelineStatus";
import { OVERALL_TOKENS } from "../utils/healthStatus";
import { PipelineRefreshContext } from "./Layout";
import HealthPanel from "./HealthPanel";

function SystemHealthIndicator() {
  const health = useSystemHealth();
  const { runState } = usePipelineStatus();
  const { openRefreshModal } = useContext(PipelineRefreshContext);
  const navigate = useNavigate();
  const [open, setOpen] = useState(false);

  const handleAction = useCallback(
    (action: HealthAction) => {
      switch (action.kind) {
        case "open_route":
          if (action.target) navigate(action.target);
          break;
        case "run_pipeline":
        case "run_migrate":
          openRefreshModal();
          break;
        case "retry_connector":
          if (action.target) {
            void invoke("sync_connector_now", { connectorId: action.target })
              .catch(() => {})
              .then(() => health.refetch());
          }
          break;
      }
    },
    [navigate, openRefreshModal, health],
  );

  // Active run takes visual priority over the steady-state verdict.
  if (runState === "running") {
    return (
      <button
        type="button"
        onClick={openRefreshModal}
        className="inline-flex items-center gap-1.5 rounded-pill bg-indigo-soft px-3 py-1.5 text-[12.5px] font-medium text-indigo transition-colors hover:bg-indigo/15"
        title="Show refresh progress"
      >
        <RefreshCw className="h-3 w-3 animate-spin" strokeWidth={1.6} />
        Syncing…
      </button>
    );
  }

  const overall = health.overall;
  if (!overall) return null; // neutral while first fetch is in flight

  const token = OVERALL_TOKENS[overall];
  const issueCount = health.errorCount + health.warnCount;
  const label =
    overall === "healthy"
      ? token.label
      : `${issueCount} issue${issueCount === 1 ? "" : "s"}`;

  return (
    <div className="relative">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className={`inline-flex items-center gap-1.5 rounded-pill px-3 py-1.5 text-[12.5px] font-medium transition-colors ${token.pill} ${token.text}`}
        title="System health"
        aria-expanded={open}
      >
        <span className={`h-1.5 w-1.5 rounded-full ${token.dot}`} />
        {label}
      </button>
      {open && (
        <>
          <div
            className="fixed inset-0 z-40"
            onClick={() => setOpen(false)}
            aria-hidden="true"
          />
          <HealthPanel
            health={health}
            onClose={() => setOpen(false)}
            onRefresh={() => {
              openRefreshModal();
              setOpen(false);
            }}
            onAction={handleAction}
          />
        </>
      )}
    </div>
  );
}

export default SystemHealthIndicator;

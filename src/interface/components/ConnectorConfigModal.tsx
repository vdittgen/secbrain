/**
 * Connector Config Modal — read-only configuration viewer for v1.
 *
 * Shows field mappings, sync schedule, sensitivity breakdown, and raw details.
 * Config editing (schedule changes, sensitivity overrides) requires backend
 * support that doesn't exist yet — those sections are marked as view-only.
 *
 * sensitivity_tier: 1 (connector config is infrastructure metadata)
 */

import { useState, useEffect } from "react";
import { invoke } from "@tauri-apps/api/core";
import {
  X,
  Clock,
  Shield,
  Database,
  Terminal,
  Code2,
} from "lucide-react";
import { Skeleton } from "../components/LoadingState";

// ---------------------------------------------------------------------------
// Types (match Rust DTOs)
// ---------------------------------------------------------------------------

interface ConnectorToolDetail {
  readonly tool_name: string;
  readonly tool_type: string;
  readonly target_table: string | null;
  readonly field_count: number;
  readonly dedup_key: readonly string[];
  readonly fields?: readonly {
    readonly source: string;
    readonly target: string;
    readonly type: string;
    readonly tier: number;
    readonly transform: string | null;
  }[];
}

interface ConnectorSyncStats {
  readonly records_synced: number;
  readonly last_sync: string | null;
  readonly next_sync: string | null;
}

interface ConnectorDetailData {
  readonly connector_id: string;
  readonly name: string;
  readonly tools: readonly ConnectorToolDetail[];
  readonly stats: ConnectorSyncStats & { readonly error: string | null };
  readonly schedule: {
    readonly interval_seconds: number;
    readonly next_sync: string | null;
  } | null;
  readonly default_schedule: string;
  readonly [key: string]: unknown;
}

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

interface ConnectorConfigModalProps {
  readonly connectorId: string;
  readonly open: boolean;
  readonly onClose: () => void;
  readonly onSaved: () => void;
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const SCHEDULE_LABELS: Record<string, string> = {
  every_15min: "Every 15 minutes",
  hourly: "Every hour",
  daily: "Once a day",
  manual: "Manual only",
};

type ConfigTab = "mapping" | "schedule" | "sensitivity" | "advanced";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function tierDotColor(tier: number): string {
  switch (tier) {
    case 1: return "bg-success";
    case 2: return "bg-amber";
    case 3: return "bg-danger";
    default: return "bg-gray-500";
  }
}

function tierLabel(tier: number): string {
  switch (tier) {
    case 1: return "Public";
    case 2: return "Personal";
    case 3: return "Sensitive";
    default: return `Tier ${tier}`;
  }
}

function formatJson(data: unknown): string {
  try {
    return JSON.stringify(data, null, 2);
  } catch {
    return String(data);
  }
}

// ---------------------------------------------------------------------------
// ConnectorConfigModal
// ---------------------------------------------------------------------------

function ConnectorConfigModal({ connectorId, open, onClose }: ConnectorConfigModalProps) {
  const [activeTab, setActiveTab] = useState<ConfigTab>("mapping");
  const [details, setDetails] = useState<ConnectorDetailData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    setLoading(true);
    setError(null);
    invoke<ConnectorDetailData>("get_connector_details", { connectorId })
      .then((data) => { if (!cancelled) { setDetails(data); setLoading(false); } })
      .catch((err) => {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : String(err));
          setLoading(false);
        }
      });
    return () => { cancelled = true; };
  }, [connectorId, open]);

  if (!open) return null;

  const tabs: readonly { readonly id: ConfigTab; readonly label: string }[] = [
    { id: "mapping", label: "Field Mapping" },
    { id: "schedule", label: "Schedule" },
    { id: "sensitivity", label: "Sensitivity" },
    { id: "advanced", label: "Advanced" },
  ];

  // Gather all fields for sensitivity tab
  const allFields = details?.tools.flatMap((t) => t.fields ?? []) ?? [];
  const tierCounts = allFields.reduce<Record<number, number>>((acc, f) => {
    acc[f.tier] = (acc[f.tier] ?? 0) + 1;
    return acc;
  }, {});

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60">
      <div className="relative w-full max-w-2xl rounded-4 border border-hairline bg-bg-2 shadow-2xl">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-hairline px-5 py-4">
          <div>
            <h3 className="text-sm font-semibold text-ink">
              {details?.name ?? connectorId} Configuration
            </h3>
            <p className="mt-0.5 text-[11px] text-muted">
              View connector settings and field mappings
            </p>
          </div>
          <button
            onClick={onClose}
            className="rounded-2 p-1.5 text-muted transition-colors hover:bg-surface hover:text-ink"
          >
            <X strokeWidth={1.6} className="h-4 w-4" />
          </button>
        </div>

        {/* Tab bar */}
        <div className="flex gap-1 border-b border-hairline px-5">
          {tabs.map((tab) => (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              className={`border-b-2 px-3 py-2 text-xs font-medium transition-colors ${
                activeTab === tab.id
                  ? "border-indigo text-indigo"
                  : "border-transparent text-muted hover:text-ink"
              }`}
            >
              {tab.label}
            </button>
          ))}
        </div>

        {/* Content */}
        <div className="max-h-[60vh] overflow-y-auto px-5 py-4">
          {loading ? (
            <div className="space-y-3">
              <Skeleton className="h-4 w-48" />
              <Skeleton className="h-4 w-32" />
              <Skeleton className="h-32 w-full" />
            </div>
          ) : error ? (
            <div className="rounded-2 border border-amber-soft bg-amber/5 px-4 py-3 text-xs text-amber">
              {error}
            </div>
          ) : !details ? (
            <p className="py-8 text-center text-sm text-muted">No details available.</p>
          ) : (
            <>
              {/* Field Mapping tab */}
              {activeTab === "mapping" && (
                <div className="space-y-4">
                  {details.tools.length === 0 ? (
                    <p className="py-4 text-center text-xs text-muted">No tools or field mappings.</p>
                  ) : (
                    details.tools.map((tool) => (
                      <div key={tool.tool_name} className="space-y-2">
                        <div className="flex items-center gap-2">
                          <Terminal strokeWidth={1.6} className="h-3.5 w-3.5 text-muted" />
                          <span className="font-mono text-xs font-medium text-ink">{tool.tool_name}</span>
                          <span
                            className={`rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase ${
                              tool.tool_type === "data"
                                ? "bg-indigo-soft text-indigo"
                                : "bg-amber/15 text-amber"
                            }`}
                          >
                            {tool.tool_type}
                          </span>
                          {tool.target_table && (
                            <span className="flex items-center gap-1 text-[11px] text-muted">
                              <Database strokeWidth={1.6} className="h-3 w-3" />
                              {tool.target_table}
                            </span>
                          )}
                        </div>
                        {tool.fields && tool.fields.length > 0 ? (
                          <div className="overflow-x-auto rounded-2 border border-hairline">
                            <table className="w-full text-left text-xs">
                              <thead>
                                <tr className="border-b border-hairline bg-surface text-[11px] uppercase tracking-wider text-muted">
                                  <th className="px-3 py-2">Source</th>
                                  <th className="px-3 py-2">Target</th>
                                  <th className="px-3 py-2">Type</th>
                                  <th className="px-3 py-2">Tier</th>
                                  <th className="px-3 py-2">Transform</th>
                                </tr>
                              </thead>
                              <tbody>
                                {tool.fields.map((f) => (
                                  <tr key={f.source} className="border-b border-hairline/30">
                                    <td className="px-3 py-2 font-mono text-muted">{f.source}</td>
                                    <td className="px-3 py-2 font-mono text-ink">{f.target}</td>
                                    <td className="px-3 py-2 text-muted">{f.type}</td>
                                    <td className="px-3 py-2">
                                      <span className="flex items-center gap-1">
                                        <span className={`h-2 w-2 rounded-full ${tierDotColor(f.tier)}`} />
                                        {tierLabel(f.tier)}
                                      </span>
                                    </td>
                                    <td className="px-3 py-2 text-muted">{f.transform ?? "—"}</td>
                                  </tr>
                                ))}
                              </tbody>
                            </table>
                          </div>
                        ) : (
                          <p className="pl-5 text-[11px] text-muted">{tool.field_count} fields (details not available)</p>
                        )}
                      </div>
                    ))
                  )}
                </div>
              )}

              {/* Schedule tab */}
              {activeTab === "schedule" && (
                <div className="space-y-4">
                  <div className="rounded-2 border border-hairline bg-surface/60 p-4">
                    <div className="flex items-center gap-2">
                      <Clock strokeWidth={1.6} className="h-4 w-4 text-muted" />
                      <span className="text-sm font-medium text-ink">Sync Schedule</span>
                    </div>
                    <div className="mt-3 space-y-2">
                      <div className="flex justify-between text-xs">
                        <span className="text-muted">Interval</span>
                        <span className="text-ink">
                          {SCHEDULE_LABELS[details.default_schedule] ?? details.default_schedule}
                        </span>
                      </div>
                      {details.schedule && (
                        <>
                          <div className="flex justify-between text-xs">
                            <span className="text-muted">Interval (seconds)</span>
                            <span className="text-ink">{details.schedule.interval_seconds}s</span>
                          </div>
                          {details.schedule.next_sync && (
                            <div className="flex justify-between text-xs">
                              <span className="text-muted">Next sync</span>
                              <span className="text-ink">{details.schedule.next_sync}</span>
                            </div>
                          )}
                        </>
                      )}
                      <div className="flex justify-between text-xs">
                        <span className="text-muted">Records synced</span>
                        <span className="text-ink">{details.stats.records_synced.toLocaleString()}</span>
                      </div>
                      {details.stats.last_sync && (
                        <div className="flex justify-between text-xs">
                          <span className="text-muted">Last sync</span>
                          <span className="text-ink">{details.stats.last_sync}</span>
                        </div>
                      )}
                      {details.stats.error && (
                        <div className="flex justify-between text-xs">
                          <span className="text-muted">Error</span>
                          <span className="text-amber">{details.stats.error}</span>
                        </div>
                      )}
                    </div>
                  </div>
                  <p className="text-[11px] text-muted">
                    Schedule editing is not yet available. The sync interval is set by the connector template.
                  </p>
                </div>
              )}

              {/* Sensitivity tab */}
              {activeTab === "sensitivity" && (
                <div className="space-y-4">
                  <div className="rounded-2 border border-hairline bg-surface/60 p-4">
                    <div className="flex items-center gap-2">
                      <Shield strokeWidth={1.6} className="h-4 w-4 text-muted" />
                      <span className="text-sm font-medium text-ink">Sensitivity Breakdown</span>
                    </div>
                    <div className="mt-3 space-y-2">
                      {[1, 2, 3].map((tier) => {
                        const count = tierCounts[tier] ?? 0;
                        if (count === 0) return null;
                        return (
                          <div key={tier} className="flex items-center justify-between text-xs">
                            <span className="flex items-center gap-2">
                              <span className={`h-2 w-2 rounded-full ${tierDotColor(tier)}`} />
                              <span className="text-ink">{tierLabel(tier)}</span>
                            </span>
                            <span className="text-muted">{count} field{count > 1 ? "s" : ""}</span>
                          </div>
                        );
                      })}
                      {allFields.length === 0 && (
                        <p className="text-xs text-muted">No field sensitivity data available.</p>
                      )}
                    </div>
                  </div>
                  <p className="text-[11px] text-muted">
                    Sensitivity tier overrides are not yet available. Tiers are auto-detected during schema discovery.
                  </p>
                </div>
              )}

              {/* Advanced tab */}
              {activeTab === "advanced" && (
                <div className="space-y-3">
                  <div className="flex items-center gap-2">
                    <Code2 strokeWidth={1.6} className="h-4 w-4 text-muted" />
                    <span className="text-sm font-medium text-ink">Raw Configuration</span>
                  </div>
                  <div className="max-h-80 overflow-y-auto rounded-2 bg-surface p-3">
                    <pre className="whitespace-pre-wrap font-mono text-[11px] leading-relaxed text-muted">
                      {formatJson(details)}
                    </pre>
                  </div>
                  <p className="text-[11px] text-muted">
                    This is the raw connector configuration. Direct editing is not yet supported.
                  </p>
                </div>
              )}
            </>
          )}
        </div>

        {/* Footer */}
        <div className="flex justify-end border-t border-hairline px-5 py-3">
          <button
            onClick={onClose}
            className="rounded-2 bg-surface px-4 py-2 text-xs font-medium text-ink transition-colors hover:bg-hairline"
          >
            Close
          </button>
        </div>
      </div>
    </div>
  );
}

export default ConnectorConfigModal;

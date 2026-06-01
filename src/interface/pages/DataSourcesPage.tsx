/**
 * Data Sources page — primary UI for connecting and managing data sources.
 *
 * Users toggle connectors on/off, configure requirements (OAuth, env vars,
 * permissions), view sync stats, and trigger manual syncs.
 *
 * sensitivity_tier: 1 (connector catalog is infrastructure metadata)
 */

import { useState, useCallback, useMemo, useEffect } from "react";
import { Link } from "react-router-dom";
import { invoke } from "@tauri-apps/api/core";
import {
  Search,
  RefreshCw,
  ChevronDown,
  ChevronRight,
  Lock,
  Key,
  FileText,
  Download,
  Plus,
  AlertTriangle,
  ExternalLink,
  Clock,
  Loader2,
} from "lucide-react";
import { Skeleton, SkeletonSection } from "../components/LoadingState";
import { useAsyncData } from "../hooks/useAsyncData";
import { dedupInvoke } from "../utils/requestDedup";
import { formatRelativeTime } from "../utils/timeFormat";

// ---------------------------------------------------------------------------
// Types (match Rust DTOs in src-tauri/src/commands/types.rs)
// ---------------------------------------------------------------------------

interface ConnectorSyncStats {
  readonly records_synced: number;
  readonly last_sync: string | null;
  readonly next_sync: string | null;
}

interface ConnectorMissingRequirement {
  readonly type: string;
  readonly key: string;
  readonly label: string;
  readonly action: string;
}

interface ConnectorCatalogEntry {
  readonly connector_id: string;
  readonly name: string;
  readonly icon: string;
  readonly description: string;
  readonly category: string;
  readonly enabled: boolean;
  readonly status: string;
  readonly stats: ConnectorSyncStats;
  readonly missing_requirements: readonly ConnectorMissingRequirement[];
  readonly tools_available: number;
  readonly default_schedule: string;
  readonly note: string | null;
}

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
// Constants
// ---------------------------------------------------------------------------

interface CategoryDef {
  readonly id: string;
  readonly label: string;
  readonly emoji: string;
}

const CATEGORIES: readonly CategoryDef[] = [
  { id: "apple", label: "Apple", emoji: "\uD83C\uDF4E" },
  { id: "files", label: "Files", emoji: "\uD83D\uDCC2" },
  { id: "email", label: "Email & Communication", emoji: "\uD83D\uDCE7" },
  { id: "notes", label: "Notes & Knowledge", emoji: "\uD83D\uDCDD" },
  { id: "lifestyle", label: "Lifestyle", emoji: "\uD83C\uDFB5" },
] as const;

const SCHEDULE_LABELS: Record<string, string> = {
  every_15min: "Every 15 minutes",
  hourly: "Every hour",
  daily: "Once a day",
  manual: "Manual only",
};

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function requirementIcon(type: string) {
  switch (type) {
    case "permission":
      return Lock;
    case "oauth":
      return Key;
    case "env":
      return FileText;
    case "app":
      return Download;
    default:
      return AlertTriangle;
  }
}

function requirementHint(
  reqs: readonly ConnectorMissingRequirement[],
): string {
  if (reqs.length === 0) return "";
  const first = reqs[0];
  switch (first.type) {
    case "permission":
      return `Requires ${first.key}`;
    case "oauth":
      return `Requires sign-in`;
    case "env":
      return `Requires configuration`;
    case "app":
      return `Requires ${first.key}`;
    default:
      return "Setup required";
  }
}

function groupByCategory(
  connectors: readonly ConnectorCatalogEntry[],
): Map<string, ConnectorCatalogEntry[]> {
  const map = new Map<string, ConnectorCatalogEntry[]>();
  for (const cat of CATEGORIES) {
    map.set(cat.id, []);
  }
  for (const c of connectors) {
    const list = map.get(c.category);
    if (list) {
      list.push(c);
    }
  }
  return map;
}

function tierBreakdown(
  tools: readonly ConnectorToolDetail[],
): { tier1: number; tier2: number; tier3: number } {
  let tier1 = 0;
  let tier2 = 0;
  let tier3 = 0;
  for (const tool of tools) {
    if (tool.fields) {
      for (const f of tool.fields) {
        if (f.tier === 1) tier1++;
        else if (f.tier === 2) tier2++;
        else if (f.tier === 3) tier3++;
      }
    }
  }
  return { tier1, tier2, tier3 };
}

// ---------------------------------------------------------------------------
// Toggle switch
// ---------------------------------------------------------------------------

function Toggle({
  enabled,
  onChange,
  disabled,
  pending,
}: {
  readonly enabled: boolean;
  readonly onChange: (v: boolean) => void;
  readonly disabled?: boolean;
  readonly pending?: boolean;
}) {
  return (
    <button
      onClick={(e) => {
        e.stopPropagation();
        if (!disabled && !pending) onChange(!enabled);
      }}
      disabled={disabled || pending}
      className={`relative h-6 w-10 shrink-0 rounded-full transition-colors ${
        pending
          ? "animate-pulse bg-indigo/50"
          : enabled
            ? "bg-indigo"
            : "bg-hairline"
      } ${disabled ? "cursor-not-allowed opacity-50" : "cursor-pointer"}`}
    >
      <span
        className={`absolute top-0.5 left-0.5 h-5 w-5 rounded-full bg-white transition-transform ${
          enabled || pending ? "translate-x-4" : ""
        }`}
      />
    </button>
  );
}

// ---------------------------------------------------------------------------
// Requirement card (shown when needs_setup)
// ---------------------------------------------------------------------------

function RequirementCard({
  requirements,
  onRetry,
}: {
  readonly requirements: readonly ConnectorMissingRequirement[];
  readonly onRetry: (userInputs: Record<string, string>) => void;
}) {
  const [envValues, setEnvValues] = useState<Record<string, string>>({});

  if (requirements.length === 0) return null;

  const hasEnvReqs = requirements.some((r) => r.type === "env");
  const canRetry =
    !hasEnvReqs ||
    requirements
      .filter((r) => r.type === "env")
      .every((r) => (envValues[r.key] ?? "").trim() !== "");

  return (
    <div className="mt-2 space-y-3 rounded-2 border border-hairline bg-surface/60 px-4 py-3">
      {requirements.map((req) => {
        const Icon = requirementIcon(req.type);
        return (
          <div key={req.key} className="space-y-2">
            <div className="flex items-center gap-2 text-sm text-ink">
              <Icon className="h-4 w-4 shrink-0 text-muted" />
              <span>{req.label}</span>
            </div>

            {req.type === "permission" && (
              <p className="pl-6 text-xs text-muted">
                Open System Settings &gt; Privacy &amp; Security to grant
                access.
              </p>
            )}

            {req.type === "oauth" && (
              <button
                disabled
                className="ml-6 rounded-2 bg-indigo-soft px-3 py-1.5 text-xs font-medium text-indigo opacity-70"
              >
                Sign in with{" "}
                {req.key.replace("_oauth", "").replace("_", " ")}
              </button>
            )}

            {req.type === "env" && (
              <div className="flex items-center gap-2 pl-6">
                <input
                  type="text"
                  placeholder={req.label}
                  value={envValues[req.key] ?? ""}
                  onChange={(e) =>
                    setEnvValues((prev) => ({
                      ...prev,
                      [req.key]: e.target.value,
                    }))
                  }
                  className="flex-1 rounded-2 bg-bg px-3 py-1.5 text-xs text-ink placeholder-muted outline-none ring-1 ring-hairline focus:ring-indigo"
                />
              </div>
            )}

            {req.type === "app" && (
              <p className="pl-6 text-xs text-muted">
                {req.key} not found.{" "}
                <span className="text-indigo">Install it</span> and try
                again.
              </p>
            )}
          </div>
        );
      })}

      <div className="flex justify-end pt-1">
        <button
          onClick={() => onRetry(envValues)}
          disabled={!canRetry}
          className={`rounded-2 px-3 py-1.5 text-xs font-medium transition-colors ${
            canRetry
              ? "bg-indigo text-white hover:bg-indigo/90"
              : "cursor-not-allowed bg-hairline text-muted"
          }`}
        >
          Retry Connection
        </button>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Connector detail (expanded view for connected connectors)
// ---------------------------------------------------------------------------

function ConnectorDetail({
  details,
  detailsLoading,
  connector,
  onSyncNow,
  onDisconnect,
  syncPending,
}: {
  readonly details: ConnectorDetailData | null;
  readonly detailsLoading: boolean;
  readonly connector: ConnectorCatalogEntry;
  readonly onSyncNow: () => void;
  readonly onDisconnect: () => void;
  readonly syncPending: boolean;
}) {
  if (detailsLoading) {
    return (
      <div className="mt-2 space-y-2 rounded-2 border border-hairline bg-surface/60 px-4 py-3">
        <Skeleton className="h-4 w-48" />
        <Skeleton className="h-4 w-32" />
        <Skeleton className="h-8 w-full" />
      </div>
    );
  }

  if (!details) return null;

  const tiers = tierBreakdown(details.tools);
  const scheduleLabel =
    SCHEDULE_LABELS[connector.default_schedule] ??
    connector.default_schedule;

  return (
    <div className="mt-2 space-y-3 rounded-2 border border-hairline bg-surface/60 px-4 py-3">
      {/* Stats */}
      <div className="flex flex-wrap gap-4 text-xs text-muted">
        <span>
          {connector.stats.records_synced.toLocaleString()} records synced
        </span>
        {connector.stats.last_sync && (
          <span className="flex items-center gap-1">
            <Clock className="h-3 w-3" />
            Synced {formatRelativeTime(connector.stats.last_sync)}
          </span>
        )}
        {connector.stats.next_sync && (
          <span className="flex items-center gap-1">
            <Clock className="h-3 w-3" />
            Next in {formatRelativeTime(connector.stats.next_sync)}
          </span>
        )}
      </div>

      {/* Sensitivity breakdown */}
      {(tiers.tier1 > 0 || tiers.tier2 > 0 || tiers.tier3 > 0) && (
        <div className="space-y-1">
          <p className="text-[11px] font-medium text-muted">
            Data sensitivity
          </p>
          <div className="flex flex-wrap gap-3 text-xs">
            {tiers.tier1 > 0 && (
              <span className="flex items-center gap-1">
                <span className="h-2 w-2 rounded-full bg-success" />
                {tiers.tier1} public fields
              </span>
            )}
            {tiers.tier2 > 0 && (
              <span className="flex items-center gap-1">
                <span className="h-2 w-2 rounded-full bg-amber" />
                {tiers.tier2} personal fields
              </span>
            )}
            {tiers.tier3 > 0 && (
              <span className="flex items-center gap-1">
                <span className="h-2 w-2 rounded-full bg-danger" />
                {tiers.tier3} sensitive fields
              </span>
            )}
          </div>
        </div>
      )}

      {/* Schedule */}
      <div className="text-xs text-muted">
        Sync schedule: {scheduleLabel}
      </div>

      {/* Actions */}
      <div className="flex items-center gap-2 border-t border-hairline pt-3">
        <button
          onClick={(e) => {
            e.stopPropagation();
            onSyncNow();
          }}
          disabled={syncPending}
          className="flex items-center gap-1.5 rounded-2 bg-surface px-3 py-1.5 text-xs font-medium text-ink transition-colors hover:bg-hairline"
        >
          <RefreshCw
            className={`h-3 w-3 ${syncPending ? "animate-spin" : ""}`}
          />
          {syncPending ? "Syncing..." : "Sync Now"}
        </button>
        <Link
          to="/explorer"
          onClick={(e) => e.stopPropagation()}
          className="flex items-center gap-1.5 rounded-2 bg-surface px-3 py-1.5 text-xs font-medium text-ink transition-colors hover:bg-hairline"
        >
          <ExternalLink className="h-3 w-3" />
          View Data
        </Link>
        <button
          onClick={(e) => {
            e.stopPropagation();
            onDisconnect();
          }}
          className="flex items-center gap-1.5 rounded-2 px-3 py-1.5 text-xs font-medium text-amber transition-colors hover:bg-amber/10"
        >
          Disconnect
        </button>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Connector row
// ---------------------------------------------------------------------------

function ConnectorRow({
  connector,
  expanded,
  details,
  detailsLoading,
  onToggle,
  onToggleWithInputs,
  onExpand,
  onSyncNow,
  onDisconnect,
  togglePending,
  syncPending,
}: {
  readonly connector: ConnectorCatalogEntry;
  readonly expanded: boolean;
  readonly details: ConnectorDetailData | null;
  readonly detailsLoading: boolean;
  readonly onToggle: (enabled: boolean) => void;
  readonly onToggleWithInputs: (inputs: Record<string, string>) => void;
  readonly onExpand: () => void;
  readonly onSyncNow: () => void;
  readonly onDisconnect: () => void;
  readonly togglePending: boolean;
  readonly syncPending: boolean;
}) {
  const isConnected = connector.status === "connected";
  const needsSetup = connector.status === "needs_setup";
  const hasError = connector.status === "error";

  const hint =
    !connector.enabled && connector.missing_requirements.length > 0
      ? requirementHint(connector.missing_requirements)
      : null;

  const HintIcon =
    !connector.enabled && connector.missing_requirements.length > 0
      ? requirementIcon(connector.missing_requirements[0].type)
      : null;

  return (
    <div className="rounded-2 transition-colors">
      {/* Main row */}
      <div
        onClick={isConnected ? onExpand : undefined}
        className={`flex items-center justify-between rounded-2 px-4 py-3 transition-colors ${
          isConnected
            ? "cursor-pointer hover:bg-surface/50"
            : "cursor-default"
        } ${expanded ? "bg-surface/50" : ""}`}
      >
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <span className="text-base">{connector.icon}</span>
            <span className="text-sm font-medium text-ink">
              {connector.name}
            </span>
            {hasError && (
              <AlertTriangle className="h-3.5 w-3.5 text-amber" />
            )}
          </div>

          {/* Stats line (when connected) */}
          {isConnected && (
            <p className="mt-0.5 pl-7 text-[11px] text-muted">
              {connector.stats.records_synced > 0 &&
                `${connector.stats.records_synced.toLocaleString()} records`}
              {connector.stats.records_synced > 0 &&
                connector.stats.last_sync &&
                " \u00B7 "}
              {connector.stats.last_sync &&
                `synced ${formatRelativeTime(connector.stats.last_sync)}`}
            </p>
          )}

          {/* Requirement hint (when disabled with requirements) */}
          {hint && HintIcon && !needsSetup && (
            <p className="mt-0.5 flex items-center gap-1 pl-7 text-[11px] text-muted">
              <HintIcon className="h-3 w-3" />
              {hint}
            </p>
          )}

          {/* Note */}
          {connector.note && !isConnected && (
            <p className="mt-0.5 pl-7 text-[11px] text-muted">
              {connector.note}
            </p>
          )}

          {/* Error message */}
          {hasError && (
            <p className="mt-0.5 pl-7 text-[11px] text-amber">
              Connection error. Try toggling off and on.
            </p>
          )}
        </div>

        <Toggle
          enabled={connector.enabled}
          onChange={onToggle}
          pending={togglePending}
        />
      </div>

      {/* Requirement card (when needs_setup) */}
      {needsSetup && connector.missing_requirements.length > 0 && (
        <div className="px-4 pb-3">
          <RequirementCard
            requirements={connector.missing_requirements}
            onRetry={onToggleWithInputs}
          />
        </div>
      )}

      {/* Expanded detail */}
      {expanded && isConnected && (
        <div className="px-4 pb-3">
          <ConnectorDetail
            details={details}
            detailsLoading={detailsLoading}
            connector={connector}
            onSyncNow={onSyncNow}
            onDisconnect={onDisconnect}
            syncPending={syncPending}
          />
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Category section (collapsible)
// ---------------------------------------------------------------------------

function CategorySection({
  category,
  connectors,
  children,
}: {
  readonly category: CategoryDef;
  readonly connectors: readonly ConnectorCatalogEntry[];
  readonly children: React.ReactNode;
}) {
  const [collapsed, setCollapsed] = useState(false);
  const connectedCount = connectors.filter(
    (c) => c.status === "connected",
  ).length;

  return (
    <section>
      <button
        onClick={() => setCollapsed((c) => !c)}
        className="flex w-full items-center justify-between border-b border-hairline pb-2"
      >
        <div className="flex items-center gap-2">
          <span>{category.emoji}</span>
          <h3 className="text-sm font-semibold text-ink">
            {category.label}
          </h3>
          <span className="text-[11px] text-muted">
            {connectedCount}/{connectors.length}
          </span>
        </div>
        {collapsed ? (
          <ChevronRight className="h-4 w-4 text-muted" />
        ) : (
          <ChevronDown className="h-4 w-4 text-muted" />
        )}
      </button>
      {!collapsed && (
        <div className="mt-1 space-y-1">{children}</div>
      )}
    </section>
  );
}

// ---------------------------------------------------------------------------
// Custom connector section (placeholder)
// ---------------------------------------------------------------------------

function CustomConnectorSection() {
  const [expanded, setExpanded] = useState(false);
  const [command, setCommand] = useState("");

  return (
    <section className="rounded-4 border border-dashed border-hairline bg-surface/30 p-5">
      <button
        onClick={() => setExpanded((e) => !e)}
        className="flex w-full items-center justify-between"
      >
        <div className="flex items-center gap-2">
          <Plus className="h-4 w-4 text-indigo" strokeWidth={1.6} />
          <span className="text-sm font-medium text-ink">
            Add Custom Connector
          </span>
          <span className="rounded-full bg-indigo-soft px-2 py-0.5 text-[10px] font-medium text-indigo">
            Advanced
          </span>
        </div>
        {expanded ? (
          <ChevronDown className="h-4 w-4 text-muted" />
        ) : (
          <ChevronRight className="h-4 w-4 text-muted" />
        )}
      </button>

      {expanded && (
        <div className="mt-4 space-y-3">
          <p className="text-xs text-muted">
            Install any MCP-compatible server. Arandu will auto-discover
            its capabilities and data structure.
          </p>
          <input
            type="text"
            placeholder="npx -y @example/mcp-server"
            value={command}
            onChange={(e) => setCommand(e.target.value)}
            className="w-full rounded-2 bg-bg px-3 py-2 text-sm text-ink placeholder-muted outline-none ring-1 ring-hairline focus:ring-indigo"
          />
          <div className="flex items-center justify-between">
            <a
              href="https://mcp.so"
              target="_blank"
              rel="noopener noreferrer"
              className="flex items-center gap-1 text-xs text-indigo hover:underline"
            >
              Browse connectors at mcp.so
              <ExternalLink className="h-3 w-3" />
            </a>
            <div className="flex gap-2">
              <button
                onClick={() => {
                  setCommand("");
                  setExpanded(false);
                }}
                className="rounded-2 px-3 py-1.5 text-xs text-muted transition-colors hover:text-ink"
              >
                Cancel
              </button>
              <button
                disabled
                className="cursor-not-allowed rounded-2 bg-indigo px-3 py-1.5 text-xs font-medium text-white opacity-50"
              >
                Discover
              </button>
            </div>
          </div>
          <p className="text-[11px] text-muted">
            Custom connector discovery is not yet available.
          </p>
        </div>
      )}
    </section>
  );
}

// ---------------------------------------------------------------------------
// Main page component
// ---------------------------------------------------------------------------

function DataSourcesPage() {
  // --- State ---
  const [search, setSearch] = useState("");
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [pendingToggles, setPendingToggles] = useState<Set<string>>(
    () => new Set(),
  );
  const [pendingSyncs, setPendingSyncs] = useState<Set<string>>(
    () => new Set(),
  );

  // --- Connector details for expanded row ---
  const [details, setDetails] = useState<ConnectorDetailData | null>(null);
  const [detailsLoading, setDetailsLoading] = useState(false);

  // --- Data fetching ---
  const {
    data: catalog,
    error: catalogError,
    refetch: refetchCatalog,
    isLoading,
  } = useAsyncData<ConnectorCatalogEntry[]>(
    useCallback(
      () => dedupInvoke<ConnectorCatalogEntry[]>("get_connector_catalog"),
      [],
    ),
  );

  // Fetch details when expandedId changes
  useEffect(() => {
    if (!expandedId) {
      setDetails(null);
      return;
    }
    let cancelled = false;
    setDetailsLoading(true);
    invoke<ConnectorDetailData>("get_connector_details", {
      connectorId: expandedId,
    })
      .then((result) => {
        if (!cancelled) {
          setDetails(result);
          setDetailsLoading(false);
        }
      })
      .catch(() => {
        if (!cancelled) {
          setDetails(null);
          setDetailsLoading(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [expandedId]);

  // --- Derived data ---
  const filtered = useMemo(() => {
    if (!catalog) return [];
    const q = search.toLowerCase();
    if (!q) return catalog;
    return catalog.filter(
      (c) =>
        c.name.toLowerCase().includes(q) ||
        c.description.toLowerCase().includes(q),
    );
  }, [catalog, search]);

  const grouped = useMemo(() => groupByCategory(filtered), [filtered]);

  // --- Handlers ---

  // sensitivity_tier: 1 (connector enable/disable is infrastructure)
  const [toggleError, setToggleError] = useState<string | null>(null);

  const handleToggle = useCallback(
    async (connectorId: string, enabled: boolean) => {
      setToggleError(null);
      setPendingToggles((prev) => new Set(prev).add(connectorId));
      try {
        await invoke("toggle_connector", {
          connectorId,
          enabled,
        });
      } catch (err) {
        const msg =
          err instanceof Error ? err.message : String(err);
        console.error("toggle_connector failed:", msg);
        setToggleError(msg);
      } finally {
        setPendingToggles((prev) => {
          const next = new Set(prev);
          next.delete(connectorId);
          return next;
        });
        refetchCatalog();
      }
    },
    [refetchCatalog],
  );

  // sensitivity_tier: 1 (providing env vars for connector setup)
  const handleToggleWithInputs = useCallback(
    async (connectorId: string, userInputs: Record<string, string>) => {
      setToggleError(null);
      setPendingToggles((prev) => new Set(prev).add(connectorId));
      try {
        await invoke("toggle_connector", {
          connectorId,
          enabled: true,
          userInputs,
        });
      } catch (err) {
        const msg =
          err instanceof Error ? err.message : String(err);
        console.error("toggle_connector (with inputs) failed:", msg);
        setToggleError(msg);
      } finally {
        setPendingToggles((prev) => {
          const next = new Set(prev);
          next.delete(connectorId);
          return next;
        });
        refetchCatalog();
      }
    },
    [refetchCatalog],
  );

  // sensitivity_tier: 1 (triggering sync is infrastructure)
  const handleSyncNow = useCallback(
    async (connectorId: string) => {
      setPendingSyncs((prev) => new Set(prev).add(connectorId));
      try {
        await invoke("sync_connector_now", {
          connectorId,
        });
      } catch (err) {
        console.error("sync_connector_now failed:", err);
      } finally {
        setPendingSyncs((prev) => {
          const next = new Set(prev);
          next.delete(connectorId);
          return next;
        });
        refetchCatalog();
      }
    },
    [refetchCatalog],
  );

  const handleSyncAll = useCallback(async () => {
    if (!catalog) return;
    const connected = catalog.filter((c) => c.status === "connected");
    await Promise.allSettled(
      connected.map((c) => handleSyncNow(c.connector_id)),
    );
  }, [catalog, handleSyncNow]);

  const connectedCount = catalog
    ? catalog.filter((c) => c.status === "connected").length
    : 0;

  // --- Render ---
  return (
    <div className="flex-1 space-y-6 overflow-y-auto p-6">
      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <h2 className="text-[44px] font-bold leading-none" style={{ background: "linear-gradient(135deg, var(--ink), var(--ink-2))", WebkitBackgroundClip: "text", WebkitTextFillColor: "transparent", backgroundClip: "text" }}>Data Sources</h2>
          <p className="mt-1 text-sm text-muted">
            Everything runs locally on your Mac. Your data never leaves this
            device.
          </p>
        </div>
        {connectedCount > 0 && (
          <button
            onClick={handleSyncAll}
            className="flex shrink-0 items-center gap-1.5 rounded-2 bg-indigo px-3 py-2 text-xs font-medium text-white transition-colors hover:bg-indigo/90"
          >
            <RefreshCw className="h-3.5 w-3.5" strokeWidth={1.6} />
            Sync All
          </button>
        )}
      </div>

      {/* Search */}
      <div className="flex items-center gap-2 rounded-2 bg-surface px-3 py-2">
        <Search className="h-4 w-4 shrink-0 text-muted" strokeWidth={1.6} />
        <input
          type="text"
          placeholder="Search connectors..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="flex-1 bg-transparent text-sm text-ink placeholder-muted outline-none"
        />
        {search && (
          <button
            onClick={() => setSearch("")}
            className="text-muted hover:text-ink"
          >
            <Loader2 className="hidden h-3 w-3" />
            <span className="text-xs">&times;</span>
          </button>
        )}
      </div>

      {/* Toggle error banner */}
      {toggleError && (
        <div className="flex items-center justify-between rounded-2 border border-amber/30 bg-amber/5 px-4 py-2 text-xs text-amber">
          <span>Toggle failed: {toggleError}</span>
          <button
            onClick={() => setToggleError(null)}
            className="ml-2 text-muted hover:text-ink"
          >
            &times;
          </button>
        </div>
      )}

      {/* Content — only show skeletons on initial load, not refetch */}
      {isLoading && !catalog ? (
        <div className="space-y-6">
          <SkeletonSection />
          <SkeletonSection />
          <SkeletonSection />
        </div>
      ) : catalogError && !catalog ? (
        <div className="rounded-4 border border-amber/30 bg-amber/5 px-4 py-3 text-sm text-amber">
          {catalogError}
        </div>
      ) : filtered.length === 0 && search ? (
        <p className="py-8 text-center text-sm text-muted">
          No connectors match &ldquo;{search}&rdquo;
        </p>
      ) : (
        <div className="space-y-6">
          {CATEGORIES.map((cat) => {
            const items = grouped.get(cat.id) ?? [];
            if (items.length === 0) return null;
            return (
              <CategorySection
                key={cat.id}
                category={cat}
                connectors={items}
              >
                {items.map((connector) => (
                  <ConnectorRow
                    key={connector.connector_id}
                    connector={connector}
                    expanded={expandedId === connector.connector_id}
                    details={
                      expandedId === connector.connector_id
                        ? details
                        : null
                    }
                    detailsLoading={
                      expandedId === connector.connector_id &&
                      detailsLoading
                    }
                    onToggle={(enabled) =>
                      handleToggle(connector.connector_id, enabled)
                    }
                    onToggleWithInputs={(inputs) =>
                      handleToggleWithInputs(
                        connector.connector_id,
                        inputs,
                      )
                    }
                    onExpand={() =>
                      setExpandedId(
                        expandedId === connector.connector_id
                          ? null
                          : connector.connector_id,
                      )
                    }
                    onSyncNow={() =>
                      handleSyncNow(connector.connector_id)
                    }
                    onDisconnect={() =>
                      handleToggle(connector.connector_id, false)
                    }
                    togglePending={pendingToggles.has(
                      connector.connector_id,
                    )}
                    syncPending={pendingSyncs.has(
                      connector.connector_id,
                    )}
                  />
                ))}
              </CategorySection>
            );
          })}

          <CustomConnectorSection />
        </div>
      )}
    </div>
  );
}

export default DataSourcesPage;

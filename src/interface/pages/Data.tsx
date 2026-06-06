/**
 * Data page — tabbed container for all data-layer surfaces.
 *
 * Wraps the previously top-level Sources, Models, Graph, Vectors, and
 * Audit Log pages behind a single sidebar entry. Active tab is mirrored
 * in the URL via `?tab=<id>` so deep links and back/forward still work.
 *
 * sensitivity_tier: 2 (child pages display user data)
 */

import { useSearchParams } from "react-router-dom";
import { Database, Layers, GitFork, Sparkles, ShieldCheck } from "lucide-react";
import Explorer from "./Explorer";
import DataMarts from "./DataMarts";
import GraphExplorer from "./GraphExplorer";
import VectorExplorer from "./VectorExplorer";
import AuditPage from "./AuditPage";
import { usePipelineStatus } from "../hooks/usePipelineStatus";
import { useAsyncData } from "../hooks/useAsyncData";
import { dedupInvoke } from "../utils/requestDedup";

const ICON_STROKE = 1.6;

interface TabDef {
  readonly id: string;
  readonly label: string;
  readonly icon: typeof Database;
  readonly render: () => JSX.Element;
}

const TABS: ReadonlyArray<TabDef> = [
  { id: "models", label: "Models", icon: Layers, render: () => <DataMarts /> },
  { id: "sources", label: "Sources", icon: Database, render: () => <Explorer /> },
  { id: "graph", label: "Graph", icon: GitFork, render: () => <GraphExplorer /> },
  { id: "vectors", label: "Vectors", icon: Sparkles, render: () => <VectorExplorer /> },
  { id: "audit", label: "Audit Log", icon: ShieldCheck, render: () => <AuditPage /> },
];

const DEFAULT_TAB = "models";

interface ConnectorStatusLite {
  readonly status: string;
}

function Data() {
  const [searchParams, setSearchParams] = useSearchParams();
  const requested = searchParams.get("tab") ?? DEFAULT_TAB;
  const active = TABS.find((t) => t.id === requested) ?? TABS[0];

  // Per-tab health badges: surface which surface is failing without
  // making the user open each one.
  const { pipelineStatus } = usePipelineStatus();
  const lastRun = pipelineStatus?.last_run ?? null;
  const connectors = useAsyncData<ConnectorStatusLite[]>(() =>
    dedupInvoke<ConnectorStatusLite[]>("get_connector_catalog"),
  );
  const sourcesFailing =
    connectors.data?.some((c) => c.status === "error") ?? false;
  const tabErrors: Record<string, boolean> = {
    sources: sourcesFailing,
    vectors: lastRun?.vector_index_status === "error",
    graph: lastRun?.graph_index_status === "error",
  };

  function selectTab(id: string) {
    if (id === DEFAULT_TAB) {
      setSearchParams({}, { replace: false });
    } else {
      setSearchParams({ tab: id }, { replace: false });
    }
  }

  return (
    <div className="flex flex-col">
      {/* Tab bar */}
      <div className="sticky top-0 z-10 frosted border-b border-hairline px-6 pt-4">
        <div className="flex items-center gap-1">
          {TABS.map(({ id, label, icon: Icon }) => {
            const isActive = id === active.id;
            return (
              <button
                key={id}
                onClick={() => selectTab(id)}
                className={`flex items-center gap-2 rounded-t-2 px-3 py-2 text-[13.5px] font-medium transition-colors ${
                  isActive
                    ? "text-indigo-2 border-b-2 border-indigo"
                    : "text-muted border-b-2 border-transparent hover:text-ink"
                }`}
              >
                <Icon
                  className={`h-[16px] w-[16px] ${isActive ? "text-indigo" : "text-muted"}`}
                  strokeWidth={ICON_STROKE}
                />
                <span style={{ letterSpacing: "-0.005em" }}>{label}</span>
                {tabErrors[id] && (
                  <span
                    className="h-1.5 w-1.5 rounded-full bg-danger"
                    title="This stage is reporting an error"
                  />
                )}
              </button>
            );
          })}
        </div>
      </div>

      {/* Active tab content */}
      <div>{active.render()}</div>
    </div>
  );
}

export default Data;

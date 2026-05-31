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

function Data() {
  const [searchParams, setSearchParams] = useSearchParams();
  const requested = searchParams.get("tab") ?? DEFAULT_TAB;
  const active = TABS.find((t) => t.id === requested) ?? TABS[0];

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

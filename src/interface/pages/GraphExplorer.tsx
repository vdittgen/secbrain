/**
 * Knowledge Graph page — explorer for Kuzu graph node and relationship data.
 *
 * Shows node types and relationship types with counts, expandable to show
 * sample nodes/relationships from the graph database.
 *
 * sensitivity_tier: 2 (displays user data from graph nodes)
 */

import { useState, useCallback } from "react";
import { RefreshCw, ChevronRight, GitFork } from "lucide-react";
import { SkeletonTable } from "../components/LoadingState";
import { formatCount } from "../components/GenericDataTable";
import { useAsyncData } from "../hooks/useAsyncData";
import { dedupInvoke } from "../utils/requestDedup";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface GraphNodeTypeInfo {
  readonly name: string;
  readonly count: number;
}

interface GraphRelTypeInfo {
  readonly name: string;
  readonly count: number;
}

interface GraphSummary {
  readonly nodes: readonly GraphNodeTypeInfo[];
  readonly relationships: readonly GraphRelTypeInfo[];
  readonly total_nodes: number;
  readonly total_relationships: number;
}

interface GraphNodeSample {
  readonly node_type: string;
  readonly total: number;
  readonly nodes: readonly Record<string, unknown>[];
}

interface GraphRelSample {
  readonly rel_type: string;
  readonly total: number;
  readonly relationships: readonly Record<string, unknown>[];
}

// ---------------------------------------------------------------------------
// NodeTypeRow
// ---------------------------------------------------------------------------

function NodeTypeRow({
  info,
  expanded,
  onToggle,
}: {
  readonly info: GraphNodeTypeInfo;
  readonly expanded: boolean;
  readonly onToggle: () => void;
}) {
  const [sample, setSample] = useState<GraphNodeSample | null>(null);
  const [loading, setLoading] = useState(false);

  async function handleToggle() {
    if (!expanded && !sample && !loading) {
      setLoading(true);
      try {
        const result = await dedupInvoke<GraphNodeSample>(
          "query_graph_nodes",
          { node_type: info.name, limit: 10 },
        );
        setSample(result);
      } catch {
        /* ignore */
      } finally {
        setLoading(false);
      }
    }
    onToggle();
  }

  return (
    <div className="rounded-2 border border-hairline bg-surface/30 overflow-hidden">
      <button
        className="flex w-full items-center gap-3 px-4 py-2.5 text-left hover:bg-surface/50 transition-colors"
        onClick={handleToggle}
      >
        <ChevronRight strokeWidth={1.6}
          className={`h-3.5 w-3.5 shrink-0 text-muted transition-transform ${
            expanded ? "rotate-90" : ""
          }`}
        />
        <span className="flex-1 text-sm font-medium text-ink">
          {info.name}
        </span>
        <span className="shrink-0 rounded-full bg-indigo-soft px-2.5 py-0.5 text-xs font-medium text-indigo-2">
          {formatCount(info.count)}
        </span>
      </button>

      {expanded && (
        <div className="border-t border-hairline px-4 py-3">
          {loading && (
            <p className="text-xs text-muted">Loading samples…</p>
          )}
          {sample && sample.nodes.length === 0 && (
            <p className="text-xs text-muted">No nodes of this type</p>
          )}
          {sample && sample.nodes.length > 0 && (
            <div className="flex flex-col gap-2">
              {sample.nodes.map((node, i) => (
                <div
                  key={String(node.id ?? i)}
                  className="rounded border border-hairline/50 bg-surface/20 px-3 py-2"
                >
                  <div className="grid grid-cols-2 sm:grid-cols-3 gap-x-4 gap-y-1 text-xs">
                    {Object.entries(node).map(([key, val]) => (
                      <div key={key} className="flex gap-1.5">
                        <span className="text-muted shrink-0">{key}:</span>
                        <span className="text-ink truncate">
                          {val === null ? "—" : String(val)}
                        </span>
                      </div>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// RelTypeRow
// ---------------------------------------------------------------------------

function RelTypeRow({
  info,
  expanded,
  onToggle,
}: {
  readonly info: GraphRelTypeInfo;
  readonly expanded: boolean;
  readonly onToggle: () => void;
}) {
  const [sample, setSample] = useState<GraphRelSample | null>(null);
  const [loading, setLoading] = useState(false);

  async function handleToggle() {
    if (!expanded && !sample && !loading) {
      setLoading(true);
      try {
        const result = await dedupInvoke<GraphRelSample>(
          "query_graph_relationships",
          { rel_type: info.name, limit: 10 },
        );
        setSample(result);
      } catch {
        /* ignore */
      } finally {
        setLoading(false);
      }
    }
    onToggle();
  }

  return (
    <div className="rounded-2 border border-hairline bg-surface/30 overflow-hidden">
      <button
        className="flex w-full items-center gap-3 px-4 py-2.5 text-left hover:bg-surface/50 transition-colors"
        onClick={handleToggle}
      >
        <ChevronRight strokeWidth={1.6}
          className={`h-3.5 w-3.5 shrink-0 text-muted transition-transform ${
            expanded ? "rotate-90" : ""
          }`}
        />
        <span className="flex-1 text-sm font-medium text-ink">
          {info.name}
        </span>
        <span className="shrink-0 rounded-full bg-indigo-soft px-2.5 py-0.5 text-xs font-medium text-indigo-2">
          {formatCount(info.count)}
        </span>
      </button>

      {expanded && (
        <div className="border-t border-hairline px-4 py-3">
          {loading && (
            <p className="text-xs text-muted">Loading samples…</p>
          )}
          {sample && sample.relationships.length === 0 && (
            <p className="text-xs text-muted">
              No relationships of this type
            </p>
          )}
          {sample && sample.relationships.length > 0 && (
            <div className="flex flex-col gap-1.5">
              {sample.relationships.map((rel, i) => (
                <div
                  key={i}
                  className="flex items-center gap-2 rounded border border-hairline/50 bg-surface/20 px-3 py-2 text-xs"
                >
                  <span className="text-indigo font-medium truncate">
                    {String(rel.source_name || rel.source_id || "?")}
                  </span>
                  <span className="text-muted">→</span>
                  <span className="text-indigo font-medium truncate">
                    {String(rel.target_name || rel.target_id || "?")}
                  </span>
                  {rel.weight != null && (
                    <span className="ml-auto text-muted">
                      w: {String(rel.weight)}
                    </span>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// GraphExplorer
// ---------------------------------------------------------------------------

function GraphExplorer() {
  const [expandedNode, setExpandedNode] = useState<string | null>(null);
  const [expandedRel, setExpandedRel] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);

  const summaryResult = useAsyncData<GraphSummary>(
    useCallback(
      () => dedupInvoke<GraphSummary>("graph_summary", {}),
      [],
    ),
  );

  async function handleRefresh() {
    setRefreshing(true);
    try {
      await summaryResult.refetch();
    } finally {
      setRefreshing(false);
    }
  }

  const summary = summaryResult.data;

  return (
    <div className="flex flex-col gap-4 p-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-[28px] font-semibold leading-tight" style={{ background: "linear-gradient(135deg, var(--ink), var(--ink-2))", WebkitBackgroundClip: "text", WebkitTextFillColor: "transparent", backgroundClip: "text" }}>
            Knowledge Graph
          </h1>
          <p className="mt-1 text-xs text-muted">
            {summary
              ? `${formatCount(summary.total_nodes)} nodes · ${formatCount(summary.total_relationships)} relationships`
              : "Loading\u2026"}
          </p>
        </div>
        <button
          onClick={handleRefresh}
          disabled={refreshing}
          className="flex items-center gap-1.5 rounded-2 bg-surface px-3 py-1.5 text-xs text-muted hover:text-ink transition-colors"
        >
          <RefreshCw
            className={`h-3.5 w-3.5 ${refreshing ? "animate-spin" : ""}`}
          />
          Refresh
        </button>
      </div>

      {summaryResult.isLoading && <SkeletonTable />}

      {summaryResult.error && (
        <div className="rounded-2 border border-amber/30 bg-amber/10 px-4 py-3 text-xs text-amber">
          Failed to load graph: {summaryResult.error}
        </div>
      )}

      {summary && (
        <>
          {/* Nodes section */}
          <div>
            <h2 className="text-sm font-semibold text-ink mb-2">
              Node Types
            </h2>
            {summary.nodes.length === 0 ? (
              <div className="flex flex-col items-center gap-2 py-8 text-muted">
                <GitFork className="h-8 w-8 opacity-40" />
                <p className="text-sm">No graph nodes yet</p>
              </div>
            ) : (
              <div className="flex flex-col gap-1.5">
                {summary.nodes.map((node) => (
                  <NodeTypeRow
                    key={node.name}
                    info={node}
                    expanded={expandedNode === node.name}
                    onToggle={() =>
                      setExpandedNode((prev) =>
                        prev === node.name ? null : node.name,
                      )
                    }
                  />
                ))}
              </div>
            )}
          </div>

          {/* Relationships section */}
          <div>
            <h2 className="text-sm font-semibold text-ink mb-2">
              Relationship Types
            </h2>
            {summary.relationships.length === 0 ? (
              <p className="text-xs text-muted py-4">
                No relationships yet
              </p>
            ) : (
              <div className="flex flex-col gap-1.5">
                {summary.relationships.map((rel) => (
                  <RelTypeRow
                    key={rel.name}
                    info={rel}
                    expanded={expandedRel === rel.name}
                    onToggle={() =>
                      setExpandedRel((prev) =>
                        prev === rel.name ? null : rel.name,
                      )
                    }
                  />
                ))}
              </div>
            )}
          </div>
        </>
      )}
    </div>
  );
}

export default GraphExplorer;

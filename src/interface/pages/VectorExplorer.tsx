/**
 * Vector Store page — explorer for ChromaDB collections and documents.
 *
 * Shows collections with document counts and sample documents.
 * Samples are loaded eagerly (5 per collection) since there are only
 * 5 collections total.
 *
 * sensitivity_tier: 2 (displays user data from vector documents)
 */

import { useState, useCallback } from "react";
import { RefreshCw, ChevronRight, Sparkles } from "lucide-react";
import { SkeletonTable } from "../components/LoadingState";
import { formatCount } from "../components/GenericDataTable";
import { useAsyncData } from "../hooks/useAsyncData";
import { dedupInvoke } from "../utils/requestDedup";
import { usePipelineStatus } from "../hooks/usePipelineStatus";
import { AlertTriangle } from "lucide-react";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface VectorDocSample {
  readonly id: string;
  readonly document: string;
  readonly metadata: Record<string, unknown>;
}

interface VectorCollectionInfo {
  readonly name: string;
  readonly count: number;
  readonly samples: readonly VectorDocSample[];
}

interface VectorSummary {
  readonly collections: readonly VectorCollectionInfo[];
}

// ---------------------------------------------------------------------------
// MetadataTag
// ---------------------------------------------------------------------------

function MetadataTag({
  label,
  value,
}: {
  readonly label: string;
  readonly value: string;
}) {
  return (
    <span className="inline-flex items-center gap-1 rounded bg-surface px-1.5 py-0.5 text-[10px] text-muted">
      <span className="font-medium">{label}:</span>
      {value}
    </span>
  );
}

// ---------------------------------------------------------------------------
// CollectionRow
// ---------------------------------------------------------------------------

function CollectionRow({
  info,
  expanded,
  onToggle,
}: {
  readonly info: VectorCollectionInfo;
  readonly expanded: boolean;
  readonly onToggle: () => void;
}) {
  return (
    <div className="rounded-2 border border-hairline bg-surface/30 overflow-hidden">
      <button
        className="flex w-full items-center gap-3 px-4 py-2.5 text-left hover:bg-surface/50 transition-colors"
        onClick={onToggle}
      >
        <ChevronRight strokeWidth={1.6}
          className={`h-3.5 w-3.5 shrink-0 text-muted transition-transform ${
            expanded ? "rotate-90" : ""
          }`}
        />
        <span className="flex-1 text-sm font-medium capitalize text-ink">
          {info.name}
        </span>
        <span className="shrink-0 rounded-full bg-indigo-soft px-2.5 py-0.5 text-xs font-medium text-indigo-2">
          {formatCount(info.count)} docs
        </span>
      </button>

      {expanded && (
        <div className="border-t border-hairline px-4 py-3">
          {info.samples.length === 0 ? (
            <p className="text-xs text-muted">No documents in this collection</p>
          ) : (
            <div className="flex flex-col gap-2">
              {info.samples.map((doc) => (
                <div
                  key={doc.id}
                  className="rounded border border-hairline/50 bg-surface/20 px-3 py-2"
                >
                  <p className="text-xs text-ink leading-relaxed mb-1.5">
                    {doc.document || "(empty)"}
                  </p>
                  <div className="flex flex-wrap gap-1">
                    {doc.metadata.source_table != null && (
                      <MetadataTag
                        label="table"
                        value={String(doc.metadata.source_table)}
                      />
                    )}
                    {doc.metadata.source != null && (
                      <MetadataTag
                        label="source"
                        value={String(doc.metadata.source)}
                      />
                    )}
                    {doc.metadata.sensitivity_tier != null && (
                      <MetadataTag
                        label="tier"
                        value={String(doc.metadata.sensitivity_tier)}
                      />
                    )}
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
// VectorExplorer
// ---------------------------------------------------------------------------

function VectorExplorer() {
  const [expandedCol, setExpandedCol] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);

  const summaryResult = useAsyncData<VectorSummary>(
    useCallback(
      () => dedupInvoke<VectorSummary>("vector_summary", {}),
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
  const totalDocs = summary
    ? summary.collections.reduce((s, c) => s + c.count, 0)
    : 0;

  // Explain an empty store: the last re-index may have failed (e.g.
  // embedding dimension mismatch after a model change).
  const { pipelineStatus } = usePipelineStatus();
  const indexError =
    pipelineStatus?.last_run?.vector_index_status === "error"
      ? pipelineStatus.last_run.index_error
      : null;

  return (
    <div className="flex flex-col gap-4 p-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-[28px] font-semibold leading-tight" style={{ background: "linear-gradient(135deg, var(--ink), var(--ink-2))", WebkitBackgroundClip: "text", WebkitTextFillColor: "transparent", backgroundClip: "text" }}>Vector Store</h1>
          <p className="mt-1 text-xs text-muted">
            {summary
              ? `${summary.collections.length} collections · ${formatCount(totalDocs)} documents`
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

      {indexError && (
        <div className="flex items-start gap-2 rounded-2 border border-danger/30 bg-danger/10 px-4 py-3 text-xs text-danger">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
          <div>
            <p className="font-medium">Last index update failed</p>
            <p className="mt-0.5">{indexError}</p>
          </div>
        </div>
      )}

      {summaryResult.isLoading && <SkeletonTable />}

      {summaryResult.error && (
        <div className="rounded-2 border border-amber/30 bg-amber/10 px-4 py-3 text-xs text-amber">
          Failed to load vector store: {summaryResult.error}
        </div>
      )}

      {summary && (
        <div className="flex flex-col gap-1.5">
          {summary.collections.length === 0 ? (
            <div className="flex flex-col items-center gap-2 py-12 text-muted">
              <Sparkles className="h-8 w-8 opacity-40" />
              <p className="text-sm">
                No vector collections yet. Run the pipeline to index documents.
              </p>
            </div>
          ) : (
            summary.collections.map((col) => (
              <CollectionRow
                key={col.name}
                info={col}
                expanded={expandedCol === col.name}
                onToggle={() =>
                  setExpandedCol((prev) =>
                    prev === col.name ? null : col.name,
                  )
                }
              />
            ))
          )}
        </div>
      )}
    </div>
  );
}

export default VectorExplorer;

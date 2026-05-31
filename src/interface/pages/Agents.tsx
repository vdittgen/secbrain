// Agents page — Pydantic AI agent registry editor.
//
// Layout: master-detail. Left column is a flat list (search + depth
// indentation derived from parent_agent). Right column is a detail
// pane with four mode tabs: Overview, Edit, Evals & runs, Architecture.
//
// Selection + mode are deep-linkable via `?agent=<id>&mode=<key>`.
//
// sensitivity_tier: 1

import { useCallback, useEffect, useMemo, useState } from "react";
import type { JSX } from "react";
import { useSearchParams } from "react-router-dom";
import { invoke } from "@tauri-apps/api/core";
import {
  Loader2,
  Play,
  Plus,
  ShieldCheck,
} from "lucide-react";

import { useAsyncData } from "../hooks/useAsyncData";
import { dedupInvoke } from "../utils/requestDedup";
import { SkeletonSection } from "../components/LoadingState";

import { AgentListPane } from "./agents/AgentListPane";
import { CreateUserAgentModal } from "./agents/create/CreateUserAgentModal";
import {
  AgentDetailPane,
  type DetailMode,
} from "./agents/detail/AgentDetailPane";

import type {
  AgentEvalRunResponse,
  PydanticAgentListResponse,
} from "../types/agents";

type TabKey = "editable" | "locked";

const VALID_MODES: ReadonlyArray<DetailMode> = [
  "overview", "edit", "evals", "architecture",
];

function parseMode(raw: string | null): DetailMode {
  if (raw && (VALID_MODES as ReadonlyArray<string>).includes(raw)) {
    return raw as DetailMode;
  }
  return "overview";
}

function Agents(): JSX.Element {
  const [searchParams, setSearchParams] = useSearchParams();
  const [modalOpen, setModalOpen] = useState(false);
  const [refreshKey, setRefreshKey] = useState(0);
  const [runAllState, setRunAllState] = useState<{
    running: boolean;
    done: number;
    total: number;
  }>({ running: false, done: 0, total: 0 });

  const result = useAsyncData<PydanticAgentListResponse>(
    useCallback(
      () => dedupInvoke<PydanticAgentListResponse>("list_pydantic_agents"),
      [],
    ),
  );

  const [activeTab, setActiveTab] = useState<TabKey>("editable");

  const rows = result.data?.agents ?? [];

  const lockedRows = useMemo(
    () => rows.filter((r) => !r.editable),
    [rows],
  );
  const editableRows = useMemo(
    () => rows.filter((r) => r.editable),
    [rows],
  );
  const visibleRows = activeTab === "locked" ? lockedRows : editableRows;

  const selectedAgentId = searchParams.get("agent");
  const mode = parseMode(searchParams.get("mode"));
  const selectedRow = useMemo(
    () => rows.find((r) => r.agent_id === selectedAgentId) ?? null,
    [rows, selectedAgentId],
  );

  const setSelection = useCallback(
    (agentId: string, nextMode?: DetailMode) => {
      setSearchParams((prev) => {
        const next = new URLSearchParams(prev);
        next.set("agent", agentId);
        if (nextMode) next.set("mode", nextMode);
        return next;
      }, { replace: true });
    },
    [setSearchParams],
  );

  const setMode = useCallback((nextMode: DetailMode) => {
    setSearchParams((prev) => {
      const next = new URLSearchParams(prev);
      if (nextMode === "overview") next.delete("mode");
      else next.set("mode", nextMode);
      return next;
    }, { replace: true });
  }, [setSearchParams]);

  // Auto-pick the first row when nothing is selected (or selection vanished).
  useEffect(() => {
    if (!result.data) return;
    if (selectedRow) return;
    const first = visibleRows[0];
    if (first) setSelection(first.agent_id);
  }, [result.data, selectedRow, visibleRows, setSelection]);

  const clearSelection = useCallback(() => {
    setSearchParams((prev) => {
      const next = new URLSearchParams(prev);
      next.delete("agent");
      next.delete("mode");
      return next;
    }, { replace: true });
  }, [setSearchParams]);

  const handleTabClick = useCallback((tab: TabKey) => {
    setActiveTab(tab);
    const bucket = tab === "locked" ? lockedRows : editableRows;
    const stillVisible = bucket.some((r) => r.agent_id === selectedAgentId);
    if (stillVisible) return;
    const first = bucket[0];
    if (first) setSelection(first.agent_id);
    else clearSelection();
  }, [
    lockedRows,
    editableRows,
    selectedAgentId,
    setSelection,
    clearSelection,
  ]);

  // Sync tab to the selected agent's bucket on deep-link / external selection
  // changes. Skipped when the user clicked a tab — handleTabClick already
  // migrates the selection, so this effect would otherwise fight it and
  // snap the tab back.
  useEffect(() => {
    if (!selectedRow) return;
    const desired: TabKey = selectedRow.editable ? "editable" : "locked";
    if (desired !== activeTab) setActiveTab(desired);
  }, [selectedRow, activeTab]);

  const handleChanged = useCallback(() => {
    result.refetch();
    setRefreshKey((k) => k + 1);
  }, [result]);

  const handleDeleted = useCallback(() => {
    setSearchParams((prev) => {
      const next = new URLSearchParams(prev);
      next.delete("agent");
      next.delete("mode");
      return next;
    }, { replace: true });
    result.refetch();
    setRefreshKey((k) => k + 1);
  }, [result, setSearchParams]);

  const runAllEvals = useCallback(async () => {
    if (rows.length === 0 || runAllState.running) return;
    setRunAllState({ running: true, done: 0, total: rows.length });
    setRefreshKey((k) => k + 1);
    await Promise.allSettled(
      rows.map(async (r) => {
        try {
          await invoke<AgentEvalRunResponse>("run_agent_eval", {
            agentId: r.agent_id,
          });
        } finally {
          setRunAllState((s) => ({ ...s, done: s.done + 1 }));
          setRefreshKey((k) => k + 1);
        }
      }),
    );
    setRunAllState({ running: false, done: 0, total: 0 });
    setRefreshKey((k) => k + 1);
  }, [rows, runAllState.running]);

  if (result.isLoading && !result.data) {
    return (
      <div className="space-y-4">
        <SkeletonSection />
        <SkeletonSection />
        <SkeletonSection />
      </div>
    );
  }

  if (result.error) {
    return (
      <div className="rounded-4 border border-amber/60 bg-amber/10 p-4 text-sm text-amber">
        Failed to load agents: {result.error}
      </div>
    );
  }

  return (
    <div className="flex h-full flex-col space-y-4">
      <header className="flex items-start justify-between gap-3">
        <div>
          <h1
            className="text-[44px] font-bold leading-none"
            style={{
              background: "linear-gradient(135deg, var(--ink), var(--ink-2))",
              WebkitBackgroundClip: "text",
              WebkitTextFillColor: "transparent",
              backgroundClip: "text",
            }}
          >
            Agents
          </h1>
          <p className="text-sm text-muted">
            Compose agents from sources, tools, and delivery hooks.
            Run on a schedule, gate edits behind evals, deliver to
            WhatsApp, email, or the app.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={runAllEvals}
            disabled={runAllState.running || rows.length === 0}
            className="inline-flex items-center gap-1 rounded-md border border-hairline px-3 py-1.5 text-[12px] text-ink hover:bg-surface disabled:opacity-50"
            title="Run the eval suite for every agent"
          >
            {runAllState.running
              ? <Loader2 size={12} className="animate-spin" />
              : <Play size={12} />}
            {runAllState.running
              ? `Running evals (${runAllState.done}/${runAllState.total})…`
              : "Run all evals"}
          </button>
          <button
            type="button"
            onClick={() => setModalOpen(true)}
            className="inline-flex items-center gap-1 rounded-md bg-indigo px-3 py-1.5 text-[12px] text-white hover:bg-indigo/90"
          >
            <Plus size={12} /> New agent
          </button>
        </div>
      </header>

      <div
        role="tablist"
        aria-label="Agent groups"
        className="flex shrink-0 items-center gap-1 border-b border-hairline"
      >
        {(["editable", "locked"] as const).map((tab) => {
          const count = tab === "locked"
            ? lockedRows.length
            : editableRows.length;
          const label = tab === "locked" ? "System" : "User";
          const active = activeTab === tab;
          return (
            <button
              key={tab}
              type="button"
              role="tab"
              aria-selected={active}
              onClick={() => handleTabClick(tab)}
              className={
                "px-3 py-2 text-[12px] -mb-px border-b-2 transition-colors "
                + (active
                  ? "border-indigo text-indigo-2"
                  : "border-transparent text-muted hover:text-ink")
              }
            >
              <span>{label}</span>
              <span className="ml-1 text-muted">({count})</span>
            </button>
          );
        })}
      </div>

      <div className="grid min-h-0 flex-1 grid-cols-[320px_minmax(0,1fr)] gap-3 overflow-hidden">
        <aside className="flex min-h-0 flex-col overflow-hidden rounded-4 border border-hairline bg-surface">
          {visibleRows.length === 0
            ? (
              <div className="p-4 text-[12px] text-muted">
                {activeTab === "locked"
                  ? "No locked agents registered."
                  : (
                    <>
                      No editable agents yet — click{" "}
                      <strong>New agent</strong> to create one.
                    </>
                  )}
              </div>
            )
            : (
              <AgentListPane
                rows={visibleRows}
                selectedAgentId={selectedAgentId}
                onSelect={(id) => setSelection(id)}
                refreshKey={refreshKey}
              />
            )}
        </aside>

        <main className="flex min-h-0 flex-col overflow-hidden rounded-4 border border-hairline bg-surface">
          {selectedRow
            ? (
              <AgentDetailPane
                key={selectedRow.agent_id}
                row={selectedRow}
                allAgents={rows}
                refreshKey={refreshKey}
                mode={mode}
                onModeChange={setMode}
                onChanged={handleChanged}
                onDeleted={handleDeleted}
              />
            )
            : (
              <div className="flex h-full items-center justify-center px-6 text-[12px] text-muted">
                Select an agent from the left to see its details.
              </div>
            )}
        </main>
      </div>

      <footer className="flex shrink-0 items-center gap-2 pt-2 text-[11px] text-muted">
        <ShieldCheck size={12} />
        Edits are persisted to <code>agent_configs</code> and{" "}
        <code>user_agents</code>; the firewall audit chain still records
        every prompt.
      </footer>

      <CreateUserAgentModal
        open={modalOpen}
        onClose={() => setModalOpen(false)}
        onCreated={() => handleChanged()}
        availableAgents={rows}
      />
    </div>
  );
}

export default Agents;

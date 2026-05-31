// Master pane (left column) of the Agents page. Renders a search +
// flat list with depth indentation taken from the parent_agent tree.
//
// sensitivity_tier: 1

import type { JSX } from "react";
import { useMemo, useState } from "react";
import { Lock, Search } from "lucide-react";
import type { PydanticAgentRow } from "../../types/agents";
import { useAgentEval } from "./hooks/useAgentEval";
import { TIER_DOT, TIER_LABELS } from "./shared/constants";
import {
  buildAgentTree,
  flattenTree,
  isUserAgent,
  statusIcon,
} from "./shared/utils";
import type { AgentTreeNode } from "./shared/utils";

interface AgentListPaneProps {
  readonly rows: ReadonlyArray<PydanticAgentRow>;
  readonly selectedAgentId: string | null;
  readonly onSelect: (agentId: string) => void;
  readonly refreshKey: number;
}

export function AgentListPane({
  rows,
  selectedAgentId,
  onSelect,
  refreshKey,
}: AgentListPaneProps): JSX.Element {
  const [query, setQuery] = useState("");

  const tree = useMemo(() => buildAgentTree(rows), [rows]);
  const flat = useMemo(() => flattenTree(tree), [tree]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return flat;
    return flat.filter((n) =>
      n.row.name.toLowerCase().includes(q)
      || n.row.agent_id.toLowerCase().includes(q)
      || n.row.description.toLowerCase().includes(q)
    );
  }, [flat, query]);

  return (
    <div className="flex h-full flex-col">
      <div className="px-2 pb-2">
        <div className="relative">
          <Search
            size={12}
            className="absolute left-2 top-1/2 -translate-y-1/2 text-muted"
          />
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search agents…"
            className="w-full rounded-md border border-hairline bg-surface px-7 py-1.5 text-[12px] text-ink placeholder:text-muted/60 focus:border-indigo focus:outline-none"
          />
        </div>
      </div>
      <div className="flex-1 overflow-auto px-1 pb-2">
        {filtered.length === 0
          ? (
            <div className="px-3 py-4 text-[12px] text-muted">
              {query
                ? `No agents match “${query}”.`
                : "No agents in this group."}
            </div>
          )
          : (
            <ul className="space-y-0.5">
              {filtered.map((node) => (
                <li key={node.row.agent_id}>
                  <AgentListRow
                    node={node}
                    selected={selectedAgentId === node.row.agent_id}
                    onSelect={onSelect}
                    refreshKey={refreshKey}
                  />
                </li>
              ))}
            </ul>
          )}
      </div>
    </div>
  );
}

interface AgentListRowProps {
  readonly node: AgentTreeNode;
  readonly selected: boolean;
  readonly onSelect: (agentId: string) => void;
  readonly refreshKey: number;
}

function AgentListRow({
  node,
  selected,
  onSelect,
  refreshKey,
}: AgentListRowProps): JSX.Element {
  const { row, depth } = node;
  const evalStatus = useAgentEval(row.agent_id, refreshKey);
  const ownership: "user" | "builtin" | "locked" = isUserAgent(row)
    ? "user"
    : row.editable
      ? "builtin"
      : "locked";

  return (
    <button
      type="button"
      onClick={() => onSelect(row.agent_id)}
      aria-current={selected ? "true" : "false"}
      className={[
        "flex w-full items-start gap-2 rounded-md px-2 py-1.5 text-left transition-colors",
        selected
          ? "bg-indigo-soft ring-1 ring-indigo/40"
          : "hover:bg-surface/60",
      ].join(" ")}
      style={{ paddingLeft: 8 + depth * 12 }}
    >
      <span className="mt-1">
        {statusIcon(
          evalStatus.polling || (evalStatus.loading && !evalStatus.run)
            ? "loading"
            : (evalStatus.run?.status ?? "idle"),
        )}
      </span>
      <span className="flex min-w-0 flex-1 flex-col">
        <span className="flex items-center gap-1.5">
          <span className="truncate text-[13px] font-medium text-ink">
            {row.name}
          </span>
          {ownership === "user" && (
            <span className="shrink-0 rounded-full border border-indigo/40 px-1.5 py-px text-[9px] text-indigo">
              yours
            </span>
          )}
          {ownership === "locked" && (
            <Lock size={9} className="shrink-0 text-muted" />
          )}
        </span>
        <span className="flex items-center gap-2 text-[10px] text-muted">
          <span className="inline-flex items-center gap-1">
            <span
              className={`h-1.5 w-1.5 rounded-full ${TIER_DOT[row.tier]}`}
            />
            {TIER_LABELS[row.tier]}
          </span>
          <span className="truncate font-mono">{row.agent_id}</span>
        </span>
      </span>
    </button>
  );
}

// Helpers reused by multiple Agents-page panes.
//
// sensitivity_tier: 1

import type { JSX } from "react";
import {
  CircleAlert,
  CircleCheck,
  CircleDashed,
  CircleX,
  Loader2,
} from "lucide-react";
import type {
  AgentEvalRun,
  AgentEvalStatus,
  PydanticAgentRow,
} from "../../../types/agents";
import { SCHEDULE_PRESETS } from "./constants";

export function isUserAgent(row: PydanticAgentRow): boolean {
  return row.tags.includes("user") || row.agent_id.startsWith("user.");
}

/** Order-insensitive equality for string arrays. */
export function setsEqual(
  a: ReadonlyArray<string>,
  b: ReadonlyArray<string>,
): boolean {
  if (a.length !== b.length) return false;
  const seen = new Set(a);
  return b.every((x) => seen.has(x));
}

// ---------------------------------------------------------------------------
// Agent tree — parent_agent edges restricted to the current tab's rows.
// Rows whose parent isn't in the same tab are promoted to top-level.
// ---------------------------------------------------------------------------

export interface AgentTreeNode {
  readonly row: PydanticAgentRow;
  readonly depth: number;
  readonly children: ReadonlyArray<AgentTreeNode>;
}

export function buildAgentTree(
  rows: ReadonlyArray<PydanticAgentRow>,
): ReadonlyArray<AgentTreeNode> {
  const ids = new Set(rows.map((r) => r.agent_id));
  const byParent = new Map<string | null, PydanticAgentRow[]>();
  for (const r of rows) {
    const parent = r.parent_agent && ids.has(r.parent_agent)
      ? r.parent_agent
      : null;
    const arr = byParent.get(parent) ?? [];
    arr.push(r);
    byParent.set(parent, arr);
  }
  for (const arr of byParent.values()) {
    arr.sort((a, b) => a.name.localeCompare(b.name));
  }
  const build = (parent: string | null, depth: number): AgentTreeNode[] =>
    (byParent.get(parent) ?? []).map((row) => ({
      row,
      depth,
      children: build(row.agent_id, depth + 1),
    }));
  return build(null, 0);
}

/** Flatten a tree to a depth-annotated linear list for list rendering. */
export function flattenTree(
  nodes: ReadonlyArray<AgentTreeNode>,
): ReadonlyArray<AgentTreeNode> {
  const out: AgentTreeNode[] = [];
  const walk = (n: AgentTreeNode): void => {
    out.push(n);
    for (const c of n.children) walk(c);
  };
  for (const n of nodes) walk(n);
  return out;
}

// ---------------------------------------------------------------------------
// Eval status visuals
// ---------------------------------------------------------------------------

export function statusIcon(
  status: AgentEvalStatus | "loading" | "idle",
): JSX.Element {
  switch (status) {
    case "passed":
      return <CircleCheck size={12} className="text-success" />;
    case "failed":
      return <CircleX size={12} className="text-amber" />;
    case "error":
      return <CircleAlert size={12} className="text-amber" />;
    case "skipped":
      return <CircleDashed size={12} className="text-muted" />;
    case "idle":
      return <CircleDashed size={12} className="text-muted" />;
    case "running":
    case "pending":
    case "loading":
    default:
      return <Loader2 size={12} className="animate-spin text-muted" />;
  }
}

export function statusText(
  run: AgentEvalRun | null,
  polling: boolean,
  loading: boolean,
): string {
  if (polling || (run && (run.status === "running" || run.status === "pending"))) {
    return "Running evals…";
  }
  if (loading) return "Loading last result…";
  if (!run) return "No eval recorded yet";
  if (run.status === "passed") {
    const suffix = run.trigger === "auto" ? "Updated — " : "";
    return `${suffix}all ${run.cases_passed} evals passed`;
  }
  if (run.status === "failed") {
    const suffix = run.trigger === "auto" ? "Updated — " : "";
    return `${suffix}${run.cases_failed} of ${run.cases_total} evals failed`;
  }
  if (run.status === "skipped") {
    return run.error
      ? `Updated — eval skipped (${run.error})`
      : "Updated — eval skipped";
  }
  if (run.status === "error") {
    return `Eval errored — ${run.error ?? "see logs"}`;
  }
  return run.status;
}

export function statusToneClass(
  run: AgentEvalRun | null,
  polling: boolean,
  loading: boolean,
): string {
  if (
    polling ||
    loading ||
    !run ||
    run.status === "running" ||
    run.status === "pending"
  ) {
    return "border-hairline bg-surface text-muted";
  }
  if (run.status === "passed") {
    return "border-success/60 bg-success/10 text-success";
  }
  if (run.status === "failed" || run.status === "error") {
    return "border-amber/60 bg-amber/10 text-amber";
  }
  return "border-hairline bg-surface text-muted";
}

// ---------------------------------------------------------------------------
// Schedule + activity formatters
// ---------------------------------------------------------------------------

export function cronToLabel(cron: string | null | undefined): string {
  if (!cron) return "Custom";
  const preset = SCHEDULE_PRESETS.find((p) => p.cron === cron);
  return preset ? preset.label : cron;
}

export function formatRelative(
  iso: string | null | undefined,
  now: number,
): string {
  if (!iso) return "—";
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return "—";
  const deltaMs = t - now;
  const past = deltaMs < 0;
  const abs = Math.abs(deltaMs);
  const minutes = Math.round(abs / 60_000);
  if (minutes < 1) return past ? "just now" : "in <1m";
  if (minutes < 60) {
    return past ? `${minutes}m ago` : `in ${minutes}m`;
  }
  const hours = Math.floor(minutes / 60);
  const rem = minutes % 60;
  if (hours < 24) {
    const tail = rem === 0 ? "" : ` ${rem}m`;
    return past ? `${hours}h${tail} ago` : `in ${hours}h${tail}`;
  }
  const days = Math.floor(hours / 24);
  const hRem = hours % 24;
  const tail = hRem === 0 ? "" : ` ${hRem}h`;
  return past ? `${days}d${tail} ago` : `in ${days}d${tail}`;
}

export function formatRunTimestamp(ts: string): string {
  const d = new Date(ts);
  if (Number.isNaN(d.getTime())) return ts;
  return d.toLocaleString();
}

export function formatDurationMs(ms: number | null): string {
  if (ms == null) return "—";
  if (ms < 1000) return `${Math.round(ms)} ms`;
  return `${(ms / 1000).toFixed(2)} s`;
}

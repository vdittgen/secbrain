// Unified picker for a user agent's MCP-tool bindings.
//
// Each connector exposes three roles:
//
//   Sources  — data-typed catalog tools. The runner pulls items every
//              tick and fans out one LLM call per item.
//   Tools    — action-typed tools the LLM may call mid-run.
//   Delivery — action-typed tools the post-batch hook invokes once per
//              tick with an LLM-summarized digest. Hidden from the LLM
//              during per-item runs.
//
// The role explanations render ONCE at the top as a legend strip;
// per-connector cards collapse to a one-line summary by default and
// auto-expand when they hold any selection.
//
// sensitivity_tier: 1

import type { JSX, ReactNode } from "react";
import { useCallback, useMemo, useState } from "react";
import { ChevronRight } from "lucide-react";

import type { McpToolEntry } from "../../types/agents";

interface ConnectorBindingsProps {
  readonly availableTools: ReadonlyArray<McpToolEntry>;
  readonly enabledTools: ReadonlyArray<string>;
  readonly deliveryTools: ReadonlyArray<string>;
  readonly onChange: (next: {
    readonly enabledTools: ReadonlyArray<string>;
    readonly deliveryTools: ReadonlyArray<string>;
  }) => void;
}

interface ConnectorGroup {
  readonly connectorId: string;
  readonly connectorName: string;
  readonly dataTools: ReadonlyArray<McpToolEntry>;
  readonly actionTools: ReadonlyArray<McpToolEntry>;
}

function groupByConnector(
  tools: ReadonlyArray<McpToolEntry>,
): ReadonlyArray<ConnectorGroup> {
  const byId = new Map<string, {
    name: string;
    data: McpToolEntry[];
    action: McpToolEntry[];
  }>();
  for (const t of tools) {
    const entry = byId.get(t.connector_id) ?? {
      name: t.connector_name,
      data: [],
      action: [],
    };
    if (t.tool_type === "data") {
      entry.data.push(t);
    } else if (t.tool_type === "action") {
      entry.action.push(t);
    }
    byId.set(t.connector_id, entry);
  }
  return [...byId.entries()]
    .map(([id, v]) => ({
      connectorId: id,
      connectorName: v.name,
      dataTools: v.data,
      actionTools: v.action,
    }))
    .sort((a, b) => a.connectorName.localeCompare(b.connectorName));
}

function hasComplexSchema(tool: McpToolEntry): boolean {
  const schema = (tool.input_schema ?? {}) as Record<string, unknown>;
  const props = (schema.properties ?? {}) as Record<string, {
    type?: string;
  }>;
  const required = (schema.required ?? []) as ReadonlyArray<string>;
  if (required.length === 0) return false;
  const firstStringRequired = required.find(
    (k) => props[k]?.type === "string",
  );
  if (!firstStringRequired) return true;
  const nonStringRequired = required.filter(
    (k) => props[k]?.type !== "string",
  );
  return nonStringRequired.length > 0;
}

function RoleLegend(): JSX.Element {
  const rows: ReadonlyArray<{
    role: string;
    swatch: string;
    detail: string;
  }> = [
    {
      role: "Sources",
      swatch: "border-indigo bg-indigo-soft text-indigo",
      detail:
        "Pulled by the runner every scheduled tick (cursor managed automatically).",
    },
    {
      role: "Tools",
      swatch: "border-indigo bg-indigo-soft text-indigo",
      detail: "LLM-callable mid-run.",
    },
    {
      role: "Delivery",
      swatch: "border-amber bg-amber/10 text-amber",
      detail:
        "Post-batch hook receives an LLM-summarized digest. Hidden from the LLM during per-item runs.",
    },
  ];
  return (
    <div className="rounded-md border border-hairline bg-surface/40 p-2 text-[11px]">
      <div className="text-[10px] uppercase tracking-wide text-muted">
        How a connector's tools are wired
      </div>
      <ul className="mt-1 space-y-1">
        {rows.map((r) => (
          <li key={r.role} className="flex items-start gap-2">
            <span
              className={`mt-[1px] inline-block min-w-[60px] shrink-0 rounded-full border px-2 py-[1px] text-center text-[10px] ${r.swatch}`}
            >
              {r.role}
            </span>
            <span className="text-muted">{r.detail}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

interface ConnectorCardProps {
  readonly group: ConnectorGroup;
  readonly enabledSet: ReadonlySet<string>;
  readonly deliverySet: ReadonlySet<string>;
  readonly defaultOpen: boolean;
  readonly onToggleEnabled: (toolId: string) => void;
  readonly onToggleDelivery: (toolId: string) => void;
}

function ConnectorCard({
  group,
  enabledSet,
  deliverySet,
  defaultOpen,
  onToggleEnabled,
  onToggleDelivery,
}: ConnectorCardProps): JSX.Element {
  const [open, setOpen] = useState(defaultOpen);

  const sourceCount = group.dataTools.filter(
    (t) => enabledSet.has(`${t.connector_id}:${t.tool_name}`),
  ).length;
  const toolCount = group.actionTools.filter(
    (t) => enabledSet.has(`${t.connector_id}:${t.tool_name}`),
  ).length;
  const deliveryCount = group.actionTools.filter(
    (t) => deliverySet.has(`${t.connector_id}:${t.tool_name}`),
  ).length;
  const summaryParts: string[] = [];
  if (group.dataTools.length > 0) {
    summaryParts.push(`${sourceCount}/${group.dataTools.length} source${group.dataTools.length === 1 ? "" : "s"}`);
  }
  if (group.actionTools.length > 0) {
    summaryParts.push(`${toolCount}/${group.actionTools.length} tool${group.actionTools.length === 1 ? "" : "s"}`);
    summaryParts.push(`${deliveryCount}/${group.actionTools.length} delivery`);
  }
  const totalSelected = sourceCount + toolCount + deliveryCount;

  return (
    <div className="rounded-md border border-hairline bg-surface/30">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center justify-between gap-3 px-2 py-1.5 text-left hover:bg-surface/40"
      >
        <div className="flex items-center gap-2">
          <ChevronRight strokeWidth={1.6}
            size={12}
            className={`text-muted transition-transform ${open ? "rotate-90" : ""}`}
          />
          <span className="text-[12px] font-medium text-ink">
            {group.connectorName}
          </span>
          <span className="text-[10px] text-muted">
            ({group.connectorId})
          </span>
        </div>
        <span
          className={`text-[10px] ${
            totalSelected > 0 ? "text-ink/80" : "text-muted"
          }`}
        >
          {summaryParts.join(" · ")}
        </span>
      </button>
      {open && (
        <div className="space-y-2 border-t border-hairline/60 px-2 py-2">
          {group.dataTools.length > 0 && (
            <RoleRow label="Sources">
              {group.dataTools.map((t) => {
                const id = `${t.connector_id}:${t.tool_name}`;
                const on = enabledSet.has(id);
                return (
                  <Chip
                    key={id}
                    label={t.display_name}
                    title={t.description}
                    selected={on}
                    tone="accent"
                    onClick={() => onToggleEnabled(id)}
                  />
                );
              })}
            </RoleRow>
          )}
          {group.actionTools.length > 0 && (
            <RoleRow label="Tools">
              {group.actionTools.map((t) => {
                const id = `${t.connector_id}:${t.tool_name}`;
                const on = enabledSet.has(id);
                return (
                  <Chip
                    key={id}
                    label={t.display_name}
                    title={t.description}
                    selected={on}
                    tone="accent"
                    onClick={() => onToggleEnabled(id)}
                  />
                );
              })}
            </RoleRow>
          )}
          {group.actionTools.length > 0 && (
            <RoleRow label="Delivery">
              {group.actionTools.map((t) => {
                const id = `${t.connector_id}:${t.tool_name}`;
                const on = deliverySet.has(id);
                const complex = hasComplexSchema(t);
                return (
                  <Chip
                    key={`d-${id}`}
                    label={
                      complex ? `${t.display_name} ⚠` : t.display_name
                    }
                    title={
                      complex
                        ? `${t.description}\n\nNote: complex input schema; delivery may need a tool with a single string field.`
                        : t.description
                    }
                    selected={on}
                    tone="warning"
                    onClick={() => onToggleDelivery(id)}
                  />
                );
              })}
            </RoleRow>
          )}
        </div>
      )}
    </div>
  );
}

function RoleRow({
  label,
  children,
}: {
  readonly label: string;
  readonly children: ReactNode;
}): JSX.Element {
  return (
    <div className="flex flex-wrap items-start gap-1.5">
      <span className="mt-1 min-w-[60px] shrink-0 text-[10px] uppercase tracking-wide text-muted">
        {label}
      </span>
      <div className="flex flex-wrap gap-1">{children}</div>
    </div>
  );
}

function Chip({
  label,
  title,
  selected,
  tone,
  onClick,
}: {
  readonly label: string;
  readonly title: string;
  readonly selected: boolean;
  readonly tone: "accent" | "warning";
  readonly onClick: () => void;
}): JSX.Element {
  const selectedClass = tone === "warning"
    ? "border-amber bg-amber/10 text-amber"
    : "border-indigo bg-indigo-soft text-indigo";
  const base = "rounded-full border px-2 py-0.5 text-[11px]";
  const cls = selected ? selectedClass : "border-hairline text-muted";
  return (
    <button
      type="button"
      onClick={onClick}
      title={title}
      className={`${base} ${cls}`}
    >
      {label}
    </button>
  );
}

export function ConnectorBindings({
  availableTools,
  enabledTools,
  deliveryTools,
  onChange,
}: ConnectorBindingsProps): JSX.Element {
  const groups = useMemo(
    () => groupByConnector(availableTools),
    [availableTools],
  );
  const enabledSet = useMemo(() => new Set(enabledTools), [enabledTools]);
  const deliverySet = useMemo(() => new Set(deliveryTools), [deliveryTools]);

  const toggleEnabled = useCallback(
    (toolId: string) => {
      const next = new Set(enabledSet);
      if (next.has(toolId)) next.delete(toolId);
      else next.add(toolId);
      onChange({
        enabledTools: [...next],
        deliveryTools: [...deliverySet],
      });
    },
    [enabledSet, deliverySet, onChange],
  );

  const toggleDelivery = useCallback(
    (toolId: string) => {
      const next = new Set(deliverySet);
      if (next.has(toolId)) next.delete(toolId);
      else next.add(toolId);
      onChange({
        enabledTools: [...enabledSet],
        deliveryTools: [...next],
      });
    },
    [enabledSet, deliverySet, onChange],
  );

  if (groups.length === 0) {
    return (
      <span className="text-[11px] text-muted">
        No enabled connectors expose tools.
      </span>
    );
  }

  return (
    <div className="space-y-2">
      <RoleLegend />
      <div className="space-y-1.5">
        {groups.map((g) => {
          const groupIds = [
            ...g.dataTools.map((t) => `${t.connector_id}:${t.tool_name}`),
            ...g.actionTools.map((t) => `${t.connector_id}:${t.tool_name}`),
          ];
          const hasSelection = groupIds.some(
            (id) => enabledSet.has(id) || deliverySet.has(id),
          );
          return (
            <ConnectorCard
              key={g.connectorId}
              group={g}
              enabledSet={enabledSet}
              deliverySet={deliverySet}
              defaultOpen={hasSelection}
              onToggleEnabled={toggleEnabled}
              onToggleDelivery={toggleDelivery}
            />
          );
        })}
      </div>
    </div>
  );
}

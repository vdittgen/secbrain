// Agent architecture rendering. Exposes both a stand-alone modal and a
// reusable inline graph component (used by the Agents page's
// Architecture mode tab).
//
// sensitivity_tier: 1

import { useEffect, useId, useMemo, useState } from "react";
import { Loader2, X } from "lucide-react";
import mermaid from "mermaid";
import type { PydanticAgentRow } from "../types/agents";

let mermaidInitialized = false;
function ensureMermaidInitialized(): void {
  if (mermaidInitialized) return;
  mermaid.initialize({
    startOnLoad: false,
    securityLevel: "strict",
    theme: "dark",
    flowchart: { htmlLabels: true, useMaxWidth: true },
  });
  mermaidInitialized = true;
}

function escapeLabel(s: string): string {
  return s.replace(/"/g, "&quot;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

function buildDiagram(
  rootId: string,
  byId: ReadonlyMap<string, PydanticAgentRow>,
): string {
  const lines: string[] = ["flowchart TD"];
  const nodeIds = new Map<string, string>();
  let counter = 0;
  const nodeFor = (id: string): string => {
    const existing = nodeIds.get(id);
    if (existing) return existing;
    const fresh = `n${counter++}`;
    nodeIds.set(id, fresh);
    return fresh;
  };
  const visited = new Set<string>();
  const walk = (id: string): void => {
    if (visited.has(id)) return;
    visited.add(id);
    const agent = byId.get(id);
    const node = nodeFor(id);
    if (!agent) {
      lines.push(
        `  ${node}["${escapeLabel(id)}<br/><small>(unregistered)</small>"]:::missing`,
      );
      return;
    }
    const label =
      `${escapeLabel(agent.name)}<br/><small>${escapeLabel(id)}</small>`;
    const cls = agent.pattern === "orchestrator"
      ? "orchestrator"
      : agent.pattern === "deep"
        ? "deep"
        : "single";
    lines.push(`  ${node}["${label}"]:::${cls}`);
    for (const sub of agent.subagents) {
      const subNode = nodeFor(sub);
      lines.push(`  ${node} --> ${subNode}`);
      walk(sub);
    }
  };
  walk(rootId);
  lines.push(
    "classDef orchestrator fill:#1f6feb,stroke:#79c0ff,color:#ffffff;",
  );
  lines.push("classDef single fill:#21262d,stroke:#30363d,color:#c9d1d9;");
  lines.push("classDef deep fill:#6e40c9,stroke:#a371f7,color:#ffffff;");
  lines.push("classDef missing fill:#3a1c1c,stroke:#9b2226,color:#ffd6d6;");
  return lines.join("\n");
}

// ---------------------------------------------------------------------------
// AgentArchitectureGraph — the inline graph, reused by pane + modal.
// ---------------------------------------------------------------------------

interface AgentArchitectureGraphProps {
  readonly rootAgentId: string;
  readonly allAgents: ReadonlyArray<PydanticAgentRow>;
}

export function AgentArchitectureGraph({
  rootAgentId,
  allAgents,
}: AgentArchitectureGraphProps): JSX.Element {
  const renderId = useId().replace(/[^A-Za-z0-9_-]/g, "");
  const [svg, setSvg] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const diagram = useMemo(() => {
    const byId = new Map(allAgents.map((a) => [a.agent_id, a]));
    return buildDiagram(rootAgentId, byId);
  }, [allAgents, rootAgentId]);

  useEffect(() => {
    let active = true;
    setSvg(null);
    setError(null);
    ensureMermaidInitialized();
    mermaid
      .render(`agent-arch-${renderId}`, diagram)
      .then(({ svg: rendered }: { svg: string }) => {
        if (active) setSvg(rendered);
      })
      .catch((err: unknown) => {
        if (active) {
          setError(err instanceof Error ? err.message : String(err));
        }
      });
    return () => {
      active = false;
    };
  }, [diagram, renderId]);

  return (
    <div>
      {error
        ? (
          <div className="rounded-md border border-amber/60 bg-amber-soft px-3 py-2 text-[12px] text-amber">
            Couldn't render the diagram: {error}
          </div>
        )
        : svg
          ? (
            <div
              className="flex justify-center [&_svg]:max-w-full [&_svg]:h-auto"
              dangerouslySetInnerHTML={{ __html: svg }}
            />
          )
          : (
            <div className="flex items-center gap-2 text-[12px] text-muted">
              <Loader2 strokeWidth={1.6} size={12} className="animate-spin" />
              Rendering diagram…
            </div>
          )}
      <details className="mt-4 text-[11px] text-muted">
        <summary className="cursor-pointer hover:text-ink">
          Diagram source
        </summary>
        <pre className="mt-2 overflow-auto rounded-md border border-hairline bg-surface p-2 text-[10px] text-ink/80">
          {diagram}
        </pre>
      </details>
    </div>
  );
}

// ---------------------------------------------------------------------------
// AgentArchitectureModal — modal shell wrapping the graph. Kept for
// callers that still want a popup view.
// ---------------------------------------------------------------------------

interface AgentArchitectureModalProps {
  readonly rootAgentId: string;
  readonly allAgents: ReadonlyArray<PydanticAgentRow>;
  readonly onClose: () => void;
}

function AgentArchitectureModal({
  rootAgentId,
  allAgents,
  onClose,
}: AgentArchitectureModalProps): JSX.Element {
  const root = useMemo(
    () => allAgents.find((a) => a.agent_id === rootAgentId) ?? null,
    [allAgents, rootAgentId],
  );
  return (
    <div className="fixed inset-0 z-40 flex items-center justify-center bg-black/40 p-4">
      <div className="flex max-h-full w-full max-w-3xl flex-col rounded-4 border border-hairline bg-surface shadow-xl">
        <div className="flex items-center justify-between border-b border-hairline px-5 py-3">
          <div>
            <h2 className="text-base font-semibold text-ink">
              Architecture: {root?.name ?? rootAgentId}
            </h2>
            <p className="text-[11px] text-muted">
              Delegation graph rooted at{" "}
              <code className="text-ink">{rootAgentId}</code>.
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-md p-1 text-muted hover:bg-surface"
            aria-label="Close"
          >
            <X strokeWidth={1.6} size={14} />
          </button>
        </div>
        <div className="flex-1 overflow-auto p-5">
          <AgentArchitectureGraph
            rootAgentId={rootAgentId}
            allAgents={allAgents}
          />
        </div>
      </div>
    </div>
  );
}

export default AgentArchitectureModal;

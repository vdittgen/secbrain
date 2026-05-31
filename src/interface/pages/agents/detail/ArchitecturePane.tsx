// Architecture mode — orchestrator delegation graph rendered inline.
//
// sensitivity_tier: 1

import type { JSX } from "react";
import { AgentArchitectureGraph } from "../../../components/AgentArchitectureModal";
import type { PydanticAgentRow } from "../../../types/agents";

interface ArchitecturePaneProps {
  readonly row: PydanticAgentRow;
  readonly allAgents: ReadonlyArray<PydanticAgentRow>;
}

export function ArchitecturePane({
  row,
  allAgents,
}: ArchitecturePaneProps): JSX.Element {
  if (row.pattern !== "orchestrator" && row.pattern !== "deep") {
    return (
      <div className="rounded-md border border-hairline bg-surface/40 px-3 py-2 text-[12px] text-muted">
        This agent has no delegation graph — it's a single-pattern
        agent.
      </div>
    );
  }
  return (
    <section className="rounded-md border border-hairline bg-surface p-4">
      <div className="text-[11px] uppercase tracking-wide text-muted">
        Delegation graph
      </div>
      <p className="mt-1 text-[11px] text-muted">
        Edges show which sub-agents{" "}
        <code className="text-ink">{row.agent_id}</code>{" "}
        may pick from to assemble its answer.
      </p>
      <div className="mt-3">
        <AgentArchitectureGraph
          rootAgentId={row.agent_id}
          allAgents={allAgents}
        />
      </div>
    </section>
  );
}

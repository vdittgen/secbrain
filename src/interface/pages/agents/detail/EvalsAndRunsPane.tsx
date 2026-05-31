// Evals & runs mode — eval banner + Run-eval, dataset
// (editable iff user agent), recent-runs table.
//
// sensitivity_tier: 1

import type { JSX } from "react";
import { useCallback, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import type {
  AgentEvalRunResponse,
  PydanticAgentRow,
} from "../../../types/agents";
import { useAgentEval } from "../hooks/useAgentEval";
import { AgentActivityPanel } from "../shared/AgentActivityPanel";
import { EvalDatasetPanel } from "../shared/EvalDatasetPanel";
import { EvalStatusBanner } from "../shared/EvalStatusBanner";
import { isUserAgent } from "../shared/utils";

interface EvalsAndRunsPaneProps {
  readonly row: PydanticAgentRow;
  readonly refreshKey: number;
  readonly onChanged: () => void;
}

export function EvalsAndRunsPane({
  row,
  refreshKey,
  onChanged,
}: EvalsAndRunsPaneProps): JSX.Element {
  const evalStatus = useAgentEval(row.agent_id, refreshKey);
  const [running, setRunning] = useState(false);
  const [runError, setRunError] = useState<string | null>(null);

  const runEval = useCallback(async () => {
    setRunError(null);
    setRunning(true);
    try {
      await invoke<AgentEvalRunResponse>("run_agent_eval", {
        agentId: row.agent_id,
      });
      onChanged();
    } catch (e: unknown) {
      setRunError(e instanceof Error ? e.message : String(e));
    } finally {
      setRunning(false);
      await evalStatus.refresh();
    }
  }, [row.agent_id, evalStatus, onChanged]);

  return (
    <div className="space-y-3">
      <EvalStatusBanner
        run={evalStatus.run}
        polling={evalStatus.polling || running}
        loading={evalStatus.loading}
        canRunNow
        onRunNow={runEval}
      />
      {runError && (
        <div className="rounded-md border border-amber/60 bg-amber/10 px-3 py-2 text-[11px] text-amber">
          Run eval failed: {runError}
        </div>
      )}
      <section className="rounded-md border border-hairline bg-surface p-3">
        <div className="text-[11px] uppercase tracking-wide text-muted">
          Eval dataset
        </div>
        <div className="mt-2">
          <EvalDatasetPanel
            agentId={row.agent_id}
            editable={isUserAgent(row)}
          />
        </div>
      </section>
      <section className="rounded-md border border-hairline bg-surface p-3">
        <div className="text-[11px] uppercase tracking-wide text-muted">
          Recent runs
        </div>
        <div className="mt-2">
          <AgentActivityPanel
            agentId={row.agent_id}
            refreshKey={refreshKey}
          />
        </div>
      </section>
    </div>
  );
}

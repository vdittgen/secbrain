// Overview mode — read-only summary of one agent. Common to user,
// built-in, and locked rows.
//
// sensitivity_tier: 1

import type { JSX } from "react";
import { Bot, Lock, Zap } from "lucide-react";
import type { PydanticAgentRow } from "../../../types/agents";
import { useAgentEval } from "../hooks/useAgentEval";
import { EvalStatusBanner } from "../shared/EvalStatusBanner";
import { ScheduleStrip } from "../shared/ScheduleStrip";
import { TIER_DOT, TIER_LABELS } from "../shared/constants";
import { isUserAgent } from "../shared/utils";
import { LockedAgentModelEditor } from "./LockedAgentModelEditor";

interface OverviewPaneProps {
  readonly row: PydanticAgentRow;
  readonly refreshKey: number;
  readonly onChanged: () => void;
}

export function OverviewPane({
  row,
  refreshKey,
  onChanged,
}: OverviewPaneProps): JSX.Element {
  const evalStatus = useAgentEval(row.agent_id, refreshKey);
  const showSchedule = isUserAgent(row);
  const tools = row.available_tools;
  const skills = row.available_skills;

  return (
    <div className="space-y-3">
      <section className="rounded-md border border-hairline bg-surface p-3">
        <div className="flex items-start gap-2">
          <Bot size={16} className="mt-1 text-indigo" />
          <div className="flex-1">
            <div className="flex items-center gap-2">
              <h3 className="text-[14px] font-medium text-ink">
                {row.name}
              </h3>
              {!row.editable && (
                <span className="inline-flex items-center gap-1 rounded-full border border-hairline px-2 py-0.5 text-[10px] text-muted">
                  <Lock size={9} /> locked
                </span>
              )}
              <span className="inline-flex items-center gap-1 text-[10px] text-muted">
                <span
                  className={`h-1.5 w-1.5 rounded-full ${TIER_DOT[row.tier]}`}
                />
                {TIER_LABELS[row.tier]}
              </span>
              <span className="font-mono text-[10px] text-muted">
                {row.agent_id}
              </span>
            </div>
            <p className="mt-1 text-[12px] text-muted">
              {row.description || "—"}
            </p>
          </div>
        </div>
        <div className="mt-3 grid grid-cols-1 gap-3 text-[11px] sm:grid-cols-2">
          <Cell label="Pattern" value={row.pattern} />
          <Cell label="Output schema" value={row.output_schema || "—"} mono />
          <Cell
            label="Model"
            value={row.config.resolved_model ?? "default"}
            mono
          />
          <Cell label="Route" value={row.config.model_route} />
          <Cell label="Max sensitivity" value={`tier ${row.max_sensitivity_tier}`} />
          <Cell label="Version" value={`v${row.config.version}`} />
        </div>
        {!row.editable && (
          <div className="mt-3">
            <LockedAgentModelEditor row={row} onSaved={onChanged} />
          </div>
        )}
      </section>

      <EvalStatusBanner
        run={evalStatus.run}
        polling={evalStatus.polling}
        loading={evalStatus.loading}
      />

      {showSchedule && (
        <ScheduleStrip agentId={row.agent_id} refreshKey={refreshKey} />
      )}

      {(tools.length > 0 || skills.length > 0) && (
        <section className="rounded-md border border-hairline bg-surface p-3">
          <div className="text-[11px] uppercase tracking-wide text-muted">
            Capabilities
          </div>
          {tools.length > 0 && (
            <div className="mt-2">
              <div className="text-[11px] text-muted">Tools</div>
              <div className="mt-1 flex flex-wrap gap-1">
                {tools.map((t) => (
                  <span
                    key={t}
                    className="rounded-full border border-hairline px-2 py-0.5 text-[10px] text-ink/80"
                  >
                    {t}
                  </span>
                ))}
              </div>
            </div>
          )}
          {skills.length > 0 && (
            <div className="mt-2">
              <div className="text-[11px] text-muted">Skills</div>
              <div className="mt-1 flex flex-wrap gap-1">
                {skills.map((s) => (
                  <span
                    key={s}
                    className="inline-flex items-center gap-1 rounded-full border border-hairline px-2 py-0.5 text-[10px] text-ink/80"
                  >
                    <Zap className="h-2.5 w-2.5" />
                    {s}
                  </span>
                ))}
              </div>
              {(row.agent_id === "brain" || row.agent_id === "chat") && (
                <p className="mt-1.5 text-[10px] text-muted">
                  All installed skills are auto-available via progressive disclosure.
                </p>
              )}
            </div>
          )}
        </section>
      )}

      <section className="rounded-md border border-hairline bg-surface p-3">
        <div className="text-[11px] uppercase tracking-wide text-muted">
          System prompt
        </div>
        <div
          className="mt-2 max-h-72 overflow-auto rounded-3 p-4"
          style={{
            background: "var(--ink)",
            color: "oklch(0.94 0.005 245)",
          }}
        >
          <pre className="whitespace-pre-wrap font-mono text-[12.5px] leading-[1.7]">
            {row.config.system_prompt || "(empty)"}
          </pre>
        </div>
      </section>
    </div>
  );
}

function Cell({
  label,
  value,
  mono,
}: {
  readonly label: string;
  readonly value: string;
  readonly mono?: boolean;
}): JSX.Element {
  return (
    <div>
      <div className="text-[10px] uppercase tracking-wide text-muted">
        {label}
      </div>
      <div
        className={`mt-0.5 text-[12px] text-ink ${mono ? "font-mono" : ""}`}
      >
        {value}
      </div>
    </div>
  );
}

// Eval-status pill with optional "Run eval" action + failed-case
// drawer. Lifted verbatim from the legacy Agents.tsx implementation.
//
// sensitivity_tier: 1

import type { JSX } from "react";
import { useState } from "react";
import { ChevronDown, ChevronRight, Play } from "lucide-react";
import type {
  AgentEvalRun,
  AgentEvalStatus,
} from "../../../types/agents";
import { statusIcon, statusText, statusToneClass } from "./utils";

interface EvalStatusBannerProps {
  readonly run: AgentEvalRun | null;
  readonly polling: boolean;
  readonly loading: boolean;
  readonly onRunNow?: () => void;
  readonly canRunNow?: boolean;
}

export function EvalStatusBanner({
  run,
  polling,
  loading,
  onRunNow,
  canRunNow,
}: EvalStatusBannerProps): JSX.Element {
  const [open, setOpen] = useState(false);
  const showDetails = run && run.failed_cases.length > 0;
  const tone = statusToneClass(run, polling, loading);
  const icon: AgentEvalStatus | "loading" | "idle" =
    polling || (loading && !run)
      ? "loading"
      : (run?.status ?? "idle");
  return (
    <div className={`rounded-md border px-3 py-2 text-[12px] ${tone}`}>
      <div className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          {statusIcon(icon)}
          <span>{statusText(run, polling, loading)}</span>
          {run?.suite && (
            <span className="text-[11px] text-muted">({run.suite})</span>
          )}
        </div>
        <div className="flex items-center gap-2">
          {showDetails && (
            <button
              type="button"
              onClick={() => setOpen((v) => !v)}
              className="inline-flex items-center gap-1 rounded-md border border-hairline px-2 py-1 text-[11px] text-ink/90 hover:bg-surface"
            >
              {open
                ? (
                  <>
                    <ChevronDown size={10} /> Hide details
                  </>
                )
                : (
                  <>
                    <ChevronRight size={10} /> View details
                  </>
                )}
            </button>
          )}
          {canRunNow && onRunNow && (
            <button
              type="button"
              onClick={onRunNow}
              disabled={polling}
              className="inline-flex items-center gap-1 rounded-md border border-hairline px-2 py-1 text-[11px] text-ink/90 hover:bg-surface disabled:opacity-50"
            >
              <Play size={10} /> Run eval
            </button>
          )}
        </div>
      </div>
      {open && showDetails && run && (
        <div className="mt-2 space-y-1 border-t border-hairline/40 pt-2">
          {run.failed_cases.map((fc, i) => (
            <div
              key={`${fc.case}-${fc.evaluator}-${i}`}
              className="rounded-md bg-surface/60 p-2"
            >
              <div className="font-mono text-[11px] text-ink">
                {fc.case}
                <span className="ml-2 text-muted">[{fc.evaluator}]</span>
              </div>
              <div className="mt-1 text-[11px] text-muted">{fc.reason}</div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

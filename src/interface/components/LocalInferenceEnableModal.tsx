/**
 * Eval-gated enable flow for the local-inference privacy mode.
 *
 * In Arandu every prompt is already local — the toggle still
 * exists so the eval suite runs against the user's configured Ollama
 * model. The flag persists only when each suite returns
 * ``status="passed"``; otherwise the toggle snaps back to OFF and
 * the failed-case list is rendered inline so the user can see
 * what's missing before swapping models.
 *
 * Phases:
 * - ``confirm`` — warning + explanation, "Run evals & enable" CTA.
 * - ``running`` — spinner with the count of agent suites scheduled.
 * - ``failed``  — list of agents whose eval did not pass; "Try a
 *                 different local model" leads to the AI Model
 *                 section.
 * - ``done``    — passed-everywhere confirmation; closes the modal.
 *
 * sensitivity_tier: 1 (operational metadata only)
 */

import { useCallback, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import {
  AlertTriangle,
  Check,
  Cpu,
  Loader2,
  ShieldCheck,
  X,
} from "lucide-react";
import type {
  LocalInferenceEvalFailure,
  LocalInferenceToggleResponse,
} from "../types/agents";

type Phase = "confirm" | "running" | "failed" | "done";

interface LocalInferenceEnableModalProps {
  /**
   * Called when the toggle finally commits (status="ok"). The parent
   * uses this to refetch settings so the toggle reflects the new
   * server state.
   */
  readonly onCommitted: () => void;
  readonly onClose: () => void;
  /**
   * Called when the user clicks "Try a different local model".
   * Parent typically scrolls the page to the AI Model section.
   */
  readonly onPickLocalModel?: () => void;
}

export default function LocalInferenceEnableModal({
  onCommitted,
  onClose,
  onPickLocalModel,
}: LocalInferenceEnableModalProps) {
  const [phase, setPhase] = useState<Phase>("confirm");
  const [failures, setFailures] = useState<
    ReadonlyArray<LocalInferenceEvalFailure>
  >([]);
  const [error, setError] = useState<string | null>(null);

  const runEvals = useCallback(async () => {
    setPhase("running");
    setError(null);
    try {
      const resp = await invoke<LocalInferenceToggleResponse>(
        "set_local_inference_for_sensitive",
        { enabled: true },
      );
      if (resp.status === "ok") {
        setPhase("done");
        onCommitted();
        return;
      }
      setFailures(resp.failures ?? []);
      setPhase("failed");
    } catch (e) {
      setError(String(e));
      setPhase("failed");
    }
  }, [onCommitted]);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4">
      <div className="w-full max-w-2xl rounded-4 border border-hairline bg-surface shadow-xl">
        <div className="flex items-center justify-between border-b border-hairline px-5 py-3">
          <div className="flex items-center gap-2">
            <ShieldCheck strokeWidth={1.6} className="h-4 w-4 text-indigo" />
            <h3 className="text-sm font-semibold text-ink">
              Run sensitive prompts locally
            </h3>
          </div>
          <button
            onClick={onClose}
            disabled={phase === "running"}
            className="rounded p-1 text-muted hover:bg-surface"
          >
            <X strokeWidth={1.6} className="h-4 w-4" />
          </button>
        </div>

        {phase === "confirm" && (
          <div className="space-y-4 px-5 py-5 text-sm text-ink">
            <p>
              Flipping this on means every agent in Arandu will run
              entirely on your machine. Before we commit the change we
              run each agent's eval suite against your currently
              configured local model.
            </p>
            <div className="rounded-2 border border-amber/40 bg-amber-soft p-3 text-xs text-amber">
              <div className="flex items-start gap-2">
                <AlertTriangle strokeWidth={1.6} className="mt-0.5 h-3.5 w-3.5" />
                <div>
                  <p className="font-medium">
                    Your local model must pass every agent's eval suite.
                  </p>
                  <p className="mt-1 text-amber/80">
                    If any agent fails, this stays off and you'll see
                    the failures below. You can pick a stronger local
                    model and try again. Your data never leaves your
                    machine either way — this toggle only confirms your
                    local model is strong enough for every agent.
                  </p>
                </div>
              </div>
            </div>
            <div className="flex justify-end gap-2 pt-2">
              <button
                onClick={onClose}
                className="rounded-2 border border-hairline px-3 py-1.5 text-xs text-ink hover:bg-surface"
              >
                Cancel
              </button>
              <button
                onClick={runEvals}
                className="rounded-2 bg-indigo px-3 py-1.5 text-xs font-medium text-white hover:opacity-90"
              >
                Run evals &amp; enable
              </button>
            </div>
          </div>
        )}

        {phase === "running" && (
          <div className="flex flex-col items-center gap-3 px-5 py-10 text-sm text-muted">
            <Loader2 strokeWidth={1.6} className="h-5 w-5 animate-spin text-indigo" />
            <p>Running agent eval suites against your local model…</p>
            <p className="text-xs">
              This typically takes a few minutes. Leave the window open.
            </p>
          </div>
        )}

        {phase === "failed" && (
          <div className="space-y-3 px-5 py-5 text-sm text-ink">
            <div className="rounded-2 border border-danger/40 bg-danger/10 p-3 text-xs text-danger">
              <div className="flex items-start gap-2">
                <AlertTriangle strokeWidth={1.6} className="mt-0.5 h-3.5 w-3.5" />
                <p>
                  Local-only mode wasn't enabled — at least one agent's
                  eval did not pass on the current local model.
                </p>
              </div>
            </div>
            {error && (
              <p className="text-xs text-danger">{error}</p>
            )}
            {failures.length > 0 && (
              <div className="max-h-72 overflow-auto rounded-2 border border-hairline">
                <table className="w-full text-xs">
                  <thead className="bg-surface text-muted">
                    <tr>
                      <th className="px-3 py-2 text-left">Agent</th>
                      <th className="px-3 py-2 text-left">Status</th>
                      <th className="px-3 py-2 text-left">Failed cases</th>
                    </tr>
                  </thead>
                  <tbody>
                    {failures.map((f) => (
                      <tr
                        key={f.agent_id}
                        className="border-t border-hairline align-top"
                      >
                        <td className="px-3 py-2 font-mono text-[11px] text-ink">
                          {f.agent_id}
                        </td>
                        <td className="px-3 py-2 text-muted">
                          {f.status}
                        </td>
                        <td className="px-3 py-2 text-muted">
                          {(f.failed_cases ?? [])
                            .map((c) => c.case ?? "")
                            .filter(Boolean)
                            .slice(0, 4)
                            .join(", ") || f.error || "—"}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
            <div className="flex justify-end gap-2 pt-2">
              <button
                onClick={onClose}
                className="rounded-2 border border-hairline px-3 py-1.5 text-xs text-ink hover:bg-surface"
              >
                Close
              </button>
              {onPickLocalModel && (
                <button
                  onClick={onPickLocalModel}
                  className="flex items-center gap-2 rounded-2 bg-indigo px-3 py-1.5 text-xs font-medium text-white hover:opacity-90"
                >
                  <Cpu strokeWidth={1.6} className="h-3.5 w-3.5" />
                  Try a different local model
                </button>
              )}
            </div>
          </div>
        )}

        {phase === "done" && (
          <div className="flex flex-col items-center gap-3 px-5 py-10 text-sm text-ink">
            <Check strokeWidth={1.6} className="h-6 w-6 text-emerald-400" />
            <p>Local-only mode is on.</p>
            <p className="text-xs text-muted">
              Every agent passed its eval suite against your local
              model. Prompts will no longer leave your machine.
            </p>
            <button
              onClick={onClose}
              className="mt-2 rounded-2 bg-indigo px-3 py-1.5 text-xs font-medium text-white hover:opacity-90"
            >
              Done
            </button>
          </div>
        )}
      </div>
    </div>
  );
}

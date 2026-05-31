/**
 * Eval-gated model override save flow with iterative re-suggestion.
 *
 * Phases:
 *
 * 1. **confirm** — explains the policy ("eval suite will run against
 *    the proposed model; the change is saved only if every case
 *    passes") and reports the agent's dataset size when known.
 *    Surfaces a warning when the agent has no dataset (the proposal
 *    won't validate anything; click-through is still allowed).
 *
 * 2. **running** — spinner + "Running N-case eval against `<model>`…".
 *    The underlying Tauri command is synchronous and blocks for the
 *    eval duration; React state stays in this branch while we await.
 *
 * 3. **result** — pass / fail / skipped branches. On pass we persist
 *    the override (and route, if changed) and resolve. On fail we
 *    render the failed case list inline and — when a ``pickerSpec``
 *    was provided — offer "Suggest a different model" that feeds the
 *    failure back into the Model Picker so the next round avoids the
 *    same capability gap. Picks apply in place; the user can re-test
 *    without leaving the modal.
 *
 * 4. **suggesting** — picker IPC in flight. Brief spinner state
 *    overlaid on the result panel so the user keeps the context.
 *
 * sensitivity_tier: 1 (operational metadata only)
 */

import { useCallback, useEffect, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import {
  AlertTriangle,
  Check,
  Loader2,
  ShieldCheck,
  Sparkles,
  X,
} from "lucide-react";
import type {
  AgentEvalProposalResponse,
  AgentEvalRun,
  ModelOption,
  ModelPickerPriorAttempt,
  ModelPickerSpec,
  ModelRecommendation,
  ModelRecommendationResponse,
  ModelRoute,
} from "../types/agents";

type Phase = "confirm" | "running" | "result" | "suggesting";

interface Proposal {
  readonly override: string | null;
  readonly route?: ModelRoute;
}

interface ModelChangeEvalModalProps {
  readonly agentId: string;
  readonly agentName: string;
  readonly proposedOverride: string | null;
  readonly proposedRoute?: ModelRoute;
  readonly currentOverride: string | null;
  readonly hasDataset: boolean;
  readonly datasetCaseCount: number | null;
  /**
   * Called when the eval passes (or when the agent has no dataset and
   * the user clicks through). Receives the FINAL choice — these may
   * differ from the props if the user iterated via re-suggestion.
   * Returning a rejected promise surfaces the error in the modal.
   */
  readonly onConfirmed: (
    override: string | null,
    route?: ModelRoute,
  ) => Promise<void>;
  readonly onClose: () => void;
  /**
   * Optional: when set, "Suggest a different model" appears on the
   * result panel after a failed eval. Click feeds the just-failed
   * model id + failed cases into the picker so the next round
   * targets the right capability gap.
   */
  readonly pickerSpec?: ModelPickerSpec;
}

export default function ModelChangeEvalModal({
  agentId,
  agentName,
  proposedOverride,
  proposedRoute,
  currentOverride,
  hasDataset,
  datasetCaseCount,
  onConfirmed,
  onClose,
  pickerSpec,
}: ModelChangeEvalModalProps) {
  const [phase, setPhase] = useState<Phase>("confirm");
  const [run, setRun] = useState<AgentEvalRun | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [proposal, setProposal] = useState<Proposal>({
    override: proposedOverride,
    route: proposedRoute,
  });
  const [attempts, setAttempts] = useState<ModelPickerPriorAttempt[]>([]);
  const [suggestion, setSuggestion] = useState<ModelRecommendation | null>(
    null,
  );
  const [suggestError, setSuggestError] = useState<string | null>(null);

  const excludedModels = attempts
    .map((a) => a.model_id)
    .filter((m): m is string => Boolean(m));

  // Close on Escape while idle; while running / suggesting the close
  // button is disabled so we don't strand a Python subprocess.
  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if (
        e.key === "Escape"
        && phase !== "running"
        && phase !== "suggesting"
      ) {
        onClose();
      }
    };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [onClose, phase]);

  const labelProposed = proposal.override ?? "(use route default)";
  const labelCurrent = currentOverride ?? "(use route default)";

  const runEval = useCallback(async () => {
    setError(null);
    setRun(null);
    setSuggestion(null);
    setSuggestError(null);
    setPhase("running");

    if (!hasDataset || !proposal.override) {
      // No dataset → skip the eval but still persist. Empty override
      // also bypasses: clearing the override falls back to the route
      // default and doesn't need a fresh probe.
      try {
        await onConfirmed(proposal.override, proposal.route);
        onClose();
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
        setPhase("confirm");
      }
      return;
    }

    try {
      const response = await invoke<AgentEvalProposalResponse>(
        "run_agent_eval_proposal",
        { agentId, proposedOverride: proposal.override },
      );
      setRun(response.run);
      setPhase("result");
      if (response.run.status === "passed") {
        try {
          await onConfirmed(proposal.override, proposal.route);
        } catch (e) {
          setError(
            e instanceof Error
              ? `Eval passed but save failed: ${e.message}`
              : "Eval passed but save failed",
          );
        }
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setPhase("confirm");
    }
  }, [agentId, hasDataset, onClose, onConfirmed, proposal]);

  const requestSuggestion = useCallback(async () => {
    if (!pickerSpec || !run) return;
    setSuggestError(null);
    setSuggestion(null);
    setPhase("suggesting");

    // Snapshot the just-failed attempt before firing the picker —
    // the picker uses it to reason about which capability gap to
    // close on the next round.
    const failed: ModelPickerPriorAttempt | null = proposal.override
      ? {
          model_id: proposal.override,
          route: proposal.route ?? "remote",
          failed_cases: run.failed_cases.map((fc) => ({
            name: fc.case,
            evaluator: fc.evaluator,
            reason: fc.reason,
          })),
        }
      : null;
    const nextAttempts = failed ? [...attempts, failed] : attempts;
    const nextExcluded = failed
      ? [...excludedModels, failed.model_id]
      : excludedModels;
    if (failed) {
      setAttempts(nextAttempts);
    }

    try {
      const response = await invoke<ModelRecommendationResponse>(
        "suggest_agent_model",
        {
          spec: {
            ...pickerSpec,
            excluded_models: nextExcluded,
            prior_attempts: nextAttempts,
          },
        },
      );
      setSuggestion(response.recommendation);
      setPhase("result");
    } catch (e) {
      setSuggestError(e instanceof Error ? e.message : String(e));
      setPhase("result");
    }
  }, [pickerSpec, run, proposal, attempts, excludedModels]);

  const applySuggestion = useCallback((option: ModelOption) => {
    setProposal({ override: option.model_id, route: option.route });
    setSuggestion(null);
    setError(null);
    setRun(null);
    setPhase("confirm");
  }, []);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
      <div className="w-full max-w-lg rounded-4 border border-hairline bg-surface p-5 shadow-2xl">
        <div className="mb-4 flex items-start justify-between gap-3">
          <div className="flex items-center gap-2">
            <ShieldCheck strokeWidth={1.6} className="h-4 w-4 text-indigo" />
            <h2 className="text-sm font-semibold text-ink">
              Confirm model change
            </h2>
          </div>
          <button
            type="button"
            onClick={onClose}
            disabled={phase === "running" || phase === "suggesting"}
            aria-label="Close"
            className="rounded p-1 text-muted hover:text-ink disabled:opacity-40"
          >
            <X strokeWidth={1.6} size={14} />
          </button>
        </div>

        <div className="mb-4 space-y-1 rounded-md border border-hairline bg-surface/40 p-3 text-[12px]">
          <Row label="Agent" value={agentName} />
          <Row label="Current model" value={labelCurrent} mono />
          <Row label="Proposed model" value={labelProposed} mono accent />
          {proposal.route && proposedRoute !== proposal.route && (
            <Row
              label="Proposed route"
              value={proposal.route}
              mono
              accent
            />
          )}
        </div>

        {attempts.length > 0 && (
          <TestedAttempts attempts={attempts} />
        )}

        {phase === "confirm" && (
          <ConfirmPanel
            hasDataset={hasDataset}
            datasetCaseCount={datasetCaseCount}
            error={error}
            isReSuggested={attempts.length > 0}
            onCancel={onClose}
            onRun={runEval}
          />
        )}

        {phase === "running" && (
          <RunningPanel
            label={labelProposed}
            caseCount={datasetCaseCount}
          />
        )}

        {phase === "result" && run !== null && (
          <ResultPanel
            run={run}
            error={error}
            suggestion={suggestion}
            suggestError={suggestError}
            canReSuggest={Boolean(pickerSpec)}
            onClose={onClose}
            onRetry={() => setPhase("confirm")}
            onReSuggest={requestSuggestion}
            onUseSuggestion={applySuggestion}
          />
        )}

        {phase === "suggesting" && (
          <SuggestingPanel />
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Row helper
// ---------------------------------------------------------------------------

function Row({
  label,
  value,
  mono,
  accent,
}: {
  readonly label: string;
  readonly value: string;
  readonly mono?: boolean;
  readonly accent?: boolean;
}) {
  return (
    <div className="flex items-baseline justify-between gap-2">
      <span className="text-muted">{label}</span>
      <span
        className={`${mono ? "font-mono" : ""} ${
          accent ? "text-indigo" : "text-ink"
        } truncate`}
        title={value}
      >
        {value}
      </span>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Tested-attempts summary
// ---------------------------------------------------------------------------

function TestedAttempts({
  attempts,
}: {
  readonly attempts: ReadonlyArray<ModelPickerPriorAttempt>;
}) {
  return (
    <div className="mb-3 rounded-md border border-hairline/60 bg-surface/30 p-2 text-[11px] text-muted">
      <div className="font-medium text-ink/80">
        Already tested ({attempts.length})
      </div>
      <ul className="mt-1 space-y-0.5">
        {attempts.map((a) => (
          <li key={a.model_id} className="flex items-center gap-2">
            <span className="font-mono text-ink/80">{a.model_id}</span>
            <span className="rounded-full border border-hairline px-1.5 py-px text-[10px]">
              {a.route}
            </span>
            <span className="text-muted/80">
              {a.failed_cases.length} failure
              {a.failed_cases.length === 1 ? "" : "s"}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Confirm panel
// ---------------------------------------------------------------------------

function ConfirmPanel({
  hasDataset,
  datasetCaseCount,
  error,
  isReSuggested,
  onCancel,
  onRun,
}: {
  readonly hasDataset: boolean;
  readonly datasetCaseCount: number | null;
  readonly error: string | null;
  readonly isReSuggested: boolean;
  readonly onCancel: () => void;
  readonly onRun: () => void;
}) {
  return (
    <>
      {isReSuggested && (
        <div className="mb-3 rounded-md border border-indigo/40 bg-indigo-soft p-2 text-[11px] text-indigo">
          New model picked from the suggestions — run the eval against
          it to verify it closes the prior gaps.
        </div>
      )}
      {hasDataset
        ? (
          <p className="mb-3 text-[12px] text-ink/80">
            The proposed model will be evaluated against this agent's
            eval suite
            {datasetCaseCount !== null && (
              <>
                {" "}
                (<span className="font-mono">{datasetCaseCount}</span>{" "}
                case
                {datasetCaseCount === 1 ? "" : "s"})
              </>
            )}
            . The override is saved <strong>only</strong> if every case
            passes. Eval calls hit the proposed model and incur real
            provider spend.
          </p>
        )
        : (
          <div className="mb-3 rounded-md border border-amber/40 bg-amber-soft p-3 text-[12px] text-amber">
            <div className="mb-1 flex items-center gap-2 font-medium">
              <AlertTriangle strokeWidth={1.6} size={12} />
              No eval dataset for this agent
            </div>
            <p className="text-amber/80">
              The change will be saved without validation. We strongly
              recommend adding a dataset first so future model changes
              are gated by a measurable contract.
            </p>
          </div>
        )}

      {error && (
        <div className="mb-3 rounded-md border border-amber/60 bg-amber-soft px-2 py-1.5 text-[11px] text-amber">
          {error}
        </div>
      )}

      <div className="flex items-center justify-end gap-2">
        <button
          type="button"
          onClick={onCancel}
          className="rounded-md border border-hairline px-3 py-1.5 text-[12px] text-ink hover:bg-surface"
        >
          Cancel
        </button>
        <button
          type="button"
          onClick={onRun}
          className="inline-flex items-center gap-1.5 rounded-md bg-indigo px-3 py-1.5 text-[12px] text-white hover:bg-indigo/90"
        >
          {hasDataset ? "Run evals & save" : "Save anyway"}
        </button>
      </div>
    </>
  );
}

// ---------------------------------------------------------------------------
// Running panel
// ---------------------------------------------------------------------------

function RunningPanel({
  label,
  caseCount,
}: {
  readonly label: string;
  readonly caseCount: number | null;
}) {
  return (
    <div className="flex flex-col items-center justify-center gap-3 py-6 text-center text-[12px] text-ink/80">
      <Loader2 strokeWidth={1.6} className="h-6 w-6 animate-spin text-indigo" />
      <div>
        Running
        {caseCount !== null && (
          <>
            {" "}
            <span className="font-mono">{caseCount}</span> case
            {caseCount === 1 ? "" : "s"}
          </>
        )}{" "}
        against
        <div className="mt-1 font-mono text-ink" title={label}>
          {label}
        </div>
      </div>
      <p className="text-[11px] text-muted">
        This may take a moment.
      </p>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Suggesting panel (picker IPC in flight)
// ---------------------------------------------------------------------------

function SuggestingPanel() {
  return (
    <div className="flex flex-col items-center justify-center gap-3 py-6 text-center text-[12px] text-ink/80">
      <Loader2 strokeWidth={1.6} className="h-6 w-6 animate-spin text-indigo" />
      <div>Picking a different model based on the failed cases…</div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Result panel — failed cases + re-suggestion controls
// ---------------------------------------------------------------------------

function ResultPanel({
  run,
  error,
  suggestion,
  suggestError,
  canReSuggest,
  onClose,
  onRetry,
  onReSuggest,
  onUseSuggestion,
}: {
  readonly run: AgentEvalRun;
  readonly error: string | null;
  readonly suggestion: ModelRecommendation | null;
  readonly suggestError: string | null;
  readonly canReSuggest: boolean;
  readonly onClose: () => void;
  readonly onRetry: () => void;
  readonly onReSuggest: () => void;
  readonly onUseSuggestion: (option: ModelOption) => void;
}) {
  const passed = run.status === "passed";
  const failed = run.status === "failed";
  const skipped = run.status === "skipped";
  const errored = run.status === "error";

  return (
    <>
      <div
        className={`mb-3 rounded-md border p-3 text-[12px] ${
          passed
            ? "border-success/40 bg-success-soft text-success"
            : failed
              ? "border-danger/40 bg-danger/10 text-danger"
              : "border-hairline bg-surface/40 text-ink/80"
        }`}
      >
        <div className="mb-1 flex items-center gap-2 font-medium">
          {passed ? <Check strokeWidth={1.6} size={12} /> : <AlertTriangle strokeWidth={1.6} size={12} />}
          {passed && "All cases passed — override saved"}
          {failed
            && `${run.cases_failed} of ${run.cases_total} cases failed — override NOT saved`}
          {skipped && "Eval skipped"}
          {errored && "Eval errored"}
        </div>
        {!passed && (
          <p className="text-[11px] opacity-80">
            {run.error
              || (skipped
                ? "No dataset was available to validate this change."
                : "Inspect the failures below; fix the dataset, edit the prompt, or try a different model.")}
          </p>
        )}
      </div>

      {failed && run.failed_cases.length > 0 && (
        <div className="mb-3 max-h-40 overflow-auto rounded-md border border-hairline bg-surface/40 p-2 text-[11px]">
          {run.failed_cases.map((fc, idx) => (
            <div
              key={`${fc.case}-${idx}`}
              className="border-b border-hairline/60 py-1.5 last:border-b-0"
            >
              <div className="flex items-center gap-2 font-mono text-ink">
                <span>{fc.case}</span>
                <span className="rounded bg-surface px-1.5 py-0.5 text-[10px] text-muted">
                  {fc.evaluator}
                </span>
              </div>
              <div className="mt-0.5 text-muted">{fc.reason}</div>
            </div>
          ))}
        </div>
      )}

      {error && (
        <div className="mb-3 rounded-md border border-amber/60 bg-amber-soft px-2 py-1.5 text-[11px] text-amber">
          {error}
        </div>
      )}

      {suggestError && (
        <div className="mb-3 rounded-md border border-amber/60 bg-amber-soft px-2 py-1.5 text-[11px] text-amber">
          Picker failed: {suggestError}
        </div>
      )}

      {suggestion && (
        <SuggestionInline
          suggestion={suggestion}
          onUse={onUseSuggestion}
        />
      )}

      <div className="flex items-center justify-end gap-2">
        {!passed && canReSuggest && !suggestion && (
          <button
            type="button"
            onClick={onReSuggest}
            className="inline-flex items-center gap-1.5 rounded-md border border-indigo/40 px-3 py-1.5 text-[12px] text-indigo hover:bg-indigo-soft"
          >
            <Sparkles strokeWidth={1.6} size={12} /> Suggest a different model
          </button>
        )}
        {!passed && (
          <button
            type="button"
            onClick={onRetry}
            className="rounded-md border border-hairline px-3 py-1.5 text-[12px] text-ink hover:bg-surface"
          >
            Back
          </button>
        )}
        <button
          type="button"
          onClick={onClose}
          className="rounded-md bg-indigo px-3 py-1.5 text-[12px] text-white hover:bg-indigo/90"
        >
          Close
        </button>
      </div>
    </>
  );
}

// ---------------------------------------------------------------------------
// Inline suggestion chips (re-suggest result)
// ---------------------------------------------------------------------------

function SuggestionInline({
  suggestion,
  onUse,
}: {
  readonly suggestion: ModelRecommendation;
  readonly onUse: (option: ModelOption) => void;
}) {
  if (!suggestion.can_recommend) {
    return (
      <div className="mb-3 rounded-md border border-amber/60 bg-amber-soft p-2 text-[11px] text-amber">
        <div className="font-medium">
          Can't recommend another model:
        </div>
        <p className="mt-0.5">
          {suggestion.reason_if_not || "purpose unclear"}
        </p>
        {suggestion.improvement_hints.length > 0 && (
          <ul className="mt-1 list-disc space-y-0.5 pl-4">
            {suggestion.improvement_hints.map((h, i) => <li key={i}>{h}</li>)}
          </ul>
        )}
      </div>
    );
  }
  return (
    <div className="mb-3 space-y-2 rounded-md border border-indigo/40 bg-indigo/5 p-2">
      <div className="text-[11px] font-medium text-indigo">
        New suggestions
      </div>
      {suggestion.best_overall && (
        <InlineChip
          label="Best overall"
          option={suggestion.best_overall}
          onUse={onUse}
        />
      )}
      {suggestion.cost_effective && (
        <InlineChip
          label="Cost-effective"
          option={suggestion.cost_effective}
          onUse={onUse}
        />
      )}
      {suggestion.notes.length > 0 && (
        <ul className="list-disc space-y-0.5 pl-4 text-[11px] text-muted">
          {suggestion.notes.map((n, i) => <li key={i}>{n}</li>)}
        </ul>
      )}
    </div>
  );
}

function InlineChip({
  label,
  option,
  onUse,
}: {
  readonly label: string;
  readonly option: ModelOption;
  readonly onUse: (option: ModelOption) => void;
}) {
  return (
    <div className="flex items-start gap-2 rounded-md border border-hairline bg-surface px-2 py-1.5">
      <div className="flex-1">
        <div className="flex items-center gap-2">
          <span className="text-[10px] uppercase tracking-wide text-muted">
            {label}
          </span>
          <span className="rounded-full border border-hairline px-1.5 py-px text-[10px] text-muted">
            {option.route}
          </span>
        </div>
        <div className="mt-0.5 font-mono text-[12px] text-ink/90">
          {option.model_id}
        </div>
        {option.rationale && (
          <p className="mt-0.5 text-[11px] text-muted/90">
            {option.rationale}
          </p>
        )}
      </div>
      <button
        type="button"
        onClick={() => onUse(option)}
        className="inline-flex items-center gap-1 rounded-md bg-indigo px-2 py-1 text-[11px] text-white hover:bg-indigo/90"
      >
        Use
      </button>
    </div>
  );
}

/**
 * Suggest two models for an agent spec — best-overall and
 * cost-effective — and let the user apply either pick to the
 * surrounding form's modelRoute + modelOverride fields.
 *
 * The actual recommendation comes from the locked `model_picker`
 * system agent over the `suggest_agent_model` IPC. The panel is
 * intentionally dumb: it owns request state + chips rendering, but
 * applies picks through a parent callback so it works for both the
 * new-agent wizard and the user-agent edit row.
 *
 * When the agent's purpose is too vague to evaluate, the panel
 * renders the refusal `reason_if_not` + `improvement_hints` instead
 * of chips so the user knows what to clarify before retrying.
 *
 * sensitivity_tier: 1 (operational metadata only)
 */

import { useCallback, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import { Loader2, Sparkles } from "lucide-react";
import type {
  ModelOption,
  ModelPickerSpec,
  ModelRecommendation,
  ModelRecommendationResponse,
} from "../types/agents";

interface ModelSuggestionPanelProps {
  /** Live spec from the surrounding form. */
  readonly spec: ModelPickerSpec;
  /** Apply a pick — should set both modelRoute and modelOverride. */
  readonly onApply: (option: ModelOption) => void;
  /**
   * Disable the button when the parent decides the spec isn't ready
   * (e.g. empty name / system prompt). Internally we also block based
   * on those fields, but the parent might want to be stricter.
   */
  readonly disabled?: boolean;
}

export default function ModelSuggestionPanel({
  spec,
  onApply,
  disabled,
}: ModelSuggestionPanelProps): JSX.Element {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<ModelRecommendation | null>(null);

  const canRequest = Boolean(
    spec.name.trim() && spec.system_prompt.trim() && !disabled && !loading,
  );

  const run = useCallback(async () => {
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      const response = await invoke<ModelRecommendationResponse>(
        "suggest_agent_model",
        { spec },
      );
      setResult(response.recommendation);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, [spec]);

  return (
    <div className="rounded-md border border-hairline bg-surface/40 p-3">
      <div className="flex items-center justify-between gap-2">
        <div>
          <div className="text-[12px] font-medium text-ink">
            Suggested models
          </div>
          <p className="mt-0.5 text-[11px] text-muted">
            Ask the Model Picker to recommend a best-overall and a
            cost-effective pick based on this agent's spec.
          </p>
        </div>
        <button
          type="button"
          onClick={run}
          disabled={!canRequest}
          className="inline-flex items-center gap-1 rounded-md border border-indigo/40 px-3 py-1.5 text-[12px] text-indigo hover:bg-indigo-soft disabled:opacity-50"
        >
          {loading
            ? <Loader2 strokeWidth={1.6} size={12} className="animate-spin" />
            : <Sparkles strokeWidth={1.6} size={12} />}
          {loading ? "Thinking…" : "Suggest model"}
        </button>
      </div>

      {error && (
        <div className="mt-2 rounded-md border border-amber/60 bg-amber-soft px-2 py-1.5 text-[11px] text-amber">
          {error}
        </div>
      )}

      {result && (
        <div className="mt-3 space-y-2">
          {result.can_recommend
            ? <RecommendationChips result={result} onApply={onApply} />
            : <Refusal result={result} />}
        </div>
      )}
    </div>
  );
}

function RecommendationChips({
  result,
  onApply,
}: {
  readonly result: ModelRecommendation;
  readonly onApply: (option: ModelOption) => void;
}): JSX.Element {
  return (
    <>
      {result.purpose_summary && (
        <p className="text-[11px] text-muted/90">
          <span className="text-muted">Purpose: </span>
          {result.purpose_summary}
        </p>
      )}
      {result.best_overall && (
        <SuggestionChip
          label="Best overall"
          option={result.best_overall}
          onApply={onApply}
        />
      )}
      {result.cost_effective && (
        <SuggestionChip
          label="Cost-effective"
          option={result.cost_effective}
          onApply={onApply}
        />
      )}
      {result.notes.length > 0 && (
        <ul className="list-disc space-y-0.5 pl-4 text-[11px] text-muted">
          {result.notes.map((note, i) => (
            <li key={i}>{note}</li>
          ))}
        </ul>
      )}
    </>
  );
}

function SuggestionChip({
  label,
  option,
  onApply,
}: {
  readonly label: string;
  readonly option: ModelOption;
  readonly onApply: (option: ModelOption) => void;
}): JSX.Element {
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
        onClick={() => onApply(option)}
        className="inline-flex items-center gap-1 rounded-md bg-indigo px-2 py-1 text-[11px] text-white hover:bg-indigo/90"
      >
        Use
      </button>
    </div>
  );
}

function Refusal({
  result,
}: {
  readonly result: ModelRecommendation;
}): JSX.Element {
  return (
    <div className="rounded-md border border-amber/60 bg-amber-soft p-2 text-[11px] text-amber">
      <div className="font-medium">
        {result.reason_if_not || "Can't recommend yet."}
      </div>
      {result.improvement_hints.length > 0 && (
        <ul className="mt-1 list-disc space-y-0.5 pl-4">
          {result.improvement_hints.map((hint, i) => (
            <li key={i}>{hint}</li>
          ))}
        </ul>
      )}
    </div>
  );
}

import { invoke } from "@tauri-apps/api/core";
import {
  Check,
  Loader2,
  Sparkles,
  Wand2,
  X,
} from "lucide-react";
import {
  useCallback,
  useEffect,
  useMemo,
  useState,
} from "react";

import type {
  PromptEngineerSpec,
  PromptImprovement,
  PromptImprovementCategory,
  PromptImprovementTarget,
  PromptSuggestion,
  PromptSuggestionResponse,
} from "../types/agents";

const CATEGORY_LABELS: Record<PromptImprovementCategory, string> = {
  clarity: "Clarity",
  expected_output: "Expected output",
  language: "Language",
  format: "Format",
  scope: "Scope",
  safety: "Safety",
};

const TARGET_LABELS: Record<PromptImprovementTarget, string> = {
  system_prompt: "system prompt",
  description: "description",
};

interface PromptEngineerModalProps {
  /** Saved agent id; null when previewing from the create-agent modal. */
  readonly agentId: string | null;
  readonly currentName: string;
  readonly currentDescription: string;
  readonly currentSystemPrompt: string;
  readonly currentMaxTier: number;
  readonly availableTools?: ReadonlyArray<string>;
  readonly availableSkills?: ReadonlyArray<string>;
  readonly enabledMcpTools?: ReadonlyArray<string>;
  readonly hasDataset?: boolean;
  readonly onClose: () => void;
  /** Called when the user accepts the full rewrite (prompt + description). */
  readonly onApplyRewrite: (
    newSystemPrompt: string,
    newDescription: string,
  ) => void;
  /** Called when the user accepts only the surgical additions. */
  readonly onApplyAdditions: (appendedText: string) => void;
}

type Phase = "loading" | "result" | "error";

export function PromptEngineerModal({
  agentId,
  currentName,
  currentDescription,
  currentSystemPrompt,
  currentMaxTier,
  availableTools,
  availableSkills,
  enabledMcpTools,
  hasDataset,
  onClose,
  onApplyRewrite,
  onApplyAdditions,
}: PromptEngineerModalProps): JSX.Element {
  const [phase, setPhase] = useState<Phase>("loading");
  const [error, setError] = useState<string | null>(null);
  const [suggestion, setSuggestion] = useState<PromptSuggestion | null>(null);
  const [draftPrompt, setDraftPrompt] = useState("");
  const [draftDescription, setDraftDescription] = useState("");
  const [acceptedImprovements, setAcceptedImprovements] = useState<
    ReadonlySet<number>
  >(() => new Set());

  const fetchSuggestion = useCallback(async () => {
    setPhase("loading");
    setError(null);
    try {
      const spec: PromptEngineerSpec = {
        name: currentName,
        description: currentDescription,
        system_prompt: currentSystemPrompt,
        max_sensitivity_tier: currentMaxTier,
        agent_id: agentId,
        available_tools: availableTools ?? [],
        available_skills: availableSkills ?? [],
        enabled_mcp_tools: enabledMcpTools ?? [],
        has_dataset: Boolean(hasDataset),
      };
      const resp = await invoke<PromptSuggestionResponse>(
        "suggest_prompt_improvements",
        { spec },
      );
      setSuggestion(resp.suggestion);
      setDraftPrompt(resp.suggestion.improved_system_prompt);
      setDraftDescription(resp.suggestion.improved_description);
      setAcceptedImprovements(
        new Set(resp.suggestion.improvements.map((_, i) => i)),
      );
      setPhase("result");
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
      setSuggestion(null);
      setPhase("error");
    }
  }, [
    agentId,
    availableSkills,
    availableTools,
    currentDescription,
    currentMaxTier,
    currentName,
    currentSystemPrompt,
    enabledMcpTools,
    hasDataset,
  ]);

  useEffect(() => {
    void fetchSuggestion();
  }, [fetchSuggestion]);

  const canApplyRewrite = useMemo(
    () =>
      suggestion?.can_improve === true
      && draftPrompt.trim().length > 0
      && draftDescription.trim().length > 0,
    [suggestion, draftPrompt, draftDescription],
  );

  const canApplyAdditions = Boolean(
    suggestion?.can_improve === true
    && suggestion.system_prompt_additions.length > 0,
  );

  const toggleImprovement = (idx: number) => {
    setAcceptedImprovements((prev) => {
      const next = new Set(prev);
      if (next.has(idx)) next.delete(idx);
      else next.add(idx);
      return next;
    });
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
      <div className="flex max-h-full w-full max-w-5xl flex-col rounded-4 border border-hairline bg-surface shadow-xl">
        <div className="flex items-center justify-between border-b border-hairline px-5 py-3">
          <h2 className="flex items-center gap-2 text-base font-semibold text-ink">
            <Sparkles strokeWidth={1.6} size={14} className="text-indigo" />
            Improve prompts
          </h2>
          <button
            type="button"
            onClick={onClose}
            className="rounded-md p-1 text-muted hover:bg-surface"
          >
            <X strokeWidth={1.6} size={14} />
          </button>
        </div>

        <div className="flex-1 space-y-3 overflow-auto px-5 py-4">
          {phase === "loading" && (
            <div className="flex items-center gap-2 text-[12px] text-muted">
              <Loader2 strokeWidth={1.6} size={12} className="animate-spin" />
              Reading the agent and proposing improvements…
            </div>
          )}

          {phase === "error" && error && (
            <div className="rounded-md border border-amber/60 bg-amber-soft px-3 py-2 text-[12px] text-amber">
              {error}
            </div>
          )}

          {phase === "result" && suggestion && !suggestion.can_improve && (
            <RefusalPanel suggestion={suggestion} />
          )}

          {phase === "result" && suggestion && suggestion.can_improve && (
            <div className="space-y-3">
              <SuggestionHeader suggestion={suggestion} />
              {suggestion.improvements.length > 0 && (
                <ImprovementList
                  improvements={suggestion.improvements}
                  accepted={acceptedImprovements}
                  onToggle={toggleImprovement}
                />
              )}
              <DiffPanel
                originalPrompt={currentSystemPrompt}
                draftPrompt={draftPrompt}
                onDraftPromptChange={setDraftPrompt}
                originalDescription={currentDescription}
                draftDescription={draftDescription}
                onDraftDescriptionChange={setDraftDescription}
              />
              {suggestion.system_prompt_additions.length > 0 && (
                <AdditionsPanel
                  additions={suggestion.system_prompt_additions}
                />
              )}
              {suggestion.notes.length > 0 && (
                <NotesPanel notes={suggestion.notes} />
              )}
            </div>
          )}
        </div>

        <div className="flex items-center justify-between gap-2 border-t border-hairline px-5 py-3">
          <button
            type="button"
            onClick={onClose}
            className="rounded-md border border-hairline px-3 py-1.5 text-[12px] text-muted hover:bg-surface"
          >
            {suggestion?.can_improve === false ? "Close" : "Skip"}
          </button>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => void fetchSuggestion()}
              disabled={phase === "loading"}
              className="inline-flex items-center gap-1 rounded-md border border-hairline px-3 py-1.5 text-[12px] text-ink hover:bg-surface disabled:opacity-50"
            >
              {phase === "loading"
                ? <Loader2 strokeWidth={1.6} size={12} className="animate-spin" />
                : <Wand2 strokeWidth={1.6} size={12} />}
              Regenerate
            </button>
            <button
              type="button"
              disabled={!canApplyAdditions}
              onClick={() => {
                if (!suggestion) return;
                onApplyAdditions(
                  suggestion.system_prompt_additions.join("\n"),
                );
              }}
              className="inline-flex items-center gap-1 rounded-md border border-indigo/60 px-3 py-1.5 text-[12px] text-indigo hover:bg-indigo-soft disabled:opacity-50"
            >
              <Sparkles strokeWidth={1.6} size={12} />
              Apply additions only
            </button>
            <button
              type="button"
              disabled={!canApplyRewrite}
              onClick={() => onApplyRewrite(draftPrompt, draftDescription)}
              className="inline-flex items-center gap-1 rounded-md bg-indigo px-3 py-1.5 text-[12px] text-white hover:bg-indigo/90 disabled:opacity-50"
            >
              <Check strokeWidth={1.6} size={12} />
              Apply full rewrite
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

function SuggestionHeader({
  suggestion,
}: {
  readonly suggestion: PromptSuggestion;
}): JSX.Element {
  const pct = Math.round(suggestion.confidence * 100);
  return (
    <div className="rounded-md border border-hairline bg-surface/30 px-3 py-2">
      <div className="flex items-center justify-between gap-2">
        <div className="text-[12px] font-medium text-ink">
          {suggestion.change_summary || "Proposed prompt rewrite"}
        </div>
        <span className="shrink-0 rounded-full border border-hairline px-2 py-0.5 text-[10px] text-muted">
          confidence {pct}%
        </span>
      </div>
    </div>
  );
}

function RefusalPanel({
  suggestion,
}: {
  readonly suggestion: PromptSuggestion;
}): JSX.Element {
  return (
    <div className="space-y-2">
      <div className="rounded-md border border-amber/60 bg-amber-soft px-3 py-2 text-[12px] text-amber">
        <div className="font-medium">No rewrite proposed</div>
        <p className="mt-1 text-amber/90">
          {suggestion.reason_if_not
            ?? "The prompt engineer did not find material edits to make."}
        </p>
      </div>
      {suggestion.improvements.length > 0 && (
        <div className="rounded-md border border-hairline bg-surface/40 px-3 py-2">
          <div className="text-[10px] uppercase tracking-wider text-muted">
            Suggested manual edits
          </div>
          <ul className="mt-1 list-disc space-y-0.5 pl-4 text-[12px] text-ink/90">
            {suggestion.improvements.map((item, i) => (
              <li key={i}>
                <span className="text-muted">
                  [{CATEGORY_LABELS[item.category]}]
                </span>{" "}
                {item.rationale}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

function ImprovementList({
  improvements,
  accepted,
  onToggle,
}: {
  readonly improvements: ReadonlyArray<PromptImprovement>;
  readonly accepted: ReadonlySet<number>;
  readonly onToggle: (idx: number) => void;
}): JSX.Element {
  return (
    <div className="rounded-md border border-hairline bg-surface/30 px-3 py-2">
      <div className="text-[10px] uppercase tracking-wider text-muted">
        What the engineer changed
      </div>
      <ul className="mt-1 space-y-1.5">
        {improvements.map((item, idx) => {
          const isOn = accepted.has(idx);
          return (
            <li
              key={idx}
              className={`rounded border border-hairline/50 bg-surface px-2 py-1.5 ${
                isOn ? "" : "opacity-60"
              }`}
            >
              <label className="flex cursor-pointer items-start gap-2">
                <input
                  type="checkbox"
                  checked={isOn}
                  onChange={() => onToggle(idx)}
                  className="mt-1"
                />
                <div className="flex-1 space-y-0.5">
                  <div className="flex items-center gap-1 text-[10px] uppercase tracking-wider text-muted">
                    <span className="rounded bg-indigo-soft px-1 py-0.5 text-indigo">
                      {CATEGORY_LABELS[item.category]}
                    </span>
                    <span>→ {TARGET_LABELS[item.target]}</span>
                  </div>
                  <div className="text-[12px] text-ink/90">
                    {item.rationale}
                  </div>
                  {item.original_snippet && (
                    <div className="mt-0.5 grid grid-cols-2 gap-1 text-[11px]">
                      <code className="rounded border border-hairline/50 bg-amber/5 px-1.5 py-0.5 text-amber/90 line-through">
                        {item.original_snippet}
                      </code>
                      <code className="rounded border border-hairline/50 bg-indigo/5 px-1.5 py-0.5 text-indigo">
                        {item.suggested_replacement}
                      </code>
                    </div>
                  )}
                </div>
              </label>
            </li>
          );
        })}
      </ul>
      <p className="mt-1.5 text-[10px] text-muted">
        Checkboxes are informational — applying the full rewrite uses the
        editable suggested prompt below as-is. Edit the right-hand
        textareas if you want to ignore an improvement before applying.
      </p>
    </div>
  );
}

function DiffPanel({
  originalPrompt,
  draftPrompt,
  onDraftPromptChange,
  originalDescription,
  draftDescription,
  onDraftDescriptionChange,
}: {
  readonly originalPrompt: string;
  readonly draftPrompt: string;
  readonly onDraftPromptChange: (value: string) => void;
  readonly originalDescription: string;
  readonly draftDescription: string;
  readonly onDraftDescriptionChange: (value: string) => void;
}): JSX.Element {
  return (
    <div className="space-y-2">
      <div className="grid grid-cols-2 gap-2">
        <label className="block">
          <span className="text-[11px] text-muted">
            Current system prompt
          </span>
          <textarea
            value={originalPrompt}
            readOnly
            spellCheck={false}
            className="mt-1 h-72 w-full resize-y rounded-md border border-hairline bg-surface/40 p-2 font-mono text-[11px] text-muted focus:outline-none"
          />
        </label>
        <label className="block">
          <span className="text-[11px] text-indigo">
            Suggested system prompt (editable)
          </span>
          <textarea
            value={draftPrompt}
            onChange={(e) => onDraftPromptChange(e.target.value)}
            spellCheck={false}
            className="mt-1 h-72 w-full resize-y rounded-md border border-indigo/60 bg-indigo/5 p-2 font-mono text-[11px] text-ink focus:border-indigo focus:outline-none"
          />
        </label>
      </div>
      <div className="grid grid-cols-2 gap-2">
        <label className="block">
          <span className="text-[11px] text-muted">
            Current description
          </span>
          <textarea
            value={originalDescription}
            readOnly
            spellCheck={false}
            className="mt-1 h-20 w-full resize-y rounded-md border border-hairline bg-surface/40 p-2 text-[12px] text-muted focus:outline-none"
          />
        </label>
        <label className="block">
          <span className="text-[11px] text-indigo">
            Suggested description (editable)
          </span>
          <textarea
            value={draftDescription}
            onChange={(e) => onDraftDescriptionChange(e.target.value)}
            spellCheck={false}
            className="mt-1 h-20 w-full resize-y rounded-md border border-indigo/60 bg-indigo/5 p-2 text-[12px] text-ink focus:border-indigo focus:outline-none"
          />
        </label>
      </div>
    </div>
  );
}

function AdditionsPanel({
  additions,
}: {
  readonly additions: ReadonlyArray<string>;
}): JSX.Element {
  return (
    <div className="rounded-md border border-indigo/40 bg-indigo/5 p-3">
      <div className="flex items-center gap-1.5 text-[12px] font-medium text-indigo">
        <Sparkles strokeWidth={1.6} size={12} /> Surgical additions
      </div>
      <p className="mt-0.5 text-[11px] text-muted">
        Short imperative lines you can append to the current prompt instead
        of taking the full rewrite. "Apply additions only" appends these
        verbatim and keeps your original wording otherwise.
      </p>
      <ul className="mt-2 space-y-1.5">
        {additions.map((text, idx) => (
          <li
            key={idx}
            className="rounded border border-hairline/50 bg-surface px-2 py-1.5"
          >
            <code className="whitespace-pre-wrap break-words font-mono text-[11px] text-ink/90">
              {text}
            </code>
          </li>
        ))}
      </ul>
    </div>
  );
}

function NotesPanel({
  notes,
}: {
  readonly notes: ReadonlyArray<string>;
}): JSX.Element {
  return (
    <div className="rounded-md border border-hairline bg-surface/40 px-3 py-2">
      <div className="text-[10px] uppercase tracking-wider text-muted">
        Caveats
      </div>
      <ul className="mt-1 list-disc space-y-0.5 pl-4 text-[11px] text-muted">
        {notes.map((n, i) => <li key={i}>{n}</li>)}
      </ul>
    </div>
  );
}

export default PromptEngineerModal;

// Eval dataset viewer + (for user agents) editor. Reuses the
// dataset_creator agent to suggest YAML.
//
// sensitivity_tier: 1

import type { JSX } from "react";
import { useCallback, useEffect, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import {
  Database,
  Loader2,
  Save,
  Sparkles,
  Wand2,
  X,
} from "lucide-react";
import type {
  AgentEvalDataset,
  DatasetSuggestion,
  DatasetSuggestionResponse,
  DatasetValidationResponse,
  UnsavedAgentSpec,
} from "../../../types/agents";

interface EvalDatasetPanelProps {
  readonly agentId: string;
  readonly editable: boolean;
}

export function EvalDatasetPanel({
  agentId,
  editable,
}: EvalDatasetPanelProps): JSX.Element {
  const [data, setData] = useState<AgentEvalDataset | null>(null);
  const [loading, setLoading] = useState(true);
  const [draft, setDraft] = useState<string>("");
  const [validating, setValidating] = useState(false);
  const [report, setReport] = useState<DatasetValidationResponse | null>(null);
  const [suggestModalOpen, setSuggestModalOpen] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const ds = await invoke<AgentEvalDataset>("get_agent_eval_dataset", {
        agentId,
      });
      setData(ds);
      setDraft(ds.content ?? "");
    } finally {
      setLoading(false);
    }
  }, [agentId]);

  useEffect(() => {
    void load();
  }, [load]);

  const handleSuggestionAccepted = useCallback((mergedYaml: string) => {
    setDraft(mergedYaml);
    setSuggestModalOpen(false);
    setReport(null);
  }, []);

  const validateAndSave = useCallback(async () => {
    setValidating(true);
    setReport(null);
    try {
      const resp = await invoke<DatasetValidationResponse>(
        "upload_user_eval_dataset",
        { agentId, content: draft },
      );
      setReport(resp);
      if (resp.persisted) {
        await load();
      }
    } catch (e) {
      setReport({
        report: {
          valid: false,
          errors: [e instanceof Error ? e.message : String(e)],
          proposals: [],
          firewall_verdict: "allow",
        },
        persisted: false,
      });
    } finally {
      setValidating(false);
    }
  }, [agentId, draft, load]);

  if (loading) {
    return (
      <div className="rounded-md border border-hairline bg-surface p-3 text-[11px] text-muted">
        Loading dataset…
      </div>
    );
  }

  return (
    <div className="space-y-2">
      <div className="flex items-center gap-2 text-[11px] text-muted">
        <Database size={11} />
        <span>
          {data?.source === "builtin"
            ? `Built-in suite: ${data.suite ?? "—"}`
            : data?.source === "user"
              ? "User-uploaded dataset"
              : "No dataset yet"}
        </span>
        {data?.path && (
          <code className="ml-1 truncate text-[10px] text-muted/80">
            {data.path}
          </code>
        )}
      </div>
      {(data?.parsed_cases ?? []).length > 0 && (
        <div className="max-h-44 overflow-auto rounded-md border border-hairline bg-surface/40">
          <table className="w-full table-fixed text-[11px]">
            <thead>
              <tr className="text-left text-muted">
                <th className="px-2 py-1">case</th>
                <th className="px-2 py-1">evaluators</th>
              </tr>
            </thead>
            <tbody>
              {data!.parsed_cases.map((c) => (
                <tr key={c.name} className="border-t border-hairline/40">
                  <td className="truncate px-2 py-1 font-mono text-ink">
                    {c.name}
                  </td>
                  <td className="truncate px-2 py-1 text-muted">
                    {c.evaluators.join(", ") || "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {editable
        ? (
          <>
            <div className="flex items-center justify-end">
              <button
                type="button"
                onClick={() => setSuggestModalOpen(true)}
                className="inline-flex items-center gap-1 rounded-md border border-indigo/60 px-2.5 py-1 text-[11px] text-indigo hover:bg-indigo-soft"
              >
                <Wand2 size={11} />
                {data?.source === "user"
                  ? "Suggest more cases"
                  : "Generate dataset"}
              </button>
            </div>
            <textarea
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              spellCheck={false}
              placeholder={"cases:\n  - name: example\n    inputs: hello\n"}
              className="h-48 w-full resize-y rounded-md border border-hairline bg-surface p-2 font-mono text-[11px] text-ink/90 focus:border-indigo focus:outline-none"
            />
            <div className="flex items-center justify-between gap-2">
              <span className="text-[11px] text-muted">
                YAML is validated structurally + scanned by the firewall before
                being saved.
              </span>
              <button
                type="button"
                disabled={validating || !draft.trim()}
                onClick={validateAndSave}
                className="inline-flex items-center gap-1 rounded-md bg-indigo px-3 py-1.5 text-[12px] text-white hover:bg-indigo/90 disabled:opacity-50"
              >
                {validating
                  ? <Loader2 size={12} className="animate-spin" />
                  : <Save size={12} />}
                Validate & save
              </button>
            </div>
            {report && <ValidationReport response={report} />}
            {suggestModalOpen && (
              <SuggestDatasetModal
                agentId={agentId}
                appending={data?.source === "user"}
                onClose={() => setSuggestModalOpen(false)}
                onAccepted={handleSuggestionAccepted}
              />
            )}
          </>
        )
        : (
          <pre className="max-h-72 overflow-auto whitespace-pre-wrap rounded-md border border-hairline bg-surface p-3 font-mono text-[11px] text-ink/90">
            {data?.content ?? "No dataset on disk."}
          </pre>
        )}
    </div>
  );
}

function ValidationReport({
  response,
}: {
  readonly response: DatasetValidationResponse;
}): JSX.Element {
  const { report, persisted } = response;
  const tone = report.valid
    ? (persisted
      ? "border-success/60 bg-success/10 text-success"
      : "border-hairline bg-surface text-muted")
    : "border-amber/60 bg-amber/10 text-amber";
  return (
    <div className={`rounded-md border px-3 py-2 text-[11px] ${tone}`}>
      <div className="font-medium">
        {persisted
          ? "Saved — dataset is now active for this agent."
          : report.valid
            ? `Dataset valid (firewall: ${report.firewall_verdict}) but not persisted.`
            : `Dataset rejected (firewall: ${report.firewall_verdict}).`}
      </div>
      {report.errors.length > 0 && (
        <ul className="mt-1 list-disc space-y-0.5 pl-4">
          {report.errors.map((e, i) => <li key={i}>{e}</li>)}
        </ul>
      )}
      {report.proposals.length > 0 && (
        <div className="mt-1">
          <div className="text-[10px] uppercase tracking-wider">Suggestions</div>
          <ul className="list-disc space-y-0.5 pl-4">
            {report.proposals.map((p, i) => <li key={i}>{p}</li>)}
          </ul>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Suggest-dataset modal — used by this panel and by the create-agent form.
// ---------------------------------------------------------------------------

interface PromptAdditionsPanelProps {
  readonly additions: ReadonlyArray<string>;
  readonly onApply?: (text: string) => void;
}

function PromptAdditionsPanel({
  additions,
  onApply,
}: PromptAdditionsPanelProps): JSX.Element | null {
  const [applied, setApplied] = useState<ReadonlySet<number>>(() => new Set());
  if (additions.length === 0) return null;

  const remaining = additions
    .map((text, idx) => ({ text, idx }))
    .filter((entry) => !applied.has(entry.idx));

  const markApplied = (idx: number) => {
    setApplied((prev) => {
      const next = new Set(prev);
      next.add(idx);
      return next;
    });
  };

  const applyOne = (text: string, idx: number) => {
    onApply?.(text);
    markApplied(idx);
  };

  const applyAll = () => {
    if (!onApply || remaining.length === 0) return;
    onApply(remaining.map((r) => r.text).join("\n"));
    setApplied(new Set(additions.map((_, i) => i)));
  };

  const allApplied = remaining.length === 0;

  return (
    <div className="rounded-md border border-indigo/40 bg-indigo/5 p-3">
      <div className="flex items-start justify-between gap-2">
        <div>
          <div className="flex items-center gap-1.5 text-[12px] font-medium text-indigo">
            <Sparkles size={12} /> Tighten your system prompt
          </div>
          <p className="mt-0.5 text-[11px] text-muted">
            The dataset bakes in specific tokens / format / language that
            your prompt doesn't pin yet. Append these one-liners so the
            LLM produces what the cases expect — otherwise even a strong
            model will fail evals with sensible defaults.
          </p>
        </div>
        {onApply && !allApplied && additions.length > 1 && (
          <button
            type="button"
            onClick={applyAll}
            className="shrink-0 rounded-md border border-indigo/40 px-2 py-1 text-[11px] text-indigo hover:bg-indigo-soft"
          >
            Append all
          </button>
        )}
      </div>
      <ul className="mt-2 space-y-1.5">
        {additions.map((text, idx) => {
          const isApplied = applied.has(idx);
          return (
            <li
              key={idx}
              className={`flex items-start gap-2 rounded border border-hairline/50 bg-surface px-2 py-1.5 ${
                isApplied ? "opacity-60" : ""
              }`}
            >
              <code className="flex-1 whitespace-pre-wrap break-words font-mono text-[11px] text-ink/90">
                {text}
              </code>
              {onApply && (
                <button
                  type="button"
                  onClick={() => applyOne(text, idx)}
                  disabled={isApplied}
                  className="shrink-0 rounded-md border border-hairline px-2 py-0.5 text-[11px] text-ink hover:bg-surface disabled:cursor-default disabled:opacity-50"
                >
                  {isApplied ? "Applied" : "Append"}
                </button>
              )}
            </li>
          );
        })}
      </ul>
    </div>
  );
}

interface SuggestDatasetModalProps {
  readonly agentId: string | null;
  readonly appending: boolean;
  readonly unsavedSpec?: UnsavedAgentSpec;
  readonly onClose: () => void;
  readonly onAccepted: (mergedYaml: string) => void;
  readonly onApplyPromptAdditions?: (text: string) => void;
}

export function SuggestDatasetModal({
  agentId,
  appending,
  unsavedSpec,
  onClose,
  onAccepted,
  onApplyPromptAdditions,
}: SuggestDatasetModalProps): JSX.Element {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [suggestion, setSuggestion] = useState<DatasetSuggestion | null>(null);
  const [draft, setDraft] = useState("");

  const fetchSuggestion = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const resp = await invoke<DatasetSuggestionResponse>(
        "suggest_eval_dataset",
        {
          agentId: agentId ?? null,
          unsavedSpec: unsavedSpec ?? null,
        },
      );
      setSuggestion(resp.suggestion);
      setDraft(resp.suggestion.dataset_yaml);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
      setSuggestion(null);
    } finally {
      setLoading(false);
    }
  }, [agentId, unsavedSpec]);

  useEffect(() => {
    void fetchSuggestion();
  }, [fetchSuggestion]);

  const canAccept = Boolean(
    suggestion && suggestion.can_create && draft.trim(),
  );

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
      <div className="flex max-h-full w-full max-w-3xl flex-col rounded-4 border border-hairline bg-surface shadow-xl">
        <div className="flex items-center justify-between border-b border-hairline px-5 py-3">
          <h2 className="flex items-center gap-2 text-base font-semibold text-ink">
            <Sparkles size={14} className="text-indigo" />
            {appending ? "Suggest more cases" : "Generate eval dataset"}
          </h2>
          <button
            type="button"
            onClick={onClose}
            className="rounded-md p-1 text-muted hover:bg-surface"
          >
            <X size={14} />
          </button>
        </div>
        <div className="flex-1 space-y-3 overflow-auto px-5 py-4">
          {loading && (
            <div className="flex items-center gap-2 text-[12px] text-muted">
              <Loader2 size={12} className="animate-spin" />
              Reading the agent and proposing a dataset…
            </div>
          )}
          {error && !loading && (
            <div className="rounded-md border border-amber/60 bg-amber/10 px-3 py-2 text-[12px] text-amber">
              {error}
            </div>
          )}
          {suggestion && !loading && !suggestion.can_create && (
            <div className="space-y-2">
              <div className="rounded-md border border-amber/60 bg-amber/10 px-3 py-2 text-[12px] text-amber">
                <div className="font-medium">Cannot infer a clear purpose</div>
                <p className="mt-1 text-amber/90">
                  {suggestion.reason_if_not
                    ?? "The agent's name, description, and system prompt don't agree on a single task."}
                </p>
              </div>
              {suggestion.improvement_hints.length > 0 && (
                <div className="rounded-md border border-hairline bg-surface/40 px-3 py-2">
                  <div className="text-[10px] uppercase tracking-wider text-muted">
                    Suggested edits to the agent
                  </div>
                  <ul className="mt-1 list-disc space-y-0.5 pl-4 text-[12px] text-ink/90">
                    {suggestion.improvement_hints.map((hint, i) => (
                      <li key={i}>{hint}</li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          )}
          {suggestion && !loading && suggestion.can_create && (
            <div className="space-y-3">
              <SuggestionSummary suggestion={suggestion} appending={appending} />
              <PromptAdditionsPanel
                additions={suggestion.system_prompt_additions}
                onApply={onApplyPromptAdditions}
              />
              <label className="block">
                <span className="text-[11px] text-muted">
                  Dataset YAML (editable)
                </span>
                <textarea
                  value={draft}
                  onChange={(e) => setDraft(e.target.value)}
                  spellCheck={false}
                  className="mt-1 h-72 w-full resize-y rounded-md border border-hairline bg-surface p-2 font-mono text-[11px] text-ink/90 focus:border-indigo focus:outline-none"
                />
              </label>
            </div>
          )}
        </div>
        <div className="flex items-center justify-between gap-2 border-t border-hairline px-5 py-3">
          <button
            type="button"
            onClick={onClose}
            className="rounded-md border border-hairline px-3 py-1.5 text-[12px] text-muted hover:bg-surface"
          >
            {suggestion?.can_create === false ? "Close" : "Cancel"}
          </button>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => void fetchSuggestion()}
              disabled={loading}
              className="inline-flex items-center gap-1 rounded-md border border-hairline px-3 py-1.5 text-[12px] text-ink hover:bg-surface disabled:opacity-50"
            >
              {loading
                ? <Loader2 size={12} className="animate-spin" />
                : <Wand2 size={12} />}
              Regenerate
            </button>
            <button
              type="button"
              disabled={!canAccept}
              onClick={() => onAccepted(draft)}
              className="inline-flex items-center gap-1 rounded-md bg-indigo px-3 py-1.5 text-[12px] text-white hover:bg-indigo/90 disabled:opacity-50"
            >
              <Save size={12} />
              {appending ? "Append & review" : "Use this dataset"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

function SuggestionSummary({
  suggestion,
  appending,
}: {
  readonly suggestion: DatasetSuggestion;
  readonly appending: boolean;
}): JSX.Element {
  return (
    <div className="rounded-md border border-hairline bg-surface/40 px-3 py-2 text-[12px]">
      <div className="font-medium text-ink">
        {suggestion.purpose_summary || "(no summary)"}
      </div>
      <div className="mt-1 flex flex-wrap gap-x-3 gap-y-1 text-[11px] text-muted">
        <span>strategy: <code>{suggestion.eval_strategy}</code></span>
        <span>shape: <code>{suggestion.output_shape}</code></span>
        <span>cases: {suggestion.case_count}</span>
        <span>confidence: {suggestion.confidence.toFixed(2)}</span>
        {appending && <span>· appending to existing</span>}
      </div>
      {suggestion.notes.length > 0 && (
        <ul className="mt-1 list-disc space-y-0.5 pl-4 text-[11px] text-muted">
          {suggestion.notes.map((n, i) => <li key={i}>{n}</li>)}
        </ul>
      )}
    </div>
  );
}

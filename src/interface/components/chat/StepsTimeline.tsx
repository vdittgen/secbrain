/**
 * Steps timeline — the chat's "what did the agent just do" surface.
 *
 * Renders the tool invocations the agent made during one turn. Closed
 * by default ("Used 3 tools · 2.4s"); clicking expands a vertical
 * timeline. Each step row shows: tool name, single-line args summary,
 * status (running / done / error), duration. The result summary is
 * hidden behind a per-step disclosure so Tier 3 echoes stay opt-in.
 *
 * Lives above the markdown body inside `MessageBubble` and
 * `StreamingBubble` so live runs surface steps as they arrive.
 *
 * sensitivity_tier: 3 (result summaries can echo Tier 3 sources)
 */

import { useMemo, useState } from "react";
import {
  ChevronDown,
  ChevronRight,
  Check,
  AlertCircle,
  Loader2,
  Wrench,
  Search,
  Globe,
  Send,
  Bell,
  Brain,
  ArrowRight,
} from "lucide-react";
import type { ToolStep, ToolStepStatus } from "../../hooks/useStreamingChat";

function iconFor(name: string): typeof Wrench {
  if (name === "recall_context") return Search;
  if (name === "web_search") return Globe;
  if (name === "propose_action") return Send;
  if (name === "update_notification_preferences") return Bell;
  if (name === "ask_brain") return Brain;
  if (name.startsWith("delegate_")) return ArrowRight;
  return Wrench;
}

function displayName(name: string): string {
  if (name.startsWith("delegate_")) {
    return `Ask ${name.slice("delegate_".length).replace(/_/g, " ")}`;
  }
  return name.replace(/_/g, " ");
}

function StatusIcon({ status }: { readonly status: ToolStepStatus }) {
  if (status === "running") {
    return <Loader2 className="h-3 w-3 animate-spin text-indigo" strokeWidth={1.6} />;
  }
  if (status === "ok") {
    return <Check className="h-3 w-3 text-success" strokeWidth={1.6} />;
  }
  if (status === "error") {
    return <AlertCircle className="h-3 w-3 text-danger" strokeWidth={1.6} />;
  }
  // incomplete — finished without a matching done event
  return <AlertCircle className="h-3 w-3 text-muted" strokeWidth={1.6} />;
}

function formatDuration(ms: number | undefined): string {
  if (ms == null || !Number.isFinite(ms)) return "";
  if (ms < 1000) return `${Math.round(ms)}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}

function Row({ step }: { readonly step: ToolStep }) {
  const [open, setOpen] = useState(false);
  const Icon = iconFor(step.name);
  const detail = step.error ?? step.result_summary ?? "";
  const hasDetail = detail.length > 0;
  return (
    <li className="rounded-2 border border-hairline bg-bg/40">
      <button
        type="button"
        onClick={() => hasDetail && setOpen((o) => !o)}
        disabled={!hasDetail}
        className="flex w-full items-center gap-2 px-2 py-1.5 text-left disabled:cursor-default"
      >
        <Icon className="h-3 w-3 shrink-0 text-muted" strokeWidth={1.6} />
        <span className="font-mono text-[11px] text-ink">
          {displayName(step.name)}
        </span>
        {step.args_summary && (
          <span className="truncate text-[11px] text-muted/80">
            · {step.args_summary}
          </span>
        )}
        <span className="ml-auto flex shrink-0 items-center gap-1.5">
          {step.duration_ms != null && (
            <span className="text-[10px] text-muted">
              {formatDuration(step.duration_ms)}
            </span>
          )}
          <StatusIcon status={step.status} />
        </span>
      </button>
      {open && hasDetail && (
        <div className="border-t border-hairline/60 px-2 py-1.5 text-[11px] text-muted">
          {step.error ? (
            <span className="text-danger">{step.error}</span>
          ) : (
            <span>{step.result_summary}</span>
          )}
        </div>
      )}
    </li>
  );
}

export interface StepsTimelineProps {
  readonly steps: ReadonlyArray<ToolStep>;
  /** When true, defaults to expanded — useful during live streaming. */
  readonly defaultOpen?: boolean;
  /**
   * When true, the agent is still streaming this turn — keep the
   * header spinner visible even if no individual step is currently
   * marked ``running`` (i.e. between tool calls, or after the last
   * tool while the LLM is composing its answer). Prevents the UI
   * from looking stalled during the silent gaps.
   */
  readonly active?: boolean;
}

export function StepsTimeline({
  steps,
  defaultOpen = false,
  active = false,
}: StepsTimelineProps) {
  const [open, setOpen] = useState(defaultOpen);
  const summary = useMemo(() => {
    if (steps.length === 0) return null;
    const totalMs = steps.reduce(
      (acc, s) => acc + (s.duration_ms ?? 0),
      0,
    );
    const noun = steps.length === 1 ? "tool" : "tools";
    const totalLabel = totalMs > 0 ? ` · ${formatDuration(totalMs)}` : "";
    const verb = active ? "Using" : "Used";
    return `${verb} ${steps.length} ${noun}${totalLabel}`;
  }, [steps, active]);

  if (steps.length === 0) return null;
  const anyRunning = steps.some((s) => s.status === "running");
  const showSpinner = active || anyRunning;

  return (
    <div className="my-1">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="flex items-center gap-1 text-xs text-muted hover:text-ink"
      >
        {open ? (
          <ChevronDown className="h-3 w-3" strokeWidth={1.6} />
        ) : (
          <ChevronRight className="h-3 w-3" strokeWidth={1.6} />
        )}
        {showSpinner ? (
          <Loader2 className="h-3 w-3 animate-spin text-indigo" strokeWidth={1.6} />
        ) : (
          <Wrench className="h-3 w-3" strokeWidth={1.6} />
        )}
        <span>{summary}</span>
      </button>
      {open && (
        <ul className="mt-1.5 space-y-1">
          {steps.map((step) => (
            <Row key={step.id} step={step} />
          ))}
        </ul>
      )}
    </div>
  );
}

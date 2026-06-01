/**
 * Plan / step renderer for `application/vnd.arandu.plan+json`.
 *
 * Mirrors `Plan` and `PlanStep` in `src/agents/core/output_types.py`:
 *
 *   { goal, revision?, steps: [{ id, description, status, notes? }] }
 *
 * Designed for deep-agent runs that surface their multi-step plan
 * before execution.
 *
 * sensitivity_tier: 1
 */

import { useMemo } from "react";
import { Check, Circle, CircleDashed, MinusCircle } from "lucide-react";
import type { ArtifactRendererProps } from "./registry";

type PlanStatus = "pending" | "in_progress" | "completed" | "blocked";

interface PlanStep {
  readonly id: string;
  readonly description: string;
  readonly status: PlanStatus;
  readonly notes?: string;
}

interface PlanSpec {
  readonly goal: string;
  readonly steps: ReadonlyArray<PlanStep>;
  readonly revision?: number;
}

function parseSpec(data: unknown): PlanSpec | null {
  let spec: unknown = data;
  if (typeof data === "string") {
    try {
      spec = JSON.parse(data);
    } catch {
      return null;
    }
  }
  if (!spec || typeof spec !== "object") return null;
  const obj = spec as Partial<PlanSpec>;
  if (typeof obj.goal !== "string" || !Array.isArray(obj.steps)) return null;
  return spec as PlanSpec;
}

function StatusIcon({ status }: { readonly status: PlanStatus }) {
  switch (status) {
    case "completed":
      return <Check className="h-3.5 w-3.5 text-success" strokeWidth={1.6} />;
    case "in_progress":
      return <CircleDashed className="h-3.5 w-3.5 animate-pulse text-indigo" strokeWidth={1.6} />;
    case "blocked":
      return <MinusCircle className="h-3.5 w-3.5 text-danger" strokeWidth={1.6} />;
    case "pending":
    default:
      return <Circle className="h-3.5 w-3.5 text-muted" strokeWidth={1.6} />;
  }
}

export function PlanCard({ part }: ArtifactRendererProps) {
  const spec = useMemo(() => parseSpec(part.data), [part.data]);
  if (!spec) {
    return <div className="text-xs text-amber">Invalid plan spec.</div>;
  }
  return (
    <div>
      <p className="text-sm font-medium text-ink">{spec.goal}</p>
      {spec.revision != null && spec.revision > 0 && (
        <p className="text-[11px] text-muted">Revision {spec.revision}</p>
      )}
      <ol className="mt-2 space-y-1">
        {spec.steps.map((step) => (
          <li key={step.id} className="flex items-start gap-2 text-xs">
            <span className="mt-0.5">
              <StatusIcon status={step.status} />
            </span>
            <div className="flex-1">
              <p
                className={
                  step.status === "completed"
                    ? "text-muted line-through"
                    : "text-ink"
                }
              >
                {step.description}
              </p>
              {step.notes && (
                <p className="mt-0.5 text-[11px] text-muted">{step.notes}</p>
              )}
            </div>
          </li>
        ))}
      </ol>
    </div>
  );
}

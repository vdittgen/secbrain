/**
 * Today's Brief — AI-synthesized narrative.
 *
 * sensitivity_tier: 3
 */

import { useState } from "react";
import { RefreshCw, Sparkles } from "lucide-react";
import Card from "./Card";
import { Skeleton } from "../LoadingState";
import { useDailyBrief } from "../../hooks/useDailyBrief";
import { formatRelativeTime } from "../../utils/timeFormat";

function DailyBrief() {
  const { data, isLoading, regenerate } = useDailyBrief();
  const [regenerating, setRegenerating] = useState(false);

  const onRegenerate = async () => {
    setRegenerating(true);
    try {
      await regenerate();
    } finally {
      setRegenerating(false);
    }
  };

  return (
    <Card
      title="Today's Brief"
      icon={<Sparkles className="h-4 w-4 text-indigo" strokeWidth={1.6} />}
      className="h-full"
      style={{ background: "radial-gradient(circle at 100% 0%, var(--indigo-soft), transparent 70%), var(--surface)" }}
      meta={
        data?.generated_at && (
          <button
            type="button"
            onClick={onRegenerate}
            disabled={regenerating}
            className="flex items-center gap-1.5 text-[11px] text-muted transition-colors hover:text-ink disabled:opacity-50"
            aria-label="Regenerate brief"
          >
            <span>
              Generated {formatRelativeTime(data.generated_at)}
            </span>
            <RefreshCw
              className={`h-3 w-3 ${regenerating ? "animate-spin" : ""}`}
              strokeWidth={1.6}
            />
          </button>
        )
      }
    >
      {isLoading && !data ? (
        <div className="space-y-2">
          <Skeleton className="h-4 w-3/4" />
          <Skeleton className="h-4 w-5/6" />
          <Skeleton className="h-4 w-1/2" />
        </div>
      ) : data ? (
        <p className="text-[15px] leading-relaxed text-ink">{data.brief}</p>
      ) : (
        <p className="py-2 text-sm text-muted">
          Run the pipeline to generate today's brief.
        </p>
      )}
    </Card>
  );
}

export default DailyBrief;

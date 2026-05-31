/**
 * Open-loop list — unanswered messages + commitments inside a domain.
 *
 * Phase 2 sources only pending replies (filtered by domain bucket
 * server-side). Each row shows an age badge ("6d unanswered") and
 * a `[Draft reply]` action that routes to /chat with a prefilled
 * draft prompt.
 *
 * sensitivity_tier: 2
 */

import { useNavigate } from "react-router-dom";
import { ArrowRight } from "lucide-react";
import type { DomainOpenLoop } from "../../../hooks/useDomainSummary";
import { buildReplyContext } from "../../../hooks/useReplyContext";

function ageBadge(days: number): string {
  if (days <= 0) return "today";
  if (days === 1) return "1d";
  if (days <= 6) return `${days}d`;
  if (days <= 13) return "1w+";
  return `${Math.floor(days / 7)}w+`;
}

interface OpenLoopListProps {
  readonly loops: ReadonlyArray<DomainOpenLoop>;
}

function OpenLoopList({ loops }: OpenLoopListProps) {
  const navigate = useNavigate();

  if (loops.length === 0) {
    return (
      <p className="py-3 text-center text-xs text-muted">
        No open loops — you're caught up here.
      </p>
    );
  }

  return (
    <ul className="space-y-1.5">
      {loops.map((loop) => (
        <li
          key={loop.id}
          className="flex items-start gap-2 rounded-2 bg-bg-2 px-3 py-2"
        >
          <span className="mt-0.5 shrink-0 rounded-pill bg-surface px-1.5 py-0.5 text-[10px] text-muted">
            {ageBadge(loop.age_days)}
          </span>
          <div className="min-w-0 flex-1">
            <p className="truncate text-xs text-ink">{loop.label}</p>
            {loop.context && (
              <p className="truncate text-[11px] text-muted">
                {loop.context}
              </p>
            )}
          </div>
          {loop.suggested_action && (
            <button
              type="button"
              onClick={() =>
                navigate("/chat", {
                  state: {
                    prefilled: `${loop.suggested_action}: ${loop.label} — ${loop.context}`,
                    autoSubmit: true,
                    replyContext: buildReplyContext({
                      source: loop.source,
                      message_id: loop.message_id,
                      contact_name: loop.contact_name,
                    }),
                  },
                })
              }
              className="flex shrink-0 items-center gap-1 rounded-2 bg-indigo-soft px-2 py-1 text-[10px] text-indigo transition-colors hover:bg-indigo-tint"
            >
              {loop.suggested_action}
              <ArrowRight className="h-3 w-3" strokeWidth={1.6} />
            </button>
          )}
        </li>
      ))}
    </ul>
  );
}

export default OpenLoopList;

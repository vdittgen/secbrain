/**
 * Today board — the dashboard's prioritized "what now" surface.
 *
 * Three columns side-by-side (or stacked on narrow screens):
 *   - Now: schedule slots straddling the current time.
 *   - Up Next: the next few slots (events, tasks, habits).
 *   - Today's loops: highest-importance pending replies.
 *
 * Replaces the previous DailyScheduleWidget + the pending-replies half
 * of Active Threads in one composition — pending replies live in
 * /inbox; this column is a small "you also need to act on these" prompt.
 *
 * sensitivity_tier: 3
 */

import { useEffect } from "react";
import { useNavigate } from "react-router-dom";
import {
  ArrowRight,
  CalendarClock,
  RefreshCw,
} from "lucide-react";
import { Skeleton } from "../../LoadingState";
import { SlotRow } from "./SlotRow";
import { useTodayBoard, type TodayLoop } from "../../../hooks/useTodayBoard";
import {
  regenerateDailySchedule,
  type ScheduleSlot,
} from "../../../hooks/useDailySchedule";
import { buildReplyContext } from "../../../hooks/useReplyContext";
import { useState } from "react";

function LoopRow({ loop }: { readonly loop: TodayLoop }) {
  const navigate = useNavigate();
  const name = loop.contact_name ?? loop.label;
  const initial = name.charAt(0).toUpperCase();
  const ageLabel =
    loop.age_days <= 0
      ? "today"
      : loop.age_days === 1
        ? "1 day ago"
        : `${loop.age_days} days ago`;

  return (
    <li className="list-none">
      <div
        className="grid grid-cols-[36px_1fr_auto] gap-3.5 rounded-[12px] border border-[oklch(0.90_0.04_25)] p-3.5 -mx-2 mb-2 items-center transition-all"
        style={{ background: "linear-gradient(135deg, var(--danger-soft) 0%, var(--surface) 70%)" }}
      >
        <div
          className="flex h-9 w-9 items-center justify-center rounded-full text-[14px] font-semibold text-white"
          style={{
            background: "linear-gradient(135deg, var(--danger), oklch(0.55 0.18 30))",
            boxShadow: "0 1px 0 oklch(1 0 0 / 0.2) inset, 0 2px 8px oklch(0.60 0.22 25 / 0.25)",
          }}
        >
          {initial}
        </div>
        <div className="min-w-0">
          <div className="flex items-center gap-2 text-[14.5px] font-semibold text-ink flex-wrap">
            {name}{" "}
            <span className="rounded-pill bg-personal-tint px-2 py-0.5 text-[11px] text-personal-ink font-medium">
              {loop.source === "whatsapp" ? "WhatsApp" : loop.source ?? "Message"}
            </span>
          </div>
          {loop.context && (
            <div className="mt-1 text-[13px] italic text-ink-2">{loop.context}</div>
          )}
          <div className="mt-2 flex items-center gap-2.5 text-[11.5px] text-muted font-medium">
            <span style={{ color: "oklch(0.40 0.14 25)", fontWeight: 600 }}>
              ⚠ Importance {loop.importance}/10
            </span>
            <span>·</span>
            <span>{ageLabel}</span>
          </div>
        </div>
        <div className="flex gap-1.5 shrink-0">
          <button
            type="button"
            onClick={() =>
              navigate("/chat", {
                state: {
                  prefilled: `${loop.label} — context: ${loop.context}`,
                  autoSubmit: true,
                  replyContext: buildReplyContext({
                    source: loop.source,
                    message_id: loop.message_id,
                    contact_name: loop.contact_name,
                  }),
                },
              })
            }
            className="flex items-center gap-1 rounded-2 bg-indigo-soft px-2 py-1 text-[10px] text-indigo hover:bg-indigo-tint transition-colors"
          >
            Draft reply <ArrowRight className="h-3 w-3" strokeWidth={1.6} />
          </button>
        </div>
      </div>
    </li>
  );
}

function SectionHeader({
  title,
  dotColor,
  haloColor,
  trailingLink,
}: {
  readonly title: string;
  readonly dotColor: string;
  readonly haloColor: string;
  readonly trailingLink?: { label: string; onClick: () => void } | undefined;
}) {
  return (
    <div className="flex items-center gap-2 pb-1">
      <span
        className={`h-[7px] w-[7px] rounded-full ${dotColor}`}
        style={{ boxShadow: `0 0 0 3px var(--${haloColor})` }}
      />
      <h4 className="text-[11px] font-medium uppercase tracking-[0.06em] text-muted">
        {title}
      </h4>
      {trailingLink && (
        <>
          <span className="flex-1" />
          <button
            type="button"
            onClick={trailingLink.onClick}
            className="text-[11px] text-muted transition-colors hover:text-ink"
          >
            {trailingLink.label}
          </button>
        </>
      )}
    </div>
  );
}

function TodayBoard() {
  const board = useTodayBoard();
  const navigate = useNavigate();
  const [replanning, setReplanning] = useState(false);

  // Refetch when the proactive cycle completes — the loops column
  // reflects pending replies, which are written by ProactiveIntelligence.
  useEffect(() => {
    const handler = () => board.refetch();
    window.addEventListener("arandu:proactive-refreshed", handler);
    window.addEventListener("arandu:pipeline-refreshed", handler);
    return () => {
      window.removeEventListener("arandu:proactive-refreshed", handler);
      window.removeEventListener("arandu:pipeline-refreshed", handler);
    };
  }, [board]);

  const onReplan = async () => {
    setReplanning(true);
    try {
      await regenerateDailySchedule();
      board.refetch();
    } finally {
      setReplanning(false);
    }
  };

  const data = board.data;
  const now = (data?.now ?? []) as ReadonlyArray<ScheduleSlot>;
  const upNext = (data?.up_next ?? []) as ReadonlyArray<ScheduleSlot>;
  const loops = data?.todays_loops ?? [];
  const empty = now.length === 0 && upNext.length === 0 && loops.length === 0;
  const totalCount = now.length + upNext.length + loops.length;

  if (board.isLoading && board.data === null) {
    return (
      <div className="rounded-4 border border-hairline bg-surface p-6 shadow-1">
        <div className="mb-4 flex items-center gap-2">
          <CalendarClock className="h-5 w-5 text-indigo" strokeWidth={1.6} />
          <h3 className="text-[22px] font-semibold leading-tight text-ink">
            Today
          </h3>
        </div>
        <div className="space-y-2">
          <Skeleton className="h-10 w-full" />
          <Skeleton className="h-10 w-full" />
          <Skeleton className="h-10 w-full" />
        </div>
      </div>
    );
  }

  return (
    <div className="rounded-4 border border-hairline bg-surface p-6 shadow-1">
      {/* Header */}
      <div className="mb-4 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <h3 className="text-[22px] font-semibold leading-tight text-ink">
            Today
          </h3>
          {totalCount > 0 && (
            <span className="rounded-pill bg-bg-2 px-2.5 py-0.5 text-[13px] font-medium text-muted">
              {now.length + upNext.length} active{loops.length > 0 ? ` · ${loops.length} loop${loops.length !== 1 ? "s" : ""}` : ""}
            </span>
          )}
        </div>
        <button
          type="button"
          onClick={onReplan}
          disabled={replanning}
          className="flex items-center gap-1.5 rounded-pill border border-hairline-2 bg-surface px-3 py-1.5 text-[13px] font-medium text-ink shadow-1 transition-colors hover:bg-bg-2 disabled:opacity-60"
          title="Regenerate today's plan"
        >
          <RefreshCw
            className={`h-3.5 w-3.5 ${replanning ? "animate-spin" : ""}`}
            strokeWidth={1.6}
          />
          Replan
        </button>
      </div>

      {/* Narrative / rationale */}
      {data?.rationale && (
        <p className="mb-4 text-sm text-muted">
          {data.rationale}
        </p>
      )}

      {empty ? (
        <p className="py-4 text-center text-xs text-muted">
          No plan yet. Click Replan to generate today's schedule.
        </p>
      ) : (
        <div className="space-y-5">
          {/* Now section */}
          {now.length > 0 && (
            <section>
              <SectionHeader title="Now" dotColor="bg-indigo" haloColor="indigo-soft" />
              <ul className="mt-1 space-y-0">
                {now.map((slot, idx) => (
                  <SlotRow
                    key={`now-${slot.ref_id}-${idx}`}
                    slot={slot}
                    onRefetch={board.refetch}
                    isNow
                  />
                ))}
              </ul>
            </section>
          )}

          {/* Up Next section */}
          {upNext.length > 0 && (
            <section className="border-t border-hairline pt-5">
              <SectionHeader
                title="Up Next"
                dotColor="bg-success"
                haloColor="success-soft"
                trailingLink={{ label: "View all →", onClick: () => navigate("/schedule") }}
              />
              <ul className="mt-1 space-y-0">
                {upNext.map((slot, idx) => (
                  <SlotRow
                    key={`next-${slot.ref_id}-${idx}`}
                    slot={slot}
                    onRefetch={board.refetch}
                  />
                ))}
              </ul>
            </section>
          )}

          {/* Today's loops */}
          {loops.length > 0 && (
            <section className="border-t border-hairline pt-5">
              <SectionHeader
                title="Today's Loops"
                dotColor="bg-danger"
                haloColor="danger-soft"
                trailingLink={{ label: "Open inbox →", onClick: () => navigate("/inbox") }}
              />
              <ul className="mt-1 space-y-0">
                {loops.slice(0, 3).map((loop) => (
                  <LoopRow key={loop.id} loop={loop} />
                ))}
              </ul>
            </section>
          )}
        </div>
      )}
    </div>
  );
}

export default TodayBoard;

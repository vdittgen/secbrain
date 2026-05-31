/**
 * Daily schedule widget — vertical timeline of today's plan.
 *
 * Reads ``_schedule_suggestions`` via ``get_daily_schedule``. Fixed
 * events render as immovable blocks; tasks render with a checkbox;
 * habits render with a goal-anchored subtitle. A left-edge color
 * stripe shows the slot's category (personal/life/work). "Replan"
 * fires the LLM scheduler and persists a new plan.
 *
 * sensitivity_tier: 2
 */

import { useState } from "react";
import { Calendar, CheckCircle2, RefreshCw, Repeat } from "lucide-react";
import Card from "../Card";
import { Skeleton } from "../../LoadingState";
import {
  regenerateDailySchedule,
  useDailySchedule,
  type ScheduleSlot,
} from "../../../hooks/useDailySchedule";
import { toggleTaskDone } from "../../../hooks/useTasks";
import type { GoalCategory } from "../../../hooks/useGoals";

function categoryDot(category: GoalCategory | null): string {
  if (category === "work") return "bg-work-ink";
  if (category === "life") return "bg-personal-ink";
  if (category === "personal") return "bg-personal-ink";
  return "bg-hairline-2";
}

function fmtTime(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

function SlotRow({
  slot,
  onRefetch,
}: {
  readonly slot: ScheduleSlot;
  readonly onRefetch: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const onCheck = async () => {
    if (slot.kind !== "task") return;
    setBusy(true);
    try {
      await toggleTaskDone(slot.ref_id);
      onRefetch();
    } finally {
      setBusy(false);
    }
  };

  const icon =
    slot.kind === "event" ? (
      <Calendar className="h-3.5 w-3.5 text-muted" strokeWidth={1.6} />
    ) : slot.kind === "habit" ? (
      <Repeat className="h-3.5 w-3.5 text-muted" strokeWidth={1.6} />
    ) : (
      <CheckCircle2 className="h-3.5 w-3.5 text-muted" strokeWidth={1.6} />
    );

  return (
    <li className="flex gap-3">
      <div
        className={`mt-1 w-1 self-stretch rounded-pill ${categoryDot(
          slot.category,
        )}`}
      />
      <div className="flex-1 rounded-2 border border-hairline bg-surface p-2">
        <div className="flex items-center justify-between gap-2">
          <div className="flex items-center gap-2">
            {slot.kind === "task" ? (
              <button
                type="button"
                onClick={onCheck}
                disabled={busy}
                className="flex h-3.5 w-3.5 items-center justify-center rounded-1 border border-hairline bg-bg"
                title="Mark done"
              />
            ) : (
              icon
            )}
            <span className="text-xs font-medium text-ink">
              {slot.title}
            </span>
          </div>
          <span className="text-[10px] text-muted">
            {fmtTime(slot.start)} – {fmtTime(slot.end)}
          </span>
        </div>
        {slot.why && (
          <p className="mt-0.5 text-[11px] text-muted">{slot.why}</p>
        )}
      </div>
    </li>
  );
}

function DailyScheduleWidget() {
  const schedule = useDailySchedule();
  const [replanning, setReplanning] = useState(false);

  const onReplan = async () => {
    setReplanning(true);
    try {
      await regenerateDailySchedule();
      schedule.refetch();
    } finally {
      setReplanning(false);
    }
  };

  const replanButton = (
    <button
      type="button"
      onClick={onReplan}
      disabled={replanning}
      className="flex items-center gap-1 text-[11px] text-muted hover:text-ink disabled:opacity-60"
    >
      <RefreshCw
        className={`h-3 w-3 ${replanning ? "animate-spin" : ""}`}
        strokeWidth={1.6}
      />
      Replan
    </button>
  );

  if (schedule.isLoading && schedule.data === null) {
    return (
      <Card
        title="Today's plan"
        icon={<Calendar className="h-4 w-4 text-indigo" strokeWidth={1.6} />}
        meta={replanButton}
      >
        <div className="space-y-2">
          {[1, 2, 3, 4].map((i) => (
            <Skeleton key={i} className="h-10 w-full" />
          ))}
        </div>
      </Card>
    );
  }

  const slots = schedule.data?.slots ?? [];

  return (
    <Card
      title="Today's plan"
      icon={<Calendar className="h-4 w-4 text-indigo" strokeWidth={1.6} />}
      meta={replanButton}
    >
      {slots.length === 0 ? (
        <p className="py-4 text-center text-xs text-muted">
          No plan yet. Click Replan to generate today's schedule.
        </p>
      ) : (
        <>
          {schedule.data?.rationale && (
            <p className="mb-3 text-[11px] italic text-muted">
              {schedule.data.rationale}
            </p>
          )}
          <ul className="space-y-2">
            {slots.map((s, idx) => (
              <SlotRow
                key={`${s.ref_id}-${idx}`}
                slot={s}
                onRefetch={schedule.refetch}
              />
            ))}
          </ul>
        </>
      )}
    </Card>
  );
}

export default DailyScheduleWidget;

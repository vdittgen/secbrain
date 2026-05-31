/**
 * Single timeline row inside the Today board.
 *
 * Shows schedule slots with goal context as an inline chip.
 * Task slots have a mark-done checkbox. No "Work on this" — the
 * schedule is a timeline for orientation, not a task launcher.
 *
 * sensitivity_tier: 2
 */

import { useState } from "react";
import { Calendar, CheckCircle2, Repeat } from "lucide-react";
import {
  type ScheduleSlot,
} from "../../../hooks/useDailySchedule";
import { toggleTaskDone } from "../../../hooks/useTasks";

function fmtTime(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

export interface SlotRowProps {
  readonly slot: ScheduleSlot;
  readonly onRefetch: () => void;
  readonly isNow?: boolean;
}

export function SlotRow({ slot, onRefetch, isNow = false }: SlotRowProps) {
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
    <li
      className={`group grid grid-cols-[20px_1fr_auto] items-center gap-2 border-t border-hairline px-3 py-2.5 transition-colors hover:bg-bg-2 ${
        isNow ? "border-l-[3px] border-l-indigo bg-indigo-tint" : ""
      }`}
    >
      {/* Column 1: icon / checkbox */}
      {slot.kind === "task" ? (
        <button
          type="button"
          onClick={onCheck}
          disabled={busy}
          className="flex h-4 w-4 items-center justify-center rounded-1 border border-hairline bg-bg"
          title="Mark done"
        />
      ) : (
        icon
      )}

      {/* Column 2: label + goal chip + why */}
      <div className="min-w-0">
        <div className="flex items-center gap-2">
          <span className="truncate text-xs font-medium text-ink">
            {slot.title}
          </span>
          {slot.goal_title && (
            <span className="shrink-0 rounded-pill bg-indigo-soft px-1.5 py-0.5 text-[10px] text-indigo">
              {slot.goal_title}
            </span>
          )}
        </div>
        {slot.why && (
          <p className="mt-0.5 text-[11px] text-muted">{slot.why}</p>
        )}
      </div>

      {/* Column 3: time */}
      <span className="shrink-0 text-[10px] text-muted">
        {fmtTime(slot.start)} – {fmtTime(slot.end)}
      </span>
    </li>
  );
}

export default SlotRow;

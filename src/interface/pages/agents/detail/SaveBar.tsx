// Sticky save-bar used by Edit mode. Shows dirty count, Discard, Save.
//
// sensitivity_tier: 1

import type { JSX } from "react";
import { Loader2, Save } from "lucide-react";

interface SaveBarProps {
  readonly dirty: boolean;
  readonly dirtyCount: number;
  readonly saving: boolean;
  readonly onDiscard: () => void;
  readonly onSave: () => void;
}

export function SaveBar({
  dirty,
  dirtyCount,
  saving,
  onDiscard,
  onSave,
}: SaveBarProps): JSX.Element | null {
  if (!dirty && !saving) return null;
  return (
    <div className="sticky bottom-0 z-10 border-t border-hairline bg-surface/95 px-4 py-2 backdrop-blur">
      <div className="flex items-center justify-between gap-3">
        <span className="text-[12px] text-muted">
          {dirtyCount} unsaved change{dirtyCount === 1 ? "" : "s"}
        </span>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={onDiscard}
            disabled={saving}
            className="rounded-md border border-hairline px-3 py-1.5 text-[12px] text-muted hover:bg-surface disabled:opacity-50"
          >
            Discard
          </button>
          <button
            type="button"
            onClick={onSave}
            disabled={saving}
            className="inline-flex items-center gap-1 rounded-md bg-indigo px-3 py-1.5 text-[12px] text-white hover:bg-indigo/90 disabled:opacity-50"
          >
            {saving
              ? <Loader2 size={12} className="animate-spin" />
              : <Save size={12} />}
            Save
          </button>
        </div>
      </div>
    </div>
  );
}

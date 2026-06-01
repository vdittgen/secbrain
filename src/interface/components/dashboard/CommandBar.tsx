/**
 * Mission Control Command Bar — Lucid "ask bar".
 *
 * Every prompt routes to /chat with autoSubmit. The Brain/Chat agent
 * decides the intent (ask vs delegate) via its tool set — if the user
 * wants a watcher/agent, the LLM calls `create_watcher` which emits a
 * `watcher_proposal` stream chunk, and the Chat page opens the wizard.
 *
 * sensitivity_tier: 2
 */

import { useCallback, useState } from "react";
import { useNavigate } from "react-router-dom";
import { ArrowRight, Sparkles } from "lucide-react";
import type { SuggestedChip } from "../../hooks/useSuggestedActions";

interface CommandBarProps {
  readonly chips: ReadonlyArray<SuggestedChip>;
  readonly loading: boolean;
}

function CommandBar({ chips, loading }: CommandBarProps) {
  const navigate = useNavigate();
  const [value, setValue] = useState("");

  const submit = useCallback(
    (prompt: string) => {
      const trimmed = prompt.trim();
      if (!trimmed) return;
      navigate("/chat", {
        state: { prefilled: trimmed, autoSubmit: true },
      });
    },
    [navigate],
  );

  return (
    <div className="space-y-3">
      <form
        className="flex items-center gap-2 rounded-3 border border-hairline bg-surface px-4 py-3 shadow-2 transition-shadow focus-within:border-indigo focus-within:shadow-glow"
        onSubmit={(e) => {
          e.preventDefault();
          submit(value);
          setValue("");
        }}
      >
        <Sparkles className="h-4 w-4 shrink-0 text-indigo" strokeWidth={1.6} />
        <input
          type="text"
          value={value}
          onChange={(e) => setValue(e.target.value)}
          placeholder="Ask Arandu… or delegate (try 'watch my inbox for…')"
          aria-label="Ask or delegate"
          className="flex-1 bg-transparent text-sm text-ink outline-none placeholder:text-muted"
        />
        <button
          type="submit"
          disabled={!value.trim()}
          aria-label="Submit"
          className="flex h-9 w-9 items-center justify-center rounded-[10px] bg-ink text-surface transition-colors hover:bg-ink-2 disabled:opacity-40"
        >
          <ArrowRight className="h-4 w-4" strokeWidth={1.6} />
        </button>
      </form>

      {!loading && chips.length > 0 && (
        <div className="flex flex-wrap gap-2 px-1">
          {chips.map((chip) => (
            <button
              key={chip.label}
              type="button"
              onClick={() => submit(chip.prefilled_prompt)}
              className="rounded-pill border border-hairline bg-surface px-3 py-1 text-xs text-muted transition-colors hover:border-indigo hover:text-ink"
            >
              {chip.label}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

export default CommandBar;

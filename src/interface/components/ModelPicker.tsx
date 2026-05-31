/**
 * Filterable model picker for the agent override field.
 *
 * Accepts free typing (so users can paste a model id that the endpoint
 * doesn't enumerate) while also offering a filtered dropdown of models
 * returned by ``list_available_models``. The dropdown loads on first
 * focus, keeping page initial render cheap.
 *
 * Empty value = "use the route default". The placeholder reflects this.
 *
 * sensitivity_tier: 1 (operational metadata only)
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { ChevronDown, Loader2 } from "lucide-react";
import { useAvailableModels } from "../hooks/useAvailableModels";

interface ModelPickerProps {
  readonly value: string;
  readonly onChange: (next: string) => void;
  readonly route: string;
  readonly placeholder?: string;
  readonly disabled?: boolean;
  readonly id?: string;
}

const MAX_VISIBLE = 50;

export default function ModelPicker({
  value,
  onChange,
  route,
  placeholder = "Override model name (blank = use route default)",
  disabled,
  id,
}: ModelPickerProps) {
  const { models, loading, error, ensureLoaded } = useAvailableModels(route);
  const [open, setOpen] = useState(false);
  const [highlight, setHighlight] = useState(0);
  const rootRef = useRef<HTMLDivElement>(null);

  const filtered = filterModels(models, value, MAX_VISIBLE);

  // Reset highlight when filter changes; clamp to filtered length.
  useEffect(() => {
    if (highlight >= filtered.length) setHighlight(0);
  }, [filtered.length, highlight]);

  // Click outside closes the dropdown.
  useEffect(() => {
    if (!open) return;
    const handleClick = (event: MouseEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, [open]);

  const handleFocus = useCallback(() => {
    setOpen(true);
    void ensureLoaded();
  }, [ensureLoaded]);

  const handleKeyDown = useCallback(
    (event: React.KeyboardEvent<HTMLInputElement>) => {
      if (event.key === "ArrowDown") {
        event.preventDefault();
        setOpen(true);
        setHighlight((h) => Math.min(h + 1, filtered.length - 1));
      } else if (event.key === "ArrowUp") {
        event.preventDefault();
        setHighlight((h) => Math.max(h - 1, 0));
      } else if (event.key === "Enter" && open && filtered[highlight]) {
        event.preventDefault();
        onChange(filtered[highlight]);
        setOpen(false);
      } else if (event.key === "Escape") {
        setOpen(false);
      }
    },
    [filtered, highlight, onChange, open],
  );

  return (
    <div ref={rootRef} className="relative flex-1">
      <div className="relative">
        <input
          id={id}
          type="text"
          value={value}
          onChange={(e) => {
            onChange(e.target.value);
            setOpen(true);
          }}
          onFocus={handleFocus}
          onKeyDown={handleKeyDown}
          placeholder={placeholder}
          spellCheck={false}
          autoComplete="off"
          disabled={disabled}
          className="w-full rounded-md border border-hairline bg-surface px-2 py-1.5 pr-7 font-mono text-[12px] text-ink focus:border-indigo focus:outline-none disabled:opacity-50"
        />
        <button
          type="button"
          tabIndex={-1}
          onClick={() => {
            if (disabled) return;
            setOpen((v) => !v);
            void ensureLoaded();
          }}
          className="absolute right-1 top-1/2 -translate-y-1/2 p-1 text-muted hover:text-ink disabled:opacity-50"
          aria-label="Toggle model list"
          disabled={disabled}
        >
          {loading
            ? <Loader2 strokeWidth={1.6} size={12} className="animate-spin" />
            : <ChevronDown strokeWidth={1.6} size={12} />}
        </button>
      </div>
      {open && (
        <div className="absolute left-0 right-0 top-full z-20 mt-1 max-h-64 overflow-auto rounded-md border border-hairline bg-surface shadow-lg">
          {loading && filtered.length === 0 && (
            <div className="px-2 py-2 text-[11px] text-muted">
              Loading models…
            </div>
          )}
          {!loading && error && (
            <div className="px-2 py-2 text-[11px] text-amber">
              {error} — type a model name manually
            </div>
          )}
          {!loading && !error && filtered.length === 0 && (
            <div className="px-2 py-2 text-[11px] text-muted">
              No matching models. Type to enter a custom id.
            </div>
          )}
          {filtered.map((id, idx) => (
            <button
              key={id}
              type="button"
              onMouseDown={(e) => {
                // mousedown (not click) — fires before input blur
                e.preventDefault();
                onChange(id);
                setOpen(false);
              }}
              onMouseEnter={() => setHighlight(idx)}
              className={`block w-full truncate px-2 py-1.5 text-left font-mono text-[12px] ${
                idx === highlight
                  ? "bg-indigo-soft text-ink"
                  : "text-ink/90 hover:bg-surface"
              }`}
              title={id}
            >
              {id}
            </button>
          ))}
          {models.length > filtered.length && (
            <div className="border-t border-hairline px-2 py-1 text-[10px] text-muted/80">
              {filtered.length} of {models.length} — type to filter
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function filterModels(
  models: ReadonlyArray<string>,
  query: string,
  limit: number,
): ReadonlyArray<string> {
  if (!query) return models.slice(0, limit);
  const q = query.toLowerCase();
  const matches: string[] = [];
  for (const id of models) {
    if (id.toLowerCase().includes(q)) {
      matches.push(id);
      if (matches.length >= limit) break;
    }
  }
  return matches;
}

/**
 * Inline popover for changing the active chat agent's model.
 *
 * Mounted by the `ModelStatusBadge` on the Chat page when the user
 * clicks the badge. Lets the user pick a different model and (less
 * commonly) a different route without leaving the chat surface.
 *
 * V1 skips the full Agents-page eval-modal gate: the chat agent is
 * locked, and locked agents' `update_agent_config` only accepts
 * model_override/model_route patches anyway. Eval-gate UX comes
 * later — for now we save directly and the user verifies behaviour
 * by sending a message.
 *
 * sensitivity_tier: 1 (operational metadata only)
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import { Loader2, Save, X } from "lucide-react";
import ModelPicker from "./ModelPicker";

interface AgentRow {
  readonly agent_id: string;
  readonly name: string;
  readonly config: {
    readonly resolved_model: string | null;
    readonly model_route: string;
    readonly model_override: string | null;
  };
}

interface ChatModelPopoverProps {
  readonly agent: AgentRow;
  readonly onClose: () => void;
  readonly onSaved: () => void;
}

const ROUTE_OPTIONS = ["inherit", "remote", "local"] as const;

export function ChatModelPopover({
  agent,
  onClose,
  onSaved,
}: ChatModelPopoverProps): JSX.Element {
  const [override, setOverride] = useState(agent.config.model_override ?? "");
  const [route, setRoute] = useState(agent.config.model_route);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const rootRef = useRef<HTMLDivElement>(null);

  const trimmed = override.trim();
  const normalised = trimmed === "" ? null : trimmed;
  const dirty = normalised !== (agent.config.model_override ?? null)
    || route !== agent.config.model_route;

  // Click outside closes the popover.
  useEffect(() => {
    const handle = (event: MouseEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) onClose();
    };
    document.addEventListener("mousedown", handle);
    return () => document.removeEventListener("mousedown", handle);
  }, [onClose]);

  const save = useCallback(async () => {
    setSaving(true);
    setError(null);
    try {
      await invoke("update_agent_config", {
        agentId: agent.agent_id,
        patch: { model_override: normalised, model_route: route },
      });
      onSaved();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSaving(false);
    }
  }, [agent.agent_id, normalised, route, onSaved]);

  return (
    <div
      ref={rootRef}
      className="absolute left-0 top-full z-30 mt-1 w-80 rounded-2 border border-hairline bg-surface p-3 shadow-xl"
    >
      <div className="mb-2 flex items-center justify-between">
        <div className="text-[11px] uppercase tracking-wider text-muted">
          {agent.name} model
        </div>
        <button
          type="button"
          onClick={onClose}
          className="text-muted hover:text-ink"
          aria-label="Close"
        >
          <X strokeWidth={1.6} size={12} />
        </button>
      </div>

      <div className="mb-2 text-[11px] text-muted">
        Resolved:{" "}
        <span className="font-mono text-ink/90">
          {agent.config.resolved_model ?? "default"}
        </span>
      </div>

      <label className="block text-[11px] text-muted">
        Route
        <select
          value={route}
          onChange={(e) => setRoute(e.target.value)}
          className="ml-2 rounded-md border border-hairline bg-surface px-2 py-0.5 text-[11px] text-ink"
        >
          {ROUTE_OPTIONS.map((r) => (
            <option key={r} value={r}>{r}</option>
          ))}
        </select>
      </label>

      <div className="mt-2 flex items-center gap-2">
        <ModelPicker
          value={override}
          onChange={setOverride}
          route={route}
        />
      </div>

      {error && (
        <div className="mt-2 rounded-md border border-amber/60 bg-amber-soft px-2 py-1 text-[11px] text-amber">
          {error}
        </div>
      )}

      <div className="mt-3 flex items-center justify-between gap-2">
        <span className="text-[10px] text-muted/80">
          Saved directly. Test by sending a message.
        </span>
        <button
          type="button"
          onClick={save}
          disabled={!dirty || saving}
          className="inline-flex items-center gap-1 rounded-md bg-indigo px-3 py-1 text-[12px] text-white hover:bg-indigo/90 disabled:opacity-50"
        >
          {saving
            ? <Loader2 strokeWidth={1.6} size={12} className="animate-spin" />
            : <Save strokeWidth={1.6} size={12} />}
          Save
        </button>
      </div>
    </div>
  );
}

export default ChatModelPopover;

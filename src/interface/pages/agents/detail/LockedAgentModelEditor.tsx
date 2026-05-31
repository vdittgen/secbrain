// Inline model picker for locked / built-in agents shown on the
// Agents > Overview pane. User-authored agents have the full Edit
// tab; locked agents (brain, firewalls, every system agent) only
// allow ``model_override`` and ``model_route`` patches per
// _LOCKED_AGENT_ALLOWED_KEYS in src/agents/core/config_store.py, so
// this editor sends exactly those two fields.
//
// sensitivity_tier: 1 (operational metadata only)

import { useCallback, useState } from "react";
import type { JSX } from "react";
import { invoke } from "@tauri-apps/api/core";
import { Loader2, Pencil, Save, X } from "lucide-react";

import ModelPicker from "../../../components/ModelPicker";
import type { PydanticAgentRow } from "../../../types/agents";

interface LockedAgentModelEditorProps {
  readonly row: PydanticAgentRow;
  readonly onSaved: () => void;
}

const ROUTE_OPTIONS = ["inherit", "remote", "local"] as const;

export function LockedAgentModelEditor({
  row,
  onSaved,
}: LockedAgentModelEditorProps): JSX.Element {
  const [open, setOpen] = useState(false);
  const [override, setOverride] = useState(row.config.model_override ?? "");
  const [route, setRoute] = useState(row.config.model_route);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const trimmed = override.trim();
  const normalised = trimmed === "" ? null : trimmed;
  const dirty =
    normalised !== (row.config.model_override ?? null)
    || route !== row.config.model_route;

  const reset = useCallback(() => {
    setOverride(row.config.model_override ?? "");
    setRoute(row.config.model_route);
    setError(null);
  }, [row.config.model_override, row.config.model_route]);

  const close = useCallback(() => {
    reset();
    setOpen(false);
  }, [reset]);

  const save = useCallback(async () => {
    setSaving(true);
    setError(null);
    try {
      await invoke("update_agent_config", {
        agentId: row.agent_id,
        patch: { model_override: normalised, model_route: route },
      });
      onSaved();
      setOpen(false);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  }, [row.agent_id, normalised, route, onSaved]);

  if (!open) {
    return (
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="inline-flex items-center gap-1 rounded-md border border-hairline px-2 py-1 text-[11px] text-muted hover:bg-surface hover:text-ink"
      >
        <Pencil size={11} />
        Change model
      </button>
    );
  }

  return (
    <div className="rounded-md border border-indigo/40 bg-surface p-3">
      <div className="mb-2 flex items-center justify-between">
        <div className="text-[11px] uppercase tracking-wider text-muted">
          Change model
        </div>
        <button
          type="button"
          onClick={close}
          className="text-muted hover:text-ink"
          aria-label="Cancel"
        >
          <X size={12} />
        </button>
      </div>

      <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
        <label className="block text-[11px] text-muted">
          Route
          <select
            value={route}
            onChange={(e) => setRoute(e.target.value)}
            className="mt-1 block w-full rounded-md border border-hairline bg-surface px-2 py-1 text-[12px] text-ink"
          >
            {ROUTE_OPTIONS.map((r) => (
              <option key={r} value={r}>{r}</option>
            ))}
          </select>
        </label>
        <div className="block">
          <span className="text-[11px] text-muted">
            Model override (blank = global default)
          </span>
          <div className="mt-1">
            <ModelPicker
              value={override}
              onChange={setOverride}
              route={route || "inherit"}
              placeholder="e.g. llama3.1:70b"
            />
          </div>
        </div>
      </div>

      {error && (
        <div className="mt-2 rounded-md border border-amber/60 bg-amber/10 px-2 py-1 text-[11px] text-amber">
          {error}
        </div>
      )}

      <div className="mt-3 flex items-center justify-end gap-2">
        <button
          type="button"
          onClick={close}
          disabled={saving}
          className="rounded-md border border-hairline px-3 py-1 text-[12px] text-muted hover:bg-surface disabled:opacity-50"
        >
          Cancel
        </button>
        <button
          type="button"
          onClick={save}
          disabled={!dirty || saving}
          className="inline-flex items-center gap-1 rounded-md bg-indigo px-3 py-1 text-[12px] text-white hover:bg-indigo/90 disabled:opacity-50"
        >
          {saving
            ? <Loader2 size={12} className="animate-spin" />
            : <Save size={12} />}
          Save
        </button>
      </div>
    </div>
  );
}

export default LockedAgentModelEditor;

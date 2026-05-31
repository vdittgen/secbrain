// Hook: hold a user agent's edit draft, expose dirty-tracking, and
// route Save through the same gates the legacy `UserAgentRow` used
// (prompt-engineer offer + model-change eval modal).
//
// sensitivity_tier: 1

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import type {
  PydanticAgentPatch,
  PydanticAgentResponse,
  PydanticAgentRow,
} from "../../../types/agents";
import { setsEqual } from "../shared/utils";

export type SaveGate =
  | { kind: "none" }
  | { kind: "prompt_engineer" }
  | { kind: "model_change_eval" };

export interface AgentDraft {
  readonly prompt: string;
  readonly modelRoute: string;
  readonly modelOverride: string;
  readonly enabledTools: ReadonlyArray<string>;
  readonly deliveryTools: ReadonlyArray<string>;
  readonly enabledSkills: ReadonlyArray<string>;
}

export interface UseAgentDraft {
  readonly draft: AgentDraft;
  setPrompt: (next: string) => void;
  setModelRoute: (next: string) => void;
  setModelOverride: (next: string) => void;
  setEnabledTools: (next: ReadonlyArray<string>) => void;
  setDeliveryTools: (next: ReadonlyArray<string>) => void;
  setEnabledSkills: (next: ReadonlyArray<string>) => void;
  readonly dirty: boolean;
  readonly dirtyCount: number;
  readonly saving: boolean;
  readonly error: string | null;
  readonly normalisedOverride: string | null;
  readonly addingOrChangingOverride: boolean;
  readonly promptChanged: boolean;
  /** Mark the prompt-engineer offer as skipped for the rest of the
   * session, so re-saving with a still-changed prompt doesn't re-open
   * the offer. */
  skipPromptOffer: () => void;
  /** Returns the gate that should fire next, or `none` to mean save
   * directly. The caller wires the gate to its modals and calls
   * `commit()` once they're satisfied. */
  decideGate: () => SaveGate;
  /** Persist the current (or override-from-modal) draft. */
  commit: (
    finalOverride?: string | null,
    finalRoute?: string,
  ) => Promise<void>;
  /** Replace the draft with the row's persisted values (used after a
   * successful save bubble-up from the parent). */
  reset: (row: PydanticAgentRow) => void;
  clearError: () => void;
}

export function useAgentDraft(
  row: PydanticAgentRow,
  onSaved: () => void,
  pollEval: () => void,
): UseAgentDraft {
  const [prompt, setPrompt] = useState(row.config.system_prompt);
  const [modelRoute, setModelRoute] = useState(row.config.model_route);
  const [modelOverride, setModelOverride] = useState(
    row.config.model_override ?? "",
  );
  const [enabledTools, setEnabledTools] = useState<ReadonlyArray<string>>(
    row.config.enabled_tools,
  );
  const [deliveryTools, setDeliveryTools] = useState<ReadonlyArray<string>>(
    row.config.delivery_tools,
  );
  const [enabledSkills, setEnabledSkills] = useState<ReadonlyArray<string>>(
    row.config.enabled_skills,
  );
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const promptOfferSkippedRef = useRef(false);

  // Re-seed the draft when the selected agent changes underneath us.
  const lastRowIdRef = useRef(row.agent_id);
  useEffect(() => {
    if (lastRowIdRef.current === row.agent_id) return;
    lastRowIdRef.current = row.agent_id;
    setPrompt(row.config.system_prompt);
    setModelRoute(row.config.model_route);
    setModelOverride(row.config.model_override ?? "");
    setEnabledTools(row.config.enabled_tools);
    setDeliveryTools(row.config.delivery_tools);
    setEnabledSkills(row.config.enabled_skills);
    setError(null);
    promptOfferSkippedRef.current = false;
  }, [row]);

  const trimmedOverride = modelOverride.trim();
  const normalisedOverride = trimmedOverride === "" ? null : trimmedOverride;
  const overrideChanged =
    normalisedOverride !== (row.config.model_override ?? null);
  const addingOrChangingOverride =
    overrideChanged && normalisedOverride !== null;

  const promptChanged = prompt !== row.config.system_prompt;
  const routeChanged = modelRoute !== row.config.model_route;
  const enabledChanged = useMemo(
    () => !setsEqual(enabledTools, row.config.enabled_tools),
    [enabledTools, row.config.enabled_tools],
  );
  const deliveryChanged = useMemo(
    () => !setsEqual(deliveryTools, row.config.delivery_tools),
    [deliveryTools, row.config.delivery_tools],
  );
  const skillsChanged = useMemo(
    () => !setsEqual(enabledSkills, row.config.enabled_skills),
    [enabledSkills, row.config.enabled_skills],
  );

  const dirtyCount = [
    promptChanged, overrideChanged, routeChanged, enabledChanged,
    deliveryChanged, skillsChanged,
  ].filter(Boolean).length;
  const dirty = dirtyCount > 0;

  const decideGate = useCallback((): SaveGate => {
    if (addingOrChangingOverride) return { kind: "model_change_eval" };
    if (promptChanged && !promptOfferSkippedRef.current) {
      return { kind: "prompt_engineer" };
    }
    return { kind: "none" };
  }, [addingOrChangingOverride, promptChanged]);

  const skipPromptOffer = useCallback(() => {
    promptOfferSkippedRef.current = true;
  }, []);

  const commit = useCallback(async (
    finalOverride?: string | null,
    finalRoute?: string,
  ) => {
    setSaving(true);
    setError(null);
    try {
      const overrideToSave = finalOverride !== undefined
        ? finalOverride
        : normalisedOverride;
      const routeToSave = finalRoute ?? modelRoute;
      if (finalOverride !== undefined) {
        setModelOverride(finalOverride ?? "");
      }
      if (finalRoute && finalRoute !== modelRoute) {
        setModelRoute(finalRoute);
      }
      const patch: PydanticAgentPatch = {
        system_prompt: prompt,
        model_route: routeToSave,
        model_override: overrideToSave,
      };
      if (enabledChanged) patch.enabled_tools = [...enabledTools];
      if (deliveryChanged) patch.delivery_tools = [...deliveryTools];
      if (skillsChanged) patch.enabled_skills = [...enabledSkills];
      await invoke<PydanticAgentResponse>("update_agent_config", {
        agentId: row.agent_id,
        patch,
      });
      onSaved();
      pollEval();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  }, [
    prompt, modelRoute, normalisedOverride, row.agent_id, onSaved, pollEval,
    enabledChanged, enabledTools, deliveryChanged, deliveryTools,
    skillsChanged, enabledSkills,
  ]);

  const reset = useCallback((next: PydanticAgentRow) => {
    setPrompt(next.config.system_prompt);
    setModelRoute(next.config.model_route);
    setModelOverride(next.config.model_override ?? "");
    setEnabledTools(next.config.enabled_tools);
    setDeliveryTools(next.config.delivery_tools);
    setEnabledSkills(next.config.enabled_skills);
    setError(null);
    promptOfferSkippedRef.current = false;
  }, []);

  const clearError = useCallback(() => setError(null), []);

  return {
    draft: { prompt, modelRoute, modelOverride, enabledTools, deliveryTools, enabledSkills },
    setPrompt,
    setModelRoute,
    setModelOverride,
    setEnabledTools,
    setDeliveryTools,
    setEnabledSkills,
    dirty,
    dirtyCount,
    saving,
    error,
    normalisedOverride,
    addingOrChangingOverride,
    promptChanged,
    skipPromptOffer,
    decideGate,
    commit,
    reset,
    clearError,
  };
}

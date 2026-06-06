/**
 * Post-onboarding follow-up: enable each connector the user picked on
 * the wizard, in the background, after the wizard has dismissed.
 *
 * The wizard saves `initial_connectors` + `onboarding_followup_pending`
 * to settings and unmounts; this hook (mounted in App once we're past
 * onboarding) does the slow `toggle_connector` work, collects any
 * missing-permission responses, and clears the pending flag when done.
 *
 * Each `toggle_connector` call internally runs the connector's initial
 * sync AND the full staging→intermediate→marts pipeline + ChromaDB
 * reindex. Running 4 of those serially is what made onboarding feel
 * stuck (~5 min for a fresh apple-* setup). Hoisting that off the
 * wizard's click handler is what makes the "Open Arandu" experience
 * atomic — the user lands on the dashboard immediately and watches the
 * setup progress in the AmbientBar.
 *
 * Persisted state: `onboarding_followup_pending` in settings. The hook
 * resumes if the user closes the app mid-flow.
 *
 * sensitivity_tier: 1 (orchestrates IPC; no direct user-data access).
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import { dedupInvoke } from "../utils/requestDedup";

export interface PendingPermission {
  readonly connectorId: string;
  readonly connectorName: string;
  readonly permissionKey: string;
  readonly permissionLabel: string;
}

interface ToggleConnectorResponse {
  readonly status: string;
  readonly connector_id: string;
  readonly missing?: ReadonlyArray<{
    readonly type: string;
    readonly key: string;
    readonly label: string;
    readonly action: string;
  }>;
}

interface CatalogEntry {
  readonly connector_id: string;
  readonly name: string;
  readonly enabled: boolean;
}

interface BootSettings {
  readonly onboarding_followup_pending?: boolean;
  readonly initial_connectors?: readonly string[];
  readonly [key: string]: unknown;
}

export interface OnboardingFollowupState {
  /** True while we're iterating through `toggle_connector` calls. */
  readonly running: boolean;
  /** Connectors completed so far in this run. */
  readonly done: number;
  /** Total connectors to process in this run. */
  readonly total: number;
  /** The connector currently being toggled, if any. */
  readonly current: string | null;
  /** Missing permissions collected across all toggle calls. */
  readonly pendingPermissions: readonly PendingPermission[];
  /** Dismiss the surfaced pending-permissions banner. */
  readonly dismissPendingPermissions: () => void;
}

export function useOnboardingFollowup(): OnboardingFollowupState {
  const [running, setRunning] = useState(false);
  const [done, setDone] = useState(0);
  const [total, setTotal] = useState(0);
  const [current, setCurrent] = useState<string | null>(null);
  const [pendingPermissions, setPendingPermissions] = useState<
    readonly PendingPermission[]
  >([]);

  // The follow-up should only fire once per app lifetime. Without this
  // guard, React 18 strict-mode's double-invoke of useEffect would
  // start two parallel toggle loops, doubling the work and racing on
  // the settings flag.
  const startedRef = useRef(false);
  // Cancellation lives in a ref (not an effect-local `let`) so StrictMode's
  // dev-only mount→unmount→remount cycle can't permanently abort the single
  // in-flight run. The cleanup sets it true, but the immediately-following
  // remount re-arms it to false before `run()`'s first `await` resolves.
  // Without this, the double-invoke cancels the follow-up forever, leaving
  // `onboarding_followup_pending` stuck true and connectors never enabled.
  const cancelledRef = useRef(false);

  useEffect(() => {
    cancelledRef.current = false;
    if (startedRef.current) {
      return () => {
        cancelledRef.current = true;
      };
    }
    startedRef.current = true;

    // Ordering contract for the post-wizard sequence:
    //   1. Wizard `handleFinish` awaits `update_settings(...,
    //      onboarding_followup_pending: true)` before calling
    //      onComplete(). So this hook always reads the just-saved
    //      flag, never the stale pre-wizard state.
    //   2. Connectors are toggled SEQUENTIALLY so each Python
    //      subprocess gets exclusive Kuzu write access — `toggle_connector`
    //      runs the full staging→intermediate→marts pipeline + ChromaDB
    //      reindex internally, and concurrent Kuzu writers would
    //      deadlock on the file lock.
    //   3. Already-enabled connectors are SKIPPED to keep the loop
    //      idempotent if the user quits mid-flow and relaunches —
    //      otherwise we'd re-run the entire pipeline for every
    //      connector that already finished. (Also defends against
    //      `initial_connectors` accidentally including "whatsapp",
    //      which the wizard has already toggled on slide 5.)
    //   4. The `onboarding_followup_pending` flag is only cleared
    //      AFTER the loop completes, by re-reading settings with
    //      `dedupInvoke` first so we merge with any user changes
    //      made during the (potentially-minutes-long) loop.
    const run = async () => {
      let settings: BootSettings;
      try {
        settings = await dedupInvoke<BootSettings>("get_settings");
      } catch {
        return;
      }
      if (cancelledRef.current) return;
      if (!settings.onboarding_followup_pending) return;
      const ids = settings.initial_connectors ?? [];

      // Fetch catalog up front so we can both resolve display names
      // and filter out already-enabled connectors.
      let catalog: readonly CatalogEntry[] = [];
      try {
        catalog = await dedupInvoke<readonly CatalogEntry[]>(
          "get_connector_catalog",
        );
      } catch {
        // Empty catalog → no name lookup, no skip filtering. We'll
        // still attempt every toggle; the worst case is a redundant
        // pipeline rebuild on resume, not incorrectness.
      }
      const byId = new Map(catalog.map((e) => [e.connector_id, e]));
      const remaining = ids.filter((id) => !byId.get(id)?.enabled);

      const clearFlag = async () => {
        try {
          const latest = await dedupInvoke<BootSettings>("get_settings");
          await invoke("update_settings", {
            settings: { ...latest, onboarding_followup_pending: false },
          });
        } catch (err) {
          console.error("Failed to clear onboarding_followup_pending:", err);
        }
      };

      if (remaining.length === 0) {
        await clearFlag();
        return;
      }

      setTotal(remaining.length);
      setDone(0);
      setRunning(true);

      const collected: PendingPermission[] = [];
      for (const id of remaining) {
        if (cancelledRef.current) return;
        const connectorName = byId.get(id)?.name ?? id;
        setCurrent(connectorName);
        try {
          const response = await invoke<ToggleConnectorResponse | null>(
            "toggle_connector",
            { connectorId: id, enabled: true },
          );
          if (response?.status === "needs_setup") {
            const permission = response.missing?.find(
              (m) => m.type === "permission",
            );
            if (permission) {
              collected.push({
                connectorId: id,
                connectorName,
                permissionKey: permission.key,
                permissionLabel: permission.label,
              });
            }
          }
        } catch (err) {
          console.error(`Follow-up toggle failed for ${id}:`, err);
        }
        if (cancelledRef.current) return;
        setDone((d) => d + 1);
      }

      setCurrent(null);
      setRunning(false);
      setPendingPermissions(collected);
      await clearFlag();
    };

    run();
    return () => {
      cancelledRef.current = true;
    };
  }, []);

  const dismissPendingPermissions = useCallback(() => {
    setPendingPermissions([]);
  }, []);

  return {
    running,
    done,
    total,
    current,
    pendingPermissions,
    dismissPendingPermissions,
  };
}

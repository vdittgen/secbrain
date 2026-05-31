/**
 * Hook for fetching the model list a route's endpoint exposes.
 *
 * Lazy: the IPC fires only when ``ensureLoaded()`` is invoked (e.g. on
 * dropdown first-open) so the page initial render stays cheap. Result
 * is cached in component state for the session; callers can pass
 * ``forceRefresh`` to bypass.
 *
 * Errors are non-fatal — ``error`` is set, ``models`` stays empty,
 * and the consumer falls back to a free-text input.
 *
 * sensitivity_tier: 1 (operational metadata only)
 */

import { useCallback, useRef, useState } from "react";
import { dedupInvoke } from "../utils/requestDedup";

export interface AvailableModelsPayload {
  readonly route: string;
  readonly models: ReadonlyArray<string>;
  readonly error?: string | null;
}

export interface AvailableModelsResult {
  readonly models: ReadonlyArray<string>;
  readonly loading: boolean;
  readonly error: string | null;
  /** Trigger an IPC fetch if we haven't loaded yet (or forceRefresh). */
  readonly ensureLoaded: (forceRefresh?: boolean) => Promise<void>;
}

export function useAvailableModels(route: string): AvailableModelsResult {
  const [models, setModels] = useState<ReadonlyArray<string>>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const loadedRef = useRef<string | null>(null);

  const ensureLoaded = useCallback(
    async (forceRefresh = false) => {
      if (!forceRefresh && loadedRef.current === route) return;
      setLoading(true);
      setError(null);
      try {
        const payload = await dedupInvoke<AvailableModelsPayload>(
          "list_available_models",
          { route },
        );
        setModels(payload.models);
        if (payload.error) {
          setError(payload.error);
        }
        loadedRef.current = route;
      } catch (err) {
        setError(
          err instanceof Error ? err.message : "Failed to list models",
        );
      } finally {
        setLoading(false);
      }
    },
    [route],
  );

  return { models, loading, error, ensureLoaded };
}

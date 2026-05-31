/**
 * Hook for managing async data fetching with loading, error, and data states.
 *
 * Replaces the manual useState(loading) + useState(data) + useEffect(fetch)
 * pattern used across pages.  Each hook instance manages its own lifecycle
 * independently, enabling per-widget progressive loading.
 *
 * sensitivity_tier: N/A (UI infrastructure)
 */

import { useState, useCallback, useEffect, useRef } from "react";

type AsyncStatus = "idle" | "loading" | "loaded" | "error";

export interface AsyncDataResult<T> {
  readonly data: T | null;
  readonly status: AsyncStatus;
  readonly error: string | null;
  readonly refetch: () => void;
  readonly isLoading: boolean;
  /** ISO timestamp of the last successful fetch, or null before the first. */
  readonly lastUpdatedAt: string | null;
}

interface UseAsyncDataOptions {
  /** If true (default), fetch automatically on mount. */
  readonly immediate?: boolean;
}

/**
 * Fetch data asynchronously with lifecycle management.
 *
 * @param fetcher - Async function that returns the data.
 * @param options - Configuration (default: fetch on mount).
 * @returns Object with data, status, error, refetch, and isLoading.
 *
 * @example
 * ```tsx
 * const { data, isLoading, refetch } = useAsyncData(
 *   useCallback(() => dedupInvoke<Stats>("get_database_stats"), []),
 * );
 * ```
 */
export function useAsyncData<T>(
  fetcher: () => Promise<T>,
  options: UseAsyncDataOptions = {},
): AsyncDataResult<T> {
  const { immediate = true } = options;
  const [data, setData] = useState<T | null>(null);
  const [status, setStatus] = useState<AsyncStatus>("idle");
  const [error, setError] = useState<string | null>(null);
  const [lastUpdatedAt, setLastUpdatedAt] = useState<string | null>(null);
  const mountedRef = useRef(true);

  const execute = useCallback(async () => {
    setStatus("loading");
    setError(null);
    try {
      const result = await fetcher();
      if (mountedRef.current) {
        setData(result);
        setStatus("loaded");
        setLastUpdatedAt(new Date().toISOString());
      }
    } catch (err) {
      if (mountedRef.current) {
        const message =
          err instanceof Error
            ? err.message
            : typeof err === "string"
              ? err
              : "Unknown error";
        setError(message);
        setStatus("error");
      }
    }
  }, [fetcher]);

  useEffect(() => {
    mountedRef.current = true;
    if (immediate) {
      execute();
    }
    return () => {
      mountedRef.current = false;
    };
  }, [execute, immediate]);

  return {
    data,
    status,
    error,
    refetch: execute,
    isLoading: status === "loading",
    lastUpdatedAt,
  };
}

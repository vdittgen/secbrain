/**
 * Request deduplication utility for Tauri IPC calls.
 *
 * Prevents duplicate in-flight requests to the same command + args
 * combination.  If a request is already in flight, subsequent callers
 * receive the same Promise.  The entry is cleared once the request
 * settles (resolves or rejects).
 *
 * This is NOT a cache — it only deduplicates concurrent in-flight
 * requests.  Once a request completes, the next call will start a
 * fresh request.
 *
 * sensitivity_tier: N/A (infrastructure)
 */

import { invoke } from "@tauri-apps/api/core";

/** Map of in-flight requests keyed by command + serialized args. */
const inflight = new Map<string, Promise<unknown>>();

function makeKey(
  command: string,
  args?: Record<string, unknown>,
): string {
  return args ? `${command}:${JSON.stringify(args)}` : command;
}

/**
 * Invoke a Tauri command with in-flight deduplication.
 *
 * If an identical request (same command + args) is already in flight,
 * returns the existing Promise instead of dispatching a new one.
 *
 * @param command - The Tauri command name.
 * @param args - Optional arguments object.
 * @returns The command result.
 */
export function dedupInvoke<T>(
  command: string,
  args?: Record<string, unknown>,
): Promise<T> {
  const key = makeKey(command, args);

  const existing = inflight.get(key);
  if (existing) {
    return existing as Promise<T>;
  }

  const promise = invoke<T>(command, args).finally(() => {
    inflight.delete(key);
  });

  inflight.set(key, promise);
  return promise;
}

/**
 * Notifications hook — feeds the TopBar bell.
 *
 * Polls `get_notification_log` and derives an unread count from a
 * locally-stored "last seen" notification id (the backend has no
 * read/unread concept). Calling `markAllSeen` writes the newest id
 * to localStorage and zeroes the badge.
 *
 * sensitivity_tier: 2
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import { dedupInvoke } from "../utils/requestDedup";
import { useAsyncData, type AsyncDataResult } from "./useAsyncData";

export interface NotificationRecord {
  readonly id: string;
  readonly dedupe_key: string;
  readonly category: string;
  readonly importance_score: number;
  readonly decision: string;
  readonly delivery_status: string;
  readonly message: string;
  readonly opt_out_text: string;
  readonly error: string | null;
  readonly source_type: string;
  readonly source_id: string;
  readonly created_at: string;
}

const LAST_SEEN_KEY = "secbrain:notifications:lastSeenId";
const POLL_INTERVAL_MS = 30_000;
const FETCH_LIMIT = 20;

export interface NotificationsResult extends AsyncDataResult<readonly NotificationRecord[]> {
  readonly unreadCount: number;
  readonly markAllSeen: () => void;
}

function readLastSeen(): string | null {
  try {
    return window.localStorage.getItem(LAST_SEEN_KEY);
  } catch {
    return null;
  }
}

function writeLastSeen(id: string): void {
  try {
    window.localStorage.setItem(LAST_SEEN_KEY, id);
  } catch {
    // Swallow: storage unavailable shouldn't break the UI.
  }
}

export function useNotifications(): NotificationsResult {
  const fetcher = useCallback(
    () =>
      dedupInvoke<readonly NotificationRecord[]>("get_notification_log", {
        limit: FETCH_LIMIT,
        offset: 0,
      }),
    [],
  );
  const result = useAsyncData<readonly NotificationRecord[]>(fetcher);
  const { refetch, data } = result;

  const [lastSeenId, setLastSeenId] = useState<string | null>(() => readLastSeen());

  // Background poll — refresh the feed so the badge stays current.
  useEffect(() => {
    const id = window.setInterval(() => refetch(), POLL_INTERVAL_MS);
    return () => window.clearInterval(id);
  }, [refetch]);

  const unreadCount = useMemo(() => {
    if (!data || data.length === 0) return 0;
    if (!lastSeenId) return data.length;
    const idx = data.findIndex((n) => n.id === lastSeenId);
    return idx === -1 ? data.length : idx;
  }, [data, lastSeenId]);

  const markAllSeen = useCallback(() => {
    const top = data?.[0]?.id;
    if (!top) return;
    writeLastSeen(top);
    setLastSeenId(top);
  }, [data]);

  return { ...result, unreadCount, markAllSeen };
}

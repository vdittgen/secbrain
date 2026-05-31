/**
 * Domain summary hook — per-life-domain rollup (work / personal / health).
 *
 * Re-fetches when the domain changes, so the LifeDomains tab switcher
 * lazily loads each tab on first view.
 *
 * sensitivity_tier: 3
 */

import { useCallback } from "react";
import { dedupInvoke } from "../utils/requestDedup";
import { useAsyncData, type AsyncDataResult } from "./useAsyncData";

export type DomainName = "work" | "personal" | "health";

export type EventOrigin = "personal" | "team_awareness" | "subscribed";

export interface DomainItem {
  readonly id: string;
  readonly kind: "event" | "metric" | "note";
  readonly title: string;
  readonly subtitle: string | null;
  readonly when: string | null;
  readonly badge: string | null;
  readonly contact: string | null;
  readonly event_origin: EventOrigin | null;
}

export interface DomainOpenLoop {
  readonly id: string;
  readonly kind: string;
  readonly label: string;
  readonly context: string;
  readonly age_days: number;
  readonly suggested_action: string | null;
  readonly source?: string | null;
  readonly message_id?: string | null;
  readonly contact_name?: string | null;
}

export interface DomainSummary {
  readonly domain: DomainName;
  readonly items: ReadonlyArray<DomainItem>;
  readonly open_loops: ReadonlyArray<DomainOpenLoop>;
}

export function useDomainSummary(
  domain: DomainName,
): AsyncDataResult<DomainSummary> {
  const fetcher = useCallback(
    () => dedupInvoke<DomainSummary>("get_domain_summary", { domain }),
    [domain],
  );
  return useAsyncData<DomainSummary>(fetcher);
}

// Constants shared across the Agents page panes.
//
// sensitivity_tier: 1

import type { PydanticAgentRow } from "../../../types/agents";

export const TIER_LABELS: Record<PydanticAgentRow["tier"], string> = {
  SYSTEM: "system",
  INTERACTIVE: "interactive",
  PROACTIVE: "proactive",
  BACKGROUND: "background",
};

export const TIER_DOT: Record<PydanticAgentRow["tier"], string> = {
  SYSTEM: "bg-amber",
  INTERACTIVE: "bg-indigo",
  PROACTIVE: "bg-success",
  BACKGROUND: "bg-muted",
};

export const POLL_INTERVAL_MS = 1500;
export const POLL_TIMEOUT_MS = 90_000;

export const SCHEDULE_PRESETS: ReadonlyArray<{
  readonly label: string;
  readonly cron: string | null;
}> = [
  { label: "Off", cron: null },
  { label: "Hourly", cron: "0 * * * *" },
  { label: "Every morning (8 AM)", cron: "0 8 * * *" },
  { label: "Daily at 9am", cron: "0 9 * * *" },
  { label: "Every evening (7 PM)", cron: "0 19 * * *" },
  { label: "Weekly (Mon 9am)", cron: "0 9 * * 1" },
];

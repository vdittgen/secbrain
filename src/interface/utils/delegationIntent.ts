/**
 * Lightweight intent classifier for the Mission Control Command Bar.
 *
 * Distinguishes "ask" prompts (route to /chat) from "delegate" prompts
 * (open the DelegationModal). Pure regex — no LLM call — so it stays
 * deterministic and cost-free. False negatives (treating delegation
 * as ask) are fine: the user still gets a useful chat. False positives
 * (treating ask as delegation) cost a modal dismiss, so the regex is
 * conservative.
 *
 * Schedule extraction is best-effort: "every morning" → 0 8 * * *,
 * "every hour" → 0 * * * *, otherwise we default to hourly which the
 * scheduler can tone down. The user can adjust on the modal.
 *
 * sensitivity_tier: 1
 */

export type IntentKind = "ask" | "delegate";

export interface DelegationIntent {
  readonly kind: "delegate";
  readonly prompt: string;
  readonly suggestedName: string;
  readonly suggestedCron: string;
}

export interface AskIntent {
  readonly kind: "ask";
  readonly prompt: string;
}

export type ClassifiedIntent = DelegationIntent | AskIntent;

const DELEGATION_TRIGGERS: ReadonlyArray<RegExp> = [
  /\bwatch\s+(my|the|for)\b/i,
  /\bkeep an eye on\b/i,
  /\bmonitor\b/i,
  /\bremind me (when|if|to|every)\b/i,
  /\b(notify|alert|tell|ping) me (when|if|every|once)\b/i,
  /\blet me know (when|if|once)\b/i,
  /\bevery (morning|afternoon|evening|night|day|hour|week|monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b/i,
  /\b(daily|hourly|weekly)\b/i,
  /\b(create|make|set\s*up|build|add)\s+(a\s+|an\s+|me\s+a\s+|me\s+an\s+)?(agent|watcher|automation)\b/i,
  /\b(I\s+want|I\s+need|I'd\s+like)\s+(a\s+|an\s+)?(agent|watcher|automation)\b/i,
  /\b(check|scan|track)\s+(my|the|for)\b/i,
];

const CRON_PRESETS: ReadonlyArray<{
  readonly pattern: RegExp;
  readonly cron: string;
}> = [
  // Specific weekdays
  { pattern: /\bevery monday\b/i, cron: "0 9 * * 1" },
  { pattern: /\bevery tuesday\b/i, cron: "0 9 * * 2" },
  { pattern: /\bevery wednesday\b/i, cron: "0 9 * * 3" },
  { pattern: /\bevery thursday\b/i, cron: "0 9 * * 4" },
  { pattern: /\bevery friday\b/i, cron: "0 9 * * 5" },
  // Time-of-day phrasing
  { pattern: /\bevery (morning|day)\b|\bdaily\b/i, cron: "0 8 * * *" },
  { pattern: /\bevery afternoon\b/i, cron: "0 14 * * *" },
  { pattern: /\bevery (evening|night)\b/i, cron: "0 19 * * *" },
  { pattern: /\bevery week\b|\bweekly\b/i, cron: "0 9 * * 1" },
  { pattern: /\bevery hour\b|\bhourly\b/i, cron: "0 * * * *" },
];

function summariseAsName(prompt: string): string {
  // Strip the verb prefix so the name reads as the subject.
  const stripped = prompt
    .replace(
      /^(please\s+)?(watch (my|the|for)|keep an eye on|monitor|remind me (when|if|to|every)|(notify|alert|tell|ping) me (when|if|every|once)|let me know (when|if|once)|every \w+|(create|make|set\s*up|build|add)\s+(me\s+)?(a\s+|an\s+)?(agent|watcher|automation)\s+(to|that|which|for)\s+|(I\s+want|I\s+need|I'd\s+like)\s+(a\s+|an\s+)?(agent|watcher|automation)\s+(to|that|which|for)\s+|(check|scan|track) (my|the|for))\s*/i,
      "",
    )
    .replace(/[.?!]\s*$/, "")
    .trim();
  if (!stripped) return "Watcher";
  // Title-case the first 4-6 words, max 48 chars.
  const words = stripped.split(/\s+/).slice(0, 6).join(" ");
  const truncated = words.length > 48 ? words.slice(0, 45) + "…" : words;
  return truncated.charAt(0).toUpperCase() + truncated.slice(1);
}

export function classifyIntent(prompt: string): ClassifiedIntent {
  const trimmed = prompt.trim();
  const isDelegation = DELEGATION_TRIGGERS.some((re) => re.test(trimmed));
  if (!isDelegation) {
    return { kind: "ask", prompt: trimmed };
  }
  const cronMatch = CRON_PRESETS.find((p) => p.pattern.test(trimmed));
  return {
    kind: "delegate",
    prompt: trimmed,
    suggestedName: summariseAsName(trimmed),
    suggestedCron: cronMatch?.cron ?? "0 * * * *",
  };
}

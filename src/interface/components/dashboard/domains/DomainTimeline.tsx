/**
 * Today's-shape horizontal timeline for one domain.
 *
 * Renders the user's *own* events as positioned chips along a 9 AM – 9 PM
 * strip, scaled to wall-clock time. Hover shows the title + time. Events
 * the user is not invited to (calendars shared by colleagues, holiday
 * feeds) render in collapsed "Team awareness" / "Subscribed" sections
 * below the strip — present for context but not mixed in with the
 * user's own meetings.
 *
 * No keyword-based colouring (CLAUDE.md: "no keyword-based filters");
 * every event uses the accent token. Anomaly badges are surfaced via
 * a coloured outline when a metric kind carries `badge="anomaly"`.
 *
 * sensitivity_tier: 3
 */

import { Calendar, Activity, Eye, Globe2 } from "lucide-react";
import type { DomainItem } from "../../../hooks/useDomainSummary";

const DAY_START_HOUR = 6;
const DAY_END_HOUR = 22;
const DAY_RANGE = DAY_END_HOUR - DAY_START_HOUR;

function hourFraction(iso: string | null): number | null {
  if (!iso) return null;
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return null;
  const hour = date.getHours() + date.getMinutes() / 60;
  if (hour < DAY_START_HOUR || hour > DAY_END_HOUR) return null;
  return (hour - DAY_START_HOUR) / DAY_RANGE;
}

function formatHHmm(iso: string | null): string {
  if (!iso) return "";
  try {
    return new Date(iso).toLocaleTimeString(undefined, {
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return "";
  }
}

interface SecondaryListProps {
  readonly title: string;
  readonly icon: typeof Eye;
  readonly items: ReadonlyArray<DomainItem>;
}

function SecondaryEventList({ title, icon: Icon, items }: SecondaryListProps) {
  if (items.length === 0) return null;
  return (
    <div className="mt-4 border-t border-hairline pt-3">
      <div className="mb-1.5 flex items-center gap-1.5 text-[11px] uppercase tracking-[0.06em] text-muted">
        <Icon className="h-3 w-3" strokeWidth={1.6} />
        <span>{title}</span>
        <span className="text-faint">· {items.length}</span>
      </div>
      <ul className="space-y-1">
        {items.map((item) => (
          <li
            key={item.id}
            className="flex items-baseline justify-between text-xs text-muted"
          >
            <span>{formatHHmm(item.when)}</span>
            <span className="ml-3 flex-1 truncate">{item.title}</span>
            {item.contact && (
              <span className="ml-2 shrink-0 text-[11px]">{item.contact}</span>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}

interface DomainTimelineProps {
  readonly items: ReadonlyArray<DomainItem>;
}

function DomainTimeline({ items }: DomainTimelineProps) {
  if (items.length === 0) {
    return (
      <p className="py-3 text-center text-xs text-muted">
        Nothing on the radar in this area today.
      </p>
    );
  }

  // Health metrics don't fit a time-strip; render as a compact grid.
  if (items.every((item) => item.kind === "metric")) {
    return (
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
        {items.map((item) => (
          <div
            key={item.id}
            className={`rounded-2 border px-3 py-2 ${
              item.badge === "anomaly"
                ? "border-amber/40 bg-amber-soft"
                : "border-hairline bg-bg-2"
            }`}
          >
            <div className="flex items-center gap-1.5">
              <Activity className="h-3 w-3 text-indigo" strokeWidth={1.6} />
              <span className="truncate text-xs text-ink">
                {item.title}
              </span>
            </div>
            {item.subtitle && (
              <p className="mt-0.5 text-[11px] text-muted">
                {item.subtitle}
              </p>
            )}
          </div>
        ))}
      </div>
    );
  }

  const events = items.filter((item) => item.kind === "event");
  const personal = events.filter(
    (item) => !item.event_origin || item.event_origin === "personal",
  );
  const awareness = events.filter(
    (item) => item.event_origin === "team_awareness",
  );
  const subscribed = events.filter(
    (item) => item.event_origin === "subscribed",
  );

  const positioned = personal
    .map((item) => ({ item, fraction: hourFraction(item.when) }))
    .filter((p): p is { item: DomainItem; fraction: number } =>
      p.fraction !== null,
    );

  const hasPersonal = personal.length > 0;

  return (
    <div>
      {hasPersonal ? (
        <>
          {positioned.length > 0 && (
            <div className="relative mt-1 h-10 rounded-2 border border-hairline bg-bg-2">
              {/* Tick marks at 6h intervals */}
              {[0, 0.25, 0.5, 0.75, 1].map((frac) => (
                <div
                  key={frac}
                  className="absolute top-0 h-full w-px bg-hairline"
                  style={{ left: `${frac * 100}%` }}
                />
              ))}
              {positioned.map(({ item, fraction }) => (
                <div
                  key={item.id}
                  className="absolute top-1/2 -translate-y-1/2"
                  style={{ left: `${fraction * 100}%` }}
                  title={`${formatHHmm(item.when)} · ${item.title}`}
                >
                  <div className="flex items-center gap-1 rounded-2 border border-indigo/40 bg-indigo-soft px-1.5 py-0.5 text-[10px] text-indigo">
                    <Calendar className="h-2.5 w-2.5" strokeWidth={1.6} />
                    <span className="max-w-[80px] truncate">{item.title}</span>
                  </div>
                </div>
              ))}
            </div>
          )}
          <ul className="mt-3 space-y-1">
            {personal.map((item) => (
              <li
                key={item.id}
                className="flex items-baseline justify-between text-xs"
              >
                <span className="text-muted">{formatHHmm(item.when)}</span>
                <span className="ml-3 flex-1 truncate text-ink">
                  {item.title}
                </span>
                {item.contact && (
                  <span className="ml-2 shrink-0 text-[11px] text-muted">
                    {item.contact}
                  </span>
                )}
              </li>
            ))}
          </ul>
        </>
      ) : (
        <p className="py-3 text-center text-xs text-muted">
          Nothing of yours on the radar today.
        </p>
      )}
      <SecondaryEventList
        title="Team awareness"
        icon={Eye}
        items={awareness}
      />
      <SecondaryEventList
        title="Subscribed"
        icon={Globe2}
        items={subscribed}
      />
    </div>
  );
}

export default DomainTimeline;

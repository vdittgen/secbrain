import { useState, useCallback, useEffect } from "react";
import {
  ShieldCheck,
  ShieldAlert,
  ShieldX,
  RefreshCw,
  ChevronUp,
  ChevronDown,
  Filter,
  Check,
  X,
  Loader2,
} from "lucide-react";
import { SkeletonTable } from "../components/LoadingState";
import { useAsyncData } from "../hooks/useAsyncData";
import { dedupInvoke } from "../utils/requestDedup";

// ---------------------------------------------------------------------------
// Types — mirror src-tauri/src/firewall/types.rs::AuditEntry
// ---------------------------------------------------------------------------

interface AuditEntry {
  timestamp: string;
  event_type: string;
  agent_id: string;
  decision: string;
  tier: number | null;
  payload_hash: string | null;
  previous_hash: string;
  extra: Record<string, unknown>;
}

interface RedactionMessage {
  role: string;
  content: string;
}

interface RedactionDetail {
  payload_hash: string;
  stored_at: string;
  agent_id: string;
  lane: string;
  original_messages: RedactionMessage[];
  redacted_messages: RedactionMessage[];
  placeholder_map: Record<string, string>;
}

interface RedactionDetailResponse {
  detail: RedactionDetail | null;
}

type SortDir = "asc" | "desc";
type VerifyState = "idle" | "checking" | "valid" | "invalid" | "error";

function messagesAreIdentical(
  a: RedactionMessage[],
  b: RedactionMessage[],
): boolean {
  if (a.length !== b.length) return false;
  for (let i = 0; i < a.length; i++) {
    if (a[i].role !== b[i].role || a[i].content !== b[i].content) {
      return false;
    }
  }
  return true;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function eventBadgeClass(eventType: string): string {
  switch (eventType) {
    case "egress_decision":
      return "bg-indigo-soft text-indigo";
    case "egress_redaction":
      return "bg-amber/20 text-amber";
    case "local_inference_toggle":
      return "bg-indigo-soft text-indigo";
    default:
      return "bg-surface text-muted";
  }
}

function eventRowBg(eventType: string): string {
  switch (eventType) {
    case "egress_decision":
      return "bg-indigo/[0.03]";
    case "egress_redaction":
      return "bg-amber/[0.05]";
    case "local_inference_toggle":
      return "bg-indigo/[0.05]";
    default:
      return "";
  }
}

function TierBadge({ tier }: { readonly tier: number }) {
  const config: Record<number, { label: string; cls: string; Icon: typeof ShieldCheck }> = {
    1: { label: "Tier 1", cls: "bg-success/20 text-success", Icon: ShieldCheck },
    2: { label: "Tier 2", cls: "bg-amber/20 text-amber", Icon: ShieldAlert },
    3: { label: "Tier 3", cls: "bg-amber/20 text-danger", Icon: ShieldX },
  };
  const c = config[tier] ?? config[1];
  return (
    <span className={`inline-flex items-center gap-1 rounded px-2 py-0.5 text-[11px] font-semibold ${c.cls}`}>
      <c.Icon className="h-3 w-3" />
      {c.label}
    </span>
  );
}

function formatTimestamp(ts: string): string {
  try {
    const d = new Date(ts);
    return d.toLocaleString(undefined, {
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return ts;
  }
}

function detailsFor(entry: AuditEntry): string {
  const extra = entry.extra ?? {};
  switch (entry.event_type) {
    case "egress_decision": {
      const policy = extra.policy ?? extra["policy"];
      const requiresRedaction = extra.requires_redaction;
      const parts: string[] = [];
      if (typeof policy === "string") parts.push(`policy=${policy}`);
      if (typeof requiresRedaction === "boolean")
        parts.push(`redacted=${requiresRedaction}`);
      return parts.join(", ") || "—";
    }
    case "egress_redaction": {
      const count =
        (extra.placeholder_count as number | undefined) ??
        (extra.placeholders as unknown[] | undefined)?.length;
      if (typeof count === "number") {
        return `${count} placeholder${count === 1 ? "" : "s"} applied`;
      }
      return "redaction applied";
    }
    case "local_inference_toggle": {
      const enabled = extra.enabled;
      if (typeof enabled === "boolean") return `enabled=${enabled}`;
      return "—";
    }
    default: {
      const keys = Object.keys(extra).slice(0, 2);
      if (keys.length === 0) return "—";
      return keys.map((k) => `${k}=${JSON.stringify(extra[k])}`).join(", ");
    }
  }
}

// ---------------------------------------------------------------------------
// Audit Log Table
// ---------------------------------------------------------------------------

function AuditLogTable({
  entries,
  sortDir,
  onToggleSort,
  agentFilter,
  onAgentFilter,
  eventFilter,
  onEventFilter,
  onRowClick,
}: {
  readonly entries: AuditEntry[];
  readonly sortDir: SortDir;
  readonly onToggleSort: () => void;
  readonly agentFilter: string;
  readonly onAgentFilter: (v: string) => void;
  readonly eventFilter: string;
  readonly onEventFilter: (v: string) => void;
  readonly onRowClick: (entry: AuditEntry) => void;
}) {
  const uniqueAgents = [...new Set(entries.map((e) => e.agent_id))];
  const uniqueEvents = [...new Set(entries.map((e) => e.event_type))];

  const filtered = entries.filter((e) => {
    if (agentFilter && e.agent_id !== agentFilter) return false;
    if (eventFilter && e.event_type !== eventFilter) return false;
    return true;
  });

  const sorted = [...filtered].sort((a, b) => {
    const ta = new Date(a.timestamp).getTime();
    const tb = new Date(b.timestamp).getTime();
    return sortDir === "desc" ? tb - ta : ta - tb;
  });

  return (
    <div className="overflow-hidden rounded-4 border border-hairline">
      <div className="flex flex-wrap items-center gap-3 border-b border-hairline bg-surface px-4 py-3">
        <Filter className="h-4 w-4 text-muted" />
        <select
          value={agentFilter}
          onChange={(e) => onAgentFilter(e.target.value)}
          className="rounded-2 bg-surface px-3 py-1.5 text-xs text-ink outline-none"
        >
          <option value="">All agents</option>
          {uniqueAgents.map((a) => (
            <option key={a} value={a}>
              {a}
            </option>
          ))}
        </select>
        <select
          value={eventFilter}
          onChange={(e) => onEventFilter(e.target.value)}
          className="rounded-2 bg-surface px-3 py-1.5 text-xs text-ink outline-none"
        >
          <option value="">All events</option>
          {uniqueEvents.map((ev) => (
            <option key={ev} value={ev}>
              {ev}
            </option>
          ))}
        </select>
        <span className="ml-auto text-xs text-muted">
          {sorted.length} entr{sorted.length === 1 ? "y" : "ies"}
        </span>
      </div>

      <div className="overflow-x-auto">
        <table className="w-full text-left text-sm">
          <thead>
            <tr className="border-b border-hairline bg-surface text-xs uppercase tracking-wider text-muted">
              <th
                className="cursor-pointer px-4 py-3"
                onClick={onToggleSort}
              >
                <span className="inline-flex items-center gap-1">
                  Timestamp
                  {sortDir === "desc" ? (
                    <ChevronDown className="h-3 w-3" />
                  ) : (
                    <ChevronUp className="h-3 w-3" />
                  )}
                </span>
              </th>
              <th className="px-4 py-3">Event</th>
              <th className="px-4 py-3">Agent</th>
              <th className="px-4 py-3">Decision</th>
              <th className="px-4 py-3">Tier</th>
              <th className="px-4 py-3">Details</th>
            </tr>
          </thead>
          <tbody>
            {sorted.length === 0 ? (
              <tr>
                <td
                  colSpan={6}
                  className="px-4 py-8 text-center text-sm text-muted"
                >
                  No audit entries yet. Firewall activity will appear here.
                </td>
              </tr>
            ) : (
              sorted.map((entry, idx) => {
                return (
                  <tr
                    key={`${entry.previous_hash}-${idx}`}
                    onClick={() => onRowClick(entry)}
                    className={`cursor-pointer border-b border-hairline/50 hover:bg-surface/40 ${eventRowBg(entry.event_type)}`}
                    title="Click to view entry details"
                  >
                    <td className="whitespace-nowrap px-4 py-3 text-xs text-muted">
                      {formatTimestamp(entry.timestamp)}
                    </td>
                    <td className="px-4 py-3">
                      <span
                        className={`inline-flex rounded px-2 py-0.5 text-[11px] font-medium ${eventBadgeClass(entry.event_type)}`}
                      >
                        {entry.event_type}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-xs text-ink">
                      {entry.agent_id}
                    </td>
                    <td className="px-4 py-3 text-xs font-medium text-ink">
                      {entry.decision}
                    </td>
                    <td className="px-4 py-3">
                      {entry.tier != null ? <TierBadge tier={entry.tier} /> : <span className="text-xs text-muted">—</span>}
                    </td>
                    <td className="px-4 py-3 text-xs text-muted">
                      {detailsFor(entry)}
                    </td>
                  </tr>
                );
              })
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Redaction detail modal
// ---------------------------------------------------------------------------

function highlightPlaceholders(text: string, placeholders: string[]): React.ReactNode {
  if (placeholders.length === 0) return text;
  // Sort longest-first so `__PERSON_10__` is matched before `__PERSON_1__`.
  const sorted = [...placeholders].sort((a, b) => b.length - a.length);
  const escaped = sorted.map((p) => p.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"));
  const re = new RegExp(`(${escaped.join("|")})`, "g");
  const parts = text.split(re);
  return parts.map((part, i) =>
    placeholders.includes(part) ? (
      <span
        key={i}
        className="rounded bg-amber/20 px-1 py-0.5 font-mono text-amber"
      >
        {part}
      </span>
    ) : (
      <span key={i}>{part}</span>
    ),
  );
}

function MessageBlock({
  message,
  highlighted,
  variant,
}: {
  readonly message: RedactionMessage;
  readonly highlighted: string[];
  readonly variant: "plain" | "redacted";
}) {
  const cls =
    variant === "redacted"
      ? "rounded-2 border border-amber/30 bg-amber/[0.04] p-3"
      : "rounded-2 border border-hairline bg-surface/40 p-3";
  return (
    <div className={cls}>
      <div className="mb-1 text-[10px] font-semibold uppercase tracking-wider text-muted">
        {message.role}
      </div>
      <pre className="whitespace-pre-wrap break-words font-mono text-xs text-ink">
        {variant === "redacted"
          ? highlightPlaceholders(message.content, highlighted)
          : message.content}
      </pre>
    </div>
  );
}

function AuditEntryModal({
  entry,
  onClose,
}: {
  readonly entry: AuditEntry;
  readonly onClose: () => void;
}) {
  const [detail, setDetail] = useState<RedactionDetail | null>(null);
  const [state, setState] = useState<
    "loading" | "ready" | "no-payload" | "no-detail" | "error"
  >(entry.payload_hash ? "loading" : "no-payload");
  const [error, setError] = useState<string>("");

  useEffect(() => {
    if (!entry.payload_hash) {
      setState("no-payload");
      return;
    }
    let cancelled = false;
    setState("loading");
    setError("");
    dedupInvoke<RedactionDetailResponse>("get_redaction_detail", {
      payloadHash: entry.payload_hash,
    })
      .then((resp) => {
        if (cancelled) return;
        if (resp.detail) {
          setDetail(resp.detail);
          setState("ready");
        } else {
          setState("no-detail");
        }
      })
      .catch((e: unknown) => {
        if (cancelled) return;
        setError(String(e));
        setState("error");
      });
    return () => {
      cancelled = true;
    };
  }, [entry.payload_hash]);

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [onClose]);

  const placeholders = detail ? Object.keys(detail.placeholder_map) : [];
  const wasRedacted =
    !!detail &&
    (placeholders.length > 0 ||
      !messagesAreIdentical(
        detail.original_messages,
        detail.redacted_messages,
      ));

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4"
      onClick={onClose}
    >
      <div
        className="max-h-[90vh] w-full max-w-4xl overflow-hidden rounded-4 border border-hairline bg-surface shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between border-b border-hairline px-5 py-4">
          <div>
            <h3 className="text-sm font-semibold text-ink">
              Audit entry details
            </h3>
            <p className="mt-0.5 text-xs text-muted">
              {entry.event_type} · {entry.agent_id} ·{" "}
              {formatTimestamp(entry.timestamp)}
            </p>
          </div>
          <button
            onClick={onClose}
            className="rounded-2 p-1.5 text-muted hover:bg-surface hover:text-ink"
            aria-label="Close"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="max-h-[calc(90vh-72px)] space-y-5 overflow-y-auto px-5 py-4">
          {/* Always show the audit-row metadata. */}
          <section>
            <h4 className="mb-2 text-[11px] font-semibold uppercase tracking-wider text-muted">
              Audit row
            </h4>
            <div className="overflow-hidden rounded-2 border border-hairline">
              <table className="w-full text-xs">
                <tbody>
                  <tr className="border-b border-hairline/50">
                    <td className="bg-surface/40 px-3 py-1.5 font-medium text-muted">Decision</td>
                    <td className="px-3 py-1.5 font-mono text-ink">{entry.decision}</td>
                  </tr>
                  <tr className="border-b border-hairline/50">
                    <td className="bg-surface/40 px-3 py-1.5 font-medium text-muted">Tier</td>
                    <td className="px-3 py-1.5 text-ink">{entry.tier ?? "—"}</td>
                  </tr>
                  {entry.payload_hash && (
                    <tr className="border-b border-hairline/50">
                      <td className="bg-surface/40 px-3 py-1.5 font-medium text-muted">Payload hash</td>
                      <td className="px-3 py-1.5 font-mono text-[10px] text-muted">
                        {entry.payload_hash}
                      </td>
                    </tr>
                  )}
                  {Object.entries(entry.extra ?? {}).map(([k, v]) => (
                    <tr key={k} className="border-b border-hairline/50 last:border-b-0">
                      <td className="bg-surface/40 px-3 py-1.5 font-medium text-muted">{k}</td>
                      <td className="px-3 py-1.5 font-mono text-ink">
                        {typeof v === "string" ? v : JSON.stringify(v)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>

          {state === "loading" && (
            <div className="flex items-center gap-2 text-xs text-muted">
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
              Loading message content…
            </div>
          )}
          {state === "no-payload" && (
            <div className="rounded-2 border border-dashed border-hairline bg-surface/40 px-4 py-4 text-xs text-muted">
              This event has no associated message body. Lifecycle events
              like agent_run and local_inference_toggle only carry the
              metadata shown above.
            </div>
          )}
          {state === "no-detail" && (
            <div className="rounded-2 border border-dashed border-hairline bg-surface/40 px-4 py-4 text-xs text-muted">
              No stored message body for this row. Prompts are kept for
              24 hours — older entries (and entries written before this
              feature shipped) won't have content here.
            </div>
          )}
          {state === "error" && (
            <div className="rounded-2 border border-danger/40 bg-danger/10 px-4 py-3 text-xs text-danger">
              Failed to load message body: {error}
            </div>
          )}
          {state === "ready" && detail && wasRedacted && (
            <>
              <section>
                <h4 className="mb-2 text-[11px] font-semibold uppercase tracking-wider text-muted">
                  Original ({detail.original_messages.length} message
                  {detail.original_messages.length === 1 ? "" : "s"})
                </h4>
                <div className="space-y-2">
                  {detail.original_messages.map((m, i) => (
                    <MessageBlock
                      key={i}
                      message={m}
                      highlighted={placeholders}
                      variant="plain"
                    />
                  ))}
                </div>
              </section>

              <section>
                <h4 className="mb-2 text-[11px] font-semibold uppercase tracking-wider text-muted">
                  Sent to provider (after redaction)
                </h4>
                <div className="space-y-2">
                  {detail.redacted_messages.map((m, i) => (
                    <MessageBlock
                      key={i}
                      message={m}
                      highlighted={placeholders}
                      variant="redacted"
                    />
                  ))}
                </div>
              </section>

              {placeholders.length > 0 && (
                <section>
                  <h4 className="mb-2 text-[11px] font-semibold uppercase tracking-wider text-muted">
                    Substitutions ({placeholders.length})
                  </h4>
                  <div className="overflow-hidden rounded-2 border border-hairline">
                    <table className="w-full text-xs">
                      <thead className="bg-surface text-muted">
                        <tr>
                          <th className="px-3 py-2 text-left font-medium">Placeholder</th>
                          <th className="px-3 py-2 text-left font-medium">Original value</th>
                        </tr>
                      </thead>
                      <tbody>
                        {placeholders.map((p) => (
                          <tr key={p} className="border-t border-hairline/50">
                            <td className="px-3 py-1.5 font-mono text-amber">{p}</td>
                            <td className="px-3 py-1.5 font-mono text-ink">
                              {detail.placeholder_map[p]}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </section>
              )}
            </>
          )}
          {state === "ready" && detail && !wasRedacted && (
            <section>
              <h4 className="mb-2 text-[11px] font-semibold uppercase tracking-wider text-muted">
                Message content ({detail.original_messages.length} message
                {detail.original_messages.length === 1 ? "" : "s"})
              </h4>
              <div className="space-y-2">
                {detail.original_messages.map((m, i) => (
                  <MessageBlock
                    key={i}
                    message={m}
                    highlighted={[]}
                    variant="plain"
                  />
                ))}
              </div>
            </section>
          )}
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------

function AuditPage() {
  const [sortDir, setSortDir] = useState<SortDir>("desc");
  const [agentFilter, setAgentFilter] = useState("");
  const [eventFilter, setEventFilter] = useState("");
  const [verifyState, setVerifyState] = useState<VerifyState>("idle");
  const [selectedEntry, setSelectedEntry] = useState<AuditEntry | null>(null);

  const auditResult = useAsyncData<AuditEntry[]>(
    useCallback(
      () => dedupInvoke<AuditEntry[]>("get_audit_log", { limit: 100, offset: 0 }),
      [],
    ),
  );

  const auditLog = auditResult.data ?? [];

  const handleVerify = async () => {
    setVerifyState("checking");
    try {
      const ok = await dedupInvoke<boolean>("verify_audit_chain");
      setVerifyState(ok ? "valid" : "invalid");
    } catch {
      setVerifyState("error");
    }
  };

  return (
    <div className="flex-1 space-y-6 overflow-y-auto">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-[44px] font-bold leading-none" style={{ background: "linear-gradient(135deg, var(--ink), var(--ink-2))", WebkitBackgroundClip: "text", WebkitTextFillColor: "transparent", backgroundClip: "text" }}>Audit Log</h2>
          <p className="mt-1 text-sm text-muted">
            Tamper-evident record of firewall decisions, redactions, and mode changes.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={handleVerify}
            disabled={verifyState === "checking"}
            className="flex items-center gap-2 rounded-2 bg-surface px-3 py-2 text-xs text-muted hover:text-ink disabled:opacity-50"
          >
            {verifyState === "checking" ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : verifyState === "valid" ? (
              <Check className="h-3.5 w-3.5 text-success" />
            ) : verifyState === "invalid" || verifyState === "error" ? (
              <X className="h-3.5 w-3.5 text-danger" />
            ) : (
              <ShieldCheck className="h-3.5 w-3.5" />
            )}
            {verifyState === "valid"
              ? "Chain valid"
              : verifyState === "invalid"
                ? "Chain corrupted"
                : verifyState === "error"
                  ? "Verify failed"
                  : "Verify chain"}
          </button>
          <button
            onClick={auditResult.refetch}
            disabled={auditResult.isLoading}
            className="flex items-center gap-2 rounded-2 bg-surface px-3 py-2 text-xs text-muted hover:text-ink disabled:opacity-50"
          >
            <RefreshCw className={`h-3.5 w-3.5 ${auditResult.isLoading ? "animate-spin" : ""}`} />
            Refresh
          </button>
        </div>
      </div>

      <section>
        {auditResult.isLoading ? (
          <SkeletonTable rows={5} />
        ) : (
          <AuditLogTable
            entries={auditLog}
            sortDir={sortDir}
            onToggleSort={() =>
              setSortDir((d) => (d === "desc" ? "asc" : "desc"))
            }
            agentFilter={agentFilter}
            onAgentFilter={setAgentFilter}
            eventFilter={eventFilter}
            onEventFilter={setEventFilter}
            onRowClick={setSelectedEntry}
          />
        )}
      </section>

      {selectedEntry && (
        <AuditEntryModal
          entry={selectedEntry}
          onClose={() => setSelectedEntry(null)}
        />
      )}
    </div>
  );
}

export default AuditPage;

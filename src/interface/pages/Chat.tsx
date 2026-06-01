import { useState, useRef, useEffect, useCallback, useMemo } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import {
  Send,
  Brain,
  User,
  Clock,
  AlertCircle,
  Loader2,
  Trash2,
  Wifi,
  WifiOff,
  Check,
  Play,
  Ban,
  Search,
  AlertTriangle,
  Cloud,
  Mic,
  Square,
} from "lucide-react";
import { invoke } from "@tauri-apps/api/core";
import { SkeletonChatMessage } from "../components/LoadingState";
import { useAsyncData } from "../hooks/useAsyncData";
import { usePipelineStatus } from "../hooks/usePipelineStatus";
import {
  useStreamingChat,
  type ActionProposal,
  type ContactCandidate,
  type RecipientDisambiguationProposal,
  type ToolStep,
} from "../hooks/useStreamingChat";
import type { ReplyContext } from "../hooks/useReplyContext";
import { useAudioRecording } from "../hooks/useAudioRecording";
import { dedupInvoke } from "../utils/requestDedup";
import { formatRelativeTime } from "../utils/timeFormat";
import type { MessagePart } from "../types/chat";
import { ArtifactFrame } from "../components/chat/ArtifactFrame";
import { ArtifactSidePanel } from "../components/chat/ArtifactSidePanel";
import { SourceList } from "../components/chat/CitationCards";
import { ThinkingBlock } from "../components/chat/ThinkingBlock";
import { StepsTimeline } from "../components/chat/StepsTimeline";
import { ResearchExtendedBanner } from "../components/chat/ResearchExtendedBanner";
import {
  SessionsPanel,
  type ChatSessionSummary,
} from "../components/chat/SessionsPanel";
import { ChatModelPopover } from "../components/ChatModelPopover";
import { ModelStatusIndicator } from "../components/ModelStatusIndicator";
import type { DelegationIntent } from "../utils/delegationIntent";
import WatcherWizard from "../components/dashboard/delegation/WatcherWizard";

interface ChatSessionListResponse {
  readonly sessions: ReadonlyArray<ChatSessionSummary>;
  readonly active_session_id: string | null;
}

interface LoadSessionResponse {
  readonly session_id: string;
  readonly messages: ReadonlyArray<ChatMessage>;
}

// ---------------------------------------------------------------------------
// Types matching Rust backend
// ---------------------------------------------------------------------------

interface OllamaStatusResponse {
  server_reachable: boolean;
  chat_model: string;
  chat_model_status: string;
  embed_model: string;
  embed_model_status: string;
  server_version: string;
  provider?: string;
}

interface Source {
  type?: string;
  content?: string;
  sensitivity_tier?: number;
  [key: string]: unknown;
}

interface ActionResultInfo {
  readonly status: string;
  readonly output: string;
  readonly error?: string;
}

interface ChatMessage {
  role: "user" | "assistant";
  content: string;
  timestamp: string;
  // Frontend-only enrichment
  sources?: Source[];
  latency_ms?: number;
  model?: string;
  error?: string;
  action_proposal?: ActionProposal;
  recipient_disambiguation?: RecipientDisambiguationProposal;
  action_result?: ActionResultInfo;
  parts?: MessagePart[];
  thinking?: string;
  steps?: ReadonlyArray<ToolStep>;
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const SUGGESTED_QUESTIONS = [
  "What do I have today?",
  "Summarize my week",
  "Who have I been talking to most?",
  "How is my health trending?",
] as const;

const OLLAMA_POLL_MS = 30_000;

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function SourcesSection({ sources }: { readonly sources: Source[] }) {
  const [open, setOpen] = useState(false);
  const pipeline = usePipelineStatus();

  if (sources.length === 0) return null;

  return (
    <div className="mt-2">
      <button
        onClick={() => setOpen((o) => !o)}
        className="flex items-center gap-1 text-xs text-muted hover:text-ink"
      >
        {open ? "▾" : "▸"} {sources.length} source{sources.length !== 1 && "s"} used
      </button>

      {open && (
        <div className="mt-1.5">
          <SourceList sources={sources} />
          <p className="mt-1.5 text-[11px] text-muted">
            Context from data processed{" "}
            {pipeline.lastCompletedAt
              ? formatRelativeTime(pipeline.lastCompletedAt)
              : "never"}
          </p>
        </div>
      )}
    </div>
  );
}

function TypingIndicator() {
  return (
    <div className="flex items-start gap-3.5">
      <div
        className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full"
        style={{
          background: "linear-gradient(135deg, var(--indigo) 0%, oklch(0.65 0.18 220) 100%)",
          boxShadow: "0 1px 0 oklch(1 0 0 / 0.2) inset, 0 4px 12px oklch(0.55 0.20 265 / 0.25)",
        }}
      >
        <Brain className="h-4 w-4 text-white" strokeWidth={1.6} />
      </div>
      <div className="pt-2">
        <div className="flex items-center gap-1">
          <span className="h-2 w-2 animate-bounce rounded-full bg-muted [animation-delay:0ms]" />
          <span className="h-2 w-2 animate-bounce rounded-full bg-muted [animation-delay:150ms]" />
          <span className="h-2 w-2 animate-bounce rounded-full bg-muted [animation-delay:300ms]" />
        </div>
      </div>
    </div>
  );
}

/** Renders the in-flight assistant response: thinking trace + each
 * streamed part via the artifact registry. Parts marked `display: panel`
 * still render inline as a stub until the user opens them.
 *
 * ``isStreaming`` keeps the live activity affordances on for the whole
 * turn — the StepsTimeline header stays in "Using N tools" with a
 * spinner, and an "active" pulse renders between tool calls / while
 * the LLM is composing its answer so the bubble never looks frozen.
 */
function StreamingBubble({
  parts,
  thinking,
  steps,
  isStreaming,
  onOpenInPanel,
  inExtendedResearch,
  extendedReason,
  userStopRequested,
  onStop,
}: {
  readonly parts: ReadonlyArray<MessagePart>;
  readonly thinking: string;
  readonly steps: ReadonlyArray<ToolStep>;
  readonly isStreaming: boolean;
  readonly onOpenInPanel: (part: MessagePart) => void;
  readonly inExtendedResearch: boolean;
  readonly extendedReason: string;
  readonly userStopRequested: boolean;
  readonly onStop: () => void;
}) {
  const hasContent =
    parts.length > 0 || thinking.length > 0 || steps.length > 0;
  // Any markdown text actively streaming in. We only suppress the
  // "still working" dots once the assistant has started producing
  // visible answer tokens — before that the user needs a heartbeat.
  const hasStreamingAnswer = parts.some(
    (p) => p.streaming && String(p.data ?? "").length > 0,
  );
  const showHeartbeat = isStreaming && !hasStreamingAnswer;

  return (
    <div className="flex items-start gap-3.5">
      <div
        className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full"
        style={{
          background: "linear-gradient(135deg, var(--indigo) 0%, oklch(0.65 0.18 220) 100%)",
          boxShadow: "0 1px 0 oklch(1 0 0 / 0.2) inset, 0 4px 12px oklch(0.55 0.20 265 / 0.25)",
        }}
      >
        <Brain className="h-4 w-4 text-white" strokeWidth={1.6} />
      </div>
      <div className="min-w-0 max-w-[85%] flex-1">
        <div className="text-[15px] leading-[1.6] text-ink">
          {thinking && (
            <ThinkingBlock
              part={{
                id: "stream-thinking",
                mime: "application/vnd.arandu.thinking+json",
                data: thinking,
                sensitivity_tier: 3,
              }}
            />
          )}
          {steps.length > 0 && (
            <StepsTimeline
              steps={steps}
              defaultOpen
              active={isStreaming}
            />
          )}
          {inExtendedResearch && (
            <ResearchExtendedBanner
              reason={extendedReason}
              userStopRequested={userStopRequested}
              onStop={onStop}
            />
          )}
          {parts.map((part) => (
            <ArtifactFrame
              key={part.id}
              part={part}
              onOpenInPanel={onOpenInPanel}
            />
          ))}
          {!hasContent && (
            <span className="ml-0.5 inline-block h-4 w-0.5 animate-pulse bg-indigo" />
          )}
          {hasContent && showHeartbeat && (
            <div
              className="mt-2 flex items-center gap-1"
              aria-label="Still working"
            >
              <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-muted [animation-delay:0ms]" />
              <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-muted [animation-delay:150ms]" />
              <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-muted [animation-delay:300ms]" />
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

/**
 * Shows the currently-selected agent's resolved model and lets the
 * user change it inline via a popover. The model name comes from the
 * agent registry (each row already carries `config.resolved_model`),
 * not from Ollama — which previously hardcoded "gemma4:e2b" regardless
 * of what the agent actually used. Provider health colours the dot
 * via the existing Ollama status probe.
 */
function ModelStatusBadge({
  agent,
  onChanged,
}: {
  readonly agent: AgentListRow | null;
  readonly onChanged: () => void;
}) {
  const [provider, setProvider] = useState<
    "ollama" | "anthropic" | "openai_compat"
  >("ollama");
  const [reachable, setReachable] = useState<boolean | null>(null);
  const [errorDetail, setErrorDetail] = useState<string | null>(null);
  const [popoverOpen, setPopoverOpen] = useState(false);

  // Poll provider/reachability so the dot reflects backend health.
  // Model name is independent — it comes from the agent config.
  //
  // For Ollama we ping the local daemon and require the chat model to
  // be downloaded. For remote providers we trust the configured
  // credentials and surface "reachable" without a probe.
  useEffect(() => {
    let mounted = true;
    let intervalId: ReturnType<typeof setInterval> | null = null;
    let confirmedOnline = false;

    const check = async () => {
      try {
        const result = await dedupInvoke<OllamaStatusResponse>(
          "get_ollama_status",
        );
        if (!mounted) return;
        setErrorDetail(null);
        const prov: "ollama" | "anthropic" | "openai_compat" =
          result.provider === "anthropic"
            ? "anthropic"
            : result.provider === "openai_compat"
              ? "openai_compat"
              : "ollama";
        setProvider(prov);
        if (prov === "anthropic" || prov === "openai_compat") {
          setReachable(true);
          confirmedOnline = true;
        } else {
          const ok = result.server_reachable
            && result.chat_model_status === "available";
          setReachable(ok);
          if (ok) confirmedOnline = true;
          else {
            setErrorDetail(
              `reachable=${result.server_reachable}, status=${result.chat_model_status}`,
            );
          }
        }
      } catch (err) {
        if (mounted) {
          setReachable(false);
          const msg = err instanceof Error ? err.message : String(err);
          setErrorDetail(msg);
        }
      }
      if (confirmedOnline && intervalId !== null) {
        clearInterval(intervalId);
        intervalId = setInterval(check, OLLAMA_POLL_MS);
      }
    };

    check();
    intervalId = setInterval(check, 5_000);
    return () => {
      mounted = false;
      if (intervalId !== null) clearInterval(intervalId);
    };
  }, []);

  const modelName = agent?.config.resolved_model ?? "default";
  const isRemote = provider === "anthropic" || provider === "openai_compat";
  const Icon = reachable === null
    ? Loader2
    : reachable
      ? (isRemote ? Cloud : Wifi)
      : WifiOff;
  const color = reachable === null
    ? "text-muted"
    : reachable
      ? "text-success"
      : "text-danger";
  const spin = reachable === null ? "animate-spin" : "";

  return (
    <div className="relative">
      <button
        type="button"
        onClick={() => agent && setPopoverOpen((v) => !v)}
        disabled={!agent}
        title={errorDetail
          ?? `Click to change the ${agent?.name ?? "agent"}'s model`}
        className={`flex items-center gap-1.5 rounded-2 px-1.5 py-0.5 text-[11px] ${color} hover:bg-surface disabled:opacity-50`}
      >
        <Icon className={`h-3 w-3 ${spin}`} strokeWidth={1.6} />
        <span>{`Model: ${modelName}`}</span>
      </button>
      {popoverOpen && agent && (
        <ChatModelPopover
          agent={agent}
          onClose={() => setPopoverOpen(false)}
          onSaved={() => {
            setPopoverOpen(false);
            onChanged();
          }}
        />
      )}
    </div>
  );
}

function EmptyState({
  onSuggestion,
}: {
  readonly onSuggestion: (q: string) => void;
}) {
  return (
    <div className="flex flex-1 flex-col items-center justify-center px-4 text-center">
      <div
        className="mb-6 flex h-16 w-16 items-center justify-center rounded-5"
        style={{
          background: "linear-gradient(135deg, var(--indigo) 0%, oklch(0.65 0.18 220) 100%)",
          boxShadow: "0 1px 0 oklch(1 0 0 / 0.2) inset, 0 4px 12px oklch(0.55 0.20 265 / 0.25)",
        }}
      >
        <Brain className="h-8 w-8 text-white" strokeWidth={1.6} />
      </div>
      <p className="max-w-md text-ink">
        Hi! I&apos;m your Arandu. I know about your messages, calendar,
        notes, and more. Everything stays on your machine. Ask me anything.
      </p>
      <div className="mt-6 flex flex-wrap justify-center gap-2">
        {SUGGESTED_QUESTIONS.map((q) => (
          <button
            key={q}
            onClick={() => onSuggestion(q)}
            className="rounded-pill border border-hairline bg-surface px-4 py-2 text-sm text-muted transition-colors hover:border-indigo hover:text-ink"
          >
            {q}
          </button>
        ))}
      </div>
    </div>
  );
}

/** Card for confirming or cancelling a proposed action. */
function RecipientPreviewBlock({
  preview,
}: {
  readonly preview: NonNullable<ActionProposal["recipient_preview"]>;
}) {
  // Build a single line summarising the resolved destination so the
  // user can confirm at a glance: "Elmara · +55 11 99999-1234 ·
  // WhatsApp". When unresolved, the warning text replaces the
  // identifier so the user is forced to notice.
  const channelLabel = preview.channel === "whatsapp"
    ? "WhatsApp"
    : preview.channel === "email"
      ? "Email"
      : "iMessage";
  // Pick the destination handle relevant to the channel.
  const handle = preview.channel === "email"
    ? preview.email
    : preview.phone ?? preview.email;
  return (
    <div
      className={`mt-2 rounded-2 border px-2 py-1.5 text-xs ${
        preview.resolved
          ? "border-hairline bg-bg/40 text-muted"
          : "border-amber/40 bg-amber-soft text-amber"
      }`}
    >
      <div className="flex items-center gap-1.5">
        {preview.resolved ? (
          <Check className="h-3 w-3 text-success" strokeWidth={1.6} />
        ) : (
          <AlertTriangle className="h-3 w-3 text-amber" strokeWidth={1.6} />
        )}
        <span className="font-medium text-ink">To:</span>
        <span>{preview.name}</span>
        {handle && (
          <span className="text-muted">· {handle}</span>
        )}
        <span className="text-muted">· {channelLabel}</span>
      </div>
      {!preview.resolved && preview.warning && (
        <p className="mt-1 text-[11px]">{preview.warning}</p>
      )}
    </div>
  );
}

function RecipientDisambiguationCard({
  proposal,
  onPick,
  onCancel,
  onSearch,
  resolving,
}: {
  readonly proposal: RecipientDisambiguationProposal;
  readonly onPick: (candidate: ContactCandidate) => void;
  readonly onCancel: () => void;
  readonly onSearch: (
    query: string,
    includeApple: boolean,
  ) => Promise<ContactCandidate[]>;
  readonly resolving: boolean;
}) {
  const channelLabel = proposal.channel === "whatsapp"
    ? "WhatsApp"
    : proposal.channel === "email"
      ? "Email"
      : "iMessage";
  const initialCandidates = proposal.candidates ?? [];

  const [query, setQuery] = useState("");
  const [candidates, setCandidates] = useState<ContactCandidate[]>(
    initialCandidates,
  );
  const [searching, setSearching] = useState(false);
  const [searchingApple, setSearchingApple] = useState(false);
  const [appleDone, setAppleDone] = useState(false);
  const [searchError, setSearchError] = useState<string | null>(null);
  // Stale-response guard: only apply results from the latest fired search.
  const searchSeq = useRef(0);

  const trimmed = query.trim();

  // Debounced DB search on keystroke. Empty input restores the
  // server-provided candidates so cancel-without-typing is a no-op.
  useEffect(() => {
    setAppleDone(false);
    if (trimmed === "") {
      setCandidates(initialCandidates);
      setSearching(false);
      setSearchError(null);
      return;
    }
    const seq = ++searchSeq.current;
    setSearching(true);
    const handle = setTimeout(async () => {
      try {
        const results = await onSearch(trimmed, false);
        if (seq !== searchSeq.current) return;
        setCandidates(results);
        setSearchError(null);
      } catch (err) {
        if (seq !== searchSeq.current) return;
        setSearchError(err instanceof Error ? err.message : String(err));
      } finally {
        if (seq === searchSeq.current) setSearching(false);
      }
    }, 250);
    return () => clearTimeout(handle);
    // initialCandidates is derived from a stable prop on this card; it
    // doesn't need to retrigger the debounce.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [trimmed, onSearch]);

  const handleAppleSearch = async () => {
    const q = trimmed || proposal.original_name;
    if (!q) return;
    const seq = ++searchSeq.current;
    setSearchingApple(true);
    try {
      const results = await onSearch(q, true);
      if (seq !== searchSeq.current) return;
      setCandidates(results);
      setAppleDone(true);
      setSearchError(null);
    } catch (err) {
      if (seq !== searchSeq.current) return;
      setSearchError(err instanceof Error ? err.message : String(err));
    } finally {
      if (seq === searchSeq.current) setSearchingApple(false);
    }
  };

  const hasCandidates = candidates.length > 0;
  const isFiltered = trimmed !== "";
  const busy = resolving || searching || searchingApple;

  return (
    <div className="flex items-start gap-3.5">
      <div
        className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full"
        style={{
          background: "linear-gradient(135deg, var(--indigo) 0%, oklch(0.65 0.18 220) 100%)",
          boxShadow: "0 1px 0 oklch(1 0 0 / 0.2) inset, 0 4px 12px oklch(0.55 0.20 265 / 0.25)",
        }}
      >
        <User className="h-4 w-4 text-white" strokeWidth={1.6} />
      </div>
      <div className="max-w-[75%]">
        <div className="rounded-4 border border-hairline bg-surface px-4 py-3 shadow-2">
          <div className="flex items-center gap-2 text-sm font-medium text-ink">
            <span>Pick recipient for {proposal.display_name}</span>
            <span className="text-[10px] text-muted">via {channelLabel}</span>
          </div>
          <p className="mt-1 text-xs text-muted">
            {isFiltered ? (
              <>
                {`${candidates.length} match${
                  candidates.length === 1 ? "" : "es"
                } for `}
                <span className="text-ink">{trimmed}</span>
              </>
            ) : (
              <>
                {`Found ${initialCandidates.length} match${
                  initialCandidates.length === 1 ? "" : "es"
                } for `}
                <span className="text-ink">{proposal.original_name}</span>
              </>
            )}
          </p>
          <div className="mt-2 flex items-center gap-1.5 rounded-2 border border-hairline bg-bg/40 px-2 py-1">
            <Search className="h-3 w-3 text-muted" strokeWidth={1.6} />
            <input
              type="text"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search contacts by name…"
              disabled={resolving}
              className="w-full bg-transparent text-xs text-ink outline-none placeholder:text-muted disabled:opacity-50"
            />
            {searching && (
              <Loader2 className="h-3 w-3 animate-spin text-muted" strokeWidth={1.6} />
            )}
          </div>
          {!hasCandidates && (
            <p className="mt-2 text-xs text-amber">
              {isFiltered
                ? "No matches for that name. Try a different spelling."
                : "No saved contact matches. Type a name to search, or cancel and retry with a phone number."}
            </p>
          )}
          {hasCandidates && (
            <ul className="mt-2 space-y-1.5">
              {candidates.map((c, idx) => (
                <li key={`${c.name}-${c.handle ?? "no-handle"}-${idx}`}>
                  <button
                    onClick={() => onPick(c)}
                    disabled={busy}
                    className="w-full rounded-2 border border-hairline bg-bg/40 px-2 py-1.5 text-left text-xs hover:border-indigo/60 disabled:opacity-50"
                  >
                    <div className="flex items-center gap-1.5 text-ink">
                      <span className="font-medium">{c.name}</span>
                      {c.relationship && (
                        <span className="text-muted">· {c.relationship}</span>
                      )}
                    </div>
                    {c.active_topic && (
                      <div className="mt-0.5 text-[11px] text-indigo">
                        topic: {c.active_topic}
                      </div>
                    )}
                    {c.handle && (
                      <div className="text-[11px] text-muted">{c.handle}</div>
                    )}
                  </button>
                </li>
              ))}
            </ul>
          )}
          {searchError && (
            <p className="mt-2 text-[11px] text-danger">
              Search failed: {searchError}
            </p>
          )}
          <div className="mt-3 flex flex-wrap items-center gap-2">
            <button
              onClick={onCancel}
              disabled={resolving}
              className="flex items-center gap-1.5 rounded-2 bg-surface-2 px-3 py-1.5 text-xs text-muted hover:text-ink disabled:opacity-50"
            >
              <Ban className="h-3 w-3" strokeWidth={1.6} />
              None of these
            </button>
            {!appleDone && (
              <button
                onClick={handleAppleSearch}
                disabled={busy}
                className="flex items-center gap-1.5 rounded-2 bg-surface-2 px-3 py-1.5 text-xs text-muted hover:text-ink disabled:opacity-50"
                title="Also search the macOS AddressBook (slower)"
              >
                {searchingApple ? (
                  <Loader2 className="h-3 w-3 animate-spin" strokeWidth={1.6} />
                ) : (
                  <Search className="h-3 w-3" strokeWidth={1.6} />
                )}
                Also search Apple Contacts
              </button>
            )}
            {appleDone && !searchingApple && (
              <span className="text-[11px] text-muted">
                Searched Apple Contacts
              </span>
            )}
            {resolving && (
              <span className="flex items-center gap-1 text-xs text-muted">
                <Loader2 className="h-3 w-3 animate-spin" strokeWidth={1.6} />
                Building action…
              </span>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

function ActionConfirmationCard({
  proposal,
  onConfirm,
  onCancel,
  confirming,
}: {
  readonly proposal: ActionProposal;
  readonly onConfirm: () => void;
  readonly onCancel: () => void;
  readonly confirming: boolean;
}) {
  // Hide the raw recipient field from the generic param list when we
  // have a resolved preview — the preview block is more informative
  // and showing both would duplicate.
  const previewFields = new Set(
    proposal.recipient_preview
      ? ["to", "recipient", "phone", "email", "address"]
      : [],
  );
  const params = Object.entries(proposal.arguments).filter(
    ([k, v]) => v != null && !previewFields.has(k),
  );
  const hasMissing = proposal.missing_params.length > 0;

  return (
    <div className="flex items-start gap-3.5">
      <div
        className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full"
        style={{
          background: "linear-gradient(135deg, var(--indigo) 0%, oklch(0.65 0.18 220) 100%)",
          boxShadow: "0 1px 0 oklch(1 0 0 / 0.2) inset, 0 4px 12px oklch(0.55 0.20 265 / 0.25)",
        }}
      >
        <Play className="h-4 w-4 text-white" strokeWidth={1.6} />
      </div>
      <div className="max-w-[75%]">
        <div className="rounded-4 border border-hairline bg-surface px-4 py-3 shadow-2">
          <div className="flex items-center gap-2 text-sm font-medium text-ink">
            <span>{proposal.display_name}</span>
            <span className="text-[10px] text-muted">
              via {proposal.connector_name}
            </span>
          </div>

          {proposal.recipient_preview && (
            <RecipientPreviewBlock preview={proposal.recipient_preview} />
          )}

          {params.length > 0 && (
            <ul className="mt-2 space-y-1">
              {params.map(([key, val]) => (
                <li key={key} className="text-xs text-muted">
                  <span className="font-medium text-ink">{key}:</span>{" "}
                  {String(val)}
                </li>
              ))}
            </ul>
          )}

          {hasMissing && (
            <div className="mt-2 flex items-center gap-1.5 text-xs text-amber">
              <AlertTriangle className="h-3 w-3 shrink-0" strokeWidth={1.6} />
              Missing: {proposal.missing_params.join(", ")}
            </div>
          )}

          <div className="mt-3 flex items-center gap-2">
            <button
              onClick={onConfirm}
              disabled={confirming}
              className="flex items-center gap-1.5 rounded-2 bg-indigo px-3 py-1.5 text-xs font-medium text-white hover:opacity-90 disabled:opacity-50"
            >
              {confirming ? (
                <Loader2 className="h-3 w-3 animate-spin" strokeWidth={1.6} />
              ) : (
                <Check className="h-3 w-3" strokeWidth={1.6} />
              )}
              {confirming ? "Running..." : "Confirm"}
            </button>
            <button
              onClick={onCancel}
              disabled={confirming}
              className="flex items-center gap-1.5 rounded-2 bg-surface-2 px-3 py-1.5 text-xs text-muted hover:text-ink disabled:opacity-50"
            >
              <Ban className="h-3 w-3" strokeWidth={1.6} />
              Cancel
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

/** Card showing the result of an executed action. */
function ActionResultCard({
  result,
  displayName,
}: {
  readonly result: ActionResultInfo;
  readonly displayName: string;
}) {
  const isSuccess = result.status === "success";

  return (
    <div className="flex items-start gap-3.5">
      <div
        className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-full ${
          isSuccess ? "bg-success-soft" : "bg-amber-soft"
        }`}
      >
        {isSuccess ? (
          <Check className="h-4 w-4 text-success" strokeWidth={1.6} />
        ) : (
          <AlertCircle className="h-4 w-4 text-danger" strokeWidth={1.6} />
        )}
      </div>
      <div className="max-w-[75%]">
        <div className="text-[15px] leading-[1.6] text-ink">
          <span className="font-medium">{displayName}</span>
          {isSuccess ? (
            <span className="ml-1.5 text-success">completed</span>
          ) : (
            <span className="ml-1.5 text-danger">failed</span>
          )}
          {result.output && (
            <p className="mt-1 text-xs text-muted">{result.output}</p>
          )}
          {result.error && (
            <p className="mt-1 text-xs text-danger">{result.error}</p>
          )}
        </div>
      </div>
    </div>
  );
}

function MessageBubble({
  msg,
  onOpenInPanel,
}: {
  readonly msg: ChatMessage;
  readonly onOpenInPanel: (part: MessagePart) => void;
}) {
  const isUser = msg.role === "user";
  const hasParts = !isUser && (msg.parts?.length ?? 0) > 0;

  return (
    <div className={`flex items-start gap-3.5 ${isUser ? "flex-row-reverse" : ""}`}>
      {/* Avatar */}
      {isUser ? (
        <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-surface-2">
          <User className="h-4 w-4 text-muted" strokeWidth={1.6} />
        </div>
      ) : (
        <div
          className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full"
          style={{
            background: "linear-gradient(135deg, var(--indigo) 0%, oklch(0.65 0.18 220) 100%)",
            boxShadow: "0 1px 0 oklch(1 0 0 / 0.2) inset, 0 4px 12px oklch(0.55 0.20 265 / 0.25)",
          }}
        >
          <Brain className="h-4 w-4 text-white" strokeWidth={1.6} />
        </div>
      )}

      {/* Bubble */}
      <div
        className={`min-w-0 ${
          isUser ? "max-w-[70%] text-right" : "max-w-[85%] flex-1"
        }`}
      >
        {isUser ? (
          /* User message: dark bubble, right-aligned */
          <div
            className="inline-block bg-ink text-surface px-4 py-3 text-sm leading-relaxed shadow-2"
            style={{ borderRadius: "18px 18px 4px 18px" }}
          >
            {msg.error ? (
              <div className="flex items-center gap-2 text-amber">
                <AlertCircle className="h-4 w-4 shrink-0" strokeWidth={1.6} />
                <span>{msg.error}</span>
              </div>
            ) : (
              <>
                {msg.steps && msg.steps.length > 0 && (
                  <StepsTimeline steps={msg.steps} />
                )}
                <span className="whitespace-pre-wrap">{msg.content}</span>
              </>
            )}
          </div>
        ) : (
          /* Assistant message: no bubble bg */
          <div className="text-[15px] leading-[1.6] text-ink">
            {msg.error ? (
              <div className="flex items-center gap-2 text-amber">
                <AlertCircle className="h-4 w-4 shrink-0" strokeWidth={1.6} />
                <span>{msg.error}</span>
              </div>
            ) : hasParts ? (
              <>
                {msg.thinking && (
                  <ThinkingBlock
                    part={{
                      id: `${msg.timestamp}-thinking`,
                      mime: "application/vnd.arandu.thinking+json",
                      data: msg.thinking,
                      sensitivity_tier: 3,
                    }}
                  />
                )}
                {msg.steps && msg.steps.length > 0 && (
                  <StepsTimeline steps={msg.steps} />
                )}
                {msg.parts!.map((part) => (
                  <ArtifactFrame
                    key={part.id}
                    part={part}
                    onOpenInPanel={onOpenInPanel}
                  />
                ))}
              </>
            ) : msg.content ? (
              // Legacy assistant messages (no parts): treat as markdown so
              // tables/code/links render properly even for old history.
              <>
                {msg.steps && msg.steps.length > 0 && (
                  <StepsTimeline steps={msg.steps} />
                )}
                <ArtifactFrame
                  part={{
                    id: `${msg.timestamp}-legacy`,
                    mime: "text/markdown",
                    data: msg.content,
                    sensitivity_tier: 2,
                  }}
                />
              </>
            ) : (
              <>
                {msg.steps && msg.steps.length > 0 && (
                  <StepsTimeline steps={msg.steps} />
                )}
                <span className="whitespace-pre-wrap">{msg.content}</span>
              </>
            )}
          </div>
        )}

        {/* Footer: sources + latency (assistant only) */}
        {!isUser && !msg.error && (
          <>
            {(msg.sources || msg.latency_ms != null) && (
              <div className="mt-2 border-t border-hairline pt-2 flex items-center gap-2 text-[12px] text-muted">
                {msg.latency_ms != null && (
                  <span className="flex items-center gap-1">
                    <Clock className="h-3 w-3" strokeWidth={1.6} />
                    {(msg.latency_ms / 1000).toFixed(1)}s
                  </span>
                )}
                {msg.sources && msg.sources.length > 0 && (
                  <span>· {msg.sources.length} source{msg.sources.length !== 1 && "s"}</span>
                )}
                {msg.model && (
                  <span>· {msg.model}</span>
                )}
              </div>
            )}
            {msg.sources && <SourcesSection sources={msg.sources} />}
          </>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main Chat component
// ---------------------------------------------------------------------------

interface AgentChoice {
  readonly agent_id: string;
  readonly name: string;
}

interface AgentListRow {
  readonly agent_id: string;
  readonly name: string;
  readonly tags: ReadonlyArray<string>;
  readonly config: {
    readonly resolved_model: string | null;
    readonly model_route: string;
    readonly model_override: string | null;
  };
}

interface AgentListResponse {
  readonly agents: ReadonlyArray<AgentListRow>;
}

const AGENT_STORAGE_KEY = "arandu.chat.agent";
const DEFAULT_AGENT_ID = "chat";

function Chat() {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [selectedAgent, setSelectedAgentState] = useState<string>(() => {
    if (typeof window === "undefined") return DEFAULT_AGENT_ID;
    return window.sessionStorage.getItem(AGENT_STORAGE_KEY)
      || DEFAULT_AGENT_ID;
  });
  const setSelectedAgent = useCallback((id: string) => {
    setSelectedAgentState(id);
    if (typeof window !== "undefined") {
      window.sessionStorage.setItem(AGENT_STORAGE_KEY, id);
    }
  }, []);
  const bottomRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  // Held to break a circular dependency: the prefill effect needs to
  // call sendMessage, but sendMessage is defined later in the file.
  const sendMessageRef = useRef<
    | ((
        text: string,
        replyContext?: ReplyContext,
        taskContext?: { task_id: string; goal_id?: string | null },
      ) => Promise<void>)
    | null
  >(null);

  const agentList = useAsyncData<AgentListResponse>(
    useCallback(
      () => dedupInvoke<AgentListResponse>("list_pydantic_agents"),
      [],
    ),
  );
  const agentChoices = useMemo<ReadonlyArray<AgentChoice>>(() => {
    const rows = agentList.data?.agents ?? [];
    const userAgents = rows
      .filter((r) =>
        r.agent_id.startsWith("user.") || r.tags.includes("user")
      )
      .map((r) => ({ agent_id: r.agent_id, name: r.name }));
    return [
      { agent_id: "chat", name: "Chat" },
      { agent_id: "brain", name: "Brain" },
      ...userAgents,
    ];
  }, [agentList.data]);

  const stream = useStreamingChat();
  const location = useLocation();
  const audio = useAudioRecording();

  // Read preferred language so the ASR backend gets a hint instead of
  // auto-detecting. Bilingual users in Settings → Preferred language
  // shouldn't see their Spanish transcribed as English.
  const settingsResult = useAsyncData<{ user_language: string | null }>(
    useCallback(
      () => dedupInvoke<{ user_language: string | null }>("get_settings"),
      [],
    ),
  );
  const languageHint = settingsResult.data?.user_language ?? undefined;

  // Guard: set to true once the initial session has been selected
  // (either by auto-select or by a prefilled auto-submit navigation).
  const autoSelectedRef = useRef(false);

  // Prefill input from navigation state. The Dashboard's CommandBar
  // and the inbox row actions both pass `autoSubmit: true` to
  // fire-and-forget into a chat. Each navigation gets a fresh
  // `location.key`, so we key the one-shot guard on that — a single
  // ref shared across the component lifetime would silently drop
  // every navigation after the first.
  const lastAutoSubmitKey = useRef<string | null>(null);
  useEffect(() => {
    const state = location.state as
      | {
          prefilled?: string;
          autoSubmit?: boolean;
          replyContext?: ReplyContext;
          taskContext?: { task_id: string; goal_id?: string | null };
        }
      | null;
    if (state?.prefilled) {
      setInput(state.prefilled);
      inputRef.current?.focus();
      if (
        state.autoSubmit &&
        location.key !== lastAutoSubmitKey.current
      ) {
        lastAutoSubmitKey.current = location.key;
        // Prevent the auto-select effect from loading an old session
        autoSelectedRef.current = true;
        setHistoryLoading(false);
        // Start a fresh session so the question doesn't land in an old conversation
        void (async () => {
          try {
            const created = await invoke<ChatSessionSummary>("new_chat_session");
            setActiveSessionId(created.id);
            setMessages([]);
            stream.reset();
          } catch {
            setActiveSessionId(null);
            setMessages([]);
          }
          void sendMessageRef.current?.(
            state.prefilled!,
            state.replyContext,
            state.taskContext,
          );
          void sessionsResult.refetch();
        })();
        setInput("");
      }
      // Clear the navigation state so it doesn't re-apply on re-render
      window.history.replaceState({}, document.title);
    }
  }, [location.state, location.key]); // eslint-disable-line react-hooks/exhaustive-deps

  // Sessions panel — list of persisted conversations
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null);
  const sessionsResult = useAsyncData<ChatSessionListResponse>(
    useCallback(
      () => dedupInvoke<ChatSessionListResponse>("list_chat_sessions"),
      [],
    ),
  );
  const sessions = sessionsResult.data?.sessions ?? [];
  const [historyLoading, setHistoryLoading] = useState(true);

  // Opening the Chat page always starts a fresh conversation. The
  // sidebar still lists prior sessions; clicking one loads it via
  // handleSelectSession. The session row itself is created lazily in
  // sendMessage on first send, so we don't spawn empty sessions if the
  // user navigates away without typing.
  useEffect(() => {
    if (autoSelectedRef.current) return;
    if (!sessionsResult.data) return;
    autoSelectedRef.current = true;
    setHistoryLoading(false);
  }, [sessionsResult.data]);

  // Auto-scroll on new messages and streaming text
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, loading, stream.text]);

  // Finalize streaming message into the messages array when done
  useEffect(() => {
    if (!stream.isStreaming && stream.recipientDisambiguation) {
      const proposal = stream.recipientDisambiguation;
      const disambigMsg: ChatMessage = {
        role: "assistant",
        content: "",
        timestamp: new Date().toISOString(),
        recipient_disambiguation: proposal,
      };
      setMessages((prev) => [...prev, disambigMsg]);
      stream.reset();
      setLoading(false);
      inputRef.current?.focus();
    } else if (!stream.isStreaming && stream.actionProposal) {
      // Action proposal received — show confirmation card. Low-risk
      // proposals auto-execute via handleConfirmActionRef so the
      // user never has to confirm a read-only call (search / list /
      // get / find / web_search). The audit chain still runs.
      const proposal = stream.actionProposal;
      const proposalMsg: ChatMessage = {
        role: "assistant",
        content: "",
        timestamp: new Date().toISOString(),
        action_proposal: proposal,
      };
      setMessages((prev) => [...prev, proposalMsg]);
      stream.reset();
      setLoading(false);
      inputRef.current?.focus();
      if (proposal.risk === "low") {
        void handleConfirmActionRef.current?.(proposal);
      }
    } else if (
      !stream.isStreaming &&
      (stream.text || stream.parts.length > 0)
    ) {
      const assistantMsg: ChatMessage = {
        role: "assistant",
        content: stream.text,
        timestamp: new Date().toISOString(),
        sources: stream.sources as Source[],
        latency_ms: stream.latencyMs,
        model: stream.model,
        error: stream.error ?? undefined,
        parts: stream.parts.length > 0 ? stream.parts : undefined,
        thinking: stream.thinking || undefined,
        steps: stream.steps.length > 0 ? stream.steps : undefined,
      };

      setMessages((prev) => [...prev, assistantMsg]);
      stream.reset();
      setLoading(false);
      inputRef.current?.focus();
    } else if (!stream.isStreaming && stream.error && !stream.text) {
      // Error before any tokens arrived
      const errorMsg: ChatMessage = {
        role: "assistant",
        content: "",
        timestamp: new Date().toISOString(),
        error: stream.error,
      };

      setMessages((prev) => [...prev, errorMsg]);
      stream.reset();
      setLoading(false);
      inputRef.current?.focus();
    }
  }, [
    stream.isStreaming,
    stream.text,
    stream.error,
    stream.actionProposal,
    stream.recipientDisambiguation,
    stream.parts.length,
    stream.steps.length,
  ]); // eslint-disable-line react-hooks/exhaustive-deps

  const [confirmingProposalId, setConfirmingProposalId] = useState<
    string | null
  >(null);

  const handleConfirmAction = useCallback(
    async (proposal: ActionProposal) => {
      setConfirmingProposalId(proposal.proposal_id);
      try {
        const result = await invoke<ActionResultInfo>("confirm_action", {
          proposalJson: JSON.stringify(proposal),
        });
        const resultMsg: ChatMessage = {
          role: "assistant",
          content: "",
          timestamp: new Date().toISOString(),
          action_result: result,
          action_proposal: proposal,
        };
        setMessages((prev) => [...prev, resultMsg]);
      } catch (err) {
        const errStr =
          err instanceof Error ? err.message : String(err);
        const resultMsg: ChatMessage = {
          role: "assistant",
          content: "",
          timestamp: new Date().toISOString(),
          action_result: {
            status: "error",
            output: "",
            error: errStr,
          },
          action_proposal: proposal,
        };
        setMessages((prev) => [...prev, resultMsg]);
      } finally {
        setConfirmingProposalId(null);
      }
    },
    [],
  );

  // Ref-mirror of handleConfirmAction so the streaming-finalize effect
  // can auto-confirm low-risk proposals without listing the callback
  // in its deps array (the effect already disables the lint rule for
  // a tightly-curated dep list).
  const handleConfirmActionRef = useRef<typeof handleConfirmAction | null>(
    null,
  );
  useEffect(() => {
    handleConfirmActionRef.current = handleConfirmAction;
  }, [handleConfirmAction]);

  const handleCancelAction = useCallback(
    async (proposal: ActionProposal) => {
      try {
        await invoke("cancel_action", {
          proposalId: proposal.proposal_id,
        });
      } catch {
        // Cancellation is best-effort
      }
      const cancelMsg: ChatMessage = {
        role: "assistant",
        content: `Cancelled: ${proposal.display_name}`,
        timestamp: new Date().toISOString(),
      };
      setMessages((prev) => [...prev, cancelMsg]);
    },
    [],
  );

  const [resolvingDisambigId, setResolvingDisambigId] = useState<
    string | null
  >(null);

  const handlePickRecipient = useCallback(
    async (
      disambiguation: RecipientDisambiguationProposal,
      candidate: ContactCandidate,
    ) => {
      setResolvingDisambigId(disambiguation.proposal_id);
      try {
        const payload = await invoke<{
          type: string;
          proposal?: ActionProposal;
          error?: string;
        }>("resume_action_with_recipient", {
          disambiguationJson: JSON.stringify(disambiguation),
          candidateJson: JSON.stringify(candidate),
        });
        if (payload?.proposal) {
          // Replace the disambiguation message with the new
          // ActionProposal so the picker collapses into the regular
          // confirmation card in the same slot.
          setMessages((prev) =>
            prev.map((m) =>
              m.recipient_disambiguation?.proposal_id ===
              disambiguation.proposal_id
                ? {
                    role: "assistant" as const,
                    content: "",
                    timestamp: new Date().toISOString(),
                    action_proposal: payload.proposal,
                  }
                : m,
            ),
          );
        } else if (payload?.error) {
          const errMsg: ChatMessage = {
            role: "assistant",
            content: `Couldn't build the action: ${payload.error}`,
            timestamp: new Date().toISOString(),
          };
          setMessages((prev) => [...prev, errMsg]);
        }
      } catch (err) {
        const errStr = err instanceof Error ? err.message : String(err);
        const errMsg: ChatMessage = {
          role: "assistant",
          content: `Couldn't resolve recipient: ${errStr}`,
          timestamp: new Date().toISOString(),
        };
        setMessages((prev) => [...prev, errMsg]);
      } finally {
        setResolvingDisambigId(null);
      }
    },
    [],
  );

  const handleSearchRecipients = useCallback(
    async (
      disambiguation: RecipientDisambiguationProposal,
      query: string,
      includeApple: boolean,
    ): Promise<ContactCandidate[]> => {
      const payload = await invoke<{ candidates?: ContactCandidate[] }>(
        "search_recipient_candidates",
        {
          query,
          channel: disambiguation.channel,
          includeApple,
          limit: 5,
        },
      );
      return payload?.candidates ?? [];
    },
    [],
  );

  const handleCancelDisambiguation = useCallback(
    (disambiguation: RecipientDisambiguationProposal) => {
      // No backend cancel for disambiguation (no DB-side pending row
      // on the app-chat path — only the WhatsApp listener stores it).
      // Just collapse the card into a small text message.
      setMessages((prev) =>
        prev.map((m) =>
          m.recipient_disambiguation?.proposal_id ===
          disambiguation.proposal_id
            ? {
                role: "assistant" as const,
                content: `Cancelled: ${disambiguation.display_name}`,
                timestamp: new Date().toISOString(),
              }
            : m,
        ),
      );
    },
    [],
  );

  const sendMessage = useCallback(
    async (
      text: string,
      replyContext?: ReplyContext,
      taskContext?: { task_id: string; goal_id?: string | null },
    ) => {
      const question = text.trim();
      if (!question || loading) return;

      // If no session is active yet, create one before sending so the
      // Rust side's `active_chat_session` pointer matches what the
      // sessions list will show after this exchange.
      let sessionId = activeSessionId;
      if (!sessionId) {
        try {
          const created = await invoke<ChatSessionSummary>(
            "new_chat_session",
          );
          sessionId = created.id;
          setActiveSessionId(created.id);
        } catch {
          // Fall through — the backend will still create one lazily.
        }
      }

      const userMsg: ChatMessage = {
        role: "user",
        content: question,
        timestamp: new Date().toISOString(),
      };

      setMessages((prev) => [...prev, userMsg]);
      setInput("");
      setLoading(true);

      await stream.sendStreamingMessage(
        question,
        selectedAgent,
        replyContext,
        taskContext,
      );
      void sessionsResult.refetch();
    },
    [loading, stream, selectedAgent, activeSessionId, sessionsResult],
  );
  sendMessageRef.current = sendMessage;

  const handleSelectSession = useCallback(
    async (id: string) => {
      if (id === activeSessionId) return;
      setHistoryLoading(true);
      try {
        const loaded = await invoke<LoadSessionResponse>(
          "load_chat_session",
          { sessionId: id },
        );
        setMessages([...loaded.messages]);
        setActiveSessionId(id);
        setPanelPart(null);
        setPanelHistory([]);
        stream.reset();
        setLoading(false);
      } finally {
        setHistoryLoading(false);
      }
    },
    [activeSessionId, stream],
  );

  const handleNewSession = useCallback(async () => {
    setHistoryLoading(true);
    try {
      const created = await invoke<ChatSessionSummary>("new_chat_session");
      setActiveSessionId(created.id);
      setMessages([]);
      setPanelPart(null);
      setPanelHistory([]);
      stream.reset();
      setLoading(false);
      void sessionsResult.refetch();
    } finally {
      setHistoryLoading(false);
    }
  }, [sessionsResult, stream]);

  const handleDeleteSession = useCallback(
    async (id: string) => {
      await invoke("delete_chat_session", { sessionId: id }).catch(() => {});
      const wasActive = id === activeSessionId;
      const refreshed = await invoke<ChatSessionListResponse>(
        "list_chat_sessions",
      );
      void sessionsResult.refetch();
      if (wasActive) {
        const next = refreshed.sessions[0]?.id ?? null;
        if (next) {
          await handleSelectSession(next);
        } else {
          setActiveSessionId(null);
          setMessages([]);
        }
      }
    },
    [activeSessionId, sessionsResult, handleSelectSession],
  );

  const handleClear = useCallback(async () => {
    await handleNewSession();
  }, [handleNewSession]);

  // Side panel for large/explicit-panel artifacts. `panelHistory`
  // remembers every part the user has opened so they can switch back.
  const [panelPart, setPanelPart] = useState<MessagePart | null>(null);
  const [panelHistory, setPanelHistory] = useState<ReadonlyArray<MessagePart>>(
    [],
  );

  const openInPanel = useCallback((part: MessagePart) => {
    setPanelPart(part);
    setPanelHistory((prev) => {
      const without = prev.filter((p) => p.id !== part.id);
      return [part, ...without].slice(0, 8);
    });
  }, []);

  const closePanel = useCallback(() => setPanelPart(null), []);

  // Auto-open any streamed part marked `display: "panel"`.
  useEffect(() => {
    for (const p of stream.parts) {
      if (p.display === "panel" && p.id !== panelPart?.id) {
        openInPanel(p);
      }
    }
  }, [stream.parts, panelPart?.id, openInPanel]);

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendMessage(input);
    }
  };

  const hasMessages = messages.length > 0;
  const [inputFocused, setInputFocused] = useState(false);
  const [delegation, setDelegation] = useState<DelegationIntent | null>(null);
  // Captured from WatcherWizard.onCreated so the wizard's Done button
  // can deep-link to the new agent. Using a ref (not state) keeps the
  // wizard from re-rendering when the id arrives and avoids the
  // setDelegation(null) + setState race that previously closed the
  // wizard before the user could see the "N cases created" line.
  const createdAgentIdRef = useRef<string | null>(null);
  const navigate = useNavigate();

  // When the LLM calls the create_watcher tool, the stream emits a
  // watcher_proposal chunk. Convert it into a DelegationIntent and
  // open the wizard.
  useEffect(() => {
    if (!stream.isStreaming && stream.watcherProposal) {
      const wp = stream.watcherProposal;
      setDelegation({
        kind: "delegate",
        prompt: wp.prompt,
        suggestedName: wp.name,
        suggestedCron: wp.suggestedCron,
      });
      stream.reset();
      setLoading(false);
    }
  }, [stream.isStreaming, stream.watcherProposal]); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div className="flex h-full flex-row">
      <SessionsPanel
        sessions={sessions}
        activeId={activeSessionId}
        isLoading={sessionsResult.isLoading}
        onSelect={(id) => { void handleSelectSession(id); }}
        onNew={() => { void handleNewSession(); }}
        onDelete={(id) => { void handleDeleteSession(id); }}
      />
      <div className="flex h-full min-w-0 flex-1 flex-col">
      {/* Header with clear button and Ollama status */}
      {hasMessages && (
        <div className="frosted flex items-center justify-between border-b border-hairline px-4 py-3">
          <div className="flex items-center gap-3">
            <h2 className="text-lg font-semibold text-ink">Conversation</h2>
            <ModelStatusBadge
              agent={
                (agentList.data?.agents ?? []).find(
                  (a) => a.agent_id === selectedAgent,
                ) ?? null
              }
              onChanged={() => { void agentList.refetch(); }}
            />
            <ModelStatusIndicator />
            {agentChoices.length > 1 && (
              <select
                value={selectedAgent}
                onChange={(e) => setSelectedAgent(e.target.value)}
                className="rounded-2 border border-hairline bg-surface px-2 py-1 text-[11px] text-ink hover:bg-surface-2"
                title="Which agent answers your messages"
              >
                {agentChoices.map((c) => (
                  <option key={c.agent_id} value={c.agent_id}>
                    {c.name}
                  </option>
                ))}
              </select>
            )}
          </div>
          <button
            onClick={handleClear}
            className="flex items-center gap-1.5 rounded-2 px-3 py-1.5 text-xs text-muted hover:bg-surface hover:text-ink"
          >
            <Trash2 className="h-3.5 w-3.5" strokeWidth={1.6} />
            Clear
          </button>
        </div>
      )}

      {/* Message area */}
      <div className="flex-1 overflow-y-auto px-4 pt-4">
        {historyLoading ? (
          <div className="space-y-4 pb-4">
            <SkeletonChatMessage />
            <SkeletonChatMessage isUser />
            <SkeletonChatMessage />
          </div>
        ) : hasMessages || loading ? (
          <div className="space-y-5 pb-4">
            {messages.map((msg, i) => {
              if (msg.action_result && msg.action_proposal) {
                return (
                  <ActionResultCard
                    key={i}
                    result={msg.action_result}
                    displayName={msg.action_proposal.display_name}
                  />
                );
              }
              if (msg.action_proposal && !msg.action_result) {
                return (
                  <ActionConfirmationCard
                    key={i}
                    proposal={msg.action_proposal}
                    onConfirm={() =>
                      handleConfirmAction(msg.action_proposal!)
                    }
                    onCancel={() =>
                      handleCancelAction(msg.action_proposal!)
                    }
                    confirming={
                      confirmingProposalId ===
                      msg.action_proposal.proposal_id
                    }
                  />
                );
              }
              if (msg.recipient_disambiguation) {
                return (
                  <RecipientDisambiguationCard
                    key={i}
                    proposal={msg.recipient_disambiguation}
                    onPick={(candidate) =>
                      handlePickRecipient(
                        msg.recipient_disambiguation!,
                        candidate,
                      )
                    }
                    onCancel={() =>
                      handleCancelDisambiguation(
                        msg.recipient_disambiguation!,
                      )
                    }
                    onSearch={(q, includeApple) =>
                      handleSearchRecipients(
                        msg.recipient_disambiguation!,
                        q,
                        includeApple,
                      )
                    }
                    resolving={
                      resolvingDisambigId ===
                      msg.recipient_disambiguation.proposal_id
                    }
                  />
                );
              }
              return (
                <MessageBubble
                  key={i}
                  msg={msg}
                  onOpenInPanel={openInPanel}
                />
              );
            })}
            {loading &&
            (stream.parts.length > 0 ||
              stream.thinking ||
              stream.steps.length > 0) ? (
              <StreamingBubble
                parts={stream.parts}
                thinking={stream.thinking}
                steps={stream.steps}
                isStreaming={stream.isStreaming}
                onOpenInPanel={openInPanel}
                inExtendedResearch={stream.inExtendedResearch}
                extendedReason={stream.extendedReason}
                userStopRequested={stream.userStopRequested}
                onStop={stream.requestStop}
              />
            ) : loading ? (
              <TypingIndicator />
            ) : null}
            <div ref={bottomRef} />
          </div>
        ) : (
          <EmptyState onSuggestion={sendMessage} />
        )}
      </div>

      {/* Input area */}
      <div className="frosted shrink-0 border-t border-hairline px-4 pt-4 pb-3">
        {/* Recording indicator */}
        {audio.status === "recording" && (
          <div className="mb-2 flex items-center justify-center gap-3 text-xs text-danger">
            <span className="inline-block h-2 w-2 animate-pulse rounded-full bg-danger" />
            <span>Recording... {audio.duration}s</span>
            <div className="h-1.5 w-24 overflow-hidden rounded-pill bg-surface">
              <div
                className="h-full rounded-pill bg-danger transition-[width] duration-75"
                style={{
                  width: `${Math.min(100, Math.round(audio.level * 400))}%`,
                }}
              />
            </div>
          </div>
        )}
        {audio.status === "transcribing" && (
          <div className="mb-2 flex items-center justify-center gap-2 text-xs text-muted">
            <Loader2 className="h-3 w-3 animate-spin" strokeWidth={1.6} />
            Transcribing...
          </div>
        )}
        {audio.error && (
          <div className="mb-2 text-center text-xs text-amber">
            {audio.error}
          </div>
        )}
        <div className={`flex items-center gap-3 rounded-3 border bg-surface px-4 py-3 shadow-1 transition-shadow ${inputFocused ? "border-indigo shadow-glow" : "border-hairline-2"}`}>
          <input
            ref={inputRef}
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            onFocus={() => setInputFocused(true)}
            onBlur={() => setInputFocused(false)}
            placeholder="Ask your Arandu anything..."
            disabled={loading || audio.status === "recording" || audio.status === "transcribing"}
            className="flex-1 bg-transparent text-sm text-ink placeholder-muted outline-none disabled:opacity-50"
          />
          {/* Mic button */}
          {audio.status === "recording" ? (
            <button
              onClick={async () => {
                const result = await audio.stopAndTranscribe();
                if (result?.text) {
                  setInput(result.text);
                  inputRef.current?.focus();
                }
              }}
              className="flex h-8 w-8 items-center justify-center rounded-[9px] bg-danger text-white transition-opacity hover:opacity-90"
              title="Stop recording"
            >
              <Square className="h-4 w-4" strokeWidth={1.6} />
            </button>
          ) : (
            <button
              onClick={() =>
                audio.startRecording({
                  languageHint,
                  onResult: (result) => {
                    if (result.text) {
                      setInput(result.text);
                      inputRef.current?.focus();
                    }
                  },
                })
              }
              disabled={loading || audio.status === "transcribing"}
              className="flex h-8 w-8 items-center justify-center rounded-[9px] text-muted transition-colors hover:bg-surface-2 hover:text-ink disabled:opacity-40"
              title="Record voice message"
            >
              {audio.status === "transcribing" ? (
                <Loader2 className="h-4 w-4 animate-spin" strokeWidth={1.6} />
              ) : (
                <Mic className="h-4 w-4" strokeWidth={1.6} />
              )}
            </button>
          )}
          {/* Send button */}
          <button
            onClick={() => sendMessage(input)}
            disabled={loading || !input.trim() || audio.status === "recording"}
            className="flex h-8 w-8 items-center justify-center rounded-[9px] bg-ink text-white transition-colors hover:bg-indigo disabled:opacity-40"
          >
            {loading ? (
              <Loader2 className="h-4 w-4 animate-spin" strokeWidth={1.6} />
            ) : (
              <Send className="h-4 w-4" strokeWidth={1.6} />
            )}
          </button>
        </div>
        <p className="mt-2 text-center text-[11.5px] text-faint">
          Your data stays on this device, always.
        </p>
      </div>
      </div>
      {panelPart && (
        <ArtifactSidePanel
          part={panelPart}
          history={panelHistory}
          onSelect={openInPanel}
          onClose={closePanel}
        />
      )}
      {delegation && (
        <WatcherWizard
          intent={delegation}
          onClose={() => {
            const createdId = createdAgentIdRef.current;
            createdAgentIdRef.current = null;
            setDelegation(null);
            if (createdId) navigate(`/agents?agent=${createdId}`);
          }}
          onCreated={(agentId) => {
            createdAgentIdRef.current = agentId;
          }}
        />
      )}
    </div>
  );
}

export default Chat;

/**
 * Hook for streaming Brain Agent responses via Tauri events.
 *
 * Listens for `brain-stream` events emitted by the Rust backend,
 * accumulates tokens into growing text, accumulates typed artifact
 * parts by `part_id`, and tracks streaming state.
 *
 * Streaming protocol (JSON-line chunks emitted by Python `ask-stream`):
 *
 *   { type: "context", context_summary, sources }
 *   { type: "token",   token }                       // back-compat plain text
 *   { type: "part_start", part_id, mime, title?, display?, sensitivity_tier?, metadata? }
 *   { type: "part_chunk", part_id, data }            // streaming text/code/markdown
 *   { type: "part_done",  part_id, data? }           // final blob for non-streaming parts
 *   { type: "thinking",   text }                     // collapsible reasoning trace
 *   { type: "done",    model, latency_ms }
 *   { type: "error",   error }
 *   { type: "action_proposal", proposal }
 *
 * The `token` variant is a back-compat alias that appends to an
 * implicit default `text/markdown` part with id `default`.
 *
 * sensitivity_tier: 3 (receives streamed LLM output from personal context)
 */

import { useState, useRef, useCallback } from "react";
import { invoke } from "@tauri-apps/api/core";
import { listen, type UnlistenFn } from "@tauri-apps/api/event";
import type { MessagePart } from "../types/chat";
import type { ReplyContext } from "./useReplyContext";

interface Source {
  type?: string;
  content?: string;
  sensitivity_tier?: number;
  [key: string]: unknown;
}

export interface ActionRecipientPreview {
  /** Channel that will receive the action — drives icon + label. */
  readonly channel: "whatsapp" | "email" | "imessage";
  /** Raw recipient string the LLM emitted, before contact lookup. */
  readonly input: string;
  /** Resolved contact name (or the raw input if we couldn't match). */
  readonly name: string;
  readonly phone: string | null;
  readonly email: string | null;
  /**
   * `true` when we matched the recipient to a saved contact AND
   * have the channel-appropriate identifier (phone for whatsapp,
   * email for mail, either for imessage). `false` means the card
   * must surface a warning before the user clicks Confirm.
   */
  readonly resolved: boolean;
  /** Human-readable warning shown when `resolved` is false. */
  readonly warning?: string;
}

export interface ActionProposal {
  readonly proposal_id: string;
  readonly connector_id: string;
  readonly connector_name: string;
  readonly tool_name: string;
  readonly display_name: string;
  readonly arguments: Record<string, unknown>;
  readonly description: string;
  readonly missing_params: string[];
  readonly command: string;
  readonly args: string[];
  /**
   * `low` for read-only tools (search_*, get_*, list_*, find_*,
   * read_*, recall_*, web_search) that auto-execute without the
   * Confirm/Cancel prompt. `high` (default) requires user
   * confirmation. The audit chain runs either way.
   */
  readonly risk?: "low" | "high";
  /**
   * Populated for messaging / email tools so the confirmation card
   * can show the resolved recipient identity (name + phone/email)
   * BEFORE the user presses Confirm — prevents the "to: WhatsApp"
   * class of failure where the LLM put a channel name in the
   * recipient field. `null` for non-messaging tools.
   */
  readonly recipient_preview?: ActionRecipientPreview | null;
}

export interface ContactCandidate {
  readonly name: string;
  readonly handle: string | null;
  readonly relationship: string;
  readonly active_topic: string;
  readonly topic_importance: number;
  readonly notification_priority: number;
  readonly source: "mart" | "stg_contacts" | "apple_mcp";
}

/**
 * Recipient picker payload — emitted instead of an ActionProposal
 * when the brain needs the user to confirm which contact a
 * messaging action should target. The user picks a candidate;
 * the frontend calls `resume_action_with_recipient` and receives
 * a normal ActionProposal in the same chat message slot.
 */
export interface RecipientDisambiguationProposal {
  readonly proposal_id: string;
  readonly connector_id: string;
  readonly connector_name: string;
  readonly tool_name: string;
  readonly display_name: string;
  readonly channel: string;
  readonly original_name: string;
  readonly candidates: ContactCandidate[];
  readonly draft_arguments: Record<string, unknown>;
  readonly command: string;
  readonly args: string[];
  readonly question: string;
  readonly context_text: string;
}

export interface WatcherProposal {
  readonly name: string;
  readonly prompt: string;
  readonly suggestedCron: string;
}

export type ToolStepStatus = "running" | "ok" | "error" | "incomplete";

export interface ToolStep {
  readonly id: string;
  readonly name: string;
  readonly args_summary: string;
  readonly status: ToolStepStatus;
  readonly duration_ms?: number;
  readonly result_summary?: string;
  readonly error?: string;
}

type StreamChunk =
  | {
      type: "context";
      context_summary?: string;
      sources?: Source[];
    }
  | { type: "token"; token: string }
  | {
      type: "part_start";
      part_id: string;
      mime: string;
      title?: string;
      display?: "inline" | "panel";
      sensitivity_tier?: number;
      metadata?: Record<string, unknown>;
    }
  | { type: "part_chunk"; part_id: string; data: string }
  | { type: "part_done"; part_id: string; data?: string | object }
  | { type: "thinking"; text: string }
  | { type: "done"; model?: string; latency_ms?: number }
  | { type: "error"; error?: string; latency_ms?: number }
  | { type: "action_proposal"; proposal?: ActionProposal }
  | {
      type: "recipient_disambiguation";
      proposal?: RecipientDisambiguationProposal;
    }
  | {
      type: "tool_call_start";
      call_id: string;
      name: string;
      args_summary?: string;
    }
  | {
      type: "tool_call_done";
      call_id: string;
      name?: string;
      duration_ms?: number;
      status?: "ok" | "error";
      result_summary?: string;
      error?: string;
    }
  | {
      type: "run_started";
      run_id: string;
      task_class: TaskClass;
      expected_total_ms?: number;
    }
  | { type: "self_review_start"; elapsed_ms?: number }
  | {
      type: "self_review_done";
      continue?: boolean;
      reason?: string;
      suggested_class?: TaskClass;
      elapsed_ms?: number;
    }
  | {
      type: "extended_research_announced";
      reason?: string;
      task_class: TaskClass;
      expected_total_ms?: number;
    }
  | { type: "user_stopped_research"; elapsed_ms?: number }
  | {
      type: "watcher_proposal";
      name: string;
      prompt: string;
      suggested_cron?: string;
    };

export type TaskClass =
  | "interactive_fast"
  | "interactive_deep"
  | "background_deep";

export interface StreamingState {
  readonly text: string;
  readonly isStreaming: boolean;
  readonly contextSummary: string;
  readonly sources: Source[];
  readonly model: string;
  readonly latencyMs: number;
  readonly error: string | null;
  readonly actionProposal: ActionProposal | null;
  readonly recipientDisambiguation: RecipientDisambiguationProposal | null;
  readonly watcherProposal: WatcherProposal | null;
  readonly parts: MessagePart[];
  readonly thinking: string;
  readonly steps: ToolStep[];
  /** Reflective-runner extras. */
  readonly runId: string | null;
  readonly taskClass: TaskClass | null;
  readonly expectedTotalMs: number | null;
  readonly inSelfReview: boolean;
  readonly inExtendedResearch: boolean;
  readonly extendedReason: string;
  readonly userStopRequested: boolean;
}

export interface TaskContext {
  readonly task_id: string;
  readonly goal_id?: string | null;
}

export interface UseStreamingChatResult extends StreamingState {
  readonly sendStreamingMessage: (
    question: string,
    agentId?: string,
    replyContext?: ReplyContext,
    taskContext?: TaskContext,
  ) => Promise<void>;
  readonly reset: () => void;
  /**
   * Ask the running orchestrator to stop researching and synthesize
   * its final answer with whatever context it already has. Non-
   * blocking — the stream keeps running and a `user_stopped_research`
   * chunk eventually arrives followed by the normal `done` chunk.
   */
  readonly requestStop: () => Promise<void>;
}

const INITIAL_STATE: StreamingState = {
  text: "",
  isStreaming: false,
  contextSummary: "",
  sources: [],
  model: "",
  latencyMs: 0,
  error: null,
  actionProposal: null,
  recipientDisambiguation: null,
  watcherProposal: null,
  parts: [],
  thinking: "",
  steps: [],
  runId: null,
  taskClass: null,
  expectedTotalMs: null,
  inSelfReview: false,
  inExtendedResearch: false,
  extendedReason: "",
  userStopRequested: false,
};

const DEFAULT_PART_ID = "default";

/**
 * Stream a Brain Agent response token-by-token and part-by-part.
 *
 * Usage:
 * ```tsx
 * const stream = useStreamingChat();
 * await stream.sendStreamingMessage("What do I have today?");
 * // stream.parts grows as artifacts arrive; stream.text mirrors the
 * // default markdown part for back-compat with plain-text consumers.
 * // stream.isStreaming becomes false when done.
 * ```
 */
export function useStreamingChat(): UseStreamingChatResult {
  const [state, setState] = useState<StreamingState>(INITIAL_STATE);
  const unlistenRef = useRef<UnlistenFn | null>(null);

  // Mutable refs to assemble parts as chunks arrive. We commit to React
  // state on every chunk so renderers update; the refs let us update
  // without racing against the previous setState.
  const partsRef = useRef<Map<string, MessagePart>>(new Map());
  const orderRef = useRef<string[]>([]);
  const thinkingRef = useRef<string>("");
  const stepsRef = useRef<ToolStep[]>([]);
  const stepIndexRef = useRef<Map<string, number>>(new Map());

  const cleanup = useCallback(() => {
    if (unlistenRef.current) {
      unlistenRef.current();
      unlistenRef.current = null;
    }
  }, []);

  const snapshotParts = useCallback((): MessagePart[] => {
    return orderRef.current
      .map((id) => partsRef.current.get(id))
      .filter((p): p is MessagePart => p != null);
  }, []);

  const reset = useCallback(() => {
    cleanup();
    partsRef.current = new Map();
    orderRef.current = [];
    thinkingRef.current = "";
    stepsRef.current = [];
    stepIndexRef.current = new Map();
    setState(INITIAL_STATE);
  }, [cleanup]);

  const ensureDefaultPart = useCallback((): MessagePart => {
    const existing = partsRef.current.get(DEFAULT_PART_ID);
    if (existing) return existing;
    const part: MessagePart = {
      id: DEFAULT_PART_ID,
      mime: "text/markdown",
      data: "",
      display: "inline",
      sensitivity_tier: 2,
      streaming: true,
    };
    partsRef.current.set(DEFAULT_PART_ID, part);
    orderRef.current.push(DEFAULT_PART_ID);
    return part;
  }, []);

  const sendStreamingMessage = useCallback(
    async (
      question: string,
      agentId: string = "brain",
      replyContext?: ReplyContext,
      taskContext?: TaskContext,
    ) => {
      cleanup();
      partsRef.current = new Map();
      orderRef.current = [];
      thinkingRef.current = "";
      stepsRef.current = [];
      stepIndexRef.current = new Map();
      setState({ ...INITIAL_STATE, isStreaming: true });

      unlistenRef.current = await listen<StreamChunk>(
        "brain-stream",
        (event) => {
          const chunk = event.payload;

          switch (chunk.type) {
            case "context":
              setState((prev) => ({
                ...prev,
                contextSummary: chunk.context_summary ?? "",
                sources: (chunk.sources ?? []) as Source[],
              }));
              break;

            case "token": {
              if (!chunk.token) break;
              const part = ensureDefaultPart();
              const next: MessagePart = {
                ...part,
                data: String(part.data ?? "") + chunk.token,
                streaming: true,
              };
              partsRef.current.set(DEFAULT_PART_ID, next);
              const allParts = snapshotParts();
              setState((prev) => ({
                ...prev,
                text: String(next.data ?? ""),
                parts: allParts,
              }));
              break;
            }

            case "part_start": {
              const part: MessagePart = {
                id: chunk.part_id,
                mime: chunk.mime,
                title: chunk.title,
                data: "",
                display: chunk.display ?? "inline",
                sensitivity_tier: (chunk.sensitivity_tier ?? 2) as 1 | 2 | 3,
                metadata: chunk.metadata,
                streaming: true,
              };
              partsRef.current.set(part.id, part);
              if (!orderRef.current.includes(part.id)) {
                orderRef.current.push(part.id);
              }
              setState((prev) => ({ ...prev, parts: snapshotParts() }));
              break;
            }

            case "part_chunk": {
              const existing = partsRef.current.get(chunk.part_id);
              if (!existing) break;
              const next: MessagePart = {
                ...existing,
                data: String(existing.data ?? "") + (chunk.data ?? ""),
                streaming: true,
              };
              partsRef.current.set(chunk.part_id, next);
              const isDefault = chunk.part_id === DEFAULT_PART_ID;
              const allParts = snapshotParts();
              setState((prev) => ({
                ...prev,
                text: isDefault ? String(next.data ?? "") : prev.text,
                parts: allParts,
              }));
              break;
            }

            case "part_done": {
              const existing = partsRef.current.get(chunk.part_id);
              if (existing) {
                const next: MessagePart = {
                  ...existing,
                  data:
                    chunk.data !== undefined ? chunk.data : existing.data,
                  streaming: false,
                };
                partsRef.current.set(chunk.part_id, next);
              }
              setState((prev) => ({ ...prev, parts: snapshotParts() }));
              break;
            }

            case "thinking":
              thinkingRef.current += chunk.text ?? "";
              setState((prev) => ({
                ...prev,
                thinking: thinkingRef.current,
              }));
              break;

            case "tool_call_start": {
              const step: ToolStep = {
                id: chunk.call_id,
                name: chunk.name,
                args_summary: chunk.args_summary ?? "",
                status: "running",
              };
              stepIndexRef.current.set(chunk.call_id, stepsRef.current.length);
              stepsRef.current = [...stepsRef.current, step];
              setState((prev) => ({ ...prev, steps: stepsRef.current }));
              break;
            }

            case "tool_call_done": {
              const idx = stepIndexRef.current.get(chunk.call_id);
              if (idx == null) break;
              const existing = stepsRef.current[idx];
              const updated: ToolStep = {
                ...existing,
                status: chunk.status === "error" ? "error" : "ok",
                duration_ms: chunk.duration_ms,
                result_summary: chunk.result_summary,
                error: chunk.error,
              };
              const next = stepsRef.current.slice();
              next[idx] = updated;
              stepsRef.current = next;
              setState((prev) => ({ ...prev, steps: stepsRef.current }));
              break;
            }

            case "done": {
              // Finalize: mark every remaining streaming part as done.
              for (const [id, p] of partsRef.current) {
                if (p.streaming) {
                  partsRef.current.set(id, { ...p, streaming: false });
                }
              }
              // Any step still flagged "running" never received a
              // matching tool_call_done — mark it incomplete so the
              // UI doesn't show a perpetual spinner on history.
              stepsRef.current = stepsRef.current.map((s) =>
                s.status === "running" ? { ...s, status: "incomplete" } : s,
              );
              const defaultPart = partsRef.current.get(DEFAULT_PART_ID);
              setState((prev) => ({
                ...prev,
                text:
                  defaultPart != null
                    ? String(defaultPart.data ?? "")
                    : prev.text,
                parts: snapshotParts(),
                steps: stepsRef.current,
                isStreaming: false,
                model: chunk.model ?? "",
                latencyMs: chunk.latency_ms ?? 0,
              }));
              cleanup();
              break;
            }

            case "action_proposal":
              setState((prev) => ({
                ...prev,
                isStreaming: false,
                actionProposal: chunk.proposal ?? null,
                recipientDisambiguation: null,
              }));
              cleanup();
              break;

            case "recipient_disambiguation":
              setState((prev) => ({
                ...prev,
                isStreaming: false,
                recipientDisambiguation: chunk.proposal ?? null,
                actionProposal: null,
              }));
              cleanup();
              break;

            case "watcher_proposal":
              setState((prev) => ({
                ...prev,
                isStreaming: false,
                watcherProposal: {
                  name: chunk.name ?? "Watcher",
                  prompt: chunk.prompt ?? "",
                  suggestedCron: chunk.suggested_cron ?? "0 * * * *",
                },
              }));
              cleanup();
              break;

            case "error":
              setState((prev) => ({
                ...prev,
                isStreaming: false,
                error: chunk.error ?? "Unknown streaming error",
                latencyMs: chunk.latency_ms ?? 0,
              }));
              cleanup();
              break;

            case "run_started":
              setState((prev) => ({
                ...prev,
                runId: chunk.run_id,
                taskClass: chunk.task_class,
                expectedTotalMs: chunk.expected_total_ms ?? null,
              }));
              break;

            case "self_review_start":
              setState((prev) => ({ ...prev, inSelfReview: true }));
              break;

            case "self_review_done":
              setState((prev) => ({ ...prev, inSelfReview: false }));
              break;

            case "extended_research_announced":
              setState((prev) => ({
                ...prev,
                inExtendedResearch: true,
                extendedReason: chunk.reason ?? "",
                taskClass: chunk.task_class,
                expectedTotalMs:
                  chunk.expected_total_ms ?? prev.expectedTotalMs,
              }));
              break;

            case "user_stopped_research":
              setState((prev) => ({
                ...prev,
                userStopRequested: true,
                inExtendedResearch: false,
              }));
              break;
          }
        },
      );

      // Fire-and-forget; events deliver data. `agentId` defaults to "brain";
      // user agents route through ask_agent_stream while reusing the same
      // event channel.
      try {
        if (agentId && agentId !== "brain") {
          await invoke("ask_agent_stream", {
            question,
            agentId,
            replyContext: replyContext ?? null,
            taskContext: taskContext ?? null,
          });
        } else {
          await invoke("ask_brain_stream", {
            question,
            replyContext: replyContext ?? null,
            taskContext: taskContext ?? null,
          });
        }
      } catch (err) {
        const message =
          err instanceof Error
            ? err.message
            : typeof err === "string"
              ? err
              : "Failed to start streaming";
        setState((prev) => ({
          ...prev,
          isStreaming: false,
          error: message,
        }));
        cleanup();
      }
    },
    [cleanup, ensureDefaultPart, snapshotParts],
  );

  const requestStop = useCallback(async () => {
    // Optimistic UI update — we mark the stop as requested even if the
    // IPC fails so the user sees instant feedback. The streaming
    // process will still emit `user_stopped_research` if it actually
    // sees the signal at its next reflection checkpoint.
    setState((prev) => ({ ...prev, userStopRequested: true }));
    const runId = state.runId;
    if (runId == null) {
      return;
    }
    try {
      await invoke("stop_research", { runId });
    } catch (err) {
      // Best-effort: a stale run id (the agent finished between
      // banner render and click) just no-ops on the Python side.
      console.warn("[stop_research] failed", err);
    }
  }, [state.runId]);

  return {
    ...state,
    sendStreamingMessage,
    reset,
    requestStop,
  };
}

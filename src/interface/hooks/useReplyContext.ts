/**
 * Origin of a "Draft reply" click from any reply-suggesting surface
 * (Today's Loops, Inbox, domain Open Loops). Carries the source channel
 * and original `raw_messages.id` so the Brain can hard-lock the
 * proposed reply to the correct platform and resolve contact info
 * (WhatsApp JID, email address, iMessage handle).
 *
 * Mirrors `src-tauri/src/commands/types.rs::ReplyContext`.
 *
 * sensitivity_tier: 2
 */

export interface ReplyContext {
  readonly source: string;
  readonly message_id: string;
  readonly contact_name?: string | null;
}

export function buildReplyContext(input: {
  readonly source?: string | null;
  readonly message_id?: string | null;
  readonly contact_name?: string | null;
}): ReplyContext | undefined {
  if (!input.source || !input.message_id) {
    return undefined;
  }
  return {
    source: input.source,
    message_id: input.message_id,
    contact_name: input.contact_name ?? null,
  };
}

"""WhatsApp notification delivery via persistent listener IPC.

Routes all WhatsApp sends through the running listener subprocess,
which owns the sole Baileys connection.  The listener writes outbox
files and polls for responses — see
:func:`send_text_via_running_listener`.

sensitivity_tier: 2 (sends messages containing personal data summaries)
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from src.notifications.models import DeliveryResult

logger = logging.getLogger(__name__)

# ------------------------------------------------------------------
# Opt-out text templates per category
# ------------------------------------------------------------------

OPT_OUT_TEMPLATES: dict[str, str] = {
    "calendar_conflicts": "Reply STOP CALENDAR to opt out of calendar notifications.",
    "health_alerts": "Reply STOP HEALTH to opt out of health notifications.",
    "action_results": "Reply STOP ACTIONS to opt out of action notifications.",
    "pipeline_summary": "Reply STOP PIPELINE to opt out of pipeline notifications.",
    "pending_replies": "Reply STOP REPLIES to opt out of reply notifications.",
    "important_people": "Reply STOP PEOPLE to opt out of people notifications.",
    "birthday_reminders": "Reply STOP BIRTHDAYS to opt out of birthday notifications.",
    "event_actions": "Reply STOP EVENTS to opt out of event notifications.",
    "topic_action": "Reply STOP ALERTS to opt out of action notifications.",
    "topic_enrichment": "Reply STOP ENRICHMENT to opt out of enrichment notifications.",
    "conversation_digest": "Reply STOP DIGEST to opt out of conversation digests.",
}

DEFAULT_OPT_OUT = "Reply STOP ALL to opt out of all notifications."


def get_opt_out_text(category: str) -> str:
    """Return the opt-out hint for a notification category.

    sensitivity_tier: 1
    """
    return OPT_OUT_TEMPLATES.get(category, DEFAULT_OPT_OUT)


class WhatsAppNotifier:
    """Send notifications via the running WhatsApp listener process.

    All sends route through
    :func:`~src.extensions.bridges.whatsapp.listener.send_text_via_running_listener`
    (file-based outbox IPC).  Only one Baileys connection per phone can
    exist, so the listener subprocess is the single owner of the session.

    If the phone number is not configured, all sends return
    ``DeliveryResult(status="not_configured")`` without error.

    The *mcp_command* and *mcp_args* parameters are accepted for
    backward compatibility but are **unused**.

    sensitivity_tier: 2
    """

    def __init__(
        self,
        whatsapp_phone: str | None,
        mcp_command: str | None = None,
        mcp_args: tuple[str, ...] = (),
        mcp_timeout: float = 10.0,
        prefer_listener_ipc: bool = True,
    ) -> None:
        self._phone = whatsapp_phone
        self._timeout = mcp_timeout

    def is_configured(self) -> bool:
        """Check whether WhatsApp delivery is configured.

        sensitivity_tier: 1
        """
        return bool(self._phone)

    def send(self, message: str, category: str) -> DeliveryResult:
        """Send a WhatsApp notification with opt-out text appended.

        Returns a ``DeliveryResult`` with status ``"not_configured"``
        if the notifier isn't set up, or ``"failed"`` if the listener
        process isn't running.

        Args:
            message: The notification body text.
            category: The notification category (for opt-out text).

        Returns:
            A delivery result describing what happened.

        sensitivity_tier: 2
        """
        now_ts = datetime.now(timezone.utc).isoformat()

        if not self.is_configured():
            return DeliveryResult(
                status="not_configured",
                timestamp=now_ts,
            )

        opt_out = get_opt_out_text(category)
        full_message = f"{message}\n\n---\n{opt_out}"

        return self._send_via_listener(full_message, now_ts)

    def _send_via_listener(
        self,
        full_message: str,
        now_ts: str,
    ) -> DeliveryResult:
        """Send through the running persistent listener process.

        sensitivity_tier: 2
        """
        try:
            from src.extensions.bridges.whatsapp.listener import (
                send_text_via_running_listener,
            )
            from src.extensions.bridges.whatsapp.paths import (
                resolve_self_jid,
                resolve_self_lid,
            )
        except Exception:  # noqa: BLE001
            return DeliveryResult(
                status="failed",
                error="WhatsApp listener module not available",
                timestamp=now_ts,
            )

        # In multi-device Baileys, the phone's self-chat thread uses @lid
        # JIDs (Linked Device IDs), NOT @s.whatsapp.net.  Sending to a
        # phone-number @s.whatsapp.net JID creates a SEPARATE chat thread
        # on the phone.  Use @lid when available, fall back to @s.whatsapp.net.
        self_lid = resolve_self_lid()
        if self_lid:
            to_jid = f"{self_lid}@lid"
        else:
            self_jid = resolve_self_jid()
            to_jid = f"{self_jid}@s.whatsapp.net" if self_jid else str(self._phone)

        response = send_text_via_running_listener(
            to=to_jid,
            message=full_message,
            timeout_seconds=max(8.0, self._timeout * 2.0),
        )
        if response is None:
            return DeliveryResult(
                status="failed",
                error="WhatsApp listener is not running",
                timestamp=now_ts,
            )

        status = str(response.get("status") or "").strip().lower()
        if status == "sent":
            return DeliveryResult(
                status="sent",
                timestamp=now_ts,
                message_id=(
                    str(response.get("message_id"))
                    if response.get("message_id")
                    else None
                ),
            )

        return DeliveryResult(
            status="failed",
            error=str(
                response.get("error") or "Listener send failed",
            ),
            timestamp=now_ts,
        )

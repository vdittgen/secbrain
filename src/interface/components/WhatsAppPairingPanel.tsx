/**
 * WhatsApp pairing panel — polls the listener subprocess for QR / phase
 * updates and renders the appropriate state.
 *
 * Shared between the Extensions page (post-onboarding management) and
 * the onboarding wizard's Notifications slide (initial pairing flow).
 * Both surfaces want the same poll + render behavior, just gated on
 * different "enabled" conditions.
 *
 * sensitivity_tier: 1 (status polling only; QR string is opaque to us)
 */

import { useCallback, useEffect, useRef } from "react";
import { Loader2 } from "lucide-react";
import { QRCodeSVG } from "qrcode.react";
import { dedupInvoke } from "../utils/requestDedup";
import { useAsyncData } from "../hooks/useAsyncData";

export interface WhatsappListenerStatus {
  readonly running: boolean;
  readonly status_file: {
    readonly phase?: string;
    readonly qr?: string | null;
    readonly last_error?: string | null;
  } | null;
}

export function WhatsAppPairingPanel({
  enabled,
  onConnected,
}: {
  readonly enabled: boolean;
  readonly onConnected?: () => void;
}) {
  const fetcher = useCallback(
    () => dedupInvoke<WhatsappListenerStatus>("get_whatsapp_listener_status"),
    [],
  );
  const { data, error, lastUpdatedAt, refetch } = useAsyncData(fetcher, {
    immediate: enabled,
  });

  useEffect(() => {
    if (!enabled) return;
    const timer = setInterval(refetch, 3000);
    return () => clearInterval(timer);
  }, [enabled, refetch]);

  // Fire onConnected exactly once per "enter connected state" transition
  // so the parent doesn't get spammed across re-renders.
  const lastNotifiedPhase = useRef<string | null>(null);
  useEffect(() => {
    const phase = data?.status_file?.phase ?? null;
    if (phase === "connected" && lastNotifiedPhase.current !== "connected") {
      lastNotifiedPhase.current = "connected";
      onConnected?.();
    } else if (phase !== "connected") {
      lastNotifiedPhase.current = phase;
    }
  }, [data, onConnected]);

  // Diagnostic: log every poll result. Lets us see in the Tauri devtools
  // console whether the panel is stuck on stale data or actually polling.
  useEffect(() => {
    if (!enabled) return;
    console.debug("[WhatsAppPairingPanel] poll", {
      phase: data?.status_file?.phase ?? null,
      qrPresent: Boolean(data?.status_file?.qr),
      running: data?.running ?? null,
      error,
      lastUpdatedAt,
    });
  }, [enabled, data, error, lastUpdatedAt]);

  if (!enabled) return null;

  const phase = data?.status_file?.phase ?? null;
  const qr = data?.status_file?.qr ?? null;

  if (phase === "connected") {
    return (
      <div className="flex items-center gap-2 rounded-2 bg-success/10 px-3 py-2 text-xs text-success">
        <span className="text-base">✓</span>
        WhatsApp is paired and listening for messages.
      </div>
    );
  }

  if (phase === "awaiting_pair" && qr) {
    return (
      <div className="flex flex-col items-center gap-3 rounded-2 bg-bg px-4 py-4 ring-1 ring-hairline">
        <div className="text-center">
          <p className="text-xs font-medium text-ink">Scan to pair WhatsApp</p>
          <p className="mt-1 text-[11px] text-muted">
            Open WhatsApp on your phone → Settings → Linked Devices → Link a Device
          </p>
        </div>
        <div className="rounded-md bg-white p-3">
          <QRCodeSVG value={qr} size={208} level="M" includeMargin={false} />
        </div>
        <p className="text-[10px] text-muted">
          QR rotates every ~20 seconds. This panel auto-refreshes.
        </p>
        {error && (
          <p className="text-[10px] text-amber-500">
            Status poll failed: {error}
          </p>
        )}
        {lastUpdatedAt && (
          <p className="text-[10px] text-faint">
            Last checked {new Date(lastUpdatedAt).toLocaleTimeString()}
          </p>
        )}
      </div>
    );
  }

  if (data && !data.running) {
    return (
      <p className="text-[11px] text-muted">
        WhatsApp listener not running. Toggle off and on to retry.
      </p>
    );
  }

  return (
    <div className="flex items-center gap-2 text-[11px] text-muted">
      <Loader2 className="h-3 w-3 animate-spin" />
      Starting WhatsApp connection...
    </div>
  );
}

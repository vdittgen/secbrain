import { useState, useCallback } from "react";
import { Power, ChevronRight } from "lucide-react";
import { invoke } from "@tauri-apps/api/core";

interface KeepAwakeModalProps {
  readonly onDismiss: () => void;
}

// update_settings expects a full AppSettings object — fetch current first,
// then spread the patch. Sending a partial fails Serde deserialization on
// the Rust side and the modal re-opens on next launch.
async function patchSettings(patch: Record<string, unknown>): Promise<void> {
  const current = await invoke<Record<string, unknown>>("get_settings");
  await invoke("update_settings", { settings: { ...current, ...patch } });
}

function KeepAwakeModal({ onDismiss }: KeepAwakeModalProps) {
  const [preventSleep, setPreventSleep] = useState(true);
  const [launchAtLogin, setLaunchAtLogin] = useState(true);
  const [menuBarMode, setMenuBarMode] = useState(true);
  const [saving, setSaving] = useState(false);

  const handleConfirm = useCallback(async () => {
    setSaving(true);
    try {
      await patchSettings({
        prevent_sleep: preventSleep,
        launch_at_login: launchAtLogin,
        menu_bar_mode: menuBarMode,
        keep_awake_modal_seen: true,
      });
    } catch {
      // best-effort
    }
    setSaving(false);
    onDismiss();
  }, [preventSleep, launchAtLogin, menuBarMode, onDismiss]);

  const handleSkip = useCallback(async () => {
    try {
      await patchSettings({ keep_awake_modal_seen: true });
    } catch {
      // best-effort
    }
    onDismiss();
  }, [onDismiss]);

  return (
    <div className="fixed inset-0 z-[1000] flex items-center justify-center"
      style={{ background: "oklch(0.18 0.01 250 / 0.5)", backdropFilter: "blur(8px)" }}>
      <div className="w-full max-w-[480px] rounded-4 border border-hairline bg-surface p-10 shadow-3"
        style={{ margin: "0 20px" }}>
        <div className="mb-5 flex h-14 w-14 items-center justify-center rounded-3 bg-indigo-soft text-indigo-2">
          <Power className="h-8 w-8" strokeWidth={1.6} />
        </div>

        <h2 className="text-[26px] font-semibold" style={{ letterSpacing: "-0.025em" }}>
          Keep me awake
        </h2>
        <p className="mt-2.5 text-[15px] leading-relaxed text-ink-2">
          Arandu runs entirely on your Mac. It needs the app and your Mac
          to stay awake to sync your data, answer questions, and run scheduled
          agents.
        </p>

        <div className="mt-6 flex flex-col gap-3.5 rounded-3 bg-bg-2 p-5">
          <label className="flex cursor-pointer items-center gap-3 text-[14px] font-medium text-ink">
            <input
              type="checkbox"
              checked={preventSleep}
              onChange={(e) => setPreventSleep(e.target.checked)}
              className="h-[18px] w-[18px] accent-[var(--indigo)]"
            />
            Prevent my Mac from sleeping while Arandu is open
          </label>
          <label className="flex cursor-pointer items-center gap-3 text-[14px] font-medium text-ink">
            <input
              type="checkbox"
              checked={launchAtLogin}
              onChange={(e) => setLaunchAtLogin(e.target.checked)}
              className="h-[18px] w-[18px] accent-[var(--indigo)]"
            />
            Launch Arandu when I log in to my Mac
          </label>
          <label className="flex cursor-pointer items-center gap-3 text-[14px] font-medium text-ink">
            <input
              type="checkbox"
              checked={menuBarMode}
              onChange={(e) => setMenuBarMode(e.target.checked)}
              className="h-[18px] w-[18px] accent-[var(--indigo)]"
            />
            Keep running in the menu bar when I close the window
          </label>
        </div>

        <p className="mt-4 text-[13px] text-muted">
          You can change any of this in{" "}
          <b className="font-semibold text-ink">Settings → General → Keep Arandu running</b>.
        </p>

        <div className="mt-6 flex justify-end gap-2">
          <button
            onClick={handleSkip}
            className="rounded-pill px-4 py-2.5 text-[14px] font-medium text-ink-2 transition-colors hover:bg-bg-2"
          >
            Skip
          </button>
          <button
            onClick={handleConfirm}
            disabled={saving}
            className="flex items-center gap-2 rounded-pill bg-indigo px-5 py-2.5 text-[14px] font-medium text-white shadow-2 transition-all hover:bg-indigo-2 hover:-translate-y-px hover:shadow-3 disabled:opacity-50"
          >
            Got it
            <ChevronRight className="h-4 w-4" strokeWidth={1.6} />
          </button>
        </div>
      </div>
    </div>
  );
}

export default KeepAwakeModal;

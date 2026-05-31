/**
 * First-launch setup screen.
 *
 * Renders when the app runs from a packaged `.app` bundle and
 * `~/.secbrain/venv/` is missing or incomplete. The Rust side
 * (`run_first_launch_setup`) drives the actual venv creation and
 * `pip install`; this component listens to `setup-progress` events
 * and shows status.
 *
 * sensitivity_tier: 1
 */

import { useEffect, useRef, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import { listen, type UnlistenFn } from "@tauri-apps/api/event";

interface SetupProgress {
  readonly stage: string;
  readonly message: string;
  readonly done: boolean;
  readonly error: string | null;
}

interface SetupScreenProps {
  readonly onComplete: () => void;
}

const STAGE_LABELS: Record<string, string> = {
  preparing: "Preparing",
  "creating-venv": "Creating Python environment",
  "installing-deps": "Installing dependencies",
  complete: "Done",
  error: "Setup failed",
};

export default function SetupScreen({ onComplete }: SetupScreenProps) {
  const [stage, setStage] = useState<string>("preparing");
  const [lastLine, setLastLine] = useState<string>("Starting setup…");
  const [log, setLog] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);
  const startedRef = useRef(false);

  useEffect(() => {
    let unlisten: UnlistenFn | null = null;

    (async () => {
      unlisten = await listen<SetupProgress>("setup-progress", (event) => {
        const p = event.payload;
        setStage(p.stage);
        setLastLine(p.message);
        setLog((prev) => [...prev.slice(-200), p.message]);
        if (p.error) setError(p.error);
        if (p.done && !p.error) {
          setTimeout(onComplete, 600);
        }
      });

      if (!startedRef.current) {
        startedRef.current = true;
        try {
          await invoke("run_first_launch_setup");
        } catch (e) {
          setError(typeof e === "string" ? e : String(e));
          setStage("error");
        }
      }
    })();

    return () => {
      if (unlisten) unlisten();
    };
  }, [onComplete]);

  const isError = stage === "error" || error !== null;

  return (
    <div className="flex h-screen flex-col items-center justify-center bg-bg px-10">
      <div className="flex w-full max-w-[520px] flex-col">
        <div className="mb-6 flex items-center gap-3">
          <img src="/icon.svg" alt="SecBrain" className="h-10 w-10 rounded-[11px]" />
          <span className="text-[20px] font-semibold tracking-tight text-ink">
            SecBrain
          </span>
        </div>

        <h1 className="text-[28px] font-semibold tracking-tight text-ink">
          Setting things up…
        </h1>
        <p className="mt-2 text-sm text-muted">
          One-time setup, takes about a minute. SecBrain is creating a private
          Python environment under <code className="font-mono text-[12px]">~/.secbrain/venv/</code>{" "}
          so your data and dependencies stay isolated from the rest of your system.
        </p>

        <div className="mt-8 rounded-3 border border-hairline bg-surface p-5 shadow-1">
          <div className="flex items-center gap-3">
            {!isError ? (
              <div className="h-4 w-4 shrink-0 rounded-full border-2 border-indigo border-t-transparent animate-spin" />
            ) : (
              <div className="h-4 w-4 shrink-0 rounded-full bg-amber-500" />
            )}
            <span className="text-sm font-medium text-ink">
              {STAGE_LABELS[stage] ?? stage}
            </span>
          </div>
          <p className="mt-3 truncate font-mono text-[11.5px] text-muted">
            {lastLine}
          </p>
        </div>

        {isError && (
          <div className="mt-4 rounded-3 border border-amber-500/40 bg-amber-500/10 p-4 text-[13px] text-ink">
            <p className="font-medium">Setup failed.</p>
            <p className="mt-1 text-muted">
              {error ?? "An unknown error occurred during setup."}
            </p>
            <details className="mt-3">
              <summary className="cursor-pointer text-[12px] text-muted hover:text-ink">
                Show install log
              </summary>
              <pre className="mt-2 max-h-60 overflow-auto rounded-2 bg-bg-2 p-3 font-mono text-[11px] leading-relaxed text-ink-2">
                {log.join("\n")}
              </pre>
            </details>
          </div>
        )}
      </div>
    </div>
  );
}

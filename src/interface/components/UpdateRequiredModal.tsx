/**
 * Full-screen blocking modal shown when a forced update is required.
 *
 * No close button — this is a forced update. The user cannot dismiss it.
 *
 * sensitivity_tier: 1 (infrastructure only)
 */

import {
  Download,
  Check,
  AlertTriangle,
  Loader2,
  RefreshCw,
  ArrowUpCircle,
} from "lucide-react";
import type { UpdateState } from "../hooks/useUpdateChecker";

interface UpdateRequiredModalProps {
  readonly state: UpdateState;
  readonly onStartDownload: () => void;
  readonly onRestart: () => void;
  readonly onRetry: () => void;
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

// --- Step sub-components ---

function AvailableStep({
  state,
  onStartDownload,
}: {
  readonly state: UpdateState;
  readonly onStartDownload: () => void;
}) {
  return (
    <>
      <div className="flex flex-col items-center gap-4 px-6 pb-6">
        <div className="flex h-14 w-14 items-center justify-center rounded-full bg-indigo-soft">
          <ArrowUpCircle strokeWidth={1.6} className="h-7 w-7 text-indigo" />
        </div>
        <div className="text-center">
          <p className="text-sm font-semibold text-ink">
            Version {state.version} is available
          </p>
          <p className="mt-1 text-xs text-muted">
            A new version of Arandu is required to continue.
          </p>
        </div>

        {state.releaseNotes && (
          <div className="max-h-40 w-full overflow-y-auto rounded-2 bg-bg-2 p-3">
            <p className="mb-1 text-[11px] font-medium text-muted">
              Release Notes
            </p>
            <p className="whitespace-pre-wrap text-xs text-ink">
              {state.releaseNotes}
            </p>
          </div>
        )}
      </div>

      <div className="flex justify-center border-t border-hairline px-6 py-4">
        <button
          onClick={onStartDownload}
          className="flex items-center gap-2 rounded-2 bg-indigo px-6 py-2.5 text-xs font-medium text-white hover:bg-indigo/80"
        >
          <Download strokeWidth={1.6} className="h-4 w-4" />
          Update Now
        </button>
      </div>
    </>
  );
}

function DownloadingStep({ state }: { readonly state: UpdateState }) {
  return (
    <div className="flex flex-col items-center gap-4 px-6 py-8">
      <Loader2 strokeWidth={1.6} className="h-8 w-8 animate-spin text-indigo" />
      <p className="text-sm font-medium text-ink">
        Downloading update...
      </p>

      <div className="w-full space-y-2">
        <div className="h-2 overflow-hidden rounded-full bg-bg-2">
          <div
            className="h-full rounded-full bg-indigo transition-all duration-300"
            style={{ width: `${state.downloadProgress}%` }}
          />
        </div>
        <div className="flex items-center justify-between text-[11px] text-muted">
          <span>
            {formatBytes(state.downloadedBytes)}
            {state.totalBytes > 0 && ` / ${formatBytes(state.totalBytes)}`}
          </span>
          <span>{state.downloadProgress}%</span>
        </div>
      </div>

      <p className="text-[11px] text-muted">
        Please do not close the application.
      </p>
    </div>
  );
}

function ReadyToRestartStep({
  onRestart,
}: {
  readonly onRestart: () => void;
}) {
  return (
    <>
      <div className="flex flex-col items-center gap-4 px-6 pb-6">
        <div className="flex h-14 w-14 items-center justify-center rounded-full bg-success/15">
          <Check strokeWidth={1.6} className="h-7 w-7 text-success" />
        </div>
        <p className="text-sm font-semibold text-ink">
          Update downloaded successfully
        </p>
        <p className="text-xs text-muted">
          Restart the app to apply the update.
        </p>
      </div>

      <div className="flex justify-center border-t border-hairline px-6 py-4">
        <button
          onClick={onRestart}
          className="flex items-center gap-2 rounded-2 bg-indigo px-6 py-2.5 text-xs font-medium text-white hover:bg-indigo/80"
        >
          <RefreshCw strokeWidth={1.6} className="h-4 w-4" />
          Restart Now
        </button>
      </div>
    </>
  );
}

function ErrorStep({
  state,
  onRetry,
}: {
  readonly state: UpdateState;
  readonly onRetry: () => void;
}) {
  return (
    <>
      <div className="flex flex-col items-center gap-4 px-6 pb-6">
        <div className="flex h-14 w-14 items-center justify-center rounded-full bg-amber/15">
          <AlertTriangle strokeWidth={1.6} className="h-7 w-7 text-amber" />
        </div>
        <p className="text-sm font-semibold text-ink">Update failed</p>
        <p className="text-center text-xs text-muted">
          {state.error ?? "An unknown error occurred while downloading."}
        </p>
      </div>

      <div className="flex justify-center border-t border-hairline px-6 py-4">
        <button
          onClick={onRetry}
          className="flex items-center gap-2 rounded-2 bg-indigo px-6 py-2.5 text-xs font-medium text-white hover:bg-indigo/80"
        >
          <RefreshCw strokeWidth={1.6} className="h-4 w-4" />
          Retry
        </button>
      </div>
    </>
  );
}

// --- Main component ---

function UpdateRequiredModal({
  state,
  onStartDownload,
  onRestart,
  onRetry,
}: UpdateRequiredModalProps) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
      <div className="mx-4 w-full max-w-md rounded-5 bg-surface shadow-2xl">
        {/* Header — no close button (forced update) */}
        <div className="flex items-center justify-center border-b border-hairline px-6 py-4">
          <h3 className="text-sm font-semibold text-ink">
            Update Required
          </h3>
        </div>

        {state.step === "available" && (
          <AvailableStep state={state} onStartDownload={onStartDownload} />
        )}
        {state.step === "downloading" && <DownloadingStep state={state} />}
        {state.step === "readyToRestart" && (
          <ReadyToRestartStep onRestart={onRestart} />
        )}
        {state.step === "error" && (
          <ErrorStep state={state} onRetry={onRetry} />
        )}
      </div>
    </div>
  );
}

export default UpdateRequiredModal;

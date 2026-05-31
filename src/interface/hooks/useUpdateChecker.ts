// SPDX-License-Identifier: Apache-2.0
// Auto-update is not wired up in this build. This stub keeps the
// component wiring intact so a downstream build can enable it by
// overriding this module.

import { useState } from "react";

type UpdateStep =
  | "idle"
  | "checking"
  | "available"
  | "downloading"
  | "readyToRestart"
  | "error";

export interface UpdateState {
  readonly step: UpdateStep;
  readonly version: string | null;
  readonly releaseNotes: string | null;
  readonly downloadProgress: number;
  readonly downloadedBytes: number;
  readonly totalBytes: number;
  readonly error: string | null;
}

export interface UseUpdateCheckerResult {
  readonly state: UpdateState;
  readonly updateRequired: boolean;
  readonly startDownload: () => void;
  readonly restart: () => void;
  readonly recheckNow: () => void;
}

const INITIAL_STATE: UpdateState = {
  step: "idle",
  version: null,
  releaseNotes: null,
  downloadProgress: 0,
  downloadedBytes: 0,
  totalBytes: 0,
  error: null,
};

const noop = () => {};

export function useUpdateChecker(): UseUpdateCheckerResult {
  const [state] = useState<UpdateState>(INITIAL_STATE);
  return {
    state,
    updateRequired: false,
    startDownload: noop,
    restart: noop,
    recheckNow: noop,
  };
}

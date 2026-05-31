/**
 * Hook for recording audio via the browser MediaRecorder API.
 *
 * Handles microphone permission, recording lifecycle, and audio blob
 * management. Records as WebM/Opus (native browser format) which is
 * compatible with faster-whisper's ffmpeg decoder.
 *
 * Also runs a lightweight AudioContext + AnalyserNode loop while
 * recording so the UI can show a live level meter and the hook can
 * auto-stop on sustained silence. No new dependencies.
 *
 * sensitivity_tier: 3 (captures voice data)
 */

import { useState, useRef, useCallback, useEffect } from "react";
import { invoke } from "@tauri-apps/api/core";

type RecordingStatus =
  | "idle"
  | "requesting_permission"
  | "recording"
  | "transcribing"
  | "error";

export interface TranscriptionResult {
  readonly text: string;
  readonly language: string;
  readonly duration: number;
}

export interface StartRecordingOptions {
  /** ISO-639-1 hint forwarded to the transcriber. Empty/undefined = auto. */
  readonly languageHint?: string;
  /** Hard upper bound on recording length. Defaults to 120_000 ms. */
  readonly maxDurationMs?: number;
  /** Silence window before auto-stop. Defaults to 1_500 ms. */
  readonly silenceMs?: number;
  /**
   * Called when the hook auto-stops (silence or max duration) and the
   * transcript is ready. Not invoked for manual `stopAndTranscribe`
   * calls — those return the result directly to the caller.
   */
  readonly onResult?: (result: TranscriptionResult) => void;
}

export interface AudioRecordingState {
  readonly status: RecordingStatus;
  readonly error: string | null;
  readonly duration: number;
  /** Smoothed mic input level, 0-1. Always 0 outside `recording`. */
  readonly level: number;
  readonly startRecording: (opts?: StartRecordingOptions) => Promise<void>;
  readonly stopAndTranscribe: () => Promise<TranscriptionResult | null>;
  readonly cancelRecording: () => void;
}

const DEFAULT_MAX_DURATION_MS = 120_000;
const DEFAULT_SILENCE_MS = 1_500;
const MIN_SPEECH_MS = 500;
const VOICE_RMS_THRESHOLD = 0.02;
const ANALYSER_POLL_MS = 50;

/**
 * Record audio and transcribe via local Whisper model.
 *
 * @returns Recording controls and transcription state.
 *
 * @example
 * ```tsx
 * const audio = useAudioRecording();
 *
 * // Start recording with a Spanish hint and auto-stop after 1.5 s silence
 * await audio.startRecording({ languageHint: "es" });
 *
 * // The hook can auto-stop on silence; you can also stop manually:
 * const result = await audio.stopAndTranscribe();
 * if (result) setInput(result.text);
 * ```
 */
export function useAudioRecording(): AudioRecordingState {
  const [status, setStatus] = useState<RecordingStatus>("idle");
  const [error, setError] = useState<string | null>(null);
  const [duration, setDuration] = useState(0);
  const [level, setLevel] = useState(0);

  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const streamRef = useRef<MediaStream | null>(null);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const startTimeRef = useRef<number>(0);
  const mountedRef = useRef(true);

  // VAD / analyser state
  const audioCtxRef = useRef<AudioContext | null>(null);
  const analyserRef = useRef<AnalyserNode | null>(null);
  const sourceRef = useRef<MediaStreamAudioSourceNode | null>(null);
  const analyserTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const lastVoiceAtRef = useRef<number>(0);
  const silenceMsRef = useRef<number>(DEFAULT_SILENCE_MS);
  const maxDurationMsRef = useRef<number>(DEFAULT_MAX_DURATION_MS);
  const languageHintRef = useRef<string | undefined>(undefined);
  const onResultRef = useRef<
    ((result: TranscriptionResult) => void) | undefined
  >(undefined);
  const stopRef = useRef<(() => Promise<TranscriptionResult | null>) | null>(
    null,
  );
  const autoStoppingRef = useRef(false);
  // Synchronous reentrancy guard for stopAndTranscribe: silence auto-stop
  // and a user click on Stop can race; whichever wins, the other must
  // bail before calling recorder.stop() twice.
  const stoppingRef = useRef(false);

  const _cleanup = useCallback(() => {
    if (timerRef.current) {
      clearInterval(timerRef.current);
      timerRef.current = null;
    }
    if (analyserTimerRef.current) {
      clearInterval(analyserTimerRef.current);
      analyserTimerRef.current = null;
    }
    if (sourceRef.current) {
      try {
        sourceRef.current.disconnect();
      } catch {
        // ignore — already disconnected
      }
      sourceRef.current = null;
    }
    analyserRef.current = null;
    if (audioCtxRef.current && audioCtxRef.current.state !== "closed") {
      audioCtxRef.current.close().catch(() => {
        // ignore — best-effort cleanup
      });
    }
    audioCtxRef.current = null;
    if (
      mediaRecorderRef.current &&
      mediaRecorderRef.current.state !== "inactive"
    ) {
      mediaRecorderRef.current.stop();
    }
    mediaRecorderRef.current = null;
    if (streamRef.current) {
      streamRef.current.getTracks().forEach((t) => t.stop());
      streamRef.current = null;
    }
    chunksRef.current = [];
    autoStoppingRef.current = false;
    setLevel(0);
  }, []);

  // Cleanup on unmount
  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      _cleanup();
    };
  }, [_cleanup]);

  const startRecording = useCallback(
    async (opts?: StartRecordingOptions) => {
      setError(null);
      setDuration(0);
      setLevel(0);
      setStatus("requesting_permission");

      silenceMsRef.current = opts?.silenceMs ?? DEFAULT_SILENCE_MS;
      maxDurationMsRef.current = opts?.maxDurationMs ?? DEFAULT_MAX_DURATION_MS;
      languageHintRef.current = opts?.languageHint?.trim() || undefined;
      onResultRef.current = opts?.onResult;
      autoStoppingRef.current = false;
      stoppingRef.current = false;

      try {
        const stream = await navigator.mediaDevices.getUserMedia({
          audio: true,
        });
        if (!mountedRef.current) {
          stream.getTracks().forEach((t) => t.stop());
          return;
        }

        streamRef.current = stream;
        chunksRef.current = [];

        const recorder = new MediaRecorder(stream, {
          mimeType: "audio/webm;codecs=opus",
        });

        recorder.ondataavailable = (e: BlobEvent) => {
          if (e.data.size > 0) {
            chunksRef.current.push(e.data);
          }
        };

        recorder.onerror = () => {
          if (mountedRef.current) {
            setError("Recording failed");
            setStatus("error");
            _cleanup();
          }
        };

        mediaRecorderRef.current = recorder;
        recorder.start(250); // Collect data every 250ms

        startTimeRef.current = Date.now();
        lastVoiceAtRef.current = Date.now();

        // Analyser pipeline for level metering + silence detection.
        // Wrapped in try/catch so a browser that can't open an
        // AudioContext (rare, but e.g. autoplay-locked) still records.
        try {
          // Cast for browsers that only expose webkitAudioContext.
          const Ctx: typeof AudioContext =
            window.AudioContext ??
            (window as unknown as { webkitAudioContext: typeof AudioContext })
              .webkitAudioContext;
          const ctx = new Ctx();
          const source = ctx.createMediaStreamSource(stream);
          const analyser = ctx.createAnalyser();
          analyser.fftSize = 1024;
          analyser.smoothingTimeConstant = 0.6;
          source.connect(analyser);

          audioCtxRef.current = ctx;
          sourceRef.current = source;
          analyserRef.current = analyser;

          const buf = new Uint8Array(analyser.fftSize);

          analyserTimerRef.current = setInterval(() => {
            if (!mountedRef.current || !analyserRef.current) return;
            analyserRef.current.getByteTimeDomainData(buf);
            // Compute RMS around the 128 midpoint, normalise to 0-1.
            let sumSq = 0;
            for (let i = 0; i < buf.length; i++) {
              const v = (buf[i] - 128) / 128;
              sumSq += v * v;
            }
            const rms = Math.sqrt(sumSq / buf.length);
            setLevel(rms);

            const now = Date.now();
            if (rms > VOICE_RMS_THRESHOLD) {
              lastVoiceAtRef.current = now;
            }

            const elapsed = now - startTimeRef.current;
            const silentFor = now - lastVoiceAtRef.current;
            if (
              elapsed >= MIN_SPEECH_MS &&
              silentFor >= silenceMsRef.current &&
              !autoStoppingRef.current
            ) {
              autoStoppingRef.current = true;
              stopRef.current?.()
                .then((result) => {
                  if (result && onResultRef.current) {
                    onResultRef.current(result);
                  }
                })
                .catch(() => {
                  // stopAndTranscribe surfaces its own errors via setError
                });
            }
          }, ANALYSER_POLL_MS);
        } catch {
          // Analyser unavailable — recording still works, just no VAD.
          audioCtxRef.current = null;
          analyserRef.current = null;
          sourceRef.current = null;
        }

        timerRef.current = setInterval(() => {
          if (!mountedRef.current) return;
          const elapsedMs = Date.now() - startTimeRef.current;
          setDuration(Math.floor(elapsedMs / 1000));
          if (
            elapsedMs >= maxDurationMsRef.current &&
            !autoStoppingRef.current
          ) {
            autoStoppingRef.current = true;
            setError("Max recording length reached");
            stopRef.current?.()
              .then((result) => {
                if (result && onResultRef.current) {
                  onResultRef.current(result);
                }
              })
              .catch(() => {
                // already reported via setError
              });
          }
        }, 200);

        setStatus("recording");
      } catch (err) {
        if (mountedRef.current) {
          const msg =
            err instanceof DOMException && err.name === "NotAllowedError"
              ? "Microphone permission denied"
              : err instanceof Error
                ? err.message
                : "Failed to start recording";
          setError(msg);
          setStatus("error");
        }
      }
    },
    [_cleanup],
  );

  const stopAndTranscribe =
    useCallback(async (): Promise<TranscriptionResult | null> => {
      if (
        stoppingRef.current ||
        !mediaRecorderRef.current ||
        status !== "recording"
      ) {
        return null;
      }
      stoppingRef.current = true;

      // Stop recording and collect remaining data
      const blob = await new Promise<Blob>((resolve) => {
        const recorder = mediaRecorderRef.current!;
        recorder.onstop = () => {
          resolve(new Blob(chunksRef.current, { type: "audio/webm" }));
        };
        recorder.stop();
      });

      // Stop mic, timer, and analyser pipeline
      if (timerRef.current) {
        clearInterval(timerRef.current);
        timerRef.current = null;
      }
      if (analyserTimerRef.current) {
        clearInterval(analyserTimerRef.current);
        analyserTimerRef.current = null;
      }
      if (sourceRef.current) {
        try {
          sourceRef.current.disconnect();
        } catch {
          // ignore
        }
        sourceRef.current = null;
      }
      analyserRef.current = null;
      if (audioCtxRef.current && audioCtxRef.current.state !== "closed") {
        audioCtxRef.current.close().catch(() => {
          // ignore — best-effort
        });
      }
      audioCtxRef.current = null;
      if (streamRef.current) {
        streamRef.current.getTracks().forEach((t) => t.stop());
        streamRef.current = null;
      }

      if (!mountedRef.current) return null;
      setLevel(0);
      setStatus("transcribing");

      try {
        // Convert blob to base64
        const buffer = await blob.arrayBuffer();
        const bytes = new Uint8Array(buffer);
        let binary = "";
        for (let i = 0; i < bytes.length; i++) {
          binary += String.fromCharCode(bytes[i]);
        }
        const base64 = btoa(binary);

        // Send to backend for transcription
        const result = await invoke<TranscriptionResult>("transcribe_audio", {
          audioBase64: base64,
          languageHint: languageHintRef.current,
        });

        if (mountedRef.current) {
          setStatus("idle");
          setDuration(0);
        }
        return result;
      } catch (err) {
        if (mountedRef.current) {
          const msg =
            err instanceof Error ? err.message : "Transcription failed";
          setError(msg);
          setStatus("error");
        }
        return null;
      } finally {
        stoppingRef.current = false;
      }
    }, [status]);

  // Keep a ref to the latest stopAndTranscribe so the analyser/duration
  // timers can auto-stop without re-creating themselves every render.
  useEffect(() => {
    stopRef.current = stopAndTranscribe;
  }, [stopAndTranscribe]);

  const cancelRecording = useCallback(() => {
    _cleanup();
    stoppingRef.current = false;
    if (mountedRef.current) {
      setStatus("idle");
      setDuration(0);
      setError(null);
    }
  }, [_cleanup]);

  return {
    status,
    error,
    duration,
    level,
    startRecording,
    stopAndTranscribe,
    cancelRecording,
  };
}

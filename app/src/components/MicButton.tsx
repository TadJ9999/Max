/**
 * Reusable microphone button that uses either the Web Speech API or
 * the Whisper engine endpoint (based on sttProvider prop).
 * Stops any active TTS before starting to record.
 */

import { useCallback, useRef } from "react";
import { ENGINE_URL } from "../engine";
import { useSpeech, type SpeechState } from "../voice/useSpeech";
import "./MicButton.css";

type Props = {
  onTranscript: (text: string) => void;
  onStateChange?: (state: SpeechState | "transcribing") => void;
  sttProvider?: string;       // "web" | "whisper" | "auto"
  stopTTS?: () => void;       // called before recording starts
  disabled?: boolean;
};

export function MicButton({
  onTranscript,
  onStateChange,
  sttProvider = "web",
  stopTTS,
  disabled = false,
}: Props) {
  const mediaRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<Blob[]>([]);

  const useWhisper = sttProvider === "whisper";

  // ── Web Speech API path ──────────────────────────────────────────
  const { state: webState, start: webStart, stop: webStop, isSupported: webSupported } = useSpeech({
    onTranscript,
    onStateChange,
  });

  // ── Whisper path ─────────────────────────────────────────────────
  const startWhisper = useCallback(async () => {
    if (mediaRef.current) return;
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const recorder = new MediaRecorder(stream);
      chunksRef.current = [];
      recorder.ondataavailable = (e) => { if (e.data.size > 0) chunksRef.current.push(e.data); };
      recorder.onstop = async () => {
        stream.getTracks().forEach((t) => t.stop());
        onStateChange?.("transcribing");
        const blob = new Blob(chunksRef.current, { type: "audio/webm" });
        const ab = await blob.arrayBuffer();
        const b64 = btoa(String.fromCharCode(...new Uint8Array(ab)));
        try {
          const res = await fetch(`${ENGINE_URL}/voice/transcribe`, {
            method: "POST",
            headers: { "content-type": "application/json" },
            body: JSON.stringify({ audio_b64: b64, mime: "audio/webm" }),
          });
          if (res.ok) {
            const { text } = (await res.json()) as { text: string };
            if (text.trim()) onTranscript(text.trim());
          }
        } catch {
          // transcription failed — silently discard
        }
        onStateChange?.("idle");
        mediaRef.current = null;
      };
      recorder.start();
      mediaRef.current = recorder;
      onStateChange?.("listening");
    } catch {
      onStateChange?.("idle");
    }
  }, [onTranscript, onStateChange]);

  const stopWhisper = useCallback(() => {
    mediaRef.current?.stop();
  }, []);

  // ── unified click handler ────────────────────────────────────────
  const handleClick = useCallback(() => {
    stopTTS?.();
    if (useWhisper) {
      if (mediaRef.current) stopWhisper();
      else void startWhisper();
    } else {
      if (!webSupported) return;
      if (webState === "idle") webStart();
      else webStop();
    }
  }, [stopTTS, useWhisper, webSupported, webState, webStart, webStop, startWhisper, stopWhisper]);

  const isRecording = useWhisper
    ? mediaRef.current !== null
    : webState !== "idle";

  const isProcessing = !useWhisper && webState === "processing";

  return (
    <button
      className={`mic-btn${isRecording ? " mic-btn--active" : ""}${isProcessing ? " mic-btn--processing" : ""}`}
      onClick={handleClick}
      disabled={disabled || (!webSupported && !useWhisper)}
      title={isRecording ? "Stop recording" : "Start voice input"}
      aria-label={isRecording ? "Stop recording" : "Start voice input"}
    >
      {isProcessing ? (
        <span className="mic-btn__spinner" />
      ) : (
        <svg viewBox="0 0 16 16" fill="currentColor" width="14" height="14">
          <rect x="5" y="1" width="6" height="9" rx="3" />
          <path d="M3 8a5 5 0 0010 0M8 13v2M6 15h4" stroke="currentColor" strokeWidth="1.4" fill="none" strokeLinecap="round"/>
        </svg>
      )}
    </button>
  );
}

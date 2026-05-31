/**
 * Web Speech API hook for speech-to-text.
 * Works in Tauri's WebView2 on Windows (Microsoft STT, degrades offline).
 */

import "./speech.d.ts";
import { useCallback, useEffect, useRef, useState } from "react";

export type SpeechState = "idle" | "listening" | "processing";

type UseSpeechOptions = {
  onTranscript: (text: string) => void;
  onStateChange?: (state: SpeechState) => void;
  lang?: string;
};

export function useSpeech({ onTranscript, onStateChange, lang = "en-US" }: UseSpeechOptions) {
  const [state, setState] = useState<SpeechState>("idle");
  const recRef = useRef<SpeechRecognition | null>(null);
  const activeRef = useRef(false);

  const isSupported =
    typeof window !== "undefined" &&
    (window.SpeechRecognition !== undefined || window.webkitSpeechRecognition !== undefined);

  const setStateAndNotify = useCallback(
    (s: SpeechState) => {
      setState(s);
      onStateChange?.(s);
    },
    [onStateChange],
  );

  const start = useCallback(() => {
    if (!isSupported || activeRef.current) return;
    const SpeechRec = window.SpeechRecognition ?? window.webkitSpeechRecognition;
    if (!SpeechRec) return;

    const rec = new SpeechRec();
    rec.lang = lang;
    rec.interimResults = false;
    rec.maxAlternatives = 1;
    rec.continuous = false;

    rec.onstart = () => {
      activeRef.current = true;
      setStateAndNotify("listening");
    };

    rec.onresult = (e: SpeechRecognitionEvent) => {
      setStateAndNotify("processing");
      const transcript = e.results[0][0].transcript.trim();
      if (transcript) onTranscript(transcript);
    };

    rec.onerror = () => {
      activeRef.current = false;
      setStateAndNotify("idle");
    };

    rec.onend = () => {
      activeRef.current = false;
      setStateAndNotify("idle");
    };

    recRef.current = rec;
    rec.start();
  }, [isSupported, lang, onTranscript, setStateAndNotify]);

  const stop = useCallback(() => {
    recRef.current?.stop();
    activeRef.current = false;
    setStateAndNotify("idle");
  }, [setStateAndNotify]);

  useEffect(() => () => { recRef.current?.abort(); }, []);

  return { state, start, stop, isSupported };
}

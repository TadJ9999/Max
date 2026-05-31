/**
 * Web Speech API text-to-speech hook.
 * Reads the first few sentences of AI responses aloud.
 */

import { useCallback, useRef } from "react";

type TTSOptions = {
  rate?: number;
  pitch?: number;
  voiceName?: string;
};

const SENTENCE_LIMIT = 3;

function firstSentences(text: string, n: number): string {
  // Split on sentence-ending punctuation followed by a space or end
  const parts = text.match(/[^.!?]*[.!?]+(\s|$)/g) ?? [];
  if (parts.length === 0) return text.slice(0, 300);
  return parts.slice(0, n).join("").trim();
}

export function useTTS() {
  const speakingRef = useRef(false);

  const isSupported = typeof window !== "undefined" && "speechSynthesis" in window;

  const speak = useCallback(
    (text: string, options: TTSOptions = {}) => {
      if (!isSupported) return;
      window.speechSynthesis.cancel();
      const excerpt = firstSentences(text, SENTENCE_LIMIT);
      if (!excerpt) return;

      const utt = new SpeechSynthesisUtterance(excerpt);
      utt.rate = options.rate ?? 1.0;
      utt.pitch = options.pitch ?? 1.0;

      if (options.voiceName) {
        const voices = window.speechSynthesis.getVoices();
        const voice = voices.find((v) => v.name === options.voiceName);
        if (voice) utt.voice = voice;
      }

      utt.onstart = () => { speakingRef.current = true; };
      utt.onend = () => { speakingRef.current = false; };
      utt.onerror = () => { speakingRef.current = false; };

      window.speechSynthesis.speak(utt);
    },
    [isSupported],
  );

  const stop = useCallback(() => {
    if (!isSupported) return;
    window.speechSynthesis.cancel();
    speakingRef.current = false;
  }, [isSupported]);

  const isSpeaking = () => speakingRef.current;

  return { speak, stop, isSpeaking, isSupported };
}

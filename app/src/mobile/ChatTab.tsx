import { useState, useRef, useEffect, useCallback } from "react";
import { streamChat, streamCommand, isDslCommand } from "../engine";

type Message = { role: "user" | "assistant"; text: string; streaming?: boolean };

// Web Speech API types (available in modern mobile browsers over HTTPS)
type SpeechRecognitionCtor = new () => {
  lang: string;
  onresult: ((e: { results: { [i: number]: { [i: number]: { transcript: string } } } }) => void) | null;
  onend: (() => void) | null;
  onerror: (() => void) | null;
  start: () => void;
  stop: () => void;
};

function getSR(): SpeechRecognitionCtor | null {
  const w = window as unknown as Record<string, unknown>;
  return (w["SpeechRecognition"] ?? w["webkitSpeechRecognition"] ?? null) as SpeechRecognitionCtor | null;
}

function tts(text: string) {
  if (!("speechSynthesis" in window)) return;
  window.speechSynthesis.cancel();
  const clean = text.replace(/[*_`#>]/g, "").trim();
  const sentences = clean.split(/(?<=[.!?])\s+/).slice(0, 2).join(" ");
  if (!sentences) return;
  const utt = new SpeechSynthesisUtterance(sentences);
  window.speechSynthesis.speak(utt);
}

export function ChatTab() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [listening, setListening] = useState(false);
  const [busy, setBusy] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const send = useCallback(async (text: string) => {
    const t = text.trim();
    if (!t || busy) return;
    setInput("");
    setBusy(true);
    setMessages((m) => [...m, { role: "user", text: t }]);

    const ac = new AbortController();
    abortRef.current = ac;
    let out = "";
    setMessages((m) => [...m, { role: "assistant", text: "", streaming: true }]);

    try {
      const gen = isDslCommand(t) ? streamCommand(t, ac.signal) : streamChat(t, ac.signal);
      for await (const chunk of gen) {
        out += chunk;
        setMessages((m) => {
          const c = [...m];
          c[c.length - 1] = { role: "assistant", text: out, streaming: true };
          return c;
        });
      }
    } catch (e: unknown) {
      if (e instanceof Error && e.name !== "AbortError") {
        out = out || "Engine offline — is Max running?";
      }
    }

    setMessages((m) => {
      const c = [...m];
      c[c.length - 1] = { role: "assistant", text: out, streaming: false };
      return c;
    });

    tts(out);
    setBusy(false);
  }, [busy]);

  const startMic = () => {
    const SR = getSR();
    if (!SR) {
      alert("Speech recognition not available in this browser.");
      return;
    }
    window.speechSynthesis?.cancel();
    const rec = new SR();
    rec.lang = "en-US";
    rec.onresult = (e) => {
      const text = e.results[0]?.[0]?.transcript ?? "";
      if (text) void send(text);
    };
    rec.onend = () => setListening(false);
    rec.onerror = () => setListening(false);
    setListening(true);
    rec.start();
  };

  return (
    <div className="mob-chat">
      <div className="mob-chat__history">
        {messages.length === 0 && (
          <p className="mob-empty">Say hi or ask Max anything…</p>
        )}
        {messages.map((m, i) => (
          <div key={i} className={`mob-bubble mob-bubble--${m.role}`}>
            {m.text
              ? m.text
              : m.streaming
                ? <span className="mob-caret">▊</span>
                : null}
          </div>
        ))}
        <div ref={bottomRef} />
      </div>

      <div className="mob-chat__bar">
        <button
          className={`mob-mic${listening ? " is-hot" : ""}`}
          onClick={startMic}
          aria-label="Voice input"
          disabled={busy}
        >
          🎙
        </button>
        <input
          className="mob-chat__input"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && !e.shiftKey && void send(input)}
          placeholder="Message Max…"
          disabled={busy}
        />
        <button
          className="mob-send"
          onClick={() => void send(input)}
          disabled={busy || !input.trim()}
          aria-label="Send"
        >
          ↑
        </button>
      </div>
    </div>
  );
}

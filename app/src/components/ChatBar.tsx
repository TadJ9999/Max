// Chat input pinned to the bottom of the widget. Sends the raw DSL text to the
// engine's /command endpoint and streams the reply. A ☁ indicator appears when
// the line starts with the cloud sigil `!`. A status dot polls /health.

import { useEffect, useRef, useState } from "react";
import {
  clearRagMemory,
  getHealth,
  getRagStatus,
  indexWorkspace,
  isDslCommand,
  streamAsk,
  streamChat,
  streamCommand,
  type RagStatus,
} from "../engine";
import { MarkdownView } from "./MarkdownView";
import { CopyButton } from "./CopyButton";
import { PoodleSprite } from "./PoodleSprite";

export function ChatBar({
  onRequest,
  onBusyChange,
}: {
  onRequest?: () => void;
  onBusyChange?: (busy: boolean) => void;
}) {
  const [online, setOnline] = useState<boolean | null>(null);
  const [text, setText] = useState("");
  const [output, setOutput] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const [inputFocused, setInputFocused] = useState(false);
  // "Knows your code" mode: plain questions are answered from the indexed workspace.
  const [codeMode, setCodeMode] = useState(false);
  const [rag, setRag] = useState<RagStatus | null>(null);
  const [indexing, setIndexing] = useState(false);
  // Stable per-app-session id so grounded chat carries memory across turns.
  const sessionId = useRef<string>(
    (globalThis.crypto?.randomUUID?.() ?? `s-${Date.now()}-${Math.random()}`),
  ).current;

  // Pull the index status when code mode turns on, so the counts are current.
  useEffect(() => {
    if (codeMode) void getRagStatus().then(setRag);
  }, [codeMode]);

  const reindex = async () => {
    if (indexing) return;
    setIndexing(true);
    setErr(null);
    try {
      const res = await indexWorkspace();
      if (res) setRag({ files: res.files, chunks: res.chunks });
      else setErr("indexing failed — is a workspace folder allow-listed in settings?");
    } finally {
      setIndexing(false);
    }
  };

  useEffect(() => {
    let alive = true;
    const ping = async () => {
      const h = await getHealth();
      if (alive) setOnline(h !== null);
    };
    ping();
    const t = window.setInterval(ping, 5000);
    return () => {
      alive = false;
      window.clearInterval(t);
    };
  }, []);

  const isCloud = text.trimStart().startsWith("!");

  const send = async () => {
    const q = text.trim();
    if (!q || busy) return;
    setBusy(true);
    onBusyChange?.(true); // mascot: enter "thinking" until the reply finishes
    setErr(null);
    setOutput("");
    onRequest?.(); // fire a request comet on the mascot
    const ac = new AbortController();
    abortRef.current = ac;
    // DSL command (`. … .`, `!. … .`, `~ … ~`) → /command. Plain text → /chat,
    // or /rag/ask (grounded in the indexed workspace, with memory) in code mode.
    const iterator = isDslCommand(q)
      ? streamCommand(q, ac.signal)
      : codeMode
        ? streamAsk(q, sessionId, ac.signal)
        : streamChat(q, ac.signal);
    try {
      for await (const delta of iterator) {
        setOutput((o) => o + delta);
      }
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
      onBusyChange?.(false); // mascot: response complete → ripple blast
      abortRef.current = null;
    }
  };

  const newConversation = () => {
    void clearRagMemory(sessionId);
    setOutput("");
    setErr(null);
  };

  const onKey = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      void send();
    }
  };

  return (
    <div className="chat">
      {(output || err || busy) && (
        <div className="chat__out">
          {output && !err && <CopyButton text={output} className="chat__copy" />}
          {err ? (
            <span className="chat__err">⚠ {err}</span>
          ) : output ? (
            <MarkdownView source={output} />
          ) : (
            <span className="chat__hint">…</span>
          )}
        </div>
      )}
      <div className="chat__row">
        <span
          className={`dot ${online == null ? "dot--unknown" : online ? "dot--on" : "dot--off"}`}
          title={online == null ? "checking engine…" : online ? "engine online" : "engine offline"}
        />
        <div className="chat__input-wrap">
          {!text && !inputFocused && <PoodleSprite />}
          <input
            className="chat__input"
            placeholder=""
            value={text}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={onKey}
            onFocus={() => setInputFocused(true)}
            onBlur={() => setInputFocused(false)}
          />
        </div>
        {isCloud && (
          <span className="chat__cloud" title="cloud ( ! ) — this leaves your machine">
            ☁
          </span>
        )}
        <button
          className={`chat__mode ${codeMode ? "is-on" : ""}`}
          onClick={() => setCodeMode((v) => !v)}
          title={
            codeMode
              ? `Knows-your-code: ON — plain questions answered from your indexed workspace${
                  rag ? ` (${rag.files} files / ${rag.chunks} chunks)` : ""
                }`
              : "Knows-your-code: OFF — click to ground answers in your codebase"
          }
        >
          🧠
        </button>
        {codeMode && (
          <button
            className="chat__index"
            onClick={() => void reindex()}
            disabled={indexing}
            title={
              rag
                ? `Re-index workspace · ${rag.files} files / ${rag.chunks} chunks`
                : "Index the allow-listed workspace"
            }
          >
            {indexing ? "…" : "⟳"}
          </button>
        )}
        {codeMode && (
          <button
            className="chat__index"
            onClick={newConversation}
            title="New conversation — clear grounded-chat memory"
          >
            ✕
          </button>
        )}
        <button className="chat__send" onClick={() => void send()} disabled={busy} title="Send">
          {busy ? "…" : "▶"}
        </button>
      </div>
    </div>
  );
}

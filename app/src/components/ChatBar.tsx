// Chat input pinned to the bottom of the widget. Sends the raw DSL text to the
// engine's /command endpoint and streams the reply. A ☁ indicator appears when
// the line starts with the cloud sigil `!`. A status dot polls /health.

import { useEffect, useRef, useState } from "react";
import { getHealth, isDslCommand, streamChat, streamCommand } from "../engine";
import { MarkdownView } from "./MarkdownView";

export function ChatBar() {
  const [online, setOnline] = useState<boolean | null>(null);
  const [text, setText] = useState("");
  const [output, setOutput] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);

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
    setErr(null);
    setOutput("");
    const ac = new AbortController();
    abortRef.current = ac;
    // DSL command (`. … .`, `!. … .`, `~ … ~`) → /command; plain text → /chat.
    const stream = isDslCommand(q) ? streamCommand : streamChat;
    try {
      for await (const delta of stream(q, ac.signal)) {
        setOutput((o) => o + delta);
      }
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
      abortRef.current = null;
    }
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
        <input
          className="chat__input"
          placeholder="Ask Max…  ( ! = cloud )"
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={onKey}
        />
        {isCloud && (
          <span className="chat__cloud" title="cloud ( ! ) — this leaves your machine">
            ☁
          </span>
        )}
        <button className="chat__send" onClick={() => void send()} disabled={busy} title="Send">
          {busy ? "…" : "▶"}
        </button>
      </div>
    </div>
  );
}

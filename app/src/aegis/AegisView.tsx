import { useCallback, useEffect, useRef, useState } from "react";
import {
  type AegisEvent,
  type AegisSeverity,
  applyFix,
  getAegisEvents,
  streamDiagnosis,
} from "./aegis";
import "./Aegis.css";

// ---- helpers -------------------------------------------------------

function timeAgo(isoStr: string): string {
  const diff = (Date.now() - new Date(isoStr).getTime()) / 1000;
  if (diff < 60) return `${Math.round(diff)}s ago`;
  if (diff < 3600) return `${Math.round(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.round(diff / 3600)}h ago`;
  return `${Math.round(diff / 86400)}d ago`;
}

function SevChip({ sev }: { sev: AegisSeverity }) {
  return (
    <span className={`aegis__sev-chip aegis__sev-chip--${sev.toLowerCase()}`}>
      {sev}
    </span>
  );
}

function SevDot({ sev }: { sev: AegisSeverity }) {
  return <span className={`aegis__sev-dot aegis__sev-dot--${sev.toLowerCase()}`} />;
}

const SOURCE_ICONS: Record<string, string> = {
  engine: "⚙", delegate: "⊞", provider: "☁", frontend: "◐", rust: "⊕",
};

function DiffBlock({ text }: { text: string }) {
  const lines = text.split("\n");
  return (
    <pre className="aegis__diff">
      {lines.map((line, i) => {
        let cls = "aegis__diff-line--ctx";
        if (line.startsWith("+++") || line.startsWith("---")) cls = "aegis__diff-line--hunk";
        else if (line.startsWith("@@")) cls = "aegis__diff-line--hunk";
        else if (line.startsWith("+")) cls = "aegis__diff-line--add";
        else if (line.startsWith("-")) cls = "aegis__diff-line--del";
        return <span key={i} className={`aegis__diff-line ${cls}`}>{line}{"\n"}</span>;
      })}
    </pre>
  );
}

// Parse the accumulated diagnosis text into rendered blocks
function DiagnosisBody({
  text,
  streaming,
}: {
  text: string;
  streaming: boolean;
}) {
  // Extract diff fences to render them specially
  const parts: { type: "text" | "diff"; content: string }[] = [];
  const diffRe = /```diff\n([\s\S]*?)```/g;
  let last = 0;
  let m: RegExpExecArray | null;
  while ((m = diffRe.exec(text)) !== null) {
    if (m.index > last) parts.push({ type: "text", content: text.slice(last, m.index) });
    parts.push({ type: "diff", content: m[1] });
    last = m.index + m[0].length;
  }
  if (last < text.length) parts.push({ type: "text", content: text.slice(last) });

  return (
    <>
      {parts.map((p, i) =>
        p.type === "diff" ? (
          <DiffBlock key={i} text={p.content} />
        ) : (
          <span key={i} className="aegis__diag-text">{p.content}</span>
        ),
      )}
      {streaming && <span className="aegis__cursor" />}
    </>
  );
}

// ---- main component ------------------------------------------------

type DiagState = "idle" | "streaming" | "done" | "error";
type ApplyState = "idle" | "applying" | "ok" | "error";

export function AegisView() {
  const [events, setEvents] = useState<AegisEvent[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [diagText, setDiagText] = useState("");
  const [diagState, setDiagState] = useState<DiagState>("idle");
  const [applyState, setApplyState] = useState<ApplyState>("idle");
  const [applyMsg, setApplyMsg] = useState("");
  const [autonomy, setAutonomy] = useState<"suggest" | "ask">("ask");
  const [lastLogId, setLastLogId] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const diagAreaRef = useRef<HTMLDivElement | null>(null);

  const selected = events.find((e) => e.id === selectedId) ?? null;

  const load = useCallback(async () => {
    const evts = await getAegisEvents(50);
    setEvents(evts);
  }, []);

  useEffect(() => {
    void load();
    const t = setInterval(load, 8000);
    return () => clearInterval(t);
  }, [load]);

  // Auto-scroll diagnosis area
  useEffect(() => {
    if (diagAreaRef.current) {
      diagAreaRef.current.scrollTop = diagAreaRef.current.scrollHeight;
    }
  }, [diagText]);

  const selectEvent = useCallback((id: string) => {
    setSelectedId(id);
    setDiagText("");
    setDiagState("idle");
    setApplyState("idle");
    setApplyMsg("");
    setLastLogId(null);
  }, []);

  const diagnose = useCallback(async () => {
    if (!selectedId || diagState === "streaming") return;
    abortRef.current?.abort();
    const ctrl = new AbortController();
    abortRef.current = ctrl;
    setDiagText("");
    setDiagState("streaming");
    setApplyState("idle");
    setApplyMsg("");
    try {
      let accumulated = "";
      for await (const chunk of streamDiagnosis(selectedId, ctrl.signal)) {
        accumulated += chunk;
        setDiagText(accumulated);
      }
      setDiagState("done");
    } catch (e: unknown) {
      if ((e as Error)?.name !== "AbortError") {
        setDiagText((t) => t + `\n\n[error: ${String(e)}]`);
        setDiagState("error");
      }
    }
  }, [selectedId, diagState]);

  const extractDiff = (text: string): string | null => {
    const m = /```diff\n([\s\S]*?)```/.exec(text);
    return m ? m[1] : null;
  };

  const approve = useCallback(async () => {
    if (!selectedId || applyState === "applying") return;
    const diff = extractDiff(diagText);
    if (!diff) {
      setApplyMsg("No diff found in the diagnosis. Apply manually.");
      setApplyState("error");
      return;
    }
    setApplyState("applying");
    setApplyMsg("Applying patch…");
    const result = await applyFix(selectedId, diff, lastLogId ?? undefined);
    if (result.ok) {
      setApplyState("ok");
      setApplyMsg(`Verified ✓  ${result.verification ?? ""}`);
    } else {
      setApplyState("error");
      setApplyMsg(result.error ?? "Apply failed");
    }
  }, [selectedId, diagText, applyState, lastLogId]);

  const reject = useCallback(() => {
    abortRef.current?.abort();
    setDiagText("");
    setDiagState("idle");
    setApplyState("idle");
    setApplyMsg("");
  }, []);

  // Severity counts for summary strip
  const counts = { Critical: 0, High: 0, Medium: 0, Low: 0 };
  for (const e of events) counts[e.severity] = (counts[e.severity] ?? 0) + 1;

  return (
    <div className="aegis">
      {/* ---- header ---- */}
      <div className="aegis__header">
        <span className="aegis__title">🛡 Aegis</span>
        <span className="aegis__badge">Self-Repair Console</span>
        <div className="aegis__spacer" />
        <div className="aegis__autonomy">
          {(["suggest", "ask"] as const).map((a) => (
            <button
              key={a}
              className={`aegis__autonomy-btn${autonomy === a ? " is-active" : ""}`}
              onClick={() => setAutonomy(a)}
            >
              {a}
            </button>
          ))}
        </div>
        <button className="aegis__refresh-btn" onClick={load}>
          ↻ Refresh
        </button>
      </div>

      {/* ---- summary strip ---- */}
      {events.length > 0 && (
        <div className="aegis__summary">
          {(["Critical", "High", "Medium", "Low"] as AegisSeverity[])
            .filter((s) => counts[s] > 0)
            .map((s) => (
              <span key={s} className="aegis__sev-count">
                <SevDot sev={s} />
                {s} {counts[s]}
              </span>
            ))}
        </div>
      )}

      {/* ---- body ---- */}
      <div className="aegis__body">
        {/* LEFT: event list */}
        <div className="aegis__list">
          {events.length === 0 ? (
            <div className="aegis__empty-list">
              <div className="aegis__empty-glyph">🛡</div>
              <div>No issues detected</div>
            </div>
          ) : (
            events.map((ev) => (
              <div
                key={ev.id}
                className={`aegis__event-card${selectedId === ev.id ? " is-selected" : ""}`}
                onClick={() => selectEvent(ev.id)}
              >
                <div className="aegis__event-top">
                  <SevChip sev={ev.severity} />
                  <span className="aegis__source-badge">
                    {SOURCE_ICONS[ev.source] ?? "◦"} {ev.source}
                  </span>
                  {ev.count > 1 && (
                    <span className="aegis__count-badge">×{ev.count}</span>
                  )}
                </div>
                <div className="aegis__event-kind">{ev.kind}</div>
                <div className="aegis__event-msg">{ev.message}</div>
                <div className="aegis__event-time">{timeAgo(ev.last_ts)}</div>
              </div>
            ))
          )}
        </div>

        {/* RIGHT: detail panel */}
        <div className="aegis__detail">
          {!selected ? (
            <div className="aegis__empty-detail">
              <div className="aegis__empty-shield">🛡</div>
              <div>Select an event to diagnose</div>
            </div>
          ) : (
            <>
              <div className="aegis__detail-header">
                <div className="aegis__detail-title">{selected.kind}</div>
                <div className="aegis__detail-meta">
                  <span>
                    <SevDot sev={selected.severity} /> {selected.severity}
                  </span>
                  <span>{SOURCE_ICONS[selected.source]} {selected.source}</span>
                  {selected.count > 1 && <span>×{selected.count} occurrences</span>}
                  <span>{timeAgo(selected.last_ts)}</span>
                </div>
                <div
                  style={{
                    marginTop: 6,
                    fontSize: 12,
                    color: "#8aaccc",
                    wordBreak: "break-all",
                  }}
                >
                  {selected.message}
                </div>

                {selected.traceback && (
                  <details style={{ marginTop: 8 }}>
                    <summary className="aegis__traceback" style={{ cursor: "pointer", padding: "4px 8px" }}>
                      ▶ Traceback
                    </summary>
                    <pre className="aegis__traceback">{selected.traceback}</pre>
                  </details>
                )}
              </div>

              {/* diagnosis stream area */}
              <div className="aegis__diag-area" ref={diagAreaRef}>
                {diagText ? (
                  <DiagnosisBody text={diagText} streaming={diagState === "streaming"} />
                ) : (
                  diagState === "idle" && (
                    <div style={{ color: "#3a5068", fontSize: 12 }}>
                      Click <strong style={{ color: "#ff8c42" }}>Diagnose</strong> to ask AI for the root cause and a fix.
                    </div>
                  )
                )}
              </div>

              {/* action bar */}
              <div className="aegis__actions">
                {diagState !== "streaming" && (
                  <button
                    className="aegis__btn aegis__btn--diagnose"
                    onClick={diagnose}
                  >
                    ⚡ Diagnose
                  </button>
                )}

                {diagState === "streaming" && (
                  <button className="aegis__btn aegis__btn--reject" onClick={reject}>
                    ✕ Stop
                  </button>
                )}

                {diagState === "done" && autonomy === "ask" && extractDiff(diagText) && (
                  <>
                    <button
                      className="aegis__btn aegis__btn--approve"
                      onClick={approve}
                      disabled={applyState === "applying"}
                    >
                      {applyState === "applying" ? (
                        <><span className="aegis__spinner" /> Applying…</>
                      ) : (
                        "✓ Approve & Apply"
                      )}
                    </button>
                    <button className="aegis__btn aegis__btn--reject" onClick={reject}>
                      ✕ Reject
                    </button>
                  </>
                )}

                {diagState === "done" && (
                  <button className="aegis__btn aegis__btn--diagnose" onClick={diagnose}>
                    ↻ Re-diagnose
                  </button>
                )}

                {applyMsg && (
                  <span
                    className={`aegis__toast aegis__toast--${applyState === "ok" ? "ok" : "err"}`}
                  >
                    {applyMsg}
                  </span>
                )}

                <div style={{ flex: 1 }} />

                <button
                  className="aegis__btn aegis__btn--dismiss"
                  onClick={() => { setSelectedId(null); reject(); }}
                >
                  Dismiss
                </button>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}

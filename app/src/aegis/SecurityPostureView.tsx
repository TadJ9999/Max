import { useCallback, useEffect, useRef, useState } from "react";
import {
  type AegisSeverity,
  type Posture,
  type ScanStatus,
  type SecurityFinding,
  type SecurityFindingCategory,
  applyFix,
  getFindings,
  getPosture,
  getReport,
  getScanStatus,
  runScan,
  setFindingStatus,
  streamFindingFix,
} from "./aegis";
import { CopyButton } from "../components/CopyButton";

// ─── helpers ──────────────────────────────────────────────────────────────────

function scoreColor(score: number): string {
  if (score >= 70) return "#4ade80";
  if (score >= 40) return "#f5c842";
  return "#ff6b6b";
}

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

// ─── Score gauge (circular ring) ─────────────────────────────────────────────

function ScoreGauge({ score }: { score: number }) {
  const r = 38;
  const cx = 50;
  const cy = 50;
  const circumference = 2 * Math.PI * r;
  const filled = (score / 100) * circumference;
  const color = scoreColor(score);

  return (
    <svg className="posture__gauge-svg" viewBox="0 0 100 100" aria-label={`Score: ${score}`}>
      {/* track */}
      <circle cx={cx} cy={cy} r={r} fill="none" stroke="rgba(255,255,255,0.06)" strokeWidth="9" />
      {/* filled arc */}
      <circle
        cx={cx} cy={cy} r={r} fill="none"
        stroke={color} strokeWidth="9"
        strokeDasharray={`${filled} ${circumference}`}
        strokeLinecap="round"
        transform={`rotate(-90 ${cx} ${cy})`}
        style={{ filter: `drop-shadow(0 0 5px ${color}60)`, transition: "stroke-dasharray 0.6s ease" }}
      />
      {/* score number */}
      <text
        x={cx} y={cy - 4}
        textAnchor="middle" dominantBaseline="central"
        fill={color} fontSize="22" fontWeight="700"
        fontFamily="JetBrains Mono, Cascadia Code, ui-monospace, monospace"
      >
        {score}
      </text>
      <text
        x={cx} y={cy + 14}
        textAnchor="middle"
        fill="rgba(255,255,255,0.3)" fontSize="8"
        fontFamily="JetBrains Mono, Cascadia Code, ui-monospace, monospace"
      >
        / 100
      </text>
    </svg>
  );
}

// ─── History strip ────────────────────────────────────────────────────────────

function HistoryStrip({ history }: { history: { ts: string; score: number }[] }) {
  if (history.length === 0) return null;
  return (
    <div className="posture__history" title="Score trend (oldest → newest)">
      {history.map((h, i) => (
        <div
          key={i}
          className="posture__history-bar"
          title={`${h.ts.slice(0, 16).replace("T", " ")}: ${h.score}`}
        >
          <div
            className="posture__history-fill"
            style={{
              height: `${Math.max(6, h.score)}%`,
              background: scoreColor(h.score),
              boxShadow: `0 0 4px ${scoreColor(h.score)}60`,
            }}
          />
        </div>
      ))}
    </div>
  );
}

// ─── Diff block (reused from AegisView pattern) ───────────────────────────────

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

function DiagnosisBody({ text, streaming }: { text: string; streaming: boolean }) {
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

// ─── Finding card ─────────────────────────────────────────────────────────────

function FindingCard({
  f,
  selected,
  onSelect,
}: {
  f: SecurityFinding;
  selected: boolean;
  onSelect: () => void;
}) {
  const isSca = f.category === "sca";
  return (
    <div
      className={`aegis__event-card posture__finding-card${selected ? " is-selected" : ""}`}
      onClick={onSelect}
    >
      <div className="aegis__event-top">
        <SevChip sev={f.severity} />
        <span className="posture__cat-badge">{isSca ? "CVE" : f.rule_id ?? "SAST"}</span>
        {f.status !== "open" && (
          <span className={`posture__status-badge posture__status-badge--${f.status}`}>
            {f.status}
          </span>
        )}
        {f.ai_confidence !== null && (
          <span
            className="posture__confidence"
            title={`AI confidence: ${Math.round((f.ai_confidence ?? 0) * 100)}%`}
          >
            AI {Math.round((f.ai_confidence ?? 0) * 100)}%
          </span>
        )}
      </div>
      <div className="aegis__event-kind">{f.title}</div>
      {isSca ? (
        <div className="aegis__event-msg">
          {f.package}@{f.installed_version}
          {f.cve_id ? ` · ${f.cve_id}` : ""}
          {f.fixed_version ? ` → fix: ${f.fixed_version}` : ""}
        </div>
      ) : (
        <div className="aegis__event-msg">
          {f.file
            ? `${f.file.split(/[\\/]/).pop()}:${f.line}`
            : f.message?.slice(0, 60)}
        </div>
      )}
    </div>
  );
}

// ─── Main component ───────────────────────────────────────────────────────────

type FixState = "idle" | "streaming" | "done" | "error";
type ApplyState = "idle" | "applying" | "ok" | "error";

export function SecurityPostureView() {
  const [posture, setPosture] = useState<Posture | null>(null);
  const [findings, setFindings] = useState<SecurityFinding[]>([]);
  const [scanStatus, setScanStatus] = useState<ScanStatus>({
    running: false,
    scan_id: null,
    files_scanned: 0,
    stage: "",
  });
  const [catFilter, setCatFilter] = useState<SecurityFindingCategory | "all">("all");
  const [selectedId, setSelectedId] = useState<string | null>(null);

  // Fix stream state
  const [fixText, setFixText] = useState("");
  const [fixState, setFixState] = useState<FixState>("idle");
  const [applyState, setApplyState] = useState<ApplyState>("idle");
  const [applyMsg, setApplyMsg] = useState("");
  const [lastLogId, setLastLogId] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const fixAreaRef = useRef<HTMLDivElement | null>(null);

  const selected = findings.find((f) => f.id === selectedId) ?? null;

  // Auto-scroll fix area
  useEffect(() => {
    if (fixAreaRef.current) {
      fixAreaRef.current.scrollTop = fixAreaRef.current.scrollHeight;
    }
  }, [fixText]);

  // Load posture + findings
  const load = useCallback(async () => {
    const [p, f] = await Promise.all([
      getPosture(),
      getFindings(
        catFilter === "all" ? undefined : catFilter,
        "open",
      ),
    ]);
    if (p) setPosture(p);
    setFindings(f);
  }, [catFilter]);

  // Poll scan status while running
  useEffect(() => {
    let interval: ReturnType<typeof setInterval> | null = null;
    const poll = async () => {
      const s = await getScanStatus();
      setScanStatus(s);
      if (!s.running && interval !== null) {
        clearInterval(interval);
        interval = null;
        void load(); // refresh findings when scan finishes
      }
    };
    if (scanStatus.running) {
      interval = setInterval(poll, 2000);
    }
    return () => {
      if (interval !== null) clearInterval(interval);
    };
  }, [scanStatus.running, load]);

  useEffect(() => {
    void load();
    const t = setInterval(load, 15000);
    return () => clearInterval(t);
  }, [load]);

  const selectFinding = useCallback((id: string) => {
    setSelectedId(id);
    setFixText("");
    setFixState("idle");
    setApplyState("idle");
    setApplyMsg("");
    setLastLogId(null);
  }, []);

  const startScan = useCallback(async () => {
    await runScan();
    setScanStatus((s) => ({ ...s, running: true }));
  }, []);

  const askLeoToFix = useCallback(async () => {
    if (!selectedId || fixState === "streaming") return;
    abortRef.current?.abort();
    const ctrl = new AbortController();
    abortRef.current = ctrl;
    setFixText("");
    setFixState("streaming");
    setApplyState("idle");
    setApplyMsg("");
    try {
      let acc = "";
      for await (const chunk of streamFindingFix(selectedId, ctrl.signal)) {
        acc += chunk;
        setFixText(acc);
      }
      setFixState("done");
    } catch (e: unknown) {
      if ((e as Error)?.name !== "AbortError") {
        setFixText((t) => t + `\n\n[error: ${String(e)}]`);
        setFixState("error");
      }
    }
  }, [selectedId, fixState]);

  const extractDiff = (text: string): string | null => {
    const m = /```diff\n([\s\S]*?)```/.exec(text);
    return m ? m[1] : null;
  };

  const approve = useCallback(async () => {
    if (!selectedId || applyState === "applying") return;
    const diff = extractDiff(fixText);
    if (!diff) {
      setApplyMsg("No diff found in the fix. Apply manually.");
      setApplyState("error");
      return;
    }
    setApplyState("applying");
    setApplyMsg("Applying patch…");
    const result = await applyFix(selectedId, diff, lastLogId ?? undefined);
    if (result.ok) {
      await setFindingStatus(selectedId, "fixed");
      setApplyState("ok");
      setApplyMsg(`Verified ✓  ${result.verification ?? ""}`);
      // Refresh findings
      void load();
    } else {
      setApplyState("error");
      setApplyMsg(result.error ?? "Apply failed");
    }
  }, [selectedId, fixText, applyState, lastLogId, load]);

  const ignore = useCallback(async () => {
    if (!selectedId) return;
    await setFindingStatus(selectedId, "ignored");
    setSelectedId(null);
    void load();
  }, [selectedId, load]);

  const reopen = useCallback(async () => {
    if (!selectedId) return;
    await setFindingStatus(selectedId, "open");
    void load();
  }, [selectedId, load]);

  const exportReport = useCallback(async () => {
    const md = await getReport();
    if (!md) return;
    const blob = new Blob([md], { type: "text/markdown" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "security-posture.md";
    a.click();
    URL.revokeObjectURL(url);
  }, []);

  const filteredFindings =
    catFilter === "all" ? findings : findings.filter((f) => f.category === catFilter);

  const score = posture?.score ?? 100;

  return (
    <div className="posture">
      {/* ── At-risk banner ── */}
      {posture?.at_risk && (
        <div className="posture__at-risk-banner">
          ⚠ Security posture is at risk — score below threshold
        </div>
      )}

      {/* ── Header row ── */}
      <div className="posture__header">
        {/* Gauge */}
        <div className="posture__gauge-wrap">
          <ScoreGauge score={score} />
        </div>

        {/* Counts + history */}
        <div className="posture__header-info">
          <div className="posture__sev-counts">
            {(["Critical", "High", "Medium", "Low"] as AegisSeverity[]).map((s) => {
              const n = posture?.[s.toLowerCase() as keyof Posture] as number ?? 0;
              if (n === 0) return null;
              return (
                <span key={s} className="aegis__sev-count">
                  <SevDot sev={s} /> {s} {n}
                </span>
              );
            })}
          </div>
          {posture?.last_scan_ts && (
            <div className="posture__last-scan">Last scan: {timeAgo(posture.last_scan_ts)}</div>
          )}
          {posture?.history && <HistoryStrip history={posture.history} />}
        </div>

        {/* Actions */}
        <div className="posture__header-actions">
          <button
            className="aegis__btn aegis__btn--diagnose"
            onClick={startScan}
            disabled={scanStatus.running}
          >
            {scanStatus.running ? (
              <>
                <span className="aegis__spinner" />
                Scanning…
              </>
            ) : (
              "⟳ Run scan now"
            )}
          </button>
          <button className="aegis__btn aegis__btn--dismiss" onClick={exportReport}>
            ⬇ Export report
          </button>
        </div>
      </div>

      {/* ── Scan progress bar ── */}
      {scanStatus.running && (
        <div className="posture__scan-progress">
          <div className="posture__scan-progress-track">
            <div className="posture__scan-progress-bar" />
          </div>
          <div className="posture__scan-progress-label">
            <span className="aegis__spinner" />
            <span>{scanStatus.stage || "Scanning"}</span>
            {scanStatus.files_scanned > 0 && (
              <span className="posture__scan-file-count">{scanStatus.files_scanned} files</span>
            )}
          </div>
        </div>
      )}

      {/* ── Category filter ── */}
      <div className="posture__filter-bar">
        {(["all", "sast", "sca"] as const).map((cat) => (
          <button
            key={cat}
            className={`aegis__autonomy-btn${catFilter === cat ? " is-active" : ""}`}
            onClick={() => { setCatFilter(cat); setSelectedId(null); }}
          >
            {cat === "all" ? "All" : cat === "sast" ? "Code (SAST)" : "Dependencies (CVE)"}
          </button>
        ))}
        <span className="posture__filter-count">{filteredFindings.length} open</span>
      </div>

      {/* ── Body ── */}
      <div className="aegis__body">
        {/* LEFT: finding list */}
        <div className="aegis__list">
          {filteredFindings.length === 0 ? (
            <div className="aegis__empty-list">
              <div className="aegis__empty-glyph">
                {posture?.last_scan_ts ? "✓" : "🛡"}
              </div>
              <div>
                {posture?.last_scan_ts
                  ? "No open findings"
                  : "Run a scan to check posture"}
              </div>
            </div>
          ) : (
            filteredFindings.map((f) => (
              <FindingCard
                key={f.id}
                f={f}
                selected={selectedId === f.id}
                onSelect={() => selectFinding(f.id)}
              />
            ))
          )}
        </div>

        {/* RIGHT: detail panel */}
        <div className="aegis__detail">
          {!selected ? (
            <div className="aegis__empty-detail">
              <div className="aegis__empty-shield" style={{ fontSize: 36, opacity: 0.12 }}>🛡</div>
              <div>Select a finding to see details and ask Leo to fix it</div>
            </div>
          ) : (
            <>
              <div className="aegis__detail-header">
                <div className="aegis__detail-title">{selected.title}</div>
                <div className="aegis__detail-meta">
                  <span><SevDot sev={selected.severity} /> {selected.severity}</span>
                  <span>{selected.category === "sca" ? "Dependency CVE" : "SAST Code"}</span>
                  {selected.cwe && <span>{selected.cwe}</span>}
                  {selected.ai_confidence !== null && (
                    <span>AI confidence: {Math.round((selected.ai_confidence ?? 0) * 100)}%</span>
                  )}
                </div>

                {/* SAST: file + snippet */}
                {selected.category === "sast" && (
                  <div className="posture__detail-loc">
                    {selected.file && (
                      <span className="posture__file-path">
                        {selected.file}:{selected.line}
                      </span>
                    )}
                    {selected.snippet && (
                      <pre className="posture__snippet">{selected.snippet}</pre>
                    )}
                  </div>
                )}

                {/* SCA: package info */}
                {selected.category === "sca" && (
                  <div className="posture__detail-loc">
                    <span className="posture__cve-id">{selected.cve_id}</span>
                    <span className="posture__pkg-info">
                      {selected.package}@{selected.installed_version}
                      {selected.fixed_version ? ` → fix: ${selected.fixed_version}` : ""}
                    </span>
                    {selected.file && (
                      <span className="posture__file-path">
                        Manifest: {selected.file.split(/[\\/]/).pop()}
                      </span>
                    )}
                  </div>
                )}

                {selected.message && (
                  <div style={{ marginTop: 8, fontSize: 12, color: "#8aaccc", lineHeight: 1.5 }}>
                    {selected.message}
                  </div>
                )}
                {selected.recommendation && (
                  <div style={{ marginTop: 4, fontSize: 12, color: "#5a7090" }}>
                    ↳ {selected.recommendation}
                  </div>
                )}
                {selected.ai_summary && (
                  <div style={{ marginTop: 6, fontSize: 11, color: "#ff8c42", fontStyle: "italic" }}>
                    AI: {selected.ai_summary}
                  </div>
                )}
              </div>

              {/* Fix stream area */}
              <div className="aegis__diag-area" ref={fixAreaRef}>
                {fixText ? (
                  <DiagnosisBody text={fixText} streaming={fixState === "streaming"} />
                ) : (
                  fixState === "idle" && (
                    <div style={{ color: "#3a5068", fontSize: 12 }}>
                      Click{" "}
                      <strong style={{ color: "#ff8c42" }}>🐩 Ask Leo to fix</strong>{" "}
                      to get an AI-generated patch.
                    </div>
                  )
                )}
              </div>

              {/* Action bar */}
              <div className="aegis__actions">
                {fixState !== "streaming" && (
                  <button
                    className="aegis__btn aegis__btn--diagnose"
                    onClick={askLeoToFix}
                  >
                    🐩 Ask Leo to fix
                  </button>
                )}

                {fixState === "streaming" && (
                  <button
                    className="aegis__btn aegis__btn--reject"
                    onClick={() => { abortRef.current?.abort(); setFixState("idle"); }}
                  >
                    ✕ Stop
                  </button>
                )}

                {fixState === "done" && extractDiff(fixText) && (
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
                )}

                {fixText && (
                  <CopyButton text={fixText} className="aegis__btn aegis__btn--dismiss" title="Copy fix" />
                )}

                {applyMsg && (
                  <span className={`aegis__toast aegis__toast--${applyState === "ok" ? "ok" : "err"}`}>
                    {applyMsg}
                  </span>
                )}

                <div style={{ flex: 1 }} />

                {selected.status === "open" && (
                  <button className="aegis__btn aegis__btn--reject" onClick={ignore}>
                    Ignore
                  </button>
                )}
                {selected.status === "ignored" && (
                  <button className="aegis__btn aegis__btn--diagnose" onClick={reopen}>
                    Reopen
                  </button>
                )}
                <button
                  className="aegis__btn aegis__btn--dismiss"
                  onClick={() => { setSelectedId(null); abortRef.current?.abort(); }}
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

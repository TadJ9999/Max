// Apollo — prediction engine. Left column: OSINT Report (top) + Market Report
// (bottom) with an Ingest button between them. Right: a tall AI Predictions box.
// Reports auto-fetch on open; Ingest re-runs them AND generates the predictions.
//
// While a box is fetching, the mascot is the loader and a REAL call-log streams
// from the engine (true per-stage trace). Vector-DB reads/writes pulse the
// mascot's particle field — the "Max is learning" cue.

import { useEffect, useRef, useState } from "react";
import { Mascot } from "../components/Mascot";
import { MarkdownView } from "../components/MarkdownView";
import { CopyButton } from "../components/CopyButton";
import {
  streamMarketReport,
  streamOsintReport,
  streamPredict,
  type ApolloEvent,
} from "./apollo";
import "./Apollo.css";

type StreamFn = (signal?: AbortSignal) => AsyncGenerator<ApolloEvent>;
type LogLine = { stage: string; db: number };

function ApolloLoader({
  log,
  dbPulse,
  size,
}: {
  log: LogLine[];
  dbPulse: number;
  size: number;
}) {
  return (
    <div className="apollo__loader">
      <Mascot state="thinking" thinking size={size} signal={log.length} dbActivity={dbPulse} />
      <ul className="apollo__log">
        {log.map((l, i) => (
          <li
            key={i}
            className={`${i === log.length - 1 ? "is-active" : "is-done"}${l.db ? " is-db" : ""}`}
          >
            <span className="apollo__log-dot" />
            {l.stage}
          </li>
        ))}
      </ul>
    </div>
  );
}

function ReportBox({
  title,
  badge,
  stream,
  run,
  tall = false,
}: {
  title: string;
  badge: string;
  stream: StreamFn;
  run: number;
  tall?: boolean;
}) {
  const [text, setText] = useState("");
  const [log, setLog] = useState<LogLine[]>([]);
  const [dbPulse, setDbPulse] = useState(0);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  // (Re)run whenever `run` changes (auto on open / on Ingest). run<=0 means
  // "not triggered yet" — used by predictions before the first Ingest.
  useEffect(() => {
    if (run <= 0) return;
    let cancelled = false;
    const ctrl = new AbortController();
    abortRef.current = ctrl;
    setText("");
    setLog([]);
    setDbPulse(0);
    setErr(null);
    setBusy(true);
    void (async () => {
      try {
        for await (const ev of stream(ctrl.signal)) {
          if (cancelled) return;
          if (ev.type === "status") {
            setLog((l) => [...l, { stage: ev.stage, db: ev.db }]);
            if (ev.db !== 0) setDbPulse((p) => p + 1);
          } else {
            setText((t) => t + ev.text);
          }
        }
      } catch (e) {
        if (!ctrl.signal.aborted) setErr((e as Error).message);
      } finally {
        if (!cancelled) setBusy(false);
      }
    })();
    return () => {
      cancelled = true;
      ctrl.abort();
    };
  }, [run, stream]);

  useEffect(() => () => abortRef.current?.abort(), []);

  const loading = busy && !text;
  const size = tall ? 168 : 132;

  return (
    <section className={`apollo__box${tall ? " apollo__box--tall" : ""}`}>
      <header className="apollo__box-head">
        <span className="apollo__box-title">{title}</span>
        <div className="apollo__box-head-right">
          {text && <CopyButton text={text} />}
          <span className="apollo__box-badge">{badge}</span>
        </div>
      </header>
      <div className="apollo__box-body">
        {run <= 0 ? (
          <div className="apollo__idle">
            <Mascot state="idle" size={size} />
            <p className="apollo__idle-hint">
              Press <b>Ingest</b> to forecast global conflicts &amp; markets.
            </p>
          </div>
        ) : err ? (
          <div className="apollo__error">⚠ {err}</div>
        ) : loading ? (
          <ApolloLoader log={log} dbPulse={dbPulse} size={size} />
        ) : (
          <div className="apollo__report">
            <MarkdownView source={text} />
            {busy && <span className="apollo__cursor">▍</span>}
          </div>
        )}
      </div>
    </section>
  );
}

export function ApolloView({ onClose }: { onClose?: () => void } = {}) {
  const [reportRun, setReportRun] = useState(1); // reports auto-run on open
  const [predictRun, setPredictRun] = useState(0); // predictions wait for Ingest
  const [ingesting, setIngesting] = useState(false);

  const onIngest = () => {
    setReportRun((n) => n + 1);
    setPredictRun((n) => n + 1);
    setIngesting(true);
    window.setTimeout(() => setIngesting(false), 1200);
  };

  return (
    <div className="apollo">
      <header className="apollo__bar">
        <div className="apollo__title">
          <span className="apollo__glyph" aria-hidden="true">
            ▲
          </span>
          Apollo · Prediction Engine
        </div>
        {onClose && (
          <button className="apollo__btn apollo__btn--close" onClick={onClose} title="Close">
            ×
          </button>
        )}
      </header>

      <div className="apollo__body">
        {/* left column: two stacked reports with the Ingest button between */}
        <div className="apollo__col">
          <ReportBox
            title="OSINT Report"
            badge="GLOBAL THREATS"
            stream={streamOsintReport}
            run={reportRun}
          />
          <button
            className={`apollo__ingest${ingesting ? " is-busy" : ""}`}
            onClick={onIngest}
            title="Re-run reports and generate predictions"
          >
            <span className="apollo__ingest-glyph" aria-hidden="true">
              ◈
            </span>
            {ingesting ? "Ingesting…" : "Ingest"}
          </button>
          <ReportBox
            title="Market Report"
            badge="LIVE MARKETS"
            stream={streamMarketReport}
            run={reportRun}
          />
        </div>

        {/* right: tall predictions panel */}
        <ReportBox
          title="AI Predictions"
          badge="CONFLICTS · MARKETS"
          stream={streamPredict}
          run={predictRun}
          tall
        />
      </div>
    </div>
  );
}

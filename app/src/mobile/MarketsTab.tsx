import { useState, useEffect } from "react";
import { getBoard, streamAnalyze, type Quote } from "../market/market";

export function MarketsTab() {
  const [quotes, setQuotes] = useState<Quote[]>([]);
  const [analysis, setAnalysis] = useState("");
  const [analyzing, setAnalyzing] = useState(false);
  const [loading, setLoading] = useState(true);
  const abortRef = { current: null as AbortController | null };

  const refresh = async () => {
    const board = await getBoard();
    if (board) setQuotes(board.quotes);
    setLoading(false);
  };

  useEffect(() => {
    void refresh();
    const id = setInterval(() => void refresh(), 15_000);
    return () => clearInterval(id);
  }, []);

  const analyze = async () => {
    setAnalyzing(true);
    setAnalysis("");
    const ac = new AbortController();
    abortRef.current = ac;
    try {
      for await (const chunk of streamAnalyze(ac.signal)) {
        setAnalysis((a) => a + chunk);
      }
    } catch {
      /* offline or aborted */
    }
    setAnalyzing(false);
  };

  if (loading) return <div className="mob-loading">Loading markets…</div>;
  if (!quotes.length) return <div className="mob-loading">No market data — check Finnhub key.</div>;

  return (
    <div className="mob-scroll">
      <div className="mob-section-head">
        <span className="mob-section-title">US Markets</span>
        <button className="mob-btn" onClick={() => void refresh()}>↻</button>
        <button className="mob-btn mob-btn--accent" onClick={() => void analyze()} disabled={analyzing}>
          {analyzing ? "Reading…" : "AI read"}
        </button>
      </div>

      {quotes.map((q) => (
        <div key={q.symbol} className="mob-card mob-quote">
          <div className="mob-quote__left">
            <span className="mob-quote__sym">{q.symbol}</span>
            {q.name && <span className="mob-quote__name">{q.name}</span>}
          </div>
          <div className="mob-quote__right">
            <span className="mob-quote__price">${q.price.toFixed(2)}</span>
            <span className={`mob-quote__chg${q.change >= 0 ? " mob-up" : " mob-down"}`}>
              {q.change >= 0 ? "+" : ""}{q.change.toFixed(2)} ({q.change >= 0 ? "+" : ""}{q.changePct.toFixed(2)}%)
            </span>
          </div>
        </div>
      ))}

      {analysis && (
        <div className="mob-card mob-analysis">
          <p className="mob-analysis__label">AI read</p>
          <p className="mob-analysis__text">{analysis}</p>
        </div>
      )}
    </div>
  );
}

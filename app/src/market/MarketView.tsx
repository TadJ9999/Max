// Market view — improved Webull-inspired ticker board + collapsible AI panel.
// Layout: full-width board with a slide-in AI panel from the right (same
// pattern as OSINT chat). Sub-tabs: Board (ticker cards) | Summary (stats).

import { useCallback, useEffect, useRef, useState } from "react";
import {
  getBoard,
  getCandles,
  getSources,
  getWatchlist,
  setWatchlist as putWatchlist,
  streamAnalyze,
  streamMarketChat,
  streamTrades,
  type Candle,
  type ChatTurn,
  type MarketBoard,
  type Quote,
} from "./market";

// Resolution/range presets for the drill-down chart (intraday → yearly).
const CHART_RANGES = [
  { key: "1D", resolution: "5",  days: 1,   label: "1D", desc: "5-min intraday" },
  { key: "1W", resolution: "30", days: 7,   label: "1W", desc: "30-min" },
  { key: "1M", resolution: "D",  days: 30,  label: "1M", desc: "daily closes" },
  { key: "3M", resolution: "D",  days: 90,  label: "3M", desc: "daily closes" },
  { key: "1Y", resolution: "W",  days: 365, label: "1Y", desc: "weekly closes" },
] as const;
type RangeKey = (typeof CHART_RANGES)[number]["key"];
import { MarkdownView } from "../components/MarkdownView";
import { CopyButton } from "../components/CopyButton";
import "./Market.css";

const POLL_MS = 10_000;

function fmt(n: number, dec = 2): string {
  return n.toLocaleString(undefined, {
    minimumFractionDigits: dec,
    maximumFractionDigits: dec,
  });
}

function dirClass(change: number): string {
  if (change > 0) return "is-up";
  if (change < 0) return "is-down";
  return "is-flat";
}

async function emitMascotEvent(name: string, payload?: unknown) {
  try {
    const ch = new BroadcastChannel("max:mascot");
    ch.postMessage({ type: name, payload });
    ch.close();
  } catch { /* not supported */ }
  try {
    const { emit } = await import("@tauri-apps/api/event");
    await emit(name, payload);
  } catch { /* not in Tauri */ }
}

// ── Sparkline SVG — mini 30-day price chart ────────────────────────────────
function Sparkline({ candles, dir }: { candles: Candle[]; dir: string }) {
  if (candles.length < 2) return null;
  const W = 80, H = 28;
  const prices = candles.map((c) => c.c);
  const min = Math.min(...prices);
  const max = Math.max(...prices);
  const range = max - min || 1;
  const pts = prices
    .map((p, i) => {
      const x = (i / (prices.length - 1)) * W;
      const y = H - ((p - min) / range) * H;
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");
  const color = dir === "is-up" ? "#22c55e" : dir === "is-down" ? "#ef4444" : "#6b7c93";
  return (
    <svg className="mkt-sparkline" width={W} height={H} viewBox={`0 0 ${W} ${H}`}>
      <polyline points={pts} fill="none" stroke={color} strokeWidth="1.5" strokeLinejoin="round" />
    </svg>
  );
}

// ── Range bar — shows where current price sits vs day range ────────────────
function RangeBar({ quote }: { quote: Quote }) {
  const { low, high, price } = quote;
  const range = high - low;
  const pct = range > 0 ? Math.max(0, Math.min(100, ((price - low) / range) * 100)) : 50;
  return (
    <div className="mkt-card__range" title={`L $${fmt(low)}  H $${fmt(high)}`}>
      <span className="mkt-card__range-lo">${fmt(low)}</span>
      <div className="mkt-card__range-track">
        <div className="mkt-card__range-fill" style={{ width: `${pct}%` }} />
        <div className="mkt-card__range-dot" style={{ left: `${pct}%` }} />
      </div>
      <span className="mkt-card__range-hi">${fmt(high)}</span>
    </div>
  );
}

// ── Ticker drill-down modal ───────────────────────────────────────────────
function DrillDownModal({
  quote,
  candles: initialCandles,
  keySet,
  onClose,
}: {
  quote: Quote;
  candles: Candle[];
  keySet: boolean;
  onClose: () => void;
}) {
  const [rangeKey, setRangeKey] = useState<RangeKey>("1M");
  // Seed the default "1M" view with the sparkline candles already fetched (D/30d).
  const [candles, setCandles] = useState<Candle[]>(initialCandles);
  const [loadingChart, setLoadingChart] = useState(false);
  const activeRange = CHART_RANGES.find((r) => r.key === rangeKey)!;

  // (Re)fetch candles whenever the selected range changes. "1M" reuses the
  // pre-loaded daily candles when present to avoid a redundant request.
  useEffect(() => {
    if (!keySet) { setCandles([]); return; }
    if (rangeKey === "1M" && initialCandles.length > 0) {
      setCandles(initialCandles);
      return;
    }
    let alive = true;
    setLoadingChart(true);
    getCandles(quote.symbol, activeRange.resolution, activeRange.days).then((c) => {
      if (!alive) return;
      setCandles(c);
      setLoadingChart(false);
    });
    return () => { alive = false; };
  }, [quote.symbol, keySet, rangeKey, activeRange.resolution, activeRange.days, initialCandles]);

  const dir = dirClass(quote.change);
  const sign = quote.change > 0 ? "+" : "";

  // Larger chart version
  const W = 340, H = 80;
  const prices = candles.map((c) => c.c);
  const min = Math.min(...prices);
  const max = Math.max(...prices);
  const range = max - min || 1;
  const pts =
    prices.length > 1
      ? prices
          .map((p, i) => {
            const x = (i / (prices.length - 1)) * W;
            const y = H - ((p - min) / range) * H;
            return `${x.toFixed(1)},${y.toFixed(1)}`;
          })
          .join(" ")
      : "";
  const color = dir === "is-up" ? "#22c55e" : dir === "is-down" ? "#ef4444" : "#6b7c93";

  return (
    <div className="mkt-modal-overlay" onClick={onClose}>
      <div className="mkt-modal" onClick={(e) => e.stopPropagation()}>
        <div className="mkt-modal__head">
          <div>
            <div className="mkt-modal__sym">{quote.symbol}</div>
            {quote.name && <div className="mkt-modal__name">{quote.name}</div>}
          </div>
          <button className="mkt-modal__close" onClick={onClose}>×</button>
        </div>

        <div className="mkt-modal__price">
          <span className="mkt-modal__price-val">${fmt(quote.price)}</span>
          <span className={`mkt-modal__chg mkt-modal__chg--${dir}`}>
            {sign}{fmt(quote.change)} ({sign}{fmt(Math.abs(quote.changePct))}%)
          </span>
        </div>

        {/* Resolution / range selector */}
        <div className="mkt-modal__ranges">
          {CHART_RANGES.map((r) => (
            <button
              key={r.key}
              className={`mkt-modal__range${rangeKey === r.key ? " is-on" : ""}`}
              onClick={() => setRangeKey(r.key)}
              title={r.desc}
            >
              {r.label}
            </button>
          ))}
        </div>

        {loadingChart ? (
          <p className="mkt-modal__no-data" style={{ opacity: 0.55 }}>Loading chart…</p>
        ) : pts ? (
          <svg className="mkt-modal__chart" width={W} height={H} viewBox={`0 0 ${W} ${H}`}>
            <polyline points={pts} fill="none" stroke={color} strokeWidth="2" strokeLinejoin="round" />
          </svg>
        ) : (
          <p className="mkt-modal__no-data">
            {keySet ? "No chart data available." : "Set FINNHUB_API_KEY in Settings → API Keys to load chart history."}
          </p>
        )}

        <div className="mkt-modal__stats">
          {[
            ["Open",  `$${fmt(quote.open)}`],
            ["High",  `$${fmt(quote.high)}`],
            ["Low",   `$${fmt(quote.low)}`],
            ["Prev close", `$${fmt(quote.prevClose)}`],
          ].map(([label, value]) => (
            <div key={label} className="mkt-modal__stat">
              <span className="mkt-modal__stat-lbl">{label}</span>
              <span className="mkt-modal__stat-val">{value}</span>
            </div>
          ))}
        </div>

        {candles.length > 0 && (
          <p className="mkt-modal__hint">{activeRange.label} · {activeRange.desc} — {candles.length} points</p>
        )}
      </div>
    </div>
  );
}

// ── Webull-style ticker card ───────────────────────────────────────────────
function TickerCard({
  quote,
  sparkCandles,
  onRemove,
  onDrillDown,
}: {
  quote: Quote;
  sparkCandles: Candle[];
  onRemove: () => void;
  onDrillDown: () => void;
}) {
  const dir = dirClass(quote.change);
  const sign = quote.change > 0 ? "+" : "";
  const changePct = Math.abs(quote.changePct);

  // Flash the price cell green/red on each live tick.
  const [flash, setFlash] = useState<"up" | "down" | null>(null);
  const prevPrice = useRef(quote.price);
  useEffect(() => {
    const prev = prevPrice.current;
    if (quote.price > prev) setFlash("up");
    else if (quote.price < prev) setFlash("down");
    prevPrice.current = quote.price;
    const id = setTimeout(() => setFlash(null), 500);
    return () => clearTimeout(id);
  }, [quote.price]);

  return (
    <div className={`mkt-card mkt-card--${dir}`} onClick={onDrillDown} style={{ cursor: "pointer" }}>
      <div className="mkt-card__left">
        <div className="mkt-card__sym">{quote.symbol}</div>
        {quote.name && <div className="mkt-card__name">{quote.name}</div>}
        <div className="mkt-card__vol">
          {quote.open > 0 && <span>O ${fmt(quote.open)}</span>}
          {quote.prevClose > 0 && <span className="mkt-card__sep">PC ${fmt(quote.prevClose)}</span>}
        </div>
        <Sparkline candles={sparkCandles} dir={dir} />
      </div>
      <div className="mkt-card__right">
        <div className={`mkt-card__price${flash ? ` mkt-card__price--flash-${flash}` : ""}`}>${fmt(quote.price)}</div>
        <div className={`mkt-card__chg mkt-card__chg--${dir}`}>
          <span className="mkt-card__chg-abs">{sign}{fmt(quote.change)}</span>
          <span className={`mkt-card__chg-badge mkt-card__chg-badge--${dir}`}>
            {sign}{fmt(changePct)}%
          </span>
        </div>
        {quote.high > 0 && quote.low > 0 && <RangeBar quote={quote} />}
      </div>
      <button className="mkt-card__rm" onClick={(e) => { e.stopPropagation(); onRemove(); }} title={`Remove ${quote.symbol}`}>×</button>
    </div>
  );
}

// ── Summary tab: market breadth stats ────────────────────────────────────
function SummaryTab({ board }: { board: MarketBoard | null }) {
  if (!board || board.quotes.length === 0) {
    return <div className="mkt-summary__empty">No market data — add tickers to the board.</div>;
  }
  const quotes = board.quotes;
  const up    = quotes.filter((q) => q.change > 0).length;
  const down  = quotes.filter((q) => q.change < 0).length;
  const flat  = quotes.length - up - down;
  const avgChg = quotes.reduce((s, q) => s + q.changePct, 0) / quotes.length;
  const gainers = [...quotes].sort((a, b) => b.changePct - a.changePct).slice(0, 3);
  const losers  = [...quotes].sort((a, b) => a.changePct - b.changePct).slice(0, 3);

  return (
    <div className="mkt-summary">
      <div className="mkt-summary__stats">
        <div className="mkt-summary__stat mkt-summary__stat--up">
          <span className="mkt-summary__stat-val">{up}</span>
          <span className="mkt-summary__stat-lbl">advancing</span>
        </div>
        <div className="mkt-summary__stat mkt-summary__stat--down">
          <span className="mkt-summary__stat-val">{down}</span>
          <span className="mkt-summary__stat-lbl">declining</span>
        </div>
        <div className="mkt-summary__stat">
          <span className="mkt-summary__stat-val">{flat}</span>
          <span className="mkt-summary__stat-lbl">unchanged</span>
        </div>
        <div className={`mkt-summary__stat ${avgChg >= 0 ? "mkt-summary__stat--up" : "mkt-summary__stat--down"}`}>
          <span className="mkt-summary__stat-val">{avgChg >= 0 ? "+" : ""}{fmt(avgChg)}%</span>
          <span className="mkt-summary__stat-lbl">avg move</span>
        </div>
      </div>

      <div className="mkt-summary__lists">
        <div className="mkt-summary__col">
          <div className="mkt-summary__col-head">Top Gainers</div>
          {gainers.map((q) => (
            <div key={q.symbol} className="mkt-summary__row mkt-summary__row--up">
              <span className="mkt-summary__sym">{q.symbol}</span>
              <span className="mkt-summary__pct">+{fmt(q.changePct)}%</span>
            </div>
          ))}
        </div>
        <div className="mkt-summary__col">
          <div className="mkt-summary__col-head">Top Losers</div>
          {losers.map((q) => (
            <div key={q.symbol} className="mkt-summary__row mkt-summary__row--down">
              <span className="mkt-summary__sym">{q.symbol}</span>
              <span className="mkt-summary__pct">{fmt(q.changePct)}%</span>
            </div>
          ))}
        </div>
      </div>

      <div className="mkt-summary__updated">
        Last updated: {new Date(board.updated).toLocaleTimeString()}
      </div>
    </div>
  );
}

// ── Main view ─────────────────────────────────────────────────────────────
export function MarketView({ onClose }: { onClose?: () => void } = {}) {
  const [board, setBoard]   = useState<MarketBoard | null>(null);
  const [watchlist, setList] = useState<string[]>([]);
  const [keySet, setKeySet]  = useState<boolean>(true);
  const [loading, setLoading] = useState(true);
  const [add, setAdd]         = useState("");
  const [subTab, setSubTab]   = useState<"board" | "summary">("board");
  const [sparklines, setSparklines] = useState<Record<string, Candle[]>>({});
  const [drillSym, setDrillSym]     = useState<string | null>(null);
  // Live trade ticks from the SSE bridge (overlay the polled board).
  const [liveTicks, setLiveTicks]   = useState<Record<string, number>>({});
  const [streamLive, setStreamLive] = useState(false);

  // AI panel state (collapsible, slides from right)
  const [panelOpen, setPanelOpen] = useState(false);
  const [analysis, setAnalysis]   = useState("");
  const [ingesting, setIngesting] = useState(false);
  const [ingestErr, setIngestErr] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  // Chat
  const [chat, setChat]       = useState<ChatTurn[]>([]);
  const [question, setQuestion] = useState("");
  const [chatBusy, setChatBusy] = useState(false);
  const chatAbortRef = useRef<AbortController | null>(null);
  const chatThreadRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (chatThreadRef.current) {
      chatThreadRef.current.scrollTop = chatThreadRef.current.scrollHeight;
    }
  }, [chat]);

  useEffect(() => {
    void (async () => {
      const wl = await getWatchlist();
      if (wl.length) setList(wl);
    })();
  }, []);

  const refresh = useCallback(async () => {
    const [b, src] = await Promise.all([getBoard(), getSources()]);
    setBoard(b);
    if (src) {
      setKeySet(src.key_set);
      if (src.watchlist.length) setList((cur) => (cur.length ? cur : src.watchlist));
    }
    setLoading(false);
    // Lazy-load sparklines for all visible symbols (don't await — background)
    if (b && src?.key_set) {
      void Promise.all(
        b.quotes.map(async (q) => {
          if (sparklines[q.symbol]?.length) return;
          const candles = await getCandles(q.symbol, "D", 30);
          if (candles.length) {
            setSparklines((prev) => ({ ...prev, [q.symbol]: candles }));
          }
        }),
      );
    }
  }, [sparklines]);

  useEffect(() => {
    void refresh();
    const id = setInterval(() => void refresh(), POLL_MS);
    return () => clearInterval(id);
  }, [refresh]);

  // Live trade-tick stream (Finnhub WS → engine SSE). Reconnects on drop.
  useEffect(() => {
    const ctrl = new AbortController();
    let alive = true;
    void (async () => {
      while (alive) {
        try {
          for await (const ev of streamTrades(ctrl.signal)) {
            if ("type" in ev && ev.type === "nokey") { setStreamLive(false); return; }
            const tr = ev as { symbol: string; price: number };
            if (tr.symbol && typeof tr.price === "number") {
              setStreamLive(true);
              setLiveTicks((prev) => ({ ...prev, [tr.symbol]: tr.price }));
            }
          }
        } catch { /* stream dropped */ }
        if (!alive) break;
        setStreamLive(false);
        await new Promise((r) => setTimeout(r, 2000)); // reconnect backoff
      }
    })();
    return () => { alive = false; ctrl.abort(); };
  }, []);

  const commitWatchlist = useCallback(async (next: string[]) => {
    setList(next);
    const saved = await putWatchlist(next);
    setList(saved);
    await refresh();
  }, [refresh]);

  const onAdd = () => {
    const sym = add.trim().toUpperCase();
    if (!sym || watchlist.includes(sym)) { setAdd(""); return; }
    void commitWatchlist([...watchlist, sym]);
    setAdd("");
  };

  const onRemove = (sym: string) => {
    void commitWatchlist(watchlist.filter((s) => s !== sym));
  };

  const onIngest = async () => {
    if (ingesting) { abortRef.current?.abort(); return; }
    setAnalysis("");
    setIngestErr(null);
    setIngesting(true);
    setPanelOpen(true);
    void emitMascotEvent("mascot:signal");
    void emitMascotEvent("mascot:thinking", true);
    const ctrl = new AbortController();
    abortRef.current = ctrl;
    try {
      for await (const delta of streamAnalyze(ctrl.signal)) {
        setAnalysis((prev) => prev + delta);
      }
    } catch (e) {
      if (!ctrl.signal.aborted) setIngestErr((e as Error).message);
    } finally {
      setIngesting(false);
      abortRef.current = null;
      void emitMascotEvent("mascot:thinking", false);
    }
  };

  useEffect(() => () => abortRef.current?.abort(), []);

  const sendChat = async () => {
    const q = question.trim();
    if (!q || chatBusy) return;
    const history: ChatTurn[] = [...chat, { role: "user", content: q }];
    setChat([...history, { role: "assistant", content: "" }]);
    setQuestion("");
    setChatBusy(true);
    void emitMascotEvent("mascot:signal");
    void emitMascotEvent("mascot:thinking", true);
    const ctrl = new AbortController();
    chatAbortRef.current = ctrl;
    try {
      for await (const delta of streamMarketChat(history, ctrl.signal)) {
        setChat((prev) => {
          const next = prev.slice();
          const last = next[next.length - 1];
          next[next.length - 1] = { ...last, content: last.content + delta };
          return next;
        });
      }
    } catch (e) {
      if (!ctrl.signal.aborted) {
        setChat((prev) => {
          const next = prev.slice();
          next[next.length - 1] = { role: "assistant", content: `⚠ ${(e as Error).message}` };
          return next;
        });
      }
    } finally {
      setChatBusy(false);
      chatAbortRef.current = null;
      void emitMascotEvent("mascot:thinking", false);
    }
  };

  useEffect(() => () => chatAbortRef.current?.abort(), []);

  const rawQuotes = board?.quotes ?? [];
  // Overlay the latest live tick onto each quote, recomputing change vs prev close.
  const quotes = rawQuotes.map((q) => {
    const lp = liveTicks[q.symbol];
    if (lp == null || lp === q.price) return q;
    const change = lp - q.prevClose;
    const changePct = q.prevClose ? (change / q.prevClose) * 100 : q.changePct;
    return { ...q, price: lp, change, changePct };
  });
  const drillQuote = drillSym ? quotes.find((q) => q.symbol === drillSym) ?? null : null;
  const offline = !loading && board === null;

  return (
    <div className="market">
      {/* ── AI slide-in panel (right overlay) ── */}
      <div className={`market__ai-panel${panelOpen ? " is-open" : ""}`}>
        <div className="market__ai-head">
          <span className="market__ai-title">✦ AI Analysis & Chat</span>
          <button className="market__ai-close" onClick={() => setPanelOpen(false)}>×</button>
        </div>

        {/* Analysis section */}
        <div className="market__ai-section-head">
          AI Ingest
          {analysis && <CopyButton text={analysis} />}
        </div>
        <div className="market__ai-analysis">
          {ingestErr && <div className="market__error">{ingestErr}</div>}
          {!analysis && !ingesting && !ingestErr && (
            <div className="market__placeholder">
              Press <b>Ingest</b> for an AI read of the live board.
              <div className="market__disclaimer">Informational only — not financial advice.</div>
            </div>
          )}
          {analysis && <MarkdownView source={analysis} />}
          {ingesting && <span className="market__cursor">▍</span>}
        </div>

        {/* Chat section */}
        <div className="market__ai-section-head market__ai-section-head--chat">Ask the board</div>
        <div className="market__ai-chat">
          <div className="market__chat-thread" ref={chatThreadRef}>
            {chat.length === 0 && (
              <div className="market__placeholder">
                Ask anything — e.g. <i>"why is NVDA down?"</i>
              </div>
            )}
            {chat.map((turn, i) => (
              <div key={i} className={`market__msg market__msg--${turn.role}`}>
                {turn.role === "assistant" ? (
                  turn.content ? (
                    <>
                      <MarkdownView source={turn.content} />
                      <CopyButton text={turn.content} className="market__msg-copy" />
                    </>
                  ) : (
                    <span className="market__cursor">▍</span>
                  )
                ) : (
                  turn.content
                )}
              </div>
            ))}
          </div>
          <div className="market__chat-input">
            <input
              className="market__chat-text"
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              onKeyDown={(e) =>
                e.key === "Enter" && !e.shiftKey && (e.preventDefault(), void sendChat())
              }
              placeholder="Ask about the board…"
              disabled={chatBusy}
            />
            <button
              className="market__chat-send"
              onClick={() => void sendChat()}
              disabled={chatBusy || !question.trim()}
            >
              {chatBusy ? "…" : "▶"}
            </button>
          </div>
        </div>
      </div>

      {/* ── header bar ── */}
      <header className="market__bar">
        <div className="market__title">
          <span className="market__glyph">$</span>
          Market · Live Tape
        </div>

        {/* Sub-tabs */}
        <div className="market__subtabs">
          {(["board", "summary"] as const).map((t) => (
            <button
              key={t}
              className={`market__subtab${subTab === t ? " is-on" : ""}`}
              onClick={() => setSubTab(t)}
            >
              {t === "board" ? "Board" : "Summary"}
            </button>
          ))}
        </div>

        <div className="market__bar-right">
          {streamLive && (
            <span className="market__live" title="Live trade stream connected (Finnhub)">
              <span className="market__live-dot" /> LIVE
            </span>
          )}
          <span className="market__updated">
            {loading ? "loading…"
              : offline ? "engine offline"
              : !keySet ? "no API key"
              : `${quotes.length} symbols`}
          </span>
          <button
            className={`market__ingest${ingesting ? " is-busy" : ""}`}
            onClick={() => void onIngest()}
          >
            {ingesting ? "Ingesting…" : "Ingest"}
          </button>
          {onClose && (
            <button className="market__btn market__btn--close" onClick={onClose}>×</button>
          )}
        </div>
      </header>

      {/* ── animated orb AI FAB (bottom-right) ── */}
      <button
        className={`market__ai-fab${panelOpen ? " is-on" : ""}`}
        onClick={() => setPanelOpen((v) => !v)}
        title={panelOpen ? "Close AI panel" : "AI Analysis & Chat"}
        aria-label="Toggle AI panel"
      >
        <span className="market__ai-fab__fluid market__ai-fab__fluid--a" />
        <span className="market__ai-fab__fluid market__ai-fab__fluid--b" />
        <span className="market__ai-fab__fluid market__ai-fab__fluid--c" />
        <span className="market__ai-fab__gloss" />
      </button>

      {/* ── body ── */}
      <div className="market__body">
        {subTab === "board" ? (
          <div className="market__board">
            {/* Add ticker */}
            <div className="market__add">
              <input
                className="market__add-input"
                value={add}
                onChange={(e) => setAdd(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && onAdd()}
                placeholder="Add ticker (e.g. AAPL)"
                spellCheck={false}
                maxLength={8}
              />
              <button className="market__add-btn" onClick={onAdd}>+</button>
            </div>

            {!keySet && (
              <div className="market__note">
                Set <code>FINNHUB_API_KEY</code> in Settings for live quotes.
              </div>
            )}
            {offline && (
              <div className="market__note">Engine offline — start Max engine for live quotes.</div>
            )}

            {drillQuote && (
              <DrillDownModal
                quote={drillQuote}
                candles={sparklines[drillQuote.symbol] ?? []}
                keySet={keySet}
                onClose={() => setDrillSym(null)}
              />
            )}

            <div className="market__cards">
              {quotes.length === 0 && !loading && (
                <div className="market__empty">No quotes yet.</div>
              )}
              {quotes.map((q) => (
                <TickerCard
                  key={q.symbol}
                  quote={q}
                  sparkCandles={sparklines[q.symbol] ?? []}
                  onRemove={() => onRemove(q.symbol)}
                  onDrillDown={() => setDrillSym(q.symbol)}
                />
              ))}
            </div>
          </div>
        ) : (
          <div className="market__board">
            <SummaryTab board={board} />
          </div>
        )}
      </div>
    </div>
  );
}

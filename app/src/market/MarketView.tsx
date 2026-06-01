// Market view — Webull-style single-symbol trading terminal.
// Layout: left watchlist (switches the focused symbol) │ center candlestick
// chart (+ volume + RSI, selectable intervals) │ right rail (Quotes, simulated
// Order Book L2, live Time & Sales). The AI Analysis/Chat slide-in panel + orb
// FAB are unchanged. Order-book depth is SIMULATED around the live price (no
// free L2 feed exists) and clearly tagged; everything else is real data.

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  getBoard,
  getCandles,
  getNews,
  getSources,
  getWatchlist,
  setWatchlist as putWatchlist,
  streamAnalyze,
  streamMarketChat,
  streamTrades,
  type Candle,
  type ChatTurn,
  type MarketBoard,
  type NewsItem,
  type Quote,
} from "./market";
import { MarketOverview } from "./MarketOverview";
import { MarkdownView } from "../components/MarkdownView";
import { CopyButton } from "../components/CopyButton";
import { HindsightPanel } from "../oracle/HindsightPanel";
import "./Market.css";

type MarketViewMode = "overview" | "terminal";

const POLL_MS = 10_000;

// Webull-style interval presets → Finnhub resolution + lookback window.
const INTERVALS = [
  { key: "5",  label: "5m", resolution: "5",  days: 1 },
  { key: "30", label: "30m", resolution: "30", days: 5 },
  { key: "60", label: "1H", resolution: "60", days: 10 },
  { key: "D",  label: "D",  resolution: "D",  days: 180 },
  { key: "W",  label: "W",  resolution: "W",  days: 730 },
  { key: "M",  label: "M",  resolution: "M",  days: 1825 },
] as const;
type IntervalKey = (typeof INTERVALS)[number]["key"];

const UP = "#22c55e";
const DOWN = "#ef4444";
const FLAT = "#6b7c93";

function fmt(n: number, dec = 2): string {
  return n.toLocaleString(undefined, { minimumFractionDigits: dec, maximumFractionDigits: dec });
}

function fmtCompact(n: number): string {
  if (!isFinite(n)) return "—";
  if (n >= 1e9) return `${(n / 1e9).toFixed(2)}B`;
  if (n >= 1e6) return `${(n / 1e6).toFixed(2)}M`;
  if (n >= 1e3) return `${(n / 1e3).toFixed(1)}K`;
  return String(Math.round(n));
}

function dirClass(change: number): string {
  if (change > 0) return "is-up";
  if (change < 0) return "is-down";
  return "is-flat";
}

function dirColor(change: number): string {
  return change > 0 ? UP : change < 0 ? DOWN : FLAT;
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

// ── element size hook (px-accurate charts that fill their container) ───────
function useElementSize<T extends HTMLElement>() {
  const ref = useRef<T | null>(null);
  const [size, setSize] = useState({ w: 0, h: 0 });
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const ro = new ResizeObserver((entries) => {
      const r = entries[0]?.contentRect;
      if (r) setSize({ w: Math.round(r.width), h: Math.round(r.height) });
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  return [ref, size] as const;
}

// ── Wilder's RSI(14) over candle closes; NaN until enough data ─────────────
function computeRSI(candles: Candle[], period = 14): number[] {
  const out = new Array(candles.length).fill(NaN);
  if (candles.length <= period) return out;
  let gain = 0, loss = 0;
  for (let i = 1; i <= period; i++) {
    const d = candles[i].c - candles[i - 1].c;
    if (d >= 0) gain += d; else loss -= d;
  }
  let avgGain = gain / period, avgLoss = loss / period;
  out[period] = avgLoss === 0 ? 100 : 100 - 100 / (1 + avgGain / avgLoss);
  for (let i = period + 1; i < candles.length; i++) {
    const d = candles[i].c - candles[i - 1].c;
    const g = d > 0 ? d : 0, l = d < 0 ? -d : 0;
    avgGain = (avgGain * (period - 1) + g) / period;
    avgLoss = (avgLoss * (period - 1) + l) / period;
    out[i] = avgLoss === 0 ? 100 : 100 - 100 / (1 + avgGain / avgLoss);
  }
  return out;
}

// ── Candlestick + volume chart (fills its container) ───────────────────────
function CandleChart({ candles }: { candles: Candle[] }) {
  const [ref, { w, h }] = useElementSize<HTMLDivElement>();
  const RIGHT = 52, LEFT = 4, TOP = 8, BOT = 6;
  const n = candles.length;

  const body = (() => {
    if (n < 2 || w < 40 || h < 40) return null;
    const innerW = w - RIGHT - LEFT;
    const volH = Math.max(26, h * 0.18);
    const priceH = h - volH - TOP - BOT - 6;
    const highs = candles.map((c) => c.h);
    const lows = candles.map((c) => c.l);
    const pMax = Math.max(...highs), pMin = Math.min(...lows);
    const pRange = pMax - pMin || 1;
    const vMax = Math.max(...candles.map((c) => c.v), 1);
    const slot = innerW / n;
    const bodyW = Math.max(1, Math.min(slot * 0.7, 14));
    const yPrice = (p: number) => TOP + (1 - (p - pMin) / pRange) * priceH;
    const volTop = TOP + priceH + 6;
    const lastClose = candles[n - 1].c;

    const gridVals = Array.from({ length: 5 }, (_, i) => pMin + (pRange * i) / 4);
    return { innerW, volH, priceH, pMax, pMin, vMax, slot, bodyW, yPrice, volTop, lastClose, gridVals };
  })();

  return (
    <div className="mkt-chart" ref={ref}>
      {body && (
        <svg className="mkt-chart__svg" width={w} height={h}>
          {/* horizontal price grid + right-axis labels */}
          {body.gridVals.map((p, i) => {
            const y = body.yPrice(p);
            return (
              <g key={i}>
                <line x1={LEFT} y1={y} x2={w - RIGHT} y2={y} stroke="rgba(255,255,255,0.05)" />
                <text x={w - RIGHT + 5} y={y + 3} className="mkt-chart__axis">{fmt(p)}</text>
              </g>
            );
          })}
          {/* candles */}
          {candles.map((c, i) => {
            const x = LEFT + i * body.slot + body.slot / 2;
            const up = c.c >= c.o;
            const col = up ? UP : DOWN;
            const yO = body.yPrice(c.o), yC = body.yPrice(c.c);
            const top = Math.min(yO, yC);
            const bh = Math.max(1, Math.abs(yC - yO));
            const vh = (c.v / body.vMax) * (body.volH - 2);
            return (
              <g key={i}>
                <line x1={x} y1={body.yPrice(c.h)} x2={x} y2={body.yPrice(c.l)} stroke={col} strokeWidth="1" />
                <rect x={x - body.bodyW / 2} y={top} width={body.bodyW} height={bh} fill={col} />
                <rect
                  x={x - body.bodyW / 2}
                  y={body.volTop + (body.volH - vh)}
                  width={body.bodyW}
                  height={vh}
                  fill={col}
                  opacity={0.45}
                />
              </g>
            );
          })}
          {/* last-price dashed marker */}
          <line
            x1={LEFT}
            y1={body.yPrice(body.lastClose)}
            x2={w - RIGHT}
            y2={body.yPrice(body.lastClose)}
            stroke="rgba(34,211,238,0.55)"
            strokeWidth="1"
            strokeDasharray="3 3"
          />
          <rect x={w - RIGHT} y={body.yPrice(body.lastClose) - 8} width={RIGHT} height={16} fill="rgba(34,211,238,0.85)" rx="2" />
          <text x={w - RIGHT + 4} y={body.yPrice(body.lastClose) + 3} className="mkt-chart__axis mkt-chart__axis--last">
            {fmt(body.lastClose)}
          </text>
        </svg>
      )}
    </div>
  );
}

// ── RSI(14) sub-chart ──────────────────────────────────────────────────────
function RsiChart({ candles }: { candles: Candle[] }) {
  const [ref, { w, h }] = useElementSize<HTMLDivElement>();
  const rsi = useMemo(() => computeRSI(candles), [candles]);
  const RIGHT = 52, LEFT = 4;
  const valid = rsi.filter((v) => !isNaN(v));
  const last = valid.length ? valid[valid.length - 1] : NaN;

  const path = (() => {
    if (w < 40 || h < 20 || candles.length < 2) return "";
    const innerW = w - RIGHT - LEFT;
    const slot = innerW / candles.length;
    const y = (v: number) => 2 + (1 - v / 100) * (h - 4);
    let d = "";
    let started = false;
    rsi.forEach((v, i) => {
      if (isNaN(v)) return;
      const x = LEFT + i * slot + slot / 2;
      d += `${started ? "L" : "M"}${x.toFixed(1)},${y(v).toFixed(1)} `;
      started = true;
    });
    return d;
  })();

  const yLvl = (v: number) => 2 + (1 - v / 100) * (h - 4);
  return (
    <div className="mkt-rsi" ref={ref}>
      {w > 40 && (
        <svg className="mkt-chart__svg" width={w} height={h}>
          <line x1={LEFT} y1={yLvl(70)} x2={w - RIGHT} y2={yLvl(70)} stroke="rgba(239,68,68,0.25)" strokeDasharray="2 3" />
          <line x1={LEFT} y1={yLvl(30)} x2={w - RIGHT} y2={yLvl(30)} stroke="rgba(34,197,94,0.25)" strokeDasharray="2 3" />
          <text x={w - RIGHT + 5} y={yLvl(70) + 3} className="mkt-chart__axis">70</text>
          <text x={w - RIGHT + 5} y={yLvl(30) + 3} className="mkt-chart__axis">30</text>
          {path && <path d={path} fill="none" stroke="#38bdf8" strokeWidth="1.3" />}
        </svg>
      )}
      <span className="mkt-rsi__label">
        RSI(14) <b style={{ color: isNaN(last) ? FLAT : last >= 70 ? DOWN : last <= 30 ? UP : "#38bdf8" }}>
          {isNaN(last) ? "—" : last.toFixed(1)}
        </b>
      </span>
    </div>
  );
}

// ── Simulated Order Book (L2). No free depth feed exists — derived from the
// live price + spread, clearly tagged SIM. Deterministic per (symbol, price)
// so it doesn't jitter wildly between renders but moves as the price moves. ──
function seededSize(sym: string, level: number, priceBucket: number): number {
  let s = priceBucket + level * 97;
  for (let i = 0; i < sym.length; i++) s = (s * 31 + sym.charCodeAt(i)) >>> 0;
  // 1..~9999 with a bias toward smaller sizes
  const r = ((s % 1000) / 1000) ** 1.7;
  return Math.max(1, Math.round(r * 4000) + (level % 3 === 0 ? 200 : 10));
}

function OrderBook({ quote }: { quote: Quote }) {
  const mid = quote.price || quote.prevClose || 0;
  const levels = 8;
  const spread = Math.max(0.01, mid * 0.0004);
  const bucket = Math.floor(mid * 100);
  const asks = Array.from({ length: levels }, (_, i) => {
    const lvl = levels - i; // top of list = highest ask
    return { price: mid + spread * lvl, size: seededSize(quote.symbol, lvl + 50, bucket) };
  });
  const bids = Array.from({ length: levels }, (_, i) => {
    const lvl = i + 1;
    return { price: mid - spread * lvl, size: seededSize(quote.symbol, lvl, bucket) };
  });
  const maxSize = Math.max(...asks.map((a) => a.size), ...bids.map((b) => b.size), 1);

  const Row = ({ price, size, side }: { price: number; size: number; side: "ask" | "bid" }) => (
    <div className={`mkt-ob__row mkt-ob__row--${side}`}>
      <span className="mkt-ob__depth" style={{ width: `${(size / maxSize) * 100}%` }} />
      <span className="mkt-ob__size">{fmtCompact(size)}</span>
      <span className="mkt-ob__price">{fmt(price)}</span>
    </div>
  );

  return (
    <div className="mkt-panel mkt-ob">
      <div className="mkt-panel__head">
        Order Book (L2)
        <span className="mkt-ob__sim" title="No free Level-2 feed exists. This depth is simulated around the live price for layout — it is not real market depth.">SIM</span>
      </div>
      <div className="mkt-ob__cols"><span>Size</span><span>Bid · Ask</span></div>
      <div className="mkt-ob__side">{asks.map((a, i) => <Row key={`a${i}`} {...a} side="ask" />)}</div>
      <div className="mkt-ob__mid">
        <span>{fmt(mid)}</span>
        <span className="mkt-ob__spread">spread {fmt(spread * 2)}</span>
      </div>
      <div className="mkt-ob__side">{bids.map((b, i) => <Row key={`b${i}`} {...b} side="bid" />)}</div>
    </div>
  );
}

// ── Time & Sales (real, from the live Finnhub trade stream) ────────────────
type Tape = { price: number; size: number | null; ts: number | null; dir: "up" | "down" | "flat" };

function TimeSales({ tape }: { tape: Tape[] }) {
  return (
    <div className="mkt-panel mkt-ts">
      <div className="mkt-panel__head">Time &amp; Sales</div>
      <div className="mkt-ts__cols"><span>Time</span><span>Price</span><span>Size</span></div>
      <div className="mkt-ts__rows">
        {tape.length === 0 && <div className="mkt-ts__empty">Waiting for live trades…</div>}
        {tape.map((t, i) => (
          <div key={i} className={`mkt-ts__row mkt-ts__row--${t.dir}`}>
            <span className="mkt-ts__time">
              {t.ts ? new Date(t.ts).toLocaleTimeString(undefined, { hour12: false }) : "—"}
            </span>
            <span className="mkt-ts__price">{fmt(t.price)}</span>
            <span className="mkt-ts__size">{t.size != null ? fmtCompact(t.size) : "—"}</span>
          </div>
        ))}
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
  const [focused, setFocused] = useState<string | null>(null);
  const focusedRef = useRef<string | null>(null);
  const [interval, setIntervalKey] = useState<IntervalKey>("D");
  const [candles, setCandles] = useState<Candle[]>([]);
  const [loadingChart, setLoadingChart] = useState(false);

  // Overview (full market board) vs Terminal (single-symbol). Overview is the
  // landing view; clicking a card drills into the Terminal for that symbol.
  const [mode, setMode] = useState<MarketViewMode>("overview");
  const [news, setNews] = useState<NewsItem[]>([]);

  // Live trade ticks: latest price per symbol (board overlay) + a rolling tape
  // for the focused symbol (Time & Sales).
  const [liveTicks, setLiveTicks] = useState<Record<string, number>>({});
  const [tape, setTape] = useState<Tape[]>([]);
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
    if (chatThreadRef.current) chatThreadRef.current.scrollTop = chatThreadRef.current.scrollHeight;
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
  }, []);

  useEffect(() => {
    void refresh();
    const id = setInterval(() => void refresh(), POLL_MS);
    return () => clearInterval(id);
  }, [refresh]);

  // Market news for the Overview board (slow-moving; 5-min server cache).
  useEffect(() => {
    void getNews(10).then(setNews);
    const id = setInterval(() => void getNews(10).then(setNews), 300_000);
    return () => clearInterval(id);
  }, []);

  // Pick a default focused symbol once the board loads.
  useEffect(() => {
    if (!focused && board?.quotes.length) setFocused(board.quotes[0].symbol);
  }, [board, focused]);

  useEffect(() => { focusedRef.current = focused; setTape([]); }, [focused]);

  // (Re)load candles whenever the focused symbol or interval changes.
  useEffect(() => {
    if (!focused || !keySet) { setCandles([]); return; }
    const ivl = INTERVALS.find((x) => x.key === interval)!;
    let alive = true;
    setLoadingChart(true);
    getCandles(focused, ivl.resolution, ivl.days).then((c) => {
      if (!alive) return;
      setCandles(c);
      setLoadingChart(false);
    });
    return () => { alive = false; };
  }, [focused, interval, keySet]);

  // Live trade-tick stream (Finnhub WS → engine SSE). Reconnects on drop.
  useEffect(() => {
    const ctrl = new AbortController();
    let alive = true;
    void (async () => {
      while (alive) {
        try {
          for await (const ev of streamTrades(ctrl.signal)) {
            if ("type" in ev && ev.type === "nokey") { setStreamLive(false); return; }
            const tr = ev as { symbol: string; price: number; volume: number | null; ts: number | null };
            if (tr.symbol && typeof tr.price === "number") {
              setStreamLive(true);
              setLiveTicks((prev) => {
                const dir: Tape["dir"] = prev[tr.symbol] == null ? "flat"
                  : tr.price > prev[tr.symbol] ? "up" : tr.price < prev[tr.symbol] ? "down" : "flat";
                if (tr.symbol === focusedRef.current) {
                  setTape((t) => [{ price: tr.price, size: tr.volume, ts: tr.ts ? tr.ts : Date.now(), dir }, ...t].slice(0, 40));
                }
                return { ...prev, [tr.symbol]: tr.price };
              });
            }
          }
        } catch { /* stream dropped */ }
        if (!alive) break;
        setStreamLive(false);
        await new Promise((r) => setTimeout(r, 2000));
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
    if (!sym) return;
    if (!watchlist.includes(sym)) void commitWatchlist([...watchlist, sym]);
    setFocused(sym);
    setAdd("");
  };

  const onRemove = (sym: string) => {
    void commitWatchlist(watchlist.filter((s) => s !== sym));
    if (focused === sym) setFocused(null);
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
      for await (const delta of streamAnalyze(ctrl.signal)) setAnalysis((prev) => prev + delta);
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

  // Overlay the latest live tick onto each quote, recomputing change vs prev close.
  const quotes = (board?.quotes ?? []).map((q) => {
    const lp = liveTicks[q.symbol];
    if (lp == null || lp === q.price) return q;
    const change = lp - q.prevClose;
    const changePct = q.prevClose ? (change / q.prevClose) * 100 : q.changePct;
    return { ...q, price: lp, change, changePct };
  });
  const focusedQuote = focused ? quotes.find((q) => q.symbol === focused) ?? null : null;
  const lastVol = candles.length ? candles[candles.length - 1].v : 0;
  const offline = !loading && board === null;

  return (
    <div className="market">
      {/* ── AI slide-in panel (right overlay) ── */}
      <div className={`market__ai-panel${panelOpen ? " is-open" : ""}`}>
        <div className="market__ai-head">
          <span className="market__ai-title">✦ AI Analysis &amp; Chat</span>
          <button className="market__ai-close" onClick={() => setPanelOpen(false)}>×</button>
        </div>
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
          {analysis && !ingesting && (
            <HindsightPanel feature="market" entity={focused ?? undefined} query={analysis} />
          )}
        </div>
        <div className="market__ai-section-head market__ai-section-head--chat">Ask the board</div>
        <div className="market__ai-chat">
          <div className="market__chat-thread" ref={chatThreadRef}>
            {chat.length === 0 && (
              <div className="market__placeholder">Ask anything — e.g. <i>"why is NVDA down?"</i></div>
            )}
            {chat.map((turn, i) => (
              <div key={i} className={`market__msg market__msg--${turn.role}`}>
                {turn.role === "assistant" ? (
                  turn.content ? (
                    <>
                      <MarkdownView source={turn.content} />
                      <CopyButton text={turn.content} className="market__msg-copy" />
                    </>
                  ) : (<span className="market__cursor">▍</span>)
                ) : (turn.content)}
              </div>
            ))}
          </div>
          <div className="market__chat-input">
            <input
              className="market__chat-text"
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && !e.shiftKey && (e.preventDefault(), void sendChat())}
              placeholder="Ask about the board…"
              disabled={chatBusy}
            />
            <button className="market__chat-send" onClick={() => void sendChat()} disabled={chatBusy || !question.trim()}>
              {chatBusy ? "…" : "▶"}
            </button>
          </div>
        </div>
      </div>

      {/* ── header bar ── */}
      <header className="market__bar">
        <div className="market__title">
          <span className="market__glyph">$</span>
          Market
        </div>
        <div className="market__subtabs" role="tablist" aria-label="Market view">
          <button
            className={`market__subtab${mode === "overview" ? " is-on" : ""}`}
            onClick={() => setMode("overview")}
            role="tab"
            aria-selected={mode === "overview"}
          >
            Overview
          </button>
          <button
            className={`market__subtab${mode === "terminal" ? " is-on" : ""}`}
            onClick={() => setMode("terminal")}
            role="tab"
            aria-selected={mode === "terminal"}
          >
            Terminal
          </button>
        </div>
        <div className="market__bar-right">
          {streamLive && (
            <span className="market__live" title="Live trade stream connected (Finnhub)">
              <span className="market__live-dot" /> LIVE
            </span>
          )}
          <span className="market__updated">
            {loading ? "loading…" : offline ? "engine offline" : !keySet ? "no API key" : `${quotes.length} symbols`}
          </span>
          <button className={`market__ingest${ingesting ? " is-busy" : ""}`} onClick={() => void onIngest()}>
            {ingesting ? "Ingesting…" : "Ingest"}
          </button>
          {onClose && <button className="market__btn market__btn--close" onClick={onClose}>×</button>}
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

      {/* ── Overview (full market board) ── */}
      {mode === "overview" && (
        <MarketOverview
          quotes={quotes}
          news={news}
          loading={loading}
          offline={offline}
          keySet={keySet}
          add={add}
          setAdd={setAdd}
          onAdd={onAdd}
          onRemove={onRemove}
          onSelect={(sym) => { setFocused(sym); setMode("terminal"); }}
        />
      )}

      {/* ── terminal body: watchlist │ chart │ right rail ── */}
      <div className="market__term" hidden={mode !== "terminal"}>
        {/* Watchlist */}
        <aside className="mkt-watch">
          <div className="mkt-watch__add">
            <input
              className="mkt-watch__add-input"
              value={add}
              onChange={(e) => setAdd(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && onAdd()}
              placeholder="Add symbol"
              spellCheck={false}
              maxLength={8}
            />
            <button className="mkt-watch__add-btn" onClick={onAdd}>+</button>
          </div>
          <div className="mkt-watch__head"><span>Symbol</span><span>Price · Chg%</span></div>
          <div className="mkt-watch__list">
            {quotes.length === 0 && !loading && <div className="mkt-watch__empty">No symbols.</div>}
            {quotes.map((q) => {
              const dir = dirClass(q.change);
              const sign = q.change > 0 ? "+" : "";
              return (
                <div
                  key={q.symbol}
                  className={`mkt-watch__row${focused === q.symbol ? " is-active" : ""}`}
                  onClick={() => setFocused(q.symbol)}
                >
                  <div className="mkt-watch__sym">
                    <span className="mkt-watch__ticker">{q.symbol}</span>
                    {q.name && <span className="mkt-watch__name">{q.name}</span>}
                  </div>
                  <div className="mkt-watch__nums">
                    <span className="mkt-watch__price">{fmt(q.price)}</span>
                    <span className={`mkt-watch__pct mkt-watch__pct--${dir}`}>{sign}{fmt(q.changePct)}%</span>
                  </div>
                  <button className="mkt-watch__rm" onClick={(e) => { e.stopPropagation(); onRemove(q.symbol); }} title={`Remove ${q.symbol}`}>×</button>
                </div>
              );
            })}
          </div>
        </aside>

        {/* Center: quote header + chart */}
        <section className="mkt-center">
          {focusedQuote ? (
            <>
              <div className="mkt-quote-head">
                <div className="mkt-quote-head__id">
                  <span className="mkt-quote-head__sym">{focusedQuote.symbol}</span>
                  {focusedQuote.name && <span className="mkt-quote-head__name">{focusedQuote.name}</span>}
                </div>
                <div className="mkt-quote-head__px">
                  <span className="mkt-quote-head__price" style={{ color: dirColor(focusedQuote.change) }}>
                    {fmt(focusedQuote.price)}
                  </span>
                  <span className="mkt-quote-head__chg" style={{ color: dirColor(focusedQuote.change) }}>
                    {focusedQuote.change > 0 ? "+" : ""}{fmt(focusedQuote.change)} ({focusedQuote.change > 0 ? "+" : ""}{fmt(focusedQuote.changePct)}%)
                  </span>
                </div>
                <div className="mkt-quote-head__ohlc">
                  {([["O", focusedQuote.open], ["H", focusedQuote.high], ["L", focusedQuote.low], ["PC", focusedQuote.prevClose]] as const).map(([k, v]) => (
                    <span key={k}><i>{k}</i> {fmt(v)}</span>
                  ))}
                  {lastVol > 0 && <span><i>Vol</i> {fmtCompact(lastVol)}</span>}
                </div>
              </div>

              <div className="mkt-intervals">
                {INTERVALS.map((iv) => (
                  <button
                    key={iv.key}
                    className={`mkt-interval${interval === iv.key ? " is-on" : ""}`}
                    onClick={() => setIntervalKey(iv.key)}
                  >
                    {iv.label}
                  </button>
                ))}
              </div>

              {!keySet ? (
                <div className="mkt-center__msg">Set <code>FINNHUB_API_KEY</code> in Settings for live charts.</div>
              ) : loadingChart ? (
                <div className="mkt-center__msg">Loading chart…</div>
              ) : candles.length < 2 ? (
                <div className="mkt-center__msg">No chart data for this interval.</div>
              ) : (
                <>
                  <CandleChart candles={candles} />
                  <RsiChart candles={candles} />
                </>
              )}
            </>
          ) : (
            <div className="mkt-center__msg">
              {offline ? "Engine offline — start the Max engine for live quotes."
                : "Select a symbol from the watchlist."}
            </div>
          )}
        </section>

        {/* Right rail: quotes + order book + time & sales */}
        <aside className="mkt-rail">
          {focusedQuote ? (
            <>
              <div className="mkt-panel mkt-quotes">
                <div className="mkt-panel__head">Quotes</div>
                <div className="mkt-quotes__grid">
                  {([["Open", focusedQuote.open], ["High", focusedQuote.high], ["Low", focusedQuote.low], ["Prev Close", focusedQuote.prevClose]] as const).map(([k, v]) => (
                    <div key={k} className="mkt-quotes__cell">
                      <span className="mkt-quotes__lbl">{k}</span>
                      <span className="mkt-quotes__val">{fmt(v)}</span>
                    </div>
                  ))}
                </div>
                {focusedQuote.high > 0 && focusedQuote.low > 0 && (
                  <div className="mkt-quotes__range" title={`Day range ${fmt(focusedQuote.low)}–${fmt(focusedQuote.high)}`}>
                    <span>{fmt(focusedQuote.low)}</span>
                    <div className="mkt-quotes__track">
                      <div
                        className="mkt-quotes__dot"
                        style={{ left: `${Math.max(0, Math.min(100, ((focusedQuote.price - focusedQuote.low) / ((focusedQuote.high - focusedQuote.low) || 1)) * 100))}%` }}
                      />
                    </div>
                    <span>{fmt(focusedQuote.high)}</span>
                  </div>
                )}
              </div>
              <OrderBook quote={focusedQuote} />
              <TimeSales tape={tape} />
            </>
          ) : (
            <div className="mkt-center__msg">—</div>
          )}
        </aside>
      </div>
    </div>
  );
}

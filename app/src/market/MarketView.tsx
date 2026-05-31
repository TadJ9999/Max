// Market view — improved Webull-inspired ticker board + collapsible AI panel.
// Layout: full-width board with a slide-in AI panel from the right (same
// pattern as OSINT chat). Sub-tabs: Board (ticker cards) | Summary (stats).

import { useCallback, useEffect, useRef, useState } from "react";
import {
  getBoard,
  getSources,
  getWatchlist,
  setWatchlist as putWatchlist,
  streamAnalyze,
  streamMarketChat,
  type ChatTurn,
  type MarketBoard,
  type Quote,
} from "./market";
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
    const { emit } = await import("@tauri-apps/api/event");
    await emit(name, payload);
  } catch { /* not in Tauri */ }
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

// ── Webull-style ticker card ───────────────────────────────────────────────
function TickerCard({ quote, onRemove }: { quote: Quote; onRemove: () => void }) {
  const dir = dirClass(quote.change);
  const sign = quote.change > 0 ? "+" : "";
  const changePct = Math.abs(quote.changePct);
  return (
    <div className={`mkt-card mkt-card--${dir}`}>
      <div className="mkt-card__left">
        <div className="mkt-card__sym">{quote.symbol}</div>
        {quote.name && <div className="mkt-card__name">{quote.name}</div>}
        <div className="mkt-card__vol">
          {quote.open > 0 && <span>O ${fmt(quote.open)}</span>}
          {quote.prevClose > 0 && <span className="mkt-card__sep">PC ${fmt(quote.prevClose)}</span>}
        </div>
      </div>
      <div className="mkt-card__right">
        <div className="mkt-card__price">${fmt(quote.price)}</div>
        <div className={`mkt-card__chg mkt-card__chg--${dir}`}>
          <span className="mkt-card__chg-abs">{sign}{fmt(quote.change)}</span>
          <span className={`mkt-card__chg-badge mkt-card__chg-badge--${dir}`}>
            {sign}{fmt(changePct)}%
          </span>
        </div>
        {quote.high > 0 && quote.low > 0 && <RangeBar quote={quote} />}
      </div>
      <button className="mkt-card__rm" onClick={onRemove} title={`Remove ${quote.symbol}`}>×</button>
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
  }, []);

  useEffect(() => {
    void refresh();
    const id = setInterval(() => void refresh(), POLL_MS);
    return () => clearInterval(id);
  }, [refresh]);

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

  const quotes  = board?.quotes ?? [];
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
          <button
            className={`market__panel-toggle${panelOpen ? " is-on" : ""}`}
            onClick={() => setPanelOpen((v) => !v)}
            title="AI Analysis & Chat"
          >
            ✦ AI
          </button>
          {onClose && (
            <button className="market__btn market__btn--close" onClick={onClose}>×</button>
          )}
        </div>
      </header>

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

            <div className="market__cards">
              {quotes.length === 0 && !loading && (
                <div className="market__empty">No quotes yet.</div>
              )}
              {quotes.map((q) => (
                <TickerCard key={q.symbol} quote={q} onRemove={() => onRemove(q.symbol)} />
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

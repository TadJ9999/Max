// Polymarket prediction market board.
// Layout: category tabs | market list | detail panel | AI Ingest + Chat panel.

import { useCallback, useEffect, useRef, useState } from "react";
import {
  CATEGORIES,
  getBoard,
  getMarketNews,
  getMarkets,
  getOrderBook,
  getPortfolio,
  getPriceHistory,
  getWatchlistMarkets,
  setWatchlist,
  streamChat,
  streamIngest,
  streamPrices,
  type Category,
  type ChatTurn,
  type MarketEvent,
  type OrderBook,
  type PolyMarket,
  type PolyPortfolio,
  type PricePoint,
} from "./polymarket";
import { PriceChart } from "./PriceChart";
import { OrderBookPanel } from "./OrderBookPanel";
import { MarkdownView } from "../components/MarkdownView";
import { CopyButton } from "../components/CopyButton";
import "./Polymarket.css";

type Interval = "1d" | "1w" | "1m" | "max";

function fmtVol(n: number): string {
  if (n >= 1_000_000) return `$${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `$${(n / 1_000).toFixed(0)}k`;
  return `$${n.toFixed(0)}`;
}

function fmtDate(iso: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return d.toLocaleDateString(undefined, { month: "short", day: "numeric", year: "2-digit" });
}

function probColor(name: string): string {
  const n = name.toLowerCase();
  if (n === "yes" || n === "true") return "yes";
  if (n === "no" || n === "false") return "no";
  return "other";
}

// ── mini market card ──────────────────────────────────────────────────────────
function MarketCard({
  market,
  selected,
  pinned,
  onSelect,
  onTogglePin,
}: {
  market: PolyMarket;
  selected: boolean;
  pinned: boolean;
  onSelect: () => void;
  onTogglePin: (e: React.MouseEvent) => void;
}) {
  const yesPct = (market.yesPrice * 100).toFixed(0);

  return (
    <div
      className={`poly__card${selected ? " is-selected" : ""}`}
      onClick={onSelect}
    >
      <button
        className={`poly__star${pinned ? " is-pinned" : ""}`}
        onClick={onTogglePin}
        title={pinned ? "Unpin" : "Pin to watchlist"}
      >
        {pinned ? "★" : "☆"}
      </button>
      {market.category && <div className="poly__card-cat">{market.category}</div>}
      <div className="poly__card-question">{market.question}</div>
      <div className="poly__card-gauge-row">
        <span className="poly__gauge-label poly__gauge-label--yes">{yesPct}%</span>
        <div className="poly__gauge-track">
          <div
            className="poly__gauge-fill"
            style={{ width: `${yesPct}%` }}
          />
        </div>
        <span className="poly__gauge-label poly__gauge-label--no">{(100 - Number(yesPct))}%</span>
      </div>
      <div className="poly__card-meta">
        {market.volume24hr > 0 && (
          <span className="poly__card-vol">Vol {fmtVol(market.volume24hr)}</span>
        )}
        {market.endDate && (
          <span className="poly__card-end">Ends {fmtDate(market.endDate)}</span>
        )}
      </div>
    </div>
  );
}

// ── News feed for a market ────────────────────────────────────────────────────
function MarketNewsFeed({ conditionId }: { conditionId: string }) {
  const [events, setEvents] = useState<MarketEvent[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    void getMarketNews(conditionId).then((evs) => {
      setEvents(evs);
      setLoading(false);
    });
  }, [conditionId]);

  if (loading) return <div className="poly__news-loading">Loading news…</div>;
  if (events.length === 0) return null;

  return (
    <div className="poly__news">
      <div className="poly__ob-header">Related Events</div>
      <div className="poly__news-list">
        {events.map((ev, i) => (
          <div key={i} className="poly__news-item">
            <div className="poly__news-title">
              {ev.article_url ? (
                <a
                  className="poly__news-link"
                  href={ev.article_url}
                  target="_blank"
                  rel="noreferrer"
                  onClick={async (e) => {
                    e.preventDefault();
                    try {
                      const m = await import("@tauri-apps/plugin-opener");
                      const openFn = (m as unknown as Record<string, unknown>).openUrl ?? (m as unknown as Record<string, unknown>).open;
                      if (typeof openFn === "function") await (openFn as (u: string) => Promise<void>)(ev.article_url!);
                      else window.open(ev.article_url!, "_blank");
                    } catch {
                      window.open(ev.article_url!, "_blank");
                    }
                  }}
                >
                  {ev.title}
                </a>
              ) : (
                ev.title
              )}
            </div>
            {ev.description && (
              <div className="poly__news-desc">{ev.description.slice(0, 180)}</div>
            )}
            {ev.start_date && (
              <div className="poly__news-date">{new Date(ev.start_date).toLocaleDateString()}</div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

// ── detail panel ─────────────────────────────────────────────────────────────
function DetailPanel({
  market,
  history,
  chartLoading,
  bookLoading,
  interval,
  onInterval,
  book,
  livePrice,
  streaming,
}: {
  market: PolyMarket;
  history: PricePoint[];
  chartLoading: boolean;
  bookLoading: boolean;
  interval: Interval;
  onInterval: (i: Interval) => void;
  book: OrderBook | null;
  livePrice: number | null;
  streaming: boolean;
}) {
  const yesToken = market.outcomes.find((o) => o.name.toLowerCase() === "yes")?.tokenId ?? null;

  return (
    <div className="poly__detail">
      {market.category && <div className="poly__detail-cat">{market.category}</div>}
      <div className="poly__detail-question">{market.question}</div>
      {market.description && (
        <div className="poly__detail-desc">{market.description.slice(0, 400)}</div>
      )}

      <div className="poly__prob-bars">
        {market.outcomes.map((o) => {
          const kind = probColor(o.name);
          return (
            <div className="poly__prob-row" key={o.name}>
              <span className="poly__prob-name">{o.name}</span>
              <div className="poly__prob-track">
                <div
                  className={`poly__prob-fill-${kind}`}
                  style={{ width: `${(o.price * 100).toFixed(1)}%` }}
                />
              </div>
              <span className={`poly__prob-pct poly__prob-pct--${kind}`}>
                {(o.price * 100).toFixed(1)}%
              </span>
            </div>
          );
        })}
      </div>

      <div className="poly__stats">
        {market.volume24hr > 0 && (
          <div className="poly__stat">
            <span className="poly__stat-label">24h Vol</span>
            <span className="poly__stat-value">{fmtVol(market.volume24hr)}</span>
          </div>
        )}
        {market.volume > 0 && (
          <div className="poly__stat">
            <span className="poly__stat-label">Total Vol</span>
            <span className="poly__stat-value">{fmtVol(market.volume)}</span>
          </div>
        )}
        {market.liquidity > 0 && (
          <div className="poly__stat">
            <span className="poly__stat-label">Liquidity</span>
            <span className="poly__stat-value">{fmtVol(market.liquidity)}</span>
          </div>
        )}
        {market.endDate && (
          <div className="poly__stat">
            <span className="poly__stat-label">Resolves</span>
            <span className="poly__stat-value">{fmtDate(market.endDate)}</span>
          </div>
        )}
      </div>

      <div className="poly__chart-header">
        <span className="poly__chart-title">
          YES Probability
          {streaming && (
            <span className="poly__live" title="Live CLOB price stream">
              <span className="poly__live-dot" />
              {livePrice != null ? ` ${(livePrice * 100).toFixed(1)}¢` : " LIVE"}
            </span>
          )}
        </span>
        <div className="poly__intervals">
          {(["1d", "1w", "1m", "max"] as Interval[]).map((iv) => (
            <button
              key={iv}
              className={`poly__interval${interval === iv ? " is-active" : ""}`}
              onClick={() => onInterval(iv)}
            >
              {iv.toUpperCase()}
            </button>
          ))}
        </div>
      </div>
      <div className="poly__chart-wrap">
        {chartLoading ? (
          <div className="poly__chart-loading">Loading…</div>
        ) : (
          <PriceChart points={history} width={360} height={110} />
        )}
      </div>

      {yesToken && (
        <>
          <div className="poly__ob-header">Order Book (YES token)</div>
          <OrderBookPanel book={book} loading={bookLoading} />
        </>
      )}

      <MarketNewsFeed conditionId={market.conditionId} />
    </div>
  );
}

// ── AI ingest panel ───────────────────────────────────────────────────────────
function IngestPanel() {
  const [output, setOutput] = useState("");
  const [busy, setBusy] = useState(false);
  const abortRef = useRef<AbortController | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);

  const run = async () => {
    if (busy) return;
    abortRef.current?.abort();
    abortRef.current = new AbortController();
    setOutput("");
    setBusy(true);
    try {
      for await (const chunk of streamIngest(abortRef.current.signal)) {
        setOutput((p) => p + chunk);
        if (scrollRef.current) {
          scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
        }
      }
    } catch (e: unknown) {
      if ((e as Error).name !== "AbortError") {
        setOutput((p) => p + "\n\n[Error: " + (e as Error).message + "]");
      }
    } finally {
      setBusy(false);
    }
  };

  useEffect(() => () => abortRef.current?.abort(), []);

  return (
    <div className="poly__ingest">
      {!output && !busy && (
        <div className="poly__ingest-trigger">
          <p>AI market brief on the live prediction board</p>
          <button className="poly__ingest-run" onClick={run}>
            Ingest Markets
          </button>
        </div>
      )}
      {busy && !output && <div className="poly__ingest-status">Analyzing markets…</div>}
      {output && (
        <>
          <div className="poly__ingest-output" ref={scrollRef}>
            <MarkdownView source={output} />
          </div>
          <div className="poly__ingest-copy">
            <CopyButton text={output} />
          </div>
          <button className="poly__ingest-run" onClick={run} disabled={busy}>
            {busy ? "Running…" : "Re-run"}
          </button>
        </>
      )}
    </div>
  );
}

// ── AI chat panel ─────────────────────────────────────────────────────────────
function ChatPanel() {
  const [history, setHistory] = useState<ChatTurn[]>([]);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const abortRef = useRef<AbortController | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);

  const send = async () => {
    const text = draft.trim();
    if (!text || busy) return;
    const userTurn: ChatTurn = { role: "user", content: text };
    setHistory((h) => [...h, userTurn]);
    setDraft("");
    setBusy(true);
    abortRef.current?.abort();
    abortRef.current = new AbortController();

    const assistantTurn: ChatTurn = { role: "assistant", content: "" };
    setHistory((h) => [...h, assistantTurn]);

    try {
      const allHistory = [...history, userTurn, assistantTurn];
      for await (const chunk of streamChat(allHistory, abortRef.current.signal)) {
        setHistory((h) => {
          const next = [...h];
          next[next.length - 1] = {
            ...next[next.length - 1],
            content: next[next.length - 1].content + chunk,
          };
          return next;
        });
        if (scrollRef.current) {
          scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
        }
      }
    } catch (e: unknown) {
      if ((e as Error).name !== "AbortError") {
        setHistory((h) => {
          const next = [...h];
          next[next.length - 1] = {
            ...next[next.length - 1],
            content: "[Error: " + (e as Error).message + "]",
          };
          return next;
        });
      }
    } finally {
      setBusy(false);
    }
  };

  useEffect(() => () => abortRef.current?.abort(), []);

  return (
    <div className="poly__chat">
      <div className="poly__chat-history" ref={scrollRef}>
        {history.length === 0 && (
          <div className="poly__chat-hint">
            Ask about prediction markets, probabilities, or events…
          </div>
        )}
        {history.map((turn, i) => (
          <div key={i} className={`poly__chat-msg poly__chat-msg--${turn.role}`}>
            {turn.role === "assistant" ? (
              <MarkdownView source={turn.content} />
            ) : (
              turn.content
            )}
          </div>
        ))}
      </div>
      <div className="poly__chat-input-row">
        <textarea
          className="poly__chat-input"
          rows={1}
          placeholder="Ask about markets…"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              void send();
            }
          }}
          disabled={busy}
        />
        <button className="poly__chat-send" onClick={send} disabled={busy || !draft.trim()}>
          {busy ? "…" : "Send"}
        </button>
      </div>
    </div>
  );
}

// ── read-only portfolio panel (by wallet address) ─────────────────────────────
const PORTFOLIO_ADDR_KEY = "max.polymarket.wallet";

function PortfolioPanel() {
  const [address, setAddress] = useState(() => localStorage.getItem(PORTFOLIO_ADDR_KEY) ?? "");
  const [portfolio, setPortfolio] = useState<PolyPortfolio | null>(null);
  const [loading, setLoading] = useState(false);
  const [loaded, setLoaded] = useState(false);

  const load = useCallback(async (addr: string) => {
    const a = addr.trim();
    if (!a) return;
    setLoading(true);
    setLoaded(true);
    localStorage.setItem(PORTFOLIO_ADDR_KEY, a);
    setPortfolio(await getPortfolio(a));
    setLoading(false);
  }, []);

  // Auto-load a previously-saved address on mount.
  useEffect(() => {
    if (address.trim()) void load(address);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const usd = (n: number) => `${n < 0 ? "-" : ""}$${Math.abs(n).toLocaleString(undefined, { maximumFractionDigits: 2 })}`;
  const sum = portfolio?.summary;
  const pnlDir = sum ? (sum.cashPnl > 0 ? "up" : sum.cashPnl < 0 ? "down" : "flat") : "flat";

  return (
    <div className="poly__portfolio">
      <div className="poly__pf-bar">
        <input
          className="poly__pf-input"
          placeholder="Wallet address (0x…)"
          value={address}
          spellCheck={false}
          onChange={(e) => setAddress(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && void load(address)}
        />
        <button className="poly__pf-load" onClick={() => void load(address)} disabled={loading || !address.trim()}>
          {loading ? "…" : "Load"}
        </button>
      </div>
      <div className="poly__pf-hint">Read-only — open positions &amp; P&amp;L from Polymarket's public Data API.</div>

      {sum && portfolio && portfolio.count > 0 && (
        <div className="poly__pf-summary">
          <div className="poly__pf-stat">
            <span className="poly__pf-stat-lbl">Value</span>
            <span className="poly__pf-stat-val">{usd(sum.currentValue)}</span>
          </div>
          <div className="poly__pf-stat">
            <span className="poly__pf-stat-lbl">Cost</span>
            <span className="poly__pf-stat-val">{usd(sum.initialValue)}</span>
          </div>
          <div className={`poly__pf-stat poly__pf-stat--${pnlDir}`}>
            <span className="poly__pf-stat-lbl">P&amp;L</span>
            <span className="poly__pf-stat-val">{usd(sum.cashPnl)} ({sum.percentPnl > 0 ? "+" : ""}{sum.percentPnl}%)</span>
          </div>
        </div>
      )}

      <div className="poly__pf-list">
        {loading ? (
          <div className="poly__loading">Loading positions…</div>
        ) : !loaded ? (
          <div className="poly__empty">Enter a wallet address to view its positions.</div>
        ) : !portfolio || portfolio.count === 0 ? (
          <div className="poly__empty">No open positions for this address.</div>
        ) : (
          portfolio.positions.map((p, i) => {
            const dir = p.cashPnl > 0 ? "up" : p.cashPnl < 0 ? "down" : "flat";
            return (
              <div key={`${p.conditionId}-${i}`} className="poly__pf-pos">
                <div className="poly__pf-pos-title">{p.title}</div>
                <div className="poly__pf-pos-row">
                  <span className={`poly__pf-outcome poly__pf-outcome--${probColor(p.outcome)}`}>{p.outcome}</span>
                  <span className="poly__pf-pos-meta">{p.size.toLocaleString(undefined, { maximumFractionDigits: 0 })} sh @ {(p.avgPrice * 100).toFixed(0)}¢ → {(p.curPrice * 100).toFixed(0)}¢</span>
                  <span className={`poly__pf-pnl poly__pf-pnl--${dir}`}>
                    {usd(p.currentValue)} · {p.percentPnl > 0 ? "+" : ""}{p.percentPnl}%
                  </span>
                </div>
              </div>
            );
          })
        )}
      </div>
    </div>
  );
}

// ── main view ────────────────────────────────────────────────────────────────
export function PolymarketView() {
  const [category, setCategory] = useState<Category>("All");
  const [markets, setMarkets] = useState<PolyMarket[]>([]);
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState<PolyMarket | null>(null);
  const [watchlist, setWatchlistState] = useState<string[]>([]);
  const [updated, setUpdated] = useState<string | null>(null);

  // detail state
  const [history, setHistory] = useState<PricePoint[]>([]);
  const [chartLoading, setChartLoading] = useState(false);
  const [book, setBook] = useState<OrderBook | null>(null);
  const [bookLoading, setBookLoading] = useState(false);
  const [interval, setIntervalState] = useState<Interval>("1w");

  // AI panel
  const [aiTab, setAiTab] = useState<"ingest" | "chat">("ingest");

  // Markets vs read-only portfolio view
  const [view, setView] = useState<"markets" | "portfolio">("markets");

  // Live CLOB price stream for the selected market
  const [liveYes, setLiveYes] = useState<number | null>(null);
  const [streaming, setStreaming] = useState(false);

  // load markets by category
  const loadMarkets = useCallback(async (cat: Category) => {
    setLoading(true);
    setSelected(null);
    try {
      if (cat === "Watchlist") {
        const res = await getWatchlistMarkets();
        setMarkets(res.markets);
        setWatchlistState(res.watchlist);
      } else {
        const board = cat === "All"
          ? await getBoard()
          : null;
        if (board) {
          setMarkets(board.markets);
          setUpdated(board.updated);
        } else {
          const ms = await getMarkets({ category: cat === "All" ? undefined : cat, limit: 50 });
          setMarkets(ms);
        }
      }
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadMarkets(category);
    // poll every 2 min
    const id = setInterval(() => void loadMarkets(category), 120_000);
    return () => clearInterval(id);
  }, [category, loadMarkets]);

  // load chart + order book when selection changes
  useEffect(() => {
    if (!selected) return;
    setHistory([]);
    setBook(null);
    setChartLoading(true);
    setBookLoading(true);

    void getPriceHistory(selected.conditionId, interval).then((pts) => {
      setHistory(pts);
      setChartLoading(false);
    });

    const yesToken = selected.outcomes.find((o) => o.name.toLowerCase() === "yes")?.tokenId;
    if (yesToken) {
      void getOrderBook(yesToken).then((b) => {
        setBook(b);
        setBookLoading(false);
      });
    } else {
      setBookLoading(false);
    }
  }, [selected]);

  // reload chart when interval changes
  useEffect(() => {
    if (!selected) return;
    setChartLoading(true);
    void getPriceHistory(selected.conditionId, interval).then((pts) => {
      setHistory(pts);
      setChartLoading(false);
    });
  }, [interval, selected]);

  // Live CLOB price/order-book stream for the selected market. Reconnects on drop.
  useEffect(() => {
    setLiveYes(null);
    setStreaming(false);
    if (!selected) return;
    const yesToken =
      selected.outcomes.find((o) => o.name.toLowerCase() === "yes")?.tokenId ??
      selected.outcomes[0]?.tokenId ?? null;
    const tokenIds = selected.outcomes.map((o) => o.tokenId).filter((t): t is string => !!t);
    if (tokenIds.length === 0) return;
    const ctrl = new AbortController();
    let alive = true;
    void (async () => {
      while (alive) {
        try {
          for await (const ev of streamPrices(tokenIds, ctrl.signal)) {
            if (ev.type === "error" || ev.type === "empty") { setStreaming(false); break; }
            setStreaming(true);
            if (ev.type === "book" && ev.tokenId === yesToken) {
              setBook({ bids: ev.bids, asks: ev.asks });
            } else if (ev.type === "trade" && ev.tokenId === yesToken) {
              setLiveYes(ev.price);
            }
          }
        } catch { /* stream dropped */ }
        if (!alive) break;
        setStreaming(false);
        await new Promise((r) => setTimeout(r, 3000)); // reconnect backoff
      }
    })();
    return () => { alive = false; ctrl.abort(); };
  }, [selected]);

  const togglePin = async (market: PolyMarket, e: React.MouseEvent) => {
    e.stopPropagation();
    const next = watchlist.includes(market.conditionId)
      ? watchlist.filter((id) => id !== market.conditionId)
      : [...watchlist, market.conditionId];
    const confirmed = await setWatchlist(next);
    setWatchlistState(confirmed);
  };

  return (
    <div className="poly">
      <div className="poly__topbar">
        <span className="poly__title">Ψ POLYMARKET</span>
        <div className="poly__view-toggle">
          <button className={`poly__view-btn${view === "markets" ? " is-active" : ""}`}
            onClick={() => setView("markets")}>Markets</button>
          <button className={`poly__view-btn${view === "portfolio" ? " is-active" : ""}`}
            onClick={() => setView("portfolio")}>💼 Portfolio</button>
        </div>
        {view === "markets" && updated && (
          <span className="poly__updated">
            Updated {new Date(updated).toLocaleTimeString()}
          </span>
        )}
      </div>

      {view === "portfolio" ? (
        <PortfolioPanel />
      ) : (
      <>
      <div className="poly__cats">
        {CATEGORIES.map((cat) => (
          <button
            key={cat}
            className={`poly__cat${category === cat ? " is-active" : ""}`}
            onClick={() => setCategory(cat)}
          >
            {cat === "Watchlist" ? "★ Watchlist" : cat}
          </button>
        ))}
      </div>

      <div className="poly__body">
        {/* market list */}
        <div className="poly__list">
          {loading ? (
            <div className="poly__loading">Loading markets…</div>
          ) : markets.length === 0 ? (
            <div className="poly__empty">No markets found</div>
          ) : (
            markets.map((m) => (
              <MarketCard
                key={m.conditionId}
                market={m}
                selected={selected?.conditionId === m.conditionId}
                pinned={watchlist.includes(m.conditionId)}
                onSelect={() => setSelected(m)}
                onTogglePin={(e) => void togglePin(m, e)}
              />
            ))
          )}
        </div>

        {/* detail panel */}
        {selected ? (
          <DetailPanel
            market={selected}
            history={history}
            chartLoading={chartLoading}
            bookLoading={bookLoading}
            interval={interval}
            onInterval={setIntervalState}
            book={book}
            livePrice={liveYes}
            streaming={streaming}
          />
        ) : (
          <div className="poly__detail">
            <div className="poly__detail-placeholder">
              Select a market to see details
            </div>
          </div>
        )}

        {/* AI panel */}
        <div className="poly__ai">
          <div className="poly__ai-tabs">
            <button
              className={`poly__ai-tab${aiTab === "ingest" ? " is-active" : ""}`}
              onClick={() => setAiTab("ingest")}
            >
              Ingest
            </button>
            <button
              className={`poly__ai-tab${aiTab === "chat" ? " is-active" : ""}`}
              onClick={() => setAiTab("chat")}
            >
              Chat
            </button>
          </div>
          <div className="poly__ai-body">
            {aiTab === "ingest" ? <IngestPanel /> : <ChatPanel />}
          </div>
        </div>
      </div>
      </>
      )}
    </div>
  );
}

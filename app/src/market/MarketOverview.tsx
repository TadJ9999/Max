// Market Overview — the Webull-style "full market" board that complements the
// single-symbol Terminal. Shows market breadth, top movers, the watchlist as
// live cards (each with a mini daily sparkline), and recent market news.
// Clicking a card opens that symbol in the Terminal. Data is passed down from
// MarketView (live-overlaid quotes + news) so there's a single source of truth;
// sparklines are fetched here (keyless Yahoo candles) and cached per symbol.

import { useEffect, useRef, useState } from "react";
import { getCandles, type Candle, type NewsItem, type Quote } from "./market";

const UP = "#22c55e";
const DOWN = "#ef4444";
const FLAT = "#6b7c93";

function fmt(n: number, dec = 2): string {
  return n.toLocaleString(undefined, { minimumFractionDigits: dec, maximumFractionDigits: dec });
}

function dirColor(change: number): string {
  return change > 0 ? UP : change < 0 ? DOWN : FLAT;
}

// ── Mini sparkline over a symbol's recent daily closes ─────────────────────
function Sparkline({ candles, color }: { candles: Candle[]; color: string }) {
  const W = 96, H = 30, P = 2;
  if (candles.length < 2) return <div className="mkt-card__spark mkt-card__spark--empty" />;
  const closes = candles.map((c) => c.c);
  const min = Math.min(...closes), max = Math.max(...closes);
  const range = max - min || 1;
  const step = (W - P * 2) / (closes.length - 1);
  const pts = closes
    .map((c, i) => `${(P + i * step).toFixed(1)},${(P + (1 - (c - min) / range) * (H - P * 2)).toFixed(1)}`)
    .join(" ");
  return (
    <svg className="mkt-card__spark" viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none">
      <polyline points={pts} fill="none" stroke={color} strokeWidth="1.4" strokeLinejoin="round" strokeLinecap="round" />
    </svg>
  );
}

function MoverList({ title, items, onSelect }: { title: string; items: Quote[]; onSelect: (s: string) => void }) {
  return (
    <div className="mkt-movers">
      <div className="mkt-movers__head">{title}</div>
      {items.length === 0 && <div className="mkt-movers__empty">—</div>}
      {items.map((q) => (
        <button key={q.symbol} className="mkt-movers__row" onClick={() => onSelect(q.symbol)}>
          <span className="mkt-movers__sym">{q.symbol}</span>
          <span className="mkt-movers__px">{fmt(q.price)}</span>
          <span className="mkt-movers__chg" style={{ color: dirColor(q.change) }}>
            {q.changePct > 0 ? "+" : ""}{fmt(q.changePct)}%
          </span>
        </button>
      ))}
    </div>
  );
}

export function MarketOverview({
  quotes,
  news,
  loading,
  offline,
  keySet,
  add,
  setAdd,
  onAdd,
  onRemove,
  onSelect,
}: {
  quotes: Quote[];
  news: NewsItem[];
  loading: boolean;
  offline: boolean;
  keySet: boolean;
  add: string;
  setAdd: (v: string) => void;
  onAdd: () => void;
  onRemove: (sym: string) => void;
  onSelect: (sym: string) => void;
}) {
  // Per-symbol daily candles for the card sparklines (keyless Yahoo). Fetched
  // once per symbol and kept; refreshed when the symbol set changes.
  const [sparks, setSparks] = useState<Record<string, Candle[]>>({});
  const fetchedRef = useRef<Set<string>>(new Set());

  // Key on the symbol SET (not the quotes array, whose reference changes on
  // every live price tick) so an in-flight sparkline fetch isn't aborted by a
  // tick-driven re-render before its result lands.
  const symbolsKey = quotes.map((q) => q.symbol).join(",");

  useEffect(() => {
    const symbols = symbolsKey ? symbolsKey.split(",") : [];
    const missing = symbols.filter((s) => !fetchedRef.current.has(s));
    if (missing.length === 0) return;
    missing.forEach((s) => fetchedRef.current.add(s));
    let alive = true;
    void Promise.all(
      missing.map(async (sym) => {
        const c = await getCandles(sym, "D", 40);
        return [sym, c] as const;
      }),
    ).then((pairs) => {
      if (!alive) return;
      setSparks((prev) => {
        const next = { ...prev };
        for (const [sym, c] of pairs) next[sym] = c;
        return next;
      });
    });
    return () => { alive = false; };
  }, [symbolsKey]);

  // Breadth + movers (computed client-side from the live board).
  const up = quotes.filter((q) => q.change > 0).length;
  const down = quotes.filter((q) => q.change < 0).length;
  const flat = quotes.length - up - down;
  const avg = quotes.length ? quotes.reduce((s, q) => s + q.changePct, 0) / quotes.length : 0;
  const byChg = [...quotes].sort((a, b) => b.changePct - a.changePct);
  const gainers = byChg.filter((q) => q.change > 0).slice(0, 5);
  const losers = byChg.filter((q) => q.change < 0).reverse().slice(0, 5);

  if (offline) {
    return <div className="mkt-center__msg">Engine offline — start the Max engine for the live market board.</div>;
  }
  if (!keySet) {
    return <div className="mkt-center__msg">Set <code>FINNHUB_API_KEY</code> in Settings for the live market board.</div>;
  }

  return (
    <div className="mkt-overview">
      {/* breadth banner */}
      <div className="mkt-breadth">
        <div className="mkt-breadth__stat">
          <span className="mkt-breadth__lbl">Advancers</span>
          <span className="mkt-breadth__val" style={{ color: UP }}>{up}</span>
        </div>
        <div className="mkt-breadth__stat">
          <span className="mkt-breadth__lbl">Decliners</span>
          <span className="mkt-breadth__val" style={{ color: DOWN }}>{down}</span>
        </div>
        <div className="mkt-breadth__stat">
          <span className="mkt-breadth__lbl">Unchanged</span>
          <span className="mkt-breadth__val" style={{ color: FLAT }}>{flat}</span>
        </div>
        <div className="mkt-breadth__stat">
          <span className="mkt-breadth__lbl">Avg move</span>
          <span className="mkt-breadth__val" style={{ color: dirColor(avg) }}>{avg > 0 ? "+" : ""}{fmt(avg)}%</span>
        </div>
        <div className="mkt-breadth__add">
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
      </div>

      <div className="mkt-overview__body">
        {/* watchlist cards */}
        <div className="mkt-cards">
          {loading && quotes.length === 0 && <div className="mkt-center__msg">Loading board…</div>}
          {quotes.map((q) => (
            <div key={q.symbol} className="mkt-card" onClick={() => onSelect(q.symbol)} title={`Open ${q.symbol} in Terminal`}>
              <button
                className="mkt-card__rm"
                onClick={(e) => { e.stopPropagation(); onRemove(q.symbol); }}
                title={`Remove ${q.symbol}`}
              >×</button>
              <div className="mkt-card__top">
                <span className="mkt-card__sym">{q.symbol}</span>
                {q.name && <span className="mkt-card__name">{q.name}</span>}
              </div>
              <Sparkline candles={sparks[q.symbol] ?? []} color={dirColor(q.change)} />
              <div className="mkt-card__nums">
                <span className="mkt-card__price">{fmt(q.price)}</span>
                <span className="mkt-card__chg" style={{ color: dirColor(q.change) }}>
                  {q.change > 0 ? "+" : ""}{fmt(q.change)} ({q.change > 0 ? "+" : ""}{fmt(q.changePct)}%)
                </span>
              </div>
            </div>
          ))}
        </div>

        {/* right column: movers + news */}
        <aside className="mkt-overview__side">
          <MoverList title="Top Gainers" items={gainers} onSelect={onSelect} />
          <MoverList title="Top Losers" items={losers} onSelect={onSelect} />
          <div className="mkt-news">
            <div className="mkt-news__head">Market News</div>
            {news.length === 0 && <div className="mkt-movers__empty">No headlines.</div>}
            {news.map((n, i) => (
              <a key={i} className="mkt-news__item" href={n.url ?? "#"} target="_blank" rel="noreferrer">
                <span className="mkt-news__headline">{n.headline}</span>
                <span className="mkt-news__source">{n.source ?? ""}</span>
              </a>
            ))}
          </div>
        </aside>
      </div>
    </div>
  );
}

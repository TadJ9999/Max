// Order book bid/ask depth ladder for one outcome token.

import type { OrderBook } from "./polymarket";

interface Props {
  book: OrderBook | null;
  loading?: boolean;
}

function Level({
  price,
  size,
  side,
  maxSize,
}: {
  price: number;
  size: number;
  side: "bid" | "ask";
  maxSize: number;
}) {
  const pct = maxSize > 0 ? (size / maxSize) * 100 : 0;
  const cls = side === "bid" ? "ob__bar--bid" : "ob__bar--ask";
  return (
    <div className="ob__row">
      <div className="ob__bar-wrap">
        <div className={`ob__bar ${cls}`} style={{ width: `${pct.toFixed(1)}%` }} />
      </div>
      <span className="ob__price">{(price * 100).toFixed(1)}¢</span>
      <span className="ob__size">{size.toLocaleString(undefined, { maximumFractionDigits: 0 })}</span>
    </div>
  );
}

export function OrderBookPanel({ book, loading }: Props) {
  if (loading) {
    return <div className="ob ob--empty">Loading order book…</div>;
  }
  if (!book || (book.bids.length === 0 && book.asks.length === 0)) {
    return <div className="ob ob--empty">No order book data</div>;
  }

  const topBids = book.bids.slice(0, 8);
  const topAsks = book.asks.slice(0, 8);
  const maxBidSize = Math.max(...topBids.map((l) => l.size), 1);
  const maxAskSize = Math.max(...topAsks.map((l) => l.size), 1);

  const spread =
    book.asks.length > 0 && book.bids.length > 0
      ? ((book.asks[0].price - book.bids[0].price) * 100).toFixed(1)
      : null;

  return (
    <div className="ob">
      <div className="ob__header">
        <span className="ob__side-label ob__side-label--bid">Bids</span>
        {spread !== null && (
          <span className="ob__spread">Spread {spread}¢</span>
        )}
        <span className="ob__side-label ob__side-label--ask">Asks</span>
      </div>
      <div className="ob__cols">
        <div className="ob__col ob__col--bids">
          {topBids.map((lvl, i) => (
            <Level key={i} price={lvl.price} size={lvl.size} side="bid" maxSize={maxBidSize} />
          ))}
        </div>
        <div className="ob__col ob__col--asks">
          {topAsks.map((lvl, i) => (
            <Level key={i} price={lvl.price} size={lvl.size} side="ask" maxSize={maxAskSize} />
          ))}
        </div>
      </div>
    </div>
  );
}

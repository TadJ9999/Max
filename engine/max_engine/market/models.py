"""Shared Market data shapes (normalized from the quote provider)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class Quote:
    """One stock's live snapshot, normalized from the provider."""

    symbol: str
    name: str | None = None  # company name, if known
    price: float = 0.0  # current price
    change: float = 0.0  # absolute change vs previous close
    change_pct: float = 0.0  # percent change vs previous close
    high: float = 0.0  # day high
    low: float = 0.0  # day low
    open: float = 0.0  # day open
    prev_close: float = 0.0  # previous close
    ts: datetime | None = None  # quote timestamp

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "name": self.name,
            "price": round(self.price, 4),
            "change": round(self.change, 4),
            "changePct": round(self.change_pct, 4),
            "high": round(self.high, 4),
            "low": round(self.low, 4),
            "open": round(self.open, 4),
            "prevClose": round(self.prev_close, 4),
            "ts": self.ts.isoformat() if self.ts else None,
        }


@dataclass
class MarketBoard:
    """The full payload served to the client."""

    updated: datetime
    quotes: list[Quote] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "updated": self.updated.isoformat(),
            "count": len(self.quotes),
            "quotes": [q.to_dict() for q in self.quotes],
        }

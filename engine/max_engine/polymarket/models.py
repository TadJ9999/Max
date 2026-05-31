"""Polymarket data shapes (normalized from Gamma + CLOB APIs)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class Outcome:
    name: str
    price: float  # 0..1 probability
    token_id: str | None = None


@dataclass
class PricePoint:
    t: int    # unix timestamp
    p: float  # probability 0..1


@dataclass
class OrderBookLevel:
    price: float
    size: float


@dataclass
class OrderBook:
    bids: list[OrderBookLevel] = field(default_factory=list)
    asks: list[OrderBookLevel] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "bids": [{"price": lvl.price, "size": lvl.size} for lvl in self.bids[:20]],
            "asks": [{"price": lvl.price, "size": lvl.size} for lvl in self.asks[:20]],
        }


@dataclass
class Market:
    condition_id: str
    question: str
    slug: str = ""
    category: str = ""
    description: str = ""
    outcomes: list[Outcome] = field(default_factory=list)
    volume: float = 0.0
    volume_24hr: float = 0.0
    liquidity: float = 0.0
    end_date: str | None = None
    active: bool = True
    closed: bool = False
    image: str | None = None

    @property
    def yes_price(self) -> float:
        for o in self.outcomes:
            if o.name.lower() in ("yes", "true"):
                return o.price
        return self.outcomes[0].price if self.outcomes else 0.0

    def to_dict(self) -> dict:
        return {
            "conditionId": self.condition_id,
            "question": self.question,
            "slug": self.slug,
            "category": self.category,
            "description": self.description,
            "outcomes": [
                {"name": o.name, "price": round(o.price, 4), "tokenId": o.token_id}
                for o in self.outcomes
            ],
            "yesPrice": round(self.yes_price, 4),
            "volume": round(self.volume, 2),
            "volume24hr": round(self.volume_24hr, 2),
            "liquidity": round(self.liquidity, 2),
            "endDate": self.end_date,
            "active": self.active,
            "closed": self.closed,
            "image": self.image,
        }


@dataclass
class PolymarketBoard:
    updated: datetime
    markets: list[Market] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "updated": self.updated.isoformat(),
            "count": len(self.markets),
            "markets": [m.to_dict() for m in self.markets],
        }

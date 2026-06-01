"""Polymarket — prediction market board (Gamma + CLOB APIs, no key required)."""

from __future__ import annotations

from .models import Market, OrderBook, Outcome, PolymarketBoard, PricePoint
from .service import PolymarketService
from .stream import normalize, stream_prices

__all__ = [
    "PolymarketService",
    "Market",
    "Outcome",
    "PricePoint",
    "OrderBook",
    "PolymarketBoard",
    "stream_prices",
    "normalize",
]

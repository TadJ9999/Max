"""Market — live US-stock board (Finnhub) with on-demand AI analysis."""

from __future__ import annotations

from .finnhub import DEFAULT_WATCHLIST
from .models import MarketBoard, Quote
from .service import MarketService, board_digest

__all__ = ["MarketService", "Quote", "MarketBoard", "DEFAULT_WATCHLIST", "board_digest"]

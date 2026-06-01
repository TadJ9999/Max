"""Finnhub trade WebSocket → SSE bridge.

Holds **one** upstream WebSocket to Finnhub (``wss://ws.finnhub.io``) and fans out
trade ticks to any number of browser subscribers via per-subscriber
``asyncio.Queue``s. The upstream socket opens lazily on the first subscriber and
closes when the last one leaves; while subscribers remain it auto-reconnects with
exponential backoff. Watchlist edits are applied live (subscribe/unsubscribe
diff) without dropping the connection.

Finnhub's free tier includes the real-time US-stock trade socket. With no API key
the stream stays dormant and emits nothing.
"""

from __future__ import annotations

import asyncio
import contextlib
import json

import websockets

FINNHUB_WS = "wss://ws.finnhub.io"


class TradeStream:
    """Single upstream Finnhub trade socket multiplexed to many SSE subscribers."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        symbols: list[str] | None = None,
        connect=None,  # injectable websockets.connect for tests
    ):
        self.api_key = api_key
        self._symbols: set[str] = {s.strip().upper() for s in (symbols or []) if s.strip()}
        self._subscribers: set[asyncio.Queue] = set()
        self._task: asyncio.Task | None = None
        self._connect = connect or websockets.connect
        self._last: dict[str, dict] = {}  # latest tick per symbol (for new-client snapshot)
        self._lock = asyncio.Lock()
        self._resub = asyncio.Event()  # set when the symbol set changes
        self.connected = False

    # ---- watchlist ------------------------------------------------------

    def set_symbols(self, symbols: list[str]) -> None:
        """Replace the streamed symbol set; applied live on the next loop tick."""
        self._symbols = {s.strip().upper() for s in symbols if s.strip()}
        self._resub.set()

    # ---- subscriber lifecycle ------------------------------------------

    async def subscribe(self) -> asyncio.Queue:
        """Register a browser subscriber; returns its tick queue. Starts the
        upstream connection if this is the first subscriber."""
        q: asyncio.Queue = asyncio.Queue(maxsize=1000)
        async with self._lock:
            self._subscribers.add(q)
            if self._task is None or self._task.done():
                self._task = asyncio.create_task(self._run())
        # Seed with the last-known tick per symbol so a new client paints at once.
        for tick in list(self._last.values()):
            with contextlib.suppress(asyncio.QueueFull):
                q.put_nowait(tick)
        return q

    async def unsubscribe(self, q: asyncio.Queue) -> None:
        async with self._lock:
            self._subscribers.discard(q)
            if not self._subscribers and self._task:
                self._task.cancel()
                self._task = None
                self.connected = False

    # ---- fan-out --------------------------------------------------------

    def _fanout(self, tick: dict) -> None:
        sym = tick.get("symbol")
        if sym:
            self._last[sym] = tick
        for q in self._subscribers:
            with contextlib.suppress(asyncio.QueueFull):
                q.put_nowait(tick)

    @staticmethod
    async def _apply_diff(ws, current: set[str], desired: set[str]) -> None:
        for s in desired - current:
            await ws.send(json.dumps({"type": "subscribe", "symbol": s}))
        for s in current - desired:
            await ws.send(json.dumps({"type": "unsubscribe", "symbol": s}))

    # ---- upstream loop --------------------------------------------------

    async def _run(self) -> None:
        if not self.api_key:
            return  # dormant without a key
        backoff = 1.0
        url = f"{FINNHUB_WS}?token={self.api_key}"
        while self._subscribers:
            subscribed: set[str] = set()
            try:
                async with self._connect(url) as ws:
                    self.connected = True
                    backoff = 1.0
                    self._resub.clear()
                    await self._apply_diff(ws, subscribed, self._symbols)
                    subscribed = set(self._symbols)
                    while self._subscribers:
                        if self._resub.is_set():
                            self._resub.clear()
                            await self._apply_diff(ws, subscribed, self._symbols)
                            subscribed = set(self._symbols)
                        try:
                            raw = await asyncio.wait_for(ws.recv(), timeout=1.0)
                        except asyncio.TimeoutError:
                            continue
                        self._ingest(raw)
            except asyncio.CancelledError:
                self.connected = False
                raise
            except Exception:
                # Connection dropped / refused / parse blowup — back off and retry
                # while anyone is still listening.
                self.connected = False
                await asyncio.sleep(min(backoff, 30.0))
                backoff *= 2
        self.connected = False

    def _ingest(self, raw: str | bytes) -> None:
        try:
            msg = json.loads(raw)
        except (ValueError, TypeError):
            return
        if not isinstance(msg, dict) or msg.get("type") != "trade":
            return
        for d in msg.get("data", []):
            if not isinstance(d, dict) or not d.get("s"):
                continue
            self._fanout(
                {
                    "symbol": d.get("s"),
                    "price": d.get("p"),
                    "volume": d.get("v"),
                    "ts": d.get("t"),
                }
            )

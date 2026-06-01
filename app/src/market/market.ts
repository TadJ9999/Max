// Client for the engine's Market endpoints. Mirrors osint.ts: hit ENGINE_URL,
// return null/[] on failure so callers can show an offline state, not throw.

import { ENGINE_URL } from "../engine";

export type Quote = {
  symbol: string;
  name: string | null;
  price: number;
  change: number;
  changePct: number;
  high: number;
  low: number;
  open: number;
  prevClose: number;
  ts: string | null;
};

export type MarketBoard = {
  updated: string;
  count: number;
  quotes: Quote[];
};

export type MarketSources = {
  provider: string;
  key_set: boolean;
  watchlist: string[];
  ttlSeconds: number;
};

export async function getBoard(): Promise<MarketBoard | null> {
  try {
    const r = await fetch(`${ENGINE_URL}/market/quotes`);
    if (!r.ok) return null;
    return (await r.json()) as MarketBoard;
  } catch {
    return null;
  }
}

export async function getWatchlist(): Promise<string[]> {
  try {
    const r = await fetch(`${ENGINE_URL}/market/watchlist`);
    if (!r.ok) return [];
    return (await r.json()).watchlist ?? [];
  } catch {
    return [];
  }
}

export async function setWatchlist(symbols: string[]): Promise<string[]> {
  try {
    const r = await fetch(`${ENGINE_URL}/market/watchlist`, {
      method: "PUT",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ symbols }),
    });
    if (!r.ok) return symbols;
    return (await r.json()).watchlist ?? symbols;
  } catch {
    return symbols;
  }
}

export async function getSources(): Promise<MarketSources | null> {
  try {
    const r = await fetch(`${ENGINE_URL}/market/sources`);
    if (!r.ok) return null;
    return (await r.json()) as MarketSources;
  } catch {
    return null;
  }
}

export type Candle = { t: number; o: number; h: number; l: number; c: number; v: number };

export async function getCandles(
  symbol: string,
  resolution = "D",
  days = 30,
): Promise<Candle[]> {
  try {
    const params = new URLSearchParams({ resolution, days: String(days) });
    const r = await fetch(`${ENGINE_URL}/market/candles/${encodeURIComponent(symbol)}?${params}`);
    if (!r.ok) return [];
    const data = await r.json();
    return (data.candles ?? []) as Candle[];
  } catch {
    return [];
  }
}

export type Trade = { symbol: string; price: number; volume: number | null; ts: number | null };
type StreamEvent = Trade | { type: "nokey" };

// Consume the engine's /market/stream SSE bridge (Finnhub trade socket fan-out).
// Yields each trade tick; yields {type:"nokey"} once and ends if no API key.
export async function* streamTrades(signal?: AbortSignal): AsyncGenerator<StreamEvent> {
  const r = await fetch(`${ENGINE_URL}/market/stream`, { signal });
  if (!r.ok || !r.body) throw new Error(`engine returned HTTP ${r.status}`);
  const reader = r.body.getReader();
  const dec = new TextDecoder();
  let buf = "";
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buf += dec.decode(value, { stream: true });
    const lines = buf.split("\n");
    buf = lines.pop() ?? "";
    for (const line of lines) {
      const t = line.trim();
      if (!t.startsWith("data:")) continue;
      const data = t.slice(5).trim();
      if (!data) continue;
      try {
        yield JSON.parse(data) as StreamEvent;
      } catch { /* skip malformed frame */ }
    }
  }
}

export type ChatTurn = { role: "user" | "assistant"; content: string };

// POST a JSON body to a market SSE endpoint and yield text deltas as they arrive
// (same OpenAI-compatible SSE shape as engine.ts:streamSSE).
async function* streamMarketSSE(
  path: string,
  body: unknown,
  signal?: AbortSignal,
): AsyncGenerator<string> {
  const r = await fetch(`${ENGINE_URL}${path}`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
    signal,
  });
  if (!r.ok || !r.body) {
    throw new Error(`engine returned HTTP ${r.status}`);
  }

  const reader = r.body.getReader();
  const decoder = new TextDecoder();
  let buf = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true });

    const lines = buf.split("\n");
    buf = lines.pop() ?? "";
    for (const line of lines) {
      const t = line.trim();
      if (!t.startsWith("data:")) continue;
      const data = t.slice(5).trim();
      if (data === "" || data === "[DONE]") continue;

      const obj = JSON.parse(data);
      if (obj.error) throw new Error(obj.error.message ?? "engine error");
      const delta: string | undefined = obj.choices?.[0]?.delta?.content;
      if (delta) yield delta;
    }
  }
}

// Stream the "Ingest" analysis (quotes + breadth + news) from /market/analyze.
export function streamAnalyze(signal?: AbortSignal): AsyncGenerator<string> {
  return streamMarketSSE("/market/analyze", {}, signal);
}

// Stream a conversational reply about the live board from /market/chat.
// `history` is the prior turns plus the new user question (last item).
export function streamMarketChat(
  history: ChatTurn[],
  signal?: AbortSignal,
): AsyncGenerator<string> {
  return streamMarketSSE("/market/chat", { messages: history }, signal);
}

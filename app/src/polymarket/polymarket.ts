// Client for the engine's Polymarket endpoints. Mirrors market.ts: hit ENGINE_URL,
// return null/[] on failure so callers can show an offline state, not throw.

import { ENGINE_URL } from "../engine";

export type PolyOutcome = {
  name: string;
  price: number;
  tokenId: string | null;
};

export type PolyMarket = {
  conditionId: string;
  question: string;
  slug: string;
  category: string;
  description: string;
  outcomes: PolyOutcome[];
  yesPrice: number;
  volume: number;
  volume24hr: number;
  liquidity: number;
  endDate: string | null;
  active: boolean;
  closed: boolean;
  image: string | null;
};

export type PolyBoard = {
  updated: string;
  count: number;
  markets: PolyMarket[];
};

export type PricePoint = { t: number; p: number };

export type OrderBookLevel = { price: number; size: number };
export type OrderBook = { bids: OrderBookLevel[]; asks: OrderBookLevel[] };

export type PolySources = {
  gamma: string;
  clob: string;
  keyRequired: boolean;
  watchlist: string[];
  ttlSeconds: number;
  embedEnabled: boolean;
  embeddedCount: number;
};

export type ChatTurn = { role: "user" | "assistant"; content: string };

export async function getBoard(): Promise<PolyBoard | null> {
  try {
    const r = await fetch(`${ENGINE_URL}/polymarket/board`);
    if (!r.ok) return null;
    return (await r.json()) as PolyBoard;
  } catch {
    return null;
  }
}

export async function getMarkets(
  opts: { category?: string; limit?: number; offset?: number } = {},
): Promise<PolyMarket[]> {
  try {
    const params = new URLSearchParams();
    if (opts.category) params.set("category", opts.category);
    if (opts.limit) params.set("limit", String(opts.limit));
    if (opts.offset) params.set("offset", String(opts.offset));
    const r = await fetch(`${ENGINE_URL}/polymarket/markets?${params}`);
    if (!r.ok) return [];
    return ((await r.json()).markets ?? []) as PolyMarket[];
  } catch {
    return [];
  }
}

export async function getWatchlistMarkets(): Promise<{
  watchlist: string[];
  markets: PolyMarket[];
}> {
  try {
    const r = await fetch(`${ENGINE_URL}/polymarket/watchlist`);
    if (!r.ok) return { watchlist: [], markets: [] };
    return (await r.json()) as { watchlist: string[]; markets: PolyMarket[] };
  } catch {
    return { watchlist: [], markets: [] };
  }
}

export async function setWatchlist(conditionIds: string[]): Promise<string[]> {
  try {
    const r = await fetch(`${ENGINE_URL}/polymarket/watchlist`, {
      method: "PUT",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ condition_ids: conditionIds }),
    });
    if (!r.ok) return conditionIds;
    return (await r.json()).watchlist ?? conditionIds;
  } catch {
    return conditionIds;
  }
}

export async function getPriceHistory(
  conditionId: string,
  interval: "1d" | "1w" | "1m" | "max" = "1w",
): Promise<PricePoint[]> {
  try {
    const r = await fetch(
      `${ENGINE_URL}/polymarket/prices/${encodeURIComponent(conditionId)}?interval=${interval}`,
    );
    if (!r.ok) return [];
    return ((await r.json()).history ?? []) as PricePoint[];
  } catch {
    return [];
  }
}

export async function getOrderBook(tokenId: string): Promise<OrderBook | null> {
  try {
    const r = await fetch(
      `${ENGINE_URL}/polymarket/order-book/${encodeURIComponent(tokenId)}`,
    );
    if (!r.ok) return null;
    const data = await r.json();
    return { bids: data.bids ?? [], asks: data.asks ?? [] };
  } catch {
    return null;
  }
}

export async function getSources(): Promise<PolySources | null> {
  try {
    const r = await fetch(`${ENGINE_URL}/polymarket/sources`);
    if (!r.ok) return null;
    return (await r.json()) as PolySources;
  } catch {
    return null;
  }
}

async function* streamPolySSE(
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
  if (!r.ok || !r.body) throw new Error(`engine returned HTTP ${r.status}`);

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

export function streamIngest(signal?: AbortSignal): AsyncGenerator<string> {
  return streamPolySSE("/polymarket/analyze", {}, signal);
}

export function streamChat(
  history: ChatTurn[],
  signal?: AbortSignal,
): AsyncGenerator<string> {
  return streamPolySSE("/polymarket/chat", { messages: history }, signal);
}

export async function* streamPolyIngest(signal?: AbortSignal): AsyncGenerator<string> {
  const r = await fetch(`${ENGINE_URL}/polymarket/ingest`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: "{}",
    signal,
  });
  if (!r.ok || !r.body) throw new Error(`engine returned HTTP ${r.status}`);

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
      const stage: string | undefined = obj.stage;
      if (stage) yield stage;
    }
  }
}

export type MarketEvent = {
  title: string;
  description: string;
  article_url: string | null;
  start_date: string | null;
  end_date: string | null;
  category: string | null;
};

export async function getMarketNews(conditionId: string): Promise<MarketEvent[]> {
  try {
    const r = await fetch(`${ENGINE_URL}/polymarket/news/${encodeURIComponent(conditionId)}`);
    if (!r.ok) return [];
    return ((await r.json()).events ?? []) as MarketEvent[];
  } catch {
    return [];
  }
}

export const CATEGORIES = ["All", "Politics", "Crypto", "Sports", "Economics", "Entertainment", "Science", "World", "Watchlist"] as const;
export type Category = (typeof CATEGORIES)[number];

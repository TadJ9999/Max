// Client for the engine's Apollo endpoints. Self-contained like osint.ts /
// market.ts: streams OpenAI-compatible SSE text deltas; throws on engine errors.

import { ENGINE_URL } from "../engine";

// Apollo SSE carries live call-trace status events alongside model text.
// `db` is +1 for a vector-memory WRITE, -1 for a READ, 0 otherwise.
export type ApolloEvent =
  | { type: "status"; stage: string; db: number }
  | { type: "delta"; text: string };

async function* streamApolloSSE(
  path: string,
  signal?: AbortSignal,
): AsyncGenerator<ApolloEvent> {
  const r = await fetch(`${ENGINE_URL}${path}`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: "{}",
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
      if (obj.object === "apollo.status") {
        yield { type: "status", stage: obj.stage ?? "", db: obj.db ?? 0 };
        continue;
      }
      const delta: string | undefined = obj.choices?.[0]?.delta?.content;
      if (delta) yield { type: "delta", text: delta };
    }
  }
}

// AI situational report over the highest-severity world news.
export function streamOsintReport(signal?: AbortSignal): AsyncGenerator<ApolloEvent> {
  return streamApolloSSE("/apollo/osint-report", signal);
}

// AI market report over the live board (quotes + breadth + news).
export function streamMarketReport(signal?: AbortSignal): AsyncGenerator<ApolloEvent> {
  return streamApolloSSE("/apollo/market-report", signal);
}

// Forward-looking predictions on global conflicts + markets.
export function streamPredict(signal?: AbortSignal): AsyncGenerator<ApolloEvent> {
  return streamApolloSSE("/apollo/predict", signal);
}

// ── Apollo chat ───────────────────────────────────────────────────────────────

export type ApolloChatTurn = { role: "user" | "assistant"; content: string };

export async function savePrediction(text: string): Promise<void> {
  try {
    await fetch(`${ENGINE_URL}/apollo/prediction`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ text }),
    });
  } catch { /* best-effort */ }
}

export async function* streamApolloChat(
  history: ApolloChatTurn[],
  signal?: AbortSignal,
): AsyncGenerator<string> {
  const r = await fetch(`${ENGINE_URL}/apollo/chat`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ messages: history }),
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
      if (!data || data === "[DONE]") continue;
      const obj = JSON.parse(data);
      if (obj.error) throw new Error(obj.error.message ?? "engine error");
      const delta: string | undefined = obj.choices?.[0]?.delta?.content;
      if (delta) yield delta;
    }
  }
}

export type MemoryStats = {
  enabled: boolean;
  total: number;
  byKind: Record<string, number>;
  oldest: number | null;
  newest: number | null;
};

export async function getMemoryStats(): Promise<MemoryStats | null> {
  try {
    const r = await fetch(`${ENGINE_URL}/apollo/status`);
    if (!r.ok) return null;
    return (await r.json()) as MemoryStats;
  } catch {
    return null;
  }
}

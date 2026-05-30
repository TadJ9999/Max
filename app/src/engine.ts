// Minimal client for the Max engine HTTP API.
// The engine runs locally (see ../../engine). Streaming endpoints return
// OpenAI-compatible SSE; we parse `data:` lines into text deltas.

export const ENGINE_URL = "http://127.0.0.1:8000";

export type Health = { status: string; version: string };

export async function getHealth(): Promise<Health | null> {
  try {
    const r = await fetch(`${ENGINE_URL}/health`, { method: "GET" });
    if (!r.ok) return null;
    return (await r.json()) as Health;
  } catch {
    return null;
  }
}

// Stream a full DSL command via /command, yielding text deltas as they arrive.
// Throws if the engine reports an error event in the stream.
export async function* streamCommand(
  text: string,
  signal?: AbortSignal,
): AsyncGenerator<string> {
  const r = await fetch(`${ENGINE_URL}/command`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ text }),
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

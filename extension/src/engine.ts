// Thin client for the local Max engine. Uses the global fetch/AbortController
// available in VS Code's Node runtime (>= 18).

import * as vscode from "vscode";

export function getConfig<T>(key: string, def: T): T {
  return vscode.workspace.getConfiguration("max").get<T>(key, def);
}

export function engineUrl(): string {
  return getConfig("engineUrl", "http://127.0.0.1:8001").replace(/\/$/, "");
}

export interface Health {
  status: string;
  version: string;
}

export async function getHealth(): Promise<Health | null> {
  try {
    const r = await fetch(`${engineUrl()}/health`);
    if (!r.ok) return null;
    return (await r.json()) as Health;
  } catch {
    return null;
  }
}

// Stream a DSL command via /command. Yields text deltas; sets meta.model when the
// engine reports which model handled it (so the UI can surface the active model).
export async function* streamCommand(
  text: string,
  token: vscode.CancellationToken,
  meta: { model?: string },
): AsyncGenerator<string> {
  const ac = new AbortController();
  const sub = token.onCancellationRequested(() => ac.abort());
  try {
    const resp = await fetch(`${engineUrl()}/command`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ text }),
      signal: ac.signal,
    });
    if (resp.status === 403) throw new Error("cloud routing is off (enable it in Max settings)");
    if (!resp.ok || !resp.body) throw new Error(`engine HTTP ${resp.status}`);

    const reader = resp.body.getReader();
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
        if (obj.model) meta.model = obj.model;
        const delta: string | undefined = obj.choices?.[0]?.delta?.content;
        if (delta) yield delta;
      }
    }
  } finally {
    sub.dispose();
  }
}

// Fill-in-the-middle completion for ghost text. Best-effort: "" on any failure.
export async function fimComplete(
  prefix: string,
  suffix: string,
  token: vscode.CancellationToken,
): Promise<string> {
  const ac = new AbortController();
  const sub = token.onCancellationRequested(() => ac.abort());
  try {
    const resp = await fetch(`${engineUrl()}/complete`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        prefix,
        suffix,
        max_tokens: getConfig("maxCompletionTokens", 96),
      }),
      signal: ac.signal,
    });
    if (!resp.ok) return "";
    const data = (await resp.json()) as { completion?: string };
    return data.completion ?? "";
  } catch {
    return "";
  } finally {
    sub.dispose();
  }
}

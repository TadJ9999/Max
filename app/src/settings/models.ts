// Client for the engine's /models endpoints.

import { ENGINE_URL } from "../engine";

export type LocalModel = {
  id: string;
  display_name: string;
  provider: string;
  kind: "local";
  size_gb: number;
  quant: string;
  family: string;
  parameter_size: string;
  vram_mb: number | null;
  ttft_ms: number | null;
  tokens_per_sec: number | null;
  bench_ran_at: number | null;
};

export type CloudModel = {
  id: string;
  display_name: string;
  provider: string;
  provider_label: string;
  kind: "cloud";
  context_k: number;
  input_cost_per_1m: number;
  output_cost_per_1m: number;
  cost_multiplier: number;
  strengths: string[];
  env_key: string;
  status: "available" | "coming_soon";
  key_set: boolean;
};

export type LocalServer = {
  base_url: string | null;
  reachable: boolean;
  models: string[];
};

export type ModelsResponse = {
  local: LocalModel[];
  cloud: CloudModel[];
  local_server: LocalServer;
  task_models: Record<string, string>;
  sigils: Record<string, string>;
};

export async function getModels(): Promise<ModelsResponse | null> {
  try {
    const r = await fetch(`${ENGINE_URL}/models`);
    if (!r.ok) return null;
    return (await r.json()) as ModelsResponse;
  } catch {
    return null;
  }
}

export async function benchmarkModel(model: string): Promise<{
  ttft_ms: number;
  tokens_per_sec: number;
} | null> {
  try {
    const r = await fetch(`${ENGINE_URL}/models/benchmark`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ model }),
    });
    if (!r.ok) return null;
    return await r.json();
  } catch {
    return null;
  }
}

export async function* streamPullModel(model: string): AsyncGenerator<string> {
  const r = await fetch(`${ENGINE_URL}/models/pull`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ model }),
  });
  if (!r.ok || !r.body) throw new Error(`Pull failed: HTTP ${r.status}`);

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
      if (data === "[DONE]" || data === "") break;
      const obj = JSON.parse(data);
      if (obj.status) yield obj.status as string;
    }
  }
}

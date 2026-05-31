// Client for the engine's UI-editable settings (/config). Returns null when the
// engine is unreachable so the panel can show an offline state.

import { ENGINE_URL } from "./engine";

export type EngineConfigView = {
  allow_cloud: boolean;
  cloud_key_set: boolean;
  finnhub_key_set: boolean;
  delegate: { mode: string; max_parallel_local: number; max_parallel_cloud: number };
  idle: { keep_alive: string };
  workspace_allowlist: string[];
  osint: {
    gdelt_query: string;
    gdelt_timespan: string;
    gdelt_max_records: number;
    ttl_seconds: number;
    naval_ttl_seconds: number;
    feeds: string[];
  };
  market: {
    watchlist: string[];
    ttl_seconds: number;
  };
  apollo: {
    embed_model: string;
    db_path: string;
    ttl_seconds: number;
    retrieve_k: number;
  };
  providers: Array<{ name: string; kind: string; base_url: string | null }>;
};

export type ConfigPatch = {
  allow_cloud?: boolean;
  workspace_allowlist?: string[];
  delegate?: { mode?: string; max_parallel_local?: number; max_parallel_cloud?: number };
  idle?: { keep_alive?: string };
  osint?: {
    gdelt_query?: string;
    gdelt_timespan?: string;
    gdelt_max_records?: number;
    ttl_seconds?: number;
    naval_ttl_seconds?: number;
    feeds?: string[];
  };
  market?: { watchlist?: string[]; ttl_seconds?: number };
  apollo?: { embed_model?: string; ttl_seconds?: number; retrieve_k?: number };
};

export async function getConfig(): Promise<EngineConfigView | null> {
  try {
    const r = await fetch(`${ENGINE_URL}/config`);
    if (!r.ok) return null;
    return (await r.json()) as EngineConfigView;
  } catch {
    return null;
  }
}

export async function updateConfig(patch: ConfigPatch): Promise<EngineConfigView | null> {
  try {
    const r = await fetch(`${ENGINE_URL}/config`, {
      method: "PUT",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(patch),
    });
    if (!r.ok) return null;
    return (await r.json()) as EngineConfigView;
  } catch {
    return null;
  }
}

export async function setApiKey(name: string, value: string): Promise<EngineConfigView | null> {
  try {
    const r = await fetch(`${ENGINE_URL}/config/key`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ name, value }),
    });
    if (!r.ok) return null;
    return (await r.json()) as EngineConfigView;
  } catch {
    return null;
  }
}

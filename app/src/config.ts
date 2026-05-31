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
  polymarket: {
    watchlist: string[];
    ttl_seconds: number;
    embed_enabled: boolean;
    categories: string[];
  };
  providers: Array<{ name: string; kind: string; base_url: string | null }>;
  personality: {
    persona: string;
    user_name: string;
    custom_prefix: string;
  };
  voice: {
    stt_provider: string;
    whisper_model: string;
    tts_enabled: boolean;
    tts_rate: number;
    tts_pitch: number;
    tts_voice_name: string;
  };
  aegis: {
    scan_enabled: boolean;
    scan_interval_hours: number;
    scan_on_startup: boolean;
    scan_roots: string[];
    osv_enabled: boolean;
    osv_ttl_seconds: number;
    score_threshold: number;
    autonomy: string;
  };
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
  polymarket?: { ttl_seconds?: number; embed_enabled?: boolean };
  personality?: { persona?: string; user_name?: string; custom_prefix?: string };
  voice?: {
    stt_provider?: string;
    whisper_model?: string;
    tts_enabled?: boolean;
    tts_rate?: number;
    tts_pitch?: number;
    tts_voice_name?: string;
  };
  aegis?: {
    scan_enabled?: boolean;
    scan_interval_hours?: number;
    scan_on_startup?: boolean;
    scan_roots?: string[];
    osv_enabled?: boolean;
    osv_ttl_seconds?: number;
    score_threshold?: number;
  };
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

// ── User profile ─────────────────────────────────────────────────────────────

export type ProfileItem = {
  key: string;
  value: string;
  kind: string;
  source: string;
  created_at: number;
  updated_at: number;
};

export async function getUserProfile(): Promise<ProfileItem[]> {
  try {
    const r = await fetch(`${ENGINE_URL}/user/profile`);
    if (!r.ok) return [];
    const data = (await r.json()) as { items: ProfileItem[] };
    return data.items;
  } catch {
    return [];
  }
}

export async function upsertProfileItem(
  key: string,
  value: string,
  kind: string = "fact",
): Promise<ProfileItem | null> {
  try {
    const r = await fetch(`${ENGINE_URL}/user/profile`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ key, value, kind }),
    });
    if (!r.ok) return null;
    return (await r.json()) as ProfileItem;
  } catch {
    return null;
  }
}

export async function deleteProfileItem(key: string): Promise<boolean> {
  try {
    const r = await fetch(`${ENGINE_URL}/user/profile/${encodeURIComponent(key)}`, {
      method: "DELETE",
    });
    return r.ok;
  } catch {
    return false;
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

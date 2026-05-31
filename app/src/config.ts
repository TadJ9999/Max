// Client for the engine's UI-editable settings (/config). Returns null when the
// engine is unreachable so the panel can show an offline state.

import { ENGINE_URL } from "./engine";

export type EngineConfigView = {
  allow_cloud: boolean;
  cloud_key_set: boolean;
  delegate: { mode: string; max_parallel_local: number; max_parallel_cloud: number };
  workspace_allowlist: string[];
};

export type ConfigPatch = {
  allow_cloud?: boolean;
  workspace_allowlist?: string[];
  delegate?: { mode?: string; max_parallel_local?: number; max_parallel_cloud?: number };
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

// Aegis API client — mirrors the osint.ts pattern.
// All calls return null / [] on failure so views show an offline state.

import { ENGINE_URL } from "../engine";

export type AegisSeverity = "Critical" | "High" | "Medium" | "Low";
export type AegisSource = "engine" | "delegate" | "provider" | "frontend" | "rust";

export type AegisEvent = {
  id: string;
  ts: string;
  source: AegisSource;
  severity: AegisSeverity;
  kind: string;
  message: string;
  traceback: string | null;
  context: Record<string, unknown>;
  fingerprint: string;
  count: number;
  first_ts: string;
  last_ts: string;
};

export type AegisLogEntry = {
  id: string;
  ts: string;
  event_id: string | null;
  status: "proposed" | "applied" | "verified" | "rolled-back";
  severity: AegisSeverity | null;
  symptom: string | null;
  root_cause: string | null;
  diff: string | null;
  provider: string | null;
  verification: string | null;
  snapshot_ref: string | null;
};

export type AegisSources = {
  provider: string;
  autonomy: string;
  cooldown_seconds: number;
  db_path: string;
  cloud_key_set: boolean;
  workspace_allowlist: string[];
};

export async function getAegisEvents(limit = 50): Promise<AegisEvent[]> {
  try {
    const r = await fetch(`${ENGINE_URL}/aegis/events?limit=${limit}`);
    if (!r.ok) return [];
    const data = (await r.json()) as { events: AegisEvent[] };
    return data.events ?? [];
  } catch {
    return [];
  }
}

export async function reportError(payload: {
  source?: AegisSource;
  severity?: AegisSeverity;
  kind: string;
  message: string;
  traceback?: string;
  context?: Record<string, unknown>;
}): Promise<void> {
  try {
    await fetch(`${ENGINE_URL}/aegis/report`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(payload),
    });
  } catch {
    /* best-effort, never throw */
  }
}

export type AegisChatTurn = { role: "user" | "assistant"; content: string };

export async function* streamDiagnosis(
  eventId: string,
  signal?: AbortSignal,
): AsyncGenerator<string> {
  const r = await fetch(`${ENGINE_URL}/aegis/diagnose`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ event_id: eventId }),
    signal,
  });
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
      if (!data || data === "[DONE]") continue;
      const obj = JSON.parse(data);
      if (obj.error) throw new Error(obj.error.message ?? "engine error");
      const delta: string | undefined = obj.choices?.[0]?.delta?.content;
      if (delta) yield delta;
    }
  }
}

export async function applyFix(
  eventId: string,
  diff: string,
  logId?: string,
): Promise<{ ok: boolean; error?: string; verification?: string }> {
  try {
    const r = await fetch(`${ENGINE_URL}/aegis/apply`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ event_id: eventId, diff, log_id: logId }),
    });
    return (await r.json()) as { ok: boolean; error?: string; verification?: string };
  } catch (e) {
    return { ok: false, error: String(e) };
  }
}

export async function rollbackFix(
  snapshotRef: string,
  logId?: string,
): Promise<{ ok: boolean; output?: string }> {
  try {
    const r = await fetch(`${ENGINE_URL}/aegis/rollback`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ snapshot_ref: snapshotRef, log_id: logId }),
    });
    return (await r.json()) as { ok: boolean; output?: string };
  } catch (e) {
    return { ok: false };
  }
}

export async function getAegisLog(limit = 100): Promise<AegisLogEntry[]> {
  try {
    const r = await fetch(`${ENGINE_URL}/aegis/log?limit=${limit}`);
    if (!r.ok) return [];
    const data = (await r.json()) as { log: AegisLogEntry[] };
    return data.log ?? [];
  } catch {
    return [];
  }
}

export async function getAegisSources(): Promise<AegisSources | null> {
  try {
    const r = await fetch(`${ENGINE_URL}/aegis/sources`);
    if (!r.ok) return null;
    return (await r.json()) as AegisSources;
  } catch {
    return null;
  }
}

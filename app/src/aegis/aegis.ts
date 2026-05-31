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

// ─── Phase 16: Security Posture ──────────────────────────────────────────────

export type SecurityFindingStatus = "open" | "fixed" | "ignored";
export type SecurityFindingCategory = "sast" | "sca";

export type SecurityFinding = {
  id: string;
  fingerprint: string;
  scan_id: string | null;
  first_scan_id: string | null;
  category: SecurityFindingCategory;
  rule_id: string | null;
  cwe: string | null;
  cve_id: string | null;
  package: string | null;
  installed_version: string | null;
  fixed_version: string | null;
  severity: AegisSeverity;
  title: string;
  file: string | null;
  line: number | null;
  snippet: string | null;
  message: string | null;
  recommendation: string | null;
  ai_confidence: number | null;
  ai_summary: string | null;
  status: SecurityFindingStatus;
  first_ts: string;
  last_ts: string;
  log_id: string | null;
};

export type ScanRun = {
  id: string;
  ts: string;
  finished_ts: string | null;
  status: "running" | "done" | "error";
  trigger: string | null;
  files_scanned: number;
  score: number | null;
  critical: number;
  high: number;
  medium: number;
  low: number;
};

export type Posture = {
  score: number;
  critical: number;
  high: number;
  medium: number;
  low: number;
  last_scan_ts: string | null;
  at_risk: boolean;
  history: { ts: string; score: number }[];
};

export type ScanStatus = {
  running: boolean;
  scan_id: string | null;
  files_scanned: number;
};

export async function runScan(): Promise<{ scan_id: string | null; started: boolean }> {
  try {
    const r = await fetch(`${ENGINE_URL}/aegis/scan`, { method: "POST" });
    if (!r.ok) return { scan_id: null, started: false };
    return (await r.json()) as { scan_id: string | null; started: boolean };
  } catch {
    return { scan_id: null, started: false };
  }
}

export async function getScanStatus(): Promise<ScanStatus> {
  try {
    const r = await fetch(`${ENGINE_URL}/aegis/scan/status`);
    if (!r.ok) return { running: false, scan_id: null, files_scanned: 0 };
    return (await r.json()) as ScanStatus;
  } catch {
    return { running: false, scan_id: null, files_scanned: 0 };
  }
}

export async function getPosture(): Promise<Posture | null> {
  try {
    const r = await fetch(`${ENGINE_URL}/aegis/posture`);
    if (!r.ok) return null;
    return (await r.json()) as Posture;
  } catch {
    return null;
  }
}

export async function getFindings(
  category?: SecurityFindingCategory,
  status?: SecurityFindingStatus,
): Promise<SecurityFinding[]> {
  try {
    const params = new URLSearchParams();
    if (category) params.set("category", category);
    if (status) params.set("status", status);
    const r = await fetch(`${ENGINE_URL}/aegis/findings?${params}`);
    if (!r.ok) return [];
    const data = (await r.json()) as { findings: SecurityFinding[] };
    return data.findings ?? [];
  } catch {
    return [];
  }
}

export async function getScans(limit = 20): Promise<ScanRun[]> {
  try {
    const r = await fetch(`${ENGINE_URL}/aegis/scans?limit=${limit}`);
    if (!r.ok) return [];
    const data = (await r.json()) as { scans: ScanRun[] };
    return data.scans ?? [];
  } catch {
    return [];
  }
}

export async function* streamFindingFix(
  findingId: string,
  signal?: AbortSignal,
): AsyncGenerator<string> {
  const r = await fetch(`${ENGINE_URL}/aegis/findings/${findingId}/fix`, {
    method: "POST",
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

export async function setFindingStatus(
  findingId: string,
  status: SecurityFindingStatus,
): Promise<boolean> {
  try {
    const r = await fetch(`${ENGINE_URL}/aegis/findings/${findingId}/status`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ status }),
    });
    return r.ok;
  } catch {
    return false;
  }
}

export async function getReport(): Promise<string> {
  try {
    const r = await fetch(`${ENGINE_URL}/aegis/report`);
    if (!r.ok) return "";
    const data = (await r.json()) as { report: string };
    return data.report ?? "";
  } catch {
    return "";
  }
}

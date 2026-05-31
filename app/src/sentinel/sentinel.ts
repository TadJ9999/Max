// Sentinel API client — talks to the Max engine (mirrors osint.ts / polymarket.ts).
const BASE = (import.meta as any).env?.VITE_ENGINE_URL || "http://localhost:8001";

export interface TLE { name: string; norad_id: string; line1: string; line2: string; }
export interface SatGroup { id: string; label: string; count: number; }
export interface TLEResponse { group: string; count: number; satellites: TLE[]; cached: boolean; error?: string; }

export interface OrbitElements { a: number | null; e: number | null; i: number | null; om: number | null; w: number | null; ma: number | null; epoch: number | null; }
export interface Neo {
  id: string; name: string; hazardous: boolean;
  diameter_min_m: number | null; diameter_max_m: number | null;
  approach_epoch_ms: number | null; approach_date: string;
  miss_km: number | null; miss_lunar: number | null; velocity_kms: number | null;
  jpl_url: string; orbit: OrbitElements | null;
}
export interface NeoResponse { count: number; hazardous_count: number; neos: Neo[]; cached: boolean; error?: string; }

export interface KpPoint { t: string; kp: number; }
export interface SpaceWeather {
  kp: number | null; kp_time: string; kp_series: KpPoint[]; storm: string;
  wind_speed: number | null; density: number | null; wind_time: string; error?: string;
}

export interface Fireball { date: string; energy_kt: number | null; impact_e_kt: number | null; lat: number | null; lon: number | null; altitude_km: number | null; velocity_kms: number | null; }
export interface FireballResponse { count: number; fireballs: Fireball[]; error?: string; }

export interface Launch { id: string; name: string; provider: string; vehicle: string; pad: string; location: string; net: string; status: string; image: string; }
export interface LaunchResponse { count: number; launches: Launch[]; error?: string; }

export interface ISS { lat: number | null; lon: number | null; altitude_km: number | null; velocity_kms: number | null; timestamp: number | null; crew: string[]; error?: string; }

async function getJSON<T>(path: string): Promise<T | null> {
  try {
    const r = await fetch(`${BASE}${path}`);
    if (!r.ok) return null;
    return (await r.json()) as T;
  } catch {
    return null;
  }
}

export const getGroups = () => getJSON<{ groups: SatGroup[] }>("/sentinel/groups");
export const getTLE = (group: string) => getJSON<TLEResponse>(`/sentinel/tle?group=${encodeURIComponent(group)}`);
export const getNeo = () => getJSON<NeoResponse>("/sentinel/neo");
export const getSpaceWeather = () => getJSON<SpaceWeather>("/sentinel/space-weather");
export const getFireballs = () => getJSON<FireballResponse>("/sentinel/fireballs");
export const getLaunches = () => getJSON<LaunchResponse>("/sentinel/launches");
export const getISS = () => getJSON<ISS>("/sentinel/iss");

// ---- SSE (AI analyze / chat) ----
export interface SentinelEvent { object: string; delta?: string; message?: string; }

async function* streamSSE(path: string, body?: unknown): AsyncGenerator<SentinelEvent> {
  const r = await fetch(`${BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!r.body) return;
  const reader = r.body.getReader();
  const decoder = new TextDecoder();
  let buf = "";
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true });
    const parts = buf.split("\n\n");
    buf = parts.pop() || "";
    for (const part of parts) {
      const line = part.trim();
      if (!line.startsWith("data:")) continue;
      try { yield JSON.parse(line.slice(5).trim()) as SentinelEvent; } catch { /* ignore */ }
    }
  }
}

export function streamAnalyze(): AsyncGenerator<SentinelEvent> { return streamSSE("/sentinel/analyze"); }
export function streamChat(messages: { role: string; content: string }[]): AsyncGenerator<SentinelEvent> {
  return streamSSE("/sentinel/chat", { messages });
}

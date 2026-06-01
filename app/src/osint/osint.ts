// Client for the engine's OSINT endpoints. Mirrors engine.ts: hit ENGINE_URL,
// return null on failure so callers can show an offline state instead of throwing.

import { ENGINE_URL } from "../engine";

export type CountryStat = {
  iso: string;
  name: string;
  intensity: number; // 0..1 (sizes bars; coloring is by severity)
  articleCount: number;
  sources: number;
  severity: number; // 0 low .. 3 critical
  severityLabel: string;
};

export type Heatmap = {
  updated: string;
  totalArticles: number;
  countries: CountryStat[];
};

export type Article = {
  title: string;
  url: string;
  domain: string;
  origin: "gdelt" | "rss";
  iso: string | null;
  country: string | null;
  published: string | null;
  image: string | null;
  severity: number; // 0 low .. 3 critical
  severityLabel: string;
  summary: string | null;
};

export type ShipPosition = {
  name: string;
  hull: string;
  kind: "carrier" | "amphib";
  lat: number;
  lon: number;
  region: string;
  status: "underway" | "in port";
  confidence: "high" | "medium" | "low";
  source: string;
  url: string;
  asOf: string | null;
};

export type NavalData = {
  updated: string | null;
  ships: ShipPosition[];
  sources: string[];
};

export type GeoEvent = {
  id: string;
  category: string;
  title: string;
  lat: number;
  lon: number;
  magnitude: number;
  severity: number;
  color: string;
  url: string;
  source: string;
  published: string | null;
};

export type EventsData = {
  updated: string | null;
  count: number;
  events: GeoEvent[];
  sources: string[];
};

export type SourceDomain = {
  domain: string;
  origin: "gdelt" | "rss";
  count: number;
};

export type TimelineFrame = {
  at: string;
  totalArticles: number;
  countries: CountryStat[];
};

export type Timeline = {
  frames: TimelineFrame[];
  windowHours: number;
};

export async function getEvents(): Promise<EventsData | null> {
  try {
    const r = await fetch(`${ENGINE_URL}/osint/events`);
    if (!r.ok) return null;
    return (await r.json()) as EventsData;
  } catch {
    return null;
  }
}

export async function getNaval(): Promise<NavalData | null> {
  try {
    const r = await fetch(`${ENGINE_URL}/osint/naval`);
    if (!r.ok) return null;
    return (await r.json()) as NavalData;
  } catch {
    return null;
  }
}

export async function getHeatmap(domains?: string[]): Promise<Heatmap | null> {
  try {
    const q = domains && domains.length ? `?domains=${encodeURIComponent(domains.join(","))}` : "";
    const r = await fetch(`${ENGINE_URL}/osint/heatmap${q}`);
    if (!r.ok) return null;
    return (await r.json()) as Heatmap;
  } catch {
    return null;
  }
}

export async function getDomains(): Promise<SourceDomain[]> {
  try {
    const r = await fetch(`${ENGINE_URL}/osint/domains`);
    if (!r.ok) return [];
    const data = (await r.json()) as { domains: SourceDomain[] };
    return data.domains ?? [];
  } catch {
    return [];
  }
}

export async function getTimeline(frames = 24): Promise<Timeline | null> {
  try {
    const r = await fetch(`${ENGINE_URL}/osint/timeline?frames=${frames}`);
    if (!r.ok) return null;
    return (await r.json()) as Timeline;
  } catch {
    return null;
  }
}

export type OsintChatTurn = { role: "user" | "assistant"; content: string };

export async function* streamOsintChat(
  messages: OsintChatTurn[],
  country: string | null,
  signal?: AbortSignal,
): AsyncGenerator<string> {
  const r = await fetch(`${ENGINE_URL}/osint/chat`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ messages, country }),
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

export async function getCountryArticles(
  iso: string | null,
  limit = 40,
  domains?: string[],
): Promise<Article[]> {
  try {
    const q = new URLSearchParams({ limit: String(limit) });
    if (iso) q.set("country", iso);
    if (domains && domains.length) q.set("domains", domains.join(","));
    const r = await fetch(`${ENGINE_URL}/osint/articles?${q}`);
    if (!r.ok) return [];
    const data = (await r.json()) as { articles: Article[] };
    return data.articles ?? [];
  } catch {
    return [];
  }
}

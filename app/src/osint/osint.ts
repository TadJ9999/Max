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

export async function getHeatmap(): Promise<Heatmap | null> {
  try {
    const r = await fetch(`${ENGINE_URL}/osint/heatmap`);
    if (!r.ok) return null;
    return (await r.json()) as Heatmap;
  } catch {
    return null;
  }
}

export async function getCountryArticles(
  iso: string | null,
  limit = 40,
): Promise<Article[]> {
  try {
    const q = new URLSearchParams({ limit: String(limit) });
    if (iso) q.set("country", iso);
    const r = await fetch(`${ENGINE_URL}/osint/articles?${q}`);
    if (!r.ok) return [];
    const data = (await r.json()) as { articles: Article[] };
    return data.articles ?? [];
  } catch {
    return [];
  }
}

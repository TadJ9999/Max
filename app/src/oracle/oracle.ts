// Oracle — client for the self-grading track-record API (Phase 20).
// Every fetch degrades to null/empty on failure so the tab never hard-crashes
// when the engine is offline.

import { ENGINE_URL } from "../engine";

export type Outcome = "hit" | "partial" | "miss" | "too-early";
export type FailureTag =
  | "wrong-direction" | "wrong-timing" | "wrong-magnitude" | "black-swan"
  | "data-gap" | "overconfidence" | "partial-correct";

export interface Grade {
  id: number;
  claimId: number;
  checkpoint: string;
  score: number;
  outcome: Outcome;
  brier: number | null;
  failureTag: FailureTag | null;
  reason: string | null;
  source: "objective" | "llm-local" | "llm-cloud" | "user";
  evidence: Record<string, unknown>;
  userVerified: boolean;
  gradedAt: number;
}

export interface Claim {
  id: number;
  reportId: number;
  feature: string;
  claim: string;
  entity: string | null;
  entityKind: string | null;
  direction: string | null;
  magnitude: number | null;
  horizonHours: number | null;
  confidence: number | null;
  status: "pending" | "graded" | "unresolvable";
  createdAt: number;
  grades: Grade[];
  latestGrade: Grade | null;
}

export interface ClaimDetail extends Claim {
  report: {
    id: number;
    feature: string;
    kind: string;
    title: string | null;
    body: string;
    context: Record<string, unknown>;
    createdAt: number;
  } | null;
}

export interface ModelMeta {
  ready: boolean;
  reason?: string;
  trainedAt: number | null;
  samples: number;
  minSamples?: number;
  brier?: number | null;
  globalHitMean?: number;
  calibrationFit?: { x: number; y: number }[];
  reliability?: Record<string, number>;
  hardestEntities?: { entity: string; skill: number }[];
}

export interface OracleStats {
  totalClaims: number;
  pending: number;
  gradedClaims: number;
  resolvedGrades: number;
  byOutcome: Partial<Record<Outcome, number>>;
  avgScore: number | null;
  avgBrier: number | null;
  accuracy: number | null;
  failureModes: Record<string, number>;
  calibrationCurve: { confidence: number; actual: number; count: number }[];
  perEntity: { entity: string; count: number; avgScore: number }[];
  model: ModelMeta;
  enabled: boolean;
  horizons: string[];
}

export interface HindsightItem {
  claimId: number;
  claim: string;
  entity: string | null;
  feature: string | null;
  outcome: Outcome;
  score: number | null;
  checkpoint: string | null;
  failureTag: FailureTag | null;
  reason: string | null;
  match: "entity" | "vector";
  distance?: number;
}

export interface Hindsight {
  right: HindsightItem[];
  missed: HindsightItem[];
}

async function getJSON<T>(path: string): Promise<T | null> {
  try {
    const r = await fetch(`${ENGINE_URL}${path}`);
    if (!r.ok) return null;
    return (await r.json()) as T;
  } catch {
    return null;
  }
}

async function postJSON<T>(path: string, body?: unknown): Promise<T | null> {
  try {
    const r = await fetch(`${ENGINE_URL}${path}`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: body === undefined ? "{}" : JSON.stringify(body),
    });
    if (!r.ok) return null;
    return (await r.json()) as T;
  } catch {
    return null;
  }
}

export async function getClaims(opts: {
  status?: string; feature?: string; entity?: string; limit?: number;
} = {}): Promise<Claim[]> {
  const q = new URLSearchParams();
  if (opts.status) q.set("status", opts.status);
  if (opts.feature) q.set("feature", opts.feature);
  if (opts.entity) q.set("entity", opts.entity);
  if (opts.limit) q.set("limit", String(opts.limit));
  const data = await getJSON<{ claims: Claim[] }>(`/oracle/claims?${q.toString()}`);
  return data?.claims ?? [];
}

export async function getClaim(id: number): Promise<ClaimDetail | null> {
  return getJSON<ClaimDetail>(`/oracle/claims/${id}`);
}

export async function getStats(): Promise<OracleStats | null> {
  return getJSON<OracleStats>("/oracle/stats");
}

export async function getHindsight(opts: {
  feature?: string; entity?: string; query?: string; k?: number;
}): Promise<Hindsight> {
  const q = new URLSearchParams();
  if (opts.feature) q.set("feature", opts.feature);
  if (opts.entity) q.set("entity", opts.entity);
  if (opts.query) q.set("query", opts.query.slice(0, 1000));
  if (opts.k) q.set("k", String(opts.k));
  const data = await getJSON<Hindsight>(`/oracle/hindsight?${q.toString()}`);
  return data ?? { right: [], missed: [] };
}

export async function overrideGrade(
  id: number,
  body: { score: number; outcome: Outcome; failure_tag?: string | null; reason?: string },
): Promise<ClaimDetail | null> {
  return postJSON<ClaimDetail>(`/oracle/grade/${id}`, body);
}

export async function gradeNow(): Promise<{ graded: number } | null> {
  return postJSON<{ graded: number }>("/oracle/grade-now");
}

export async function retrain(): Promise<ModelMeta | null> {
  return postJSON<ModelMeta>("/oracle/retrain");
}

// ---- shared display helpers ---------------------------------------------

export const OUTCOME_COLOR: Record<string, string> = {
  hit: "#22c55e",
  partial: "#eab308",
  miss: "#ef4444",
  "too-early": "#64748b",
  pending: "#64748b",
};

export function outcomeLabel(o: string | null | undefined): string {
  if (!o) return "Pending";
  return { hit: "Hit", partial: "Partial", miss: "Miss", "too-early": "Too early" }[o] ?? o;
}

export function timeAgo(ts: number): string {
  const s = Math.max(0, Math.floor(Date.now() / 1000 - ts));
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  return `${Math.floor(s / 86400)}d ago`;
}

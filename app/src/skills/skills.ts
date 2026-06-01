/** API client for Phase 9 skills endpoints. */

const BASE = "http://127.0.0.1:8001";

async function get<T>(path: string): Promise<T> {
  const r = await fetch(BASE + path);
  if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
  return r.json() as Promise<T>;
}

async function post<T>(path: string, body?: unknown): Promise<T> {
  const r = await fetch(BASE + path, {
    method: "POST",
    headers: body !== undefined ? { "Content-Type": "application/json" } : {},
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  if (!r.ok) {
    const err = await r.json().catch(() => ({ detail: r.statusText }));
    throw new Error((err as { detail?: string }).detail ?? r.statusText);
  }
  return r.json() as Promise<T>;
}

async function del<T>(path: string): Promise<T> {
  const r = await fetch(BASE + path, { method: "DELETE" });
  if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
  return r.json() as Promise<T>;
}

// ---- Capabilities -----------------------------------------------------------

export function fetchCapabilities() {
  return get<{ capabilities: Capability[] }>("/capabilities");
}

export interface Capability {
  name: string;
  description: string;
  domains: string[];
  available: boolean;
  connected: boolean;
  [key: string]: unknown;
}

// ---- Web Search -------------------------------------------------------------

export interface SearchHit {
  title: string;
  url: string;
  snippet: string;
}

export function searchRaw(q: string, maxResults = 6) {
  return get<{ query: string; results: SearchHit[] }>(
    `/skills/search/raw?q=${encodeURIComponent(q)}&max_results=${maxResults}`
  );
}

export function streamSearch(
  query: string,
  onChunk: (t: string) => void,
  signal?: AbortSignal
): Promise<void> {
  return streamSSE(`${BASE}/skills/search`, { query }, onChunk, signal);
}

// ---- Reports ----------------------------------------------------------------

export interface Report {
  id: string;
  title: string;
  created_at: number;
  word_count: number;
  content?: string;
}

export function listReports() {
  return get<{ reports: Report[] }>("/skills/report/list");
}

export function getReport(id: string) {
  return get<Report>(`/skills/report/${id}`);
}

export function deleteReport(id: string) {
  return del<{ ok: boolean }>(`/skills/report/${id}`);
}

export function streamReport(
  title: string,
  instructions: string,
  onChunk: (t: string) => void,
  signal?: AbortSignal
): Promise<void> {
  return streamSSE(
    `${BASE}/skills/report/generate`,
    { title, instructions },
    onChunk,
    signal
  );
}

// ---- Files ------------------------------------------------------------------

export interface FileEntry {
  name: string;
  type: "file" | "dir";
  size: number | null;
  ext: string | null;
}

export interface FileHit {
  file: string;
  line: number;
  text: string;
}

export function listFiles(path?: string) {
  const qs = path ? `?path=${encodeURIComponent(path)}` : "";
  return get<{ path: string; entries: FileEntry[] }>(`/skills/files/list${qs}`);
}

export function readFile(path: string) {
  return post<{ path: string; content: string }>("/skills/files/read", { path });
}

export function searchFiles(query: string, path?: string, maxResults = 50) {
  return post<{ query: string; hits: FileHit[] }>("/skills/files/search", {
    query, path, max_results: maxResults,
  });
}

export function writeFile(path: string, content: string) {
  return post<{ path: string; bytes_written: number }>("/skills/files/write", {
    path, content, preview: false,
  });
}

export function writeFilePreview(path: string, content: string) {
  return post<{ path: string; exists: boolean; old_size: number; new_size: number; preview: string }>(
    "/skills/files/write", { path, content, preview: true }
  );
}

// ---- Spotify ----------------------------------------------------------------

export interface SpotifyTrack {
  name: string;
  artist: string;
  album: string;
  uri: string;
  duration_ms: number;
  image: string;
}

export interface SpotifyStatus {
  configured: boolean;
  authenticated: boolean;
  client_id: string;
  is_playing?: boolean;
  track?: SpotifyTrack & { progress_ms?: number };
}

export function spotifyAuth() {
  return get<{ url: string; configured: boolean }>("/skills/spotify/auth");
}

export function spotifyStatus() {
  return get<SpotifyStatus>("/skills/spotify/status");
}

export function spotifyControl(action: "play" | "pause" | "next" | "prev") {
  return post<{ action: string; ok: boolean }>("/skills/spotify/control", { action });
}

export function spotifyPlay(uri: string) {
  return post<{ uri: string; ok: boolean }>("/skills/spotify/play", { uri });
}

export function spotifySearch(query: string, types = "track", limit = 10) {
  return post<{ results: SpotifyTrack[] }>("/skills/spotify/search", {
    query, types, limit,
  });
}

export function spotifyDisconnect() {
  return post<{ ok: boolean }>("/skills/spotify/disconnect");
}

// ---- Google Calendar --------------------------------------------------------

export interface CalEvent {
  id: string;
  summary: string;
  description: string;
  start: string;
  end: string;
  location: string;
  html_link: string;
}

export interface CalStatus {
  configured: boolean;
  authenticated: boolean;
  calendar_id: string;
}

export function calendarAuth() {
  return get<{ url: string; configured: boolean }>("/skills/calendar/auth");
}

export function calendarStatus() {
  return get<CalStatus>("/skills/calendar/status");
}

export function calendarEvents(maxResults = 15, daysAhead = 14) {
  return get<{ events: CalEvent[] }>(
    `/skills/calendar/events?max_results=${maxResults}&days_ahead=${daysAhead}`
  );
}

export function calendarCreateEvent(
  summary: string,
  start_dt: string,
  end_dt: string,
  description = "",
  location = ""
) {
  return post<CalEvent>("/skills/calendar/event", {
    summary, start_dt, end_dt, description, location,
  });
}

export function calendarDeleteEvent(eventId: string) {
  return del<{ ok: boolean }>(`/skills/calendar/event/${eventId}`);
}

export function calendarDisconnect() {
  return post<{ ok: boolean }>("/skills/calendar/disconnect");
}

// ---- SSE helper -------------------------------------------------------------

export async function streamSSE(
  url: string,
  body: unknown,
  onChunk: (text: string) => void,
  signal?: AbortSignal
): Promise<void> {
  const r = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    signal,
  });
  if (!r.ok || !r.body) throw new Error(`${r.status} ${r.statusText}`);
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
      if (!line.startsWith("data: ")) continue;
      const raw = line.slice(6).trim();
      if (raw === "[DONE]") return;
      try {
        const parsed = JSON.parse(raw) as {
          object?: string;
          choices?: Array<{ delta?: { content?: string } }>;
        };
        const text = parsed.choices?.[0]?.delta?.content;
        if (text) onChunk(text);
      } catch {
        /* skip malformed */
      }
    }
  }
}

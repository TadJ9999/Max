import { useCallback, useEffect, useRef, useState } from "react";
import {
  type CalEvent,
  type FileEntry,
  type FileHit,
  type Report,
  type SpotifyStatus,
  type SpotifyTrack,
  calendarAuth,
  calendarCreateEvent,
  calendarDeleteEvent,
  calendarDisconnect,
  calendarEvents,
  calendarStatus,
  deleteReport,
  getReport,
  fetchCapabilities,
  listFiles,
  listReports,
  readFile,
  searchFiles,
  spotifyAuth,
  spotifyControl,
  spotifyDisconnect,
  spotifyPlay,
  spotifySearch,
  spotifyStatus,
  streamReport,
  streamSearch,
  writeFile,
  writeFilePreview,
} from "./skills";
import "./Skills.css";

// ─────────────────────────────────────────────────────────────────────────────
// Helpers
// ─────────────────────────────────────────────────────────────────────────────

function fmtDate(iso: string): string {
  if (!iso) return "";
  try {
    return new Date(iso).toLocaleString(undefined, {
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return iso;
  }
}

function fmtMs(ms: number): string {
  const m = Math.floor(ms / 60000);
  const s = Math.floor((ms % 60000) / 1000);
  return `${m}:${s.toString().padStart(2, "0")}`;
}

async function openUrl(url: string) {
  try {
    const { openUrl: tauriOpen } = await import("@tauri-apps/plugin-opener");
    await tauriOpen(url);
  } catch {
    window.open(url, "_blank", "noopener,noreferrer");
  }
}

// ─────────────────────────────────────────────────────────────────────────────
// Web Search Panel
// ─────────────────────────────────────────────────────────────────────────────

function WebSearchPanel() {
  const [query, setQuery] = useState("");
  const [output, setOutput] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const abortRef = useRef<AbortController | null>(null);

  const run = useCallback(async () => {
    if (!query.trim() || loading) return;
    abortRef.current?.abort();
    const ctrl = new AbortController();
    abortRef.current = ctrl;
    setOutput("");
    setError("");
    setLoading(true);
    try {
      await streamSearch(query, (t) => setOutput((p) => p + t), ctrl.signal);
    } catch (e) {
      if ((e as Error).name !== "AbortError") setError(String(e));
    } finally {
      setLoading(false);
    }
  }, [query, loading]);

  return (
    <div className="skills__panel-body">
      <div className="skills__search-row">
        <input
          className="skills__input"
          placeholder="Search the web…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && void run()}
        />
        <button className="skills__btn" onClick={() => void run()} disabled={loading}>
          {loading ? "…" : "Search"}
        </button>
      </div>
      {error && <div className="skills__error">{error}</div>}
      {(output || loading) && (
        <div className="skills__stream-box">
          {output}
          {loading && <span style={{ opacity: 0.5 }}>▋</span>}
        </div>
      )}
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Reports Panel
// ─────────────────────────────────────────────────────────────────────────────

function ReportsPanel() {
  const [reports, setReports] = useState<Report[]>([]);
  const [selected, setSelected] = useState<Report | null>(null);
  const [title, setTitle] = useState("");
  const [instructions, setInstructions] = useState("");
  const [output, setOutput] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [mode, setMode] = useState<"list" | "new" | "view">("list");
  const abortRef = useRef<AbortController | null>(null);

  const refreshList = useCallback(async () => {
    try {
      const r = await listReports();
      setReports(r.reports);
    } catch { /* ignore */ }
  }, []);

  useEffect(() => { void refreshList(); }, [refreshList]);

  const generate = async () => {
    if (!title.trim() || loading) return;
    abortRef.current?.abort();
    const ctrl = new AbortController();
    abortRef.current = ctrl;
    setOutput("");
    setError("");
    setLoading(true);
    try {
      await streamReport(title, instructions || title, (t) => setOutput((p) => p + t), ctrl.signal);
      await refreshList();
    } catch (e) {
      if ((e as Error).name !== "AbortError") setError(String(e));
    } finally {
      setLoading(false);
    }
  };

  const viewReport = async (r: Report) => {
    try {
      const full = await getReport(r.id);
      setSelected(full);
      setOutput(full.content ?? "");
      setMode("view");
    } catch (e) {
      setError(String(e));
    }
  };

  const del = async (r: Report) => {
    await deleteReport(r.id);
    setReports((prev) => prev.filter((x) => x.id !== r.id));
    if (selected?.id === r.id) { setSelected(null); setMode("list"); }
  };

  if (mode === "view" && selected) {
    return (
      <div className="skills__panel-body">
        <div className="skills__row">
          <button className="skills__btn" onClick={() => setMode("list")}>← Back</button>
          <button
            className="skills__copy-btn"
            onClick={() => void navigator.clipboard.writeText(output)}
          >Copy</button>
          <button className="skills__btn skills__btn--danger" onClick={() => void del(selected)}>Delete</button>
        </div>
        <div className="skills__label">{selected.title}</div>
        <div className="skills__stream-box" style={{ maxHeight: "500px" }}>{output}</div>
      </div>
    );
  }

  if (mode === "new") {
    return (
      <div className="skills__panel-body">
        <div className="skills__row">
          <button className="skills__btn" onClick={() => setMode("list")}>← Back</button>
        </div>
        <div className="skills__label">Title</div>
        <input className="skills__input" value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Report title…" />
        <div className="skills__label">Instructions</div>
        <textarea className="skills__textarea" value={instructions} onChange={(e) => setInstructions(e.target.value)} placeholder="What should the report cover?…" />
        <button className="skills__btn" onClick={() => void generate()} disabled={loading}>
          {loading ? "Generating…" : "Generate"}
        </button>
        {error && <div className="skills__error">{error}</div>}
        {(output || loading) && (
          <div className="skills__stream-box">
            {output}{loading && <span style={{ opacity: 0.5 }}>▋</span>}
          </div>
        )}
      </div>
    );
  }

  return (
    <div className="skills__panel-body">
      <div className="skills__row">
        <button className="skills__btn" onClick={() => setMode("new")}>+ New Report</button>
        <button className="skills__btn" onClick={() => void refreshList()} style={{ marginLeft: "auto" }}>↺</button>
      </div>
      {error && <div className="skills__error">{error}</div>}
      {reports.length === 0 ? (
        <div className="skills__connect-label" style={{ textAlign: "center", paddingTop: 24 }}>
          No reports yet — generate your first one.
        </div>
      ) : (
        <div className="skills__report-list">
          {reports.map((r) => (
            <div key={r.id} className="skills__report-card" onClick={() => void viewReport(r)}>
              <div className="skills__report-title">{r.title}</div>
              <div className="skills__report-meta">{r.word_count}w</div>
              <button
                className="skills__copy-btn"
                style={{ marginLeft: 4 }}
                onClick={(e) => { e.stopPropagation(); void del(r); }}
              >✕</button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Files Panel
// ─────────────────────────────────────────────────────────────────────────────

function FilesPanel() {
  const [tab, setTab] = useState<"browse" | "search" | "write">("browse");
  const [path, setPath] = useState("");
  const [entries, setEntries] = useState<FileEntry[]>([]);
  const [fileContent, setFileContent] = useState("");
  const [viewPath, setViewPath] = useState("");
  const [searchQuery, setSearchQuery] = useState("");
  const [hits, setHits] = useState<FileHit[]>([]);
  const [writePath, setWritePath] = useState("");
  const [writeContent, setWriteContent] = useState("");
  const [writePreviewData, setWritePreviewData] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const browse = async (p?: string) => {
    setLoading(true); setError("");
    try {
      const r = await listFiles(p);
      setPath(r.path);
      setEntries(r.entries);
      setFileContent("");
      setViewPath("");
    } catch (e) { setError(String(e)); }
    finally { setLoading(false); }
  };

  const openFile = async (entry: FileEntry, base: string) => {
    if (entry.type === "dir") { void browse(`${base}/${entry.name}`); return; }
    setLoading(true); setError("");
    try {
      const r = await readFile(`${base}/${entry.name}`);
      setViewPath(r.path);
      setFileContent(r.content);
    } catch (e) { setError(String(e)); }
    finally { setLoading(false); }
  };

  const doSearch = async () => {
    if (!searchQuery.trim()) return;
    setLoading(true); setError("");
    try {
      const r = await searchFiles(searchQuery);
      setHits(r.hits);
    } catch (e) { setError(String(e)); }
    finally { setLoading(false); }
  };

  const doWritePreview = async () => {
    if (!writePath.trim()) return;
    setLoading(true); setError("");
    try {
      const r = await writeFilePreview(writePath, writeContent);
      setWritePreviewData(r.preview);
    } catch (e) { setError(String(e)); }
    finally { setLoading(false); }
  };

  const doWrite = async () => {
    if (!writePath.trim()) return;
    setLoading(true); setError(""); setWritePreviewData(null);
    try {
      await writeFile(writePath, writeContent);
      setError(""); // success
    } catch (e) { setError(String(e)); }
    finally { setLoading(false); }
  };

  return (
    <div className="skills__panel-body">
      <div className="skills__row">
        {(["browse", "search", "write"] as const).map((t) => (
          <button key={t} className={`skills__btn${tab === t ? " is-active" : ""}`}
            style={tab === t ? { background: "rgba(79,195,247,0.18)" } : {}}
            onClick={() => setTab(t)}>
            {t === "browse" ? "Browse" : t === "search" ? "Search" : "Write"}
          </button>
        ))}
      </div>
      {error && <div className="skills__error">{error}</div>}

      {tab === "browse" && (
        <>
          <div className="skills__search-row">
            <input className="skills__input" value={path} onChange={(e) => setPath(e.target.value)} placeholder="Directory path…" />
            <button className="skills__btn" onClick={() => void browse(path)} disabled={loading}>Open</button>
          </div>
          {viewPath && (
            <>
              <div className="skills__label">{viewPath}</div>
              <div className="skills__stream-box" style={{ fontFamily: "monospace", fontSize: 11 }}>{fileContent}</div>
            </>
          )}
          {!viewPath && entries.length > 0 && (
            <div className="skills__file-list">
              {entries.map((e) => (
                <div key={e.name} className={`skills__file-entry${e.type === "dir" ? " skills__file-entry--dir" : ""}`}
                  onClick={() => void openFile(e, path)}>
                  <span>{e.type === "dir" ? "📁" : "📄"}</span>
                  <span>{e.name}</span>
                  {e.size !== null && <span style={{ marginLeft: "auto", opacity: 0.4, fontSize: 10 }}>{(e.size / 1024).toFixed(1)}k</span>}
                </div>
              ))}
            </div>
          )}
        </>
      )}

      {tab === "search" && (
        <>
          <div className="skills__search-row">
            <input className="skills__input" value={searchQuery} onChange={(e) => setSearchQuery(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && void doSearch()} placeholder="Search pattern (regex ok)…" />
            <button className="skills__btn" onClick={() => void doSearch()} disabled={loading}>Search</button>
          </div>
          <div className="skills__result-list">
            {hits.map((h, i) => (
              <div key={i} className="skills__result-card">
                <div className="skills__result-title" style={{ color: "#4fc3f7" }}>{h.file}:{h.line}</div>
                <div className="skills__result-snippet" style={{ fontFamily: "monospace" }}>{h.text}</div>
              </div>
            ))}
          </div>
        </>
      )}

      {tab === "write" && (
        <>
          <div className="skills__label">File path</div>
          <input className="skills__input" value={writePath} onChange={(e) => setWritePath(e.target.value)} placeholder="Absolute path…" />
          <div className="skills__label">Content</div>
          <textarea className="skills__textarea" style={{ minHeight: 140 }} value={writeContent}
            onChange={(e) => setWriteContent(e.target.value)} placeholder="File content…" />
          <div className="skills__row">
            <button className="skills__btn" onClick={() => void doWritePreview()} disabled={loading}>Preview</button>
            <button className="skills__btn skills__btn--green" onClick={() => void doWrite()} disabled={loading}>Write</button>
          </div>
          {writePreviewData && (
            <>
              <div className="skills__label">Preview (first 2000 chars)</div>
              <div className="skills__stream-box" style={{ fontFamily: "monospace", fontSize: 11 }}>{writePreviewData}</div>
            </>
          )}
        </>
      )}
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Spotify Panel
// ─────────────────────────────────────────────────────────────────────────────

function SpotifyPanel() {
  const [status, setStatus] = useState<SpotifyStatus | null>(null);
  const [searchQ, setSearchQ] = useState("");
  const [results, setResults] = useState<SpotifyTrack[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const refresh = useCallback(async () => {
    try { setStatus(await spotifyStatus()); } catch { /* ignore */ }
  }, []);

  useEffect(() => {
    void refresh();
    const id = setInterval(() => void refresh(), 5000);
    return () => clearInterval(id);
  }, [refresh]);

  const connect = async () => {
    setError("");
    try {
      const r = await spotifyAuth();
      await openUrl(r.url);
      setTimeout(() => void refresh(), 5000);
    } catch (e) { setError(String(e)); }
  };

  const control = async (action: "play" | "pause" | "next" | "prev") => {
    try { await spotifyControl(action); setTimeout(() => void refresh(), 600); }
    catch (e) { setError(String(e)); }
  };

  const search = async () => {
    if (!searchQ.trim()) return;
    setLoading(true);
    try {
      const r = await spotifySearch(searchQ);
      setResults(r.results);
    } catch (e) { setError(String(e)); }
    finally { setLoading(false); }
  };

  const play = async (uri: string) => {
    try { await spotifyPlay(uri); setTimeout(() => void refresh(), 600); }
    catch (e) { setError(String(e)); }
  };

  if (!status?.configured) {
    return (
      <div className="skills__panel-body">
        <div className="skills__connect-area">
          <div className="skills__connect-icon">🎵</div>
          <div className="skills__connect-label">
            Add <code>SPOTIFY_CLIENT_ID</code> and <code>SPOTIFY_CLIENT_SECRET</code> to <code>engine/.env</code>, then connect.
          </div>
          {error && <div className="skills__error">{error}</div>}
        </div>
      </div>
    );
  }

  if (!status.authenticated) {
    return (
      <div className="skills__panel-body">
        <div className="skills__connect-area">
          <div className="skills__connect-icon">🎵</div>
          <div className="skills__connect-label">Connect your Spotify account to control playback.</div>
          <button className="skills__btn skills__btn--spotify" onClick={() => void connect()}>
            Connect Spotify
          </button>
          {error && <div className="skills__error">{error}</div>}
        </div>
      </div>
    );
  }

  return (
    <div className="skills__panel-body">
      {/* Now playing */}
      {status.track && (
        <div className="skills__spotify-card">
          {status.track.image
            ? <img src={status.track.image} alt="" className="skills__spotify-art" />
            : <div className="skills__spotify-art" />}
          <div className="skills__spotify-info">
            <div className="skills__spotify-track">{status.track.name}</div>
            <div className="skills__spotify-artist">{status.track.artist} · {status.track.album}</div>
            <div style={{ fontSize: 10, color: "rgba(200,200,200,0.4)", marginTop: 4 }}>
              {fmtMs(status.track.progress_ms ?? 0)} / {fmtMs(status.track.duration_ms)}
            </div>
          </div>
          <div className="skills__spotify-controls">
            <button className="skills__spotify-ctrl" onClick={() => void control("prev")}>⏮</button>
            <button className="skills__spotify-ctrl" onClick={() => void control(status.is_playing ? "pause" : "play")}>
              {status.is_playing ? "⏸" : "▶"}
            </button>
            <button className="skills__spotify-ctrl" onClick={() => void control("next")}>⏭</button>
          </div>
        </div>
      )}

      {/* Search */}
      <div className="skills__search-row">
        <input className="skills__input" value={searchQ} onChange={(e) => setSearchQ(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && void search()} placeholder="Search tracks…" />
        <button className="skills__btn" onClick={() => void search()} disabled={loading}>Search</button>
      </div>
      {error && <div className="skills__error">{error}</div>}
      <div className="skills__result-list">
        {results.map((t) => (
          <div key={t.uri} className="skills__track-row" onClick={() => void play(t.uri)}>
            {t.image
              ? <img src={t.image} alt="" className="skills__track-img" />
              : <div className="skills__track-img" />}
            <div style={{ flex: 1 }}>
              <div className="skills__track-name">{t.name}</div>
              <div className="skills__track-artist">{t.artist} · {t.album}</div>
            </div>
            <div style={{ fontSize: 10, color: "rgba(200,200,200,0.35)" }}>{fmtMs(t.duration_ms)}</div>
          </div>
        ))}
      </div>

      <div className="skills__row" style={{ marginTop: "auto", paddingTop: 8 }}>
        <button className="skills__btn skills__btn--danger" onClick={async () => { await spotifyDisconnect(); void refresh(); }}>
          Disconnect
        </button>
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Calendar Panel
// ─────────────────────────────────────────────────────────────────────────────

function CalendarPanel() {
  const [status, setStatus] = useState<{ configured: boolean; authenticated: boolean } | null>(null);
  const [events, setEvents] = useState<CalEvent[]>([]);
  const [showAdd, setShowAdd] = useState(false);
  const [newSummary, setNewSummary] = useState("");
  const [newStart, setNewStart] = useState("");
  const [newEnd, setNewEnd] = useState("");
  const [newDesc, setNewDesc] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const refresh = useCallback(async () => {
    try {
      const s = await calendarStatus();
      setStatus(s);
      if (s.authenticated) {
        const r = await calendarEvents(20, 30);
        setEvents(r.events);
      }
    } catch { /* ignore */ }
  }, []);

  useEffect(() => { void refresh(); }, [refresh]);

  const connect = async () => {
    setError("");
    try {
      const r = await calendarAuth();
      await openUrl(r.url);
      setTimeout(() => void refresh(), 8000);
    } catch (e) { setError(String(e)); }
  };

  const addEvent = async () => {
    if (!newSummary.trim() || !newStart || !newEnd) return;
    setLoading(true); setError("");
    try {
      await calendarCreateEvent(newSummary, newStart, newEnd, newDesc);
      setShowAdd(false); setNewSummary(""); setNewStart(""); setNewEnd(""); setNewDesc("");
      await refresh();
    } catch (e) { setError(String(e)); }
    finally { setLoading(false); }
  };

  const delEvent = async (id: string) => {
    try { await calendarDeleteEvent(id); setEvents((p) => p.filter((e) => e.id !== id)); }
    catch (e) { setError(String(e)); }
  };

  if (!status?.configured) {
    return (
      <div className="skills__panel-body">
        <div className="skills__connect-area">
          <div className="skills__connect-icon">📅</div>
          <div className="skills__connect-label">
            Add <code>GOOGLE_CALENDAR_CLIENT_ID</code> and <code>GOOGLE_CALENDAR_CLIENT_SECRET</code> to <code>engine/.env</code>, then connect.
          </div>
          {error && <div className="skills__error">{error}</div>}
        </div>
      </div>
    );
  }

  if (!status.authenticated) {
    return (
      <div className="skills__panel-body">
        <div className="skills__connect-area">
          <div className="skills__connect-icon">📅</div>
          <div className="skills__connect-label">Connect your Google account to view and manage calendar events.</div>
          <button className="skills__btn" onClick={() => void connect()}>Connect Google Calendar</button>
          {error && <div className="skills__error">{error}</div>}
        </div>
      </div>
    );
  }

  return (
    <div className="skills__panel-body">
      <div className="skills__row">
        <button className="skills__btn skills__btn--green" onClick={() => setShowAdd((p) => !p)}>
          {showAdd ? "Cancel" : "+ Add Event"}
        </button>
        <button className="skills__btn" onClick={() => void refresh()} style={{ marginLeft: "auto" }}>↺</button>
      </div>
      {error && <div className="skills__error">{error}</div>}

      {showAdd && (
        <div style={{ display: "flex", flexDirection: "column", gap: 8, background: "rgba(255,255,255,0.03)", border: "1px solid rgba(255,255,255,0.08)", borderRadius: 6, padding: 12 }}>
          <input className="skills__input" placeholder="Event title" value={newSummary} onChange={(e) => setNewSummary(e.target.value)} />
          <div className="skills__row">
            <div style={{ flex: 1 }}>
              <div className="skills__label">Start (ISO 8601 UTC)</div>
              <input className="skills__input" value={newStart} onChange={(e) => setNewStart(e.target.value)} placeholder="2026-06-01T10:00:00Z" />
            </div>
            <div style={{ flex: 1 }}>
              <div className="skills__label">End</div>
              <input className="skills__input" value={newEnd} onChange={(e) => setNewEnd(e.target.value)} placeholder="2026-06-01T11:00:00Z" />
            </div>
          </div>
          <textarea className="skills__textarea" placeholder="Description (optional)" value={newDesc} onChange={(e) => setNewDesc(e.target.value)} />
          <button className="skills__btn skills__btn--green" onClick={() => void addEvent()} disabled={loading}>
            {loading ? "Adding…" : "Add Event"}
          </button>
        </div>
      )}

      <div className="skills__event-list">
        {events.length === 0 && <div className="skills__connect-label">No upcoming events in the next 30 days.</div>}
        {events.map((ev) => (
          <div key={ev.id} className="skills__event-card">
            <div className="skills__event-time">{fmtDate(ev.start)}</div>
            <div style={{ flex: 1 }}>
              <div className="skills__event-title">{ev.summary}</div>
              {ev.location && <div className="skills__event-loc">📍 {ev.location}</div>}
            </div>
            <button className="skills__copy-btn" onClick={() => void delEvent(ev.id)}>✕</button>
          </div>
        ))}
      </div>

      <div className="skills__row" style={{ marginTop: "auto", paddingTop: 8 }}>
        <button className="skills__btn skills__btn--danger" onClick={async () => { await calendarDisconnect(); void refresh(); }}>
          Disconnect
        </button>
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Main SkillsView
// ─────────────────────────────────────────────────────────────────────────────

type SkillId = "search" | "reports" | "files" | "spotify" | "calendar";

interface SkillMeta {
  id: SkillId;
  label: string;
  icon: string;
  connected?: boolean;
}

const SKILL_META: SkillMeta[] = [
  { id: "search", label: "Web Search", icon: "🔍" },
  { id: "reports", label: "Reports", icon: "📄" },
  { id: "files", label: "Files", icon: "🗂" },
  { id: "spotify", label: "Spotify", icon: "🎵" },
  { id: "calendar", label: "Calendar", icon: "📅" },
];

const PANEL_TITLE: Record<SkillId, string> = {
  search: "Web Search",
  reports: "Report Generator",
  files: "File Explorer",
  spotify: "Spotify",
  calendar: "Google Calendar",
};

export function SkillsView() {
  const [active, setActive] = useState<SkillId>("search");
  const [caps, setCaps] = useState<Record<string, boolean>>({});

  useEffect(() => {
    void fetchCapabilities().then((r) => {
      const m: Record<string, boolean> = {};
      for (const c of r.capabilities) m[c.name] = c.connected;
      setCaps(m);
    }).catch(() => {});
  }, []);

  const meta = SKILL_META.map((s) => ({
    ...s,
    connected: caps[s.id] ?? false,
  }));

  return (
    <div className="skills">
      <aside className="skills__sidebar">
        {meta.map((s) => (
          <button
            key={s.id}
            className={`skills__skill-btn${active === s.id ? " is-active" : ""}`}
            onClick={() => setActive(s.id)}
          >
            <span className="skills__skill-icon">{s.icon}</span>
            {s.label}
            <span className={`skills__skill-dot skills__skill-dot--${s.connected ? "on" : "off"}`} />
          </button>
        ))}
      </aside>

      <div className="skills__panel">
        <div className="skills__panel-header">
          <span className="skills__panel-icon">{SKILL_META.find((s) => s.id === active)?.icon}</span>
          {PANEL_TITLE[active]}
        </div>
        {active === "search" && <WebSearchPanel />}
        {active === "reports" && <ReportsPanel />}
        {active === "files" && <FilesPanel />}
        {active === "spotify" && <SpotifyPanel />}
        {active === "calendar" && <CalendarPanel />}
      </div>
    </div>
  );
}

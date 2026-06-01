// OSINT view — severity filter bar, zoomable map, expandable news cards,
// and a slide-in AI chat panel grounded in the indexed articles.

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

function stripHtml(s: string): string {
  return s
    .replace(/<[^>]*>/g, "")
    .replace(/&amp;/g, "&").replace(/&lt;/g, "<").replace(/&gt;/g, ">")
    .replace(/&quot;/g, '"').replace(/&#39;/g, "'")
    .trim();
}
import { WorldMap } from "./WorldMap";
import { SEVERITY_TIERS, severityColor, severityTier } from "./countries";
import {
  getCountryArticles,
  getDomains,
  getEvents,
  getHeatmap,
  getNaval,
  getTimeline,
  streamOsintChat,
  type Article,
  type GeoEvent,
  type Heatmap,
  type OsintChatTurn,
  type ShipPosition,
  type SourceDomain,
  type Timeline,
} from "./osint";
import { MarkdownView } from "../components/MarkdownView";
import { MicButton } from "../components/MicButton";
import { getConfig } from "../config";
import { useTTS } from "../voice/useTTS";
import "./Osint.css";

async function openUrl(url: string) {
  try {
    const { openUrl: tauriOpenUrl } = await import("@tauri-apps/plugin-opener");
    await tauriOpenUrl(url);
  } catch {
    window.open(url, "_blank", "noreferrer");
  }
}

async function emitMascotEvent(name: string, payload?: unknown) {
  // BroadcastChannel reaches the widget window reliably across Tauri WebView2 windows
  try {
    const ch = new BroadcastChannel("max:mascot");
    ch.postMessage({ type: name, payload });
    ch.close();
  } catch { /* not supported */ }
  try {
    const { emit } = await import("@tauri-apps/api/event");
    await emit(name, payload);
  } catch { /* not in Tauri */ }
}

type Selection = { iso: string; name: string } | null;
const ALL_SEVERITIES = new Set(SEVERITY_TIERS.map((t) => t.level));

function timeAgo(iso: string | null): string {
  if (!iso) return "";
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return "";
  const mins = Math.round((Date.now() - t) / 60000);
  if (mins < 1) return "now";
  if (mins < 60) return `${mins}m`;
  const hrs = Math.round(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  return `${Math.round(hrs / 24)}d ago`;
}

function clockLabel(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

// ── Political lean lookup ─────────────────────────────────────────────────────
// Scores: -1.0 = far left, 0.0 = center, +1.0 = far right
// Based on AllSides / Media Bias Fact Check approximations.
const LEAN_DB: Record<string, number> = {
  // Center / slight lean
  "reuters.com": -0.05, "apnews.com": -0.1, "thehill.com": -0.05,
  "axios.com": -0.1, "usatoday.com": -0.15, "newsweek.com": -0.2,
  "bbc.com": -0.2, "bbc.co.uk": -0.2, "politico.com": -0.2,
  "businessinsider.com": -0.2, "wsj.com": 0.25, "reason.com": 0.3,
  "nypost.com": 0.4, "msn.com": -0.1,
  // Center-left
  "npr.org": -0.3, "cbsnews.com": -0.3, "nbcnews.com": -0.35,
  "abcnews.go.com": -0.35, "time.com": -0.3, "theatlantic.com": -0.4,
  "aljazeera.com": -0.3, "cbc.ca": -0.2, "globalnews.ca": -0.2,
  "independent.co.uk": -0.35, "telegraph.co.uk": 0.4,
  // Left
  "nytimes.com": -0.45, "washingtonpost.com": -0.5, "theguardian.com": -0.6,
  "cnn.com": -0.55, "msnbc.com": -0.7, "huffpost.com": -0.7,
  "huffingtonpost.com": -0.7, "vox.com": -0.65, "slate.com": -0.65,
  "motherjones.com": -0.8, "thenation.com": -0.8,
  // Right
  "foxnews.com": 0.65, "washingtonexaminer.com": 0.6,
  "nationalreview.com": 0.65, "washingtontimes.com": 0.6,
  "dailycaller.com": 0.7, "thefederalist.com": 0.75,
  "townhall.com": 0.75, "pjmedia.com": 0.7,
  "dailywire.com": 0.8, "breitbart.com": 0.9,
};

function domainLean(domain: string): number | null {
  const d = domain.replace(/^www\./, "");
  if (d in LEAN_DB) return LEAN_DB[d];
  const parts = d.split(".");
  if (parts.length > 2) {
    const base = parts.slice(-2).join(".");
    if (base in LEAN_DB) return LEAN_DB[base];
  }
  return null;
}

function LeanBar({ domain }: { domain: string }) {
  const lean = domainLean(domain);
  if (lean === null) return null;
  const pct = ((lean + 1) / 2) * 100;
  return (
    <div className="news-card__lean">
      <span className="news-card__lean-l">L</span>
      <div className="news-card__lean-track">
        <div className="news-card__lean-dot" style={{ left: `${pct}%` }} />
      </div>
      <span className="news-card__lean-r">R</span>
    </div>
  );
}

// ── News card ─────────────────────────────────────────────────────────────────
function ArticleCard({ article, expanded, onToggle }: {
  article: Article;
  expanded: boolean;
  onToggle: () => void;
}) {
  const color = severityColor(article.severity);
  const tier  = severityTier(article.severity);
  const cardRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (expanded) cardRef.current?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }, [expanded]);

  return (
    <div
      ref={cardRef}
      className={`news-card${expanded ? " is-open" : ""}`}
      style={{ ["--tier-color" as string]: color }}
      onClick={onToggle}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => e.key === "Enter" && onToggle()}
    >
      {/* header — always visible */}
      <div className="news-card__head">
        <span className="news-card__tier" title={tier.label} />
        <span className="news-card__headline">{stripHtml(article.title)}</span>
        <span className="news-card__chevron">{expanded ? "▲" : "▼"}</span>
      </div>

      {/* political lean slider — shown when source is known */}
      <LeanBar domain={article.domain} />

      {/* expanded body */}
      {expanded && (
        <div className="news-card__body" onClick={(e) => e.stopPropagation()}>
          {article.image && (
            <img
              className="news-card__img"
              src={article.image}
              alt=""
              loading="lazy"
              onError={(e) => { (e.target as HTMLImageElement).style.display = "none"; }}
            />
          )}
          {article.summary && (
            <p className="news-card__summary">{article.summary}</p>
          )}
          <div className="news-card__foot">
            <span className="news-card__meta">
              <span className={`osint__src osint__src--${article.origin}`}>{article.domain}</span>
              <span className="news-card__time">{timeAgo(article.published)}</span>
            </span>
            <button
              className="news-card__link"
              onClick={() => void openUrl(article.url)}
            >
              Read article ↗
            </button>
          </div>
        </div>
      )}

      {/* collapsed meta line */}
      {!expanded && (
        <div className="news-card__meta-row">
          <span className={`osint__src osint__src--${article.origin}`}>{article.domain}</span>
          <span className="news-card__time">{timeAgo(article.published)}</span>
        </div>
      )}
    </div>
  );
}

// ── Main view ────────────────────────────────────────────────────────────────
export function OsintView({ onClose }: { onClose?: () => void }) {
  const [heatmap,  setHeatmap]  = useState<Heatmap | null>(null);
  const [loading,  setLoading]  = useState(true);
  const [selected, setSelected] = useState<Selection>(null);
  const [articles, setArticles] = useState<Article[]>([]);
  const [articlesBusy, setArticlesBusy] = useState(false);
  const [active,   setActive]   = useState<Set<number>>(new Set(ALL_SEVERITIES));
  const [ships,    setShips]    = useState<ShipPosition[]>([]);
  const [showFleet, setShowFleet] = useState(true);
  const [geoEvents, setGeoEvents] = useState<GeoEvent[]>([]);
  const [showEvents, setShowEvents] = useState(true);
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [eventDetail, setEventDetail] = useState<GeoEvent[] | null>(null);

  // ── Time-scrubber (24h heat replay) ────────────────────────────────────────
  const [timeline, setTimeline] = useState<Timeline | null>(null);
  const [frameIdx, setFrameIdx] = useState<number | null>(null); // null = live (now)
  const [playing, setPlaying] = useState(false);

  // ── Per-source domain toggles ──────────────────────────────────────────────
  const [domainList, setDomainList] = useState<SourceDomain[]>([]);
  const [muted, setMuted] = useState<Set<string>>(new Set());
  const [sourcesOpen, setSourcesOpen] = useState(false);
  // Allowlist passed to the engine; undefined when nothing is muted (use full set).
  const allowedDomains = useMemo(
    () => domainList.filter((d) => !muted.has(d.domain)).map((d) => d.domain),
    [domainList, muted],
  );
  const domainsArgRef = useRef<string[] | undefined>(undefined);
  domainsArgRef.current = muted.size > 0 ? allowedDomains : undefined;

  // ── AI Chat panel ────────────────────────────────────────────────────────
  const [chatOpen, setChatOpen] = useState(false);
  const [chatMsgs, setChatMsgs] = useState<OsintChatTurn[]>([]);
  const [chatInput, setChatInput] = useState("");
  const [chatBusy, setChatBusy] = useState(false);
  const chatAbort = useRef<AbortController | null>(null);
  const chatThreadRef = useRef<HTMLDivElement | null>(null);

  // ── Voice ────────────────────────────────────────────────────────────────
  const { speak, stop: stopTTS } = useTTS();
  const [sttProvider, setSttProvider] = useState("web");
  const [ttsEnabled, setTtsEnabled] = useState(true);
  const [ttsRate, setTtsRate] = useState(1.0);
  const [ttsPitch, setTtsPitch] = useState(1.0);
  const [ttsVoiceName, setTtsVoiceName] = useState("");

  useEffect(() => {
    void (async () => {
      const cfg = await getConfig();
      if (!cfg) return;
      setSttProvider(cfg.voice.stt_provider);
      setTtsEnabled(cfg.voice.tts_enabled);
      setTtsRate(cfg.voice.tts_rate);
      setTtsPitch(cfg.voice.tts_pitch);
      setTtsVoiceName(cfg.voice.tts_voice_name);
    })();
  }, []);

  useEffect(() => {
    if (chatThreadRef.current) {
      chatThreadRef.current.scrollTop = chatThreadRef.current.scrollHeight;
    }
  }, [chatMsgs]);

  const sendChat = async () => {
    const q = chatInput.trim();
    if (!q || chatBusy) return;
    const history: OsintChatTurn[] = [...chatMsgs, { role: "user", content: q }];
    setChatMsgs([...history, { role: "assistant", content: "" }]);
    setChatInput("");
    setChatBusy(true);
    stopTTS();
    void emitMascotEvent("mascot:signal");
    void emitMascotEvent("mascot:thinking", true);
    const ctrl = new AbortController();
    chatAbort.current = ctrl;
    let fullResponse = "";
    try {
      for await (const delta of streamOsintChat(history, selected?.iso ?? null, ctrl.signal)) {
        fullResponse += delta;
        setChatMsgs((prev) => {
          const next = prev.slice();
          const last = next[next.length - 1];
          next[next.length - 1] = { ...last, content: last.content + delta };
          return next;
        });
      }
      if (ttsEnabled && fullResponse) {
        speak(fullResponse, { rate: ttsRate, pitch: ttsPitch, voiceName: ttsVoiceName || undefined });
      }
    } catch (e) {
      if (!ctrl.signal.aborted) {
        setChatMsgs((prev) => {
          const next = prev.slice();
          next[next.length - 1] = { role: "assistant", content: `⚠ ${(e as Error).message}` };
          return next;
        });
      }
    } finally {
      setChatBusy(false);
      chatAbort.current = null;
      void emitMascotEvent("mascot:thinking", false);
    }
  };

  useEffect(() => () => { chatAbort.current?.abort(); }, []);

  const loadHeatmap = useCallback(async () => {
    setLoading(true);
    setHeatmap(await getHeatmap(domainsArgRef.current));
    setLoading(false);
  }, []);

  const loadArticles = useCallback(async (iso: string | null) => {
    setArticlesBusy(true);
    setExpanded(new Set()); // collapse all cards on country switch
    setArticles(await getCountryArticles(iso, 40, domainsArgRef.current));
    setArticlesBusy(false);
  }, []);

  useEffect(() => {
    void loadHeatmap();
    void loadArticles(null);
    void (async () => { const d = await getNaval();  if (d) setShips(d.ships); })();
    void (async () => { const d = await getEvents(); if (d) setGeoEvents(d.events); })();
    void (async () => { setTimeline(await getTimeline()); })();
    void (async () => { setDomainList(await getDomains()); })();
  }, [loadHeatmap, loadArticles]);

  // Re-filter heat + articles when the source allowlist changes (skip first run;
  // the mount effect already did the initial load).
  const mutedFirstRun = useRef(true);
  useEffect(() => {
    if (mutedFirstRun.current) { mutedFirstRun.current = false; return; }
    void loadHeatmap();
    void loadArticles(selected?.iso ?? null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [muted]);

  // Scrubber playback: advance one frame at a time, snapping back to live at the end.
  useEffect(() => {
    if (!playing || !timeline) return;
    const id = window.setInterval(() => {
      setFrameIdx((idx) => {
        const cur = idx === null ? 0 : idx + 1;
        if (cur >= timeline.frames.length - 1) { setPlaying(false); return null; }
        return cur;
      });
    }, 650);
    return () => window.clearInterval(id);
  }, [playing, timeline]);

  const onSelect = (iso: string, name: string) => {
    setSelected({ iso, name });
    void loadArticles(iso);
  };

  const clearSelection = () => {
    setSelected(null);
    void loadArticles(null);
  };

  const refresh = () => {
    void loadHeatmap();
    void loadArticles(selected?.iso ?? null);
    void (async () => { setTimeline(await getTimeline()); })();
    void (async () => { setDomainList(await getDomains()); })();
    setFrameIdx(null);
    setPlaying(false);
  };

  const toggleDomain = (domain: string) => {
    setMuted((prev) => {
      const next = new Set(prev);
      if (next.has(domain)) next.delete(domain); else next.add(domain);
      return next;
    });
  };

  const scrubTo = (idx: number) => {
    setPlaying(false);
    // Far-right of the track == back to live.
    setFrameIdx(timeline && idx >= timeline.frames.length - 1 ? null : idx);
  };

  const toggleSeverity = (level: number) => {
    setActive((prev) => {
      const next = new Set(prev);
      if (next.has(level)) next.delete(level); else next.add(level);
      return next.size === 0 ? new Set(ALL_SEVERITIES) : next;
    });
  };

  const toggleCard = (url: string) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(url)) next.delete(url); else next.add(url);
      return next;
    });
  };

  const offline  = !loading && heatmap === null;
  const live     = heatmap?.countries ?? [];
  // When scrubbing, the map + hotspots reflect the selected historical frame.
  const frame    = frameIdx !== null ? timeline?.frames[frameIdx] : undefined;
  const all      = frame ? frame.countries : live;
  const counts   = useMemo(() => {
    const m = new Map<number, number>();
    for (const c of all) m.set(c.severity, (m.get(c.severity) ?? 0) + 1);
    return m;
  }, [all]);
  const visibleCountries = useMemo(() => all.filter((c) => active.has(c.severity)), [all, active]);
  const top = visibleCountries.slice(0, 8);
  const visibleArticles  = useMemo(
    () => articles.filter((a) => active.has(a.severity)),
    [articles, active],
  );

  return (
    <div className="osint">
      {/* ── AI chat slide-in panel ── */}
      <div className={`osint__chat-panel${chatOpen ? " is-open" : ""}`}>
        <div className="osint__chat-head">
          <span className="osint__chat-title">
            ✦ OSINT Intel AI
            {selected && <span className="osint__chat-scope"> · {selected.name}</span>}
          </span>
          <button className="osint__chat-close" onClick={() => setChatOpen(false)}>×</button>
        </div>
        <div className="osint__chat-thread" ref={chatThreadRef}>
          {chatMsgs.length === 0 && (
            <div className="osint__chat-placeholder">
              Ask anything about current intelligence. I'll cross-reference indexed
              articles with broader knowledge to give you the full picture.
            </div>
          )}
          {chatMsgs.map((m, i) => (
            <div key={i} className={`osint__chat-msg osint__chat-msg--${m.role}`}>
              {m.role === "assistant" ? (
                m.content ? (
                  <MarkdownView source={m.content} />
                ) : (
                  <span className="osint__chat-cursor">▍</span>
                )
              ) : (
                m.content
              )}
            </div>
          ))}
        </div>
        <div className="osint__chat-input">
          <MicButton
            onTranscript={(text) => setChatInput(text)}
            sttProvider={sttProvider}
            stopTTS={stopTTS}
            disabled={chatBusy}
          />
          <input
            className="osint__chat-text"
            value={chatInput}
            onChange={(e) => setChatInput(e.target.value)}
            onKeyDown={(e) =>
              e.key === "Enter" && !e.shiftKey && (e.preventDefault(), void sendChat())
            }
            placeholder={`Ask about ${selected ? selected.name : "global"} intel…`}
            disabled={chatBusy}
          />
          <button
            className="osint__chat-send"
            onClick={() => void sendChat()}
            disabled={chatBusy || !chatInput.trim()}
          >
            {chatBusy ? "…" : "▶"}
          </button>
        </div>
      </div>

      {/* ── header bar ── */}
      <header className="osint__bar">
        <div className="osint__title">
          <span className="osint__glyph">◉</span> OSINT · Global Threat Intercept
        </div>

        <div className="osint__filters">
          {SEVERITY_TIERS.map((t) => {
            const on = active.has(t.level);
            return (
              <button key={t.key}
                className={`osint__sev${on ? " is-on" : ""}`}
                style={on ? { ["--sev" as string]: t.color } : undefined}
                onClick={() => toggleSeverity(t.level)}
                title={`${on ? "Hide" : "Show"} ${t.label}`}
              >
                <span className="osint__sev-dot" style={{ background: t.color }} />
                {t.label}
                <span className="osint__sev-n">{counts.get(t.level) ?? 0}</span>
              </button>
            );
          })}
        </div>

        <div className="osint__bar-right">
          <button className={`osint__layer-btn${showEvents ? " is-on" : ""}`}
            onClick={() => setShowEvents((v) => !v)}
            title="Earthquakes + disaster alerts"
            style={showEvents ? { ["--layer-color" as string]: "#f97316" } : undefined}
          >
            ⚡ Events <span className="osint__sev-n">{geoEvents.length}</span>
          </button>
          <button className={`osint__layer-btn${showFleet ? " is-on" : ""}`}
            onClick={() => setShowFleet((v) => !v)}
            title="US carrier / amphib positions — estimated"
            style={showFleet ? { ["--layer-color" as string]: "#ffe27a" } : undefined}
          >
            ⚓ Fleet <span className="osint__sev-n">{ships.length}</span>
          </button>
          {domainList.length > 0 && (
            <div className="osint__sources-wrap">
              <button className={`osint__layer-btn${muted.size > 0 ? " is-on" : ""}`}
                onClick={() => setSourcesOpen((v) => !v)}
                title="Toggle individual news sources"
                style={muted.size > 0 ? { ["--layer-color" as string]: "#7dd3fc" } : undefined}
              >
                ⌗ Sources
                <span className="osint__sev-n">
                  {domainList.length - muted.size}/{domainList.length}
                </span>
              </button>
              {sourcesOpen && (
                <div className="osint__sources-pop">
                  <div className="osint__sources-head">
                    <span>News sources</span>
                    <div className="osint__sources-actions">
                      <button onClick={() => setMuted(new Set())} disabled={muted.size === 0}>All</button>
                      <button onClick={() => setMuted(new Set(domainList.map((d) => d.domain)))}
                        disabled={muted.size === domainList.length}>None</button>
                      <button className="osint__sources-x" onClick={() => setSourcesOpen(false)}>×</button>
                    </div>
                  </div>
                  <div className="osint__sources-list">
                    {domainList.map((d) => {
                      const on = !muted.has(d.domain);
                      return (
                        <label key={d.domain} className={`osint__source-row${on ? " is-on" : ""}`}>
                          <input type="checkbox" checked={on} onChange={() => toggleDomain(d.domain)} />
                          <span className={`osint__src osint__src--${d.origin}`}>{d.domain}</span>
                          <span className="osint__source-n">{d.count}</span>
                        </label>
                      );
                    })}
                  </div>
                </div>
              )}
            </div>
          )}
          <span className="osint__updated">
            {loading ? "loading…" : offline ? "engine offline"
              : `${heatmap?.totalArticles ?? 0} signals`}
          </span>
          <button
            className={`osint__btn osint__btn--chat${chatOpen ? " is-on" : ""}`}
            onClick={() => setChatOpen((v) => !v)}
            title="AI Chat"
          >
            ✦ Ask AI
          </button>
          <button className="osint__btn" onClick={refresh} title="Refresh">↻</button>
          {onClose && (
            <button className="osint__btn osint__btn--close" onClick={onClose} title="Close">×</button>
          )}
        </div>
      </header>

      {/* ── body ── */}
      <div className="osint__body">
        {/* map stage */}
        <div className="osint__stage">
          {selected && (
            <button className="osint__map-back" onClick={clearSelection}>
              ← {selected.name}
            </button>
          )}
          <WorldMap
            countries={all}
            selectedIso={selected?.iso ?? null}
            activeSeverities={active}
            ships={ships} showFleet={showFleet}
            geoEvents={geoEvents} showEvents={showEvents}
            onSelect={onSelect}
            onEventSelect={(evs) => setEventDetail(evs)}
          />

          {/* ── Event / cluster detail card ── */}
          {eventDetail && (
            <div className="osint__event-detail">
              <div className="osint__event-detail-head">
                <span>{eventDetail.length === 1 ? "Event detail" : `${eventDetail.length} clustered events`}</span>
                <button onClick={() => setEventDetail(null)}>×</button>
              </div>
              <div className="osint__event-detail-list">
                {eventDetail.map((ev) => (
                  <div key={ev.id} className="osint__event-item" style={{ ["--ev-color" as string]: ev.color }}>
                    <div className="osint__event-item-title">{ev.title}</div>
                    <div className="osint__event-item-meta">
                      <span className="osint__event-cat" style={{ color: ev.color }}>{ev.category}</span>
                      {ev.magnitude > 0 && <span>M{ev.magnitude.toFixed(1)}</span>}
                      <span className="osint__event-src">{ev.source}</span>
                      {ev.published && <span className="news-card__time">{timeAgo(ev.published)}</span>}
                    </div>
                    {ev.url && (
                      <button className="news-card__link" onClick={() => void openUrl(ev.url)}>
                        Read source ↗
                      </button>
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* ── 24h heat replay scrubber ── */}
          {timeline && timeline.frames.length > 1 && (
            <div className="osint__scrubber">
              <button className="osint__scrub-play" onClick={() => setPlaying((p) => !p)}
                title={playing ? "Pause" : "Play 24h replay"}>
                {playing ? "❚❚" : "▶"}
              </button>
              <input
                className="osint__scrub-range"
                type="range"
                min={0}
                max={timeline.frames.length - 1}
                value={frameIdx ?? timeline.frames.length - 1}
                onChange={(e) => scrubTo(Number(e.target.value))}
              />
              <span className={`osint__scrub-time${frame ? "" : " is-live"}`}>
                {frame ? clockLabel(frame.at) : "● LIVE"}
              </span>
            </div>
          )}

          {offline && (
            <div className="osint__offline-note">
              Engine offline — showing base map. Start Max engine for live intel.
            </div>
          )}
          <div className="osint__legend">
            <span className="osint__legend-dot osint__legend-dot--sun" /> subsolar
            <span className="osint__legend-night" /> night
            {showEvents && geoEvents.length > 0 && (
              <span className="osint__legend-event">⚡ {geoEvents.length} events</span>
            )}
            {showFleet && ships.length > 0 && (
              <span className="osint__legend-fleet">⚓ fleet est.</span>
            )}
          </div>

          {/* ── AI animated orb FAB ── */}
          <button
            className={`osint__ai-fab${chatOpen ? " is-on" : ""}`}
            onClick={() => setChatOpen((v) => !v)}
            title={chatOpen ? "Close AI chat" : "AI Chat"}
            aria-label="Toggle AI chat"
          >
            <span className="osint__ai-fab__fluid osint__ai-fab__fluid--a" />
            <span className="osint__ai-fab__fluid osint__ai-fab__fluid--b" />
            <span className="osint__ai-fab__fluid osint__ai-fab__fluid--c" />
            <span className="osint__ai-fab__gloss" />
          </button>
        </div>

        {/* side panel */}
        <aside className="osint__panel">
          <div className="osint__panel-head">
            <span className="osint__panel-title">{selected ? selected.name : "Hotspots"}</span>
          </div>

          {/* hotspot rank bars */}
          {!selected && top.length > 0 && (
            <ol className="osint__ranks">
              {top.map((c) => (
                <li key={c.iso}>
                  <button className="osint__rank" onClick={() => onSelect(c.iso, c.name)}>
                    <span className="osint__rank-bar"
                      style={{ width: `${Math.max(8, c.intensity * 100)}%`,
                               background: severityColor(c.severity) }} />
                    <span className="osint__rank-tier"
                      style={{ background: severityColor(c.severity) }} />
                    <span className="osint__rank-name">{c.name}</span>
                    <span className="osint__rank-n">{c.articleCount}</span>
                  </button>
                </li>
              ))}
            </ol>
          )}

          {/* news cards */}
          <div className="osint__articles">
            {articlesBusy ? (
              <div className="osint__hint">loading intel…</div>
            ) : visibleArticles.length === 0 ? (
              <div className="osint__hint">
                {selected ? "No articles match the current filter." : "No signals match the filter."}
              </div>
            ) : (
              visibleArticles.map((a) => (
                <ArticleCard
                  key={a.url}
                  article={a}
                  expanded={expanded.has(a.url)}
                  onToggle={() => toggleCard(a.url)}
                />
              ))
            )}
          </div>
        </aside>
      </div>
    </div>
  );
}

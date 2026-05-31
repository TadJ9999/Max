// OSINT view — severity filter bar, zoomable map, expandable news cards,
// and a slide-in AI chat panel grounded in the indexed articles.

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { WorldMap } from "./WorldMap";
import { SEVERITY_TIERS, severityColor, severityTier } from "./countries";
import {
  getCountryArticles,
  getEvents,
  getHeatmap,
  getNaval,
  streamOsintChat,
  type Article,
  type GeoEvent,
  type Heatmap,
  type OsintChatTurn,
  type ShipPosition,
} from "./osint";
import { MarkdownView } from "../components/MarkdownView";
import "./Osint.css";

async function emitMascotEvent(name: string, payload?: unknown) {
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

// ── News card ─────────────────────────────────────────────────────────────────
function ArticleCard({ article, expanded, onToggle }: {
  article: Article;
  expanded: boolean;
  onToggle: () => void;
}) {
  const color = severityColor(article.severity);
  const tier  = severityTier(article.severity);
  return (
    <div
      className={`news-card${expanded ? " is-open" : ""}`}
      style={{ ["--tier-color" as string]: color }}
      onClick={onToggle}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => e.key === "Enter" && onToggle()}
    >
      {/* collapsed header — always visible */}
      <div className="news-card__head">
        <span className="news-card__tier" title={tier.label} />
        <span className="news-card__headline">{article.title}</span>
        <span className="news-card__chevron">{expanded ? "▲" : "▼"}</span>
      </div>

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
            <a
              className="news-card__link"
              href={article.url}
              target="_blank"
              rel="noreferrer noopener"
            >
              Read article ↗
            </a>
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

  // ── AI Chat panel ────────────────────────────────────────────────────────
  const [chatOpen, setChatOpen] = useState(false);
  const [chatMsgs, setChatMsgs] = useState<OsintChatTurn[]>([]);
  const [chatInput, setChatInput] = useState("");
  const [chatBusy, setChatBusy] = useState(false);
  const chatAbort = useRef<AbortController | null>(null);
  const chatThreadRef = useRef<HTMLDivElement | null>(null);

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
    void emitMascotEvent("mascot:signal");
    void emitMascotEvent("mascot:thinking", true);
    const ctrl = new AbortController();
    chatAbort.current = ctrl;
    try {
      for await (const delta of streamOsintChat(history, selected?.iso ?? null, ctrl.signal)) {
        setChatMsgs((prev) => {
          const next = prev.slice();
          const last = next[next.length - 1];
          next[next.length - 1] = { ...last, content: last.content + delta };
          return next;
        });
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
    setHeatmap(await getHeatmap());
    setLoading(false);
  }, []);

  const loadArticles = useCallback(async (iso: string | null) => {
    setArticlesBusy(true);
    setExpanded(new Set()); // collapse all cards on country switch
    setArticles(await getCountryArticles(iso));
    setArticlesBusy(false);
  }, []);

  useEffect(() => {
    void loadHeatmap();
    void loadArticles(null);
    void (async () => { const d = await getNaval();  if (d) setShips(d.ships); })();
    void (async () => { const d = await getEvents(); if (d) setGeoEvents(d.events); })();
  }, [loadHeatmap, loadArticles]);

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
  const all      = heatmap?.countries ?? [];
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
          />
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

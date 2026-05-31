import { useEffect, useRef, useState } from "react";
import { type TorStatus, type FetchResult, type SearchResult, getTorStatus, newCircuit, searchDark, streamFetchUrl } from "./shadownet";
import "./ShadowNet.css";

// Mascot signal helper (same pattern as other Hub features)
async function emitMascotEvent(name: string, payload?: unknown) {
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

// Tauri command — propagates errors so the caller can surface them. Throws
// "not in Tauri" when the API isn't available (e.g. browser preview).
async function invokeTauri(cmd: string, args?: Record<string, unknown>): Promise<unknown> {
  const { invoke } = await import("@tauri-apps/api/core");
  return await invoke(cmd, args ?? {});
}

const SEARCH_ENGINES = [
  { label: "Ahmia", url: "https://ahmia.fi/search/?q=" },
  { label: "DuckDuckGo", url: "https://duckduckgogg42xjoc72x3sjasowoarfbgcmvfimaftt6twagswzczad.onion/?q=" },
];

// ---- per-tab browser state ----------------------------------------------
type LoadState = "idle" | "loading" | "done" | "error";
interface BrowserTab {
  id: number;
  title: string;
  history: string[];
  idx: number;
  page: FetchResult | null;
  loadState: LoadState;
  loadError: string | null;
  addrInput: string;
  searchResults: SearchResult[];
}

interface Bookmark {
  url: string;
  title: string;
}

const BOOKMARKS_KEY = "max:shadow:bookmarks";

function hostOf(url: string): string {
  try {
    return new URL(url).hostname;
  } catch {
    return url.slice(0, 24);
  }
}

function normalizeUrl(raw: string): string {
  const u = raw.trim();
  if (!u) return "";
  return u.startsWith("http://") || u.startsWith("https://") ? u : `https://${u}`;
}

let TAB_SEQ = 1;
function makeTab(): BrowserTab {
  return {
    id: TAB_SEQ++,
    title: "New Tab",
    history: [],
    idx: -1,
    page: null,
    loadState: "idle",
    loadError: null,
    addrInput: "",
    searchResults: [],
  };
}

export function ShadowNetView() {
  const [torStatus, setTorStatus] = useState<TorStatus | null>(null);
  const [connecting, setConnecting] = useState(false);
  const [connectError, setConnectError] = useState<string | null>(null);

  const [tabs, setTabs] = useState<BrowserTab[]>(() => [makeTab()]);
  const [activeId, setActiveId] = useState<number>(() => tabs[0]?.id ?? 1);

  const [searchQuery, setSearchQuery] = useState("");
  const [searching, setSearching] = useState(false);

  const [bookmarks, setBookmarks] = useState<Bookmark[]>(() => {
    try {
      return JSON.parse(localStorage.getItem(BOOKMARKS_KEY) ?? "[]");
    } catch {
      return [];
    }
  });
  const [showBookmarks, setShowBookmarks] = useState(false);

  const iframeRef = useRef<HTMLIFrameElement>(null);
  const tabAborts = useRef<Map<number, AbortController>>(new Map());

  const activeTab = tabs.find((t) => t.id === activeId) ?? tabs[0];
  const isConnected = torStatus?.circuit_established ?? false;

  // Poll Tor status every 3s
  useEffect(() => {
    let alive = true;
    const tick = async () => {
      const s = await getTorStatus();
      if (alive) setTorStatus(s);
    };
    void tick();
    const id = window.setInterval(() => void tick(), 3000);
    return () => { alive = false; window.clearInterval(id); };
  }, []);

  // ---- connect / disconnect -----------------------------------------------

  const connect = async () => {
    setConnecting(true);
    setConnectError(null);
    try {
      await invokeTauri("start_tor");
    } catch (e) {
      setConnectError(String(e));
    } finally {
      setConnecting(false);
    }
  };

  const disconnect = async () => {
    try {
      await invokeTauri("stop_tor");
    } catch { /* best-effort */ }
    for (const ac of tabAborts.current.values()) ac.abort();
    tabAborts.current.clear();
    setTorStatus(null);
    setTabs([makeTab()]);
  };

  // ---- tab state helpers --------------------------------------------------

  const updateTab = (id: number, patch: Partial<BrowserTab>) => {
    setTabs((prev) => prev.map((t) => (t.id === id ? { ...t, ...patch } : t)));
  };

  // Stream a URL into a tab WITHOUT touching its history (used by back/forward
  // and reload; navigate() handles the history push separately).
  const loadInto = (id: number, url: string) => {
    tabAborts.current.get(id)?.abort();
    const ac = new AbortController();
    tabAborts.current.set(id, ac);

    updateTab(id, { loadState: "loading", loadError: null, page: null, addrInput: url, searchResults: [] });
    void emitMascotEvent("mascot:tor-request");

    streamFetchUrl(
      url,
      {
        onStart: () => updateTab(id, { loadState: "loading" }),
        onHtml: (result) => {
          updateTab(id, { page: result, loadState: "done", title: result.title || hostOf(url) });
          void emitMascotEvent("mascot:tor-response");
        },
        onError: (msg) => updateTab(id, { loadState: "error", loadError: msg }),
      },
      ac.signal,
    );
  };

  // Navigate the active tab to a URL, pushing onto its history stack.
  const navigate = (rawUrl: string) => {
    const url = normalizeUrl(rawUrl);
    if (!url) return;
    const id = activeId;
    setTabs((prev) =>
      prev.map((t) => {
        if (t.id !== id) return t;
        const trimmed = t.history.slice(0, t.idx + 1);
        return { ...t, history: [...trimmed, url], idx: trimmed.length };
      }),
    );
    loadInto(id, url);
  };

  const goBack = () => {
    const t = activeTab;
    if (!t || t.idx <= 0) return;
    const ni = t.idx - 1;
    updateTab(t.id, { idx: ni });
    loadInto(t.id, t.history[ni]);
  };

  const goForward = () => {
    const t = activeTab;
    if (!t || t.idx >= t.history.length - 1) return;
    const ni = t.idx + 1;
    updateTab(t.id, { idx: ni });
    loadInto(t.id, t.history[ni]);
  };

  // ---- tab open / close / switch ------------------------------------------

  const openTab = () => {
    const t = makeTab();
    setTabs((prev) => [...prev, t]);
    setActiveId(t.id);
  };

  const closeTab = (id: number) => {
    tabAborts.current.get(id)?.abort();
    tabAborts.current.delete(id);
    setTabs((prev) => {
      const remaining = prev.filter((t) => t.id !== id);
      if (remaining.length === 0) {
        const fresh = makeTab();
        setActiveId(fresh.id);
        return [fresh];
      }
      if (id === activeId) {
        const closedIdx = prev.findIndex((t) => t.id === id);
        const neighbor = remaining[Math.min(closedIdx, remaining.length - 1)];
        setActiveId(neighbor.id);
      }
      return remaining;
    });
  };

  // ---- iframe link intercept ----------------------------------------------
  useEffect(() => {
    const iframe = iframeRef.current;
    if (!iframe || !activeTab?.page) return;
    const onLoad = () => {
      try {
        const doc = iframe.contentDocument;
        if (!doc) return;
        doc.addEventListener("click", (e) => {
          const a = (e.target as Element).closest("a");
          if (!a) return;
          e.preventDefault();
          const href = a.getAttribute("href") ?? "";
          const match = href.match(/\?url=(.+)/);
          if (match) navigate(decodeURIComponent(match[1]));
        });
      } catch { /* cross-origin — can't intercept */ }
    };
    iframe.addEventListener("load", onLoad);
    return () => iframe.removeEventListener("load", onLoad);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeTab?.page, activeId]);

  // ---- search -------------------------------------------------------------
  const runSearch = async (engine: typeof SEARCH_ENGINES[0]) => {
    if (!searchQuery.trim()) return;
    setSearching(true);
    updateTab(activeId, { searchResults: [], loadState: "idle" });
    const url = `${engine.url}${encodeURIComponent(searchQuery)}`;
    const results = await searchDark(searchQuery);
    setSearching(false);
    if (results.length > 0) {
      updateTab(activeId, { searchResults: results, addrInput: url, title: `Search: ${searchQuery}` });
    } else {
      navigate(url);
    }
  };

  // ---- Tor features -------------------------------------------------------
  const handleNewCircuit = async () => {
    await newCircuit();
    void getTorStatus().then((s) => s && setTorStatus(s));
  };

  const copyUrl = () => {
    const url = activeTab?.history[activeTab.idx];
    if (url) void navigator.clipboard?.writeText(url).catch(() => {});
  };

  const goHome = () => {
    updateTab(activeId, { loadState: "idle", page: null, searchResults: [], addrInput: "" });
  };

  const currentUrl = activeTab?.history[activeTab.idx] ?? null;
  const isBookmarked = currentUrl ? bookmarks.some((b) => b.url === currentUrl) : false;

  const toggleBookmark = () => {
    if (!currentUrl) return;
    setBookmarks((prev) => {
      const exists = prev.some((b) => b.url === currentUrl);
      const next = exists
        ? prev.filter((b) => b.url !== currentUrl)
        : [...prev, { url: currentUrl, title: activeTab?.title || hostOf(currentUrl) }];
      localStorage.setItem(BOOKMARKS_KEY, JSON.stringify(next));
      return next;
    });
  };

  // ---- bootstrap progress display -----------------------------------------
  const bootstrapPct = torStatus?.bootstrapped ?? 0;
  const isBootstrapping = torStatus?.running && !torStatus.circuit_established;

  // ---- render: connect screen ---------------------------------------------
  if (!isConnected) {
    return (
      <div className="shadow-connect">
        <div className="shadow-connect__orb">
          <svg viewBox="0 0 80 80" className="shadow-connect__logo" aria-label="Tor onion">
            <circle cx="40" cy="40" r="36" stroke="rgba(34,211,238,0.15)" strokeWidth="1.5" fill="none" />
            <circle cx="40" cy="40" r="28" stroke="rgba(34,211,238,0.25)" strokeWidth="1.5" fill="none" />
            <circle cx="40" cy="40" r="20" stroke="rgba(34,211,238,0.40)" strokeWidth="1.5" fill="none" />
            <circle cx="40" cy="40" r="12" stroke="rgba(34,211,238,0.65)" strokeWidth="1.5" fill="none" />
            <circle cx="40" cy="40" r="5" fill="rgba(34,211,238,0.85)" />
            <ellipse cx="40" cy="22" rx="4" ry="6" fill="rgba(34,211,238,0.18)" />
            <ellipse cx="40" cy="58" rx="4" ry="6" fill="rgba(34,211,238,0.18)" />
            <ellipse cx="22" cy="40" rx="6" ry="4" fill="rgba(34,211,238,0.18)" />
            <ellipse cx="58" cy="40" rx="6" ry="4" fill="rgba(34,211,238,0.18)" />
          </svg>
        </div>

        <h2 className="shadow-connect__title">SHADOW NET</h2>
        <p className="shadow-connect__sub">
          Route through the Secure network to access Dark Web sites and browse anonymously.
        </p>

        {isBootstrapping && (
          <div className="shadow-connect__progress">
            <div className="shadow-connect__progress-bar">
              <div className="shadow-connect__progress-fill" style={{ width: `${bootstrapPct}%` }} />
            </div>
            <span className="shadow-connect__progress-label">Bootstrapping: {bootstrapPct}%</span>
          </div>
        )}

        {connectError && <div className="shadow-connect__error">{connectError}</div>}

        <button
          className="shadow-connect__btn"
          onClick={() => void connect()}
          disabled={connecting || isBootstrapping}
        >
          {connecting || isBootstrapping ? "Connecting…" : "Connect"}
        </button>
      </div>
    );
  }

  // ---- render: browser ----------------------------------------------------
  return (
    <div className="shadow-browser">
      {/* ---- tab strip ---- */}
      <div className="shadow-tabs">
        <div className="shadow-tabs__list">
          {tabs.map((t) => (
            <div
              key={t.id}
              className={`shadow-tab${t.id === activeId ? " shadow-tab--active" : ""}`}
              onClick={() => setActiveId(t.id)}
              title={t.title}
            >
              {t.loadState === "loading" ? (
                <span className="shadow-tab__spin" />
              ) : (
                <span className="shadow-tab__glyph">⬡</span>
              )}
              <span className="shadow-tab__title">{t.title}</span>
              <button
                className="shadow-tab__close"
                onClick={(e) => { e.stopPropagation(); closeTab(t.id); }}
                title="Close tab"
              >
                ×
              </button>
            </div>
          ))}
          <button className="shadow-tabs__new" onClick={openTab} title="New tab">+</button>
        </div>
        <div className="shadow-tabs__status">
          <span className="shadow-statusbar__dot shadow-statusbar__dot--on" />
          <span>Tor</span>
          {torStatus?.exit_ip && <span className="shadow-statusbar__ip">{torStatus.exit_ip}</span>}
        </div>
      </div>

      {/* ---- address toolbar ---- */}
      <div className="shadow-toolbar">
        <button className="shadow-toolbar__nav" onClick={goBack} disabled={!activeTab || activeTab.idx <= 0} title="Back">←</button>
        <button className="shadow-toolbar__nav" onClick={goForward} disabled={!activeTab || activeTab.idx >= activeTab.history.length - 1} title="Forward">→</button>
        <button
          className="shadow-toolbar__nav"
          onClick={() => currentUrl && loadInto(activeId, currentUrl)}
          disabled={!currentUrl || activeTab?.loadState === "loading"}
          title="Reload"
        >
          ⟳
        </button>
        <input
          className="shadow-toolbar__addr"
          value={activeTab?.addrInput ?? ""}
          onChange={(e) => updateTab(activeId, { addrInput: e.target.value })}
          onKeyDown={(e) => { if (e.key === "Enter") navigate(activeTab?.addrInput ?? ""); }}
          placeholder=".onion or https://…"
          spellCheck={false}
        />
        <button className="shadow-toolbar__go" onClick={() => navigate(activeTab?.addrInput ?? "")}>Go</button>
      </div>

      {/* ---- Tor features bar (below address) ---- */}
      <div className="shadow-features">
        <button className="shadow-feat" onClick={() => void handleNewCircuit()} title="Request a new Tor circuit (new exit IP)">
          ⟲ New Identity
        </button>
        <button
          className={`shadow-feat${isBookmarked ? " shadow-feat--on" : ""}`}
          onClick={toggleBookmark}
          disabled={!currentUrl}
          title={isBookmarked ? "Remove bookmark" : "Bookmark this page"}
        >
          {isBookmarked ? "★" : "☆"} Bookmark
        </button>
        <button className="shadow-feat" onClick={() => setShowBookmarks((v) => !v)} title="Show bookmarks">
          ▤ Saved
        </button>
        <button className="shadow-feat" onClick={copyUrl} disabled={!currentUrl} title="Copy current URL">
          ⧉ Copy
        </button>
        <button className="shadow-feat" onClick={goHome} title="Home (new tab page)">⌂ Home</button>

        <div className="shadow-features__search">
          <input
            className="shadow-features__search-input"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter") void runSearch(SEARCH_ENGINES[0]); }}
            placeholder="Search dark web…"
          />
          {SEARCH_ENGINES.map((eng) => (
            <button
              key={eng.label}
              className="shadow-feat shadow-feat--search"
              onClick={() => void runSearch(eng)}
              disabled={searching || !searchQuery.trim()}
            >
              {eng.label}
            </button>
          ))}
        </div>

        <div className="shadow-features__spacer" />
        {torStatus?.circuit_age_seconds !== undefined && (
          <span className="shadow-features__age">
            ⏱ {Math.floor(torStatus.circuit_age_seconds / 60)}m {torStatus.circuit_age_seconds % 60}s
          </span>
        )}
        <button className="shadow-feat shadow-feat--disc" onClick={() => void disconnect()} title="Disconnect Tor">
          ⏻ Disconnect
        </button>
      </div>

      {/* ---- bookmarks dropdown ---- */}
      {showBookmarks && (
        <div className="shadow-bookmarks">
          {bookmarks.length === 0 ? (
            <div className="shadow-bookmarks__empty">No bookmarks yet — press ☆ on a page to save it.</div>
          ) : (
            bookmarks.map((b, i) => (
              <div key={i} className="shadow-bookmark" onClick={() => { setShowBookmarks(false); navigate(b.url); }}>
                <span className="shadow-bookmark__title">{b.title}</span>
                <span className="shadow-bookmark__url">{b.url}</span>
                <button
                  className="shadow-bookmark__del"
                  onClick={(e) => {
                    e.stopPropagation();
                    setBookmarks((prev) => {
                      const next = prev.filter((x) => x.url !== b.url);
                      localStorage.setItem(BOOKMARKS_KEY, JSON.stringify(next));
                      return next;
                    });
                  }}
                  title="Remove"
                >
                  ×
                </button>
              </div>
            ))
          )}
        </div>
      )}

      {/* ---- content area ---- */}
      <div className="shadow-content">
        {activeTab?.loadState === "loading" && (
          <div className="shadow-content__loading">
            <div className="shadow-content__spinner" />
            <span>Routing through Tor…</span>
          </div>
        )}

        {activeTab?.loadState === "error" && (
          <div className="shadow-content__error">
            <div className="shadow-content__error-title">⚠ Unreachable</div>
            <div className="shadow-content__error-msg">{activeTab.loadError}</div>
            <button className="shadow-content__retry" onClick={() => currentUrl && loadInto(activeId, currentUrl)}>Retry</button>
          </div>
        )}

        {activeTab && activeTab.searchResults.length > 0 && activeTab.loadState !== "loading" && (
          <div className="shadow-results">
            {activeTab.searchResults.map((r, i) => (
              <div key={i} className="shadow-result" onClick={() => navigate(r.url)}>
                <div className="shadow-result__title">
                  {r.is_onion && <span className="shadow-result__onion">⬡</span>}
                  {r.title}
                </div>
                {r.description && <div className="shadow-result__desc">{r.description}</div>}
                <div className="shadow-result__url">{r.url}</div>
              </div>
            ))}
          </div>
        )}

        {activeTab?.page && activeTab.loadState === "done" && activeTab.searchResults.length === 0 && (
          <iframe
            ref={iframeRef}
            className="shadow-content__iframe"
            srcDoc={activeTab.page.html}
            sandbox="allow-same-origin allow-forms"
            title={activeTab.page.title ?? "Shadow Net"}
          />
        )}

        {activeTab?.loadState === "idle" && activeTab.searchResults.length === 0 && (
          <div className="shadow-content__home">
            <div className="shadow-content__home-title">◈ Shadow Net</div>
            <p>Enter an address above or use search to explore. .onion sites require Tor to be bootstrapped.</p>
            <div className="shadow-content__home-links">
              <button onClick={() => navigate("https://check.torproject.org")}>Verify Tor Connection</button>
              <button onClick={() => { setSearchQuery("news"); void runSearch(SEARCH_ENGINES[0]); }}>Search News</button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

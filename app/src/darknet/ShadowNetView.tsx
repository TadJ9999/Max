import { useEffect, useReducer, useRef, useState } from "react";
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

// ---- nav history reducer ------------------------------------------------
type NavState = { history: string[]; idx: number };
type NavAction =
  | { type: "push"; url: string }
  | { type: "back" }
  | { type: "forward" };

function navReducer(state: NavState, action: NavAction): NavState {
  switch (action.type) {
    case "push": {
      const trimmed = state.history.slice(0, state.idx + 1);
      return { history: [...trimmed, action.url], idx: trimmed.length };
    }
    case "back":
      return state.idx > 0 ? { ...state, idx: state.idx - 1 } : state;
    case "forward":
      return state.idx < state.history.length - 1 ? { ...state, idx: state.idx + 1 } : state;
  }
}

const SEARCH_ENGINES = [
  { label: "Ahmia", url: "https://ahmia.fi/search/?q=" },
  { label: "DuckDuckGo .onion", url: "https://duckduckgogg42xjoc72x3sjasowoarfbgcmvfimaftt6twagswzczad.onion/?q=" },
];

export function ShadowNetView() {
  const [torStatus, setTorStatus] = useState<TorStatus | null>(null);
  const [connecting, setConnecting] = useState(false);
  const [connectError, setConnectError] = useState<string | null>(null);

  const [addrInput, setAddrInput] = useState("");
  const [loadState, setLoadState] = useState<"idle" | "loading" | "done" | "error">("idle");
  const [loadError, setLoadError] = useState<string | null>(null);
  const [page, setPage] = useState<FetchResult | null>(null);

  const [searchQuery, setSearchQuery] = useState("");
  const [searchResults, setSearchResults] = useState<SearchResult[]>([]);
  const [searching, setSearching] = useState(false);

  const [nav, dispatchNav] = useReducer(navReducer, { history: [], idx: -1 });
  const iframeRef = useRef<HTMLIFrameElement>(null);
  const abortRef = useRef<AbortController | null>(null);

  const currentUrl = nav.history[nav.idx] ?? null;
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
      // start_tor returns Ok(()) on success (resolves undefined) or rejects with
      // a String error (binary missing, etc.). Once it resolves, the status poll
      // takes over and shows bootstrap progress.
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
    setTorStatus(null);
    setPage(null);
    setLoadState("idle");
    dispatchNav({ type: "push", url: "" }); // clear history conceptually
  };

  // ---- navigation ----------------------------------------------------------

  const navigate = (url: string) => {
    if (!url.trim()) return;
    const normalized = url.startsWith("http") ? url : `https://${url}`;

    abortRef.current?.abort();
    const ac = new AbortController();
    abortRef.current = ac;

    setLoadState("loading");
    setLoadError(null);
    setPage(null);
    dispatchNav({ type: "push", url: normalized });

    void emitMascotEvent("mascot:tor-request");

    streamFetchUrl(
      normalized,
      {
        onStart: () => setLoadState("loading"),
        onHtml: (result) => {
          setPage(result);
          setLoadState("done");
          void emitMascotEvent("mascot:tor-response");
          if (result.title) setAddrInput(normalized);
        },
        onError: (msg) => {
          setLoadError(msg);
          setLoadState("error");
        },
      },
      ac.signal,
    );
  };

  const goBack = () => {
    dispatchNav({ type: "back" });
    const prev = nav.history[nav.idx - 1];
    if (prev) navigate(prev);
  };

  const goForward = () => {
    dispatchNav({ type: "forward" });
    const next = nav.history[nav.idx + 1];
    if (next) navigate(next);
  };

  // ---- iframe link intercept -----------------------------------------------
  // When the user clicks a link inside the rendered page (which was rewritten to
  // ?url=...), we intercept the navigation and re-route through the engine.
  useEffect(() => {
    const iframe = iframeRef.current;
    if (!iframe || !page) return;
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
          if (match) {
            const dest = decodeURIComponent(match[1]);
            setAddrInput(dest);
            navigate(dest);
          }
        });
      } catch { /* cross-origin — can't intercept */ }
    };
    iframe.addEventListener("load", onLoad);
    return () => iframe.removeEventListener("load", onLoad);
  }, [page]);

  // ---- search --------------------------------------------------------------
  const runSearch = async (engine: typeof SEARCH_ENGINES[0]) => {
    if (!searchQuery.trim()) return;
    setSearching(true);
    setSearchResults([]);
    const q = encodeURIComponent(searchQuery);
    const url = `${engine.url}${q}`;
    setAddrInput(url);
    const results = await searchDark(searchQuery);
    setSearchResults(results);
    setSearching(false);
    if (results.length === 0) {
      navigate(url);
    }
  };

  // ---- handle new identity from popover (wired via prop drilling to TorLock) --
  const handleNewCircuit = async () => {
    await newCircuit();
    void getTorStatus().then((s) => s && setTorStatus(s));
  };

  // ---- bootstrap progress display -----------------------------------------
  const bootstrapPct = torStatus?.bootstrapped ?? 0;
  const isBootstrapping = torStatus?.running && !torStatus.circuit_established;

  // ---- render --------------------------------------------------------------

  if (!isConnected) {
    return (
      <div className="shadow-connect">
        <div className="shadow-connect__orb">
          {/* Tor onion SVG logo */}
          <svg viewBox="0 0 80 80" className="shadow-connect__logo" aria-label="Tor onion">
            <circle cx="40" cy="40" r="36" stroke="rgba(34,211,238,0.15)" strokeWidth="1.5" fill="none" />
            <circle cx="40" cy="40" r="28" stroke="rgba(34,211,238,0.25)" strokeWidth="1.5" fill="none" />
            <circle cx="40" cy="40" r="20" stroke="rgba(34,211,238,0.40)" strokeWidth="1.5" fill="none" />
            <circle cx="40" cy="40" r="12" stroke="rgba(34,211,238,0.65)" strokeWidth="1.5" fill="none" />
            <circle cx="40" cy="40" r="5" fill="rgba(34,211,238,0.85)" />
            {/* petal shapes */}
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

        {connectError && (
          <div className="shadow-connect__error">{connectError}</div>
        )}

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

  return (
    <div className="shadow-browser">
      {/* ---- toolbar ---- */}
      <div className="shadow-toolbar">
        <button className="shadow-toolbar__nav" onClick={goBack} disabled={nav.idx <= 0} title="Back">←</button>
        <button className="shadow-toolbar__nav" onClick={goForward} disabled={nav.idx >= nav.history.length - 1} title="Forward">→</button>
        <button
          className="shadow-toolbar__nav"
          onClick={() => currentUrl && navigate(currentUrl)}
          disabled={loadState === "loading"}
          title="Reload"
        >
          ⟳
        </button>

        <input
          className="shadow-toolbar__addr"
          value={addrInput}
          onChange={(e) => setAddrInput(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter") navigate(addrInput); }}
          placeholder=".onion or https://…"
          spellCheck={false}
        />
        <button className="shadow-toolbar__go" onClick={() => navigate(addrInput)}>Go</button>
      </div>

      {/* ---- quick search strip ---- */}
      <div className="shadow-search-strip">
        <input
          className="shadow-search-strip__input"
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter") void runSearch(SEARCH_ENGINES[0]); }}
          placeholder="Search dark web…"
        />
        {SEARCH_ENGINES.map((eng) => (
          <button
            key={eng.label}
            className="shadow-search-strip__btn"
            onClick={() => void runSearch(eng)}
            disabled={searching || !searchQuery.trim()}
          >
            {eng.label}
          </button>
        ))}
      </div>

      {/* ---- status bar ---- */}
      <div className="shadow-statusbar">
        <span className="shadow-statusbar__dot shadow-statusbar__dot--on" />
        <span>Tor</span>
        {torStatus?.exit_ip && <span className="shadow-statusbar__ip">{torStatus.exit_ip}</span>}
        {torStatus?.circuit_age_seconds !== undefined && (
          <span className="shadow-statusbar__age">
            Circuit: {Math.floor(torStatus.circuit_age_seconds / 60)}m {torStatus.circuit_age_seconds % 60}s
          </span>
        )}
        {loadState === "loading" && <span className="shadow-statusbar__loading">Loading…</span>}
        {page && <span className="shadow-statusbar__time">{page.fetch_time_ms}ms</span>}
        <div style={{ flex: 1 }} />
        <button className="shadow-statusbar__newid" onClick={() => void handleNewCircuit()} title="New Tor Identity">
          New Identity
        </button>
        <button className="shadow-statusbar__disc" onClick={() => void disconnect()} title="Disconnect Tor">
          Disconnect
        </button>
      </div>

      {/* ---- content area ---- */}
      <div className="shadow-content">
        {loadState === "loading" && (
          <div className="shadow-content__loading">
            <div className="shadow-content__spinner" />
            <span>Routing through Tor…</span>
          </div>
        )}

        {loadState === "error" && (
          <div className="shadow-content__error">
            <div className="shadow-content__error-title">⚠ Unreachable</div>
            <div className="shadow-content__error-msg">{loadError}</div>
            <button className="shadow-content__retry" onClick={() => currentUrl && navigate(currentUrl)}>Retry</button>
          </div>
        )}

        {searchResults.length > 0 && loadState !== "loading" && (
          <div className="shadow-results">
            {searchResults.map((r, i) => (
              <div key={i} className="shadow-result" onClick={() => { setAddrInput(r.url); navigate(r.url); setSearchResults([]); }}>
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

        {page && loadState === "done" && searchResults.length === 0 && (
          <iframe
            ref={iframeRef}
            className="shadow-content__iframe"
            srcDoc={page.html}
            sandbox="allow-same-origin allow-forms"
            title={page.title ?? "Shadow Net"}
          />
        )}

        {loadState === "idle" && searchResults.length === 0 && (
          <div className="shadow-content__home">
            <div className="shadow-content__home-title">◈ Shadow Net</div>
            <p>Enter an address above or use search to explore. .onion sites require Tor to be bootstrapped.</p>
            <div className="shadow-content__home-links">
              <button onClick={() => { setAddrInput("https://check.torproject.org"); navigate("https://check.torproject.org"); }}>
                Verify Tor Connection
              </button>
              <button onClick={() => { setSearchQuery("news"); void runSearch(SEARCH_ENGINES[0]); }}>
                Search News
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

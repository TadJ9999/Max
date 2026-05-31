// Market view — live US-stock board (left) + on-demand AI "Ingest" panel (right).
// The board polls /market/quotes every ~10s; "Ingest" streams an AI read of it.

import { useCallback, useEffect, useRef, useState } from "react";
import {
  getBoard,
  getSources,
  getWatchlist,
  setWatchlist as putWatchlist,
  streamAnalyze,
  streamMarketChat,
  type ChatTurn,
  type MarketBoard,
  type Quote,
} from "./market";
import { MarkdownView } from "../components/MarkdownView";
import { CopyButton } from "../components/CopyButton";
import "./Market.css";

const POLL_MS = 10_000;

function fmt(n: number): string {
  return n.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function dirClass(change: number): string {
  if (change > 0) return "is-up";
  if (change < 0) return "is-down";
  return "is-flat";
}

// ── one ticker row ──────────────────────────────────────────────────────────
function QuoteRow({ quote, onRemove }: { quote: Quote; onRemove: () => void }) {
  const dir = dirClass(quote.change);
  const sign = quote.change > 0 ? "+" : "";
  return (
    <div className={`market__row ${dir}`}>
      <div className="market__sym">
        <span className="market__ticker">{quote.symbol}</span>
        {quote.name && <span className="market__name">{quote.name}</span>}
      </div>
      <div className="market__price">${fmt(quote.price)}</div>
      <div className={`market__chg ${dir}`}>
        <span className="market__chg-abs">{sign}{fmt(quote.change)}</span>
        <span className="market__chg-pct">{sign}{fmt(quote.changePct)}%</span>
      </div>
      <button className="market__remove" onClick={onRemove} title={`Remove ${quote.symbol}`}>
        ×
      </button>
    </div>
  );
}

export function MarketView({ onClose }: { onClose?: () => void } = {}) {
  const [board, setBoard] = useState<MarketBoard | null>(null);
  const [watchlist, setList] = useState<string[]>([]);
  const [keySet, setKeySet] = useState<boolean>(true);
  const [loading, setLoading] = useState(true);
  const [add, setAdd] = useState("");

  const [analysis, setAnalysis] = useState("");
  const [ingesting, setIngesting] = useState(false);
  const [ingestErr, setIngestErr] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  // ── conversational AI panel (talks to /market/chat through the AI pipeline) ──
  const [chat, setChat] = useState<ChatTurn[]>([]);
  const [question, setQuestion] = useState("");
  const [chatBusy, setChatBusy] = useState(false);
  const chatAbortRef = useRef<AbortController | null>(null);

  // initial watchlist (the editable symbol set)
  useEffect(() => {
    void (async () => {
      const wl = await getWatchlist();
      if (wl.length) setList(wl);
    })();
  }, []);

  // poll the live board + key status every ~10s, so the UI self-heals if the
  // engine starts (or gains its API key) after this view is already open.
  const refresh = useCallback(async () => {
    const [b, src] = await Promise.all([getBoard(), getSources()]);
    setBoard(b);
    if (src) {
      setKeySet(src.key_set);
      if (src.watchlist.length) setList((cur) => (cur.length ? cur : src.watchlist));
    }
    setLoading(false);
  }, []);

  useEffect(() => {
    void refresh();
    const id = setInterval(() => void refresh(), POLL_MS);
    return () => clearInterval(id);
  }, [refresh]);

  const commitWatchlist = useCallback(async (next: string[]) => {
    setList(next);
    const saved = await putWatchlist(next);
    setList(saved);
    await refresh();
  }, [refresh]);

  const onAdd = () => {
    const sym = add.trim().toUpperCase();
    if (!sym || watchlist.includes(sym)) { setAdd(""); return; }
    void commitWatchlist([...watchlist, sym]);
    setAdd("");
  };

  const onRemove = (sym: string) => {
    void commitWatchlist(watchlist.filter((s) => s !== sym));
  };

  const onIngest = async () => {
    if (ingesting) {
      abortRef.current?.abort();
      return;
    }
    setAnalysis("");
    setIngestErr(null);
    setIngesting(true);
    const ctrl = new AbortController();
    abortRef.current = ctrl;
    try {
      for await (const delta of streamAnalyze(ctrl.signal)) {
        setAnalysis((prev) => prev + delta);
      }
    } catch (e) {
      if (!ctrl.signal.aborted) setIngestErr((e as Error).message);
    } finally {
      setIngesting(false);
      abortRef.current = null;
    }
  };

  useEffect(() => () => abortRef.current?.abort(), []);

  const sendChat = async () => {
    const q = question.trim();
    if (!q || chatBusy) return;
    const history: ChatTurn[] = [...chat, { role: "user", content: q }];
    // Show the question + an empty assistant turn we stream into.
    setChat([...history, { role: "assistant", content: "" }]);
    setQuestion("");
    setChatBusy(true);
    const ctrl = new AbortController();
    chatAbortRef.current = ctrl;
    try {
      for await (const delta of streamMarketChat(history, ctrl.signal)) {
        setChat((prev) => {
          const next = prev.slice();
          const last = next[next.length - 1];
          next[next.length - 1] = { ...last, content: last.content + delta };
          return next;
        });
      }
    } catch (e) {
      if (!ctrl.signal.aborted) {
        setChat((prev) => {
          const next = prev.slice();
          next[next.length - 1] = { role: "assistant", content: `⚠ ${(e as Error).message}` };
          return next;
        });
      }
    } finally {
      setChatBusy(false);
      chatAbortRef.current = null;
    }
  };

  useEffect(() => () => chatAbortRef.current?.abort(), []);

  const quotes = board?.quotes ?? [];
  const offline = !loading && board === null;

  return (
    <div className="market">
      {/* ── header bar ── */}
      <header className="market__bar">
        <div className="market__title">
          <span className="market__glyph">$</span> Market · Live Tape
        </div>

        <div className="market__bar-right">
          <span className="market__updated">
            {loading ? "loading…"
              : offline ? "engine offline"
              : !keySet ? "no API key"
              : `${quotes.length} symbols`}
          </span>
          <button
            className={`market__ingest${ingesting ? " is-busy" : ""}`}
            onClick={() => void onIngest()}
            title="Stream an AI read of the current board"
          >
            {ingesting ? "Ingesting…" : "Ingest"}
          </button>
          {onClose && (
            <button className="market__btn market__btn--close" onClick={onClose} title="Close">×</button>
          )}
        </div>
      </header>

      {/* ── body ── */}
      <div className="market__body">
        {/* left: live board */}
        <div className="market__board">
          <div className="market__add">
            <input
              className="market__add-input"
              value={add}
              onChange={(e) => setAdd(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && onAdd()}
              placeholder="Add ticker (e.g. AAPL)"
              spellCheck={false}
              maxLength={8}
            />
            <button className="market__add-btn" onClick={onAdd} title="Add to watchlist">+</button>
          </div>

          {!keySet && (
            <div className="market__note">
              Set <code>FINNHUB_API_KEY</code> in <code>engine/.env</code> for live quotes.
            </div>
          )}
          {offline && (
            <div className="market__note">Engine offline — start Max engine for live quotes.</div>
          )}

          <div className="market__rows">
            {quotes.length === 0 && !loading && (
              <div className="market__empty">No quotes yet.</div>
            )}
            {quotes.map((q) => (
              <QuoteRow key={q.symbol} quote={q} onRemove={() => onRemove(q.symbol)} />
            ))}
          </div>
        </div>

        {/* right: AI analysis + conversational panel */}
        <aside className="market__panel">
          <div className="market__panel-head">
            AI Analysis
            {analysis && <CopyButton text={analysis} />}
          </div>
          <div className="market__panel-body">
            {ingestErr && <div className="market__error">{ingestErr}</div>}
            {!analysis && !ingesting && !ingestErr && (
              <div className="market__placeholder">
                Press <b>Ingest</b> for an AI read of the live board.
                <div className="market__disclaimer">Informational only — not financial advice.</div>
              </div>
            )}
            {analysis && (
              <div className="market__analysis">
                <MarkdownView source={analysis} />
              </div>
            )}
            {ingesting && <span className="market__cursor">▍</span>}
          </div>

          {/* conversational Q&A about the board, through the AI pipeline */}
          <div className="market__panel-head market__panel-head--chat">Ask the board</div>
          <div className="market__chat">
            <div className="market__chat-thread">
              {chat.length === 0 && (
                <div className="market__placeholder">
                  Ask anything about the live board — e.g. <i>“why is NVDA down?”</i>
                </div>
              )}
              {chat.map((turn, i) => (
                <div key={i} className={`market__msg market__msg--${turn.role}`}>
                  {turn.role === "assistant" ? (
                    turn.content ? (
                      <>
                        <MarkdownView source={turn.content} />
                        <CopyButton text={turn.content} className="market__msg-copy" />
                      </>
                    ) : (
                      <span className="market__cursor">▍</span>
                    )
                  ) : (
                    turn.content
                  )}
                </div>
              ))}
            </div>
            <div className="market__chat-input">
              <input
                className="market__chat-text"
                value={question}
                onChange={(e) => setQuestion(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && !e.shiftKey && (e.preventDefault(), void sendChat())}
                placeholder="Ask about the board…"
                spellCheck={false}
                disabled={chatBusy}
              />
              <button
                className="market__chat-send"
                onClick={() => void sendChat()}
                disabled={chatBusy || !question.trim()}
                title="Ask"
              >
                {chatBusy ? "…" : "▶"}
              </button>
            </div>
          </div>
        </aside>
      </div>
    </div>
  );
}

import { useEffect, useRef, useState } from "react";
import { EarthView } from "./EarthView";
import { SolarView } from "./SolarView";
import { MarkdownView } from "../components/MarkdownView";
import {
  getSpaceWeather, getNeo, getFireballs, getISS, getLaunches, streamChat,
  type SpaceWeather, type Neo, type Fireball, type ISS, type Launch,
} from "./sentinel";
import "./Sentinel.css";

// Cross-window mascot signal (Tauri event, with a same-window DOM fallback).
async function emitMascotEvent(name: string, payload?: unknown) {
  try {
    const { emit } = await import("@tauri-apps/api/event");
    await emit(name, payload);
  } catch {
    window.dispatchEvent(new CustomEvent(name, { detail: payload }));
  }
}

type SubTab = "earth" | "solar";
interface ChatMsg { role: "user" | "assistant"; content: string; }

export function SentinelView() {
  const [subTab, setSubTab] = useState<SubTab>("earth");
  const [visited, setVisited] = useState<Set<SubTab>>(() => new Set<SubTab>(["earth"]));

  // shared live data
  const [sw, setSw] = useState<SpaceWeather | null>(null);
  const [neos, setNeos] = useState<Neo[]>([]);
  const [fireballs, setFireballs] = useState<Fireball[]>([]);
  const [iss, setIss] = useState<ISS | null>(null);
  const [launches, setLaunches] = useState<Launch[]>([]);

  // chat
  const [chatOpen, setChatOpen] = useState(false);
  const [messages, setMessages] = useState<ChatMsg[]>([]);
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState(false);
  const bodyRef = useRef<HTMLDivElement>(null);

  const show = (t: SubTab) => { setSubTab(t); setVisited((v) => (v.has(t) ? v : new Set(v).add(t))); };

  useEffect(() => {
    void getSpaceWeather().then((d) => d && setSw(d));
    void getNeo().then((d) => d && setNeos(d.neos));
    void getFireballs().then((d) => d && setFireballs(d.fireballs));
    void getLaunches().then((d) => d && setLaunches(d.launches));
    const pollIss = () => void getISS().then((d) => d && setIss(d));
    pollIss();
    const id = setInterval(pollIss, 5000);
    return () => clearInterval(id);
  }, []);

  useEffect(() => { if (bodyRef.current) bodyRef.current.scrollTop = bodyRef.current.scrollHeight; }, [messages]);

  const send = async () => {
    const text = input.trim();
    if (!text || streaming) return;
    const next = [...messages, { role: "user" as const, content: text }];
    setMessages(next);
    setInput("");
    setStreaming(true);
    void emitMascotEvent("mascot:signal");
    void emitMascotEvent("mascot:thinking", true);
    setMessages((m) => [...m, { role: "assistant", content: "" }]);
    try {
      for await (const ev of streamChat(next.map((m) => ({ role: m.role, content: m.content })))) {
        if (ev.object === "chat.completion.chunk" && ev.delta) {
          setMessages((m) => {
            const copy = m.slice();
            copy[copy.length - 1] = { role: "assistant", content: copy[copy.length - 1].content + ev.delta };
            return copy;
          });
        }
      }
    } catch {
      setMessages((m) => {
        const copy = m.slice();
        copy[copy.length - 1] = { role: "assistant", content: copy[copy.length - 1].content || "_Connection to the engine failed._" };
        return copy;
      });
    } finally {
      setStreaming(false);
      void emitMascotEvent("mascot:thinking", false);
    }
  };

  return (
    <div className="sentinel">
      <header className="sentinel__bar">
        <span className="sentinel__title">🛰 Sentinel</span>
        <div className="sentinel__subtabs">
          <button className={`sentinel__subtab ${subTab === "earth" ? "is-active" : ""}`} onClick={() => show("earth")}>⊕ Earth</button>
          <button className={`sentinel__subtab ${subTab === "solar" ? "is-active" : ""}`} onClick={() => show("solar")}>☀ Solar System</button>
        </div>
        <div className="sentinel__spacer" />
        <button className="sentinel__ask" onClick={() => setChatOpen((v) => !v)}>✦ Ask Sentinel</button>
      </header>

      <div className="sentinel__body">
        {visited.has("earth") && (
          <div className="sentinel__view" hidden={subTab !== "earth"}>
            <EarthView spaceWeather={sw} fireballs={fireballs} iss={iss} launches={launches} />
          </div>
        )}
        {visited.has("solar") && (
          <div className="sentinel__view" hidden={subTab !== "solar"}>
            <SolarView neos={neos} />
          </div>
        )}

        <aside className={`sentinel__chat ${chatOpen ? "is-open" : ""}`}>
          <div className="sentinel__chat-head">
            <span>✦ SENTINEL AI</span>
            <button onClick={() => setChatOpen(false)}>✕</button>
          </div>
          <div className="sentinel__chat-body" ref={bodyRef}>
            {messages.length === 0 && <div className="sentinel__chat-empty">Ask about satellites, space weather, close approaches, or launches — grounded in the live feed.</div>}
            {messages.map((m, i) => (
              m.role === "user"
                ? <div key={i} className="sentinel__msg sentinel__msg--user">{m.content}</div>
                : <div key={i} className="sentinel__msg sentinel__msg--assistant"><MarkdownView source={m.content || "…"} /></div>
            ))}
          </div>
          <div className="sentinel__chat-foot">
            <input
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter") void send(); }}
              placeholder="Ask Sentinel…"
              disabled={streaming}
            />
            <button className="sentinel__chat-send" onClick={() => void send()} disabled={streaming || !input.trim()}>➤</button>
          </div>
        </aside>
      </div>
    </div>
  );
}

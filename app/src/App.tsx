import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { TopBar, type SysInfo } from "./components/TopBar";
import { TaskCard } from "./components/TaskCard";
import { Mascot } from "./components/Mascot";
import { ChatBar } from "./components/ChatBar";
import { SettingsPanel } from "./components/SettingsPanel";
import { OsintButton } from "./osint/OsintButton";
import { deriveMascotState } from "./mascot/deriveMascotState";
import { initFloatingWindow } from "./window";
import { getSystemStats } from "./system";
import { getSessions, cancelSession, promoteSession } from "./engine";
import { type Session } from "./types";
import "./App.css";

// Mock data until Rust sysinfo + /sessions polling are wired (ROADMAP Phase 3/4).
const MOCK_SYS: SysInfo = { cpu: 37, gpu: 64, vram: 78, ram: 52, gpuTemp: 58 };

const MOCK_SESSIONS: Session[] = [
  {
    id: "s1",
    title: "TASK #1",
    provider: "claude",
    model: "claude-sonnet-4-6",
    state: "running",
    isCloud: true,
  },
  {
    id: "s2",
    title: "TASK #2",
    provider: "ollama",
    model: "qwen2.5-coder:14b",
    state: "queued",
    isCloud: false,
  },
  {
    id: "s3",
    title: "TASK #3",
    provider: "ollama",
    model: "qwen2.5-coder:3b",
    state: "done",
    isCloud: false,
  },
];

function App() {
  const [sessions, setSessions] = useState<Session[]>(MOCK_SESSIONS);
  const [sys, setSys] = useState<SysInfo>(MOCK_SYS);
  const [showSettings, setShowSettings] = useState(false);
  const [pulse, setPulse] = useState(0); // bump => mascot fires a request comet
  const ping = useCallback(() => setPulse((p) => p + 1), []);
  const [systemDown, setSystemDown] = useState(!navigator.onLine);
  const [chatThinking, setChatThinking] = useState(false);
  const seenIds = useRef<Set<string>>(new Set());
  const firstPoll = useRef(true);

  // Anchor top-right + register the global hotkey (no-op outside Tauri).
  useEffect(() => {
    void initFloatingWindow();
  }, []);

  // System status → red core when the host is unreachable. Connectivity is a
  // stand-in until a real engine health probe is wired (ROADMAP Phase 3/4).
  useEffect(() => {
    const sync = () => setSystemDown(!navigator.onLine);
    window.addEventListener("online", sync);
    window.addEventListener("offline", sync);
    return () => {
      window.removeEventListener("online", sync);
      window.removeEventListener("offline", sync);
    };
  }, []);

  // Poll real system meters from the backend (~1.5s); keeps placeholders in the
  // browser preview where the Tauri command isn't available.
  useEffect(() => {
    let alive = true;
    const tick = async () => {
      const s = await getSystemStats();
      if (alive && s) setSys(s);
    };
    void tick();
    const id = window.setInterval(() => void tick(), 1500);
    return () => {
      alive = false;
      window.clearInterval(id);
    };
  }, []);

  // Poll the engine's sessions (~2s). When the engine is unreachable, keep the
  // current cards (placeholder until first successful connect).
  useEffect(() => {
    let alive = true;
    const tick = async () => {
      const real = await getSessions();
      if (!alive || !real) return;
      setSessions(real);
      // Fire one comet when new sessions appear (skip the initial load).
      const fresh = real.some((s) => !seenIds.current.has(s.id));
      real.forEach((s) => seenIds.current.add(s.id));
      if (fresh && !firstPoll.current) ping();
      firstPoll.current = false;
    };
    void tick();
    const id = window.setInterval(() => void tick(), 2000);
    return () => {
      alive = false;
      window.clearInterval(id);
    };
  }, []);

  // Collapse sessions (+ measured VRAM) into the single mascot signal.
  const mascot = useMemo(
    () =>
      deriveMascotState(
        sessions.map((s) => ({ id: s.id, state: s.state, cloud: s.isCloud })),
        sys.vram / 100,
      ),
    [sessions, sys.vram],
  );

  // Optimistic local update + tell the engine (a no-op for offline/mock cards);
  // the next /sessions poll reconciles with the engine's truth.
  const cancel = (id: string) => {
    setSessions((xs) => xs.map((s) => (s.id === id ? { ...s, state: "done" } : s)));
    void cancelSession(id);
  };

  const promote = (id: string) => {
    setSessions((xs) =>
      xs.map((s) =>
        s.id === id ? { ...s, provider: "claude", isCloud: true, state: "running" } : s,
      ),
    );
    void promoteSession(id);
  };

  return (
    <div className="widget">
      <TopBar sys={sys} onSettings={() => setShowSettings((v) => !v)} />

      {showSettings && <SettingsPanel />}

      <div className="cards">
        {sessions.length === 0 ? (
          <div className="cards__empty">No active sessions</div>
        ) : (
          sessions.map((s) => (
            <TaskCard key={s.id} session={s} onCancel={cancel} onPromote={promote} />
          ))
        )}
      </div>

      <Mascot
        state={mascot.state}
        metrics={{ cpu: sys.cpu, gpu: sys.gpu, vram: sys.vram, ram: sys.ram, gpuTemp: sys.gpuTemp }}
        size={150}
        signal={pulse}
        thinking={chatThinking}
        systemDown={systemDown}
      />

      <ChatBar onRequest={ping} onBusyChange={setChatThinking} />

      <OsintButton />
    </div>
  );
}

export default App;

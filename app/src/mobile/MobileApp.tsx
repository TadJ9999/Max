import { useState } from "react";
import { ChatTab } from "./ChatTab";
import { MarketsTab } from "./MarketsTab";
import { OsintTab } from "./OsintTab";
import { SentinelTab } from "./SentinelTab";

type Tab = "chat" | "markets" | "osint" | "sentinel";

const TABS: { id: Tab; icon: string; label: string }[] = [
  { id: "chat",     icon: "💬", label: "Chat"    },
  { id: "markets",  icon: "$",  label: "Markets" },
  { id: "osint",    icon: "◉",  label: "Intel"   },
  { id: "sentinel", icon: "🛰", label: "Space"   },
];

export function MobileApp() {
  const [tab, setTab] = useState<Tab>("chat");

  return (
    <div className="mob">
      <div className="mob__content">
        {tab === "chat"     && <ChatTab />}
        {tab === "markets"  && <MarketsTab />}
        {tab === "osint"    && <OsintTab />}
        {tab === "sentinel" && <SentinelTab />}
      </div>
      <nav className="mob__nav">
        {TABS.map((t) => (
          <button
            key={t.id}
            className={`mob__nav-btn${tab === t.id ? " is-active" : ""}`}
            onClick={() => setTab(t.id)}
          >
            <span className="mob__nav-icon">{t.icon}</span>
            <span className="mob__nav-label">{t.label}</span>
          </button>
        ))}
      </nav>
    </div>
  );
}

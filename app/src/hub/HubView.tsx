// Intelligence Hub — one window, tabbed across Apollo / OSINT / Market. Each
// feature view renders unchanged inside a tab panel (no per-view close button;
// the hub owns the chrome). Tabs are lazy-mounted on first visit and then kept
// alive (hidden) so switching is instant and state/streams persist.
//
// In Tauri, clicking a widget launcher button while the hub is open emits a
// "hub:set-tab" event that switches the active tab here.

import { useEffect, useState } from "react";
import { ApolloView } from "../apollo/ApolloView";
import { OsintView } from "../osint/OsintView";
import { MarketView } from "../market/MarketView";
import { PolymarketView } from "../polymarket/PolymarketView";
import { AegisView } from "../aegis/AegisView";
import { SentinelView } from "../sentinel/SentinelView";
import { SettingsView } from "../settings/SettingsView";
import { ShadowNetView } from "../darknet/ShadowNetView";
import { CodeView } from "../code/CodeView";
import { SkillsView } from "../skills/SkillsView";
import "./Hub.css";

export type HubTab = "apollo" | "osint" | "market" | "polymarket" | "aegis" | "shadow" | "sentinel" | "code" | "skills" | "settings";

const TABS: { id: HubTab; label: string; glyph: string }[] = [
  { id: "apollo", label: "Apollo", glyph: "▲" },
  { id: "osint", label: "OSINT", glyph: "◎" },
  { id: "market", label: "Market", glyph: "$" },
  { id: "polymarket", label: "Poly", glyph: "Ψ" },
  { id: "aegis", label: "Aegis", glyph: "🛡" },
  { id: "shadow", label: "Shadow", glyph: "⬡" },
  { id: "sentinel", label: "Sentinel", glyph: "🛰" },
  { id: "code", label: "Code", glyph: "⌨" },
  { id: "skills", label: "Skills", glyph: "⚡" },
  { id: "settings", label: "Settings", glyph: "⚙" },
];

export function HubView({
  initialTab = "apollo",
  onClose,
}: {
  initialTab?: HubTab;
  onClose?: () => void;
}) {
  const [tab, setTab] = useState<HubTab>(initialTab);
  const [visited, setVisited] = useState<Set<HubTab>>(() => new Set([initialTab]));

  const show = (t: HubTab) => {
    setTab(t);
    setVisited((v) => (v.has(t) ? v : new Set(v).add(t)));
  };

  // Tauri: a widget launcher click while the hub is already open switches tabs.
  useEffect(() => {
    let unlisten: (() => void) | undefined;
    void (async () => {
      try {
        const { listen } = await import("@tauri-apps/api/event");
        unlisten = await listen<string>("hub:set-tab", (e) => {
          if (e.payload) show(e.payload as HubTab);
        });
      } catch {
        /* not running in Tauri */
      }
    })();
    return () => unlisten?.();
  }, []);

  return (
    <div className="hub">
      <nav className="hub__tabs">
        <div className="hub__tabs-left">
          {TABS.filter((t) => t.id !== "settings").map((t) => (
            <button
              key={t.id}
              className={`hub__tab hub__tab--${t.id}${tab === t.id ? " is-active" : ""}`}
              onClick={() => show(t.id)}
            >
              <span className="hub__tab-glyph" aria-hidden="true">
                {t.glyph}
              </span>
              {t.label}
            </button>
          ))}
        </div>
        <div className="hub__tabs-right">
          <button
            className={`hub__tab hub__tab--settings${tab === "settings" ? " is-active" : ""}`}
            onClick={() => show("settings")}
          >
            <span className="hub__tab-glyph" aria-hidden="true">⚙</span>
            Settings
          </button>
          {onClose && (
            <button className="hub__close" onClick={onClose} title="Close">
              ×
            </button>
          )}
        </div>
      </nav>

      <div className="hub__panel">
        {visited.has("apollo") && (
          <div className="hub__view" hidden={tab !== "apollo"}>
            <ApolloView />
          </div>
        )}
        {visited.has("osint") && (
          <div className="hub__view" hidden={tab !== "osint"}>
            <OsintView />
          </div>
        )}
        {visited.has("market") && (
          <div className="hub__view" hidden={tab !== "market"}>
            <MarketView />
          </div>
        )}
        {visited.has("polymarket") && (
          <div className="hub__view" hidden={tab !== "polymarket"}>
            <PolymarketView />
          </div>
        )}
        {visited.has("aegis") && (
          <div className="hub__view" hidden={tab !== "aegis"}>
            <AegisView />
          </div>
        )}
        {visited.has("shadow") && (
          <div className="hub__view" hidden={tab !== "shadow"}>
            <ShadowNetView />
          </div>
        )}
        {visited.has("sentinel") && (
          <div className="hub__view" hidden={tab !== "sentinel"}>
            <SentinelView />
          </div>
        )}
        {visited.has("code") && (
          <div className="hub__view" hidden={tab !== "code"}>
            <CodeView />
          </div>
        )}
        {visited.has("skills") && (
          <div className="hub__view" hidden={tab !== "skills"}>
            <SkillsView />
          </div>
        )}
        {visited.has("settings") && (
          <div className="hub__view" hidden={tab !== "settings"}>
            <SettingsView />
          </div>
        )}
      </div>
    </div>
  );
}

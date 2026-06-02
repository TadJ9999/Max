// The widget's feature launcher grid. Icon buttons (one per Hub tab) laid out
// 6 per row that open the unified Hub window on the matching tab. In Tauri a
// single "hub" window is reused (focus + emit a tab switch if already open);
// in the browser preview it opens an in-page overlay.

import { useState } from "react";
import { HubView, type HubTab } from "./HubView";
import { OwlLogo } from "../oracle/OwlLogo";
import "./Hub.css";

function inTauri(): boolean {
  return typeof window !== "undefined" && "__TAURI_INTERNALS__" in window;
}

export async function openHubWindow(tab: HubTab): Promise<void> {
  const { WebviewWindow } = await import("@tauri-apps/api/webviewWindow");
  const { Effect } = await import("@tauri-apps/api/window");
  const existing = await WebviewWindow.getByLabel("hub");
  if (existing) {
    try {
      await existing.emit("hub:set-tab", tab); // switch the tab in the open window
    } catch {
      /* emit unavailable — focusing is still useful */
    }
    await existing.setFocus();
    return;
  }
  const win = new WebviewWindow("hub", {
    url: `index.html#hub:${tab}`,
    title: "Max · Intelligence Hub",
    width: 1300,
    height: 840,
    minWidth: 900,
    minHeight: 600,
    resizable: true,
    // Keep the native frame (drag/resize/close) but make the window transparent
    // and apply Windows acrylic so the hub reads as frosted glass.
    decorations: true,
    transparent: true,
    windowEffects: { effects: [Effect.Acrylic], radius: 16 },
    center: true,
    skipTaskbar: false,
  });
  win.once("tauri://error", (e) => console.error("Hub window failed to open", e));
}

const ICONS: Record<HubTab, React.ReactNode> = {
  shadow: (
    <svg viewBox="0 0 20 20" fill="none" xmlns="http://www.w3.org/2000/svg">
      {/* Tor onion — nested hexagon rings */}
      <polygon points="10,2 16.5,5.5 16.5,14.5 10,18 3.5,14.5 3.5,5.5" stroke="currentColor" strokeWidth="1.2" fill="none" />
      <polygon points="10,5 14,7.5 14,12.5 10,15 6,12.5 6,7.5" stroke="currentColor" strokeWidth="0.9" fill="none" />
      <circle cx="10" cy="10" r="2" stroke="currentColor" strokeWidth="0.8" />
      <circle cx="10" cy="10" r="0.7" fill="currentColor" />
    </svg>
  ),
  polymarket: (
    <svg viewBox="0 0 20 20" fill="none" xmlns="http://www.w3.org/2000/svg">
      <circle cx="10" cy="10" r="7.5" stroke="currentColor" strokeWidth="1.2" />
      <path d="M7 7h4a2 2 0 0 1 0 4H8v4" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" strokeLinejoin="round" />
      <path d="M8 7v8" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" />
    </svg>
  ),
  oracle: <OwlLogo size={20} />,
  apollo: (
    <svg viewBox="0 0 20 20" fill="none" xmlns="http://www.w3.org/2000/svg">
      <path d="M10 2.6 L18 16.6 L2 16.6 Z" stroke="currentColor" strokeWidth="1.2" strokeLinejoin="round" />
      <path d="M5.4 12.3 Q10 8.9 14.6 12.3 Q10 15.7 5.4 12.3 Z" stroke="currentColor" strokeWidth="1" />
      <circle cx="10" cy="12.3" r="1.5" fill="currentColor" />
      <line x1="10" y1="2.6" x2="10" y2="0.8" stroke="currentColor" strokeWidth="0.8" opacity="0.65" />
    </svg>
  ),
  osint: (
    <svg viewBox="0 0 20 20" fill="none" xmlns="http://www.w3.org/2000/svg">
      <circle cx="10" cy="10" r="8" stroke="currentColor" strokeWidth="1.2" />
      <circle cx="10" cy="10" r="4" stroke="currentColor" strokeWidth="1" strokeDasharray="2 1.5" />
      <circle cx="10" cy="10" r="1.5" fill="currentColor" />
      <path d="M10 10 L10 2 A8 8 0 0 1 17.6 14" stroke="currentColor" strokeWidth="1" opacity="0.7" strokeLinecap="round" />
    </svg>
  ),
  market: (
    <svg viewBox="0 0 20 20" fill="none" xmlns="http://www.w3.org/2000/svg">
      <rect x="2" y="5" width="16" height="10" rx="2" stroke="currentColor" strokeWidth="1.2" />
      <circle cx="10" cy="10" r="2.4" stroke="currentColor" strokeWidth="1" />
      <path d="M10 8.2v3.6M9.1 8.9h1.6a0.7 0.7 0 0 1 0 1.4H9.4a0.7 0.7 0 0 0 0 1.4h1.5" stroke="currentColor" strokeWidth="0.9" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  ),
  aegis: (
    <svg viewBox="0 0 20 20" fill="none" xmlns="http://www.w3.org/2000/svg">
      <path d="M10 2 L17 5 L17 10 C17 14.5 13.5 17.5 10 18.5 C6.5 17.5 3 14.5 3 10 L3 5 Z"
        stroke="currentColor" strokeWidth="1.2" strokeLinejoin="round" />
      <path d="M7 10 L9 12 L13 8" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  ),
  sentinel: (
    <svg viewBox="0 0 20 20" fill="none" xmlns="http://www.w3.org/2000/svg">
      <circle cx="10" cy="10" r="6.5" stroke="currentColor" strokeWidth="1.2" />
      <ellipse cx="10" cy="10" rx="9" ry="3.4" stroke="currentColor" strokeWidth="0.9" strokeDasharray="2 1.4" transform="rotate(28 10 10)" />
      <circle cx="17.2" cy="6.2" r="1.2" fill="currentColor" />
    </svg>
  ),
  code: (
    <svg viewBox="0 0 20 20" fill="none" xmlns="http://www.w3.org/2000/svg">
      <rect x="2" y="4" width="16" height="12" rx="2" stroke="currentColor" strokeWidth="1.2" />
      <path d="M7 8l-3 2 3 2M13 8l3 2-3 2" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" strokeLinejoin="round" />
      <path d="M11 7l-2 6" stroke="currentColor" strokeWidth="1.1" strokeLinecap="round" />
    </svg>
  ),
  skills: (
    <svg viewBox="0 0 20 20" fill="none" xmlns="http://www.w3.org/2000/svg">
      <polygon points="10,2 12.5,7.5 18.5,8.3 14.2,12.4 15.3,18.3 10,15.5 4.7,18.3 5.8,12.4 1.5,8.3 7.5,7.5"
        stroke="currentColor" strokeWidth="1.2" strokeLinejoin="round" />
    </svg>
  ),
  settings: (
    <svg viewBox="0 0 20 20" fill="none" xmlns="http://www.w3.org/2000/svg">
      <circle cx="10" cy="10" r="2.5" stroke="currentColor" strokeWidth="1.2" />
      <path d="M10 2v1.5M10 16.5V18M2 10h1.5M16.5 10H18M4.1 4.1l1.1 1.1M14.8 14.8l1.1 1.1M15.9 4.1l-1.1 1.1M5.2 14.8l-1.1 1.1" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" />
    </svg>
  ),
};

const META: { id: HubTab; title: string; cls: string }[] = [
  { id: "osint", title: "OSINT — Global Threat Intercept", cls: "widget-action-btn--osint" },
  { id: "market", title: "Market — Live Stocks", cls: "widget-action-btn--market" },
  { id: "polymarket", title: "Poly — Prediction Markets", cls: "widget-action-btn--polymarket" },
  { id: "apollo", title: "Apollo — Prediction Engine", cls: "widget-action-btn--apollo" },
  { id: "oracle", title: "Oracle — Self-Grading Prediction Track Record", cls: "widget-action-btn--oracle" },
  { id: "shadow", title: "Shadow Net — Tor Browser", cls: "widget-action-btn--shadow" },
  { id: "sentinel", title: "Sentinel — 3D Space Intelligence", cls: "widget-action-btn--sentinel" },
  { id: "aegis", title: "Aegis — Self-Repair Console", cls: "widget-action-btn--aegis" },
  { id: "code", title: "Code — AI Editor", cls: "widget-action-btn--code" },
  { id: "skills", title: "Skills — Web Search, Reports, Music, Calendar", cls: "widget-action-btn--skills" },
];

export function HubButtons() {
  const [overlayTab, setOverlayTab] = useState<HubTab | null>(null);

  const open = (tab: HubTab) => {
    if (inTauri()) void openHubWindow(tab);
    else setOverlayTab(tab);
  };

  return (
    <>
      {META.map((m) => (
        <button
          key={m.id}
          className={`widget-action-btn ${m.cls}`}
          onClick={() => open(m.id)}
          title={m.title}
        >
          {ICONS[m.id]}
        </button>
      ))}

      {overlayTab && (
        <div className="hub-overlay" role="dialog" aria-modal="true">
          <div className="hub-overlay__backdrop" onClick={() => setOverlayTab(null)} />
          <div className="hub-overlay__panel">
            <HubView initialTab={overlayTab} onClose={() => setOverlayTab(null)} />
          </div>
        </div>
      )}
    </>
  );
}

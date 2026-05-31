// The widget's feature launcher row. Three icon buttons (Apollo / OSINT /
// Market) that open the unified Hub window on the matching tab. In Tauri a
// single "hub" window is reused (focus + emit a tab switch if already open);
// in the browser preview it opens an in-page overlay.

import { useState } from "react";
import { HubView, type HubTab } from "./HubView";
import "./Hub.css";

function inTauri(): boolean {
  return typeof window !== "undefined" && "__TAURI_INTERNALS__" in window;
}

async function openHubWindow(tab: HubTab): Promise<void> {
  const { WebviewWindow } = await import("@tauri-apps/api/webviewWindow");
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
    decorations: true,
    transparent: false,
    center: true,
    skipTaskbar: false,
  });
  win.once("tauri://error", (e) => console.error("Hub window failed to open", e));
}

const ICONS: Record<HubTab, React.ReactNode> = {
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
};

const META: { id: HubTab; title: string; cls: string }[] = [
  { id: "osint", title: "OSINT — Global Threat Intercept", cls: "widget-action-btn--osint" },
  { id: "market", title: "Market — Live Stocks", cls: "widget-action-btn--market" },
  { id: "apollo", title: "Apollo — Prediction Engine", cls: "widget-action-btn--apollo" },
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

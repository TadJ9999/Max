// Small square icon button below the chat bar. Future OSINT sub-features will
// sit alongside it in the same row. In Tauri opens a dedicated large window;
// in the browser preview falls back to an in-page overlay.

import { useState } from "react";
import { OsintView } from "./OsintView";
import "./Osint.css";

function inTauri(): boolean {
  return typeof window !== "undefined" && "__TAURI_INTERNALS__" in window;
}

async function openOsintWindow(): Promise<void> {
  const { WebviewWindow } = await import("@tauri-apps/api/webviewWindow");
  const existing = await WebviewWindow.getByLabel("osint");
  if (existing) {
    await existing.setFocus();
    return;
  }
  const win = new WebviewWindow("osint", {
    url: "index.html#osint",
    title: "Max · OSINT — Global Threat Intercept",
    width: 1180,
    height: 760,
    minWidth: 820,
    minHeight: 560,
    resizable: true,
    decorations: true,
    transparent: false,
    center: true,
    skipTaskbar: false,
  });
  win.once("tauri://error", (e) => console.error("OSINT window failed to open", e));
}

export function OsintButton() {
  const [open, setOpen] = useState(false);

  const onClick = () => {
    if (inTauri()) void openOsintWindow();
    else setOpen(true);
  };

  return (
    <>
      {/* Square icon button — sits in a row with future feature buttons */}
      <div className="widget-actions">
        <button
          className="widget-action-btn widget-action-btn--osint"
          onClick={onClick}
          title="OSINT — Global Threat Intercept"
        >
          {/* Radar/globe SVG icon */}
          <svg viewBox="0 0 20 20" fill="none" xmlns="http://www.w3.org/2000/svg">
            <circle cx="10" cy="10" r="8" stroke="currentColor" strokeWidth="1.2" />
            <circle cx="10" cy="10" r="4" stroke="currentColor" strokeWidth="1" strokeDasharray="2 1.5" />
            <circle cx="10" cy="10" r="1.5" fill="currentColor" />
            <line x1="10" y1="2" x2="10" y2="18" stroke="currentColor" strokeWidth="0.8" opacity="0.45" />
            <line x1="2" y1="10" x2="18" y2="10" stroke="currentColor" strokeWidth="0.8" opacity="0.45" />
            {/* Sweep arc indicating live scan */}
            <path d="M10 10 L10 2 A8 8 0 0 1 17.6 14" stroke="currentColor" strokeWidth="1" opacity="0.7" strokeLinecap="round" />
          </svg>
        </button>
      </div>

      {open && (
        <div className="osint-overlay" role="dialog" aria-modal="true">
          <div className="osint-overlay__backdrop" onClick={() => setOpen(false)} />
          <div className="osint-overlay__panel">
            <OsintView onClose={() => setOpen(false)} />
          </div>
        </div>
      )}
    </>
  );
}

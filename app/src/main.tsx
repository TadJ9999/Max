import React from "react";
import ReactDOM from "react-dom/client";
import { initEngineBase } from "./engine";
import App from "./App";
import { OsintView } from "./osint/OsintView";
import { MarketView } from "./market/MarketView";
import { ApolloView } from "./apollo/ApolloView";
import { PolymarketView } from "./polymarket/PolymarketView";
import { AegisView } from "./aegis/AegisView";
import { ShadowNetView } from "./darknet/ShadowNetView";
import { HubView, type HubTab } from "./hub/HubView";
import { MobileApp } from "./mobile/MobileApp";
import "./mobile/Mobile.css";

// /m serves the mobile-first shell (LAN access from phones/Macs).
const isMobile = window.location.pathname === "/m" || window.location.pathname.startsWith("/m/");

// The features open in the unified Hub window (#hub or #hub:<tab>). The legacy
// per-feature hashes (#osint / #market / #apollo) still resolve to their
// standalone view for direct links. Empty hash = the floating widget shell.
const hash = window.location.hash;

function pickRoot() {
  if (isMobile) return <MobileApp />;
  if (hash.startsWith("#hub")) {
    const tab = hash.split(":")[1] as HubTab | undefined;
    return <HubView initialTab={tab ?? "apollo"} />;
  }
  if (hash === "#osint") return <OsintView />;
  if (hash === "#market") return <MarketView />;
  if (hash === "#polymarket") return <PolymarketView />;
  if (hash === "#apollo") return <ApolloView />;
  if (hash === "#aegis") return <AegisView />;
  if (hash === "#shadow") return <ShadowNetView />;
  return <App />;
}

// Resolve the engine base URL (Tauri vs same-origin mobile browser) before
// the first component renders so all API calls use the right URL from the start.
void initEngineBase().then(() => {
  ReactDOM.createRoot(document.getElementById("root") as HTMLElement).render(
    <React.StrictMode>{pickRoot()}</React.StrictMode>,
  );
});

// Safety net: the main widget window starts hidden and is revealed after mount
// (see window.ts). If that path ever fails, force-show shortly after load so the
// window can never get stuck invisible. Only the main widget starts hidden.
if (!window.location.hash && "__TAURI_INTERNALS__" in window) {
  window.setTimeout(() => {
    void (async () => {
      try {
        const { getCurrentWindow } = await import("@tauri-apps/api/window");
        await getCurrentWindow().show();
      } catch {
        /* ignore */
      }
    })();
  }, 2000);
}

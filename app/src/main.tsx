import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import { OsintView } from "./osint/OsintView";

// The OSINT map opens in its own large Tauri window (#osint); the widget shell
// is far too small for it. That window mounts OsintView standalone.
const isOsintWindow = window.location.hash === "#osint";

ReactDOM.createRoot(document.getElementById("root") as HTMLElement).render(
  <React.StrictMode>{isOsintWindow ? <OsintView /> : <App />}</React.StrictMode>,
);

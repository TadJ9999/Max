// Integrated terminal — xterm.js over WebSocket to engine's PowerShell/bash.
// Mounted once and shown/hidden via CSS to preserve shell session state.

import { useEffect, useRef } from "react";
import { Terminal as XTerm } from "@xterm/xterm";
import { FitAddon } from "@xterm/addon-fit";
import "@xterm/xterm/css/xterm.css";
import { ENGINE_URL } from "../engine";

interface TerminalProps {
  isOpen: boolean;
}

export function Terminal({ isOpen }: TerminalProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const termRef = useRef<XTerm | null>(null);
  const fitRef = useRef<FitAddon | null>(null);
  const wsRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    if (!containerRef.current) return;

    const term = new XTerm({
      theme: {
        background: "#0d0d0f",
        foreground: "#c9d1d9",
        cursor: "#58a6ff",
        selectionBackground: "#1c2a3a",
      },
      fontFamily: "'Cascadia Code', 'JetBrains Mono', monospace",
      fontSize: 13,
      cursorBlink: true,
      convertEol: true,
    });

    const fit = new FitAddon();
    term.loadAddon(fit);
    term.open(containerRef.current);
    fit.fit();

    termRef.current = term;
    fitRef.current = fit;

    const wsUrl = ENGINE_URL.replace(/^http/, "ws") + "/code/ws/terminal";
    const ws = new WebSocket(wsUrl);
    wsRef.current = ws;

    ws.onopen = () => {
      term.writeln("\x1b[2m[terminal connected]\x1b[0m");
    };

    ws.onmessage = (e) => {
      if (typeof e.data === "string") term.write(e.data);
    };

    ws.onclose = () => {
      term.writeln("\r\n\x1b[33m[disconnected — close and reopen tab to reconnect]\x1b[0m");
    };

    ws.onerror = () => {
      term.writeln("\r\n\x1b[31m[terminal connection error]\x1b[0m");
    };

    term.onData((data) => {
      if (ws.readyState === WebSocket.OPEN) ws.send(data);
    });

    const ro = new ResizeObserver(() => {
      try { fit.fit(); } catch { /* ignore */ }
    });
    ro.observe(containerRef.current);

    return () => {
      ro.disconnect();
      ws.close();
      term.dispose();
      termRef.current = null;
      wsRef.current = null;
    };
  }, []);

  useEffect(() => {
    if (isOpen) {
      requestAnimationFrame(() => {
        try { fitRef.current?.fit(); } catch { /* ignore */ }
      });
    }
  }, [isOpen]);

  return (
    <div
      ref={containerRef}
      className="code-terminal__xterm"
      style={{ display: isOpen ? "block" : "none" }}
    />
  );
}

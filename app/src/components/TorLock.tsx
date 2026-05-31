import { useEffect, useRef, useState } from "react";
import "./TorLock.css";

export type TorLockStatus = "off" | "connecting" | "connected" | "error";

interface TorLockProps {
  status: TorLockStatus;
  exitIp?: string | null;
  circuitAge?: number;
  onDisconnect: () => void;
  onNewCircuit: () => void;
}

function formatAge(seconds: number): string {
  if (seconds < 60) return `${seconds}s`;
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return `${m}m ${s}s`;
}

export function TorLock({ status, exitIp, circuitAge = 0, onDisconnect, onNewCircuit }: TorLockProps) {
  const [open, setOpen] = useState(false);
  const popoverRef = useRef<HTMLDivElement>(null);

  // Close popover on outside click
  useEffect(() => {
    if (!open) return;
    const handler = (e: MouseEvent) => {
      if (popoverRef.current && !popoverRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [open]);

  return (
    <div className={`tor-lock tor-lock--${status}`} ref={popoverRef}>
      {/* The lock icon button */}
      <button
        className="tor-lock__btn"
        onClick={() => setOpen((v) => !v)}
        aria-label={`Tor ${status}`}
        title={status === "connected" ? `Tor connected — ${exitIp ?? "IP unknown"}` : `Tor ${status}`}
      >
        <svg viewBox="0 0 24 24" fill="none" className="tor-lock__icon" aria-hidden="true">
          {status === "connected" ? (
            /* closed padlock */
            <>
              <rect x="5" y="11" width="14" height="10" rx="2" stroke="currentColor" strokeWidth="1.5" />
              <path d="M8 11V7a4 4 0 1 1 8 0v4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
              <circle cx="12" cy="16" r="1.5" fill="currentColor" />
            </>
          ) : (
            /* open padlock */
            <>
              <rect x="5" y="11" width="14" height="10" rx="2" stroke="currentColor" strokeWidth="1.5" />
              <path d="M8 11V7a4 4 0 0 1 8 0" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
              <circle cx="12" cy="16" r="1.5" fill="currentColor" opacity="0.5" />
            </>
          )}
        </svg>
        {/* rotating arc while connecting */}
        {status === "connecting" && <span className="tor-lock__spin" aria-hidden="true" />}
      </button>

      {/* Popover */}
      {open && (
        <div className="tor-lock__popover">
          <div className={`tor-lock__badge tor-lock__badge--${status}`}>
            {status === "connected" ? "● Connected" : status === "connecting" ? "◌ Connecting…" : "○ Disconnected"}
          </div>

          {status === "connected" && (
            <div className="tor-lock__meta">
              {exitIp && <div className="tor-lock__meta-row"><span>Exit IP</span><span>{exitIp}</span></div>}
              <div className="tor-lock__meta-row"><span>Circuit age</span><span>{formatAge(circuitAge)}</span></div>
            </div>
          )}

          <div className="tor-lock__actions">
            {status === "connected" && (
              <button className="tor-lock__action tor-lock__action--newid" onClick={() => { onNewCircuit(); setOpen(false); }}>
                New Identity
              </button>
            )}
            <button className="tor-lock__action tor-lock__action--disc" onClick={() => { onDisconnect(); setOpen(false); }}>
              Disconnect
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

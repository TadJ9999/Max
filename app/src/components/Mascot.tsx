import { useEffect, useRef, useState } from "react";
import "./Mascot.css";

/**
 * The five engine-reactive states of the mascot.
 * Mirrors the state-machine contract in docs/ui.md, so the rendering tech can
 * change without touching callers.
 */
export type MascotState = "idle" | "thinking" | "busy" | "done" | "error";

export interface MascotProps {
  /** Current engine state. Drives palette + spin speed + glow. */
  state?: MascotState;
  /**
   * VRAM pressure, 0..1. When `state === "busy"` this scales the intensity
   * (spin speed + glow). Ignored in other states.
   */
  vramLoad?: number;
  /** Rendered pixel size (square). Default 160. */
  size?: number;
  /** When true (default), `done` auto-relaxes to `idle` after the bloom beat. */
  autoRelaxDone?: boolean;
  className?: string;
}

const DONE_BEAT_MS = 1300;

type Tick = { x1: number; y1: number; x2: number; y2: number; major: boolean };

/** Evenly spaced radial tick marks around the center (100,100). */
function ticks(count: number, rIn: number, rOut: number, majorEvery = 6): Tick[] {
  return Array.from({ length: count }, (_, i) => {
    const a = (i / count) * Math.PI * 2 - Math.PI / 2;
    const major = i % majorEvery === 0;
    const ri = major ? rIn - 3 : rIn;
    return {
      x1: 100 + Math.cos(a) * ri,
      y1: 100 + Math.sin(a) * ri,
      x2: 100 + Math.cos(a) * rOut,
      y2: 100 + Math.sin(a) * rOut,
      major,
    };
  });
}

const OUTER = ticks(84, 84, 92, 7);
const MID = ticks(48, 66, 72, 6);
const INNER = ticks(60, 44, 49, 5);

/**
 * Max's mascot — a "Jarvis"-style holographic HUD: several counter-rotating
 * rings of tick marks and animated data arcs, a sweeping radar, and a pulsing
 * reactor core with an "X" sigil. Pure SVG + CSS (transparent background), no
 * runtime deps. Multi-color (cyan + amber + white); state shifts the palette,
 * spin speed and glow.
 */
export function Mascot({
  state = "idle",
  vramLoad = 0,
  size = 160,
  autoRelaxDone = true,
  className = "",
}: MascotProps) {
  // Transient "done" beat settles back to idle without the parent timing it.
  const [active, setActive] = useState<MascotState>(state);
  const relaxTimer = useRef<number | null>(null);

  useEffect(() => {
    if (relaxTimer.current) window.clearTimeout(relaxTimer.current);
    setActive(state);
    if (state === "done" && autoRelaxDone) {
      relaxTimer.current = window.setTimeout(() => setActive("idle"), DONE_BEAT_MS);
    }
    return () => {
      if (relaxTimer.current) window.clearTimeout(relaxTimer.current);
    };
  }, [state, autoRelaxDone]);

  const v = clamp01(vramLoad);
  // Base rotation period (seconds): lower = faster.
  const spin =
    active === "busy"
      ? 9 - v * 5
      : active === "error"
        ? 4
        : active === "thinking"
          ? 9
          : active === "done"
            ? 14
            : 18;
  const glow =
    active === "busy"
      ? 0.75 + v * 0.25
      : active === "thinking"
        ? 0.75
        : active === "error"
          ? 0.95
          : active === "done"
            ? 0.9
            : 0.5;

  return (
    <div
      className={`hud ${className}`.trim()}
      data-state={active}
      style={
        {
          "--hud-size": `${size}px`,
          "--spin": `${spin.toFixed(2)}s`,
          "--glow": glow.toFixed(2),
        } as React.CSSProperties
      }
      role="img"
      aria-label={`Max is ${ariaFor(active)}`}
    >
      {/* rotating radar sweep behind the rings */}
      <div className="hud__sweep" />

      <svg viewBox="0 0 200 200" width={size} height={size} className="hud__svg" aria-hidden="true">
        {/* outer tick ring (cyan, slow) */}
        <g className="hud__spin-slow hud__c1">
          {OUTER.map((t, i) => (
            <line
              key={i}
              x1={t.x1}
              y1={t.y1}
              x2={t.x2}
              y2={t.y2}
              className={t.major ? "hud__tick hud__tick--major" : "hud__tick"}
            />
          ))}
          <circle cx="100" cy="100" r="80" className="hud__hairline" pathLength={100} />
        </g>

        {/* amber data arc (reverse, dashes travel) */}
        <g className="hud__spin-rev hud__c2">
          <circle cx="100" cy="100" r="74" className="hud__arc hud__arc--dash" pathLength={100} />
        </g>

        {/* mid tick ring (white, fast) */}
        <g className="hud__spin-fast hud__c3">
          {MID.map((t, i) => (
            <line
              key={i}
              x1={t.x1}
              y1={t.y1}
              x2={t.x2}
              y2={t.y2}
              className={t.major ? "hud__tick hud__tick--major" : "hud__tick"}
            />
          ))}
        </g>

        {/* cyan gapped ring (fast, dashes travel) */}
        <g className="hud__spin-fast hud__c1">
          <circle cx="100" cy="100" r="58" className="hud__ring-gapped hud__arc--dash" pathLength={100} />
        </g>

        {/* inner tick ring (cyan, slow reverse) */}
        <g className="hud__spin-rev-slow hud__c1">
          {INNER.map((t, i) => (
            <line key={i} x1={t.x1} y1={t.y1} x2={t.x2} y2={t.y2} className="hud__tick hud__tick--inner" />
          ))}
        </g>

        {/* fixed crosshair notches (cyan) */}
        <g className="hud__cross hud__c1">
          <line x1="100" y1="26" x2="100" y2="42" />
          <line x1="100" y1="158" x2="100" y2="174" />
          <line x1="26" y1="100" x2="42" y2="100" />
          <line x1="158" y1="100" x2="174" y2="100" />
        </g>

        {/* reactor core */}
        <g className="hud__c2">
          <circle cx="100" cy="100" r="30" className="hud__core-ring" />
        </g>
        <g className="hud__spin-fast hud__c1">
          <circle cx="100" cy="100" r="22" className="hud__core-ring hud__arc--dash" pathLength={100} />
        </g>
        <circle cx="100" cy="100" r="13" className="hud__core hud__c1" />
        {/* core "X" sigil (white) */}
        <g className="hud__sigil">
          <line x1="93" y1="93" x2="107" y2="107" />
          <line x1="107" y1="93" x2="93" y2="107" />
        </g>
      </svg>
    </div>
  );
}

function clamp01(n: number): number {
  return Math.min(1, Math.max(0, Number.isFinite(n) ? n : 0));
}

function ariaFor(s: MascotState): string {
  switch (s) {
    case "thinking":
      return "thinking";
    case "busy":
      return "busy — local queue is deep";
    case "done":
      return "done";
    case "error":
      return "reporting an error";
    default:
      return "idle";
  }
}

export default Mascot;

import { useEffect, useRef, useState } from "react";
import "./Mascot.css";

/**
 * The five engine-reactive states of the mascot.
 * Mirrors the state-machine contract in docs/ui.md, so the rendering tech can
 * change without touching callers.
 */
export type MascotState = "idle" | "thinking" | "busy" | "done" | "error";

export interface MascotProps {
  /** Current engine state. Drives color + spin speed + glow. */
  state?: MascotState;
  /**
   * VRAM pressure, 0..1. When `state === "busy"` this scales the intensity
   * (spin speed + glow) — the deeper the local queue, the faster the HUD spins.
   * Ignored in other states.
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

const OUTER = ticks(72, 84, 92);
const INNER = ticks(48, 44, 50);

/**
 * Max's mascot — a "Jarvis"-style holographic HUD: concentric rings of tick
 * marks and dashed arcs counter-rotating around a pulsing reactor core. Pure
 * SVG + CSS (transparent background), no runtime deps. State drives the accent
 * color, spin speed and glow.
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
      ? 0.7 + v * 0.3
      : active === "thinking"
        ? 0.7
        : active === "error"
          ? 0.9
          : active === "done"
            ? 0.85
            : 0.4;

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
      <svg viewBox="0 0 200 200" width={size} height={size} className="hud__svg" aria-hidden="true">
        {/* outer tick ring (slow) */}
        <g className="hud__spin-slow">
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
        </g>

        {/* dashed arc ring (reverse) */}
        <g className="hud__spin-rev">
          <circle cx="100" cy="100" r="74" className="hud__arc" pathLength={100} />
        </g>

        {/* gapped ring (fast) */}
        <g className="hud__spin-fast">
          <circle cx="100" cy="100" r="62" className="hud__ring-gapped" pathLength={100} />
        </g>

        {/* inner tick ring (slow reverse) */}
        <g className="hud__spin-rev-slow">
          {INNER.map((t, i) => (
            <line
              key={i}
              x1={t.x1}
              y1={t.y1}
              x2={t.x2}
              y2={t.y2}
              className="hud__tick hud__tick--inner"
            />
          ))}
        </g>

        {/* fixed crosshair notches */}
        <g className="hud__cross">
          <line x1="100" y1="28" x2="100" y2="44" />
          <line x1="100" y1="156" x2="100" y2="172" />
          <line x1="28" y1="100" x2="44" y2="100" />
          <line x1="156" y1="100" x2="172" y2="100" />
        </g>

        {/* reactor core */}
        <circle cx="100" cy="100" r="26" className="hud__core-ring" />
        <circle cx="100" cy="100" r="14" className="hud__core" />
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

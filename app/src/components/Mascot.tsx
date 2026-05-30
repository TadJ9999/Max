import { useEffect, useRef, useState } from "react";
import "./Mascot.css";

/**
 * The five engine-reactive states of the mascot.
 * Mirrors the state-machine contract in docs/ui.md, so the rendering tech can
 * change (here: a canvas particle cloud) without touching callers.
 */
export type MascotState = "idle" | "thinking" | "busy" | "done" | "error";

export interface MascotProps {
  /** Current engine state. Drives the cloud's motion, spread and color. */
  state?: MascotState;
  /**
   * VRAM pressure, 0..1. When `state === "busy"` this scales the intensity
   * (swirl speed, spread, brightness) — the deeper the local queue, the more
   * agitated the cloud. Ignored in other states.
   */
  vramLoad?: number;
  /** Rendered pixel size (square). Default 160. */
  size?: number;
  /** When true (default), `done` auto-relaxes to `idle` after the bloom beat. */
  autoRelaxDone?: boolean;
  className?: string;
}

const DONE_BEAT_MS = 1300;

/** Tuning per state. Targets are smoothly approached each frame. */
interface StateProfile {
  speed: number; // swirl rate
  spread: number; // radius scale
  brightness: number; // particle alpha multiplier
  turbulence: number; // random per-frame jitter (error)
  palette: string[]; // center → edge colors
}

const CYAN = ["#bff5ff", "#67e8f9", "#22d3ee", "#2dd4bf"];
const GREEN = ["#d1fae5", "#6ee7b7", "#34d399", "#10b981"];
const RED = ["#ffe4e6", "#fda4af", "#fb7185", "#f43f5e"];

function profileFor(state: MascotState, vram: number): StateProfile {
  switch (state) {
    case "thinking":
      return { speed: 0.55, spread: 1.0, brightness: 0.85, turbulence: 0, palette: CYAN };
    case "busy":
      return {
        speed: 0.7 + vram * 1.0,
        spread: 1.04 + vram * 0.12,
        brightness: 1.0,
        turbulence: vram * 0.6,
        palette: CYAN,
      };
    case "done":
      return { speed: 0.35, spread: 1.0, brightness: 1.0, turbulence: 0, palette: GREEN };
    case "error":
      return { speed: 0.85, spread: 1.08, brightness: 0.95, turbulence: 2.4, palette: RED };
    default:
      return { speed: 0.16, spread: 0.9, brightness: 0.5, turbulence: 0, palette: CYAN };
  }
}

interface Particle {
  r0: number; // base radius fraction 0..1
  a0: number; // base angle
  ci: number; // palette color index
  size: number; // dot radius (css px)
  alpha: number; // base alpha
  wobAmp: number; // radial wobble amplitude
  wobFreq: number;
  wobPhase: number;
}

/** A soft round glow sprite, cached per color. */
function makeSprite(color: string): HTMLCanvasElement {
  const s = 64;
  const c = document.createElement("canvas");
  c.width = c.height = s;
  const ctx = c.getContext("2d")!;
  const g = ctx.createRadialGradient(s / 2, s / 2, 0, s / 2, s / 2, s / 2);
  g.addColorStop(0, color);
  g.addColorStop(0.4, hexA(color, 0.45));
  g.addColorStop(1, hexA(color, 0));
  ctx.fillStyle = g;
  ctx.fillRect(0, 0, s, s);
  return c;
}

function hexA(hex: string, a: number): string {
  const n = parseInt(hex.slice(1), 16);
  return `rgba(${(n >> 16) & 255}, ${(n >> 8) & 255}, ${n & 255}, ${a})`;
}

/**
 * Max's mascot — an Apple-Watch-pairing-style swirling dust cloud, rendered on
 * a canvas with additive blending. Pure browser APIs, no runtime deps.
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

  // Latest inputs, read by the animation loop without restarting it.
  const stateRef = useRef(active);
  const vramRef = useRef(vramLoad);
  const doneAtRef = useRef<number>(-Infinity);
  stateRef.current = active;
  vramRef.current = clamp01(vramLoad);

  useEffect(() => {
    if (relaxTimer.current) window.clearTimeout(relaxTimer.current);
    setActive(state);
    if (state === "done") {
      doneAtRef.current = performance.now();
      if (autoRelaxDone) {
        relaxTimer.current = window.setTimeout(() => setActive("idle"), DONE_BEAT_MS);
      }
    }
    return () => {
      if (relaxTimer.current) window.clearTimeout(relaxTimer.current);
    };
  }, [state, autoRelaxDone]);

  const canvasRef = useRef<HTMLCanvasElement | null>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d")!;
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    canvas.width = size * dpr;
    canvas.height = size * dpr;
    ctx.scale(dpr, dpr);

    const cx = size / 2;
    const cy = size / 2;
    const maxR = size * 0.42;
    const count = Math.round(size * 2.4);

    // Build the cloud: denser toward the center (radius biased), brighter core.
    const particles: Particle[] = Array.from({ length: count }, () => {
      const r0 = Math.pow(Math.random(), 0.7);
      return {
        r0,
        a0: Math.random() * Math.PI * 2,
        ci: r0 < 0.35 ? 0 : r0 < 0.6 ? 1 : r0 < 0.85 ? 2 : 3,
        size: 1.2 + Math.random() * 1.8,
        alpha: 0.22 + (1 - r0) * 0.22,
        wobAmp: 0.02 + Math.random() * 0.06,
        wobFreq: 0.6 + Math.random() * 1.4,
        wobPhase: Math.random() * Math.PI * 2,
      };
    });

    const sprites = new Map<string, HTMLCanvasElement>();
    const sprite = (color: string) => {
      let s = sprites.get(color);
      if (!s) sprites.set(color, (s = makeSprite(color)));
      return s;
    };

    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

    // Smoothed running values + phase accumulators.
    let speed = 0.16;
    let spread = 0.9;
    let bright = 0.5;
    let turb = 0;
    let swirl = 0; // accumulated swirl phase (advances by speed)
    let last = performance.now();
    let raf = 0;
    let cancelled = false;

    const frame = (now: number) => {
      if (cancelled) return;
      const dt = Math.min((now - last) / 1000, 0.05);
      last = now;

      const target = profileFor(stateRef.current, vramRef.current);

      // Done bloom: a radial pop that eases out over the beat window.
      let bloom = 0;
      const sinceDone = now - doneAtRef.current;
      if (sinceDone >= 0 && sinceDone < DONE_BEAT_MS) {
        const t = sinceDone / DONE_BEAT_MS;
        bloom = Math.sin(Math.min(t * 3.0, Math.PI)) * 0.35 * (1 - t);
      }

      // Ease toward targets for buttery state transitions.
      const k = 1 - Math.pow(0.001, dt); // frame-rate independent smoothing
      speed += (target.speed - speed) * k;
      spread += (target.spread + bloom - spread) * k;
      bright += (target.brightness - bright) * k;
      turb += (target.turbulence - turb) * k;
      swirl += dt * speed;

      const clock = now / 1000;
      ctx.clearRect(0, 0, size, size);
      ctx.globalCompositeOperation = "lighter";

      for (const p of particles) {
        // Differential rotation (inner faster) → continuous nebula swirl.
        const ang = p.a0 + swirl * (1.6 - p.r0 * 0.9);
        const wob = p.r0 + p.wobAmp * Math.sin(clock * p.wobFreq + p.wobPhase);
        const R = wob * maxR * spread;
        let x = cx + Math.cos(ang) * R;
        let y = cy + Math.sin(ang) * R;
        if (turb > 0.001) {
          x += (Math.random() - 0.5) * turb;
          y += (Math.random() - 0.5) * turb;
        }
        const d = p.size * 5;
        ctx.globalAlpha = Math.min(p.alpha * bright, 1);
        ctx.drawImage(sprite(target.palette[p.ci]), x - d / 2, y - d / 2, d, d);
      }
      ctx.globalAlpha = 1;

      if (!reduced) raf = requestAnimationFrame(frame);
    };

    raf = requestAnimationFrame(frame);
    return () => {
      cancelled = true;
      cancelAnimationFrame(raf);
    };
  }, [size]);

  return (
    <div
      className={`mascot ${className}`.trim()}
      data-state={active}
      style={{ "--mascot-size": `${size}px` } as React.CSSProperties}
      role="img"
      aria-label={`Max is ${ariaFor(active)}`}
    >
      <canvas ref={canvasRef} className="mascot__canvas" style={{ width: size, height: size }} />
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

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

  // ---- canvas FX: circular waveform + drifting particles -----------------
  // Latest inputs, read by the loop without restarting it.
  const stateRef = useRef<MascotState>(active);
  const vramRef = useRef<number>(vramLoad);
  stateRef.current = active;
  vramRef.current = clamp01(vramLoad);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    canvas.width = size * dpr;
    canvas.height = size * dpr;
    ctx.scale(dpr, dpr);

    const cx = size / 2;
    const cy = size / 2;
    const maxR = size * 0.46;
    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

    const particles = Array.from({ length: Math.round(size * 0.5) }, () => ({
      a: Math.random() * Math.PI * 2,
      r: 0.46 + Math.random() * 0.56,
      sp: 0.1 + Math.random() * 0.5,
      sz: 0.6 + Math.random() * 1.6,
      tw: Math.random() * Math.PI * 2,
      drift: (Math.random() - 0.5) * 0.0009,
      c: Math.random() < 0.5,
    }));

    const start = performance.now();
    let raf = 0;
    let cancelled = false;

    const frame = (now: number) => {
      if (cancelled) return;
      const t = (now - start) / 1000;
      const st = stateRef.current;
      const v = clamp01(vramRef.current);
      const pal = paletteFor(st);
      const amp =
        st === "busy" ? 0.5 + v * 0.6 : st === "thinking" ? 0.55 : st === "error" ? 0.7 : st === "done" ? 0.5 : 0.34;
      const spd = st === "busy" ? 1.3 + v : st === "error" ? 1.8 : st === "thinking" ? 1.1 : 0.6;

      ctx.clearRect(0, 0, size, size);
      ctx.globalCompositeOperation = "lighter";

      // circular waveform blob (layered sines → organic audio look)
      const N = 140;
      const baseR = maxR * 0.42;
      const grad = ctx.createLinearGradient(cx - baseR, cy - baseR, cx + baseR, cy + baseR);
      grad.addColorStop(0, pal.c1);
      grad.addColorStop(1, pal.c2);
      ctx.beginPath();
      for (let i = 0; i <= N; i++) {
        const ang = (i / N) * Math.PI * 2;
        const wave =
          Math.sin(ang * 6 + t * spd * 2) * 0.5 +
          Math.sin(ang * 11 - t * spd * 1.3) * 0.3 +
          Math.sin(ang * 3 + t * spd) * 0.2;
        const rr = baseR * (1 + wave * amp * 0.5);
        const x = cx + Math.cos(ang) * rr;
        const y = cy + Math.sin(ang) * rr;
        if (i === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
      }
      ctx.closePath();
      ctx.shadowColor = pal.c1;
      ctx.shadowBlur = 8;
      ctx.lineWidth = 1.6;
      ctx.strokeStyle = grad;
      ctx.globalAlpha = 0.45 + amp * 0.3;
      ctx.stroke();
      ctx.shadowBlur = 0;
      ctx.globalAlpha = 0.08;
      ctx.fillStyle = grad;
      ctx.fill();

      // drifting, twinkling particles
      for (const p of particles) {
        p.a += p.sp * 0.01 * spd;
        p.r += p.drift;
        if (p.r > 1.04 || p.r < 0.44) p.drift *= -1;
        const rr = p.r * maxR;
        const x = cx + Math.cos(p.a) * rr;
        const y = cy + Math.sin(p.a) * rr;
        const tw = 0.35 + 0.65 * Math.abs(Math.sin(t * 1.5 + p.tw));
        ctx.globalAlpha = tw * 0.8;
        ctx.fillStyle = p.c ? pal.c1 : pal.c2;
        ctx.beginPath();
        ctx.arc(x, y, p.sz, 0, Math.PI * 2);
        ctx.fill();
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

      {/* canvas FX: waveform + particles, behind the crisp SVG rings */}
      <canvas
        ref={canvasRef}
        className="hud__fx"
        width={size}
        height={size}
        style={{ width: size, height: size }}
      />

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
        {/* pulsing reactor core */}
        <circle cx="100" cy="100" r="13" className="hud__core hud__c1" />
        <circle cx="100" cy="100" r="5" className="hud__core-hot" />
      </svg>
    </div>
  );
}

function clamp01(n: number): number {
  return Math.min(1, Math.max(0, Number.isFinite(n) ? n : 0));
}

/** Canvas FX palette (hex) per state — matches the CSS ring palette. */
function paletteFor(s: MascotState): { c1: string; c2: string } {
  switch (s) {
    case "done":
      return { c1: "#34d399", c2: "#6ee7b7" };
    case "error":
      return { c1: "#fb7185", c2: "#f472b6" };
    default:
      return { c1: "#22d3ee", c2: "#f24fd6" };
  }
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

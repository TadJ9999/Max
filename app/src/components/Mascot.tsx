import { useEffect, useRef } from "react";
import "./Mascot.css";

/** Engine-reactive states (error tints the whole instrument red). */
export type MascotState = "idle" | "thinking" | "busy" | "done" | "error";

export interface MascotMetrics {
  cpu: number; // 0..100
  gpu: number; // 0..100
  vram: number; // 0..100
  ram: number; // 0..100
  gpuTemp: number; // °C (0 if unavailable)
}

export interface MascotProps {
  state?: MascotState;
  metrics?: MascotMetrics;
  size?: number;
  className?: string;
}

const ZERO: MascotMetrics = { cpu: 0, gpu: 0, vram: 0, ram: 0, gpuTemp: 0 };

type Tick = { x1: number; y1: number; x2: number; y2: number; major: boolean };

function notches(count: number, rIn: number, rOut: number, majorEvery = 5): Tick[] {
  return Array.from({ length: count }, (_, i) => {
    const a = (i / count) * Math.PI * 2 - Math.PI / 2;
    const major = i % majorEvery === 0;
    const ri = major ? rIn - 2 : rIn;
    return {
      x1: 100 + Math.cos(a) * ri,
      y1: 100 + Math.sin(a) * ri,
      x2: 100 + Math.cos(a) * rOut,
      y2: 100 + Math.sin(a) * rOut,
      major,
    };
  });
}

const OUTER = notches(90, 90, 95, 6);
const MIDNOTCH = notches(60, 83, 87, 5);
const INNER = notches(36, 43, 47, 3);

const clamp = (n: number, lo = 0, hi = 100) => Math.min(hi, Math.max(lo, Number.isFinite(n) ? n : 0));

/**
 * Heat → accent. Strict bands (cyan normal → amber warm → red hot) rather than a
 * blended lerp, which would muddy cyan↔amber. CSS transitions smooth crossings.
 */
function heatColor(tempC: number): string {
  if (tempC >= 80) return "rgb(255, 59, 59)"; // hot
  if (tempC >= 68) return "rgb(245, 165, 36)"; // warm
  return "rgb(34, 211, 238)"; // cool / no reading → cyan
}

/** A thin gauge arc: faint full-circle track + accent fill to `pct` from top. */
function Gauge({ r, pct, label }: { r: number; pct: number; label: string }) {
  const p = clamp(pct);
  return (
    <g className="hud__gauge">
      <circle cx="100" cy="100" r={r} className="hud__gauge-track" />
      <circle
        cx="100"
        cy="100"
        r={r}
        className="hud__gauge-fill"
        pathLength={100}
        strokeDasharray={`${p} ${100 - p}`}
        transform="rotate(-90 100 100)"
      />
      <text x="100" y={100 - r - 1.5} className="hud__gauge-label">
        {label}
      </text>
    </g>
  );
}

/**
 * Max's mascot — a thin-wireframe holographic instrument. Everything maps to
 * real state:
 *   • outer + mid notched rings spin faster with VRAM load
 *   • inner notched ring spins with CPU load
 *   • CPU/GPU/VRAM/RAM each have a gauge arc
 *   • accent color (rings + core) tracks GPU temperature: cyan → amber → red
 *   • `error` state forces red
 * Rotation is rAF-driven (seamless, no loop seam) and reads the latest metrics
 * without restarting.
 */
export function Mascot({ state = "idle", metrics = ZERO, size = 160, className = "" }: MascotProps) {
  const r1 = useRef<SVGGElement | null>(null);
  const r2 = useRef<SVGGElement | null>(null);
  const r3 = useRef<SVGGElement | null>(null);
  const core = useRef<SVGGElement | null>(null);

  const mref = useRef<MascotMetrics>(metrics);
  mref.current = metrics;

  useEffect(() => {
    let raf = 0;
    let last = performance.now();
    let a1 = 0;
    let a2 = 0;
    let a3 = 0;
    let t = 0;
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

    const frame = (now: number) => {
      const dt = Math.min((now - last) / 1000, 0.05);
      last = now;
      t += dt;
      const m = mref.current;
      // deg/sec: ring speed tied to load
      const outer = 5 + clamp(m.vram) * 0.45; // VRAM → outer rings
      const inner = 7 + clamp(m.cpu) * 0.6; // CPU → inner ring
      a1 += dt * outer;
      a2 -= dt * outer * 0.72;
      a3 += dt * inner;
      if (r1.current) r1.current.style.transform = `rotate(${a1}deg)`;
      if (r2.current) r2.current.style.transform = `rotate(${a2}deg)`;
      if (r3.current) r3.current.style.transform = `rotate(${a3}deg)`;
      if (core.current) {
        const s = 1 + Math.sin(t * 2.2) * 0.05;
        core.current.style.transform = `scale(${s})`;
      }
      if (!reduce) raf = requestAnimationFrame(frame);
    };
    raf = requestAnimationFrame(frame);
    return () => cancelAnimationFrame(raf);
  }, []);

  const accent = state === "error" ? "rgb(255, 59, 59)" : heatColor(metrics.gpuTemp);

  return (
    <div
      className={`hud ${className}`.trim()}
      data-state={state}
      style={{ "--hud-size": `${size}px`, "--accent": accent } as React.CSSProperties}
      role="img"
      aria-label={`Max — CPU ${Math.round(metrics.cpu)}%, GPU ${Math.round(metrics.gpu)}%, VRAM ${Math.round(
        metrics.vram,
      )}%, ${Math.round(metrics.gpuTemp)}°C`}
    >
      <svg viewBox="0 0 200 200" width={size} height={size} className="hud__svg" aria-hidden="true">
        {/* fixed crosshair ticks */}
        <g className="hud__cross">
          <line x1="100" y1="2" x2="100" y2="9" />
          <line x1="100" y1="191" x2="100" y2="198" />
          <line x1="2" y1="100" x2="9" y2="100" />
          <line x1="191" y1="100" x2="198" y2="100" />
        </g>

        {/* outer notched ring — VRAM speed */}
        <g ref={r1} className="hud__ring hud__spin">
          <circle cx="100" cy="100" r="95" className="hud__hair" />
          {OUTER.map((t, i) => (
            <line key={i} x1={t.x1} y1={t.y1} x2={t.x2} y2={t.y2} className={t.major ? "hud__tick hud__tick--maj" : "hud__tick"} />
          ))}
        </g>

        {/* mid notched ring — VRAM speed (counter) */}
        <g ref={r2} className="hud__ring hud__spin">
          <circle cx="100" cy="100" r="87" className="hud__hair" />
          {MIDNOTCH.map((t, i) => (
            <line key={i} x1={t.x1} y1={t.y1} x2={t.x2} y2={t.y2} className="hud__tick" />
          ))}
        </g>

        {/* metric gauges */}
        <g className="hud__gauges">
          <Gauge r={78} pct={metrics.cpu} label="C" />
          <Gauge r={71} pct={metrics.gpu} label="G" />
          <Gauge r={64} pct={metrics.vram} label="V" />
          <Gauge r={57} pct={metrics.ram} label="R" />
        </g>

        {/* inner notched ring — CPU speed, accent (heat) color */}
        <g ref={r3} className="hud__ring hud__spin hud__inner">
          <circle cx="100" cy="100" r="47" className="hud__hair-accent" />
          {INNER.map((t, i) => (
            <line key={i} x1={t.x1} y1={t.y1} x2={t.x2} y2={t.y2} className="hud__tick--accent" />
          ))}
        </g>

        {/* core */}
        <g ref={core} className="hud__core">
          <circle cx="100" cy="100" r="30" className="hud__hair-accent" />
          <circle cx="100" cy="100" r="20" className="hud__hair-accent" />
          <circle cx="100" cy="100" r="6.5" className="hud__core-dot" />
        </g>
      </svg>
    </div>
  );
}

export default Mascot;

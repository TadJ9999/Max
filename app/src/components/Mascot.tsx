import { useEffect, useMemo, useRef, useState } from "react";
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
  /** Increment to fire a "request incoming" comet that strikes the core. */
  signal?: number;
  /**
   * Drive the "thinking" core shimmer directly (e.g. from the chat box). It is
   * OR-combined with the `state`-derived thinking, so either source lights it.
   * A ripple blast fires on the falling edge (response complete).
   */
  thinking?: boolean;
  /** Engine/host unreachable — the core destabilises and glows red. */
  systemDown?: boolean;
  /**
   * Increment on every vector-DB read/write to pulse the particle field — the
   * "Max is learning" cue. Each bump flashes the motes brighter for a beat.
   */
  dbActivity?: number;
}

const ZERO: MascotMetrics = { cpu: 0, gpu: 0, vram: 0, ram: 0, gpuTemp: 0 };

const RED = "rgb(255, 59, 59)";

// comet travel time (ms) — keep in sync with the `comet-in` CSS keyframe
const COMET_MS = 750;

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

// deterministic [0,1) — keeps the particle field stable across renders
const rand = (n: number) => {
  const x = Math.sin(n * 127.1) * 43758.5453;
  return x - Math.floor(x);
};

/**
 * Heat → accent. Strict bands (cyan normal → amber warm → red hot) rather than a
 * blended lerp, which would muddy cyan↔amber. CSS transitions smooth crossings.
 */
function heatColor(tempC: number): string {
  if (tempC >= 80) return RED; // hot
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
 * Max's mascot — a thin-wireframe holographic instrument with a glowing reactor
 * core that reacts to the request → think → respond lifecycle:
 *   • `signal` bump → a comet streaks in from a random angle and strikes the core
 *   • while thinking/busy → the core shimmers an iridescent "intelligence" color
 *   • on response (thinking falling edge) → a ripple shockwave + glow blast
 * Plus the steady-state instrument: notched rings spin with VRAM/CPU load, gauges
 * show CPU/GPU/VRAM/RAM, accent tracks GPU heat (cyan → amber → red), and
 * `systemDown` forces an offline-red flicker. Rotation is rAF-driven (seamless).
 */
export function Mascot({
  state = "idle",
  metrics = ZERO,
  size = 160,
  className = "",
  signal,
  thinking,
  systemDown = false,
  dbActivity,
}: MascotProps) {
  const isThinking = (Boolean(thinking) || state === "thinking" || state === "busy") && !systemDown;

  // DB read/write pulse: flash the particle field briefly on each bump.
  const [dbPulsing, setDbPulsing] = useState(false);
  const lastDb = useRef(dbActivity);
  useEffect(() => {
    if (dbActivity === undefined || dbActivity === lastDb.current) return;
    lastDb.current = dbActivity;
    setDbPulsing(true);
    const t = window.setTimeout(() => setDbPulsing(false), 700);
    return () => window.clearTimeout(t);
  }, [dbActivity]);

  // Request comets: a streak flies in from a random angle and lands on the core.
  const [comets, setComets] = useState<Array<{ id: number; angle: number }>>([]);
  const [absorb, setAbsorb] = useState(0); // bumped when a comet reaches the core
  const lastSignal = useRef(signal);
  useEffect(() => {
    if (signal === undefined || signal === lastSignal.current) return;
    lastSignal.current = signal;
    const id = signal;
    setComets((cs) => [...cs, { id, angle: Math.random() * 360 }]);
    const land = window.setTimeout(() => setAbsorb((a) => a + 1), COMET_MS - 40);
    const gone = window.setTimeout(() => setComets((cs) => cs.filter((c) => c.id !== id)), COMET_MS + 120);
    return () => {
      window.clearTimeout(land);
      window.clearTimeout(gone);
    };
  }, [signal]);

  // Response blast: fire a one-shot ripple when thinking ends.
  const [ripple, setRipple] = useState(0);
  const prevThinking = useRef(isThinking);
  useEffect(() => {
    if (prevThinking.current && !isThinking) setRipple((r) => r + 1);
    prevThinking.current = isThinking;
  }, [isThinking]);

  // A deliberately sparse field of motes drifting around the core.
  const particles = useMemo(() => {
    const palette = ["var(--accent)", "var(--accent-2)", "rgba(222, 240, 255, 0.75)"];
    return Array.from({ length: 12 }, (_, i) => {
      const seed = i + 1;
      const a = rand(seed) * Math.PI * 2;
      const radius = 33 + rand(seed * 1.7) * 43;
      return {
        cx: 100 + Math.cos(a) * radius,
        cy: 100 + Math.sin(a) * radius,
        r: 0.6 + rand(seed * 3) * 1.4,
        fill: palette[i % palette.length],
        delay: rand(seed * 4) * 6,
        dur: 4 + rand(seed * 5) * 5,
      };
    });
  }, []);

  const r1 = useRef<SVGGElement | null>(null);
  const r2 = useRef<SVGGElement | null>(null);
  const r3 = useRef<SVGGElement | null>(null);

  const mref = useRef<MascotMetrics>(metrics);
  mref.current = metrics;
  const downRef = useRef(systemDown);
  downRef.current = systemDown;

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
      // deg/sec: ring speed tied to load (rings stall when the host is down)
      const load = downRef.current ? 0 : 1;
      const outer = (5 + clamp(m.vram) * 0.45) * load; // VRAM → outer rings
      const inner = (7 + clamp(m.cpu) * 0.6) * load; // CPU → inner ring
      a1 += dt * outer;
      a2 -= dt * outer * 0.72;
      a3 += dt * inner;
      if (r1.current) r1.current.style.transform = `rotate(${a1}deg)`;
      if (r2.current) r2.current.style.transform = `rotate(${a2}deg)`;
      if (r3.current) r3.current.style.transform = `rotate(${a3}deg)`;
      if (!reduce) raf = requestAnimationFrame(frame);
    };
    raf = requestAnimationFrame(frame);
    return () => cancelAnimationFrame(raf);
  }, []);

  const accent = systemDown || state === "error" ? RED : heatColor(metrics.gpuTemp);

  return (
    <div
      className={`hud ${className}`.trim()}
      data-state={state}
      data-thinking={isThinking ? "true" : undefined}
      data-down={systemDown ? "true" : undefined}
      style={{ "--hud-size": `${size}px`, "--accent": accent } as React.CSSProperties}
      role="img"
      aria-label={
        systemDown
          ? "Max — system offline"
          : `Max — CPU ${Math.round(metrics.cpu)}%, GPU ${Math.round(metrics.gpu)}%, VRAM ${Math.round(
              metrics.vram,
            )}%, ${Math.round(metrics.gpuTemp)}°C`
      }
    >
      <svg viewBox="0 0 200 200" width={size} height={size} className="hud__svg" aria-hidden="true">
        <defs>
          <radialGradient id="hud-core" cx="50%" cy="50%" r="50%">
            <stop offset="0%" stopColor="#ffffff" stopOpacity="0.95" />
            <stop offset="28%" stopColor="var(--accent)" stopOpacity="0.85" />
            <stop offset="100%" stopColor="var(--accent)" stopOpacity="0" />
          </radialGradient>
          <radialGradient id="hud-halo" cx="50%" cy="50%" r="50%">
            <stop offset="0%" stopColor="var(--accent-2)" stopOpacity="0.16" />
            <stop offset="70%" stopColor="var(--accent)" stopOpacity="0.05" />
            <stop offset="100%" stopColor="var(--accent)" stopOpacity="0" />
          </radialGradient>
        </defs>

        {/* ambient halo (violet) — gives the field depth without reading as blue */}
        <circle className="hud__halo" cx="100" cy="100" r="78" style={{ fill: "url(#hud-halo)" }} />

        {/* fixed crosshair ticks */}
        <g className="hud__cross">
          <line x1="100" y1="2" x2="100" y2="9" />
          <line x1="100" y1="191" x2="100" y2="198" />
          <line x1="2" y1="100" x2="9" y2="100" />
          <line x1="191" y1="100" x2="198" y2="100" />
        </g>

        {/* outer notched ring — VRAM speed (violet structure) */}
        <g ref={r1} className="hud__ring hud__spin hud__ring--alt">
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

        {/* sparse drifting particle field (pulses on DB read/write) */}
        <g className={`hud__particles${dbPulsing ? " hud__particles--db" : ""}`}>
          {particles.map((p, i) => (
            <circle
              key={i}
              className="hud__particle"
              cx={p.cx}
              cy={p.cy}
              r={p.r}
              style={{ fill: p.fill, animationDelay: `${p.delay}s`, animationDuration: `${p.dur}s` }}
            />
          ))}
        </g>

        {/* inner notched ring — CPU speed, accent (heat) color */}
        <g ref={r3} className="hud__ring hud__spin hud__inner">
          <circle cx="100" cy="100" r="47" className="hud__hair-accent" />
          {INNER.map((t, i) => (
            <line key={i} x1={t.x1} y1={t.y1} x2={t.x2} y2={t.y2} className="hud__tick--accent" />
          ))}
        </g>

      </svg>

      {/* Apple-Intelligence liquid-glass core orb (shifts colour while thinking) */}
      <div className="hud__orb" aria-hidden="true">
        <span className="hud__orb-fluid hud__orb-fluid--a" />
        <span className="hud__orb-fluid hud__orb-fluid--b" />
        <span className="hud__orb-fluid hud__orb-fluid--c" />
        <span className="hud__orb-gloss" />
      </div>

      {/* HTML effect layer (comet strike / response ripple) */}
      <div className="hud__fx">
        {absorb > 0 && <div key={`a${absorb}`} className="hud__absorb" />}
        {ripple > 0 && <div key={`r${ripple}`} className="hud__ripple" />}
        {ripple > 0 && <div key={`b${ripple}`} className="hud__blast" />}
      </div>

      {/* request comets */}
      <div className="hud__comets">
        {comets.map((c) => (
          <span key={c.id} className="comet" style={{ transform: `rotate(${c.angle}deg)` }}>
            <span className="comet__streak" />
          </span>
        ))}
      </div>
    </div>
  );
}

export default Mascot;

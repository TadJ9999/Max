/**
 * Animated chocolate toy poodle for the ChatBar idle state.
 * Trots left→right, turns around (scaleX flip), trots back.
 * Randomly stops to sit, sleep, smile, or play with a ball.
 */

import { useEffect, useState } from "react";

type Mode = "running" | "sitting" | "sleeping" | "smiling" | "playing";

const C = {
  main: "#8B4513",
  dark: "#6B3210",
  light: "#A0522D",
  nose: "#2d1a0e",
};

// ── Pose SVGs ─────────────────────────────────────────────────────────────────

function RunSVG() {
  return (
    <svg viewBox="0 -3 46 33" width="30" height="21" className="poodle-bob">
      <circle cx="7" cy="6" r="3.5" fill={C.light} />
      <path d="M10 14 Q5 10 7 6" stroke={C.main} strokeWidth="2.5" fill="none" strokeLinecap="round" />
      <ellipse cx="21" cy="17" rx="10.5" ry="6.5" fill={C.main} />
      <line x1="14" y1="21" x2="9"  y2="26" stroke={C.dark} strokeWidth="2.5" strokeLinecap="round" />
      <line x1="18" y1="21" x2="21" y2="26" stroke={C.dark} strokeWidth="2.5" strokeLinecap="round" />
      <circle cx="9"  cy="26" r="2.5" fill={C.light} />
      <circle cx="21" cy="26" r="2.5" fill={C.light} />
      <circle cx="30" cy="17" r="4.5" fill={C.light} />
      <line x1="26" y1="21" x2="22" y2="26" stroke={C.dark} strokeWidth="2.5" strokeLinecap="round" />
      <line x1="30" y1="21" x2="35" y2="26" stroke={C.dark} strokeWidth="2.5" strokeLinecap="round" />
      <circle cx="22" cy="26" r="2.5" fill={C.light} />
      <circle cx="35" cy="26" r="2.5" fill={C.light} />
      <ellipse cx="34" cy="12" rx="3.5" ry="5"   fill={C.main} />
      <circle  cx="37" cy="9"  r="6.5"            fill={C.main} />
      <ellipse cx="35" cy="14.5" rx="2.5" ry="4.5" fill={C.dark} transform="rotate(-12,35,14.5)" />
      <circle  cx="37" cy="3.5" r="4"             fill={C.light} />
      <ellipse cx="42" cy="10.5" rx="2.5" ry="2"  fill={C.dark} />
      <ellipse cx="44" cy="10"   rx="1.3" ry="1"  fill={C.nose} />
      <circle  cx="39" cy="8"    r="1.4"           fill={C.nose} />
      <circle  cx="39.6" cy="7.4" r="0.55"         fill="rgba(255,255,255,0.75)" />
    </svg>
  );
}

function SitSVG({ smile = false }: { smile?: boolean }) {
  return (
    <svg viewBox="0 -3 40 27" width="26" height="18">
      <circle cx="4" cy="8" r="3"   fill={C.light} />
      <path d="M7 14 Q3 10 4 8" stroke={C.main} strokeWidth="2" fill="none" strokeLinecap="round" />
      <ellipse cx="17" cy="14" rx="9"   ry="6"   fill={C.main} />
      <circle  cx="24" cy="13" r="3.5"           fill={C.light} />
      <circle  cx="19" cy="19.5" r="2"           fill={C.light} />
      <circle  cx="26" cy="19.5" r="2"           fill={C.light} />
      <ellipse cx="28" cy="9"  rx="2.5" ry="4"   fill={C.main} />
      <circle  cx="31" cy="7"  r="5.5"           fill={C.main} />
      <ellipse cx="29" cy="11.5" rx="2" ry="3.5" fill={C.dark} transform="rotate(-10,29,11.5)" />
      <circle  cx="31" cy="2"  r="3.5"           fill={C.light} />
      <ellipse cx="35.5" cy="8"  rx="2" ry="1.5" fill={C.dark} />
      <ellipse cx="37"   cy="7.5" rx="1" ry="0.8" fill={C.nose} />
      {smile ? (
        <>
          <path d="M29.5 5.5 Q31 4 32.5 5.5" stroke={C.nose} strokeWidth="1.2" fill="none" strokeLinecap="round" />
          <path d="M33 8.5 Q35 11.5 37.5 8.5"  stroke={C.nose} strokeWidth="1"   fill="none" strokeLinecap="round" />
          <circle cx="33.5" cy="8" r="2" fill="rgba(255,120,80,0.22)" />
        </>
      ) : (
        <>
          <circle cx="31.5" cy="5.5" r="1.2" fill={C.nose} />
          <circle cx="32"   cy="5"   r="0.45" fill="rgba(255,255,255,0.75)" />
          <path d="M33.5 8 Q35 9 36.5 8" stroke={C.nose} strokeWidth="0.8" fill="none" strokeLinecap="round" />
        </>
      )}
    </svg>
  );
}

function SleepSVG() {
  return (
    <svg viewBox="0 -2 44 25" width="30" height="17">
      <ellipse cx="18" cy="15" rx="13" ry="5"   fill={C.main} />
      <circle  cx="32" cy="12" r="5.5"          fill={C.main} />
      <ellipse cx="30" cy="17" rx="2" ry="3.5"  fill={C.dark} transform="rotate(20,30,17)" />
      <circle  cx="33" cy="7"  r="3"            fill={C.light} />
      <circle  cx="5"  cy="12" r="3"            fill={C.light} />
      <ellipse cx="37" cy="13" rx="2" ry="1.5"  fill={C.dark} />
      <ellipse cx="38.5" cy="12.5" rx="1" ry="0.8" fill={C.nose} />
      {/* closed eyes */}
      <path d="M30 11 Q32 12 34 11" stroke={C.nose} strokeWidth="1.2" fill="none" strokeLinecap="round" />
      {/* Zzz — mint tint to match the app palette */}
      <text x="6"  y="9"   fontSize="5.5" fill="#22d3ee" fontFamily="monospace" opacity="0.9" fontWeight="bold">z</text>
      <text x="13" y="6"   fontSize="4"   fill="#22d3ee" fontFamily="monospace" opacity="0.65">z</text>
      <text x="18" y="3.5" fontSize="3"   fill="#22d3ee" fontFamily="monospace" opacity="0.4">z</text>
    </svg>
  );
}

function PlaySVG() {
  return (
    <svg viewBox="0 -5 46 34" width="30" height="22">
      {/* Ball */}
      <circle cx="40" cy="18" r="5.5" fill="#e63946" />
      <circle cx="38.5" cy="16.5" r="1.8" fill="rgba(255,255,255,0.38)" />
      {/* Rear / tail */}
      <ellipse cx="9"  cy="9"  rx="6"   ry="4.5" fill={C.main} />
      <circle  cx="4"  cy="7"  r="3"             fill={C.light} />
      {/* Back leg */}
      <line x1="12" y1="13" x2="14" y2="20" stroke={C.dark} strokeWidth="2.5" strokeLinecap="round" />
      <circle cx="14" cy="20" r="2" fill={C.light} />
      {/* Front body low (play bow) */}
      <ellipse cx="22" cy="16" rx="9"  ry="5"   fill={C.main} />
      <circle  cx="28" cy="16" r="3.5"          fill={C.light} />
      {/* Front paws on ground */}
      <line x1="19" y1="20" x2="17" y2="25" stroke={C.dark} strokeWidth="2.5" strokeLinecap="round" />
      <line x1="23" y1="20" x2="26" y2="25" stroke={C.dark} strokeWidth="2.5" strokeLinecap="round" />
      <circle cx="17" cy="25" r="2" fill={C.light} />
      <circle cx="26" cy="25" r="2" fill={C.light} />
      {/* Neck craning toward ball */}
      <ellipse cx="32" cy="9" rx="3" ry="5.5" fill={C.main} transform="rotate(20,32,9)" />
      {/* Head alert */}
      <circle  cx="34" cy="5"  r="5.5"          fill={C.main} />
      <circle  cx="34" cy="0"  r="3.2"          fill={C.light} />
      <ellipse cx="31" cy="10" rx="2" ry="3.5"  fill={C.dark} transform="rotate(-20,31,10)" />
      <ellipse cx="38.5" cy="6.5" rx="2" ry="1.5" fill={C.dark} transform="rotate(15,38.5,6.5)" />
      <ellipse cx="40"   cy="6"   rx="1" ry="0.9" fill={C.nose} />
      {/* Alert eye */}
      <circle  cx="35.5" cy="4" r="1.3" fill={C.nose} />
      <circle  cx="36"   cy="3.5" r="0.5" fill="rgba(255,255,255,0.75)" />
    </svg>
  );
}

// ── State machine ──────────────────────────────────────────────────────────────

const IDLE_DUR: Record<string, number> = {
  sleeping: 4200,
  playing:  3200,
  smiling:  2200,
  sitting:  2600,
};

const IDLE_PICKS: Mode[] = ["sitting", "sleeping", "smiling", "playing"];

export function PoodleSprite() {
  const [mode, setMode] = useState<Mode>("running");

  useEffect(() => {
    if (mode !== "running") {
      const dur = IDLE_DUR[mode] ?? 2500;
      const t = window.setTimeout(() => setMode("running"), dur + Math.random() * 1000);
      return () => window.clearTimeout(t);
    }
    // Random idle while running (every 11-22 s)
    const delay = 11000 + Math.random() * 11000;
    const t = window.setTimeout(() => {
      setMode(IDLE_PICKS[Math.floor(Math.random() * IDLE_PICKS.length)]);
    }, delay);
    return () => window.clearTimeout(t);
  }, [mode]);

  return (
    <span className={`chat__poodle${mode === "running" ? " chat__poodle--run" : ""}`}>
      {mode === "running"  && <RunSVG />}
      {mode === "sitting"  && <SitSVG />}
      {mode === "sleeping" && <SleepSVG />}
      {mode === "smiling"  && <SitSVG smile />}
      {mode === "playing"  && <PlaySVG />}
    </span>
  );
}

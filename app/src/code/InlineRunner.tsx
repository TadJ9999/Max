// InlineRunner — the animated "runner on a track" shown ~2 lines below an inline
// AI invoke in the Code tab, in place of the old text status. The invoked model's
// logo glides left→right along a glowing track as % climbs, then gives a green
// "done" pulse and fades as the reply text drops in. Rendered into a Monaco
// content widget via a portal (see CodeView).

import { ACCENT, KIND_LABEL, ModelLogo, type LogoKind } from "./modelLogos";
import "./InlineRunner.css";

export type RunnerPhase = "running" | "done" | "error" | "leaving";

export interface RunnerState {
  phase: RunnerPhase;
  pct: number;
  kind: LogoKind;
  model?: string;
  message?: string;
}

export function InlineRunner({ state }: { state: RunnerState }) {
  const { phase, pct, kind, model, message } = state;
  const clamped = Math.max(0, Math.min(100, pct));
  const style = {
    "--accent": ACCENT[kind],
    "--pct": `${clamped}%`,
  } as React.CSSProperties;

  if (phase === "error") {
    return (
      <div className="ir is-error" style={style}>
        <span className="ir__err">⚠ {message || "inline error"}</span>
      </div>
    );
  }

  return (
    <div className={`ir is-${phase}`} style={style}>
      <span className="ir__label" style={{ color: ACCENT[kind] }}>
        {model || KIND_LABEL[kind]}
      </span>
      <div className="ir__track">
        <div className="ir__trail" />
        <div className="ir__runner">
          <span className="ir__spark" />
          <ModelLogo kind={kind} size={18} />
        </div>
      </div>
      <span className="ir__pct">{Math.round(clamped)}%</span>
    </div>
  );
}

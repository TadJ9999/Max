// Calibration curve — stated confidence (x) vs realised hit-fraction (y).
// The dashed diagonal is perfect calibration; points above = under-confident,
// below = over-confident. Dot size encodes sample count.

import type { OracleStats } from "./oracle";

interface Props {
  curve: OracleStats["calibrationCurve"];
  fit?: { x: number; y: number }[];
  size?: number;
}

export function CalibrationChart({ curve, fit, size = 200 }: Props) {
  const pad = 28;
  const W = size - pad * 2;
  const H = size - pad * 2;
  const toX = (v: number) => pad + v * W;
  const toY = (v: number) => pad + (1 - v) * H;

  const maxCount = Math.max(1, ...curve.map((p) => p.count));
  const fitPath =
    fit && fit.length > 1
      ? "M " + fit.map((p) => `${toX(p.x).toFixed(1)},${toY(p.y).toFixed(1)}`).join(" L ")
      : null;

  return (
    <svg width={size} height={size} className="ora-cal">
      {/* frame */}
      <rect x={pad} y={pad} width={W} height={H} className="ora-cal__frame" />
      {/* perfect-calibration diagonal */}
      <line x1={toX(0)} y1={toY(0)} x2={toX(1)} y2={toY(1)} className="ora-cal__diag" />
      {/* fitted isotonic map */}
      {fitPath && <path d={fitPath} className="ora-cal__fit" fill="none" />}
      {/* empirical points */}
      {curve.map((p, i) => (
        <circle
          key={i}
          cx={toX(p.confidence)}
          cy={toY(p.actual)}
          r={3 + (p.count / maxCount) * 5}
          className="ora-cal__pt"
        />
      ))}
      {/* axes labels */}
      <text x={pad} y={size - 8} className="ora-cal__lbl">0</text>
      <text x={size - pad} y={size - 8} textAnchor="end" className="ora-cal__lbl">conf 1.0</text>
      <text x={6} y={pad + 8} className="ora-cal__lbl">actual</text>
      {curve.length === 0 && (
        <text x="50%" y="50%" textAnchor="middle" className="ora-cal__empty">
          no graded data yet
        </text>
      )}
    </svg>
  );
}

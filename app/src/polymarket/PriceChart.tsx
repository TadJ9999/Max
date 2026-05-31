// SVG line chart for YES probability over time.
// Renders a smooth path with a gradient fill and axis labels.

import { useMemo } from "react";
import type { PricePoint } from "./polymarket";

interface Props {
  points: PricePoint[];
  width?: number;
  height?: number;
  mini?: boolean; // compact spark-line mode (no axes/labels)
}

export function PriceChart({ points, width = 320, height = 100, mini = false }: Props) {
  const path = useMemo(() => {
    if (points.length < 2) return null;
    const minP = Math.min(...points.map((p) => p.p));
    const maxP = Math.max(...points.map((p) => p.p));
    const rangeP = maxP - minP || 0.01;
    const minT = points[0].t;
    const maxT = points[points.length - 1].t;
    const rangeT = maxT - minT || 1;

    const pad = mini ? 2 : 10;
    const W = width - pad * 2;
    const H = height - pad * 2;

    const toX = (t: number) => pad + ((t - minT) / rangeT) * W;
    const toY = (p: number) => pad + (1 - (p - minP) / rangeP) * H;

    const pts = points.map((pt) => `${toX(pt.t).toFixed(1)},${toY(pt.p).toFixed(1)}`);
    const linePath = `M ${pts.join(" L ")}`;
    const firstX = toX(points[0].t).toFixed(1);
    const lastX = toX(points[points.length - 1].t).toFixed(1);
    const bottom = (pad + H).toFixed(1);
    const fillPath = `${linePath} L ${lastX},${bottom} L ${firstX},${bottom} Z`;

    return { linePath, fillPath, minP, maxP };
  }, [points, width, height, mini]);

  if (!path || points.length < 2) {
    return (
      <svg width={width} height={height} className="price-chart price-chart--empty">
        <text x="50%" y="50%" textAnchor="middle" fill="#4a5568" fontSize="11">
          No data
        </text>
      </svg>
    );
  }

  const lastPrice = points[points.length - 1].p;
  const firstPrice = points[0].p;
  const trending = lastPrice >= firstPrice;
  const lineColor = trending ? "#22c55e" : "#ef4444";
  const fillId = `poly-fill-${mini ? "mini" : "main"}`;

  return (
    <svg width={width} height={height} className={`price-chart${mini ? " price-chart--mini" : ""}`}>
      <defs>
        <linearGradient id={fillId} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={lineColor} stopOpacity="0.25" />
          <stop offset="100%" stopColor={lineColor} stopOpacity="0.02" />
        </linearGradient>
      </defs>
      <path d={path.fillPath} fill={`url(#${fillId})`} />
      <path d={path.linePath} stroke={lineColor} strokeWidth={mini ? 1.2 : 1.5} fill="none" strokeLinejoin="round" />
      {!mini && (
        <>
          <text x="6" y="14" fill="#8aa0b4" fontSize="9">
            {(path.maxP * 100).toFixed(0)}%
          </text>
          <text x="6" y={height - 4} fill="#8aa0b4" fontSize="9">
            {(path.minP * 100).toFixed(0)}%
          </text>
          <text x={width - 4} y={height - 4} fill="#8aa0b4" fontSize="9" textAnchor="end">
            {(lastPrice * 100).toFixed(1)}%
          </text>
        </>
      )}
    </svg>
  );
}

// Equirectangular world map: severity choropleth, animated country zoom,
// realistic top-down ship silhouettes, USGS/GDACS event markers, day/night terminator.

import { useEffect, useMemo, useRef, useState } from "react";
import { geoEquirectangular, geoGraticule10, geoPath } from "d3-geo";
import { feature } from "topojson-client";
import type { Topology } from "topojson-specification";
import type { Feature, FeatureCollection, Geometry } from "geojson";
import worldData from "world-atlas/countries-110m.json";
import { isoForFeatureId, severityColor, severityTier } from "./countries";
import { nightRing, subsolarPoint } from "./terminator";
import type { CountryStat, GeoEvent, ShipPosition } from "./osint";

const W = 960;
const H = 480;

const world = worldData as unknown as Topology;
const land = feature(
  world,
  world.objects.countries,
) as unknown as FeatureCollection<Geometry, { name: string }>;

// ── Ship silhouettes (top-down, bow pointing up, centered at 0,0) ──────────
//
// Aircraft carrier (CVN – Nimitz / Ford class)
// Defining features: very elongated, angled flight deck on PORT side (left),
// island superstructure bump on STARBOARD side (right), pointed bow.
const CARRIER_D =
  "M1,-14 L5,-11 L5.5,0 L9.5,0 L9.5,7.5 L5.5,7.5 " +
  "L4,13 L-4,13 L-4.5,4 L-10.5,-0.5 L-7.5,-10.5 L-2.5,-13 Z";

// Amphibious assault ship (LHD/LHA – Wasp / America class)
// Defining features: shorter / wider, NO angled deck (symmetric), island on
// starboard, rounded bow — clearly different silhouette from a carrier.
const AMPHIB_D =
  "M0,-11 L4,-9.5 L5.5,-5 L5.5,-1 L8.5,-1 L8.5,5 " +
  "L5.5,5 L5,10 L-5,10 L-5.5,-5 L-4,-9.5 Z";

// ── types ───────────────────────────────────────────────────────────────────
type VB = { x: number; y: number; w: number; h: number };
const WORLD_VB: VB = { x: 0, y: 0, w: W, h: H };

type Props = {
  countries: CountryStat[];
  selectedIso: string | null;
  activeSeverities: Set<number>;
  ships: ShipPosition[];
  showFleet: boolean;
  geoEvents: GeoEvent[];
  showEvents: boolean;
  onSelect: (iso: string, name: string) => void;
};

type Hover = { name: string; severity: number; articles: number; lit: boolean; x: number; y: number };
type ShipHover = { ship: ShipPosition; x: number; y: number };
type EventHover = { event: GeoEvent; x: number; y: number };

function easeOutCubic(t: number) {
  return 1 - (1 - t) ** 3;
}

function ringToPath(
  ring: [number, number][],
  project: (p: [number, number]) => [number, number] | null,
  close: boolean,
): string {
  let d = "";
  for (const pt of ring) {
    const p = project(pt);
    if (!p) continue;
    d += (d ? "L" : "M") + p[0].toFixed(1) + " " + p[1].toFixed(1);
  }
  return d && close ? d + "Z" : d;
}

function quakeRadius(mag: number) {
  return Math.max(3, Math.min(10, (mag - 4.0) * 2.2));
}

export function WorldMap({
  countries, selectedIso, activeSeverities,
  ships, showFleet,
  geoEvents, showEvents,
  onSelect,
}: Props) {
  const [hover, setHover] = useState<Hover | null>(null);
  const [shipHover, setShipHover] = useState<ShipHover | null>(null);
  const [eventHover, setEventHover] = useState<EventHover | null>(null);
  const [tick, setTick] = useState(0);

  // ── viewBox zoom state ────────────────────────────────────────────────────
  // Uses setInterval (not rAF) so animation runs even in headless/iframe contexts
  // where requestAnimationFrame is throttled.
  const vbRef  = useRef<VB>(WORLD_VB);
  const [vb, _setVb] = useState<VB>(WORLD_VB);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  function animateTo(target: VB) {
    if (timerRef.current) clearInterval(timerRef.current);
    const from = { ...vbRef.current };
    const t0 = Date.now();
    const dur = 650;
    timerRef.current = setInterval(() => {
      const p = Math.min(1, (Date.now() - t0) / dur);
      const e = easeOutCubic(p);
      const next: VB = {
        x: from.x + (target.x - from.x) * e,
        y: from.y + (target.y - from.y) * e,
        w: from.w + (target.w - from.w) * e,
        h: from.h + (target.h - from.h) * e,
      };
      vbRef.current = next;
      _setVb({ ...next });
      if (p >= 1) { clearInterval(timerRef.current!); timerRef.current = null; }
    }, 16);
  }

  const projection = useMemo(
    () => geoEquirectangular().fitSize([W, H], { type: "Sphere" }),
    [],
  );
  const path = useMemo(() => geoPath(projection), [projection]);
  const project = useMemo(
    () => (p: [number, number]) => projection(p) ?? null,
    [projection],
  );
  const graticule = useMemo(() => path(geoGraticule10()) ?? undefined, [path]);

  // Zoom to selected country; zoom out when deselected.
  useEffect(() => {
    if (!selectedIso) {
      animateTo(WORLD_VB);
      return;
    }
    const feat = land.features.find(
      (f) => isoForFeatureId(f.id as string | number | undefined) === selectedIso,
    ) as Feature | undefined;
    if (!feat) { animateTo(WORLD_VB); return; }

    const [[x0, y0], [x1, y1]] = path.bounds(feat as Parameters<typeof path.bounds>[0]);
    const bw = x1 - x0, bh = y1 - y0;
    // Pad 35 % on each side, maintain 2:1 aspect, enforce minimum zoom level.
    const padX = Math.max(bw * 0.35, 20), padY = Math.max(bh * 0.35, 10);
    let tw = bw + padX * 2, th = bh + padY * 2;
    const aspect = W / H;
    if (tw / th > aspect) { th = tw / aspect; } else { tw = th * aspect; }
    // Cap at 80 % of the world view so large countries still have context.
    tw = Math.max(tw, W / 6); th = tw / aspect;
    const cx = (x0 + x1) / 2, cy = (y0 + y1) / 2;
    animateTo({ x: cx - tw / 2, y: cy - th / 2, w: tw, h: th });
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedIso]);

  // Cleanup zoom timer on unmount.
  useEffect(() => () => { if (timerRef.current) clearInterval(timerRef.current); }, []);

  // Terminator ticks every minute.
  useEffect(() => {
    const id = window.setInterval(() => setTick((t) => t + 1), 60_000);
    return () => window.clearInterval(id);
  }, []);

  const byIso = useMemo(() => {
    const m = new Map<string, CountryStat>();
    for (const c of countries) m.set(c.iso, c);
    return m;
  }, [countries]);

  const night = useMemo(() => {
    const now = new Date();
    const ring = nightRing(now);
    const curve = ring.slice(0, ring.length - 2);
    const sun = subsolarPoint(now);
    return {
      fill: ringToPath(ring, project, true),
      line: ringToPath(curve, project, false),
      sun: project([sun.lon, sun.lat]),
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [project, tick]);

  const viewBoxStr = `${vb.x.toFixed(1)} ${vb.y.toFixed(1)} ${vb.w.toFixed(1)} ${vb.h.toFixed(1)}`;

  return (
    <div className="osint-map-wrap">
      <svg
        className="osint-map"
        viewBox={viewBoxStr}
        role="img"
        aria-label="World threat intelligence map"
      >
        <defs>
          <radialGradient id="osint-ocean" cx="50%" cy="42%" r="75%">
            <stop offset="0%" stopColor="#091722" />
            <stop offset="100%" stopColor="#03080d" />
          </radialGradient>
          <style>{`
            @keyframes osint-pulse {
              0%   { r: 9; opacity: 0.6; }
              80%  { r: 17; opacity: 0; }
              100% { r: 17; opacity: 0; }
            }
            .osint-ship-pulse { animation: osint-pulse 2.6s ease-out infinite; }
          `}</style>
        </defs>

        <path d={path({ type: "Sphere" }) ?? undefined} className="osint-map__sphere" />
        <path d={graticule} className="osint-map__graticule" />

        {/* Country choropleth */}
        <g className="osint-map__countries">
          {land.features.map((f, i) => {
            const iso = isoForFeatureId(f.id as string | number | undefined);
            const stat = iso ? byIso.get(iso) : undefined;
            const lit = !!stat && activeSeverities.has(stat.severity);
            const selected = !!iso && iso === selectedIso;
            const d = path(f);
            if (!d) return null;
            const color = lit ? severityColor(stat!.severity) : undefined;
            return (
              <path
                key={(iso ?? f.properties?.name ?? i) as string}
                d={d}
                className={`osint-country${lit ? " is-hot" : ""}${selected ? " is-selected" : ""}`}
                style={color ? { fill: color, color } : undefined}
                onMouseMove={(e) =>
                  setHover({
                    name: stat?.name ?? f.properties?.name ?? "—",
                    severity: stat?.severity ?? 0,
                    articles: stat?.articleCount ?? 0,
                    lit,
                    x: e.nativeEvent.offsetX,
                    y: e.nativeEvent.offsetY,
                  })
                }
                onMouseLeave={() => setHover(null)}
                onClick={() => lit && iso && onSelect(iso, stat!.name)}
              />
            );
          })}
        </g>

        {/* Night / terminator */}
        <path d={night.fill} className="osint-map__night" />
        <path d={night.line} className="osint-map__terminator" />
        {night.sun && (
          <circle cx={night.sun[0]} cy={night.sun[1]} r={5} className="osint-map__sun" />
        )}

        {/* Geo events (earthquakes, disasters) */}
        {showEvents && (
          <g className="osint-map__events">
            {geoEvents.map((ev) => {
              const p = project([ev.lon, ev.lat]);
              if (!p) return null;
              const [x, y] = p;
              const r = ev.category === "earthquake" ? quakeRadius(ev.magnitude) : 5;
              return (
                <g key={ev.id} className="osint-event"
                  onMouseMove={(e) => setEventHover({ event: ev, x: e.nativeEvent.offsetX, y: e.nativeEvent.offsetY })}
                  onMouseLeave={() => setEventHover(null)}
                  onClick={() => ev.url && window.open(ev.url, "_blank", "noopener")}
                >
                  <circle cx={x} cy={y} r={r + 5} fill={ev.color} opacity={0.1} />
                  <circle cx={x} cy={y} r={r} fill={ev.color} opacity={0.72}
                    stroke={ev.color} strokeWidth={0.7}
                    style={{ filter: `drop-shadow(0 0 3px ${ev.color})` }}
                  />
                </g>
              );
            })}
          </g>
        )}

        {/* Fleet markers */}
        {showFleet && (
          <g className="osint-map__fleet">
            {ships.map((s) => {
              const p = project([s.lon, s.lat]);
              if (!p) return null;
              const [x, y] = p;
              const inPort = s.status === "in port";
              const isCarrier = s.kind === "carrier";
              return (
                <g key={s.hull}
                  className={`osint-ship osint-ship--${s.kind}${inPort ? " is-port" : ""}`}
                  transform={`translate(${x},${y}) scale(0.68)`}
                  onMouseMove={(e) => setShipHover({ ship: s, x: e.nativeEvent.offsetX, y: e.nativeEvent.offsetY })}
                  onMouseLeave={() => setShipHover(null)}
                  onClick={() => s.url && window.open(s.url, "_blank", "noopener")}
                >
                  {!inPort && (
                    <circle cx={0} cy={0} r={9} fill="none" stroke="currentColor"
                      strokeWidth={1} className="osint-ship-pulse" />
                  )}
                  <circle cx={0} cy={0} r={13} className="osint-ship__halo" />
                  <path d={isCarrier ? CARRIER_D : AMPHIB_D} className="osint-ship__mark" />
                </g>
              );
            })}
          </g>
        )}
      </svg>

      {/* Tooltips */}
      {hover && !shipHover && !eventHover && (
        <div className="osint-tip" style={{ left: hover.x + 14, top: hover.y + 10 }}>
          <span className="osint-tip__name">{hover.name}</span>
          {hover.lit && hover.articles > 0 ? (
            <span className="osint-tip__meta" style={{ color: severityColor(hover.severity) }}>
              {severityTier(hover.severity).label} · {hover.articles} articles
            </span>
          ) : (
            <span className="osint-tip__meta osint-tip__meta--quiet">no signal in filter</span>
          )}
        </div>
      )}

      {shipHover && (
        <div className="osint-tip osint-tip--ship"
          style={{ left: shipHover.x + 14, top: shipHover.y + 10 }}>
          <span className="osint-tip__name">
            {shipHover.ship.kind === "carrier" ? "✈" : "⚓"} {shipHover.ship.name}
            <span className="osint-tip__hull"> {shipHover.ship.hull}</span>
          </span>
          <span className="osint-tip__meta">{shipHover.ship.region} · {shipHover.ship.status}</span>
          <span className="osint-tip__meta osint-tip__meta--quiet">
            {shipHover.ship.source}{shipHover.ship.asOf ? ` · ${shipHover.ship.asOf}` : ""} · est.
          </span>
        </div>
      )}

      {eventHover && (
        <div className="osint-tip"
          style={{ left: eventHover.x + 14, top: eventHover.y + 10,
            borderColor: eventHover.event.color + "88" }}>
          <span className="osint-tip__name">{eventHover.event.title}</span>
          <span className="osint-tip__meta" style={{ color: eventHover.event.color }}>
            {eventHover.event.category}
            {eventHover.event.magnitude > 0 ? ` · M${eventHover.event.magnitude.toFixed(1)}` : ""}
          </span>
          <span className="osint-tip__meta osint-tip__meta--quiet">{eventHover.event.source}</span>
        </div>
      )}
    </div>
  );
}

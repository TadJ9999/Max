/// <reference lib="webworker" />
// SGP4 propagation worker — runs satellite.js off the main thread.
// Propagates every loaded satellite to a given time and returns scene-space XYZ
// positions; computes the orbit track + overhead passes for a selected sat.
import * as satellite from "satellite.js";

const EARTH_R_KM = 6371; // 1 scene unit = 1 Earth radius

interface SatInput { name: string; norad_id: string; line1: string; line2: string; }

let satrecs: (satellite.SatRec | null)[] = [];

// Geodetic (radians, km alt) -> scene coords. MUST match earthUtils.geoToVec3.
function geoToScene(latRad: number, lonRad: number, heightKm: number): [number, number, number] {
  const r = 1 + heightKm / EARTH_R_KM;
  return [
    r * Math.cos(latRad) * Math.cos(lonRad),
    r * Math.sin(latRad),
    -r * Math.cos(latRad) * Math.sin(lonRad),
  ];
}

function propagate(rec: satellite.SatRec, date: Date) {
  try {
    const pv = satellite.propagate(rec, date);
    if (!pv || !pv.position || typeof pv.position === "boolean") return null;
    const gmst = satellite.gstime(date);
    const geo = satellite.eciToGeodetic(pv.position, gmst);
    return { lat: geo.latitude, lon: geo.longitude, alt: geo.height, eci: pv.position, gmst };
  } catch {
    return null;
  }
}

self.onmessage = (e: MessageEvent) => {
  const msg = e.data;

  if (msg.type === "load") {
    const sats: SatInput[] = msg.satellites || [];
    satrecs = sats.map((s) => {
      try { return satellite.twoline2satrec(s.line1, s.line2); } catch { return null; }
    });
    (self as DedicatedWorkerGlobalScope).postMessage({ type: "loaded", count: satrecs.length });
    return;
  }

  if (msg.type === "positions") {
    const date = new Date(msg.timeMs);
    const n = satrecs.length;
    const positions = new Float32Array(n * 3);
    const valid = new Uint8Array(n);
    const altKm = new Float32Array(n);
    for (let i = 0; i < n; i++) {
      const rec = satrecs[i];
      if (!rec) continue;
      const p = propagate(rec, date);
      if (!p || !isFinite(p.lat) || !isFinite(p.lon)) continue;
      const [x, y, z] = geoToScene(p.lat, p.lon, p.alt);
      positions[i * 3] = x; positions[i * 3 + 1] = y; positions[i * 3 + 2] = z;
      altKm[i] = p.alt;
      valid[i] = 1;
    }
    (self as DedicatedWorkerGlobalScope).postMessage(
      { type: "positions", timeMs: msg.timeMs, positions, valid, altKm, count: n },
      [positions.buffer, valid.buffer, altKm.buffer],
    );
    return;
  }

  if (msg.type === "orbit") {
    const idx: number = msg.index;
    const rec = satrecs[idx];
    if (!rec) { (self as DedicatedWorkerGlobalScope).postMessage({ type: "orbit", index: idx, points: new Float32Array(0) }); return; }
    const periodMin = rec.no ? (2 * Math.PI) / rec.no : 95; // mean motion rad/min
    const steps = 180;
    const stepMs = (periodMin * 60 * 1000) / steps;
    const points = new Float32Array((steps + 1) * 3);
    let w = 0;
    for (let s = 0; s <= steps; s++) {
      const p = propagate(rec, new Date(msg.timeMs + s * stepMs));
      if (!p) continue;
      const [x, y, z] = geoToScene(p.lat, p.lon, p.alt);
      points[w++] = x; points[w++] = y; points[w++] = z;
    }
    const copy = new Float32Array(points.subarray(0, w));
    (self as DedicatedWorkerGlobalScope).postMessage({ type: "orbit", index: idx, points: copy }, [copy.buffer]);
    return;
  }

  if (msg.type === "passes") {
    const idx: number = msg.index;
    const rec = satrecs[idx];
    const observer = {
      longitude: satellite.degreesToRadians(msg.lon),
      latitude: satellite.degreesToRadians(msg.lat),
      height: 0.05,
    };
    const passes: { start: number; end: number; maxEl: number }[] = [];
    if (rec) {
      const stepMin = 0.5, horizon = 10;
      let cur: { start: number; end: number; maxEl: number } | null = null;
      for (let m = 0; m <= 48 * 60; m += stepMin) {
        const date = new Date(msg.timeMs + m * 60000);
        const pv = satellite.propagate(rec, date);
        if (!pv || !pv.position || typeof pv.position === "boolean") continue;
        const gmst = satellite.gstime(date);
        const ecf = satellite.eciToEcf(pv.position, gmst);
        const look = satellite.ecfToLookAngles(observer, ecf);
        const el = (look.elevation * 180) / Math.PI;
        if (el >= horizon && !cur) cur = { start: date.getTime(), end: 0, maxEl: el };
        else if (cur) {
          if (el > cur.maxEl) cur.maxEl = el;
          if (el < horizon) { cur.end = date.getTime(); cur.maxEl = Math.round(cur.maxEl); passes.push(cur); cur = null; if (passes.length >= 6) break; }
        }
      }
    }
    (self as DedicatedWorkerGlobalScope).postMessage({ type: "passes", index: idx, passes });
    return;
  }
};

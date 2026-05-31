// Three.js helpers for the neon-hologram Earth: coordinate mapping, glowing
// coastlines (world-atlas topojson), lat/lon graticule, atmosphere Fresnel
// shell, satellite glow sprite, and the subsolar point for the aurora.
import * as THREE from "three";

export const MINT = 0x00ffc8;
export const CYAN = 0x22d3ee;
export const BLUE = 0x5b8cff;
export const VIOLET = 0xb56bff;

// Geodetic degrees -> scene coords (1 unit = Earth radius). Matches satelliteWorker.
export function geoToVec3(lonDeg: number, latDeg: number, r = 1): THREE.Vector3 {
  const lon = (lonDeg * Math.PI) / 180;
  const lat = (latDeg * Math.PI) / 180;
  return new THREE.Vector3(
    r * Math.cos(lat) * Math.cos(lon),
    r * Math.sin(lat),
    -r * Math.cos(lat) * Math.sin(lon),
  );
}

// Soft radial-glow sprite for satellite points.
export function makeGlowTexture(): THREE.Texture {
  const s = 64;
  const c = document.createElement("canvas");
  c.width = c.height = s;
  const ctx = c.getContext("2d")!;
  const g = ctx.createRadialGradient(s / 2, s / 2, 0, s / 2, s / 2, s / 2);
  g.addColorStop(0, "rgba(255,255,255,1)");
  g.addColorStop(0.25, "rgba(180,255,235,0.9)");
  g.addColorStop(0.6, "rgba(0,255,200,0.25)");
  g.addColorStop(1, "rgba(0,255,200,0)");
  ctx.fillStyle = g;
  ctx.fillRect(0, 0, s, s);
  const tex = new THREE.CanvasTexture(c);
  tex.needsUpdate = true;
  return tex;
}

export function altColor(altKm: number): THREE.Color {
  const mint = new THREE.Color(MINT);
  const blue = new THREE.Color(BLUE);
  const violet = new THREE.Color(VIOLET);
  if (altKm < 2000) return mint.clone().lerp(blue, (altKm / 2000) * 0.5);
  if (altKm < 20000) return blue.clone();
  return blue.clone().lerp(violet, Math.min(1, (altKm - 20000) / 16000));
}

// Lat/lon graticule as additive line segments.
export function buildGraticule(r = 1.002): THREE.LineSegments {
  const pts: number[] = [];
  const push = (a: THREE.Vector3, b: THREE.Vector3) => pts.push(a.x, a.y, a.z, b.x, b.y, b.z);
  for (let lat = -75; lat <= 75; lat += 15) {
    for (let lon = -180; lon < 180; lon += 5) push(geoToVec3(lon, lat, r), geoToVec3(lon + 5, lat, r));
  }
  for (let lon = -180; lon < 180; lon += 15) {
    for (let lat = -90; lat < 90; lat += 5) push(geoToVec3(lon, lat, r), geoToVec3(lon, lat + 5, r));
  }
  const geo = new THREE.BufferGeometry();
  geo.setAttribute("position", new THREE.Float32BufferAttribute(pts, 3));
  const mat = new THREE.LineBasicMaterial({ color: 0x1f6f63, transparent: true, opacity: 0.4 });
  return new THREE.LineSegments(geo, mat);
}

// Glowing coastlines from world-atlas land topojson (best-effort, async).
export async function buildCoastlines(r = 1.004): Promise<THREE.LineSegments | null> {
  try {
    const [{ feature }, topo] = await Promise.all([
      import("topojson-client"),
      import("world-atlas/land-110m.json"),
    ]);
    const data = (topo as { default?: unknown }).default ?? topo;
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const land = feature(data as any, (data as any).objects.land) as any;
    const segs: number[] = [];
    const addRing = (ring: number[][]) => {
      for (let i = 0; i < ring.length - 1; i++) {
        const a = geoToVec3(ring[i][0], ring[i][1], r);
        const b = geoToVec3(ring[i + 1][0], ring[i + 1][1], r);
        segs.push(a.x, a.y, a.z, b.x, b.y, b.z);
      }
    };
    const handle = (geom: { type: string; coordinates: number[][][] | number[][][][] }) => {
      if (geom.type === "Polygon") (geom.coordinates as number[][][]).forEach(addRing);
      else if (geom.type === "MultiPolygon") (geom.coordinates as number[][][][]).forEach((poly) => poly.forEach(addRing));
    };
    if (land.type === "FeatureCollection") land.features.forEach((f: { geometry: { type: string; coordinates: number[][][] | number[][][][] } }) => handle(f.geometry));
    else handle(land.geometry);

    const geo = new THREE.BufferGeometry();
    geo.setAttribute("position", new THREE.Float32BufferAttribute(segs, 3));
    const mat = new THREE.LineBasicMaterial({ color: CYAN, transparent: true, opacity: 0.55, blending: THREE.AdditiveBlending });
    return new THREE.LineSegments(geo, mat);
  } catch {
    return null;
  }
}

const ATMO_VERT = `
  varying vec3 vNormal;
  void main() {
    vNormal = normalize(normalMatrix * normal);
    gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
  }`;
const ATMO_FRAG = `
  varying vec3 vNormal;
  void main() {
    float intensity = pow(0.62 - dot(vNormal, vec3(0.0, 0.0, 1.0)), 3.0);
    gl_FragColor = vec4(0.0, 1.0, 0.78, 1.0) * intensity;
  }`;

export function buildAtmosphere(): THREE.Mesh {
  const mat = new THREE.ShaderMaterial({
    vertexShader: ATMO_VERT,
    fragmentShader: ATMO_FRAG,
    blending: THREE.AdditiveBlending,
    side: THREE.BackSide,
    transparent: true,
  });
  const mesh = new THREE.Mesh(new THREE.SphereGeometry(1, 64, 64), mat);
  mesh.scale.setScalar(1.18);
  return mesh;
}

// Dark inner globe + faint wire shell.
export function buildGlobeBody(): THREE.Group {
  const g = new THREE.Group();
  const inner = new THREE.Mesh(
    new THREE.SphereGeometry(0.999, 64, 64),
    new THREE.MeshBasicMaterial({ color: 0x04161a, transparent: true, opacity: 0.92 }),
  );
  const wire = new THREE.Mesh(
    new THREE.SphereGeometry(1.0, 36, 24),
    new THREE.MeshBasicMaterial({ color: 0x0b3b38, wireframe: true, transparent: true, opacity: 0.22 }),
  );
  g.add(inner, wire);
  return g;
}

// Subsolar point (deg) for "sun" direction / aurora — low-precision but fine.
export function subsolarPoint(date: Date): { lat: number; lon: number } {
  const start = Date.UTC(date.getUTCFullYear(), 0, 0);
  const dayMs = 86400000;
  const dayOfYear = Math.floor((date.getTime() - start) / dayMs);
  const decl = -23.44 * Math.cos((2 * Math.PI / 365) * (dayOfYear + 10));
  const secUTC = date.getUTCHours() * 3600 + date.getUTCMinutes() * 60 + date.getUTCSeconds();
  let lon = 180 - (secUTC / 86400) * 360;
  if (lon > 180) lon -= 360;
  if (lon < -180) lon += 360;
  return { lat: decl, lon };
}

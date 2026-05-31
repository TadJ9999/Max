// Heliocentric planet positions (Standish low-precision Keplerian elements,
// valid ~1800-2050) and a Kepler solver to place / draw NEO orbits from JPL
// SBDB elements. All positions are in AU, ecliptic-J2000 frame.
// No external data, no network — coefficients are hardcoded.
import type { OrbitElements } from "./sentinel";

const DEG = Math.PI / 180;

export interface Vec3 { x: number; y: number; z: number; }

// name: [a, e, I, L, longPeri(ϖ), longNode(Ω)] and their per-century rates.
type Row = [number, number, number, number, number, number];
interface Planet { name: string; color: number; el: Row; rate: Row; }

export const PLANETS: Planet[] = [
  { name: "Mercury", color: 0xb0a08c, el: [0.38709927, 0.20563593, 7.00497902, 252.25032350, 77.45779628, 48.33076593], rate: [0.00000037, 0.00001906, -0.00594749, 149472.67411175, 0.16047689, -0.12534081] },
  { name: "Venus", color: 0xe0c98a, el: [0.72333566, 0.00677672, 3.39467605, 181.97909950, 131.60246718, 76.67984255], rate: [0.00000390, -0.00004107, -0.00078890, 58517.81538729, 0.00268329, -0.27769418] },
  { name: "Earth", color: 0x4aa3ff, el: [1.00000261, 0.01671123, -0.00001531, 100.46457166, 102.93768193, 0.0], rate: [0.00000562, -0.00004392, -0.01294668, 35999.37244981, 0.32327364, 0.0] },
  { name: "Mars", color: 0xff6b4a, el: [1.52371034, 0.09339410, 1.84969142, -4.55343205, -23.94362959, 49.55953891], rate: [0.00001847, 0.00007882, -0.00813131, 19140.30268499, 0.44441088, -0.29257343] },
  { name: "Jupiter", color: 0xd9a066, el: [5.20288700, 0.04838624, 1.30439695, 34.39644051, 14.72847983, 100.47390909], rate: [-0.00011607, -0.00013253, -0.00183714, 3034.74612775, 0.21252668, 0.20469106] },
  { name: "Saturn", color: 0xead6a6, el: [9.53667594, 0.05386179, 2.48599187, 49.95424423, 92.59887831, 113.66242448], rate: [-0.00125060, -0.00050991, 0.00193609, 1222.49362201, -0.41897216, -0.28867794] },
  { name: "Uranus", color: 0x9fe0e6, el: [19.18916464, 0.04725744, 0.77263783, 313.23810451, 170.95427630, 74.01692503], rate: [-0.00196176, -0.00004397, -0.00242939, 428.48202785, 0.40805281, 0.04240589] },
  { name: "Neptune", color: 0x5b8cff, el: [30.06992276, 0.00859048, 1.77004347, -55.12002969, 44.96476227, 131.78422574], rate: [0.00026291, 0.00005105, 0.00035372, 218.45945325, -0.32241464, -0.00508664] },
];

export function dateToJD(date: Date): number {
  return date.getTime() / 86400000 + 2440587.5;
}

function solveKepler(Mrad: number, e: number): number {
  let E = Mrad;
  for (let i = 0; i < 8; i++) {
    const dE = (E - e * Math.sin(E) - Mrad) / (1 - e * Math.cos(E));
    E -= dE;
    if (Math.abs(dE) < 1e-7) break;
  }
  return E;
}

// Orbital elements (deg/AU) -> ecliptic position. argPeri ω, node Ω, M all deg.
function elementsToVec3(a: number, e: number, Ideg: number, omegaDeg: number, OmegaDeg: number, Mdeg: number): Vec3 {
  const I = Ideg * DEG, w = omegaDeg * DEG, O = OmegaDeg * DEG;
  let M = ((Mdeg % 360) + 540) % 360 - 180; // -180..180
  M *= DEG;
  const E = solveKepler(M, e);
  const xp = a * (Math.cos(E) - e);
  const yp = a * Math.sqrt(1 - e * e) * Math.sin(E);
  const cw = Math.cos(w), sw = Math.sin(w);
  const cO = Math.cos(O), sO = Math.sin(O);
  const cI = Math.cos(I), sI = Math.sin(I);
  return {
    x: (cw * cO - sw * sO * cI) * xp + (-sw * cO - cw * sO * cI) * yp,
    y: (cw * sO + sw * cO * cI) * xp + (-sw * sO + cw * cO * cI) * yp,
    z: (sw * sI) * xp + (cw * sI) * yp,
  };
}

function planetElements(p: Planet, T: number) {
  const a = p.el[0] + p.rate[0] * T;
  const e = p.el[1] + p.rate[1] * T;
  const I = p.el[2] + p.rate[2] * T;
  const L = p.el[3] + p.rate[3] * T;
  const peri = p.el[4] + p.rate[4] * T;
  const node = p.el[5] + p.rate[5] * T;
  return { a, e, I, omega: peri - node, node, M: L - peri };
}

export function planetPosition(p: Planet, jd: number): Vec3 {
  const T = (jd - 2451545.0) / 36525;
  const el = planetElements(p, T);
  return elementsToVec3(el.a, el.e, el.I, el.omega, el.node, el.M);
}

export function planetOrbitPoints(p: Planet, jd: number, steps = 128): Vec3[] {
  const T = (jd - 2451545.0) / 36525;
  const el = planetElements(p, T);
  const out: Vec3[] = [];
  for (let i = 0; i <= steps; i++) out.push(elementsToVec3(el.a, el.e, el.I, el.omega, el.node, (i / steps) * 360));
  return out;
}

// NEO from SBDB elements at a given date (a AU, e, i/om/w deg, ma deg @ epoch JD).
export function neoPosition(o: OrbitElements, jd: number): Vec3 | null {
  if (o.a == null || o.e == null || o.i == null || o.om == null || o.w == null || o.ma == null || o.epoch == null) return null;
  const n = 0.9856076686 / Math.pow(Math.abs(o.a), 1.5); // deg/day
  const M = o.ma + n * (jd - o.epoch);
  return elementsToVec3(o.a, o.e, o.i, o.w, o.om, M);
}

export function neoOrbitPoints(o: OrbitElements, steps = 128): Vec3[] | null {
  if (o.a == null || o.e == null || o.i == null || o.om == null || o.w == null) return null;
  const out: Vec3[] = [];
  for (let i = 0; i <= steps; i++) out.push(elementsToVec3(o.a, o.e, o.i, o.w, o.om, (i / steps) * 360));
  return out;
}

// Distance compression so inner + outer planets are all visible on screen.
export function compress(au: number): number {
  return Math.log10(1 + au) * 3.2;
}

// AU ecliptic -> three.js scene (ecliptic = XZ plane, +Y up), distance-compressed.
export function toScene(v: Vec3): [number, number, number] {
  const au = Math.sqrt(v.x * v.x + v.y * v.y + v.z * v.z);
  const f = au > 0 ? compress(au) / au : 0;
  return [v.x * f, v.z * f, v.y * f];
}

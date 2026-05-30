// Day/night terminator — pure astronomy, no dependencies.
//
// Computes the subsolar point (where the sun is directly overhead) from a UTC
// instant, then the great-circle that divides day from night. Returns the night
// hemisphere as a lon/lat ring the map can project and fill. Accurate to a
// fraction of a degree — plenty for a moving shadow on a world map.

const RAD = Math.PI / 180;

function daysSinceJ2000(date: Date): number {
  const jd = date.getTime() / 86400000 + 2440587.5;
  return jd - 2451545.0;
}

function sunEclipticLongitude(d: number): number {
  const M = (357.5291 + 0.98560028 * d) * RAD; // mean anomaly
  const C =
    (1.9148 * Math.sin(M) + 0.02 * Math.sin(2 * M) + 0.0003 * Math.sin(3 * M)) * RAD; // equation of center
  const P = 102.9372 * RAD; // perihelion of Earth
  return M + C + P + Math.PI; // ecliptic longitude (rad)
}

export type SubSolar = { lon: number; lat: number };

/** Geographic point the sun is directly above, for `date` (default: now). */
export function subsolarPoint(date: Date = new Date()): SubSolar {
  const d = daysSinceJ2000(date);
  const e = 23.4397 * RAD; // obliquity
  const L = sunEclipticLongitude(d);

  const decl = Math.asin(Math.sin(e) * Math.sin(L)); // declination (rad)
  const ra = Math.atan2(Math.cos(e) * Math.sin(L), Math.cos(L)); // right ascension (rad)
  const gmstHours = (18.697374558 + 24.06570982441908 * d) % 24; // Greenwich mean sidereal time

  let lon = ra / RAD - gmstHours * 15;
  lon = (((lon + 180) % 360) + 360) % 360 - 180; // wrap to [-180, 180)
  return { lon, lat: decl / RAD };
}

/**
 * The night-side polygon as a closed lon/lat ring. Walks the terminator across
 * all longitudes, then closes along whichever pole is currently in darkness.
 * Step is in degrees of longitude (smaller = smoother).
 */
export function nightRing(date: Date = new Date(), stepDeg = 2): [number, number][] {
  const sun = subsolarPoint(date);
  // Clamp declination away from 0 so tan() doesn't blow up at the equinox.
  const declRad = (Math.abs(sun.lat) < 0.001 ? 0.001 * Math.sign(sun.lat || 1) : sun.lat) * RAD;

  const ring: [number, number][] = [];
  for (let lon = -180; lon <= 180; lon += stepDeg) {
    const hourAngle = (lon - sun.lon) * RAD;
    const lat = Math.atan(-Math.cos(hourAngle) / Math.tan(declRad)) / RAD;
    ring.push([lon, lat]);
  }
  // Dark pole: opposite hemisphere to the sun's declination.
  const darkPole = sun.lat >= 0 ? -90 : 90;
  ring.push([180, darkPole], [-180, darkPole]);
  return ring;
}

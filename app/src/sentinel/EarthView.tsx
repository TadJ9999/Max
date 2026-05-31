import { useEffect, useMemo, useRef, useState } from "react";
import * as THREE from "three";
import { useThreeScene, type ThreeHandles } from "./useThreeScene";
import {
  altColor, buildAtmosphere, buildCoastlines, buildGlobeBody, buildGraticule,
  geoToVec3, makeGlowTexture, MINT,
} from "./earthUtils";
import {
  getGroups, getTLE, type SatGroup, type TLE,
  type SpaceWeather, type Fireball, type ISS, type Launch,
} from "./sentinel";

interface Pass { start: number; end: number; maxEl: number; }
interface Props {
  spaceWeather: SpaceWeather | null;
  fireballs: Fireball[];
  iss: ISS | null;
  launches: Launch[];
}

const SPEEDS = [1, 10, 60, 300, 1800];
const OBSERVER = { lat: 40.7128, lon: -74.006 }; // NYC

function fmtCountdown(ms: number): string {
  if (ms <= 0) return "now";
  const s = Math.floor(ms / 1000);
  const d = Math.floor(s / 86400), h = Math.floor((s % 86400) / 3600), m = Math.floor((s % 3600) / 60);
  if (d > 0) return `${d}d ${h}h`;
  if (h > 0) return `${h}h ${m}m`;
  return `${m}m`;
}
const speedLabel = (x: number) => (x >= 3600 ? `${x / 3600}h/s` : x >= 60 ? `${x / 60}m/s` : `${x}×`);

export function EarthView({ spaceWeather, fireballs, iss, launches }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const glow = useMemo(makeGlowTexture, []);

  // scene object refs
  const geomRef = useRef<THREE.BufferGeometry | null>(null);
  const matRef = useRef<THREE.PointsMaterial | null>(null);
  const pointsRef = useRef<THREE.Points | null>(null);
  const colorsSet = useRef(false);
  const selMarkerRef = useRef<THREE.Sprite | null>(null);
  const orbitRef = useRef<THREE.Line | null>(null);
  const auroraRef = useRef<THREE.Group | null>(null);
  const fireballRef = useRef<THREE.Group | null>(null);
  const handlesRef2 = useRef<ThreeHandles | null>(null);
  const workerRef = useRef<Worker | null>(null);

  // sim/time refs
  const simTimeRef = useRef(Date.now());
  const playingRef = useRef(true);
  const speedRef = useRef(1);
  const selectedIdxRef = useRef<number | null>(null);
  const posAccum = useRef(0);

  // UI state
  const [groups, setGroups] = useState<SatGroup[]>([]);
  const [group, setGroup] = useState("stations");
  const [sats, setSats] = useState<TLE[]>([]);
  const [loading, setLoading] = useState(false);
  const [layers, setLayers] = useState({ sats: true, land: true, grid: true, aurora: true, fireballs: true });
  const [selected, setSelected] = useState<number | null>(null);
  const [passes, setPasses] = useState<Pass[]>([]);
  const [playing, setPlaying] = useState(true);
  const [speed, setSpeed] = useState(1);
  const [clock, setClock] = useState(Date.now());
  const [, force] = useState(0);

  useEffect(() => { playingRef.current = playing; }, [playing]);
  useEffect(() => { speedRef.current = speed; }, [speed]);
  useEffect(() => { selectedIdxRef.current = selected; }, [selected]);

  // ---- scene setup (once) ----
  const { handlesRef, addFrameCallback } = useThreeScene(
    containerRef,
    { background: 0x03070d, cameraPosition: [0, 1.2, 3.2], fov: 50, minDistance: 1.3, maxDistance: 12 },
    (h) => {
      handlesRef2.current = h;
      h.scene.add(buildGlobeBody());
      const grat = buildGraticule();
      grat.name = "grid";
      h.scene.add(grat);
      h.scene.add(buildAtmosphere());

      // stars
      const starPos: number[] = [];
      for (let i = 0; i < 2500; i++) {
        const v = new THREE.Vector3().randomDirection().multiplyScalar(60 + Math.random() * 40);
        starPos.push(v.x, v.y, v.z);
      }
      const starGeo = new THREE.BufferGeometry();
      starGeo.setAttribute("position", new THREE.Float32BufferAttribute(starPos, 3));
      h.scene.add(new THREE.Points(starGeo, new THREE.PointsMaterial({ color: 0x9fb3c8, size: 0.06, sizeAttenuation: true, transparent: true, opacity: 0.7 })));

      // selected marker
      const sprite = new THREE.Sprite(new THREE.SpriteMaterial({ map: glow, color: 0xffffff, transparent: true, depthWrite: false, blending: THREE.AdditiveBlending }));
      sprite.scale.setScalar(0.13);
      sprite.visible = false;
      selMarkerRef.current = sprite;
      h.scene.add(sprite);

      // aurora + fireball groups
      const aur = new THREE.Group(); auroraRef.current = aur; h.scene.add(aur);
      const fb = new THREE.Group(); fireballRef.current = fb; h.scene.add(fb);

      // coastlines (async)
      void buildCoastlines().then((lines) => {
        if (lines) { lines.name = "land"; lines.visible = layers.land; h.scene.add(lines); }
      });
    },
  );

  // ---- per-frame ----
  useEffect(() => {
    const un = addFrameCallback((dt) => {
      if (playingRef.current) simTimeRef.current += dt * 1000 * speedRef.current;
      posAccum.current += dt;
      if (posAccum.current > 0.08 && workerRef.current) {
        posAccum.current = 0;
        workerRef.current.postMessage({ type: "positions", timeMs: simTimeRef.current });
      }
      if (matRef.current) matRef.current.size = 0.05 + Math.sin(performance.now() / 500) * 0.006;
      const sel = selectedIdxRef.current;
      const marker = selMarkerRef.current;
      if (marker && sel != null && geomRef.current) {
        const arr = (geomRef.current.getAttribute("position") as THREE.BufferAttribute).array as Float32Array;
        marker.position.set(arr[sel * 3], arr[sel * 3 + 1], arr[sel * 3 + 2]);
        marker.visible = true;
      } else if (marker) marker.visible = false;
    });
    return un;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // clock display + countdown refresh
  useEffect(() => {
    const id = setInterval(() => { setClock(simTimeRef.current); force((n) => n + 1); }, 300);
    return () => clearInterval(id);
  }, []);

  // ---- worker ----
  useEffect(() => {
    const w = new Worker(new URL("./satelliteWorker.ts", import.meta.url), { type: "module" });
    workerRef.current = w;
    w.onmessage = (e: MessageEvent) => {
      const m = e.data;
      if (m.type === "positions") {
        const geom = geomRef.current;
        if (!geom) return;
        const posAttr = geom.getAttribute("position") as THREE.BufferAttribute;
        if (posAttr && m.positions.length === posAttr.array.length) {
          (posAttr.array as Float32Array).set(m.positions);
          posAttr.needsUpdate = true;
          if (!colorsSet.current && m.altKm) {
            const colAttr = geom.getAttribute("color") as THREE.BufferAttribute;
            const arr = colAttr.array as Float32Array;
            for (let i = 0; i < m.count; i++) {
              const c = altColor(m.altKm[i] || 0);
              arr[i * 3] = c.r; arr[i * 3 + 1] = c.g; arr[i * 3 + 2] = c.b;
            }
            colAttr.needsUpdate = true;
            colorsSet.current = true;
          }
        }
      } else if (m.type === "orbit") {
        const h = handlesRef2.current;
        if (!h) return;
        if (orbitRef.current) { h.scene.remove(orbitRef.current); orbitRef.current.geometry.dispose(); orbitRef.current = null; }
        if (m.points.length > 3) {
          const g = new THREE.BufferGeometry();
          g.setAttribute("position", new THREE.Float32BufferAttribute(m.points, 3));
          const line = new THREE.Line(g, new THREE.LineBasicMaterial({ color: MINT, transparent: true, opacity: 0.75 }));
          orbitRef.current = line; h.scene.add(line);
        }
      } else if (m.type === "passes") {
        setPasses(m.passes || []);
      }
    };
    return () => { w.terminate(); workerRef.current = null; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // load groups once
  useEffect(() => { void getGroups().then((d) => d && setGroups(d.groups)); }, []);

  // load satellites for group
  useEffect(() => {
    setLoading(true);
    setSelected(null);
    void getTLE(group).then((d) => {
      const list = d?.satellites || [];
      setSats(list);
      setLoading(false);
      // (re)build the points cloud sized to the new set
      const h = handlesRef2.current;
      if (h) {
        if (pointsRef.current) { h.scene.remove(pointsRef.current); pointsRef.current.geometry.dispose(); }
        const n = Math.max(list.length, 1);
        const geom = new THREE.BufferGeometry();
        geom.setAttribute("position", new THREE.BufferAttribute(new Float32Array(n * 3), 3));
        geom.setAttribute("color", new THREE.BufferAttribute(new Float32Array(n * 3).fill(0.6), 3));
        geomRef.current = geom;
        colorsSet.current = false;
        const mat = new THREE.PointsMaterial({ size: 0.05, map: glow, vertexColors: true, transparent: true, depthWrite: false, blending: THREE.AdditiveBlending, sizeAttenuation: true });
        matRef.current = mat;
        const pts = new THREE.Points(geom, mat);
        pts.visible = layers.sats;
        pointsRef.current = pts;
        h.scene.add(pts);
      }
      if (workerRef.current && list.length) workerRef.current.postMessage({ type: "load", satellites: list });
      if (orbitRef.current && h) { h.scene.remove(orbitRef.current); orbitRef.current = null; }
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [group]);

  // selection -> request orbit + passes
  useEffect(() => {
    const w = workerRef.current;
    if (!w || selected == null) { setPasses([]); return; }
    w.postMessage({ type: "orbit", index: selected, timeMs: simTimeRef.current });
    w.postMessage({ type: "passes", index: selected, timeMs: simTimeRef.current, lat: OBSERVER.lat, lon: OBSERVER.lon });
  }, [selected]);

  // layer visibility
  useEffect(() => {
    const h = handlesRef2.current;
    if (!h) return;
    if (pointsRef.current) pointsRef.current.visible = layers.sats;
    const grid = h.scene.getObjectByName("grid"); if (grid) grid.visible = layers.grid;
    const land = h.scene.getObjectByName("land"); if (land) land.visible = layers.land;
    if (auroraRef.current) auroraRef.current.visible = layers.aurora;
    if (fireballRef.current) fireballRef.current.visible = layers.fireballs;
  }, [layers]);

  // aurora from Kp
  useEffect(() => {
    const grp = auroraRef.current;
    if (!grp) return;
    grp.clear();
    const kp = spaceWeather?.kp;
    if (kp == null || kp < 1) return;
    const intensity = Math.min(1, kp / 9);
    const latDeg = 75 - kp * 2;
    const y = Math.sin((latDeg * Math.PI) / 180);
    const rad = Math.cos((latDeg * Math.PI) / 180) * 1.04;
    [1, -1].forEach((sgn) => {
      const mesh = new THREE.Mesh(
        new THREE.TorusGeometry(rad, 0.02 + intensity * 0.05, 8, 96),
        new THREE.MeshBasicMaterial({ color: 0x3bff9e, transparent: true, opacity: 0.25 + intensity * 0.5, blending: THREE.AdditiveBlending }),
      );
      mesh.position.y = sgn * y;
      mesh.rotation.x = Math.PI / 2;
      grp.add(mesh);
    });
  }, [spaceWeather]);

  // fireball surface markers
  useEffect(() => {
    const grp = fireballRef.current;
    if (!grp) return;
    grp.clear();
    fireballs.slice(0, 40).forEach((f) => {
      if (f.lat == null || f.lon == null) return;
      const pos = geoToVec3(f.lon, f.lat, 1.01);
      const mesh = new THREE.Mesh(
        new THREE.ConeGeometry(0.018, 0.05, 6),
        new THREE.MeshBasicMaterial({ color: 0xffb454, transparent: true, opacity: 0.85 }),
      );
      mesh.position.copy(pos);
      mesh.lookAt(0, 0, 0);
      mesh.rotateX(Math.PI / 2);
      grp.add(mesh);
    });
  }, [fireballs]);

  // ---- click to select satellite ----
  useEffect(() => {
    const el = handlesRef.current?.renderer.domElement;
    if (!el) return;
    const onClick = (ev: MouseEvent) => {
      const h = handlesRef2.current;
      if (!h || !pointsRef.current || !layers.sats) return;
      const rect = el.getBoundingClientRect();
      const ndc = new THREE.Vector2(((ev.clientX - rect.left) / rect.width) * 2 - 1, -((ev.clientY - rect.top) / rect.height) * 2 + 1);
      const ray = new THREE.Raycaster();
      ray.params.Points = { threshold: 0.06 };
      ray.setFromCamera(ndc, h.camera);
      const hits = ray.intersectObject(pointsRef.current);
      if (hits.length && hits[0].index != null) setSelected(hits[0].index);
    };
    el.addEventListener("click", onClick);
    return () => el.removeEventListener("click", onClick);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [layers.sats]);

  const selectedSat = selected != null ? sats[selected] : null;
  const offsetH = (clock - Date.now()) / 3600000;
  const goLive = () => { simTimeRef.current = Date.now(); setSpeed(1); setPlaying(true); };
  const scrub = (h: number) => { simTimeRef.current = Date.now() + h * 3600000; setPlaying(false); };

  return (
    <div className="sen-earth">
      <div className="sen-canvas" ref={containerRef} />

      {/* top-left: group + layers */}
      <div className="sen-controls">
        <select className="sen-select" value={group} onChange={(e) => setGroup(e.target.value)}>
          {groups.map((g) => <option key={g.id} value={g.id}>{g.label}</option>)}
        </select>
        <div className="sen-count">{loading ? "loading…" : `${sats.length} tracked`}</div>
        <div className="sen-chips">
          {([["sats", "Sats"], ["land", "Land"], ["grid", "Grid"], ["aurora", "Aurora"], ["fireballs", "Fireballs"]] as const).map(([k, label]) => (
            <button key={k} className={`sen-chip ${layers[k] ? "on" : ""}`} onClick={() => setLayers((l) => ({ ...l, [k]: !l[k] }))}>{label}</button>
          ))}
        </div>
      </div>

      {/* top-right: space weather */}
      {spaceWeather && (
        <div className="sen-weather">
          <div className="sen-weather-title">SPACE WEATHER</div>
          <div className="sen-kp">
            <div className={`sen-kp-val ${spaceWeather.kp != null && spaceWeather.kp >= 5 ? "storm" : ""}`}>{Number.isFinite(spaceWeather.kp as number) ? spaceWeather.kp : "—"}</div>
            <div className="sen-kp-label">Kp index</div>
          </div>
          <div className={`sen-storm ${spaceWeather.kp != null && spaceWeather.kp >= 5 ? "storm" : ""}`}>{spaceWeather.storm}</div>
          <div className="sen-wrow"><span>Solar wind</span><span>{Number.isFinite(spaceWeather.wind_speed as number) ? `${Math.round(spaceWeather.wind_speed as number)} km/s` : "—"}</span></div>
          <div className="sen-wrow"><span>Density</span><span>{Number.isFinite(spaceWeather.density as number) ? `${(spaceWeather.density as number).toFixed(1)} p/cm³` : "—"}</span></div>
          <div className="sen-spark">
            {spaceWeather.kp_series.slice(-24).map((p, i) => (
              <div key={i} className={`sen-bar ${p.kp >= 5 ? "storm" : ""}`} style={{ height: `${Math.max(4, (p.kp / 9) * 100)}%` }} title={`Kp ${p.kp}`} />
            ))}
          </div>
        </div>
      )}

      {/* bottom: time controls */}
      <div className="sen-time">
        <button className="sen-play" onClick={() => setPlaying((p) => !p)}>{playing ? "❚❚" : "▶"}</button>
        <div className="sen-clock">
          <div className="sen-clock-time">{new Date(clock).toUTCString().replace(" GMT", " UTC")}</div>
          <div className="sen-clock-off">{Math.abs(offsetH) < 0.05 ? "LIVE" : `${offsetH > 0 ? "+" : ""}${offsetH.toFixed(1)}h`}</div>
        </div>
        <div className="sen-chips">
          {SPEEDS.map((s) => <button key={s} className={`sen-chip ${speed === s ? "on" : ""}`} onClick={() => setSpeed(s)}>{speedLabel(s)}</button>)}
        </div>
        <input className="sen-scrub" type="range" min={-12} max={12} step={0.25} value={Math.max(-12, Math.min(12, offsetH))} onChange={(e) => scrub(parseFloat(e.target.value))} />
        <button className="sen-live" onClick={goLive}>LIVE</button>
      </div>

      {/* selected satellite */}
      {selectedSat && (
        <div className="sen-detail">
          <button className="sen-detail-close" onClick={() => setSelected(null)}>✕</button>
          <div className="sen-detail-kind">SATELLITE</div>
          <h3>{selectedSat.name}</h3>
          <div className="sen-drow"><span>NORAD ID</span><span>{selectedSat.norad_id}</span></div>
          <div className="sen-passes-title">Next passes · NYC</div>
          {passes.length === 0 && <div className="sen-empty">No passes above 10° in 48h</div>}
          {passes.map((p, i) => (
            <div key={i} className="sen-pass">
              <div className="sen-pass-time">{new Date(p.start).toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" })}</div>
              <div className="sen-pass-meta">max el {p.maxEl}° · {Math.round((p.end - p.start) / 60000)} min · in {fmtCountdown(p.start - clock)}</div>
            </div>
          ))}
        </div>
      )}

      {/* bottom-right: ISS + launches */}
      {!selectedSat && (
        <div className="sen-side">
          {iss && (
            <div className="sen-card">
              <div className="sen-card-head">◉ ISS · {iss.crew.length} crew</div>
              {iss.lat != null && <div className="sen-wrow"><span>Position</span><span>{iss.lat.toFixed(1)}, {iss.lon?.toFixed(1)}</span></div>}
              {iss.altitude_km != null && <div className="sen-wrow"><span>Altitude</span><span>{Math.round(iss.altitude_km)} km</span></div>}
              {iss.velocity_kms != null && <div className="sen-wrow"><span>Velocity</span><span>{iss.velocity_kms.toFixed(1)} km/s</span></div>}
              {iss.crew.length > 0 && <div className="sen-crew">{iss.crew.join(" · ")}</div>}
            </div>
          )}
          {launches.length > 0 && (
            <div className="sen-card">
              <div className="sen-card-head">🚀 Upcoming launches</div>
              {launches.slice(0, 4).map((l) => (
                <div key={l.id} className="sen-launch">
                  <div className="sen-launch-name">{l.name}</div>
                  <div className="sen-launch-meta">{l.provider}{l.net ? ` · in ${fmtCountdown(new Date(l.net).getTime() - clock)}` : ""}</div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

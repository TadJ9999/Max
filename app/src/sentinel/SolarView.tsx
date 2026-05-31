import { useEffect, useMemo, useRef, useState } from "react";
import * as THREE from "three";
import { useThreeScene, type ThreeHandles } from "./useThreeScene";
import { makeGlowTexture } from "./earthUtils";
import {
  PLANETS, dateToJD, planetPosition, planetOrbitPoints, neoOrbitPoints, neoPosition, toScene,
} from "./solarUtils";
import type { Neo } from "./sentinel";

interface Props { neos: Neo[]; }

const PLANET_SIZE: Record<string, number> = {
  Mercury: 0.03, Venus: 0.045, Earth: 0.05, Mars: 0.035,
  Jupiter: 0.11, Saturn: 0.095, Uranus: 0.07, Neptune: 0.07,
};
const SPEEDS = [0, 1, 7, 30, 120]; // days per second

interface Sel { kind: "planet" | "neo"; name: string; data?: Neo; }

export function SolarView({ neos }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const glow = useMemo(makeGlowTexture, []);

  const handles2 = useRef<ThreeHandles | null>(null);
  const planetMeshes = useRef<{ mesh: THREE.Mesh; idx: number }[]>([]);
  const neoMarkers = useRef<{ mesh: THREE.Mesh; orbit: Neo }[]>([]);
  const neoGroupRef = useRef<THREE.Group | null>(null);

  const simDateRef = useRef(Date.now());
  const playingRef = useRef(true);
  const speedRef = useRef(7);

  const [dayOffset, setDayOffset] = useState(0);
  const [playing, setPlaying] = useState(true);
  const [speed, setSpeed] = useState(7);
  const [selected, setSelected] = useState<Sel | null>(null);

  useEffect(() => { playingRef.current = playing; }, [playing]);
  useEffect(() => { speedRef.current = speed; }, [speed]);

  const { handlesRef, addFrameCallback } = useThreeScene(
    containerRef,
    { background: 0x03060c, cameraPosition: [0, 6, 9], fov: 50, minDistance: 1, maxDistance: 60 },
    (h) => {
      handles2.current = h;

      // Sun
      const sun = new THREE.Mesh(new THREE.SphereGeometry(0.14, 32, 32), new THREE.MeshBasicMaterial({ color: 0xffcc44 }));
      h.scene.add(sun);
      const sunGlow = new THREE.Sprite(new THREE.SpriteMaterial({ map: glow, color: 0xffd166, transparent: true, depthWrite: false, blending: THREE.AdditiveBlending }));
      sunGlow.scale.setScalar(0.9);
      h.scene.add(sunGlow);

      // stars
      const starPos: number[] = [];
      for (let i = 0; i < 3000; i++) { const v = new THREE.Vector3().randomDirection().multiplyScalar(120 + Math.random() * 80); starPos.push(v.x, v.y, v.z); }
      const sg = new THREE.BufferGeometry();
      sg.setAttribute("position", new THREE.Float32BufferAttribute(starPos, 3));
      h.scene.add(new THREE.Points(sg, new THREE.PointsMaterial({ color: 0x9fb3c8, size: 0.12, transparent: true, opacity: 0.7 })));

      // planets + orbit rings
      const jd = dateToJD(new Date());
      PLANETS.forEach((p, idx) => {
        const pts = planetOrbitPoints(p, jd).map((v) => new THREE.Vector3(...toScene(v)));
        const og = new THREE.BufferGeometry().setFromPoints(pts);
        h.scene.add(new THREE.Line(og, new THREE.LineBasicMaterial({ color: 0x2a4a66, transparent: true, opacity: 0.5 })));
        const mesh = new THREE.Mesh(new THREE.SphereGeometry(PLANET_SIZE[p.name] ?? 0.04, 24, 24), new THREE.MeshBasicMaterial({ color: p.color }));
        mesh.position.set(...toScene(planetPosition(p, jd)));
        mesh.userData = { kind: "planet", name: p.name };
        h.scene.add(mesh);
        planetMeshes.current.push({ mesh, idx });
      });

      // asteroid belt (2.1–3.3 AU)
      const beltGeo = new THREE.SphereGeometry(0.012, 6, 6);
      const beltMat = new THREE.MeshBasicMaterial({ color: 0x6b7280 });
      const belt = new THREE.InstancedMesh(beltGeo, beltMat, 1200);
      const dummy = new THREE.Object3D();
      for (let i = 0; i < 1200; i++) {
        const au = 2.1 + Math.random() * 1.2;
        const th = Math.random() * Math.PI * 2;
        const incl = (Math.random() - 0.5) * 0.2;
        const v = { x: au * Math.cos(th), y: au * Math.sin(th), z: au * incl };
        dummy.position.set(...toScene(v));
        dummy.updateMatrix();
        belt.setMatrixAt(i, dummy.matrix);
      }
      h.scene.add(belt);

      const neoGroup = new THREE.Group(); neoGroupRef.current = neoGroup; h.scene.add(neoGroup);
    },
  );

  // per-frame: advance sim date and move planets + NEOs
  useEffect(() => {
    const un = addFrameCallback((dt) => {
      if (playingRef.current) simDateRef.current += dt * speedRef.current * 86400000;
      const jd = dateToJD(new Date(simDateRef.current));
      planetMeshes.current.forEach(({ mesh, idx }) => mesh.position.set(...toScene(planetPosition(PLANETS[idx], jd))));
      neoMarkers.current.forEach(({ mesh, orbit }) => {
        if (!orbit.orbit) return;
        const v = neoPosition(orbit.orbit, jd);
        if (v) mesh.position.set(...toScene(v));
      });
    });
    return un;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // reflect scrubber/clock state
  useEffect(() => {
    const id = setInterval(() => setDayOffset(Math.round((simDateRef.current - Date.now()) / 86400000)), 300);
    return () => clearInterval(id);
  }, []);

  // build NEO orbits + markers when data changes
  useEffect(() => {
    const grp = neoGroupRef.current;
    if (!grp) return;
    grp.clear();
    neoMarkers.current = [];
    const jd = dateToJD(new Date(simDateRef.current));
    neos.filter((n) => n.orbit && n.orbit.a != null).slice(0, 16).forEach((n) => {
      const pts = neoOrbitPoints(n.orbit!);
      if (pts) {
        const og = new THREE.BufferGeometry().setFromPoints(pts.map((v) => new THREE.Vector3(...toScene(v))));
        grp.add(new THREE.Line(og, new THREE.LineBasicMaterial({ color: n.hazardous ? 0xff4d6d : 0x6fe3c8, transparent: true, opacity: n.hazardous ? 0.7 : 0.4 })));
      }
      const mesh = new THREE.Mesh(new THREE.OctahedronGeometry(n.hazardous ? 0.05 : 0.035, 0), new THREE.MeshBasicMaterial({ color: n.hazardous ? 0xff4d6d : 0xffd166 }));
      const v = neoPosition(n.orbit!, jd);
      if (v) mesh.position.set(...toScene(v));
      mesh.userData = { kind: "neo", name: n.name };
      grp.add(mesh);
      neoMarkers.current.push({ mesh, orbit: n });
    });
  }, [neos]);

  // click selection (planets + NEOs)
  useEffect(() => {
    const el = handlesRef.current?.renderer.domElement;
    if (!el) return;
    const onClick = (ev: MouseEvent) => {
      const h = handles2.current;
      if (!h) return;
      const rect = el.getBoundingClientRect();
      const ndc = new THREE.Vector2(((ev.clientX - rect.left) / rect.width) * 2 - 1, -((ev.clientY - rect.top) / rect.height) * 2 + 1);
      const ray = new THREE.Raycaster();
      ray.setFromCamera(ndc, h.camera);
      const targets = [...planetMeshes.current.map((p) => p.mesh), ...neoMarkers.current.map((n) => n.mesh)];
      const hits = ray.intersectObjects(targets);
      if (hits.length) {
        const ud = hits[0].object.userData as { kind: "planet" | "neo"; name: string };
        const neo = ud.kind === "neo" ? neos.find((n) => n.name === ud.name) : undefined;
        setSelected({ kind: ud.kind, name: ud.name, data: neo });
      } else setSelected(null);
    };
    el.addEventListener("click", onClick);
    return () => el.removeEventListener("click", onClick);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [neos]);

  const simDate = new Date(Date.now() + dayOffset * 86400000);
  const goNow = () => { simDateRef.current = Date.now(); setDayOffset(0); };
  const scrub = (d: number) => { simDateRef.current = Date.now() + d * 86400000; setPlaying(false); };

  return (
    <div className="sen-solar">
      <div className="sen-canvas" ref={containerRef} />

      <div className="sen-controls">
        <div className="sen-legend">☀ Heliocentric · {neos.filter((n) => n.orbit).length} NEO orbits</div>
        <div className="sen-legend-row"><span className="sen-dot hazard" /> hazardous <span className="sen-dot neo" /> near-Earth</div>
      </div>

      <div className="sen-time">
        <button className="sen-play" onClick={() => setPlaying((p) => !p)}>{playing ? "❚❚" : "▶"}</button>
        <div className="sen-clock">
          <div className="sen-clock-time">{simDate.toLocaleDateString([], { year: "numeric", month: "short", day: "numeric" })}</div>
          <div className="sen-clock-off">{dayOffset === 0 ? "TODAY" : `${dayOffset > 0 ? "+" : ""}${dayOffset}d`}</div>
        </div>
        <div className="sen-chips">
          {SPEEDS.map((s) => <button key={s} className={`sen-chip ${speed === s ? "on" : ""}`} onClick={() => setSpeed(s)}>{s === 0 ? "0" : `${s}d/s`}</button>)}
        </div>
        <input className="sen-scrub" type="range" min={-365} max={365} step={1} value={Math.max(-365, Math.min(365, dayOffset))} onChange={(e) => scrub(parseInt(e.target.value))} />
        <button className="sen-live" onClick={goNow}>TODAY</button>
      </div>

      {selected && (
        <div className="sen-detail">
          <button className="sen-detail-close" onClick={() => setSelected(null)}>✕</button>
          {selected.kind === "planet" ? (
            <>
              <div className="sen-detail-kind">PLANET</div>
              <h3>{selected.name}</h3>
              <div className="sen-empty">Heliocentric position at {simDate.toLocaleDateString()}.</div>
            </>
          ) : selected.data ? (
            <>
              <div className={`sen-detail-kind ${selected.data.hazardous ? "hazard" : ""}`}>{selected.data.hazardous ? "⚠ HAZARDOUS NEO" : "NEAR-EARTH OBJECT"}</div>
              <h3>{selected.data.name}</h3>
              <div className="sen-drow"><span>Diameter</span><span>{selected.data.diameter_min_m}–{selected.data.diameter_max_m} m</span></div>
              <div className="sen-drow"><span>Miss distance</span><span>{selected.data.miss_lunar} LD</span></div>
              <div className="sen-drow"><span /><span className="sen-dim">{selected.data.miss_km?.toLocaleString()} km</span></div>
              <div className="sen-drow"><span>Velocity</span><span>{selected.data.velocity_kms} km/s</span></div>
              <div className="sen-drow"><span>Approach</span><span>{selected.data.approach_date}</span></div>
              {selected.data.jpl_url && <a className="sen-link" href={selected.data.jpl_url} target="_blank" rel="noreferrer">JPL details →</a>}
            </>
          ) : null}
        </div>
      )}
    </div>
  );
}

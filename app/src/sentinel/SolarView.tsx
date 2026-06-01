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
const _UP = new THREE.Vector3(0, 1, 0); // comet local axis the tail extends along

interface Sel { kind: "planet" | "neo"; name: string; data?: Neo; }

// Derive a display type from orbital eccentricity — comets ride highly
// eccentric orbits (e≳0.8); everything else we render as a rocky asteroid.
type NeoKind = "comet" | "asteroid";
function neoKind(n: Neo): NeoKind {
  return (n.orbit?.e ?? 0) > 0.8 ? "comet" : "asteroid";
}

// Scene size from physical diameter (log-scaled so a 20 km comet doesn't dwarf a
// 50 m rock), nudged up for hazardous objects so they read at a glance.
function neoRadius(n: Neo): number {
  const d = n.diameter_max_m ?? 150;
  const r = 0.02 + Math.log10(Math.max(10, d)) * 0.009;
  return Math.min(0.075, r) * (n.hazardous ? 1.25 : 1);
}

// A real 3D body per type: an irregular faceted rock for asteroids; an icy
// nucleus + additive coma + tail for comets (the tail is oriented away from the
// Sun each frame by the caller). `comet` groups carry userData.tail = true.
function makeNeoMesh(n: Neo, glow: THREE.Texture): THREE.Object3D {
  const r = neoRadius(n);
  const hazard = n.hazardous;
  if (neoKind(n) === "comet") {
    const col = hazard ? 0xff6b8a : 0x9fe8ff;
    const grp = new THREE.Group();
    const nucleus = new THREE.Mesh(
      new THREE.IcosahedronGeometry(r * 0.7, 0),
      new THREE.MeshStandardMaterial({ color: col, emissive: col, emissiveIntensity: 0.5, flatShading: true, roughness: 0.7 }),
    );
    grp.add(nucleus);
    const coma = new THREE.Sprite(new THREE.SpriteMaterial({ map: glow, color: col, transparent: true, opacity: 0.55, depthWrite: false, blending: THREE.AdditiveBlending }));
    coma.scale.setScalar(r * 5);
    grp.add(coma);
    // Tail built along +Y from the nucleus; group is rotated so +Y faces away
    // from the Sun. Cone (wide end out) gives the classic flared dust tail.
    const len = r * 14;
    const tail = new THREE.Mesh(
      new THREE.ConeGeometry(r * 2.2, len, 14, 1, true),
      new THREE.MeshBasicMaterial({ color: col, transparent: true, opacity: 0.22, side: THREE.DoubleSide, depthWrite: false, blending: THREE.AdditiveBlending }),
    );
    tail.position.y = len / 2;          // base at nucleus, apex pointing +Y outward
    tail.rotation.x = Math.PI;          // flare the wide end away from the Sun
    grp.add(tail);
    grp.userData = { tail: true };
    return grp;
  }
  // asteroid — jitter an icosahedron's vertices for an irregular rocky silhouette
  const col = hazard ? 0xff4d6d : 0xc9a06a;
  const geo = new THREE.IcosahedronGeometry(r, 1);
  const pos = geo.attributes.position;
  for (let i = 0; i < pos.count; i++) {
    const f = 0.78 + Math.random() * 0.44;
    pos.setXYZ(i, pos.getX(i) * f, pos.getY(i) * f, pos.getZ(i) * f);
  }
  geo.computeVertexNormals();
  return new THREE.Mesh(
    geo,
    new THREE.MeshStandardMaterial({ color: col, emissive: col, emissiveIntensity: 0.22, flatShading: true, roughness: 0.95, metalness: 0.1 }),
  );
}

export function SolarView({ neos }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const glow = useMemo(makeGlowTexture, []);

  const handles2 = useRef<ThreeHandles | null>(null);
  const planetMeshes = useRef<{ mesh: THREE.Mesh; idx: number }[]>([]);
  const neoMarkers = useRef<{ obj: THREE.Object3D; orbit: Neo; comet: boolean }[]>([]);
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

      // Lighting for the shaded NEO meshes (planets use unlit MeshBasic, so they
      // are unaffected). Sunlight radiates from the origin with no falloff so
      // distant objects stay lit; ambient keeps the dark side from going black.
      h.scene.add(new THREE.AmbientLight(0xffffff, 0.4));
      const sunLight = new THREE.PointLight(0xfff2d6, 2.4, 0, 0);
      h.scene.add(sunLight);

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
      neoMarkers.current.forEach(({ obj, orbit, comet }) => {
        if (!orbit.orbit) return;
        const v = neoPosition(orbit.orbit, jd);
        if (!v) return;
        obj.position.set(...toScene(v));
        // Comet tail always points radially away from the Sun (origin): rotate the
        // group's local +Y axis to the outward direction.
        if (comet) obj.quaternion.setFromUnitVectors(_UP, obj.position.clone().normalize());
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
      const comet = neoKind(n) === "comet";
      const obj = makeNeoMesh(n, glow);
      const v = neoPosition(n.orbit!, jd);
      if (v) {
        obj.position.set(...toScene(v));
        if (comet) obj.quaternion.setFromUnitVectors(_UP, obj.position.clone().normalize());
      }
      obj.userData = { ...obj.userData, kind: "neo", name: n.name };
      grp.add(obj);
      neoMarkers.current.push({ obj, orbit: n, comet });
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
      const targets = [...planetMeshes.current.map((p) => p.mesh), ...neoMarkers.current.map((n) => n.obj)];
      const hits = ray.intersectObjects(targets, true); // recursive: comets are groups
      if (hits.length) {
        // Walk up to the marker that carries the {kind,name} userData (a comet
        // group's nucleus/tail children have none of their own).
        let o: THREE.Object3D | null = hits[0].object;
        while (o && !(o.userData && o.userData.kind)) o = o.parent;
        const ud = (o?.userData ?? {}) as { kind?: "planet" | "neo"; name?: string };
        if (ud.kind) {
          const neo = ud.kind === "neo" ? neos.find((n) => n.name === ud.name) : undefined;
          setSelected({ kind: ud.kind, name: ud.name!, data: neo });
        } else setSelected(null);
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
        <div className="sen-legend-row"><span className="sen-dot hazard" /> hazardous <span className="sen-dot neo" /> asteroid · comet (tail)</div>
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
              <div className={`sen-detail-kind ${selected.data.hazardous ? "hazard" : ""}`}>{(selected.data.hazardous ? "⚠ HAZARDOUS " : "NEAR-EARTH ") + neoKind(selected.data).toUpperCase()}</div>
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

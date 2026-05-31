// Shared Three.js scene lifecycle: renderer + camera + OrbitControls + a single
// animation loop with registerable per-frame callbacks, plus resize handling.
// Both EarthView and SolarView build their objects into the returned scene and
// register an update callback (which reads UI state via refs to avoid staleness).
import { useEffect, useRef } from "react";
import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";

export interface ThreeHandles {
  scene: THREE.Scene;
  camera: THREE.PerspectiveCamera;
  renderer: THREE.WebGLRenderer;
  controls: OrbitControls;
}

export interface ThreeOptions {
  background?: number;
  cameraPosition?: [number, number, number];
  fov?: number;
  minDistance?: number;
  maxDistance?: number;
  autoRotate?: boolean;
}

type FrameCb = (dt: number, elapsed: number) => void;

export function useThreeScene(
  containerRef: React.RefObject<HTMLDivElement | null>,
  opts: ThreeOptions,
  onInit: (h: ThreeHandles) => void | (() => void),
) {
  const frameCbs = useRef<Set<FrameCb>>(new Set());
  const handlesRef = useRef<ThreeHandles | null>(null);

  // Stable ref to onInit so we only ever build the scene once.
  const onInitRef = useRef(onInit);
  onInitRef.current = onInit;

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    const scene = new THREE.Scene();
    if (opts.background !== undefined) scene.background = new THREE.Color(opts.background);

    const camera = new THREE.PerspectiveCamera(
      opts.fov ?? 50,
      container.clientWidth / Math.max(1, container.clientHeight),
      0.01,
      2000,
    );
    const [cx, cy, cz] = opts.cameraPosition ?? [0, 1.4, 3.4];
    camera.position.set(cx, cy, cz);

    const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: false });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.setSize(container.clientWidth, container.clientHeight);
    container.appendChild(renderer.domElement);

    const controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;
    controls.dampingFactor = 0.08;
    controls.enablePan = false;
    controls.rotateSpeed = 0.5;
    controls.zoomSpeed = 0.8;
    if (opts.minDistance) controls.minDistance = opts.minDistance;
    if (opts.maxDistance) controls.maxDistance = opts.maxDistance;
    if (opts.autoRotate) { controls.autoRotate = true; controls.autoRotateSpeed = 0.3; }

    const handles: ThreeHandles = { scene, camera, renderer, controls };
    handlesRef.current = handles;
    const cleanupUser = onInitRef.current(handles);

    const clock = new THREE.Clock();
    let raf = 0;
    const loop = () => {
      raf = requestAnimationFrame(loop);
      const dt = clock.getDelta();
      const elapsed = clock.elapsedTime;
      frameCbs.current.forEach((cb) => cb(dt, elapsed));
      controls.update();
      renderer.render(scene, camera);
    };
    loop();

    const onResize = () => {
      const w = container.clientWidth, h = Math.max(1, container.clientHeight);
      camera.aspect = w / h;
      camera.updateProjectionMatrix();
      renderer.setSize(w, h);
    };
    const ro = new ResizeObserver(onResize);
    ro.observe(container);

    return () => {
      cancelAnimationFrame(raf);
      ro.disconnect();
      if (typeof cleanupUser === "function") cleanupUser();
      controls.dispose();
      renderer.dispose();
      if (renderer.domElement.parentNode === container) container.removeChild(renderer.domElement);
      scene.traverse((o) => {
        const mesh = o as THREE.Mesh;
        if (mesh.geometry) mesh.geometry.dispose();
        const mat = mesh.material as THREE.Material | THREE.Material[] | undefined;
        if (Array.isArray(mat)) mat.forEach((m) => m.dispose());
        else if (mat) mat.dispose();
      });
      handlesRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const addFrameCallback = (cb: FrameCb) => {
    frameCbs.current.add(cb);
    return () => { frameCbs.current.delete(cb); };
  };

  return { handlesRef, addFrameCallback };
}

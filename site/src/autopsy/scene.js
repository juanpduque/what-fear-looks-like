import * as THREE from 'three';

const PLANE_H = 1.62;
const PLANE_W = PLANE_H * (2 / 3);

export function wantsWebGL() {
  if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return false;
  if (window.matchMedia('(max-width: 720px)').matches) return false;
  try {
    const c = document.createElement('canvas');
    const gl = c.getContext('webgl') || c.getContext('experimental-webgl');
    return !!gl;
  } catch {
    return false;
  }
}

export function createLightTable(host) {
  const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, powerPreference: 'low-power' });
  renderer.setPixelRatio(Math.min(2, window.devicePixelRatio || 1));
  renderer.setClearColor(0x000000, 0);
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.domElement.className = 'au-webgl';
  host.insertBefore(renderer.domElement, host.firstChild);

  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(32, 1, 0.1, 40);
  camera.position.set(0, 0.02, 3.15);

  const amb = new THREE.AmbientLight(0xb8c0cc, 0.55);
  scene.add(amb);
  const key = new THREE.SpotLight(0xfff4e0, 18, 12, Math.PI / 6, 0.55, 1.2);
  key.position.set(-0.4, 2.2, 2.4);
  scene.add(key);
  const fill = new THREE.DirectionalLight(0x6a7a99, 0.35);
  fill.position.set(1.4, 0.2, 1.6);
  scene.add(fill);
  const rim = new THREE.PointLight(0xc1121f, 0.55, 6);
  rim.position.set(1.1, -0.8, 1.2);
  scene.add(rim);

  const geo = new THREE.PlaneGeometry(PLANE_W, PLANE_H);
  const mat = new THREE.MeshStandardMaterial({
    color: 0x1a1a1c,
    roughness: 0.72,
    metalness: 0.04,
  });
  const mesh = new THREE.Mesh(geo, mat);
  scene.add(mesh);

  const tableGeo = new THREE.PlaneGeometry(8, 5);
  const tableMat = new THREE.MeshBasicMaterial({ color: 0x08090c, transparent: true, opacity: 0.0 });
  const table = new THREE.Mesh(tableGeo, tableMat);
  table.position.z = -0.6;
  scene.add(table);

  const loader = new THREE.TextureLoader();
  loader.crossOrigin = 'anonymous';

  let raf = 0;
  let running = false;
  let tiltTarget = 1;
  let tilt = 1;
  let tex = null;
  const _v = new THREE.Vector3();

  function size() {
    const w = Math.max(1, host.clientWidth);
    const h = Math.max(1, host.clientHeight);
    renderer.setSize(w, h, false);
    camera.aspect = w / h;
    camera.updateProjectionMatrix();
  }

  function projectRect() {
    const w = host.clientWidth;
    const h = host.clientHeight;
    if (w < 2 || h < 2) return null;
    mesh.updateWorldMatrix(true, false);
    camera.updateMatrixWorld();
    const corners = [
      [-PLANE_W / 2, PLANE_H / 2],
      [PLANE_W / 2, PLANE_H / 2],
      [PLANE_W / 2, -PLANE_H / 2],
      [-PLANE_W / 2, -PLANE_H / 2],
    ].map(([x, y]) => {
      _v.set(x, y, 0).applyMatrix4(mesh.matrixWorld).project(camera);
      return {
        x: (_v.x * 0.5 + 0.5) * w,
        y: (-_v.y * 0.5 + 0.5) * h,
      };
    });
    const xs = corners.map((c) => c.x);
    const ys = corners.map((c) => c.y);
    const left = Math.min(...xs);
    const top = Math.min(...ys);
    return {
      left,
      top,
      width: Math.max(...xs) - left,
      height: Math.max(...ys) - top,
    };
  }

  function tick(now) {
    if (!running) return;
    const t = now * 0.001;
    tilt += (tiltTarget - tilt) * 0.06;
    mesh.rotation.y = -0.22 * tilt + Math.sin(t * 0.35) * 0.03 * tilt;
    mesh.rotation.x = 0.06 * tilt + Math.cos(t * 0.28) * 0.015 * tilt;
    mesh.position.y = Math.sin(t * 0.6) * 0.012;
    renderer.render(scene, camera);
    raf = requestAnimationFrame(tick);
  }

  function start() {
    if (running) return;
    running = true;
    size();
    raf = requestAnimationFrame(tick);
  }

  function stop() {
    running = false;
    cancelAnimationFrame(raf);
  }

  function setTilt(v) {
    tiltTarget = v;
  }

  function setPoster(url) {
    return new Promise((resolve, reject) => {
      loader.load(
        url,
        (next) => {
          next.colorSpace = THREE.SRGBColorSpace;
          next.anisotropy = 4;
          mat.map = next;
          mat.color.set(0xffffff);
          mat.needsUpdate = true;
          if (tex) tex.dispose();
          tex = next;
          resolve(next);
        },
        undefined,
        reject,
      );
    });
  }

  function dispose() {
    stop();
    if (tex) tex.dispose();
    geo.dispose();
    mat.dispose();
    tableGeo.dispose();
    tableMat.dispose();
    renderer.dispose();
    if (renderer.domElement.parentNode === host) host.removeChild(renderer.domElement);
  }

  const ro = new ResizeObserver(() => size());
  ro.observe(host);

  return { start, stop, size, setTilt, setPoster, projectRect, dispose, renderer, host };
}

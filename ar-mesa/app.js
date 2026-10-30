/* =====================================================================================================================
   RA de mesa · Brazo robótico y Atlas XR
   Un solo sistema de colocación (slam-colocacion.js) para los dos modelos, con:
   - RA real en Meta Quest (passthrough) y Android/Chrome (ARCore) vía WebXR immersive-ar
   - iPhone/iPad: AR Quick Look con el .usdz (ARKit hace la detección de planos, la colocación y la sombra)
   - Simulador de escritorio: mismo flujo y misma retícula sobre una mesa virtual
   ===================================================================================================================== */
import * as THREE from 'three';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { RoomEnvironment } from 'three/addons/environments/RoomEnvironment.js';
import { XREstimatedLight } from 'three/addons/webxr/XREstimatedLight.js';
import { SlamPlacementController, SimulatedSurfaces, AMARILLO } from './slam-colocacion.js';

const DEBUG = new URLSearchParams(location.search).has('debug');
const MODELOS = {
  robot: {
    titulo: 'Brazo robótico', sub: 'UR de 6 ejes · alcance 88 cm',
    glb: '../robot-6-ejes/modelo/Robot6Ejes_web.glb', usdz: '../robot-6-ejes/modelo/Robot6Ejes.usdz',
    huella: 0.09, accion: 'Animar', ayuda: 'Tocá una articulación para ver qué eje es',
  },
  atlas: {
    titulo: 'Atlas XR', sub: 'Globo logístico · Ø 45 cm',
    glb: '../atlas-xr/modelo/AtlasXR_web.glb', usdz: '../atlas-xr/modelo/AtlasXR.usdz',
    huella: 0.118, accion: 'Girar', ayuda: 'Tocá un nodo para ver sus datos · arrastrá el globo para girarlo',
  },
};
const params = new URLSearchParams(location.search);
let modelKey = MODELOS[params.get('modelo')] ? params.get('modelo') : 'atlas';

const UA = navigator.userAgent;
const IS_IOS = /iPad|iPhone|iPod/.test(UA) || (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1);
const IS_QUEST = /OculusBrowser|Quest/.test(UA);

/* ---------------------------------------------------------------------------------------------------------------------
   Render
   --------------------------------------------------------------------------------------------------------------------- */
const canvas = document.getElementById('c');
const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true });
renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
renderer.setSize(innerWidth, innerHeight);
renderer.outputColorSpace = THREE.SRGBColorSpace;
renderer.toneMapping = THREE.NeutralToneMapping;
renderer.shadowMap.enabled = true;
renderer.shadowMap.type = THREE.PCFShadowMap;
renderer.xr.enabled = true;
renderer.xr.setReferenceSpaceType('local');

const scene = new THREE.Scene();
const pmrem = new THREE.PMREMGenerator(renderer);
const roomEnv = pmrem.fromScene(new RoomEnvironment(), 0.04).texture;
scene.environment = roomEnv;
scene.environmentIntensity = 0.9;

const camera = new THREE.PerspectiveCamera(55, innerWidth / innerHeight, 0.01, 60);
camera.position.set(0.1, 1.55, 1.75);
scene.add(camera);
const controls = new OrbitControls(camera, canvas);
controls.target.set(0, 0.9, 0);
controls.enableDamping = true;
controls.maxPolarAngle = Math.PI * 0.49;
controls.minDistance = 0.35;
controls.maxDistance = 4;

const hemi = new THREE.HemisphereLight(0xf3f6fb, 0x8d8072, 0.9);
scene.add(hemi);
// Luz de sombras: cuelga del ancla para que la sombra siempre caiga bajo el objeto
const sun = new THREE.DirectionalLight(0xffffff, 1.6);
sun.castShadow = true;
sun.shadow.mapSize.set(1024, 1024);
sun.shadow.camera.left = sun.shadow.camera.bottom = -0.8;
sun.shadow.camera.right = sun.shadow.camera.top = 0.8;
sun.shadow.camera.near = 0.1;
sun.shadow.camera.far = 4;
sun.shadow.bias = -0.0004;
sun.shadow.normalBias = 0.01;
sun.shadow.radius = 5;
const SUN_DIR = new THREE.Vector3(0.45, 1, 0.35).normalize();

/* ---------- Habitación del simulador ---------- */
const room = new THREE.Group();
room.name = 'Simulador';
scene.add(room);
{
  const floor = new THREE.Mesh(new THREE.PlaneGeometry(12, 12).rotateX(-Math.PI / 2),
    new THREE.MeshStandardMaterial({ color: 0xcfc8bd, roughness: 0.9 }));
  floor.receiveShadow = true;
  room.add(floor);
  const top = new THREE.Mesh(new THREE.BoxGeometry(1.6, 0.04, 0.9), new THREE.MeshStandardMaterial({ color: 0xe9e6e1, roughness: 0.55 }));
  top.position.set(0, 0.73, 0);
  top.receiveShadow = top.castShadow = true;
  room.add(top);
  const legM = new THREE.MeshStandardMaterial({ color: 0x3a3f47, roughness: 0.5, metalness: 0.6 });
  for (const [x, z] of [[-0.74, -0.39], [0.74, -0.39], [-0.74, 0.39], [0.74, 0.39]]) {
    const leg = new THREE.Mesh(new THREE.CylinderGeometry(0.02, 0.02, 0.71, 12), legM);
    leg.position.set(x, 0.355, z);
    leg.castShadow = true;
    room.add(leg);
  }
  const wallM = new THREE.MeshStandardMaterial({ color: 0xeef1f5, roughness: 1 });
  const wall = new THREE.Mesh(new THREE.PlaneGeometry(12, 4), wallM);
  wall.position.set(0, 2, -2.2);
  room.add(wall);
}
const sim = new SimulatedSurfaces();
sim.add('mesa', 0.75, -0.8, 0.8, -0.45, 0.45);
sim.add('piso', 0, -6, 6, -2.2, 6);

/* ---------- Colocación ---------- */
const slam = new SlamPlacementController({ renderer, scene, footprint: MODELOS[modelKey].huella, device: 'escritorio' });
slam.anchorRoot.add(sun, sun.target);
sun.target.position.set(0, 0, 0);
sun.position.copy(SUN_DIR).multiplyScalar(2);
// planos simulados (los mismos de SimulatedSurfaces) para la malla de puntos
slam.planes.setStatic('mesa', [{ x: -0.8, z: -0.45 }, { x: 0.8, z: -0.45 }, { x: 0.8, z: 0.45 }, { x: -0.8, z: 0.45 }],
  new THREE.Matrix4().makeTranslation(0, 0.7505, 0));
for (const e of slam.planes.planes.values()) e.reveal = -1e9;   // se revela al detectarse

// Sombra de contacto (siempre bajo la base, también sin luz direccional)
function blobTexture() {
  const c = document.createElement('canvas');
  c.width = c.height = 128;
  const g = c.getContext('2d');
  const gr = g.createRadialGradient(64, 64, 0, 64, 64, 64);
  gr.addColorStop(0, 'rgba(0,0,0,0.55)');
  gr.addColorStop(0.55, 'rgba(0,0,0,0.25)');
  gr.addColorStop(1, 'rgba(0,0,0,0)');
  g.fillStyle = gr;
  g.fillRect(0, 0, 128, 128);
  const t = new THREE.CanvasTexture(c);
  t.colorSpace = THREE.SRGBColorSpace;
  return t;
}
const blob = new THREE.Mesh(new THREE.PlaneGeometry(1, 1).rotateX(-Math.PI / 2),
  new THREE.MeshBasicMaterial({ map: blobTexture(), transparent: true, depthWrite: false, toneMapped: false }));
blob.position.y = 0.0015;
blob.renderOrder = 1;
slam.anchorRoot.add(blob);

/* ---------------------------------------------------------------------------------------------------------------------
   Modelos
   --------------------------------------------------------------------------------------------------------------------- */
const loader = new GLTFLoader();
const cache = {};
let current = null;   // { key, root, pickables, update(dt), action(), card(hit) }

const ROBOT_JOINTS = [
  { node: 'Shoulder_Joint', key: 'J1', name: 'Base giratoria', info: 'Gira todo el brazo sobre el eje vertical.' },
  { node: 'Upper_Arm', key: 'J2', name: 'Hombro', info: 'Levanta y baja el brazo superior.' },
  { node: 'Elbow_Joint', key: 'J3', name: 'Codo', info: 'Pliega el antebrazo; junto con J2 define el alcance.' },
  { node: 'Wrist_1', key: 'J4', name: 'Muñeca 1', info: 'Inclina la muñeca para orientar la herramienta.' },
  { node: 'Wrist_2', key: 'J5', name: 'Muñeca 2', info: 'Gira la muñeca alrededor de su eje vertical.' },
  { node: 'Wrist_3', key: 'J6', name: 'Brida', info: 'Gira la herramienta (brida ISO 9409, Ø 63 mm).' },
];
const ROBOT_POSES = {
  inicio: [0, -5, 110, -10, -90, 0],
  tomar: [-40, 25, 125, -60, -90, 0],
  dejar: [60, 25, 125, -60, -90, 90],
};
const AXIS_Y = new THREE.Vector3(0, 1, 0);
const _qa = new THREE.Quaternion();

function prepare(gltf) {
  const root = gltf.scene;
  root.traverse((o) => {
    if (!o.isMesh) return;
    if (o.userData.shadow_catcher || o.name === 'ShadowCatcher') {
      o.material = new THREE.ShadowMaterial({ opacity: 0.3, depthWrite: false });
      o.receiveShadow = true;
      o.castShadow = false;
      o.userData.isShadow = true;
      o.renderOrder = 2;
      return;
    }
    o.castShadow = true;
    o.receiveShadow = true;
  });
  return root;
}

function makeRobot(root) {
  const joints = ROBOT_JOINTS.map((j) => ({ ...j, obj: root.getObjectByName(j.node) }));
  for (const j of joints) j.rest = j.obj.quaternion.clone();
  const pickables = [];
  root.traverse((o) => { if (o.isMesh && !o.userData.isShadow) pickables.push(o); });
  let anim = false, t = 0;
  let pose = [...ROBOT_POSES.inicio], from = [...pose], target = pose, blend = 1;
  const seq = ['tomar', 'inicio', 'dejar', 'inicio'];
  let step = 0, wait = 0;
  const apply = () => joints.forEach((j, i) => j.obj.quaternion.copy(j.rest).multiply(_qa.setFromAxisAngle(AXIS_Y, THREE.MathUtils.degToRad(pose[i]))));
  apply();
  let selected = null;
  const glowMat = new Map();
  function highlight(mesh) {
    if (selected) { selected.material = glowMat.get(selected); selected = null; }
    if (!mesh) return;
    glowMat.set(mesh, mesh.material);
    const m = mesh.material.clone();
    m.emissive = AMARILLO.clone();
    m.emissiveIntensity = 0.35;
    mesh.material = m;
    selected = mesh;
  }
  return {
    key: 'robot', root, pickables,
    get animating() { return anim; },
    action() { anim = !anim; return anim; },
    update(dt) {
      t += dt;
      if (!anim && blend >= 1) return;
      if (blend >= 1) {
        wait -= dt;
        if (wait > 0) return;
        from = [...pose];
        target = ROBOT_POSES[seq[step % seq.length]];
        step++;
        blend = 0;
      }
      blend = Math.min(1, blend + dt / 1.6);
      const e = blend < 0.5 ? 4 * blend ** 3 : 1 - (-2 * blend + 2) ** 3 / 2;
      pose = from.map((a, i) => a + (target[i] - a) * e);
      apply();
      if (blend >= 1) wait = 0.45;
    },
    pick(hit) {
      if (!hit) { highlight(null); return null; }
      let o = hit.object, j = null;
      while (o && !j) { j = joints.find((x) => x.obj === o); o = o.parent; }
      highlight(hit.object);
      if (!j) {
        return { mesh: hit.object, anchor: root.getObjectByName('Base_Mesh'), color: '#9aa6b5', title: 'Base fija', kicker: 'Brazo robótico · base',
          lines: ['Placa de montaje atornillada a la mesa (Ø 18 cm). Su centro inferior es el origen (0, 0, 0) del modelo y el punto que se ancla en la superficie.'], foot: 'Base_Mesh · UCX_Base' };
      }
      return { mesh: hit.object, anchor: j.obj, color: '#0a84ff', title: `${j.key} · ${j.name}`, kicker: 'Brazo robótico · articulación',
        lines: [j.info, `Ángulo actual: ${Math.round(pose[joints.indexOf(j)])}°`], foot: `Nodo ${j.node} · gira sobre su eje Z (Y en glTF)` };
    },
  };
}

function makeAtlas(root) {
  const globe = root.getObjectByName('Globe_Sphere');
  const tilt = globe.quaternion.clone();
  const nodes = [];
  const proxyMat = new THREE.MeshBasicMaterial({ visible: false });
  const proxyGeo = new THREE.SphereGeometry(0.014, 10, 8);
  root.traverse((o) => {
    if (o.name?.startsWith('Node_') && o.userData.id) {
      const p = new THREE.Mesh(proxyGeo, proxyMat);
      p.position.y = 0.016;
      p.userData.node = o;
      o.add(p);
      nodes.push({ obj: o, proxy: p });
    }
    if (o.isMesh && o.material?.emissiveMap) o.material.emissiveIntensity = 1.7;
  });
  const globeMesh = globe.isMesh ? globe : globe.children.find((c) => c.isMesh);
  const pickables = [...nodes.map((n) => n.proxy), globeMesh];
  let spin = 0, auto = true, sel = null;
  const fmt = new Intl.NumberFormat('es-UY', { maximumFractionDigits: 2 });
  return {
    key: 'atlas', root, pickables, globe: globeMesh,
    get animating() { return auto; },
    action() { auto = !auto; return auto; },
    get spin() { return spin; },
    set spin(v) { spin = v; },
    dragging: false,
    update(dt) {
      if (auto && !this.dragging && !sel) spin += dt * 0.12;
      globe.quaternion.copy(tilt).multiply(_qa.setFromAxisAngle(AXIS_Y, spin));
      for (const n of nodes) {
        const s = n === sel ? 1.7 + 0.15 * Math.sin(performance.now() / 160) : 1;
        n.obj.scale.setScalar(n.obj.scale.x + (s - n.obj.scale.x) * Math.min(1, dt * 10));
      }
    },
    pick(hit) {
      sel = null;
      if (!hit || !hit.object.userData.node) return null;
      const o = hit.object.userData.node, d = o.userData;
      sel = nodes.find((n) => n.obj === o);
      const lines = [];
      if (d.kind === 'port' && d.teu) lines.push(`${fmt.format(d.teu)} M TEU (${d.year})`);
      if (d.status) lines.push(`Estado: ${d.status}`);
      if (d.info) lines.push(d.info);
      return { mesh: o, anchor: o, color: d.color || '#ffd60a', title: d.name, kicker: `${d.country} · ${d.kind === 'port' ? 'Puerto' : 'Paso estratégico'} · ${d.region_name || ''}`,
        lines, foot: d.src ? `Fuente: ${d.src}` : '' };
    },
  };
}

async function loadModel(key) {
  const M = MODELOS[key];
  setLoading(true, `Cargando ${M.titulo}…`);
  if (!cache[key]) {
    const gltf = await loader.loadAsync(M.glb);
    const root = prepare(gltf);
    cache[key] = key === 'robot' ? makeRobot(root) : makeAtlas(root);
  }
  if (current) slam.anchorRoot.remove(current.root);
  current = cache[key];
  slam.anchorRoot.add(current.root);
  slam.setFootprint(M.huella);
  blob.scale.setScalar(M.huella * 3.2);
  card.hide();
  updateShadowCatchers();
  setLoading(false);
  ui.model(key);
}

/* ---------------------------------------------------------------------------------------------------------------------
   Tarjeta de datos flotante (canvas en el mundo, sirve igual en Quest, Android y escritorio)
   --------------------------------------------------------------------------------------------------------------------- */
function wrap(g, text, maxW) {
  const out = [];
  for (const para of String(text).split('\n')) {
    let line = '';
    for (const w of para.split(' ')) {
      const t = line ? line + ' ' + w : w;
      if (g.measureText(t).width > maxW && line) { out.push(line); line = w; } else line = t;
    }
    out.push(line);
  }
  return out;
}

const card = (() => {
  const W = 1024, H = 640;
  const c = document.createElement('canvas');
  c.width = W; c.height = H;
  const g = c.getContext('2d');
  const tex = new THREE.CanvasTexture(c);
  tex.colorSpace = THREE.SRGBColorSpace;
  tex.anisotropy = 4;
  const mesh = new THREE.Mesh(new THREE.PlaneGeometry(0.32, 0.2), new THREE.MeshBasicMaterial({ map: tex, transparent: true, toneMapped: false, depthWrite: false }));
  mesh.renderOrder = 990;
  const lineGeo = new THREE.BufferGeometry().setFromPoints([new THREE.Vector3(), new THREE.Vector3()]);
  const line = new THREE.Line(lineGeo, new THREE.LineBasicMaterial({ color: 0xffffff, transparent: true, opacity: 0.8, depthTest: false }));
  line.renderOrder = 989;
  const dot = new THREE.Mesh(new THREE.SphereGeometry(0.0035, 12, 8), new THREE.MeshBasicMaterial({ color: 0xffffff, depthTest: false }));
  dot.renderOrder = 989;
  const group = new THREE.Group();
  group.add(mesh, line, dot);
  group.visible = false;
  scene.add(group);
  let info = null, appear = 0;
  const FONT = '-apple-system, BlinkMacSystemFont, "SF Pro Text", "Segoe UI", Roboto, system-ui, sans-serif';

  function draw(d) {
    g.clearRect(0, 0, W, H);
    const r = 44;
    g.beginPath();
    g.roundRect(8, 8, W - 16, H - 16, r);
    g.fillStyle = 'rgba(18, 24, 34, 0.86)';
    g.fill();
    g.lineWidth = 3;
    g.strokeStyle = 'rgba(255,255,255,0.35)';
    g.stroke();
    const grd = g.createLinearGradient(0, 8, 0, 120);
    grd.addColorStop(0, 'rgba(255,255,255,0.16)');
    grd.addColorStop(1, 'rgba(255,255,255,0)');
    g.fillStyle = grd;
    g.beginPath();
    g.roundRect(8, 8, W - 16, 140, [r, r, 0, 0]);
    g.fill();
    g.fillStyle = d.color;
    g.beginPath();
    g.arc(70, 92, 16, 0, Math.PI * 2);
    g.fill();
    g.fillStyle = 'rgba(235,242,250,0.72)';
    g.font = `500 30px ${FONT}`;
    g.fillText(d.kicker, 102, 103);
    g.fillStyle = '#fff';
    g.font = `700 64px ${FONT}`;
    g.fillText(d.title, 52, 182);
    let y = 244;
    d.lines.forEach((t, i) => {
      g.font = i === 0 ? `600 36px ${FONT}` : `400 30px ${FONT}`;
      g.fillStyle = i === 0 ? '#ffd60a' : 'rgba(235,242,250,0.9)';
      for (const l of wrap(g, t, W - 110)) {
        if (y > H - 96) return;
        g.fillText(l, 52, y);
        y += i === 0 ? 50 : 41;
      }
      y += 8;
    });
    if (d.foot) {
      g.font = `400 24px ${FONT}`;
      g.fillStyle = 'rgba(235,242,250,0.55)';
      g.fillText(wrap(g, d.foot, W - 110)[0], 52, H - 50);
    }
    tex.needsUpdate = true;
  }
  const _a = new THREE.Vector3(), _c = new THREE.Vector3(), _cam = new THREE.Vector3();
  return {
    get visible() { return group.visible; },
    show(d) { info = d; draw(d); group.visible = true; appear = 0; },
    hide() { info = null; group.visible = false; },
    update(dt, cam) {
      if (!info || !slam.anchorRoot.visible) { group.visible = false; return; }
      group.visible = true;
      appear = Math.min(1, appear + dt * 5);
      // el ancla visual sigue al nodo (el globo gira); la tarjeta queda arriba del objeto, del lado del usuario
      info.anchor.getWorldPosition(_a);
      cam.getWorldPosition(_cam);
      const base = new THREE.Vector3().setFromMatrixPosition(slam.anchorRoot.matrixWorld);
      const toCam = _cam.clone().sub(base).setY(0).normalize();
      const right = new THREE.Vector3(toCam.z, 0, -toCam.x);   // derecha de quien mira
      // al costado del objeto (a la derecha de quien mira), a media altura y un poco hacia el usuario
      const robot = current?.key === 'robot';
      _c.copy(base).addScaledVector(toCam, 0.06).addScaledVector(right, robot ? 0.62 : 0.43).add(new THREE.Vector3(0, robot ? 0.55 : 0.36, 0));
      mesh.position.copy(_c);
      mesh.lookAt(_cam);
      const s = 0.85 + 0.15 * appear;
      mesh.scale.setScalar(s * THREE.MathUtils.clamp(_cam.distanceTo(_c) / 1.1, 0.7, 2));
      mesh.material.opacity = appear;
      const bottom = _c.clone().add(new THREE.Vector3(0, -0.1 * mesh.scale.y, 0));
      lineGeo.attributes.position.setXYZ(0, _a.x, _a.y, _a.z);
      lineGeo.attributes.position.setXYZ(1, bottom.x, bottom.y, bottom.z);
      lineGeo.attributes.position.needsUpdate = true;
      dot.position.copy(_a);
    },
    mesh,
  };
})();

/* ---------------------------------------------------------------------------------------------------------------------
   Selección y arrastre (mismo código para toque, gatillo, pellizco y mouse)
   --------------------------------------------------------------------------------------------------------------------- */
const raycaster = new THREE.Raycaster();
function pickAt(ray) {
  if (!current || !slam.anchorRoot.visible) return null;
  raycaster.ray.copy(ray);
  slam.anchorRoot.updateMatrixWorld(true);
  const hits = raycaster.intersectObjects(current.pickables, false);
  if (!hits.length) return null;
  return hits.find((h) => h.object.userData.node) || hits[0];
}

function select(ray) {
  if (card.visible && raycaster.ray.copy(ray) && raycaster.intersectObject(card.mesh).length) { card.hide(); current.pick(null); return; }
  const hit = pickAt(ray);
  const d = current.pick(hit);
  if (d) { card.show(d); ui.toast(d.title); } else card.hide();
}

const drag = { on: false, yaw0: 0, spin0: 0, moved: 0, start: 0 };
const rayYaw = (r) => Math.atan2(r.direction.x, r.direction.z);
function dragStart(ray) {
  drag.on = false;
  drag.moved = 0;
  drag.start = performance.now();
  drag.ray0 = ray.clone();
  if (current?.key !== 'atlas' || slam.state !== 'colocado') return false;
  const hit = pickAt(ray);
  if (!hit || hit.object.userData.node) return false;
  drag.on = true;
  drag.yaw0 = rayYaw(ray);
  drag.pitch0 = ray.direction.y;
  drag.spin0 = current.spin;
  current.dragging = true;
  return true;
}
function dragMove(ray) {
  if (drag.ray0) drag.moved = Math.max(drag.moved, ray.direction.angleTo(drag.ray0.direction));
  if (!drag.on) return;
  let d = rayYaw(ray) - drag.yaw0;
  d = Math.atan2(Math.sin(d), Math.cos(d));
  current.spin = drag.spin0 - d * 6;
}
function dragEnd() {
  const tap = drag.moved < 0.03 && performance.now() - drag.start < 600;
  drag.on = false;
  drag.ray0 = null;
  if (current) current.dragging = false;
  return tap;
}

/* ---------------------------------------------------------------------------------------------------------------------
   Escritorio (simulador)
   --------------------------------------------------------------------------------------------------------------------- */
const pointer = new THREE.Vector2(0, 0);
let pointerIn = false;
function pointerRay(ev) {
  const r = canvas.getBoundingClientRect();
  pointer.set(((ev.clientX - r.left) / r.width) * 2 - 1, -((ev.clientY - r.top) / r.height) * 2 + 1);
  raycaster.setFromCamera(pointer, camera);
  return raycaster.ray.clone();
}
canvas.addEventListener('pointermove', (e) => { pointerIn = true; const r = pointerRay(e); dragMove(r); });
canvas.addEventListener('pointerleave', () => { pointerIn = false; });
canvas.addEventListener('pointerdown', (e) => {
  if (renderer.xr.isPresenting) return;
  const r = pointerRay(e);
  if (dragStart(r)) controls.enabled = false;
});
canvas.addEventListener('pointerup', (e) => {
  if (renderer.xr.isPresenting) return;
  const r = pointerRay(e);
  const tap = dragEnd();
  controls.enabled = true;
  if (!tap) return;
  if (slam.state === 'superficie') slam.place(camera.position);
  else if (slam.state === 'colocado') select(r);
});

/* ---------------------------------------------------------------------------------------------------------------------
   WebXR immersive-ar
   --------------------------------------------------------------------------------------------------------------------- */
let xrLight = null, estimating = false;
const worldHud = makeWorldHud();

async function startAR() {
  const overlay = document.getElementById('arui');
  const session = await navigator.xr.requestSession('immersive-ar', {
    requiredFeatures: ['hit-test'],
    optionalFeatures: ['anchors', 'light-estimation', 'dom-overlay', 'plane-detection', 'local-floor'],
    domOverlay: { root: overlay },
  });
  document.body.classList.add('in-ar');
  room.visible = false;
  slam.planes.planes.get('mesa').mesh.visible = false;   // el plano simulado no existe en el mundo real
  scene.background = null;
  controls.enabled = false;
  card.hide();
  if (!xrLight) {
    xrLight = new XREstimatedLight(renderer);
    xrLight.addEventListener('estimationstart', () => {
      estimating = true;
      scene.add(xrLight);
      hemi.visible = false;
      if (xrLight.environment) scene.environment = xrLight.environment;
    });
    xrLight.addEventListener('estimationend', () => {
      estimating = false;
      scene.remove(xrLight);
      hemi.visible = true;
      scene.environment = roomEnv;
    });
  }
  await renderer.xr.setSession(session);
  slam.device = IS_QUEST ? 'quest' : 'telefono';
  await slam.attachSession(session);
  worldHud.group.visible = !session.domOverlayState;
  updateShadowCatchers();
  const rayOf = (frame, src) => {
    const p = frame?.getPose(src.targetRaySpace, renderer.xr.getReferenceSpace());
    if (!p) return null;
    const m = new THREE.Matrix4().fromArray(p.transform.matrix);
    const o = new THREE.Vector3().setFromMatrixPosition(m);
    const d = new THREE.Vector3(0, 0, -1).transformDirection(m);
    return new THREE.Ray(o, d);
  };
  session.addEventListener('selectstart', (e) => {
    const r = rayOf(e.frame, e.inputSource);
    if (r) { dragStart(r); xrDragSrc = e.inputSource; }
  });
  session.addEventListener('selectend', (e) => {
    const r = rayOf(e.frame, e.inputSource);
    xrDragSrc = null;
    const tap = dragEnd();
    if (!tap) return;
    if (slam.state === 'superficie') {
      const head = renderer.xr.getCamera().getWorldPosition(new THREE.Vector3());
      slam.place(head, e.frame);
    } else if (slam.state === 'colocado' && r) select(r);
  });
  session.addEventListener('end', () => {
    document.body.classList.remove('in-ar');
    room.visible = true;
    slam.planes.planes.get('mesa').mesh.visible = true;
    scene.environment = roomEnv;
    hemi.visible = true;
    controls.enabled = true;
    worldHud.group.visible = false;
    slam.device = 'escritorio';
    slam.reset();
    updateShadowCatchers();
  });
  overlay.querySelectorAll('button').forEach((b) => b.addEventListener('beforexrselect', (ev) => ev.preventDefault()));
}
let xrDragSrc = null;
document.getElementById('arReset').addEventListener('click', () => { slam.reset(); card.hide(); });
document.getElementById('arAction').addEventListener('click', (e) => { const on = current.action(); e.currentTarget.setAttribute('aria-pressed', on); });
document.getElementById('arExit').addEventListener('click', () => renderer.xr.getSession()?.end());

/* ---------- HUD en el mundo (Quest: no hay DOM overlay) ---------- */
function makeWorldHud() {
  const c = document.createElement('canvas');
  c.width = 1024; c.height = 220;
  const g = c.getContext('2d');
  const tex = new THREE.CanvasTexture(c);
  tex.colorSpace = THREE.SRGBColorSpace;
  const m = new THREE.Mesh(new THREE.PlaneGeometry(0.30, 0.0645), new THREE.MeshBasicMaterial({ map: tex, transparent: true, depthTest: false, toneMapped: false }));
  m.renderOrder = 1000;
  m.position.set(0, -0.13, -0.62);
  const group = new THREE.Group();
  group.add(m);
  group.visible = false;
  camera.add(group);
  return {
    group,
    set(title, detail) {
      g.clearRect(0, 0, 1024, 220);
      if (!title) { tex.needsUpdate = true; return; }
      g.beginPath();
      g.roundRect(6, 6, 1012, 208, 104);
      g.fillStyle = 'rgba(18,24,34,0.78)';
      g.fill();
      g.strokeStyle = 'rgba(255,255,255,0.3)';
      g.lineWidth = 3;
      g.stroke();
      g.textAlign = 'center';
      g.fillStyle = '#fff';
      g.font = '700 58px -apple-system, "Segoe UI", Roboto, system-ui, sans-serif';
      g.fillText(title, 512, detail ? 98 : 128);
      if (detail) {
        g.fillStyle = 'rgba(235,242,250,0.75)';
        g.font = '400 36px -apple-system, "Segoe UI", Roboto, system-ui, sans-serif';
        g.fillText(detail, 512, 160);
      }
      tex.needsUpdate = true;
    },
  };
}

/* ---------- Mandos del Quest: A = reubicar, B = animar/girar, stick = rotar el objeto ---------- */
const prevBtn = new Map();
function pollGamepads(dt) {
  const s = renderer.xr.getSession();
  if (!s) return;
  for (const src of s.inputSources) {
    const gp = src.gamepad;
    if (!gp) continue;
    const prev = prevBtn.get(src) || [];
    const now = gp.buttons.map((b) => b.pressed);
    if (now[4] && !prev[4]) { slam.reset(); card.hide(); }
    if (now[5] && !prev[5] && current) current.action();
    prevBtn.set(src, now);
    const x = gp.axes[2] ?? 0;
    if (Math.abs(x) > 0.2 && slam.state === 'colocado') slam.rotateYaw(-x * dt * 1.6);
  }
}

/* ---------------------------------------------------------------------------------------------------------------------
   Interfaz
   --------------------------------------------------------------------------------------------------------------------- */
const $ = (id) => document.getElementById(id);
const ui = {
  hud(title, detail) {
    for (const el of [$('hud'), $('arHud')]) {
      el.querySelector('b').textContent = title;
      el.querySelector('span').textContent = detail || '';
      el.classList.toggle('found', slam.state === 'superficie');
      el.hidden = !title;
    }
    worldHud.set(title, detail);
  },
  model(key) {
    const M = MODELOS[key];
    document.querySelectorAll('#seg button').forEach((b) => b.setAttribute('aria-pressed', b.dataset.k === key));
    $('ql').href = M.usdz;
    $('modelSub').textContent = M.sub;
    $('arAction').querySelector('span').textContent = M.accion;
    $('simAction').querySelector('span').textContent = M.accion;
    const u = new URL(location.href);
    u.searchParams.set('modelo', key);
    history.replaceState(null, '', u);
  },
  toast(t) {
    const el = $('toast');
    el.textContent = t;
    el.classList.add('on');
    clearTimeout(ui._t);
    ui._t = setTimeout(() => el.classList.remove('on'), 1800);
  },
};
function setLoading(on, text) {
  $('loading').style.opacity = on ? 1 : 0;
  if (text) $('loading').querySelector('.glass').textContent = text;
}
slam.addEventListener('hud', (e) => {
  let detail = e.detail;
  if (e.key === 'colocado') detail = MODELOS[current?.key || modelKey].ayuda;
  ui.hud(e.title, detail);
});
slam.addEventListener('placed', (e) => {
  ui.toast('Anclado');
  navigator.vibrate?.(12);
  $('noAR').hidden = true;
  if (!renderer.xr.isPresenting) {   // simulador: centrar la vista en el objeto
    const p = new THREE.Vector3().setFromMatrixPosition(e.matrix);
    focus = p.add(new THREE.Vector3(0, current?.key === 'robot' ? 0.45 : 0.3, 0));
  }
});
let focus = null;

function updateShadowCatchers() {
  const ar = renderer.xr.isPresenting;
  for (const c of Object.values(cache)) c.root.traverse((o) => { if (o.userData.isShadow) o.visible = ar; });
}

document.querySelectorAll('#seg button').forEach((b) => b.addEventListener('click', () => {
  if (b.dataset.k === current?.key) return;
  modelKey = b.dataset.k;
  slam.reset();
  loadModel(modelKey);
}));
$('simReset').addEventListener('click', () => { slam.reset(); card.hide(); });
$('simAction').addEventListener('click', (e) => { const on = current?.action(); e.currentTarget.setAttribute('aria-pressed', !!on); });
$('btnAR').addEventListener('click', () => startAR().catch((err) => { console.error(err); ui.toast('No se pudo iniciar la realidad aumentada'); }));
$('btnManual').addEventListener('click', () => $('manual').showModal());
$('manual').querySelector('.close').addEventListener('click', () => $('manual').close());

if (navigator.xr?.isSessionSupported) {
  navigator.xr.isSessionSupported('immersive-ar').then((ok) => { $('btnAR').hidden = !ok; $('noAR').hidden = ok || IS_IOS; }).catch(() => {});
} else { $('noAR').hidden = IS_IOS; }
// iPhone/iPad: Quick Look (ARKit) con el .usdz
if (IS_IOS || document.createElement('a').relList.supports?.('ar')) $('ql').hidden = false;

addEventListener('resize', () => {
  camera.aspect = innerWidth / innerHeight;
  camera.updateProjectionMatrix();
  renderer.setSize(innerWidth, innerHeight);
});

/* ---------------------------------------------------------------------------------------------------------------------
   Bucle
   --------------------------------------------------------------------------------------------------------------------- */
const clock = new THREE.Timer();
let paused = false;
function tick(time, frame) {
  clock.update(time);
  const dt = Math.min(clock.getDelta(), 0.05);
  if (renderer.xr.isPresenting && frame) {
    const xrCam = renderer.xr.getCamera();
    slam.updateXR(dt, frame, xrCam);
    pollGamepads(dt);
    if (xrDragSrc) {
      const p = frame.getPose(xrDragSrc.targetRaySpace, renderer.xr.getReferenceSpace());
      if (p) {
        const m = new THREE.Matrix4().fromArray(p.transform.matrix);
        dragMove(new THREE.Ray(new THREE.Vector3().setFromMatrixPosition(m), new THREE.Vector3(0, 0, -1).transformDirection(m)));
      }
    }
    // la luz estimada orienta la sombra
    if (estimating && xrLight.directionalLight.intensity > 0) {
      sun.position.copy(xrLight.directionalLight.position).normalize();
      if (sun.position.y < 0.35) sun.position.y = 0.35;
      sun.position.normalize().multiplyScalar(2);
      sun.intensity = 0.0001;     // solo proyecta sombra: la iluminación la da la luz estimada
    } else { sun.position.copy(SUN_DIR).multiplyScalar(2); sun.intensity = 1.6; }
    card.update(dt, xrCam);
  } else {
    if (focus) { controls.target.lerp(focus, 1 - Math.exp(-dt * 4)); if (controls.target.distanceTo(focus) < 0.002) focus = null; }
    controls.update();
    // "SLAM" de escritorio: rayo del puntero (o del centro de la vista si el puntero no está sobre el lienzo)
    if (!pointerIn) raycaster.setFromCamera(new THREE.Vector2(0, 0), camera);
    else raycaster.setFromCamera(pointer, camera);
    const hit = slam.state === 'colocado' ? null : sim.hit(raycaster.ray, dt);
    for (const s of sim.detected()) { const e = slam.planes.planes.get(s.name); if (e && e.reveal < 0) e.reveal = 0; }
    slam.updateSimulated(dt, camera, hit);
    sun.position.copy(SUN_DIR).multiplyScalar(2);
    sun.intensity = 1.6;
    card.update(dt, camera);
  }
  current?.update(dt);
  if (!paused) renderer.render(scene, camera);
}
renderer.setAnimationLoop(tick);

if (DEBUG) window.__ar = { THREE, renderer, scene, camera, slam, sim, card, get current() { return current; }, select, dragStart, dragMove, dragEnd,
  loadModel, startAR, pause: (v = true) => { paused = v; }, renderOnce: () => renderer.render(scene, camera) };

loadModel(modelKey).catch((e) => { console.error(e); setLoading(true, 'No se pudo cargar el modelo'); });

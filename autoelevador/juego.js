// Autoelevador VR · Uruguay Logística
// Conducción de un autoelevador eléctrico en un centro de distribución, en la computadora, el celular o el Meta Quest.
// Física simple de vehículo con dirección trasera, mástil de dos etapas con carro y desplazador lateral, pallets que se
// toman con las horquillas y se apoyan en el piso o en la estantería, slalom con conos y tareas de logística.
import * as THREE from 'three';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { RoomEnvironment } from 'three/addons/environments/RoomEnvironment.js';
import { XRControllerModelFactory } from 'three/addons/webxr/XRControllerModelFactory.js';

/* =====================================================================
   Constantes (metros, segundos). Marco three.js: Y arriba; el autoelevador mira hacia +Z de su raíz.
   ===================================================================== */
const DEBUG = new URLSearchParams(location.search).has('debug');
const L = 1.45;                     // distancia entre ejes
const V_MAX = 3.0, V_MAX_R = 2.0;   // m/s (≈ 11 km/h adelante, 7 km/h atrás)
const ACCEL = 1.5, BRAKE = 4.5, ROLL = 0.5;
const WHEEL_TURNS = 2.5 * Math.PI;  // ± giro del volante (rad) a tope
const STEER_MAX = 1.30;             // ± giro de las ruedas traseras (rad, ≈ 75°)
const LIFT_SPEED = 0.42, LOWER_SPEED = 0.50;
const CARR_MAX = 1.55, INNER_MAX = 1.85;  // elevación libre del carro + carrera del mástil interior
const TILT_FWD = THREE.MathUtils.degToRad(5), TILT_BACK = THREE.MathUtils.degToRad(-8), TILT_SPEED = THREE.MathUtils.degToRad(4);
const SIDE_MAX = 0.10, SIDE_SPEED = 0.10;
const FORK_X = 0.19;
// Pala de la horquilla en el marco local de cada Fork_* (three): talón, punta, tope y piso de la pala
const BLADE = { heelZ: 0.08, tipZ: 1.23, top: -0.565, bottom: -0.605, halfW: 0.05 };
// Pallet EUR en su marco local (three): ancho X 0,80, largo Z 1,20; huecos entre tacos
const PAL = { hw: 0.40, hl: 0.60, deck: 0.10, top: 0.144, laneMin: 0.0725, laneMax: 0.30 };
// Estantería (desde el script de Blender): 4 módulos, puntales cada 2,79 m, niveles 1,50 y 3,00 m, fondo z = -8,45
const RACK = { z: -8.45, depth: 1.10, bays: [-4.185, -1.395, 1.395, 4.185], bay: 2.70, posts: [-5.58, -2.79, 0, 2.79, 5.58],
  levels: [1.512, 3.012], beamH: 0.12, top: 3.95 };
const ROOM = { hx: 14, hz: 10 };
const EYE = new THREE.Vector3(0, 1.80, -0.98);   // ojos del conductor sentado (local de la raíz)
// Cuerpo del autoelevador (local de la raíz) para choques: chasis + mástil + techo
const BODY = { x0: -0.62, x1: 0.62, z0: -2.06, z1: 0.62, y1: 2.30 };

/* =====================================================================
   Render, escena y luz
   ===================================================================== */
const canvas = document.getElementById('c');
const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, powerPreference: 'high-performance' });
renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
renderer.setSize(innerWidth, innerHeight);
renderer.outputColorSpace = THREE.SRGBColorSpace;
renderer.toneMapping = THREE.ACESFilmicToneMapping;
renderer.toneMappingExposure = 1.0;
renderer.xr.enabled = true;
renderer.xr.setReferenceSpaceType('local-floor');
renderer.xr.setFoveation(1);

const scene = new THREE.Scene();
scene.background = new THREE.Color(0xdfe5ec);
const pmrem = new THREE.PMREMGenerator(renderer);
scene.environment = pmrem.fromScene(new RoomEnvironment(), 0.04).texture;
scene.environmentIntensity = 0.55;
scene.add(new THREE.HemisphereLight(0xffffff, 0x8a8f96, 1.15));
const sun = new THREE.DirectionalLight(0xffffff, 1.4);
sun.position.set(-6, 12, 4);
scene.add(sun);

const camera = new THREE.PerspectiveCamera(60, innerWidth / innerHeight, 0.05, 120);
const orbit = new OrbitControls(camera, canvas);
orbit.enableDamping = true;
orbit.maxPolarAngle = 1.45;
orbit.minDistance = 2.5;
orbit.maxDistance = 18;

/* =====================================================================
   Carga de los modelos
   ===================================================================== */
const loader = new GLTFLoader();
const [gEnv, gFk] = await Promise.all([loader.loadAsync('modelo/Deposito_web.glb'), loader.loadAsync('modelo/Autoelevador_web.glb')]);
scene.add(gEnv.scene);
const fk = gFk.scene.getObjectByName('Forklift_Root');
scene.add(fk);
document.getElementById('loading').style.opacity = 0;

const N = (name) => fk.getObjectByName(name);
const parts = {
  outer: N('Mast_Outer_Stage'), inner: N('Mast_Inner_Stage'), carriage: N('Fork_Carriage'),
  forkL: N('Fork_Left'), forkR: N('Fork_Right'), wheel: N('Steering_Wheel'), knob: N('Spinner_Knob'),
  levLift: N('Lever_Lift'), levTilt: N('Lever_Tilt'), levSide: N('Lever_Sideshift'), accel: N('Pedal_Accel'), brake: N('Pedal_Brake'),
  shuttle: N('Shuttle_Switch'), key: N('Key_Ignition'), estop: N('Emergency_Stop'),
  knL: N('Steer_Knuckle_Left'), knR: N('Steer_Knuckle_Right'),
  wFL: N('Wheel_Front_Left'), wFR: N('Wheel_Front_Right'), wRL: N('Wheel_Rear_Left'), wRR: N('Wheel_Rear_Right'),
  mirrors: [N('Mirror_Left'), N('Mirror_Right'), N('Mirror_Center')], chassis: N('Chassis'),
};
// Pose de reposo de cada pieza (para aplicar los movimientos como desplazamientos relativos)
const rest = new Map();
for (const o of Object.values(parts).flat()) if (o) rest.set(o, { p: o.position.clone(), q: o.quaternion.clone() });
const AX = { x: new THREE.Vector3(1, 0, 0), y: new THREE.Vector3(0, 1, 0), z: new THREE.Vector3(0, 0, 1) };
const _q = new THREE.Quaternion();
function rotLocal(o, axis, ang) { const r = rest.get(o); o.quaternion.copy(r.q).multiply(_q.setFromAxisAngle(AX[axis], ang)); }
function moveLocal(o, dx, dy, dz) { const r = rest.get(o); o.position.set(r.p.x + dx, r.p.y + dy, r.p.z + dz); }

/* ---------- objetos de juego del depósito ---------- */
const E = (name) => gEnv.scene.getObjectByName(name);
const world = { pallets: [], cones: [], zones: {}, slots: [] };
gEnv.scene.traverse((o) => {
  const u = o.userData || {};
  if (u.pallet) world.pallets.push({ node: o, carga: u.carga || null, desc: u.descripcion || 'Pallet vacío', kg: u.masa_kg || 25 });
  if (u.cono) world.cones.push({ node: o, home: o.position.clone(), down: false, t: 0, dir: new THREE.Vector3() });
  if (u.zona) world.zones[u.zona] = o;
  if (u.ranura) world.slots.push({ node: o, nivel: u.nivel });
});
gEnv.scene.updateMatrixWorld(true);
for (const p of world.pallets) {
  // altura de la carga (para choques y apilado): caja que envuelve pallet + carga en su marco local
  const box = new THREE.Box3().setFromObject(p.node);
  p.height = box.max.y - box.min.y;
  p.node.userData.home = p.node.matrixWorld.clone();
}
const spawn = E('Spawn_Forklift');

/* ---------- espejos: cámaras traseras a textura (render-to-texture) ---------- */
const mirrorCams = parts.mirrors.map((m, i) => {
  const rt = new THREE.WebGLRenderTarget(i === 2 ? 384 : 256, i === 2 ? 128 : 170, { samples: 0 });
  const cam = new THREE.PerspectiveCamera(i === 2 ? 70 : 42, rt.width / rt.height, 0.1, 60);
  fk.add(cam);
  const tex = rt.texture;
  tex.colorSpace = THREE.SRGBColorSpace;
  tex.wrapS = THREE.RepeatWrapping;
  tex.repeat.x = -1;               // imagen espejada
  tex.offset.x = 1;
  m.material = new THREE.MeshBasicMaterial({ map: tex, toneMapped: false });
  // cada cámara mira hacia atrás desde su espejo (izquierdo y derecho un poco hacia afuera)
  const pos = new THREE.Vector3();
  m.getWorldPosition(pos);
  fk.worldToLocal(pos);
  cam.position.copy(pos).add(new THREE.Vector3(i === 0 ? 0.05 : i === 1 ? -0.05 : 0, 0.02, 0));
  const yaw = i === 0 ? Math.PI - 0.12 : i === 1 ? Math.PI + 0.12 : Math.PI;
  cam.rotation.set(i === 2 ? -0.18 : -0.08, yaw, 0, 'YXZ');
  return { rt, cam };
});

/* ---------- pantalla del tablero y visera con la tarea ---------- */
function canvasPanel(w, h) {
  const c = document.createElement('canvas');
  c.width = w; c.height = h;
  const t = new THREE.CanvasTexture(c);
  t.colorSpace = THREE.SRGBColorSpace;
  t.anisotropy = 4;
  return { c, g: c.getContext('2d'), t };
}
const dash = canvasPanel(512, 224);
const screenMesh = (() => { let m = null; parts.chassis.traverse((o) => { if (o.isMesh) { const arr = Array.isArray(o.material) ? o.material : [o.material]; arr.forEach((mt, k) => { if (mt.name === 'M_Dash_Screen') { m = { mesh: o, k }; } }); } }); return m; })();
if (screenMesh) {
  const mat = new THREE.MeshBasicMaterial({ map: dash.t, toneMapped: false });
  if (Array.isArray(screenMesh.mesh.material)) screenMesh.mesh.material[screenMesh.k] = mat; else screenMesh.mesh.material = mat;
}
const visor = canvasPanel(1024, 220);
const visorMesh = new THREE.Mesh(new THREE.PlaneGeometry(0.62, 0.133), new THREE.MeshBasicMaterial({ map: visor.t, transparent: true, toneMapped: false }));
visorMesh.position.set(0, 2.0, 0.06);
visorMesh.rotation.set(0.25, Math.PI, 0);   // mira al conductor (hacia -Z de la raíz) y un poco hacia abajo
visorMesh.visible = false;
fk.add(visorMesh);

/* ---------- marcadores de objetivo ---------- */
function marker(color) {
  const g = new THREE.Group();
  const ring = new THREE.Mesh(new THREE.TorusGeometry(0.75, 0.035, 8, 48), new THREE.MeshBasicMaterial({ color, transparent: true, opacity: 0.85 }));
  ring.rotation.x = Math.PI / 2;
  const arrow = new THREE.Mesh(new THREE.ConeGeometry(0.16, 0.34, 20), new THREE.MeshBasicMaterial({ color }));
  arrow.rotation.x = Math.PI;
  arrow.position.y = 1.9;
  g.add(ring, arrow);
  g.userData.arrow = arrow;
  g.visible = false;
  scene.add(g);
  return g;
}
const markPick = marker(0x0a84ff), markDrop = marker(0x34c759);

/* ---------- sombra difusa bajo el autoelevador ---------- */
const blob = (() => {
  const c = document.createElement('canvas'); c.width = c.height = 128;
  const g = c.getContext('2d'); const gr = g.createRadialGradient(64, 64, 8, 64, 64, 64);
  gr.addColorStop(0, 'rgba(0,0,0,.55)'); gr.addColorStop(1, 'rgba(0,0,0,0)'); g.fillStyle = gr; g.fillRect(0, 0, 128, 128);
  const m = new THREE.Mesh(new THREE.PlaneGeometry(1.7, 3.0), new THREE.MeshBasicMaterial({ map: new THREE.CanvasTexture(c), transparent: true, depthWrite: false }));
  m.rotation.x = -Math.PI / 2; m.position.set(0, 0.006, -0.75); fk.add(m); return m;
})();

/* =====================================================================
   Estado del vehículo
   ===================================================================== */
const S = {
  pos: new THREE.Vector3(), yaw: 0, v: 0, wheel: 0, steer: 0,
  carr: 0, inner: 0, tilt: 0, side: 0,
  shuttle: 'N', key: false, estop: false, battery: 100,
  accel: 0, brake: 0, lever: { lift: 0, tilt: 0, side: 0 },
  carried: null, hits: 0, spin: 0,
};
function resetVehicle() {
  spawn.getWorldPosition(S.pos);
  const q = new THREE.Quaternion(); spawn.getWorldQuaternion(q);
  S.yaw = new THREE.Euler().setFromQuaternion(q, 'YXZ').y;
  Object.assign(S, { v: 0, wheel: 0, steer: 0, carr: 0, inner: 0, tilt: 0, side: 0, shuttle: 'N', key: false, estop: false });
  if (S.carried) dropPallet(true);
  applyPose();
}

/* ---------- geometría auxiliar (choques en planta + altura) ---------- */
// OBB en planta: centro (x,z), semiejes (hx,hz), ángulo yaw (rotación sobre Y) y rango de altura
function obb(cx, cz, hx, hz, yaw, y0, y1) { return { cx, cz, hx, hz, c: Math.cos(yaw), s: Math.sin(yaw), y0, y1 }; }
function obbAxes(o) { return [[o.c, -o.s], [o.s, o.c]]; }   // ejes X y Z locales en el plano XZ del mundo
function overlap(a, b) {
  if (a.y1 <= b.y0 || b.y1 <= a.y0) return false;
  const dx = b.cx - a.cx, dz = b.cz - a.cz;
  for (const [ax, az] of [...obbAxes(a), ...obbAxes(b)]) {
    const proj = (o) => { const [ux, uz] = obbAxes(o)[0], [vx, vz] = obbAxes(o)[1]; return o.hx * Math.abs(ux * ax + uz * az) + o.hz * Math.abs(vx * ax + vz * az); };
    if (Math.abs(dx * ax + dz * az) > proj(a) + proj(b)) return false;
  }
  return true;
}
// obstáculos fijos: paredes (como franjas), puntales y largueros de la estantería
const STATIC = [];
STATIC.push(obb(0, -ROOM.hz - 0.5, ROOM.hx + 1, 0.5, 0, -1, 9), obb(0, ROOM.hz + 0.5, ROOM.hx + 1, 0.5, 0, -1, 9),
  obb(-ROOM.hx - 0.5, 0, 0.5, ROOM.hz + 1, 0, -1, 9), obb(ROOM.hx + 0.5, 0, 0.5, ROOM.hz + 1, 0, -1, 9));
for (const x of RACK.posts) STATIC.push(obb(x, RACK.z, 0.06, RACK.depth / 2 + 0.04, 0, 0, RACK.top));
for (const xc of RACK.bays) for (const lv of RACK.levels) {
  for (const dz of [-RACK.depth / 2, RACK.depth / 2]) STATIC.push(obb(xc, RACK.z + dz, RACK.bay / 2, 0.03, 0, lv - 0.012 - RACK.beamH, lv - 0.012));
}
STATIC.push(obb(-12.4, -6.5, 0.6, 0.4, 0, 0, 0.45));   // pila de pallets vacíos (z = -y de Blender)

/* ---------- pose del vehículo en la escena ---------- */
function applyPose() {
  fk.position.copy(S.pos);
  fk.rotation.set(0, S.yaw, 0);
  rotLocal(parts.outer, 'x', S.tilt);
  moveLocal(parts.inner, 0, S.inner, 0);
  moveLocal(parts.carriage, S.side, S.carr, 0);
  rotLocal(parts.wheel, 'y', S.wheel);
  rotLocal(parts.knob, 'y', -S.wheel);
  rotLocal(parts.knL, 'y', -S.steer); rotLocal(parts.knR, 'y', -S.steer);
  for (const w of [parts.wFL, parts.wFR]) rotLocal(w, 'x', S.spin / 0.28);
  for (const w of [parts.wRL, parts.wRR]) rotLocal(w, 'x', S.spin / 0.23);
  rotLocal(parts.levLift, 'x', -S.lever.lift * 0.35);
  rotLocal(parts.levTilt, 'x', S.lever.tilt * 0.35);
  rotLocal(parts.levSide, 'x', S.lever.side * 0.35);
  rotLocal(parts.accel, 'x', S.accel * 0.25);
  rotLocal(parts.brake, 'x', S.brake * 0.25);
  rotLocal(parts.shuttle, 'x', S.shuttle === 'F' ? 0.3 : S.shuttle === 'R' ? -0.3 : 0);
  rotLocal(parts.key, 'y', S.key ? 1.1 : 0);
  moveLocal(parts.estop, 0, S.estop ? -0.012 : 0, 0);
  fk.updateMatrixWorld(true);
}

// Cajas de choque del autoelevador en una pose dada (cuerpo, horquillas y la carga que lleva)
const _v = new THREE.Vector3(), _w = new THREE.Vector3();
function forkWorld(fork) {
  // centro, semiejes y altura de la pala en el mundo
  _v.set(0, (BLADE.top + BLADE.bottom) / 2, (BLADE.heelZ + BLADE.tipZ) / 2);
  fork.localToWorld(_v);
  return { c: _v.clone(), y0: _v.y - 0.02, y1: _v.y + 0.02 };
}
function shapes() {
  const s = [];
  const c = Math.cos(S.yaw), sn = Math.sin(S.yaw);
  const bx = (BODY.x0 + BODY.x1) / 2, bz = (BODY.z0 + BODY.z1) / 2;
  s.push({ kind: 'cuerpo', o: obb(S.pos.x + bx * c + bz * sn, S.pos.z - bx * sn + bz * c, (BODY.x1 - BODY.x0) / 2, (BODY.z1 - BODY.z0) / 2, S.yaw, 0.05, BODY.y1) });
  for (const f of [parts.forkL, parts.forkR]) {
    const w = forkWorld(f);
    s.push({ kind: 'horquilla', o: obb(w.c.x, w.c.z, BLADE.halfW, (BLADE.tipZ - BLADE.heelZ) / 2, S.yaw, w.y0, w.y1) });
  }
  if (S.carried) {
    const p = S.carried; const m = p.node.matrixWorld;
    _v.setFromMatrixPosition(m);
    const yaw = Math.atan2(m.elements[8], m.elements[10]);
    s.push({ kind: 'carga', o: obb(_v.x, _v.z, PAL.hw, PAL.hl, yaw, _v.y + 0.01, _v.y + p.height) });
  }
  return s;
}
function palletBox(p) {
  const m = p.node.matrixWorld;
  _w.setFromMatrixPosition(m);
  const yaw = Math.atan2(m.elements[8], m.elements[10]);
  return obb(_w.x, _w.z, PAL.hw, PAL.hl, yaw, _w.y, _w.y + p.height);
}
// ¿la horquilla está dentro de un hueco del pallet? (en planta y en altura)
function forkInPocket(fork, p) {
  const inv = p.node.matrixWorld.clone().invert();
  const heel = fork.localToWorld(new THREE.Vector3(0, BLADE.top, BLADE.heelZ)).applyMatrix4(inv);
  const tip = fork.localToWorld(new THREE.Vector3(0, BLADE.top, BLADE.tipZ)).applyMatrix4(inv);
  const ax = Math.abs((heel.x + tip.x) / 2);
  const lane = ax - BLADE.halfW >= PAL.laneMin - 0.01 && ax + BLADE.halfW <= PAL.laneMax + 0.01;
  const along = Math.abs(heel.z - tip.z) > 0.5 && Math.abs(heel.x - tip.x) < 0.2;
  const top = Math.max(heel.y, tip.y), bottom = top - 0.04;
  const height = bottom >= -0.02 && top <= PAL.deck + 0.03;
  return { lane, along, height, top, depth: Math.min(Math.max(-heel.z, -tip.z), PAL.hl) - Math.max(Math.min(-heel.z, -tip.z), -PAL.hl) };
}

function collides(sh) {
  for (const s of sh) {
    for (const o of STATIC) if (overlap(s.o, o)) return { what: 'estructura', s };
    for (const p of world.pallets) {
      if (p === S.carried) continue;
      const b = palletBox(p);
      if (!overlap(s.o, b)) continue;
      if (s.kind === 'horquilla') {
        const f = s === sh[1] ? parts.forkL : parts.forkR;
        const k = forkInPocket(f, p);
        if (k.lane && k.along && k.height) continue;   // entra por el hueco: no choca
      }
      return { what: 'pallet', s, p };
    }
  }
  return null;
}

/* =====================================================================
   Pallets: tomar y apoyar
   ===================================================================== */
const _m = new THREE.Matrix4();
function supportUnder(x, z, bottomY) {
  // apoyo bajo el centro del pallet: piso o nivel de la estantería
  let y = 0;
  if (Math.abs(z - RACK.z) < RACK.depth / 2 + 0.05) {
    for (const xc of RACK.bays) if (Math.abs(x - xc) < RACK.bay / 2 - 0.30) for (const lv of RACK.levels) if (lv <= bottomY + 0.05) y = Math.max(y, lv);
  }
  return y;
}
function tryPick() {
  if (S.carried) return;
  for (const p of world.pallets) {
    const a = forkInPocket(parts.forkL, p), b = forkInPocket(parts.forkR, p);
    if (!(a.lane && b.lane && a.along && b.along && a.depth > 0.75 && b.depth > 0.75)) continue;
    if (Math.min(a.top, b.top) >= PAL.deck) {           // las palas tocan la cara inferior del tablero
      S.carried = p;
      p.lifted = false;
      parts.carriage.attach(p.node);
      say(`Tomaste: ${p.desc}`);
      haptic(0.3, 60);
      return;
    }
  }
}
function dropPallet(force) {
  const p = S.carried;
  if (!p) return;
  scene.attach(p.node);
  const e = new THREE.Euler().setFromQuaternion(p.node.quaternion, 'YXZ');
  p.node.rotation.set(0, e.y, 0);
  const sup = supportUnder(p.node.position.x, p.node.position.z, p.node.position.y);
  if (force) p.node.position.y = sup;
  S.carried = null;
  p.node.updateMatrixWorld(true);
  checkTask();
}
function updateCarried() {
  const p = S.carried;
  if (!p) return;
  p.node.updateMatrixWorld(true);
  _v.setFromMatrixPosition(p.node.matrixWorld);
  const sup = supportUnder(_v.x, _v.z, _v.y);
  if (!p.lifted) { if (_v.y > sup + 0.03) p.lifted = true; return; }   // recién tomado: todavía no despegó
  if (_v.y <= sup + 0.004) {              // el pallet llegó a su apoyo: queda ahí y las horquillas siguen bajando libres
    p.node.position.y += sup - _v.y;
    dropPallet(false);
    say('Pallet apoyado');
  }
}

/* =====================================================================
   Tareas del entrenamiento
   ===================================================================== */
const byCargo = (k) => world.pallets.find((p) => p.carga === k && !isOnRack(p));
function isOnRack(p) { _v.setFromMatrixPosition(p.node.matrixWorld); return _v.y > 1.0; }
function inZone(p, z) {
  const zn = world.zones[z]; if (!zn) return false;
  _v.setFromMatrixPosition(p.node.matrixWorld); _w.setFromMatrixPosition(zn.matrixWorld);
  return Math.abs(_v.x - _w.x) < 0.95 && Math.abs(_v.z - _w.z) < 1.15 && _v.y < 0.05;
}
function onLevel(p, nivel) {
  _v.setFromMatrixPosition(p.node.matrixWorld);
  const y = nivel === 'medio' ? RACK.levels[0] : RACK.levels[1];
  return Math.abs(_v.y - y) < 0.03 && Math.abs(_v.z - RACK.z) < 0.4;
}
const TASKS = [
  { id: 'arranque', titulo: 'Arranque seguro', texto: 'Girá la llave (B o K) y poné el inversor en Adelante (A o F). Revisá que la parada de emergencia esté liberada.',
    ok: () => S.key && !S.estop && S.shuttle === 'F' },
  { id: 'slalom', titulo: 'Slalom entre conos', texto: 'Pasá los 5 conos en zigzag, alternando de lado, sin tocarlos. El tiempo corre desde el primer cono.',
    ok: () => slalom.done },
  { id: 'retiro', titulo: 'Retiro de lácteos', texto: 'Tomá el pallet de LÁCTEOS (aro azul) por los huecos y dejalo apoyado en la ZONA A (aro verde).',
    carga: 'lacteos', destino: 'A', ok() { const p = taskPallet(this); return p && p !== S.carried && inZone(p, 'A'); } },
  { id: 'medio', titulo: 'Estantería · nivel medio', texto: 'Llevá los TAMBORES DE COMBUSTIBLE al nivel medio (1,50 m) de un módulo libre. Subí las horquillas antes de entrar.',
    carga: 'combustible', nivel: 'medio', ok() { const p = taskPallet(this); return p && p !== S.carried && onLevel(p, 'medio'); } },
  { id: 'alto', titulo: 'Estantería · nivel alto', texto: 'Ubicá el TRANSFORMADOR en el nivel alto (3,00 m). Inclinación hacia atrás mientras subís, y despacio.',
    carga: 'transformador', nivel: 'alto', ok() { const p = taskPallet(this); return p && p !== S.carried && onLevel(p, 'alto'); } },
  { id: 'export', titulo: 'Carne de exportación', texto: 'Llevá la CARNE VACUNA DE EXPORTACIÓN a la ZONA C, junto al portón del muelle.',
    carga: 'carne', destino: 'C', ok() { const p = taskPallet(this); return p && p !== S.carried && inZone(p, 'C'); } },
];
for (const p of world.pallets) { _v.setFromMatrixPosition(p.node.matrixWorld); p.node.userData.inicialEnRack = _v.y > 1.0 || Math.abs(_v.z - RACK.z) < 1; }
let taskIdx = 0, tStart = performance.now(), tTask = performance.now(), finished = false;
const slalom = { next: 0, side: 0, errors: 0, done: false, t0: 0 };
function taskPallet(t) { return world.pallets.find((p) => p.carga === t.carga && !p.node.userData.inicialEnRack); }
function checkTask() {
  if (finished) return;
  const t = TASKS[taskIdx];
  if (t.ok.call(t)) {
    const secs = Math.round((performance.now() - tTask) / 1000);
    say(`✓ ${t.titulo} · ${secs} s`);
    haptic(0.6, 120);
    taskIdx++;
    tTask = performance.now();
    if (taskIdx >= TASKS.length) { finished = true; taskIdx = TASKS.length - 1; say(`¡Entrenamiento completo! ${fmtTime((performance.now() - tStart) / 1000)} · ${S.hits} choques · ${slalom.errors} conos`); }
    renderTask();
  }
}
function updateSlalom() {
  if (slalom.done || TASKS[taskIdx].id !== 'slalom') return;
  const cones = world.cones;
  const c = cones[slalom.next];
  if (!c) return;
  // el cono se cuenta cuando el eje delantero lo pasa en X; el lado lo da Z
  const dir = S.pos.x - c.home.x;
  if (Math.abs(dir) < 0.3 && Math.abs(S.pos.z - c.home.z) < 3.2) {
    const side = Math.sign(S.pos.z - c.home.z) || 1;
    if (slalom.next === 0) slalom.t0 = performance.now();
    if (slalom.side && side === slalom.side) { slalom.errors++; say('Ese cono era por el otro lado'); }
    slalom.side = side;
    slalom.next++;
    if (slalom.next >= cones.length) { slalom.done = true; checkTask(); }
  }
}
function updateMarkers(t) {
  const task = TASKS[taskIdx];
  markPick.visible = markDrop.visible = false;
  if (finished) return;
  if (task.carga) {
    const p = taskPallet(task);
    if (p && p !== S.carried) { markPick.visible = true; p.node.getWorldPosition(markPick.position); }
    else if (p === S.carried) {
      markDrop.visible = true;
      if (task.destino) world.zones[task.destino].getWorldPosition(markDrop.position);
      else {
        // primer módulo libre del nivel pedido
        const lvY = task.nivel === 'medio' ? RACK.levels[0] : RACK.levels[1];
        const free = world.slots.find((s) => s.nivel === task.nivel && !world.pallets.some((q) => q !== S.carried && q.node.getWorldPosition(_w).distanceTo(s.node.getWorldPosition(_v)) < 0.5));
        if (free) free.node.getWorldPosition(markDrop.position); else markDrop.position.set(0, lvY, RACK.z);
      }
    }
  } else if (task.id === 'slalom') {
    const c = world.cones[slalom.next];
    if (c) { markDrop.visible = true; markDrop.position.copy(c.home); }
  }
  for (const m of [markPick, markDrop]) {
    m.userData.arrow.position.y = 1.9 + Math.sin(t * 3) * 0.12;
    m.children[0].material.opacity = 0.55 + 0.3 * Math.sin(t * 4);
  }
}

/* =====================================================================
   Entrada: teclado, botones táctiles y controles del Quest
   ===================================================================== */
const keys = new Set();
addEventListener('keydown', (e) => {
  if (e.target.closest && e.target.closest('dialog')) return;
  keys.add(e.code);
  if (e.code === 'KeyF') setShuttle('F');
  if (e.code === 'KeyR') setShuttle('R');
  if (e.code === 'KeyN') setShuttle('N');
  if (e.code === 'KeyK') toggleKey();
  if (e.code === 'KeyX') toggleEstop();
  if (e.code === 'KeyC') toggleCam();
  if (e.code === 'KeyG') { S.carried ? dropPallet(true) : tryPick(); }
  if (['ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight', 'Space'].includes(e.code)) e.preventDefault();
});
addEventListener('keyup', (e) => keys.delete(e.code));
addEventListener('blur', () => keys.clear());
const touch = { up: 0, down: 0, left: 0, right: 0, acc: 0, brk: 0 };
document.querySelectorAll('#touch [data-t]').forEach((b) => {
  const k = b.dataset.t;
  const on = (e) => { e.preventDefault(); touch[k] = 1; b.style.background = 'rgba(10,132,255,.35)'; };
  const off = () => { touch[k] = 0; b.style.background = ''; };
  b.addEventListener('pointerdown', on); b.addEventListener('pointerup', off); b.addEventListener('pointerleave', off); b.addEventListener('pointercancel', off);
});

function setShuttle(s) {
  if (!S.key) { say('Primero girá la llave'); return; }
  if (s !== 'N' && Math.abs(S.v) > 0.3 && Math.sign(S.v) !== (s === 'F' ? 1 : -1)) { say('Frená antes de cambiar de sentido'); return; }
  S.shuttle = s;
  document.querySelectorAll('.shuttle button').forEach((b) => b.setAttribute('aria-pressed', String(b.dataset.s === s)));
  checkTask();
}
function toggleKey() { S.key = !S.key; if (!S.key) S.shuttle = 'N'; say(S.key ? 'Autoelevador encendido' : 'Autoelevador apagado'); syncUI(); checkTask(); }
function toggleEstop() { S.estop = !S.estop; if (S.estop) { S.v = 0; } say(S.estop ? 'Parada de emergencia activada' : 'Parada de emergencia liberada'); syncUI(); checkTask(); }

/* ---------- Quest: controles, agarre del volante y las palancas ---------- */
const rig = new THREE.Group();
fk.add(rig);
const ctrlFactory = new XRControllerModelFactory();
const hands = [0, 1].map((i) => {
  const grip = renderer.xr.getControllerGrip(i);
  grip.add(ctrlFactory.createControllerModel(grip));
  rig.add(grip);
  return { grip, side: null, gp: null, prev: {}, hold: null, holdData: null };
});
function haptic(intensity, ms) {
  const s = renderer.xr.getSession();
  if (!s) return;
  for (const src of s.inputSources) src.gamepad?.hapticActuators?.[0]?.pulse?.(intensity, ms);
}
const GRAB = () => [
  { id: 'volante', node: parts.knob, r: 0.13 },
  { id: 'volante', node: parts.wheel, r: 0.20 },
  { id: 'lift', node: parts.levLift, r: 0.07, top: 0.11 },
  { id: 'tilt', node: parts.levTilt, r: 0.07, top: 0.11 },
  { id: 'side', node: parts.levSide, r: 0.07, top: 0.11 },
  { id: 'llave', node: parts.key, r: 0.07 },
  { id: 'parada', node: parts.estop, r: 0.08 },
];
const _p = new THREE.Vector3(), _a = new THREE.Vector3(), _n = new THREE.Vector3();
function wheelAngleOf(handWorld) {
  // ángulo de la mano alrededor del eje de la columna, en el plano del volante
  const inv = parts.wheel.parent.matrixWorld.clone().invert();
  const p = handWorld.clone().applyMatrix4(inv).sub(rest.get(parts.wheel).p);
  const q = rest.get(parts.wheel).q.clone().invert();
  p.applyQuaternion(q);       // marco de reposo del volante: eje en Y
  return Math.atan2(p.x, p.z);
}
function updateHands(dt) {
  const session = renderer.xr.getSession();
  if (!session) return;
  const srcs = [...session.inputSources];
  for (const [i, h] of hands.entries()) {
    const src = srcs.find((s, k) => k === i) || null;
    h.side = src?.handedness; h.gp = src?.gamepad || null;
    const gp = h.gp;
    if (!gp) continue;
    const b = (n) => !!gp.buttons[n]?.pressed;
    const flank = (n) => b(n) && !h.prev[n];
    const handPos = h.grip.getWorldPosition(new THREE.Vector3());
    // gatillos: acelerador (derecho) y freno (izquierdo)
    const trig = gp.buttons[0]?.value || 0;
    if (h.side === 'right') xr.accel = trig; else xr.brake = trig;
    // sticks
    const ax = gp.axes[2] || 0, ay = gp.axes[3] || 0;
    if (h.side === 'left') { xr.steer = Math.abs(ax) > 0.15 ? ax : 0; xr.tilt = Math.abs(ay) > 0.3 ? -ay : 0; }
    else { xr.lift = Math.abs(ay) > 0.2 ? -ay : 0; xr.side = Math.abs(ax) > 0.3 ? -ax : 0; }
    // botones: A (4) inversor · B (5) llave · X (4 izq) parada · Y (5 izq) recentrar
    // A: Adelante → Neutro → Reversa → Neutro → Adelante…
    if (h.side === 'right' && flank(4)) setShuttle(S.shuttle !== 'N' ? 'N' : lastDir === 'F' ? 'R' : 'F');
    if (h.side === 'right' && flank(5)) toggleKey();
    if (h.side === 'left' && flank(4)) toggleEstop();
    if (h.side === 'left' && flank(5)) calibrate();
    // grip: agarrar el control más cercano
    if (flank(1) && !h.hold) {
      let best = null, bd = 1e9;
      for (const g of GRAB()) {
        g.node.getWorldPosition(_p);
        if (g.top) _p.add(_a.set(0, g.top, 0));
        const d = _p.distanceTo(handPos);
        if (d < g.r && d < bd) { best = g; bd = d; }
      }
      if (best) {
        h.hold = best.id;
        if (best.id === 'volante') h.holdData = { last: wheelAngleOf(handPos) };
        else if (best.id === 'llave') { toggleKey(); h.hold = null; }
        else if (best.id === 'parada') { toggleEstop(); h.hold = null; }
        else h.holdData = { start: fk.worldToLocal(handPos.clone()) };
        haptic(0.2, 30);
      }
    }
    if (!b(1) && h.hold) { if (h.hold in S.lever) S.lever[h.hold] = 0; h.hold = null; }
    if (h.hold === 'volante') {
      const a = wheelAngleOf(handPos);
      let d = a - h.holdData.last; if (d > Math.PI) d -= 2 * Math.PI; if (d < -Math.PI) d += 2 * Math.PI;
      S.wheel = THREE.MathUtils.clamp(S.wheel + d, -WHEEL_TURNS, WHEEL_TURNS);
      h.holdData.last = a;
      xr.wheelHeld = true;
    } else if (h.hold in S.lever) {
      const now = fk.worldToLocal(handPos.clone());
      // tirar hacia el conductor (-Z de la raíz) = subir / inclinar atrás / desplazar a la izquierda
      S.lever[h.hold] = THREE.MathUtils.clamp(-(now.z - h.holdData.start.z) / 0.06, -1, 1);
    }
    for (const n of [0, 1, 3, 4, 5]) h.prev[n] = b(n);
  }
}
const xr = { accel: 0, brake: 0, steer: 0, lift: 0, tilt: 0, side: 0, wheelHeld: false };
let lastDir = 'F';
function calibrate() {
  // ubica la cabeza del usuario en el asiento del autoelevador, mirando hacia adelante (+Z de la raíz)
  const headLocal = camera.position.clone();                    // pose de la cabeza dentro del rig
  const yawHead = new THREE.Euler().setFromQuaternion(camera.quaternion, 'YXZ').y;
  const th = Math.PI - yawHead;
  rig.rotation.set(0, th, 0);
  rig.position.copy(EYE).sub(headLocal.applyAxisAngle(AX.y, th));
  say('Vista recentrada en el asiento');
}

/* =====================================================================
   Simulación
   ===================================================================== */
function step(dt) {
  // entradas combinadas
  const k = (c) => keys.has(c) ? 1 : 0;
  let accel = Math.max(k('KeyW'), touch.acc, xr.accel);
  let brake = Math.max(k('KeyS'), k('Space'), touch.brk, xr.brake);
  const steerIn = (k('KeyA') + touch.left) - (k('KeyD') + touch.right) + xr.steer * -1;
  const liftIn = (k('ArrowUp') + touch.up) - (k('ArrowDown') + touch.down) + xr.lift + S.lever.lift;
  const tiltIn = k('KeyE') - k('KeyQ') + xr.tilt + S.lever.tilt;
  const sideIn = k('ArrowLeft') - k('ArrowRight') + xr.side + S.lever.side;
  if (!S.key || S.estop) accel = 0;
  S.accel += (accel - S.accel) * Math.min(1, dt * 10);
  S.brake += (brake - S.brake) * Math.min(1, dt * 10);

  // volante (si no lo agarra la mano)
  if (!xr.wheelHeld) S.wheel = THREE.MathUtils.clamp(S.wheel + steerIn * 3.2 * dt, -WHEEL_TURNS, WHEEL_TURNS);
  xr.wheelHeld = false;
  S.steer = (S.wheel / WHEEL_TURNS) * STEER_MAX;

  // tracción
  const dir = S.shuttle === 'F' ? 1 : S.shuttle === 'R' ? -1 : 0;
  if (dir) lastDir = S.shuttle;
  const vmax = dir > 0 ? V_MAX : V_MAX_R;
  const loadSlow = S.carried ? 0.75 : 1;
  const target = dir * vmax * loadSlow * S.accel;
  const toward = (goal, rate) => { S.v += Math.sign(goal - S.v) * Math.min(Math.abs(goal - S.v), rate * dt); };
  if (S.estop) S.v = 0;
  else if (S.brake > 0.05) toward(0, BRAKE * S.brake);
  else if (dir && S.accel > 0.02) {
    if (S.v * dir < -0.01) toward(0, BRAKE * 0.6);               // venía en el otro sentido: frena primero
    else toward(target, Math.abs(target) > Math.abs(S.v) ? ACCEL : ROLL * 2);
  } else toward(0, ROLL);

  // hidráulica: primero el carro (elevación libre), después el mástil interior
  const hyd = S.key && !S.estop;
  let carr = S.carr, inner = S.inner, tilt = S.tilt, side = S.side;
  if (hyd && Math.abs(liftIn) > 0.05) {
    const dz = THREE.MathUtils.clamp(liftIn, -1, 1) * (liftIn > 0 ? LIFT_SPEED : LOWER_SPEED) * (S.carried && liftIn > 0 ? 0.8 : 1) * dt;
    if (dz > 0) { const a = Math.min(dz, CARR_MAX - carr); carr += a; inner = Math.min(INNER_MAX, inner + dz - a); }
    else { const a = Math.max(dz, -inner); inner += a; carr = Math.max(0, carr + dz - a); }
  }
  if (hyd) tilt = THREE.MathUtils.clamp(tilt + THREE.MathUtils.clamp(tiltIn, -1, 1) * TILT_SPEED * dt, TILT_BACK, TILT_FWD);
  if (hyd) side = THREE.MathUtils.clamp(side + THREE.MathUtils.clamp(sideIn, -1, 1) * SIDE_SPEED * dt, -SIDE_MAX, SIDE_MAX);

  // nueva pose (cinemática de dirección trasera: el eje delantero avanza en su rumbo)
  const yaw = S.yaw + (S.v * Math.tan(S.steer) / L) * dt;
  const pos = S.pos.clone().add(_a.set(Math.sin(yaw), 0, Math.cos(yaw)).multiplyScalar(S.v * dt));

  // probar la pose; si choca, se queda donde estaba
  const prev = { pos: S.pos.clone(), yaw: S.yaw, carr: S.carr, inner: S.inner, tilt: S.tilt, side: S.side };
  Object.assign(S, { pos, yaw, carr, inner, tilt, side });
  applyPose();
  const hit = collides(shapes());
  if (hit) {
    // primero se intenta conservar solo el movimiento del mástil, después solo el del vehículo
    Object.assign(S, { pos: prev.pos, yaw: prev.yaw }); applyPose();
    if (collides(shapes())) { Object.assign(S, { carr: prev.carr, inner: prev.inner, tilt: prev.tilt, side: prev.side }); applyPose(); }
    if (Math.abs(S.v) > 0.6) { S.hits++; say(hit.what === 'pallet' ? 'Golpeaste un pallet' : 'Golpe contra la estructura'); haptic(0.9, 160); }
    S.v = 0;
  }
  S.spin += S.v * dt;
  // conos: si el cuerpo los toca, se caen
  const body = shapes()[0].o;
  for (const c of world.cones) {
    if (c.down) { if (c.t < 1) { c.t = Math.min(1, c.t + dt * 2.5); c.node.rotation.set(0, 0, 0); c.node.rotateOnWorldAxis(c.dir, c.t * 1.45); c.node.position.copy(c.home).addScaledVector(_w.set(Math.sin(S.yaw), 0, Math.cos(S.yaw)), c.t * 0.25); } continue; }
    if (overlap(body, obb(c.home.x, c.home.z, 0.17, 0.17, 0, 0, 0.7))) {
      c.down = true; c.t = 0;
      c.dir = new THREE.Vector3(Math.cos(S.yaw), 0, -Math.sin(S.yaw));
      slalom.errors++; say('¡Tiraste un cono!'); haptic(0.5, 80);
    }
  }
  tryPick();
  updateCarried();
  updateSlalom();
  // batería: baja con la marcha y la hidráulica
  S.battery = Math.max(0, S.battery - (Math.abs(S.v) * 0.004 + (Math.abs(liftIn) > 0.05 ? 0.01 : 0)) * dt);
  if (TASKS[taskIdx].id === 'arranque') checkTask();
  else if (TASKS[taskIdx].carga) checkTask();
}

/* =====================================================================
   Pantallas (tablero, visera) e interfaz HTML
   ===================================================================== */
const fmtTime = (s) => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, '0')}`;
const forkHeight = () => {
  _v.set(0, BLADE.top, BLADE.heelZ); parts.forkL.localToWorld(_v);
  return Math.max(0, _v.y);
};
function drawDash() {
  const { g, c } = dash;
  g.fillStyle = '#05080b'; g.fillRect(0, 0, c.width, c.height);
  const on = S.key;
  g.globalAlpha = on ? 1 : 0.35;
  // inversor
  const col = { F: '#34c759', N: '#ffd60a', R: '#ff453a' }[S.shuttle];
  g.fillStyle = col; g.font = '800 92px system-ui'; g.textAlign = 'left'; g.textBaseline = 'middle';
  g.fillText(S.shuttle, 22, 78);
  // velocidad
  g.fillStyle = '#f2f6fa'; g.font = '700 64px system-ui'; g.textAlign = 'right';
  g.fillText((Math.abs(S.v) * 3.6).toFixed(1).replace('.', ','), 330, 70);
  g.font = '500 24px system-ui'; g.fillStyle = '#9fb3c8'; g.fillText('km/h', 330, 116);
  // horquillas y batería
  g.textAlign = 'left'; g.fillStyle = '#9fb3c8'; g.font = '500 22px system-ui';
  g.fillText('Horquillas', 352, 40); g.fillText('Batería', 352, 120);
  g.fillStyle = '#f2f6fa'; g.font = '700 34px system-ui';
  g.fillText(`${forkHeight().toFixed(2).replace('.', ',')} m`, 352, 76);
  const b = S.battery / 100;
  g.strokeStyle = '#9fb3c8'; g.lineWidth = 3; g.strokeRect(352, 140, 130, 34); g.fillRect(482, 150, 6, 14);
  g.fillStyle = b > 0.3 ? '#34c759' : '#ff9f0a'; g.fillRect(356, 144, 122 * b, 26);
  g.fillStyle = '#f2f6fa'; g.font = '700 22px system-ui'; g.fillText(`${Math.round(S.battery)} %`, 400, 158);
  // franja de estado
  g.fillStyle = S.estop ? '#ff453a' : S.carried ? '#0a84ff' : '#1c2733';
  g.fillRect(0, 186, c.width, 38);
  g.fillStyle = '#ffffff'; g.font = '600 22px system-ui'; g.textAlign = 'left';
  g.fillText(S.estop ? 'PARADA DE EMERGENCIA' : S.carried ? `Carga: ${S.carried.desc}` : (on ? 'Listo · ORIENTAL E25' : 'Apagado · girá la llave'), 16, 206);
  // bandera chiquita
  g.globalAlpha = 1;
  dash.t.needsUpdate = true;
}
function drawVisor() {
  const { g, c } = visor;
  g.clearRect(0, 0, c.width, c.height);
  g.fillStyle = 'rgba(12,20,32,.78)';
  roundRect(g, 4, 4, c.width - 8, c.height - 8, 34); g.fill();
  const t = TASKS[taskIdx];
  g.fillStyle = '#7cc4ff'; g.font = '700 30px system-ui'; g.textBaseline = 'top';
  g.fillText(finished ? 'ENTRENAMIENTO COMPLETO' : `TAREA ${taskIdx + 1} DE ${TASKS.length}`, 36, 26);
  g.fillStyle = '#fff'; g.font = '700 46px system-ui'; g.fillText(finished ? '¡Muy bien!' : t.titulo, 36, 66);
  g.fillStyle = '#c9d6e3'; g.font = '500 28px system-ui';
  if (lastMsg && performance.now() - lastMsg.t < 3000) { g.fillStyle = '#ffd60a'; g.font = '700 30px system-ui'; g.fillText(lastMsg.msg, 36, 128); visor.t.needsUpdate = true; return; }
  wrap(g, finished ? `Tiempo total ${fmtTime((performance.now() - tStart) / 1000)} · ${S.hits} choques · ${slalom.errors} conos` : t.texto, 36, 124, c.width - 72, 34, 2);
  visor.t.needsUpdate = true;
}
function roundRect(g, x, y, w, h, r) { g.beginPath(); g.moveTo(x + r, y); g.arcTo(x + w, y, x + w, y + h, r); g.arcTo(x + w, y + h, x, y + h, r); g.arcTo(x, y + h, x, y, r); g.arcTo(x, y, x + w, y, r); g.closePath(); }
function wrap(g, text, x, y, w, lh, max) {
  const words = text.split(' '); let line = '', n = 0;
  for (const word of words) {
    const t = line ? line + ' ' + word : word;
    if (g.measureText(t).width > w && line) { g.fillText(line, x, y + n * lh); line = word; if (++n >= max) return; } else line = t;
  }
  if (line) g.fillText(line, x, y + n * lh);
}

const ui = {
  step: document.getElementById('tStep'), title: document.getElementById('tTitle'), text: document.getElementById('tText'), prog: document.getElementById('prog'),
  v: document.getElementById('sV'), h: document.getElementById('sH'), b: document.getElementById('sB'), time: document.getElementById('sTime'),
  hits: document.getElementById('sHits'), key: document.getElementById('swKey'), estop: document.getElementById('swStop'),
};
function renderTask() {
  const t = TASKS[taskIdx];
  ui.step.textContent = finished ? 'Entrenamiento completo' : `Tarea ${taskIdx + 1} de ${TASKS.length}`;
  ui.title.textContent = finished ? '¡Muy bien!' : t.titulo;
  ui.text.textContent = finished ? `Tiempo total ${fmtTime((performance.now() - tStart) / 1000)} · ${S.hits} choques · ${slalom.errors} conos.` : t.texto;
  ui.prog.innerHTML = TASKS.map((_, i) => `<i class="${i < taskIdx || finished ? 'done' : i === taskIdx ? 'now' : ''}"></i>`).join('');
}
function syncUI() {
  ui.key.checked = S.key; ui.estop.checked = S.estop;
  document.querySelectorAll('.shuttle button').forEach((b) => b.setAttribute('aria-pressed', String(b.dataset.s === S.shuttle)));
}
ui.key.addEventListener('change', () => { if (ui.key.checked !== S.key) toggleKey(); });
ui.estop.addEventListener('change', () => { if (ui.estop.checked !== S.estop) toggleEstop(); });
document.querySelectorAll('.shuttle button').forEach((b) => b.addEventListener('click', () => setShuttle(b.dataset.s)));
function updatePanel() {
  ui.v.textContent = (Math.abs(S.v) * 3.6).toFixed(1).replace('.', ',');
  ui.h.textContent = forkHeight().toFixed(2).replace('.', ',');
  ui.b.textContent = Math.round(S.battery);
  ui.time.textContent = fmtTime((performance.now() - tStart) / 1000);
  ui.hits.textContent = `${S.hits} choques · ${slalom.errors} conos`;
}
let toastT = 0;
function say(msg) {
  const el = document.getElementById('toast');
  el.textContent = msg; el.classList.add('on'); clearTimeout(toastT); toastT = setTimeout(() => el.classList.remove('on'), 2600);
  lastMsg = { msg, t: performance.now() };
}
let lastMsg = null;

/* ---------- cámaras de escritorio: exterior (sigue al autoelevador) o cabina ---------- */
let camMode = 'exterior';
const camTarget = new THREE.Vector3();
function toggleCam() {
  camMode = camMode === 'exterior' ? 'cabina' : 'exterior';
  orbit.enabled = camMode === 'exterior';
  document.getElementById('btnCam').querySelector('span').textContent = camMode === 'exterior' ? 'Vista de cabina' : 'Vista exterior';
  if (camMode === 'cabina') { look.yaw = 0; look.pitch = -0.12; }
}
const look = { yaw: 0, pitch: -0.12, drag: null };
canvas.addEventListener('pointerdown', (e) => { if (camMode === 'cabina') look.drag = { x: e.clientX, y: e.clientY, yaw: look.yaw, pitch: look.pitch }; });
addEventListener('pointerup', () => { look.drag = null; });
addEventListener('pointermove', (e) => {
  if (!look.drag) return;
  look.yaw = look.drag.yaw - (e.clientX - look.drag.x) * 0.005;
  look.pitch = THREE.MathUtils.clamp(look.drag.pitch - (e.clientY - look.drag.y) * 0.005, -1.2, 0.9);
});
function updateDesktopCamera(dt) {
  if (camMode === 'cabina') {
    camera.position.copy(EYE); fk.localToWorld(camera.position);
    const q = new THREE.Quaternion().setFromEuler(new THREE.Euler(look.pitch, S.yaw + Math.PI + look.yaw, 0, 'YXZ'));
    camera.quaternion.copy(q);
    camera.fov = 75; camera.updateProjectionMatrix();
  } else {
    camera.fov = 55; camera.updateProjectionMatrix();
    const target = _a.set(0, 1.1, -0.6); fk.localToWorld(target);
    const delta = target.clone().sub(camTarget);
    camTarget.copy(target); orbit.target.copy(target);
    camera.position.add(delta);    // la cámara acompaña al autoelevador manteniendo el ángulo que eligió el usuario
    orbit.update();
  }
}

/* ---------- espejos ---------- */
let mirrorTick = 0;
function renderMirrors() {
  mirrorTick++;
  const i = mirrorTick % 3;
  const { rt, cam } = mirrorCams[i];
  const xrOn = renderer.xr.enabled;
  renderer.xr.enabled = false;
  const prevRT = renderer.getRenderTarget();
  visorMesh.visible = false;
  renderer.setRenderTarget(rt);
  renderer.render(scene, cam);
  renderer.setRenderTarget(prevRT);
  renderer.xr.enabled = xrOn;
}

/* =====================================================================
   VR
   ===================================================================== */
const btnVR = document.getElementById('btnVR');
if (navigator.xr && await navigator.xr.isSessionSupported('immersive-vr').catch(() => false)) {
  btnVR.hidden = false;
  btnVR.addEventListener('click', async () => {
    const s = await navigator.xr.requestSession('immersive-vr', { optionalFeatures: ['local-floor', 'hand-tracking'] });
    await renderer.xr.setSession(s);
  });
}
renderer.xr.addEventListener('sessionstart', () => {
  rig.add(camera);  // la cámara XR vive dentro del rig, sentado en el autoelevador
  camera.position.set(0, 0, 0); camera.quaternion.identity();
  visorMesh.visible = true;
  setTimeout(calibrate, 400);
  document.body.classList.add('xr');
});
renderer.xr.addEventListener('sessionend', () => {
  scene.add(camera);
  visorMesh.visible = false;
  camera.position.set(-6, 5, 10);
  document.body.classList.remove('xr');
});

/* =====================================================================
   Botones de la interfaz y arranque
   ===================================================================== */
document.getElementById('btnCam').addEventListener('click', toggleCam);
document.getElementById('btnManual').addEventListener('click', () => document.getElementById('manual').showModal());
document.getElementById('btnReset').addEventListener('click', () => restart());
function restart() {
  if (S.carried) dropPallet(true);
  for (const p of world.pallets) { p.node.matrix.copy(p.node.userData.home); p.node.matrix.decompose(p.node.position, p.node.quaternion, p.node.scale); scene.attach(p.node); p.node.matrix.decompose(p.node.position, p.node.quaternion, p.node.scale); }
  for (const c of world.cones) { c.down = false; c.t = 0; c.node.position.copy(c.home); c.node.rotation.set(0, 0, 0); }
  Object.assign(slalom, { next: 0, side: 0, errors: 0, done: false });
  S.hits = 0; S.battery = 100; taskIdx = 0; finished = false; tStart = tTask = performance.now();
  resetVehicle(); renderTask(); syncUI();
  say('Entrenamiento reiniciado');
}
// los pallets pasan a ser hijos directos de la escena (se pueden reubicar libremente)
for (const p of world.pallets) scene.attach(p.node);
resetVehicle();
camera.position.copy(S.pos).add(new THREE.Vector3(-5.5, 4.2, 6.5));
camTarget.copy(S.pos); orbit.target.copy(S.pos); orbit.update();
renderTask(); syncUI();
if (!localStorage.getItem('ae-manual-visto')) { document.getElementById('manual').showModal(); try { localStorage.setItem('ae-manual-visto', '1'); } catch {} }

const clock = new THREE.Clock();
let uiTick = 0;
renderer.setAnimationLoop((t, frame) => {
  const dt = Math.min(clock.getDelta(), 1 / 20);
  updateHands(dt);
  step(dt);
  updateMarkers(t / 1000);
  uiTick += dt;
  if (uiTick > 0.2) { uiTick = 0; drawDash(); if (renderer.xr.isPresenting) drawVisor(); else updatePanel(); }
  renderMirrors();
  if (renderer.xr.isPresenting) visorMesh.visible = true;
  else updateDesktopCamera(dt);
  renderer.render(scene, camera);
});
addEventListener('resize', () => { renderer.setSize(innerWidth, innerHeight); camera.aspect = innerWidth / innerHeight; camera.updateProjectionMatrix(); });
if (DEBUG) Object.assign(window, { __ae: { renderer, renderOnce() { renderMirrors(); updateDesktopCamera(0); renderer.render(scene, camera); }, pause() { renderer.setAnimationLoop(null); }, drawDash, toggleCam, S, parts, world, step, applyPose, shapes, collides, tryPick, dropPallet, forkInPocket, TASKS, setShuttle, toggleKey, scene, camera, fk, restart, slalom, get taskIdx() { return taskIdx; }, set taskIdx(v) { taskIdx = v; renderTask(); } } });

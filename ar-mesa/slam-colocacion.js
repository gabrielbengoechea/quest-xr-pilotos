/* =====================================================================================================================
   Colocación SLAM estilo "Medición" (iOS) para WebXR: Meta Quest (passthrough), Android (ARCore) y simulador de escritorio.

   Exporta
   - MedicionReticle      retícula blanca y amarilla que flota frente a la cámara mientras busca y se "aplana" sobre el
                          plano encontrado; punto amarillo central con pulso; huella del objeto a escala real.
   - PlaneVisualizer      malla de puntos sobre los planos horizontales detectados (WebXR plane-detection o simulados).
   - SlamPlacementController
                          máquina de estados  inicio → buscando → superficie → colocado  con hit-test continuo desde el
                          centro de la vista (teléfono) o desde el rayo del control/mano (Quest), ancla espacial al tocar,
                          estimación de luz y eventos para la interfaz.
   - SimulatedSurfaces    "SLAM" de escritorio: rayo del puntero contra mesas/pisos virtuales, mismo contrato que el hit-test.

   El contrato es el mismo en todos los casos: cada cuadro llega un `hit` = { matrix: Matrix4 (eje Y = normal del plano),
   horizontal: bool } o null, y al tocar se fija un ancla. El objeto se cuelga de `anchorRoot`, que el controlador mueve con
   la pose del ancla en cada cuadro (si el sistema la corrige, el objeto la sigue).
   ===================================================================================================================== */
import * as THREE from 'three';

export const AMARILLO = new THREE.Color('#ffd60a');
const BLANCO = new THREE.Color('#ffffff');
const COS_HORIZONTAL = Math.cos(THREE.MathUtils.degToRad(22));   // tolerancia para "plano horizontal"
const _v = new THREE.Vector3(), _v2 = new THREE.Vector3(), _q = new THREE.Quaternion(), _q2 = new THREE.Quaternion();
const _m = new THREE.Matrix4(), _s = new THREE.Vector3();
const Q_FACE = new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(1, 0, 0), Math.PI / 2);   // Y local → Z de la cámara

/* ---------------------------------------------------------------------------------------------------------------------
   Retícula
   --------------------------------------------------------------------------------------------------------------------- */
function basic(color, opacity = 1) {
  return new THREE.MeshBasicMaterial({ color, transparent: true, opacity, depthTest: false, depthWrite: false, side: THREE.DoubleSide, toneMapped: false });
}

export class MedicionReticle extends THREE.Group {
  /** @param {{footprint?: number}} opts footprint = radio (m) de la huella del objeto a colocar */
  constructor({ footprint = 0.1 } = {}) {
    super();
    this.name = 'MedicionReticle';
    this.renderOrder = 999;
    this.state = 'oculto';          // oculto | buscando | superficie
    this.t = 0;
    this.found = 0;                  // 0 → 1: mezcla "flotando" ↔ "apoyada"
    this.visible = false;
    // Disco (en el plano XZ local: su normal es +Y del grupo). Escala con la distancia para tamaño aparente constante.
    this.disc = new THREE.Group();
    this.add(this.disc);
    const flat = (geo) => geo.rotateX(-Math.PI / 2);
    this.ring = new THREE.Mesh(flat(new THREE.RingGeometry(0.046, 0.051, 72)), basic(BLANCO, 0.95));
    this.shadowRing = new THREE.Mesh(flat(new THREE.RingGeometry(0.043, 0.054, 72)), basic(new THREE.Color('#000000'), 0.18));
    this.arcs = new THREE.Group();
    for (let k = 0; k < 4; k++) {
      const a = new THREE.Mesh(flat(new THREE.RingGeometry(0.034, 0.039, 20, 1, k * Math.PI / 2 + 0.28, Math.PI / 2 - 0.56)), basic(AMARILLO));
      this.arcs.add(a);
    }
    this.dot = new THREE.Mesh(flat(new THREE.CircleGeometry(0.0065, 32)), basic(AMARILLO));
    this.halo = new THREE.Mesh(flat(new THREE.RingGeometry(0.0085, 0.011, 40)), basic(AMARILLO, 0.6));
    for (const m of [this.shadowRing, this.ring, this.arcs, this.halo, this.dot]) this.disc.add(m);
    this.traverse((o) => { o.renderOrder = 999; });
    // Huella a escala real (no escala con la distancia): círculo punteado del tamaño de la base del objeto
    this.footprint = new THREE.Group();
    this.add(this.footprint);
    this.setFootprint(footprint);
    this._pos = new THREE.Vector3();
    this._quat = new THREE.Quaternion();
    this._init = false;
  }

  setFootprint(r) {
    this.footprint.clear();
    const n = 48, dash = 0.55;
    for (let k = 0; k < n; k++) {
      const a0 = (k / n) * Math.PI * 2, a1 = a0 + (dash * Math.PI * 2) / n;
      const g = new THREE.RingGeometry(r - 0.002, r + 0.002, 4, 1, a0, a1 - a0).rotateX(-Math.PI / 2);
      const m = new THREE.Mesh(g, basic(BLANCO, 0.75));
      m.renderOrder = 998;
      this.footprint.add(m);
    }
  }

  /**
   * @param {number} dt
   * @param {THREE.Camera} camera cámara activa (en XR: renderer.xr.getCamera())
   * @param {{matrix: THREE.Matrix4, horizontal: boolean}|null} hit
   * @param {boolean} active false oculta la retícula (p. ej. con el objeto ya colocado)
   */
  update(dt, camera, hit, active = true) {
    this.t += dt;
    const camPos = camera.getWorldPosition(_v2);
    let targetPos, targetQuat, horizontal = false;
    if (!active) {
      this.state = 'oculto';
      this.visible = false;
      this._init = false;
      return;
    }
    this.visible = true;
    if (hit) {
      hit.matrix.decompose(_v, _q, _s);
      horizontal = hit.horizontal;
      targetPos = _v.clone();
      if (horizontal) {
        // apoyada: normal hacia arriba; giro alrededor de la normal mirando a la cámara (como la app Medición)
        const yaw = Math.atan2(camPos.x - targetPos.x, camPos.z - targetPos.z);
        targetQuat = new THREE.Quaternion().setFromAxisAngle(THREE.Object3D.DEFAULT_UP, yaw);
      } else {
        targetQuat = _q.clone();
      }
      this.state = horizontal ? 'superficie' : 'buscando';
    } else {
      // flotando 0,55 m adelante, de cara a la cámara
      const fwd = camera.getWorldDirection(new THREE.Vector3());
      targetPos = camPos.clone().addScaledVector(fwd, 0.55);
      targetQuat = camera.getWorldQuaternion(new THREE.Quaternion()).multiply(Q_FACE);
      this.state = 'buscando';
    }
    const k = this._init ? 1 - Math.exp(-dt * (hit ? 18 : 10)) : 1;
    this._init = true;
    this._pos.lerp(targetPos, k);
    this._quat.slerp(targetQuat, k);
    this.position.copy(this._pos);
    this.quaternion.copy(this._quat);

    const want = this.state === 'superficie' ? 1 : 0;
    this.found += (want - this.found) * (1 - Math.exp(-dt * 12));
    const dist = Math.max(0.25, this._pos.distanceTo(camPos));
    this.disc.scale.setScalar(THREE.MathUtils.clamp(dist, 0.3, 3.5));
    // Buscando: anillo más tenue, arcos girando, sin punto. Superficie: arcos quietos, punto con pulso y halo.
    this.ring.material.opacity = 0.55 + 0.4 * this.found;
    this.arcs.rotation.y += dt * (2.2 * (1 - this.found) + 0.15);
    this.arcs.scale.setScalar(1.25 - 0.25 * this.found);
    for (const a of this.arcs.children) a.material.opacity = 0.35 + 0.65 * this.found;
    const pulse = 0.5 + 0.5 * Math.sin(this.t * Math.PI * 2 * 0.9);
    this.dot.scale.setScalar((0.35 + 0.65 * this.found) * (0.85 + 0.3 * pulse));
    this.dot.material.opacity = 0.4 + 0.6 * this.found;
    const ph = (this.t * 0.9) % 1;
    this.halo.scale.setScalar(1 + ph * 2.6);
    this.halo.material.opacity = 0.6 * (1 - ph) * this.found;
    this.footprint.visible = this.found > 0.5;
    for (const m of this.footprint.children) m.material.opacity = 0.75 * this.found;
  }
}

/* ---------------------------------------------------------------------------------------------------------------------
   Visualización de planos detectados (puntos tipo ARKit)
   --------------------------------------------------------------------------------------------------------------------- */
function dotTexture() {
  const c = document.createElement('canvas');
  c.width = c.height = 64;
  const g = c.getContext('2d');
  g.fillStyle = 'rgba(255,255,255,0.9)';
  g.beginPath();
  g.arc(32, 32, 5, 0, Math.PI * 2);
  g.fill();
  const t = new THREE.CanvasTexture(c);
  t.wrapS = t.wrapT = THREE.RepeatWrapping;
  t.colorSpace = THREE.SRGBColorSpace;
  t.anisotropy = 4;
  return t;
}

export class PlaneVisualizer extends THREE.Group {
  constructor() {
    super();
    this.name = 'PlaneVisualizer';
    this.tex = dotTexture();
    this.planes = new Map();   // clave → { mesh, changed }
    this.fade = 1;
    this.target = 1;
  }

  _material() {
    return new THREE.MeshBasicMaterial({ map: this.tex, transparent: true, opacity: 0, depthWrite: false, toneMapped: false,
      polygonOffset: true, polygonOffsetFactor: -2, side: THREE.DoubleSide });
  }

  /** Polígono en coordenadas del plano (x, z) → malla con UV en metros (10 puntos por metro). */
  _geometry(polygon) {
    const shape = new THREE.Shape(polygon.map((p) => new THREE.Vector2(p.x, -p.z)));
    const g = new THREE.ShapeGeometry(shape).rotateX(-Math.PI / 2);
    const pos = g.attributes.position, uv = g.attributes.uv;
    for (let i = 0; i < pos.count; i++) uv.setXY(i, pos.getX(i) * 12, pos.getZ(i) * 12);
    return g;
  }

  /** WebXR plane-detection: frame.detectedPlanes */
  updateFromFrame(frame, refSpace) {
    const seen = new Set();
    if (frame.detectedPlanes) {
      for (const plane of frame.detectedPlanes) {
        if (plane.orientation && plane.orientation !== 'horizontal') continue;
        seen.add(plane);
        let e = this.planes.get(plane);
        if (!e || e.changed !== plane.lastChangedTime) {
          if (e) { e.mesh.geometry.dispose(); } else {
            e = { mesh: new THREE.Mesh(undefined, this._material()) };
            e.mesh.matrixAutoUpdate = false;
            this.add(e.mesh);
            this.planes.set(plane, e);
          }
          e.mesh.geometry = this._geometry(plane.polygon);
          e.changed = plane.lastChangedTime;
        }
        const pose = frame.getPose(plane.planeSpace, refSpace);
        if (pose) e.mesh.matrix.fromArray(pose.transform.matrix);
        e.mesh.visible = !!pose;
      }
    }
    for (const [k, e] of this.planes) {
      if (typeof k !== 'string' && !seen.has(k)) { this.remove(e.mesh); e.mesh.geometry.dispose(); this.planes.delete(k); }
    }
  }

  /** Plano simulado (escritorio): clave fija, polígono local y matriz de mundo */
  setStatic(key, polygon, matrix) {
    let e = this.planes.get(key);
    if (!e) {
      e = { mesh: new THREE.Mesh(this._geometry(polygon), this._material()) };
      e.mesh.matrixAutoUpdate = false;
      this.add(e.mesh);
      this.planes.set(key, e);
    }
    e.mesh.matrix.copy(matrix);
  }

  update(dt) {
    this.fade += (this.target - this.fade) * (1 - Math.exp(-dt * 4));
    for (const e of this.planes.values()) {
      e.reveal = Math.min(1, (e.reveal ?? 0) + dt * 1.5);
      e.mesh.material.opacity = 0.32 * this.fade * e.reveal;
    }
    this.visible = this.fade > 0.01;
  }
}

/* ---------------------------------------------------------------------------------------------------------------------
   Superficies simuladas (escritorio): mesas y piso como planos con hit-test por rayo
   --------------------------------------------------------------------------------------------------------------------- */
export class SimulatedSurfaces {
  constructor() {
    this.surfaces = [];   // { name, y, minX, maxX, minZ, maxZ, detectedAt }
    this.t = 0;
  }
  add(name, y, minX, maxX, minZ, maxZ) { this.surfaces.push({ name, y, minX, maxX, minZ, maxZ, seen: 0 }); }
  /** Rayo → { matrix, horizontal } en la superficie más cercana. Una superficie "se detecta" tras mirarla ~0,6 s. */
  hit(ray, dt) {
    let best = null;
    for (const s of this.surfaces) {
      if (Math.abs(ray.direction.y) < 1e-4) continue;
      const t = (s.y - ray.origin.y) / ray.direction.y;
      if (t <= 0) continue;
      const p = ray.origin.clone().addScaledVector(ray.direction, t);
      if (p.x < s.minX || p.x > s.maxX || p.z < s.minZ || p.z > s.maxZ) continue;
      if (!best || t < best.t) best = { t, p, s };
    }
    for (const s of this.surfaces) if (!best || best.s !== s) s.seen = Math.max(0, s.seen - dt * 0.5);
    if (!best) return null;
    best.s.seen = Math.min(1, best.s.seen + dt / 0.6);
    if (best.s.seen < 1) return null;
    return { matrix: new THREE.Matrix4().makeTranslation(best.p.x, best.p.y, best.p.z), horizontal: true, surface: best.s.name };
  }
  detected() { return this.surfaces.filter((s) => s.seen >= 1); }
}

/* ---------------------------------------------------------------------------------------------------------------------
   Controlador de colocación
   --------------------------------------------------------------------------------------------------------------------- */
export const HUD = {
  inicio: { telefono: ['Buscá una superficie plana', 'Mové el teléfono despacio sobre la mesa'],
            quest: ['Buscá una superficie plana', 'Apuntá con el control o la mano a una mesa o al piso'],
            escritorio: ['Buscá una superficie plana', 'Pasá el puntero sobre la mesa'] },
  vertical: { telefono: ['Apuntá a una superficie horizontal', 'Una mesa, un escritorio o el piso'],
              quest: ['Apuntá a una superficie horizontal', 'Una mesa, un escritorio o el piso'],
              escritorio: ['Apuntá a una superficie horizontal', ''] },
  superficie: { telefono: ['Tocá para colocar', 'La retícula amarilla marca dónde va a quedar'],
                quest: ['Gatillo o pellizco para colocar', 'La retícula amarilla marca dónde va a quedar'],
                escritorio: ['Hacé clic para colocar', 'La retícula amarilla marca dónde va a quedar'] },
  colocado: { telefono: ['Caminá alrededor', ''], quest: ['Caminá alrededor', ''], escritorio: ['Girá la vista arrastrando', ''] },
  limitado: { telefono: ['Seguimiento limitado', 'Mové el teléfono más despacio y con más luz'],
              quest: ['Seguimiento limitado', 'Mirá alrededor para recuperar la posición'], escritorio: ['', ''] },
  ancla_perdida: { telefono: ['Recuperando el ancla…', 'Volvé a mirar hacia donde colocaste el objeto'],
                   quest: ['Recuperando el ancla…', 'Volvé a mirar hacia donde colocaste el objeto'], escritorio: ['', ''] },
};

export class SlamPlacementController extends THREE.EventDispatcher {
  /**
   * @param {object} o
   * @param {THREE.WebGLRenderer} o.renderer
   * @param {THREE.Scene} o.scene
   * @param {number} [o.footprint] radio de la huella (m)
   * @param {string} [o.device] 'telefono' | 'quest' | 'escritorio'
   */
  constructor({ renderer, scene, footprint = 0.1, device = 'telefono' }) {
    super();
    this.renderer = renderer;
    this.scene = scene;
    this.device = device;
    this.reticle = new MedicionReticle({ footprint });
    this.planes = new PlaneVisualizer();
    this.anchorRoot = new THREE.Group();
    this.anchorRoot.name = 'SpatialAnchorRoot';
    this.anchorRoot.visible = false;
    this.anchorRoot.matrixAutoUpdate = false;
    scene.add(this.reticle, this.planes, this.anchorRoot);
    this.state = 'inicio';
    this.hit = null;
    this.anchor = null;          // XRAnchor
    this.anchorTracked = true;
    this.session = null;
    this.refSpace = null;
    this.viewerSource = null;
    this.ctrlSource = null;      // hit-test desde el rayo de un control/mano (Quest)
    this.ctrlInput = null;
    this.limited = false;
    this.hudKey = '';
    this.yawOffset = 0;
  }

  setFootprint(r) { this.reticle.setFootprint(r); }

  /* ---------- Sesión WebXR ---------- */
  async attachSession(session) {
    this.session = session;
    this.refSpace = this.renderer.xr.getReferenceSpace();
    this.device = session.domOverlayState ? 'telefono' : this.device;
    try {
      const viewer = await session.requestReferenceSpace('viewer');
      this.viewerSource = await session.requestHitTestSource({ space: viewer });
    } catch (e) { console.warn('[AR] hit-test desde la vista no disponible', e); }
    session.addEventListener('inputsourceschange', () => this._pickController());
    this._pickController();
    session.addEventListener('end', () => this.detachSession());
    this.reset();
  }

  async _pickController() {
    const s = this.session;
    if (!s) return;
    const src = [...s.inputSources].find((i) => i.targetRayMode === 'tracked-pointer' && i.handedness === 'right')
             || [...s.inputSources].find((i) => i.targetRayMode === 'tracked-pointer');
    if (src === this.ctrlInput) return;
    this.ctrlSource?.cancel?.();
    this.ctrlSource = null;
    this.ctrlInput = src || null;
    if (src && s.requestHitTestSource) {
      try { this.ctrlSource = await s.requestHitTestSource({ space: src.targetRaySpace }); this.device = 'quest'; } catch (e) { /* solo la vista */ }
    }
  }

  detachSession() {
    this.viewerSource?.cancel?.();
    this.ctrlSource?.cancel?.();
    this.viewerSource = this.ctrlSource = this.ctrlInput = null;
    this.anchor?.delete?.();
    this.anchor = null;
    this.session = null;
  }

  /** Vuelve a "buscando": suelta el ancla y oculta el objeto. */
  reset() {
    this.anchor?.delete?.();
    this.anchor = null;
    this.anchorRoot.visible = false;
    this.planes.target = 1;
    this._setState('inicio');
  }

  _setState(st) {
    if (this.state === st && this.hudKey) return;
    this.state = st;
    this._hud(st === 'buscando' ? 'inicio' : st);
    this.dispatchEvent({ type: 'statechange', state: st });
  }

  _hud(key) {
    const k = this.limited && key !== 'colocado' ? 'limitado' : key;
    const t = (HUD[k] || HUD.inicio)[this.device] || HUD[k].telefono;
    const id = k + this.device;
    if (id === this.hudKey) return;
    this.hudKey = id;
    this.dispatchEvent({ type: 'hud', key: k, title: t[0], detail: t[1] });
  }

  /** Llamar en cada cuadro XR (desde setAnimationLoop). */
  updateXR(dt, frame, camera) {
    const ref = this.refSpace;
    const vp = frame.getViewerPose(ref);
    const lim = !!vp?.emulatedPosition;
    if (lim !== this.limited) { this.limited = lim; this.hudKey = ''; this._hud(this.state); }
    this.planes.updateFromFrame(frame, ref);

    if (this.state === 'colocado') {
      if (this.anchor) {
        const tracked = frame.trackedAnchors ? frame.trackedAnchors.has(this.anchor) : true;
        const pose = tracked ? frame.getPose(this.anchor.anchorSpace, ref) : null;
        if (pose) {
          this.anchorRoot.matrix.fromArray(pose.transform.matrix).multiply(_m.makeRotationY(this.yawOffset));
          this.anchorRoot.matrixWorldNeedsUpdate = true;
        }
        if (!!pose !== this.anchorTracked) { this.anchorTracked = !!pose; this.hudKey = ''; this._hud(pose ? 'colocado' : 'ancla_perdida'); }
      }
    } else {
      const src = this.ctrlSource || this.viewerSource;
      let hit = null;
      if (src) {
        const res = frame.getHitTestResults(src);
        if (res.length) {
          const p = res[0].getPose(ref);
          if (p) {
            const m = new THREE.Matrix4().fromArray(p.transform.matrix);
            const up = new THREE.Vector3(0, 1, 0).applyQuaternion(new THREE.Quaternion().setFromRotationMatrix(m));
            hit = { matrix: m, horizontal: up.y > COS_HORIZONTAL, result: res[0] };
          }
        }
      }
      this._applyHit(hit);
    }
    this.reticle.update(dt, camera, this.state === 'colocado' ? null : this.hit, this.state !== 'colocado');
    this.planes.update(dt);
  }

  /** Escritorio: el hit lo calcula SimulatedSurfaces. */
  updateSimulated(dt, camera, hit) {
    if (this.state !== 'colocado') this._applyHit(hit);
    this.reticle.update(dt, camera, this.hit, this.state !== 'colocado');
    this.planes.update(dt);
  }

  _applyHit(hit) {
    this.hit = hit;
    if (!hit) this._setState('buscando');
    else this._setState(hit.horizontal ? 'superficie' : 'buscando');
    if (this.state === 'buscando') this._hud(hit && !hit.horizontal ? 'vertical' : 'inicio');
  }

  /**
   * Fija el ancla donde está la retícula. Devuelve true si colocó.
   * @param {XRFrame} [frame] el frame del evento select (activo durante el evento) para crear el XRAnchor
   * @param {THREE.Vector3} viewerPos posición de la cabeza/cámara: el objeto queda mirando al usuario
   */
  place(viewerPos, frame) {
    if (this.state !== 'superficie' || !this.hit) return false;
    const p = new THREE.Vector3().setFromMatrixPosition(this.hit.matrix);
    const yaw = Math.atan2(viewerPos.x - p.x, viewerPos.z - p.z);
    const q = new THREE.Quaternion().setFromAxisAngle(THREE.Object3D.DEFAULT_UP, yaw);   // +Z del modelo hacia el usuario
    this.anchorRoot.matrix.compose(p, q, new THREE.Vector3(1, 1, 1));
    this.anchorRoot.matrixWorldNeedsUpdate = true;
    this.anchorRoot.visible = true;
    this.anchorTracked = true;
    this.yawOffset = 0;
    if (frame?.createAnchor && this.refSpace) {
      const t = new XRRigidTransform({ x: p.x, y: p.y, z: p.z }, { x: q.x, y: q.y, z: q.z, w: q.w });
      frame.createAnchor(t, this.refSpace).then((a) => {
        if (this.state === 'colocado' && !this.anchor) this.anchor = a; else a.delete?.();
      }).catch((e) => console.warn('[AR] sin ancla espacial, queda fijo en el espacio de referencia', e));
    }
    this.planes.target = 0;
    this._setState('colocado');
    this.dispatchEvent({ type: 'placed', matrix: this.anchorRoot.matrix.clone() });
    return true;
  }

  /** Gira el objeto colocado sobre su normal (stick del Quest o gesto). */
  rotateYaw(delta) {
    if (this.state !== 'colocado') return;
    this.anchorRoot.matrix.multiply(_m.makeRotationY(delta));
    this.anchorRoot.matrixWorldNeedsUpdate = true;
    this.yawOffset += delta;   // con ancla: se vuelve a aplicar sobre su pose en cada cuadro
  }
}

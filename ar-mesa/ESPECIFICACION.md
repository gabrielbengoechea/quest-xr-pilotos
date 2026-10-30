# RA de mesa · Especificación técnica

Dos proyectos de realidad aumentada comparten un mismo sistema de colocación SLAM con la interfaz de la app Medición del iPhone:

- **Brazo robótico**: UR de 6 ejes, 8.122 triángulos, escala 1:1.
- **Atlas XR**: globo logístico de mesa, 9.760 triángulos, Ø 45 cm.

| Plataforma | Cómo se ejecuta | Estado |
|---|---|---|
| Meta Quest 3 / 3S (passthrough) | WebXR `immersive-ar` en el navegador del Quest | Implementado en `ar-mesa/` |
| Android | WebXR `immersive-ar` en Chrome con ARCore | Implementado en `ar-mesa/` |
| iPhone / iPad | AR Quick Look con `.usdz` | Implementado. ARKit pone su propia interfaz de colocación |
| iOS nativo con la interfaz de Medición | RealityKit + ARKit | Pseudocódigo en §5.2 |
| Android nativo | ARCore + SceneView/Filament | Pseudocódigo en §5.3 |
| Quest nativo (Unity / OpenXR) | Meta XR SDK, MRUK | Pseudocódigo en §5.4 |

Safari en iOS no expone WebXR. En la web, el iPhone solo puede usar Quick Look: detecta el plano, coloca el modelo y genera la sombra, pero con la interfaz de Apple. Para tener en iOS la misma retícula, hace falta la app nativa del §5.2.

---

## 1. Sistema de colocación compartido

### 1.1 Capacidades SLAM

| Capacidad | WebXR (Quest / Android) | ARKit | ARCore |
|---|---|---|---|
| Detección de planos horizontales | `plane-detection` (opcional) + validación de la normal del hit (±22°) | `ARWorldTrackingConfiguration.planeDetection = [.horizontal]` | `Config.PlaneFindingMode.HORIZONTAL` |
| Hit-test / raycast continuo | `XRHitTestSource` desde `viewer` (centro de pantalla) o desde `targetRaySpace` (control/mano) | `ARView.raycast(from: center, allowing: .estimatedPlane, alignment: .horizontal)` | `Frame.hitTest(cx, cy)` filtrando `Plane.isPoseInPolygon` |
| Ancla espacial | `XRFrame.createAnchor(pose, refSpace)` → `XRAnchor.anchorSpace` | `AnchorEntity(raycastResult:)` / `ARAnchor` | `HitResult.createAnchor()` |
| Seguimiento 6DoF | `local` reference space + `getViewerPose` | `ARWorldTrackingConfiguration` | `Session` (por defecto) |
| Estimación de luz | `light-estimation` → `XREstimatedLight` (SH + luz principal) | `environmentTexturing = .automatic` + `ARLightEstimate` | `LightEstimationMode.ENVIRONMENTAL_HDR` |
| Sombras suaves sobre la mesa real | `ShadowMaterial` en el plano `ShadowCatcher` + blob de contacto | `ModelEntity` con `GroundingShadowComponent` | `ShadowCatcher` del motor / `planeRenderer` con sombras |

### 1.2 Máquina de estados

```
           ┌────────────── reset (A en Quest / «Reubicar») ──────────────┐
           ▼                                                             │
 INICIO ──► BUSCANDO ──hit horizontal──► SUPERFICIE ──tap / gatillo──► COLOCADO
               ▲                             │                           │
               └─────── sin hit / vertical ──┘          ancla perdida ──► (sigue COLOCADO, HUD «Recuperando…»)
```

| Estado | Retícula | HUD (título · detalle) |
|---|---|---|
| BUSCANDO, sin hit | Flota 0,55 m adelante, de cara a la cámara; anillo tenue y arcos girando | «Buscá una superficie plana» · «Mové el teléfono despacio sobre la mesa» |
| BUSCANDO, hit vertical | Pegada a la pared, sin punto | «Apuntá a una superficie horizontal» |
| SUPERFICIE | Se aplana sobre el plano; arcos quietos; punto amarillo con pulso; huella punteada a escala real | «Tocá para colocar» (Quest: «Gatillo o pellizco para colocar») |
| COLOCADO | Oculta | «Caminá alrededor» · ayuda del modelo |
| Seguimiento limitado (`emulatedPosition`) | Sin cambios | «Seguimiento limitado» · «Mové el teléfono más despacio y con más luz» |

### 1.3 Retícula (`MedicionReticle`)

- Anillo exterior blanco: r = 46–51 mm a 1 m.
- Cuatro arcos amarillos (`#FFD60A`): r = 34–39 mm.
- Punto central amarillo: r = 6,5 mm, con pulso a 0,9 Hz y un halo que se expande y se apaga.
- **Tamaño aparente constante:** el disco escala con la distancia a la cámara, con un límite de 0,3 a 3,5.
- **Huella:** un círculo punteado a escala real con el radio de la base (robot 90 mm, globo 118 mm). No escala con la distancia.
- **Aplanado:** la posición y la orientación se suavizan exponencialmente (`k = 1 − e^(−dt·18)`) entre la pose flotante (de cara a la cámara) y la pose apoyada (normal del plano y giro hacia el usuario). La mezcla `found` (de 0 a 1) controla la opacidad, el giro de los arcos y el punto.
- **Dibujo:** se dibuja sin prueba de profundidad (`depthTest: false`, `renderOrder 999`), siempre por encima de la escena, como un HUD.

### 1.4 Colocación

1. Al tocar en SUPERFICIE, se toma la posición del último hit.
2. Se calcula el giro para que el **frente del modelo** (+Z en glTF, −Y en Blender) mire al usuario: `yaw = atan2(cam.x − p.x, cam.z − p.z)`.
3. Se crea el ancla con `XRFrame.createAnchor` usando el `frame` del evento `selectend`, que está activo durante el evento.
4. En cada cuadro se toma `anchorRoot.matrix = pose(anchorSpace) · Ry(yawOffset)`. Así, si el SLAM corrige su mapa, el objeto lo sigue. El stick del Quest acumula `yawOffset`.
5. El origen (0, 0, 0) de los dos modelos es el **centro inferior de la base**, por lo que el objeto queda apoyado al ras sin ningún desplazamiento.

### 1.5 Interacción después de colocar

- **Mismo rayo para todo:** `targetRaySpace` del `XRInputSource` (toque transitorio en el teléfono, control o mano en el Quest, puntero en el simulador).
- **Toque o arrastre:** `selectstart` y `selectend`. Si el rayo se mueve menos de 0,03 rad en menos de 600 ms, es un toque. Si no, es un arrastre, que en Atlas XR gira el globo: Δspin = −6·Δyaw del rayo.
- **Atlas XR:** los pines son chicos (cabeza de 3,4 mm), por eso cada nodo tiene una esfera de selección invisible de 14 mm. Al tocarla se abre la tarjeta del nodo y el pin late.
- **Brazo:** al tocar una pieza se resalta (emisivo amarillo) y se abre la tarjeta de su articulación.
- **Tarjeta de datos:** un canvas de 1024×640 sobre un plano de 32×20 cm, al costado del objeto y a la derecha de quien mira, orientado hacia la cámara. Una línea guía la une al nodo y sigue al globo mientras gira.
- **Quest:** <kbd>A</kbd> reubica, <kbd>B</kbd> anima el brazo o activa el giro del globo, y el stick derecho rota el objeto sobre su normal. El HUD va anclado a la cabeza, a 0,62 m, porque el Quest no tiene DOM overlay.

---

## 2. Proyecto 1 · Brazo robótico

| Ítem | Valor |
|---|---|
| Triángulos | 8.122 (meta: 8.000–12.000) |
| Lados de los cilindros | 24 en las articulaciones grandes, 16 en las piezas chicas |
| Detalle horneado | Tornillos, chaflanes, juntas y placa «Universidad Tecnológica · ITR Norte» en el normal map |
| Escala | 1:1. Base Ø 18 cm, alcance con el brazo extendido 0,88 m, altura erguido 1,09 m |
| Origen | (0, 0, 0) en el centro inferior de `Base_Mesh` |
| Material | `M_Robot6Ejes`, un atlas de 2048² Metallic-Roughness: aluminio cepillado, tapas azul UR y juntas de goma negra mate. BaseColor, ORM (R = AO, G = rugosidad, B = metal) y Normal OpenGL |
| Colisiones | `UCX_Base`, `UCX_Shoulder`, `UCX_Upper_Arm`, `UCX_Elbow`, `UCX_Wrist_1`, `UCX_Wrist_2`, `UCX_Wrist_3`, todas convexas y cada una hija de su pieza |

**Jerarquía y pivotes.** Cada pivote está en el centro de giro, con el **Z local alineado al eje de giro** (en glTF y three.js pasa a ser el Y local):

```
Base_Mesh                (fija)                     pivote (0, 0, 0)        eje Z
└─ Shoulder_Joint        J1 base giratoria          (0, 0, 0,096)           Z  (vertical)
   └─ Upper_Arm          J2 hombro                  (0, 0,064, 0,165)       Y  (horizontal)
      └─ Elbow_Joint     J3 codo                    (0, 0,068, 0,565)       Y
         └─ Wrist_1      J4 muñeca 1                (0, 0,062, 0,925)       Y
            └─ Wrist_2   J5 muñeca 2                (0, 0,112, 0,986)       Z
               └─ Wrist_3  J6 brida ISO 9409        (0, 0,170, 1,025)       Y
```

> La especificación original lista `Base_Mesh → Shoulder_Joint → Elbow_Joint → Wrist_1 → Wrist_2 → Wrist_3`, pero pide **6 articulaciones**. Con esa lista solo hay 5 nodos móviles. Por eso se mantiene `Upper_Arm` (J2) entre el hombro y el codo, como en el UR real. Los nombres `Wrist_1/2/3` quedan como se pidieron.

**FK en tiempo de ejecución:** `joint.quaternion = rest · Quaternion(Y, θ)` en three.js. En Unity se aplica el giro sobre el eje Y local de cada transform. En Unreal, sobre el Z local si se importa con Z arriba.

---

## 3. Proyecto 2 · Atlas XR

| Ítem | Valor |
|---|---|
| Triángulos | 9.760 en total: esfera 3.920 (56 × 36), base y meridiano 1.472, 39 nodos 2.020, 12 rutas 2.348 |
| Escala | Globo Ø 45 cm, centro a 0,316 m, altura total 0,566 m, base de nogal Ø 23,6 cm |
| Origen | (0, 0, 0) en el centro inferior de la base: apoya al ras sobre la mesa |
| Inclinación | 23,5° hacia +X; meridiano de bronce graduado (marcas cada 5°, largas cada 15°) |
| Orientación en reposo | Uruguay (−56°) mirando al frente (−Y en Blender, +Z en glTF). Propiedad `lon_offset_deg = −34` |
| Material | `M_AtlasXR`, un atlas de 2048² con BaseColor, ORM, Normal y **Emisivo** (rutas, nodos y una costa cian tenue) |
| Rugosidad | Océano 0,30, tierra 0,78, hielo 0,58 |
| Colisiones | `UCX_Atlas_Base`, `UCX_Stem` y `UCX_Globe` (esta última hija del globo) |
| Datos | 30 puertos, 8 pasos estratégicos y Montevideo, más 12 corredores, todos con fuente, de *Atlas Portuario XR*. Montevideo: 857.491 TEU en 2025 (ANP, dato preliminar) |

**Distribución del atlas (píxeles; v = 1 − y/2048):**

| Región | x, y, ancho, alto | Contenido |
|---|---|---|
| Tierra | 0, 0, 2048, 1016 | Equirectangular: u = (lon + 180)/360. Blue Marble más costas Natural Earth 1:50m, con tierra realzada y costa emisiva |
| Madera | 8, 1032, 1008, 504 | Nogal torneado |
| Bronce | 1032, 1032, 1008, 248 | Bronce cepillado (metal 1) |
| Meridiano | 1032, 1296, 1008, 56 | Graduación grabada |
| Muestras | 1032, 1368, 1008, 56 | 20 colores de 48 px: 7 regiones, 12 corredores y el vástago. Los de regiones y corredores también van al mapa emisivo |
| Placa | 8, 1552, 1008, 120 | «ATLAS XR · Universidad Tecnológica · ITR Norte» |

**Jerarquía:**

```
Atlas_Base                         (fija; base, vástago, meridiano, pernos y placa)
└─ Globe_Sphere                    pivote en el centro; Z local = eje terrestre (23,5°)
   ├─ Logistics_Nodes_Group        identidad: los pines giran con el globo
   │  └─ Node_<id> × 39            origen en la superficie, Z local = normal; extras: id, name, country, kind,
   │                               region, lat, lon, teu, year, src, info, status, color
   └─ Logistics_Routes
      └─ Route_01 … Route_12       tubos de 3 lados a 3,5 mm sobre el océano, por círculo máximo entre puntos de paso
```

**Girar el globo:** `Globe_Sphere.quaternion = q_inclinación · Quaternion(Y, giro)` (Y local en glTF). Así los nodos y las rutas se mueven con él.

---

## 4. Pipelines de exportación

| Archivo | Para | Cómo |
|---|---|---|
| `X.glb` | Android (Scene Viewer, ARCore), Quest, motores | glTF 2.0 binario, Y arriba, PNG, tangentes, `extras` |
| `X_web.glb` | Navegador del Quest, web | Igual, con texturas WebP (`EXT_texture_webp`): el globo baja de 5,7 MB a 1,3 MB |
| `X_motor.glb` | Unity / Unreal / Godot | Incluye las `UCX_*` |
| `gltf/X.gltf` | Edición y versionado | `.gltf` + `.bin` + texturas separadas |
| `X.usdz` | iPhone / iPad (AR Quick Look) | USD de Blender: Y arriba, metros, `UsdPreviewSurface` con BaseColor, ORM, Normal y Emisivo |

**Scripts:**

- `atlas-xr/fuente/build_atlas.py`: arma el globo desde cero. Hace la geometría, la limpieza (soldado, caras degeneradas, n-gonos triangulados), aplica escala y rotación sin tocar los pivotes de giro, pinta las texturas, arma el material y exporta todo. Uso: `python3 build_atlas.py --out salida` o `blender -b -P build_atlas.py -- --out salida`.
- `robot-6-ejes/fuente/build_robot.py`: arma el robot, hornea las texturas (AO y normal desde el high-poly en Cycles) y exporta todo.
- `herramientas/exportar_ar.py`: pipeline genérico desde cualquier `.blend`. Verifica antes de exportar:
  - una sola raíz;
  - escala 1 en todos los objetos;
  - raíz en el origen y geometría apoyada en z = 0;
  - presupuesto de triángulos;
  - un solo material;
  - UV en todas las mallas;
  - `UCX_*` fuera del render.

  Aplica escala y rotación en la raíz, exporta los cinco formatos y escribe `X_reporte.json`. Uso: `python3 exportar_ar.py modelo.blend --out salida --max-tris 12000`.

**Reglas que cumplen los dos modelos:**

- Unidades en metros y escala 1 en todos los objetos.
- Las rotaciones solo están donde son ejes de giro.
- Un material y un atlas de 2048² por modelo.
- `doubleSided = false`.
- La sombra va en un `ShadowCatcher` aparte: alfa 0 en glTF y marcado `extras.shadow_catcher`. En el visor se reemplaza por `ShadowMaterial`.

---

## 5. Pseudocódigo

### 5.1 WebXR (lo implementado: `ar-mesa/slam-colocacion.js`)

```js
session = navigator.xr.requestSession('immersive-ar', {
  requiredFeatures: ['hit-test'],
  optionalFeatures: ['anchors', 'light-estimation', 'dom-overlay', 'plane-detection', 'local-floor'],
  domOverlay: { root: hudOverlay } })
ref        = renderer.xr.getReferenceSpace()            // 'local'
viewerHit  = session.requestHitTestSource({ space: viewerSpace })        // centro de pantalla
ctrlHit    = session.requestHitTestSource({ space: rightController.targetRaySpace })   // Quest (si hay)

onFrame(frame):
  planes.update(frame.detectedPlanes)                    // malla de puntos sobre planos horizontales
  if state == COLOCADO:
     pose = frame.getPose(anchor.anchorSpace, ref)       // el SLAM puede corregir el ancla
     anchorRoot.matrix = pose ? pose.matrix · Ry(yawOffset) : último
  else:
     r = frame.getHitTestResults(ctrlHit ?? viewerHit)[0]
     hit = r ? { matrix: r.getPose(ref), horizontal: (R·Ŷ).y > cos 22° } : null
     state = hit?.horizontal ? SUPERFICIE : BUSCANDO
  reticle.update(dt, camera, hit)                        // flota ↔ se aplana, pulso, huella
  hud.show(HUD[state][dispositivo])

onSelectEnd(e):                                          // e.frame está activo durante el evento
  if esToque and state == SUPERFICIE:
     p = hit.position;  q = Ry(atan2(cam.x − p.x, cam.z − p.z))
     anchor = await e.frame.createAnchor(XRRigidTransform(p, q), ref)
     anchorRoot.visible = true;  state = COLOCADO
  elif esToque and state == COLOCADO:
     ray = e.frame.getPose(e.inputSource.targetRaySpace, ref)
     abrirTarjeta(raycast(ray, pickables))

XREstimatedLight 'estimationstart' → scene.environment = luz.environment; sombra.dir = luz.directionalLight.position
```

### 5.2 iOS nativo: ARKit + RealityKit con la interfaz de Medición

```swift
let config = ARWorldTrackingConfiguration()
config.planeDetection = [.horizontal]
config.environmentTexturing = .automatic                  // luz e IBL estimadas
if ARWorldTrackingConfiguration.supportsSceneReconstruction(.mesh) { config.sceneReconstruction = .mesh } // LiDAR
arView.session.run(config)
arView.environment.lighting.resource = nil               // usa la del entorno
let coaching = ARCoachingOverlayView(); coaching.goal = .horizontalPlane   // opcional, como Medición

var estado = .buscando, reticula = ReticleEntity()        // ModelEntity con anillo, arcos y punto (unlit)
arView.scene.addAnchor(AnchorEntity(.camera)).addChild(reticula.flotante)

func session(_ s: ARSession, didUpdate frame: ARFrame):  // ~60 Hz
  if estado == .colocado { return }
  let centro = CGPoint(x: arView.bounds.midX, y: arView.bounds.midY)
  if let r = arView.raycast(from: centro, allowing: .estimatedPlane, alignment: .horizontal).first {
     reticula.apoyar(en: r.worldTransform, suavizado: 1 - exp(-dt*18))   // aplanar
     estado = .superficie; hud("Tocá para colocar")
  } else {
     reticula.flotar(frente: frame.camera.transform, a: 0.55)
     estado = .buscando; hud("Buscá una superficie plana")
  }
  if case .limited = frame.camera.trackingState { hud("Seguimiento limitado") }

@objc func tap(_ g: UITapGestureRecognizer):
  if estado == .superficie, let r = arView.raycast(from: centro, allowing: .estimatedPlane, alignment: .horizontal).first {
     let ancla = AnchorEntity(raycastResult: r)           // ancla espacial
     let modelo = try! Entity.load(named: "AtlasXR.usdz") // o Robot6Ejes.usdz; origen = centro inferior
     modelo.orientation = simd_quatf(angle: yawHacia(camara, r.worldTransform), axis: [0,1,0])
     modelo.components.set(GroundingShadowComponent(castsShadow: true))
     modelo.generateCollisionShapes(recursive: true)      // para tocar nodos
     ancla.addChild(modelo); arView.scene.addAnchor(ancla)
     estado = .colocado; reticula.ocultar(); UIImpactFeedbackGenerator(style: .light).impactOccurred()
  } else if estado == .colocado, let e = arView.entity(at: g.location(in: arView)), let nodo = e.ancestro(prefijo: "Node_") {
     mostrarTarjeta(nodo)                                 // Entity con texto o un SwiftUI attachment
  }
// Girar el globo: UIPanGestureRecognizer → globe.transform.rotation = qInclinacion * simd_quatf(angle: giro, axis: [0,1,0])
```

### 5.3 Android nativo: ARCore + SceneView/Filament

```kotlin
config.planeFindingMode = Config.PlaneFindingMode.HORIZONTAL
config.lightEstimationMode = Config.LightEstimationMode.ENVIRONMENTAL_HDR
config.depthMode = if (session.isDepthModeSupported(AUTOMATIC)) AUTOMATIC else DISABLED
config.instantPlacementMode = Config.InstantPlacementMode.LOCAL_Y_UP   // retícula antes de tener plano

onUpdate(frame):
  if (frame.camera.trackingState != TRACKING) { hud("Seguimiento limitado"); return }
  if (estado == COLOCADO) { modelo.worldPose = ancla.pose · Ry(yawOffset); return }
  val hit = frame.hitTest(width/2f, height/2f).firstOrNull {
      (it.trackable as? Plane)?.let { p -> p.type == HORIZONTAL_UPWARD_FACING && p.isPoseInPolygon(it.hitPose) } == true }
  if (hit != null) { reticula.apoyar(hit.hitPose); estado = SUPERFICIE; hud("Tocá para colocar") }
  else { reticula.flotar(frame.camera.pose, 0.55f); estado = BUSCANDO; hud("Buscá una superficie plana") }
  luz.aplicar(frame.lightEstimate)                       // SH + dirección principal → sombra

onTap():
  if (estado == SUPERFICIE) {
     ancla = hit.createAnchor()                          // o session.hostCloudAnchor(ancla) para compartir
     modelo = ModelNode("AtlasXR.glb", centerOrigin = null)   // el origen ya es el centro inferior
     modelo.rotation = yawHacia(camara); anclaNode.addChild(modelo)
     estado = COLOCADO
  } else if (estado == COLOCADO) {
     scene.hitTest(motionEvent)?.node?.ancestro("Node_")?.let { mostrarTarjeta(it.extras) }   // extras del glTF
  }
```

### 5.4 Meta Quest nativo: Unity + Meta XR SDK (passthrough)

```csharp
// OVRManager: Passthrough activado; OVRCameraRig con OVRPassthroughLayer (underlay)
// Mesas y piso desde el Space Setup: MRUK (Mixed Reality Utility Kit)
await MRUK.Instance.LoadSceneFromDevice();
var mesas = MRUK.Instance.GetCurrentRoom().Anchors.Where(a => a.HasAnyLabel(TABLE | FLOOR));

void Update() {
  var ray = new Ray(controlDerecho.position, controlDerecho.forward);   // o OVRHand.PointerPose
  if (estado != COLOCADO && room.Raycast(ray, 5f, out RaycastHit h, out MRUKAnchor a)
      && Vector3.Dot(h.normal, Vector3.up) > Mathf.Cos(22 * Mathf.Deg2Rad)) {
    reticula.Apoyar(h.point, h.normal); estado = SUPERFICIE; Hud("Gatillo o pellizco para colocar");
  } else if (estado != COLOCADO) { reticula.Flotar(cabeza, 0.55f); estado = BUSCANDO; }
  if (OVRInput.GetDown(OVRInput.Button.PrimaryIndexTrigger) && estado == SUPERFICIE) Colocar(h.point);
  if (OVRInput.GetDown(OVRInput.Button.One)) Reubicar();                 // A
  ancla.transform.Rotate(0, OVRInput.Get(OVRInput.Axis2D.SecondaryThumbstick).x * -90 * Time.deltaTime, 0);
}
async void Colocar(Vector3 p) {
  var go = new GameObject("Ancla"); go.transform.SetPositionAndRotation(p, YawHacia(cabeza, p));
  var spatial = go.AddComponent<OVRSpatialAnchor>();                    // ancla persistente
  await spatial.WhenLocalizedAsync(); await spatial.SaveAnchorAsync();   // sobrevive a reinicios
  Instantiate(modeloPrefab, go.transform);                               // AtlasXR_motor.glb vía glTFast, con UCX → MeshCollider convexos
  estado = COLOCADO;
}
// Sombras: material "Shadow Receiver" de Meta en un quad sobre la mesa + luz direccional fija (Quest no estima luz)
```

---

## 6. Verificación hecha

- **Robot:** 8.122 tris; escala 1; pivotes con Z = eje de giro; jerarquía `Base_Mesh › Shoulder_Joint › Upper_Arm › Elbow_Joint › Wrist_1 › Wrist_2 › Wrist_3`; 7 colisiones UCX.
- **Globo:**
  - 9.760 tris y z mínimo 0.
  - Eje a 23,50°, con el Z local exportado como Y local en glTF.
  - Un material, sin doble cara.
  - `extras` presentes en los 39 nodos y las 12 rutas.
  - El USDZ incluye las 4 texturas.
- **`exportar_ar.py`:** pasa las verificaciones en los dos `.blend`.
- **Simulador (Chromium):**
  - En el globo y en el brazo, la retícula pasa a SUPERFICIE.
  - El clic ancla el objeto en la mesa (y = 0,75).
  - Tocar Montevideo abre su tarjeta y tocar el codo abre «J3 · Codo».
- **Quest 3 emulado (IWER), con superficie simulada:**
  - Se crea el hit-test desde el control y desde la vista.
  - El gatillo coloca el objeto y se crea el `XRAnchor`.
  - El stick rota el objeto, <kbd>A</kbd> lo reubica y salir restaura la página.
- **Sin probar en hardware real:** el hit-test con el SLAM de un dispositivo físico, la estimación de luz en Android y Quick Look en un iPhone. Hay que probarlos en los equipos.

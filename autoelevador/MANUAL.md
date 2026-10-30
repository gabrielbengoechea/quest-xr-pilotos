# Autoelevador VR · Manual de uso

Entrenamiento de conducción de un autoelevador eléctrico contrapesado de 2.500 kg (**ORIENTAL E25**, marca ficticia) en un
centro de distribución uruguayo. Funciona en el **Meta Quest** (VR, sentado), en la computadora y en el celular.

**Abrir:** <https://gabrielbengoechea.github.io/quest-xr-pilotos/autoelevador/>

## Tareas

| # | Tarea | Qué se evalúa |
|---|---|---|
| 1 | Arranque seguro | Llave, inversor en Adelante y parada de emergencia liberada |
| 2 | Slalom entre conos | Pasar 5 conos en zigzag sin tocarlos |
| 3 | Retiro de lácteos | Tomar el pallet por los huecos y dejarlo en la Zona A |
| 4 | Estantería · nivel medio | Tambores de combustible al nivel de 1,50 m |
| 5 | Estantería · nivel alto | Transformador al nivel de 3,00 m |
| 6 | Carne de exportación | Llevarla a la Zona C, junto al portón del muelle |

El aro azul marca la carga y el verde, el destino. Se cuentan el tiempo, los choques (a más de 2 km/h) y los conos derribados.

## Meta Quest

| Control | Acción |
|---|---|
| Gatillo derecho / izquierdo | Acelerador / freno |
| Grip sobre la perilla del volante | Girar el volante con la mano (también: stick izquierdo ← →) |
| Grip sobre una palanca de la consola (derecha) | Tirar o empujar: elevar (roja), inclinar (amarilla), desplazar (celeste) |
| Stick derecho ↑ ↓ / ← → | Horquillas arriba/abajo / desplazador lateral |
| Stick izquierdo ↑ ↓ | Inclinar el mástil |
| A | Inversor: Adelante → Neutro → Reversa |
| B o grip en la llave | Encender / apagar |
| X o grip en el hongo rojo | Parada de emergencia |
| Y | Recentrar la vista en el asiento |

La visera del techo muestra la tarea y los avisos; la pantalla del tablero, la velocidad, la altura de las horquillas, el inversor y la batería.
Los espejos laterales y el espejo convexo central muestran lo que pasa atrás.

## Computadora

<kbd>W</kbd>/<kbd>S</kbd> acelerar y frenar · <kbd>A</kbd>/<kbd>D</kbd> volante · <kbd>↑</kbd>/<kbd>↓</kbd> horquillas ·
<kbd>Q</kbd>/<kbd>E</kbd> inclinar · <kbd>←</kbd>/<kbd>→</kbd> desplazador · <kbd>F</kbd> <kbd>N</kbd> <kbd>R</kbd> inversor ·
<kbd>K</kbd> llave · <kbd>X</kbd> parada · <kbd>C</kbd> cámara exterior o de cabina.

## Tomar y dejar un pallet

1. Horquillas abajo (o a la altura del nivel), de frente al lado de 80 cm del pallet.
2. Entrar despacio hasta que las palas queden dentro de los huecos; corregir con el desplazador lateral.
3. Subir: cuando las palas tocan el tablero, el pallet queda tomado. Inclinar un poco hacia atrás.
4. Ubicarlo sobre la zona o el nivel y bajar; cuando se apoya, salir en reversa.

## Archivos para Unity, Unreal y Blender

| Archivo | Contenido |
|---|---|
| `modelo/Autoelevador.glb` · `.fbx` | Autoelevador, 18.718 triángulos, jerarquía y pivotes; el `.fbx` incluye `UCX_*` |
| `modelo/Deposito.glb` · `.fbx` | Nave, estanterías, pallets, cargas y conos, 9.486 triángulos; nodos de juego y `extras` |
| `modelo/*_web.glb` | Igual, con texturas WebP (para WebXR) |
| `fuente/Autoelevador_Deposito.blend` | Escena de Blender |
| `fuente/texturas/` | `Atlas_Forklift_PBR_*` y `Atlas_Environment_PBR_*`: BaseColor, Normal (OpenGL), ORM, Metallic, Roughness, AO |
| `fuente/*.py` | Scripts que generan todo: `blender -b -P build_autoelevador.py -- --out ./salida` |

### Jerarquía del autoelevador

```
Forklift_Root (suelo, mitad del eje delantero)
├ Chassis ─ Mirror_Left · Mirror_Right · Mirror_Center (materiales M_Mirror_*, UV 0..1 para render-to-texture)
├ Mast_Outer_Stage (inclinación: X local)
│ └ Mast_Inner_Stage (elevación: Z local)
│   └ Fork_Carriage (elevación libre: Z local · desplazamiento: X local)
│     ├ Fork_Left · Fork_Right (separación: X local)
├ Wheel_Front_Left · Wheel_Front_Right (giro: X local)
├ Rear_Axle ─ Steer_Knuckle_Left/Right (dirección: Z local) ─ Wheel_Rear_Left/Right
├ Steering_Wheel (eje de la columna: Z local) ─ Spinner_Knob
├ Lever_Lift · Lever_Tilt · Lever_Sideshift · Pedal_Accel · Pedal_Brake · Shuttle_Switch (bisagra: X local)
├ Key_Ignition (Z local a lo largo de la llave) · Emergency_Stop (Z local: se hunde)
```

Los ejes son los de Blender (Z arriba). En glTF el Z local de cada pieza pasa a ser su **Y local**.
Colisiones: `UCX_Fork_Left`, `UCX_Fork_Right` (cajas exactas de las palas), `UCX_Chassis` (casco convexo), `UCX_Wheels`.

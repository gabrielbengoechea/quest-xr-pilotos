# Robot de 6 ejes · Manual de uso

Brazo robótico industrial de 6 ejes (tipo cobot) a escala real, con la placa **Universidad Tecnológica · ITR Norte**.
Base de 18 cm, alcance de unos 88 cm, 8.122 triángulos y un solo material PBR.

**Abrir:** <https://gabrielbengoechea.github.io/quest-xr-pilotos/robot-6-ejes/>

## En la computadora o el celular

| Acción | Cómo |
|---|---|
| Girar la vista | Arrastrar (un dedo en el celular) |
| Acercar | Rueda del mouse o pellizco |
| Desplazar | Clic derecho o dos dedos |
| Mover una articulación | Su control deslizante, o <kbd>1</kbd>–<kbd>6</kbd> para elegir y <kbd>←</kbd> <kbd>→</kbd> para girar |
| Poses rápidas | Erguido, Inicio, Tomar, Dejar |
| Demostración | Interruptor «Demostración» o <kbd>Espacio</kbd>: el robot toma una caja y la deja del otro lado |
| Ejes de giro | Interruptor «Mostrar ejes»: una flecha naranja por articulación |

## En el Meta Quest (VR)

1. Abrir la página en el navegador del Quest y tocar **Entrar en VR**.
2. El robot aparece sobre una mesa virtual; a su izquierda hay un panel de vidrio.
3. **Gatillo** sobre el panel: elegir articulación (J1–J6), girarla de a 15°, cambiar de pose, iniciar la demostración o mostrar los ejes.
4. **Stick derecho ← →**: girar de forma continua la articulación elegida.
5. **Grip** (botón lateral): tomar el robot con la mano y moverlo; al soltarlo queda derecho.
6. **B** o **Y**: volver a ubicar el robot frente a vos.

## Sobre una mesa real (realidad mixta)

1. Quest: marcar la mesa en *Configuración › Entorno físico › Configuración del espacio* (en Android no hace falta).
2. Tocar **Ver en tu mesa** y aceptar el permiso del espacio.
3. Apuntar a la mesa hasta ver el aro azul y apretar el **gatillo** (o tocar la pantalla): la base queda al ras y proyecta sombra.
4. Para cambiarlo de lugar: botón **Recolocar** del panel, o **B/Y**.
5. iPhone y iPad: **Ver en AR** abre el modelo en Quick Look.

## Articulaciones

| Eje | Pieza (nodo) | Movimiento |
|---|---|---|
| J1 | `Shoulder_Joint` | Base: gira todo el brazo sobre la vertical |
| J2 | `Upper_Arm` | Hombro: sube o baja el brazo superior |
| J3 | `Elbow_Joint` | Codo: pliega el antebrazo |
| J4 | `Wrist_1` | Muñeca 1 |
| J5 | `Wrist_2` | Muñeca 2 |
| J6 | `Wrist_3` | Brida de herramienta |

## Archivos

| Archivo | Para qué |
|---|---|
| `modelo/Robot6Ejes_web.glb` | WebXR y three.js (texturas WebP, ~1 MB). Es el que usa esta página |
| `modelo/Robot6Ejes.glb` | Texturas PNG: Android Scene Viewer y cualquier visor glTF |
| `modelo/Robot6Ejes_motor.glb` | Incluye colisiones `UCX_*` para Unity, Unreal o Godot |
| `modelo/Robot6Ejes.usdz` | iPhone y iPad (Quick Look) |
| `fuente/Robot6Ejes.blend` | Escena de Blender 5.2 con el high-poly de horneado y las colisiones |
| `fuente/build_robot.py` | Regenera todo: `blender -b --factory-startup -P build_robot.py -- --out ./salida` |

**Para programadores:** en glTF cada articulación gira sobre su **eje Y local** (el Z local de Blender); el origen es el
centro de la cara inferior de la base, apoyado en y = 0. El nodo `ShadowCatcher` trae `extras.shadow_catcher = true`:
reemplazar su material por `THREE.ShadowMaterial` para proyectar sombras en realidad aumentada.

Modelo ilustrativo inspirado en los cobots industriales; no reproduce ninguna marca comercial.

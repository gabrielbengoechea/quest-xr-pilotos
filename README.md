# Pilotos XR para Meta Quest

Aplicaciones WebXR (three.js r186) pensadas para Meta Quest 2 y preparadas para Quest 3.
No requieren instalación: se abren desde el navegador del visor.

| App | Archivo | Qué hace |
|---|---|---|
| Atlas Portuario XR | `atlas.html` | Globo en realidad mixta con 30 puertos (5 por región), 8 pasos estratégicos, 12 corredores y vistas 360° de Wikimedia Commons |
| Motor turbofán | `motor-jet/index.html` | Vista explosionada de un motor de reacción en 5 niveles, colocada sobre la mesa |
| Centro Logístico 3D | [fork de logi](https://github.com/gabrielbengoechea/logi) | Recorrido a pie en VR por una nave de distribución |
| Logística 3D | [fork de logistica3d](https://github.com/gabrielbengoechea/logistica3d) | Recorrido a pie en VR por la terminal de Montevideo |
| Estiba | [fork de Estiba-VR](https://github.com/gabrielbengoechea/Estiba-VR) | Exploración libre en VR de una terminal de contenedores |

## Cómo usarlas en el Quest

1. Activar **GitHub Pages** en este repositorio (Settings › Pages › rama `main`, carpeta `/`).
2. En el visor, marcar la mesa en *Ajustes › Entorno físico › Configuración del espacio*.
3. Abrir `https://<usuario>.github.io/quest-xr-pilotos/` en el navegador del Quest y elegir la app.
4. Aceptar el permiso de acceso al espacio al entrar en realidad mixta.

WebXR exige HTTPS; GitHub Pages ya lo provee.

## Controles comunes

- **Gatillo:** colocar en la mesa / seleccionar
- **Grip:** tomar y mover el modelo
- **Thumbstick:** girar y ajustar (despiece o tamaño según la app)
- **B/Y:** volver a colocar

## Datos del Atlas

TEU de 2024–2025 o año fiscal según la región (indicado en cada ficha); estado de los pasos estratégicos a octubre de 2026.
Fuentes: DynaLiners (vía Container News), estudio de R. J. Sánchez publicado por MundoMarítimo, autoridades portuarias,
Lloyd's List One Hundred Ports 2025, EIA (World Oil Transit Chokepoints), BIMCO/Clarksons, Autoridad del Canal de Panamá,
IMF PortWatch. Las imágenes 360° se consultan en vivo en Wikimedia Commons y muestran autor y licencia.

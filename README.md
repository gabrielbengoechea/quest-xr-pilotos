# Quest XR Pilots

> Browser-based WebXR pilots for Meta Quest — logistics, industry and engineering experiences that open straight from the headset browser, with no installation.

**[▶ Open the portal](https://gabrielbengoechea.github.io/quest-xr-pilotos/)** · Interfaces in Spanish · [Leer en español](README.es.md)

Built with three.js (r186) and WebXR, designed for Meta Quest 2 and prepared for Quest 3. Several pilots also run on Android and iPhone.

## Pilots

| App | Path | What it does |
|---|---|---|
| **Port Atlas XR** | [`atlas.html`](atlas.html) | Mixed-reality globe with 30 ports (5 per region), 8 strategic chokepoints, 12 shipping corridors and 360° views from Wikimedia Commons |
| **Turbofan engine** | [`motor-jet/`](motor-jet/index.html) | Exploded view of a jet engine in 5 levels, placed on a real table |
| **Forklift VR** | [`autoelevador/`](autoelevador/index.html) | Forklift driving training in a Uruguayan warehouse: 6 tasks, steering wheel, levers, mirrors and pallets ([manual](autoelevador/MANUAL.md)) |
| **6-axis robot** | [`robot-6-ejes/`](robot-6-ejes/index.html) | Full-scale industrial arm with joints, poses, demo mode and tabletop placement (VR, mixed reality, Android and iPhone Quick Look) ([manual](robot-6-ejes/MANUAL.md)) |
| **Tabletop AR** | [`ar-mesa/`](ar-mesa/index.html) | SLAM-style placement (reticle, hit-test, anchor, light estimation, shadows) for the robot and Atlas XR on Quest passthrough, Android (ARCore) and iPhone ([spec](ar-mesa/ESPECIFICACION.md)) |
| **Atlas XR model** | [`atlas-xr/`](atlas-xr/) | 45 cm tabletop logistics globe: 9,760 triangles, 39 data nodes, 12 emissive routes; glTF, USDZ and Blender sources with the generator script |

The portal also links to VR walkthroughs I added to forks of simulators by [@sr-sebastian](https://github.com/sr-sebastian): [Centro Logístico 3D](https://github.com/gabrielbengoechea/logi), [Logística 3D](https://github.com/gabrielbengoechea/logistica3d) and [Estiba](https://github.com/gabrielbengoechea/Estiba-VR).

## Using them on a Quest

1. Open <https://gabrielbengoechea.github.io/quest-xr-pilotos/> in the Quest browser and choose an app.
2. For mixed reality, set up your table in *Settings › Physical space › Space setup* and accept the space permission.

WebXR requires HTTPS, which GitHub Pages provides.

### Common controls

| Action | Input |
|---|---|
| Place on table / select | Trigger |
| Grab and move the model | Grip |
| Rotate / adjust (explode level or size) | Thumbstick |
| Re-place | B / Y |

## Technology

three.js r186 · WebXR (VR, mixed reality, hit-test, anchors) · glTF / USDZ · Blender (models and generator scripts) · static hosting on GitHub Pages.

## Data sources (Port Atlas)

TEU figures for 2024–2025 or fiscal year depending on the region (stated on each card); chokepoint status as of October 2026. Sources: DynaLiners (via Container News), R. J. Sánchez study published by MundoMarítimo, port authorities, Lloyd's List One Hundred Ports 2025, EIA World Oil Transit Chokepoints, BIMCO/Clarksons, Panama Canal Authority, IMF PortWatch. 360° images are loaded live from Wikimedia Commons with author and license shown.

## Credits & license

- Author: [Gabriel Bengoechea](https://github.com/gabrielbengoechea) — Logistics Engineering, UTEC Uruguay (robot and tabletop AR pilots carry the UTEC ITR Norte plate).
- Developed with AI-assisted coding (Anthropic's Claude), as recorded in the commit history.
- No license has been chosen yet. Third-party images keep their original licenses.

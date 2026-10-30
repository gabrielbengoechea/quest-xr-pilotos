"""
Pipeline de exportación AR: un .blend → todos los formatos que usan Quest, Android/WebXR e iOS.

    python3 exportar_ar.py modelo.blend --out salida [--max-tris 12000]
    blender -b modelo.blend -P exportar_ar.py -- --out salida

Pasos
1. Verifica (y frena si algo está mal): un solo objeto raíz, escala 1 en todo, origen de la raíz en (0,0,0) con la geometría
   apoyada en z = 0, presupuesto de triángulos, un solo material de atlas, UV presentes y colisiones UCX_* fuera del render.
2. Exporta:
   <nombre>.glb          glTF binario (PNG): Android / ARCore Scene Viewer, Quest, motores
   <nombre>_web.glb      igual con texturas WebP (EXT_texture_webp): para el navegador del Quest y la web
   <nombre>_motor.glb    con las colisiones UCX_* (para Unity / Unreal / Godot)
   gltf/<nombre>.gltf    glTF separado (.gltf + .bin + texturas) para editar o versionar
   <nombre>.usdz         USD comprimido para AR Quick Look (iPhone/iPad): Y arriba, metros, UsdPreviewSurface
3. Escribe <nombre>_reporte.json con lo verificado.

Los pivotes de las piezas articuladas (rotación = eje de giro) se respetan: solo se aplica escala/rotación en la raíz,
que es la única que tiene que quedar en identidad para apoyar al ras sobre el plano detectado.
"""
import json
import os
import sys

import bpy  # antes que bmesh
from mathutils import Matrix, Vector


def roots():
    return [o for o in bpy.context.scene.objects if o.parent is None and not o.hide_render and not o.name.startswith(("UCX_", "ShadowCatcher"))
            and o.type in {"MESH", "EMPTY"}]


def descendants(ob):
    out = [ob]
    for c in ob.children:
        out += descendants(c)
    return out


def tris(ob):
    return sum(len(p.vertices) - 2 for p in ob.data.polygons) if ob.type == "MESH" else 0


def check(max_tris):
    errs, warns = [], []
    rs = roots()
    if len(rs) != 1:
        errs.append(f"Se esperaba una sola raíz y hay {len(rs)}: {[r.name for r in rs]}")
        return errs, warns, None
    root = rs[0]
    # Aplicar escala y rotación en la raíz (Ctrl+A) si hiciera falta, sin mover los hijos
    if root.matrix_world.to_3x3() != Matrix.Identity(3):
        for o in bpy.context.view_layer.objects:
            o.select_set(False)
        root.select_set(True)
        bpy.context.view_layer.objects.active = root
        bpy.ops.object.transform_apply(location=False, rotation=True, scale=True)
        warns.append("Se aplicó escala/rotación en la raíz")
    if root.matrix_world.translation.length > 1e-5:
        errs.append(f"La raíz no está en el origen: {tuple(round(v, 4) for v in root.matrix_world.translation)}")
    objs = [o for o in descendants(root)]
    meshes = [o for o in objs if o.type == "MESH" and not o.name.startswith("UCX_")]
    for o in objs:
        s = o.matrix_world.to_scale()
        if max(abs(v - 1) for v in s) > 1e-4:
            errs.append(f"{o.name}: escala {tuple(round(v, 4) for v in s)} (aplicar escala)")
    zmin = min((o.matrix_world @ v.co).z for o in meshes for v in o.data.vertices)
    if abs(zmin) > 0.002:
        errs.append(f"La geometría no apoya en z = 0 (z mínimo = {zmin:.4f} m)")
    total = sum(tris(o) for o in meshes)
    if total > max_tris:
        warns.append(f"{total} triángulos (presupuesto {max_tris})")
    mats = {m.name for o in meshes for m in o.data.materials if m}
    if len(mats) != 1:
        warns.append(f"Materiales: {sorted(mats)} (se esperaba un único atlas)")
    for o in meshes:
        if not o.data.uv_layers:
            errs.append(f"{o.name}: sin UV")
    ucx = [o for o in objs if o.name.startswith("UCX_")]
    for o in ucx:
        o.hide_render = True
    dims = Vector((0, 0, 0))
    pts = [o.matrix_world @ v.co for o in meshes for v in o.data.vertices]
    for i in range(3):
        dims[i] = max(p[i] for p in pts) - min(p[i] for p in pts)
    info = dict(raiz=root.name, triangulos=total, materiales=sorted(mats), colisiones=[o.name for o in ucx],
                dimensiones_m=[round(v, 4) for v in dims], z_min=round(zmin, 5), objetos=len(objs))
    return errs, warns, (root, objs, ucx, info)


def select_only(objs):
    for o in bpy.context.view_layer.objects:
        o.select_set(False)
    for o in objs:
        o.hide_set(False)
        o.select_set(True)
    bpy.context.view_layer.objects.active = objs[0]


def gltf(path, objs, fmt="GLB", image_format="AUTO"):
    select_only(objs)
    r = bpy.ops.export_scene.gltf(filepath=path, export_format=fmt, use_selection=True, export_extras=True, export_yup=True,
                                  export_apply=True, export_tangents=True, export_image_format=image_format, export_image_quality=90,
                                  export_materials="EXPORT", export_cameras=False, export_lights=False, export_animations=False)
    assert r == {"FINISHED"}, r


def usdz(path, objs):
    select_only(objs)
    kw = dict(filepath=path, selected_objects_only=True, export_materials=True, generate_preview_surface=True,
              export_uvmaps=True, export_normals=True, convert_orientation=True,
              export_global_forward_selection="NEGATIVE_Z", export_global_up_selection="Y")
    try:
        r = bpy.ops.wm.usd_export(**kw)
    except TypeError:
        for k in ("convert_orientation", "export_global_forward_selection", "export_global_up_selection"):
            kw.pop(k, None)
        r = bpy.ops.wm.usd_export(**kw)
    assert r == {"FINISHED"}, r


def main(blend, out, max_tris):
    if blend:
        bpy.ops.wm.open_mainfile(filepath=blend)
    name = os.path.splitext(os.path.basename(bpy.data.filepath))[0]
    os.makedirs(os.path.join(out, "gltf"), exist_ok=True)
    errs, warns, res = check(max_tris)
    if errs:
        print("ERRORES:\n  " + "\n  ".join(errs))
        sys.exit(1)
    root, objs, ucx, info = res
    shadow = [o for o in bpy.context.scene.objects if o.name.startswith("ShadowCatcher")]
    vis = [o for o in objs if not o.name.startswith("UCX_")] + shadow
    gltf(os.path.join(out, f"{name}.glb"), vis)
    gltf(os.path.join(out, f"{name}_web.glb"), vis, image_format="WEBP")
    gltf(os.path.join(out, f"{name}_motor.glb"), vis + ucx)
    gltf(os.path.join(out, "gltf", f"{name}.gltf"), vis, fmt="GLTF_SEPARATE")
    usdz(os.path.join(out, f"{name}.usdz"), [o for o in objs if o.type == "MESH" and not o.name.startswith("UCX_")])
    info["avisos"] = warns
    info["archivos"] = {f: os.path.getsize(os.path.join(out, f)) for f in sorted(os.listdir(out)) if os.path.isfile(os.path.join(out, f))}
    with open(os.path.join(out, f"{name}_reporte.json"), "w", encoding="utf-8") as f:
        json.dump(info, f, ensure_ascii=False, indent=1)
    print(json.dumps(info, ensure_ascii=False))


if __name__ == "__main__":
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else sys.argv[1:]
    blend = next((a for a in argv if a.endswith(".blend")), None)
    out = argv[argv.index("--out") + 1] if "--out" in argv else "salida"
    mt = int(argv[argv.index("--max-tris") + 1]) if "--max-tris" in argv else 12000
    main(blend, os.path.abspath(out), mt)

"""
Paquete VR «Autoelevador ORIENTAL E25 + Centro Logístico»: arma el autoelevador y el depósito, empaqueta y pinta los dos
atlas PBR, hornea la oclusión, genera colisiones UCX y exporta .glb, .fbx y .blend.

    blender -b --factory-startup -P build_autoelevador.py -- --out ./salida
    python build_autoelevador.py --out ./salida        (con pip install bpy==5.2.*)
"""
import json
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import bpy  # noqa: E402
import bmesh  # noqa: E402
import numpy as np  # noqa: E402
from mathutils import Matrix, Vector  # noqa: E402

import forklift as F  # noqa: E402
import warehouse as WH  # noqa: E402
from kit3d import Atlas, Builder, Painter, axis_m, tris  # noqa: E402


# ---------------------------------------------------------------------------------------------------------------------
# Escena
# ---------------------------------------------------------------------------------------------------------------------
def clean():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    sc = bpy.context.scene
    sc.unit_settings.system = "METRIC"
    sc.unit_settings.scale_length = 1.0
    return sc


def collection(name, parent=None):
    c = bpy.data.collections.new(name)
    (parent or bpy.context.scene.collection).children.link(c)
    return c


def parent_keep(child, parent):
    """Emparenta sin matrix_parent_inverse oculta: la matriz local queda explícita (lo que exportan glTF y FBX)."""
    mw = child.matrix_world.copy()
    child.parent = parent
    child.matrix_parent_inverse = Matrix.Identity(4)
    child.matrix_basis = parent.matrix_world.inverted() @ mw


def empty(name, coll, M=Matrix.Identity(4), size=0.2):
    e = bpy.data.objects.new(name, None)
    e.empty_display_type = "ARROWS"
    e.empty_display_size = size
    coll.objects.link(e)
    e.matrix_world = M
    return e


def ext_material(name, color, rough, metal, emissive=False):
    m = bpy.data.materials.new(name)
    b = next(n for n in m.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
    b.inputs["Base Color"].default_value = (*color, 1)
    b.inputs["Roughness"].default_value = rough
    b.inputs["Metallic"].default_value = metal
    if emissive:
        b.inputs["Emission Color"].default_value = (*color, 1)
        b.inputs["Emission Strength"].default_value = 1.0
    return m


# ---------------------------------------------------------------------------------------------------------------------
# Autoelevador
# ---------------------------------------------------------------------------------------------------------------------
def build_forklift(coll, atlas):
    parts = {}      # nombre → (Builder, pivote, padre, materiales extra)
    root = empty("Forklift_Root", coll, size=0.5)

    def part(name, pivot, parent="Forklift_Root", extra=()):
        b = Builder(atlas, density=F.DENS)
        parts[name] = (b, pivot, parent, list(extra))
        return b

    ch = part("Chassis", Matrix.Identity(4), extra=["Atlas", "M_Dash_Screen"])
    F.build_chassis(ch, {"M_Dash_Screen": 1})

    # Mástil y horquillas
    F.build_mast_outer(part("Mast_Outer_Stage", Matrix.Translation(F.TILT_PIVOT)))
    F.build_mast_inner(part("Mast_Inner_Stage", Matrix.Translation((0, F.MAST_Y, 0.16)), "Mast_Outer_Stage"))
    F.build_carriage(part("Fork_Carriage", Matrix.Translation((0, F.CARRIAGE_Y, 0.28)), "Mast_Inner_Stage"))
    # horquillas a ±0,19 m: entran en los huecos de un pallet EUR por el lado de 800 mm
    F.build_fork(part("Fork_Left", Matrix.Translation((F.FORK_X, F.CARRIAGE_Y - 0.03, 0.62)), "Fork_Carriage"), F.FORK_X)
    F.build_fork(part("Fork_Right", Matrix.Translation((-F.FORK_X, F.CARRIAGE_Y - 0.03, 0.62)), "Fork_Carriage"), -F.FORK_X)

    # Ruedas: delanteras (tracción) y traseras (dirección) con muñones
    F.tire(part("Wheel_Front_Left", Matrix.Translation((F.FRONT_X, 0, F.FRONT_R))), (F.FRONT_X, 0, F.FRONT_R), F.FRONT_R, F.FRONT_W)
    F.tire(part("Wheel_Front_Right", Matrix.Translation((-F.FRONT_X, 0, F.FRONT_R))), (-F.FRONT_X, 0, F.FRONT_R), F.FRONT_R, F.FRONT_W)
    ax = part("Rear_Axle", Matrix.Translation((0, F.REAR_Y, F.REAR_R)))
    ax.box((0.62, 0.12, 0.10), (0, F.REAR_Y, F.REAR_R), mat="grafito")
    ax.cyl(0.06, 0.16, axis_m("Y", (0, F.REAR_Y, F.REAR_R)), 16, "acero")
    for sx, nm in ((1, "Left"), (-1, "Right")):
        kp = Vector((sx * (F.REAR_X - 0.11), F.REAR_Y, F.REAR_R))
        kn = part(f"Steer_Knuckle_{nm}", Matrix.Translation(kp), "Rear_Axle")
        kn.cyl(0.035, 0.16, axis_m("Z", kp), 12, "acero")
        kn.box((0.06, 0.08, 0.06), kp + Vector((sx * 0.05, 0, 0)), mat="grafito")
        wc = (sx * F.REAR_X, F.REAR_Y, F.REAR_R)
        F.tire(part(f"Wheel_Rear_{nm}", Matrix.Translation(wc), f"Steer_Knuckle_{nm}"), wc, F.REAR_R, F.REAR_W, seg=28)

    # Cabina: volante con perilla, inversor, palancas, pedales, llave y parada
    sw = part("Steering_Wheel", axis_m(F.COLUMN_DIR, F.WHEEL_HUB))
    knob = Builder(atlas, density=F.DENS)
    kp = F.build_steering_wheel(sw, knob)
    parts["Spinner_Knob"] = (knob, axis_m(F.COLUMN_DIR, kp), "Steering_Wheel", [])
    sh_base = Vector((F.WHEEL_HUB.x + 0.06, 0.12, 1.12))
    F.build_shuttle(part("Shuttle_Switch", Matrix.Translation(sh_base)), sh_base)
    for i, (nm, col) in enumerate((("Lever_Lift", "rojo"), ("Lever_Tilt", "amarillo"), ("Lever_Sideshift", "celeste"))):
        base = Vector((-0.33, 0.60 + i * 0.055, 1.21))
        F.build_lever(part(nm, Matrix.Translation(base)), base, col)
    for nm, x, w in (("Pedal_Accel", -0.17, 0.10), ("Pedal_Brake", 0.06, 0.16)):
        hinge = Vector((x, 0.02, 0.70))
        F.build_pedal(part(nm, Matrix.Translation(hinge)), hinge, w)
    F.build_key(part("Key_Ignition", axis_m("Y", F.KEY)), F.KEY)
    F.build_estop(part("Emergency_Stop", Matrix.Translation(F.ESTOP + Vector((0, 0, -0.012)))), F.ESTOP + Vector((0, 0, -0.012)))

    # Espejos (vidrios separados con material propio)
    for nm, c, w, h, face in (("Mirror_Left", Vector((0.71, -0.054, 1.80)), 0.18, 0.12, Vector((-0.25, 1, 0))),
                              ("Mirror_Right", Vector((-0.71, -0.054, 1.80)), 0.18, 0.12, Vector((0.25, 1, 0))),
                              ("Mirror_Center", Vector((0, -0.008, 2.05)), 0.34, 0.12, Vector((0, 1, -0.35)))):
        b = part(nm, Matrix.Translation(c), "Chassis", extra=["M_" + nm.replace("Mirror_", "Mirror_")])
        F.build_mirror_glass(b, 0, c, w, h, face)
    return root, parts


# ---------------------------------------------------------------------------------------------------------------------
# Construcción común: objetos, jerarquía, UV del atlas
# ---------------------------------------------------------------------------------------------------------------------
def realize(parts, coll, atlas, root, materials):
    obs = {}
    for name, (b, pivot, par, extra) in parts.items():
        obs[name] = b.to_object(name, coll, pivot)
    scale = atlas.pack()
    for name, (b, pivot, par, extra) in parts.items():
        ob = b.finalize(obs[name])
        mats = extra or ["Atlas"]
        for m in mats:
            ob.data.materials.append(materials[m])
    for name, (b, pivot, par, extra) in parts.items():
        parent_keep(obs[name], obs.get(par) or root)
    bpy.context.view_layer.update()
    return obs, scale


def atlas_material(name, imgs):
    mat = bpy.data.materials.new(name)
    nt = mat.node_tree
    nodes, links = nt.nodes, nt.links
    bsdf = next(n for n in nodes if n.type == "BSDF_PRINCIPLED")

    def tex(img, x, y):
        n = nodes.new("ShaderNodeTexImage")
        n.image = img
        n.location = (x, y)
        return n
    bc = tex(imgs["BaseColor"], -700, 300)
    orm = tex(imgs["ORM"], -700, 0)
    nrm = tex(imgs["Normal"], -700, -300)
    sep = nodes.new("ShaderNodeSeparateColor")
    nm = nodes.new("ShaderNodeNormalMap")
    links.new(bc.outputs["Color"], bsdf.inputs["Base Color"])
    links.new(orm.outputs["Color"], sep.inputs["Color"])
    links.new(sep.outputs["Green"], bsdf.inputs["Roughness"])
    links.new(sep.outputs["Blue"], bsdf.inputs["Metallic"])
    links.new(nrm.outputs["Color"], nm.inputs["Color"])
    links.new(nm.outputs["Normal"], bsdf.inputs["Normal"])
    grp = bpy.data.node_groups.get("glTF Material Output") or bpy.data.node_groups.new("glTF Material Output", "ShaderNodeTree")
    if not grp.interface.items_tree:
        grp.interface.new_socket("Occlusion", in_out="INPUT", socket_type="NodeSocketFloat")
    g = nodes.new("ShaderNodeGroup")
    g.node_tree = grp
    links.new(sep.outputs["Red"], g.inputs["Occlusion"])
    return mat, {"BaseColor": bc, "ORM": orm, "Normal": nrm}


def placeholder_images(prefix, size):
    imgs = {}
    for key, col, nc in (("BaseColor", (0.8, 0.8, 0.8, 1), False), ("ORM", (1, 0.5, 0, 1), True), ("Normal", (0.5, 0.5, 1, 1), True)):
        im = bpy.data.images.new(f"{prefix}_{key}", size, size, alpha=False)
        im.generated_color = col
        im.colorspace_settings.name = "Non-Color" if nc else "sRGB"
        imgs[key] = im
    return imgs


def bake_ao(objs, ao_img, mat, node, samples=32):
    """Oclusión ambiental de todo el conjunto (en pose de reposo) sobre el atlas."""
    sc = bpy.context.scene
    vl = bpy.context.view_layer
    sc.render.engine = "CYCLES"
    sc.cycles.device = "CPU"
    sc.cycles.samples = samples
    sc.render.bake.margin = 8
    sc.render.bake.use_clear = True
    node.image = ao_img
    for n in mat.node_tree.nodes:
        n.select = False
    node.select = True
    mat.node_tree.nodes.active = node
    for o in vl.objects:
        o.select_set(False)
    targets = [o for o in objs if o.type == "MESH" and any(m and m.name == mat.name for m in o.data.materials)]
    for o in targets:
        o.select_set(True)
    vl.objects.active = targets[0]
    r = bpy.ops.object.bake(type="AO", margin=8, use_clear=True, target="IMAGE_TEXTURES")
    assert r == {"FINISHED"}, r
    S = ao_img.size[0]
    return np.array(ao_img.pixels[:], np.float32).reshape(S, S, 4)[::-1, :, 0]


def load_into(img, path):
    img.filepath = path
    img.source = "FILE"
    img.reload()


def quick_render(path, target=(0, 0.6, 1.0), dist=4.2, az=-40, el=18, res=900, lens=45, color="TEXTURE"):
    sc = bpy.context.scene
    sc.render.engine = "BLENDER_WORKBENCH"
    sc.display.shading.light = "STUDIO"
    sc.display.shading.color_type = color
    sc.render.resolution_x = res
    sc.render.resolution_y = res
    cam = bpy.data.objects.new("_cam", bpy.data.cameras.new("_cam"))
    sc.collection.objects.link(cam)
    a, e = math.radians(az), math.radians(el)
    t = Vector(target)
    cam.location = t + Vector((math.cos(e) * math.sin(a), -math.cos(e) * math.cos(a), math.sin(e))) * dist
    cam.rotation_euler = (t - cam.location).to_track_quat("-Z", "Y").to_euler()
    cam.data.lens = lens
    sc.camera = cam
    sc.render.filepath = path
    bpy.ops.render.render(write_still=True)
    bpy.data.objects.remove(cam)


def paint_and_apply(atlas, mats_def, imgs, outdir, name, ao=None):
    p = Painter(atlas, mats_def)
    p.paint_all()
    paths = p.finish(outdir, name, ao=ao)
    for key in ("BaseColor", "ORM", "Normal"):
        load_into(imgs[key], paths[key])
    return paths, p


# ---------------------------------------------------------------------------------------------------------------------
# Depósito
# ---------------------------------------------------------------------------------------------------------------------
PICKUP = [("lacteos", (-6.0, 1.5)), ("combustible", (-3.0, 1.5)), ("transformador", (0.0, 1.5)), ("carne", (3.0, 1.5))]
ZONES = [("A", (5.2, -6.6)), ("B", (8.2, -6.6)), ("C", (11.2, -6.6))]
CONES_X = [-10.0, -7.0, -4.0, -1.0, 2.0]
SLALOM_Y = -2.6
SPAWN = (-9.5, -7.2, math.pi)        # x, y, giro (el autoelevador mira hacia +Y)


def build_environment(coll, atlas):
    parts = {}
    root = empty("Warehouse_Root", coll, size=1.0)
    gameplay = []   # (nombre, matriz, extras) → empties de juego

    def part(name, pivot, parent="Warehouse_Root"):
        b = Builder(atlas, density=WH.DENS)
        parts[name] = (b, pivot, parent, [])
        return b

    bld = part("Building", Matrix.Identity(4))
    WH.build_building(bld)
    for z, c in ZONES:
        WH.build_drop_zone(bld, c, label=f"ZONA {z}")
        gameplay.append((f"DropZone_{z}", Matrix.Translation((c[0], c[1], 0)), {"zona": z, "ancho": 1.8, "largo": 2.2}))
    WH.build_slalom_lane(bld, CONES_X[0] - 1.5, CONES_X[-1] + 1.5, SLALOM_Y)
    # lugar de inicio pintado en el piso
    WH._floor_quad(bld, (SPAWN[0], SPAWN[1] + 0.6), 1.6, 3.4, "negro", [("text", ["INICIO", "ORIENTAL E25"], "#ffffff", None, 0.0)],
                   density=60)
    gameplay.append(("Spawn_Forklift", Matrix.Translation((SPAWN[0], SPAWN[1], 0)) @ Matrix.Rotation(SPAWN[2], 4, "Z"), {"inicio": True}))

    racks = part("Racks", Matrix.Translation((0, WH.RACK_Y, 0)))
    x0, width = WH.build_racks(racks)
    slots = WH.rack_slots(x0)
    # pallets: 4 cargados en la zona de retiro, 5 ya ubicados en la estantería, 3 vacíos apilados
    n = 0

    def pallet(c, rot=0.0, cargo=None):
        nonlocal n
        n += 1
        name = f"Pallet_{n:02d}"
        pv = Matrix.Translation(Vector(c)) @ Matrix.Rotation(rot, 4, "Z")
        WH.build_pallet(part(name, pv), c, rot)
        extras = {"pallet": True, "masa_kg": 25}
        if cargo:
            cb = part(f"Carga_{n:02d}", pv, name)
            label, kg = WH.build_cargo(cb, cargo, (c[0], c[1], c[2] + WH.PALLET[2]), rot)
            extras.update({"carga": cargo, "descripcion": label, "masa_kg": 25 + kg})
        parts[name][3].append(("extras", extras))
        return name
    for kind, (x, y) in PICKUP:
        pallet((x, y, 0.0), 0.0, kind)
    occupied = {1: "carne", 4: "lacteos", 9: "combustible", 14: "carne", 20: "transformador"}
    for i, (sx, sy, sz, nv) in enumerate(slots):
        name = f"RackSlot_{chr(65 + i // 6)}{i % 6 + 1}_{nv}"
        gameplay.append((name, Matrix.Translation((sx, sy, sz)), {"ranura": True, "nivel": nv, "ocupada": i in occupied}))
        if i in occupied:
            pallet((sx, sy, sz), 0.0, occupied[i])
    for k in range(3):
        pallet((-12.4, 6.5, k * WH.PALLET[2]), math.pi / 2)
    cones = []
    for i, x in enumerate(CONES_X):
        nm = f"Cone_{i + 1:02d}"
        WH.build_cone(part(nm, Matrix.Translation((x, SLALOM_Y, 0))), (x, SLALOM_Y, 0))
        parts[nm][3].append(("extras", {"cono": True}))
    return root, parts, gameplay, slots


def realize_env(parts, coll, atlas, root, mat):
    obs = {}
    for name, (b, pivot, par, extra) in parts.items():
        obs[name] = b.to_object(name, coll, pivot)
    scale = atlas.pack()
    for name, (b, pivot, par, extra) in parts.items():
        ob = b.finalize(obs[name])
        ob.data.materials.append(mat)
        for item in extra:
            if item[0] == "extras":
                for k, v in item[1].items():
                    ob[k] = v
    for name, (b, pivot, par, extra) in parts.items():
        parent_keep(obs[name], obs.get(par) or root)
    bpy.context.view_layer.update()
    return obs, scale


# ---------------------------------------------------------------------------------------------------------------------
# Colisiones (UCX_*)
# ---------------------------------------------------------------------------------------------------------------------
def ucx_box(name, coll, parent, size, center_world, rot=None):
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    bm.transform(Matrix.Diagonal((*size, 1.0)))
    if rot is not None:
        bm.transform(rot.to_4x4())
    bm.transform(Matrix.Translation(Vector(center_world)))
    return _ucx_from_bm(name, coll, parent, bm)


def ucx_hull(name, coll, parent, points_world, dissolve_deg=6):
    bm = bmesh.new()
    vs = [bm.verts.new(p) for p in points_world]
    res = bmesh.ops.convex_hull(bm, input=vs)
    bmesh.ops.delete(bm, geom=list(set(res["geom_interior"]) | set(res["geom_unused"])), context="VERTS")
    bmesh.ops.dissolve_limit(bm, angle_limit=math.radians(dissolve_deg), verts=bm.verts, edges=bm.edges)
    return _ucx_from_bm(name, coll, parent, bm)


def _ucx_from_bm(name, coll, parent, bm, extra_bms=()):
    bmesh.ops.triangulate(bm, faces=bm.faces)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    bm.transform(parent.matrix_world.inverted())
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    ob = bpy.data.objects.new(name, me)
    coll.objects.link(ob)
    ob.parent = parent
    ob.matrix_parent_inverse = Matrix.Identity(4)
    ob.matrix_basis = Matrix.Identity(4)
    ob.display_type = "WIRE"
    ob.hide_render = True
    ob["collider"] = True
    return ob


def forklift_colliders(obs, coll):
    out = []
    for nm, x in (("Fork_Left", F.FORK_X), ("Fork_Right", -F.FORK_X)):
        # caja exacta de la pala: 100 × 40 mm, desde el talón hasta la punta
        y0 = F.CARRIAGE_Y - 0.04 - 0.07
        out.append(ucx_box(f"UCX_{nm}", coll, obs[nm], (0.10, F.FORK_LEN, 0.04), (x, y0 - F.FORK_LEN / 2, 0.035)))
    ch = obs["Chassis"]
    pts = [ch.matrix_world @ v.co for v in ch.data.vertices]
    out.append(ucx_hull("UCX_Chassis", coll, ch, pts))
    # cuatro cilindros de rueda en un solo objeto (cada isla es convexa)
    bm = bmesh.new()
    for x, y, r, w in ((F.FRONT_X, 0, F.FRONT_R, F.FRONT_W), (-F.FRONT_X, 0, F.FRONT_R, F.FRONT_W),
                       (F.REAR_X, F.REAR_Y, F.REAR_R, F.REAR_W), (-F.REAR_X, F.REAR_Y, F.REAR_R, F.REAR_W)):
        bmesh.ops.create_cone(bm, cap_ends=True, cap_tris=False, segments=12, radius1=r, radius2=r, depth=w,
                              matrix=axis_m("X", (x, y, r)))
    out.append(_ucx_from_bm("UCX_Wheels", coll, obs["Chassis"].parent, bm))
    return out


def environment_colliders(obs, coll, x0, width):
    out = []
    root = obs["Building"]
    hx, hy = WH.W / 2, WH.D / 2
    for nm, size, c in (("UCX_Wall_N", (WH.W, 0.2, WH.H), (0, hy + 0.1, WH.H / 2)), ("UCX_Wall_S", (WH.W, 0.2, WH.H), (0, -hy - 0.1, WH.H / 2)),
                        ("UCX_Wall_E", (0.2, WH.D, WH.H), (hx + 0.1, 0, WH.H / 2)), ("UCX_Wall_W", (0.2, WH.D, WH.H), (-hx - 0.1, 0, WH.H / 2)),
                        ("UCX_Floor", (WH.W, WH.D, 0.2), (0, 0, -0.1))):
        out.append(ucx_box(nm, coll, root, size, c))
    racks = obs["Racks"]
    post = 0.09
    for i in range(5):
        x = x0 + post / 2 + i * (WH.BAY + post)
        out.append(ucx_box(f"UCX_Rack_Frame_{i + 1:02d}", coll, racks, (post, WH.RACK_DEPTH + 0.07, 3.95), (x, WH.RACK_Y, 3.95 / 2)))
    for j in range(4):
        xc = x0 + post + j * (WH.BAY + post) + WH.BAY / 2
        for k, z in enumerate(WH.RACK_LEVELS[1:]):
            out.append(ucx_box(f"UCX_Rack_Level_{chr(65 + j)}{k + 2}", coll, racks, (WH.BAY, WH.RACK_DEPTH + 0.05, 0.13), (xc, WH.RACK_Y, z - 0.055)))
    # pallets: tablero superior + tres filas de tacos (los huecos de las horquillas quedan libres)
    for name, ob in obs.items():
        if not name.startswith("Pallet_"):
            continue
        M = ob.matrix_world
        r3 = M.to_3x3()
        out.append(ucx_box(f"UCX_{name}_01", coll, ob, (0.80, 1.20, 0.044), M @ Vector((0, 0, 0.122)), r3))
        for k, x in enumerate((-0.35, 0.0, 0.35)):
            out.append(ucx_box(f"UCX_{name}_{k + 2:02d}", coll, ob, (0.145 if x == 0 else 0.10, 1.20, 0.10), M @ Vector((x, 0, 0.05)), r3))
    return out


def freeze_transforms(objs):
    """Congela escala (y rotación cuando no define un eje) manteniendo cada pivote en su lugar.
    Las piezas articuladas conservan su rotación: es la que alinea su eje local con el eje mecánico."""
    for ob in objs:
        if ob.type != "MESH":
            continue
        s = ob.matrix_basis.to_scale()
        if any(abs(v - 1) > 1e-6 for v in s):
            ob.data.transform(Matrix.Diagonal((*s, 1.0)))
            loc, rot, _ = ob.matrix_basis.decompose()
            ob.matrix_basis = Matrix.LocRotScale(loc, rot, None)


# ---------------------------------------------------------------------------------------------------------------------
# Exportación
# ---------------------------------------------------------------------------------------------------------------------
def select_tree(roots, include=lambda o: True):
    vl = bpy.context.view_layer
    for o in vl.objects:
        o.select_set(False)
    chosen = []

    def walk(o):
        if include(o):
            o.hide_set(False)
            o.select_set(True)
            chosen.append(o)
        for c in o.children:
            walk(c)
    for r in roots:
        walk(r)
    vl.objects.active = chosen[0]
    return chosen


def export_glb(path, roots, include, webp=False):
    select_tree(roots, include)
    r = bpy.ops.export_scene.gltf(filepath=path, export_format="GLB", use_selection=True, export_extras=True, export_yup=True,
                                  export_apply=True, export_tangents=True, export_image_format="WEBP" if webp else "AUTO",
                                  export_image_quality=88, export_materials="EXPORT", export_cameras=False, export_lights=False,
                                  export_animations=False)
    assert r == {"FINISHED"}, r


def export_fbx(path, roots, include):
    select_tree(roots, include)
    r = bpy.ops.export_scene.fbx(filepath=path, use_selection=True, object_types={"EMPTY", "MESH"}, apply_unit_scale=True,
                                 apply_scale_options="FBX_SCALE_UNITS", axis_forward="-Z", axis_up="Y", bake_space_transform=False,
                                 add_leaf_bones=False, path_mode="COPY", embed_textures=True, mesh_smooth_type="FACE", use_tspace=True,
                                 use_custom_props=True)
    assert r == {"FINISHED"}, r


def glb_nodes(path):
    import struct
    with open(path, "rb") as f:
        d = f.read()
    n = struct.unpack_from("<I", d, 12)[0]
    j = json.loads(d[20:20 + n])
    return j


# ---------------------------------------------------------------------------------------------------------------------
def main(outdir, samples_ao=24):
    outdir = os.path.abspath(outdir)
    tex = os.path.join(outdir, "texturas")
    os.makedirs(tex, exist_ok=True)
    clean()
    c_fk = collection("Autoelevador")
    c_fk_ucx = collection("Autoelevador_Colisiones")
    c_env = collection("Deposito")
    c_env_ucx = collection("Deposito_Colisiones")
    c_game = collection("Deposito_Juego")

    # --- autoelevador
    atl_fk = Atlas("Atlas_Forklift_PBR", 2048, density=F.DENS)
    img_fk = placeholder_images("Atlas_Forklift_PBR", 64)
    mat_fk, nodes_fk = atlas_material("Atlas_Forklift_PBR", img_fk)
    mats = {"Atlas": mat_fk, "M_Dash_Screen": ext_material("M_Dash_Screen", (0.01, 0.03, 0.05), 0.15, 0.0, True)}
    for m in ("M_Mirror_Left", "M_Mirror_Right", "M_Mirror_Center"):
        mats[m] = ext_material(m, (0.85, 0.88, 0.92), 0.03, 1.0)
    root_fk, parts_fk = build_forklift(c_fk, atl_fk)
    obs_fk, sc_fk = realize(parts_fk, c_fk, atl_fk, root_fk, mats)
    ucx_fk = forklift_colliders(obs_fk, c_fk_ucx)

    # --- depósito
    atl_env = Atlas("Atlas_Environment_PBR", 2048, density=WH.DENS)
    img_env = placeholder_images("Atlas_Environment_PBR", 64)
    mat_env, nodes_env = atlas_material("Atlas_Environment_PBR", img_env)
    root_env, parts_env, game, slots = build_environment(c_env, atl_env)
    obs_env, sc_env = realize_env(parts_env, c_env, atl_env, root_env, mat_env)
    x0 = WH.build_racks.__defaults__  # (solo para documentación)
    post = 0.09
    width = 4 * (WH.BAY + post) + post
    ucx_env = environment_colliders(obs_env, c_env_ucx, -width / 2, width)
    for name, M, extras in game:
        e = empty(name, c_game, M, size=0.4)
        parent_keep(e, root_env)
        for k, v in extras.items():
            e[k] = v
    # El autoelevador arranca en su lugar de inicio (la raíz se mueve; las piezas quedan relativas a ella)
    root_fk.matrix_world = Matrix.Translation((SPAWN[0], SPAWN[1], 0)) @ Matrix.Rotation(SPAWN[2], 4, "Z")
    bpy.context.view_layer.update()

    # --- pintar, hornear oclusión y repintar con la oclusión
    painter_fk = Painter(atl_fk, F.MATS_FK)
    painter_fk.paint_all()
    p_fk = painter_fk.finish(tex, "Atlas_Forklift_PBR")
    painter_env = Painter(atl_env, WH.MATS_ENV, seed=5)
    painter_env.paint_all()
    p_env = painter_env.finish(tex, "Atlas_Environment_PBR")
    for imgs, paths in ((img_fk, p_fk), (img_env, p_env)):
        for key in ("BaseColor", "ORM", "Normal"):
            load_into(imgs[key], paths[key])
    for o in ucx_fk + ucx_env:
        o.hide_render = True
    ao_fk_img = bpy.data.images.new("_AO_fk", 2048, 2048, alpha=False, float_buffer=False)
    ao_fk_img.colorspace_settings.name = "Non-Color"
    ao_fk = bake_ao(list(obs_fk.values()), ao_fk_img, mat_fk, nodes_fk["ORM"], samples_ao)
    ao_env_img = bpy.data.images.new("_AO_env", 2048, 2048, alpha=False, float_buffer=False)
    ao_env_img.colorspace_settings.name = "Non-Color"
    ao_env = bake_ao(list(obs_env.values()), ao_env_img, mat_env, nodes_env["ORM"], samples_ao)
    # suavizar la oclusión (sin ruido) y no oscurecer de más
    ao_fk = 0.35 + 0.65 * np.clip(ao_fk, 0, 1)
    ao_env = 0.45 + 0.55 * np.clip(ao_env, 0, 1)
    nodes_fk["ORM"].image = img_fk["ORM"]
    nodes_env["ORM"].image = img_env["ORM"]
    p_fk = painter_fk.finish(tex, "Atlas_Forklift_PBR", ao=ao_fk)
    p_env = painter_env.finish(tex, "Atlas_Environment_PBR", ao=ao_env)
    for imgs, paths in ((img_fk, p_fk), (img_env, p_env)):
        for key in ("BaseColor", "ORM", "Normal"):
            load_into(imgs[key], paths[key])
    bpy.data.images.remove(ao_fk_img)
    bpy.data.images.remove(ao_env_img)

    # --- congelar y exportar
    freeze_transforms(list(obs_fk.values()) + list(obs_env.values()))
    root_fk.matrix_world = Matrix.Identity(4)        # el paquete del autoelevador se exporta en su origen
    bpy.context.view_layer.update()
    vis = lambda o: not o.name.startswith("UCX_")   # noqa: E731
    allo = lambda o: True                           # noqa: E731
    export_glb(os.path.join(outdir, "Autoelevador.glb"), [root_fk], vis)
    export_glb(os.path.join(outdir, "Autoelevador_web.glb"), [root_fk], vis, webp=True)
    export_fbx(os.path.join(outdir, "Autoelevador.fbx"), [root_fk], allo)
    export_glb(os.path.join(outdir, "Deposito.glb"), [root_env], vis)
    export_glb(os.path.join(outdir, "Deposito_web.glb"), [root_env], vis, webp=True)
    export_fbx(os.path.join(outdir, "Deposito.fbx"), [root_env], allo)
    root_fk.matrix_world = Matrix.Translation((SPAWN[0], SPAWN[1], 0)) @ Matrix.Rotation(SPAWN[2], 4, "Z")
    bpy.ops.wm.save_as_mainfile(filepath=os.path.join(outdir, "Autoelevador_Deposito.blend"), compress=True, relative_remap=True)

    piv = {}
    for n in ("Mast_Outer_Stage", "Mast_Inner_Stage", "Fork_Carriage", "Fork_Left", "Fork_Right", "Steering_Wheel", "Spinner_Knob",
              "Lever_Lift", "Lever_Tilt", "Lever_Sideshift", "Pedal_Accel", "Pedal_Brake", "Shuttle_Switch", "Key_Ignition", "Emergency_Stop",
              "Steer_Knuckle_Left", "Wheel_Front_Left", "Wheel_Rear_Left"):
        o = obs_fk[n]
        M = root_fk.matrix_world.inverted() @ o.matrix_world
        piv[n] = dict(pos=[round(v, 3) for v in M.translation], z=[round(v, 3) for v in (M.to_3x3() @ Vector((0, 0, 1)))],
                      padre=o.parent.name)
    rep = {
        "tris_autoelevador": sum(tris(o) for o in obs_fk.values()),
        "tris_deposito": sum(tris(o) for o in obs_env.values()),
        "tris_por_pieza": {n: tris(o) for n, o in obs_fk.items()},
        "colisiones": {o.name: tris(o) for o in ucx_fk} | {"deposito": len(ucx_env)},
        "atlas_densidad_px_m": {"autoelevador": round(F.DENS * sc_fk), "deposito": round(WH.DENS * sc_env)},
        "pivotes": piv,
        "juego": [g[0] for g in game],
        "archivos": {f: os.path.getsize(os.path.join(outdir, f)) for f in sorted(os.listdir(outdir)) if os.path.isfile(os.path.join(outdir, f))},
    }
    print("@@JSON@@" + json.dumps(rep, ensure_ascii=False))
    return rep


if __name__ == "__main__":
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else sys.argv[1:]
    out = argv[argv.index("--out") + 1] if "--out" in argv else os.path.join(os.getcwd(), "salida")
    main(out)

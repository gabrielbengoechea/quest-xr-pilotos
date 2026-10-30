"""
Brazo robótico industrial de 6 ejes (estilo cobot UR), low-poly para AR de mesa y VR.

Se ejecuta en Blender 5.2+ (o con el módulo `bpy` 5.2 de pip):
    blender -b --factory-startup -P build_robot.py -- --out ./salida
    python build_robot.py --out ./salida            # con `pip install bpy==5.2.*`

Genera en --out:
    Robot6Ejes.blend        escena completa (malla low, high-poly de horneado oculto, colisiones, sombra)
    Robot6Ejes.glb          WebXR / Android AR (Scene Viewer): malla + plano de sombra
    Robot6Ejes_motor.glb    igual + colisiones UCX_* (Unity, Unreal, Godot)
    Robot6Ejes.usdz         iOS Quick Look (solo la malla; Quick Look pone su propia sombra)
    textures/T_Robot6Ejes_BC.png, _N.png (OpenGL), _ORM.png (R=AO, G=rugosidad, B=metalicidad)

Unidades: metros, Z arriba. Origen global (0,0,0) = centro de la cara inferior de la base.
Cada pieza móvil tiene su origen sobre su eje de giro y el Z local alineado con ese eje.
"""
import math
import os
import sys

import bpy  # antes que bmesh (con el módulo bpy de pip)
import bmesh
from mathutils import Matrix, Vector

# ---------------------------------------------------------------------------------------------------------------------
# Parámetros (metros)
# ---------------------------------------------------------------------------------------------------------------------
SEG = 24                 # lados de los cilindros grandes (máximo pedido: 24)
SEG_S = 16               # lados de piezas chicas
R_BASE = 0.090           # base Ø 18 cm
R_J = 0.068              # articulaciones grandes (J1-J3)
R_W = 0.050              # articulaciones de muñeca (J4-J6)
Z1 = 0.165               # altura del eje J2 (hombro)
L1 = 0.400               # brazo superior (J2 → J3)
L2 = 0.360               # antebrazo (J3 → J4)
Y_UA = 0.128             # desplazamiento lateral del brazo superior
Y_W1 = 0.112             # desplazamiento lateral de la muñeca 1
Z2 = Z1 + L1
Z3 = Z2 + L2
Z5 = Z3 + 0.100          # eje J6
Y6 = Y_W1 + R_W          # cara de la brida

ALU, BLUE, RUBBER = 0, 1, 2
FINISH = {
    # albedo lineal, rugosidad, metalicidad
    ALU: ((0.78, 0.79, 0.80), 0.30, 0.85),
    BLUE: ((0.02, 0.27, 0.62), 0.35, 0.10),
    RUBBER: ((0.018, 0.018, 0.019), 0.70, 0.00),
}

HI_MULT = 1             # se sube a 3 al construir el high-poly de horneado

AX = {"X": Vector((1, 0, 0)), "Y": Vector((0, 1, 0)), "Z": Vector((0, 0, 1))}


def axis_matrix(axis: str, center) -> Matrix:
    """Matriz que lleva el Z local al eje dado (X, Y o Z del mundo) y lo centra en `center`."""
    rot = {"Z": Matrix.Identity(4), "Y": Matrix.Rotation(-math.pi / 2, 4, "X"), "X": Matrix.Rotation(math.pi / 2, 4, "Y")}[axis]
    return Matrix.Translation(Vector(center)) @ rot


# ---------------------------------------------------------------------------------------------------------------------
# Primitivas (en coordenadas de mundo, sobre un bmesh por pieza)
# ---------------------------------------------------------------------------------------------------------------------
def _assign(bm, before, side_mat, cap_mats, axis_vec):
    """Material por cara: tapas (normal paralela al eje) y laterales."""
    for f in set(bm.faces) - before:
        d = f.normal.dot(axis_vec)
        if d > 0.9:
            f.material_index = cap_mats[1]
        elif d < -0.9:
            f.material_index = cap_mats[0]
        else:
            f.material_index = side_mat
        f.smooth = True


def _seam_line(bm, faces, axis_vec, center):
    """Costura longitudinal en el lateral de un sólido de revolución (sin ella el desplegado colapsa)."""
    c = Vector(center)
    best = None
    for f in faces:
        for e in f.edges:
            d = (e.verts[1].co - e.verts[0].co)
            if d.length < 1e-9:
                continue
            if abs(d.normalized().dot(axis_vec)) > 0.98:
                mid = (e.verts[0].co + e.verts[1].co) / 2 - c
                radial = mid - axis_vec * mid.dot(axis_vec)
                # lado de atrás (+X, o +Y si el eje es X): la costura queda donde menos se ve
                ref = Vector((1, 0, 0)) if abs(axis_vec.x) < 0.9 else Vector((0, 1, 0))
                score = radial.normalized().dot(ref) if radial.length > 1e-9 else -2
                if best is None or score > best[0] + 1e-6:
                    best = (score, radial.normalized())
    if best is None:
        return
    for f in faces:
        for e in f.edges:
            d = (e.verts[1].co - e.verts[0].co)
            if d.length < 1e-9 or abs(d.normalized().dot(axis_vec)) < 0.98:
                continue
            mid = (e.verts[0].co + e.verts[1].co) / 2 - c
            radial = mid - axis_vec * mid.dot(axis_vec)
            if radial.length > 1e-9 and radial.normalized().dot(best[1]) > 0.9999:
                e.seam = True


def cyl(bm, axis, center, r, length, side=ALU, caps=(ALU, ALU), seg=SEG, r2=None):
    before = set(bm.faces)
    seg = seg * HI_MULT
    bmesh.ops.create_cone(bm, cap_ends=True, cap_tris=False, segments=seg, radius1=r, radius2=r if r2 is None else r2,
                          depth=length, matrix=axis_matrix(axis, center))
    _assign(bm, before, side, caps, AX[axis])
    _seam_line(bm, set(bm.faces) - before, AX[axis], center)


def lofted(bm, axis, center, stations, side=ALU, seg=SEG, cap_start=None, cap_end=None):
    """Sólido de revolución: `stations` = [(posición a lo largo del eje, radio), ...] relativas a `center`."""
    m = axis_matrix(axis, center)
    seg = seg * HI_MULT
    rings = []
    for z, r in stations:
        ring = [bm.verts.new(m @ Vector((r * math.cos(2 * math.pi * i / seg), r * math.sin(2 * math.pi * i / seg), z))) for i in range(seg)]
        rings.append(ring)
    before = set(bm.faces)
    for a, b in zip(rings, rings[1:]):
        for i in range(seg):
            j = (i + 1) % seg
            f = bm.faces.new((a[i], a[j], b[j], b[i]))
            f.material_index = side
            f.smooth = True
        e = bm.edges.get((a[0], b[0]))
        if e:
            e.seam = True
    for ring, mat, flip in ((rings[0], cap_start, True), (rings[-1], cap_end, False)):
        if mat is not None:
            f = bm.faces.new(list(reversed(ring)) if flip else ring)
            f.material_index = mat
            f.smooth = True
    bm.normal_update()
    return set(bm.faces) - before


def crowned(bm, axis, center, r, length, side=ALU, caps=(ALU, ALU), seg=SEG, crown=0.035, stations=7):
    """Carcasa con perfil levemente abombado (silueta de fundición, no bisel): más ancha al centro."""
    st = []
    for i in range(stations):
        t = i / (stations - 1)
        z = -length / 2 + t * length
        st.append((z, r * (1 - crown * (2 * t - 1) ** 2)))
    lofted(bm, axis, center, st, side=side, seg=seg, cap_start=caps[0], cap_end=caps[1])


def joint(bm, axis, center, r, length, cap_side=+1, ring_side=-1, cap=True, ring=True, seg=SEG):
    """Carcasa de articulación: cuerpo de aluminio, tapa azul en un extremo y anillo de goma en el otro.
    `cap_side`/`ring_side` = +1 o -1 (extremo del eje)."""
    a = AX[axis]
    c = Vector(center)
    # Cuerpo (abombado)
    crowned(bm, axis, c, r, length, ALU, (ALU, ALU), seg)
    if cap:
        # Tapa azul, apenas sobresaliente, con un escalón (dos discos) para una silueta más rica.
        e = c + a * (cap_side * length / 2)
        lofted(bm, axis, e, [(0, r * 0.97), (cap_side * 0.006, r * 0.97), (cap_side * 0.012, r * 0.80), (cap_side * 0.014, r * 0.62)],
               side=BLUE, seg=seg, cap_start=None, cap_end=BLUE) if cap_side > 0 else \
            lofted(bm, axis, e, [(-0.014, r * 0.62), (-0.012, r * 0.80), (-0.006, r * 0.97), (0, r * 0.97)],
                   side=BLUE, seg=seg, cap_start=BLUE, cap_end=None)
    if ring:
        e = c + a * (ring_side * length / 2)
        cyl(bm, axis, e + a * (ring_side * 0.004), r * 1.015, 0.010, RUBBER, (RUBBER, RUBBER), seg)


def flared_tube(bm, axis, start, length, r, r_end, flare=0.07, rings=22, seg=SEG):
    """Tubo con ensanches suaves en los extremos (transición tubo → carcasa, sin biseles)."""
    st = []
    for i in range(rings + 1):
        t = i / rings
        z = t * length
        # perfil: ensancha en los primeros/últimos `flare` m (curva suave coseno)
        k = 0.0
        if z < flare:
            k = 0.5 * (1 + math.cos(math.pi * z / flare))
        elif z > length - flare:
            k = 0.5 * (1 + math.cos(math.pi * (length - z) / flare))
        st.append((z, r + (r_end - r) * k))
    lofted(bm, axis, start, st, side=ALU, seg=seg)


def cable(bm, pts, r, seg=16, sub=6):
    """Tubo que sigue una curva Catmull-Rom (cable). Termina recortado en el último punto."""
    P = [Vector(p) for p in pts]
    seg = seg * HI_MULT
    path = []
    for i in range(len(P) - 1):
        p0, p1, p2, p3 = P[max(i - 1, 0)], P[i], P[i + 1], P[min(i + 2, len(P) - 1)]
        for k in range(sub):
            t = k / sub
            path.append(0.5 * ((2 * p1) + (-p0 + p2) * t + (2 * p0 - 5 * p1 + 4 * p2 - p3) * t * t + (-p0 + 3 * p1 - 3 * p2 + p3) * t ** 3))
    path.append(P[-1])
    rings = []
    up = Vector((0, 0, 1))
    for i, p in enumerate(path):
        tdir = (path[min(i + 1, len(path) - 1)] - path[max(i - 1, 0)]).normalized()
        x = tdir.cross(up).normalized()
        y = tdir.cross(x).normalized()   # (x, y, tdir) dextrógiro: anillo antihorario → normales hacia afuera
        rings.append([bm.verts.new(p + (x * math.cos(2 * math.pi * j / seg) + y * math.sin(2 * math.pi * j / seg)) * r) for j in range(seg)])
    for a, b in zip(rings, rings[1:]):
        for j in range(seg):
            f = bm.faces.new((a[j], a[(j + 1) % seg], b[(j + 1) % seg], b[j]))
            f.material_index = RUBBER
            f.smooth = True
        e = bm.edges.get((a[0], b[0]))
        if e:
            e.seam = True
    for ring, flip in ((rings[0], True), (rings[-1], False)):
        f = bm.faces.new(list(reversed(ring)) if flip else ring)
        f.material_index = RUBBER
    bm.normal_update()


# ---------------------------------------------------------------------------------------------------------------------
# Piezas
# ---------------------------------------------------------------------------------------------------------------------
PARTS = {}   # nombre → dict(pivot, axis, parent, build)


def part(name, pivot, axis, parent):
    def deco(fn):
        PARTS[name] = dict(pivot=Vector(pivot), axis=axis, parent=parent, build=fn)
        return fn
    return deco


@part("Base_Mesh", (0, 0, 0), "Z", None)
def _base(bm, hi=False):
    # Placa de montaje (apoya en z = 0), con un leve escalón.
    lofted(bm, "Z", (0, 0, 0), [(0.0, R_BASE), (0.014, R_BASE), (0.016, R_BASE * 0.96), (0.024, R_BASE * 0.92)],
           side=ALU, cap_start=ALU, cap_end=ALU)
    # Cuerpo del motor J1 (parte fija) + anillo de goma arriba
    crowned(bm, "Z", (0, 0, 0.024 + 0.033), R_J, 0.066, crown=0.0, stations=4)
    # Cable de alimentación saliendo de la base (tramo curvo apoyado en la mesa)
    cable(bm, [(-R_BASE - 0.017, 0, 0.012), (-R_BASE - 0.06, 0, 0.010), (-R_BASE - 0.11, 0.02, 0.008), (-R_BASE - 0.16, 0.07, 0.008),
               (-R_BASE - 0.19, 0.13, 0.008)], 0.0075)
    cyl(bm, "Z", (0, 0, 0.093), R_J * 1.015, 0.006, RUBBER, (RUBBER, RUBBER))
    # Conector del cable en la base
    cyl(bm, "X", (-R_BASE + 0.004, 0, 0.012), 0.010, 0.026, RUBBER, (RUBBER, RUBBER), SEG_S)
    cyl(bm, "X", (-R_BASE - 0.012, 0, 0.012), 0.012, 0.010, ALU, (ALU, ALU), SEG_S)


@part("Shoulder_Joint", (0, 0, 0.096), "Z", "Base_Mesh")
def _shoulder(bm, hi=False):
    # Carcasa giratoria J1 (vertical) que sube hasta el eje J2
    crowned(bm, "Z", (0, 0, 0.096 + (Z1 - 0.096) / 2), R_J, Z1 - 0.096, crown=0.0, stations=4)
    # Carcasa J2 (horizontal, eje Y): tapa azul hacia -Y, el brazo superior sale por +Y
    joint(bm, "Y", (0, 0, Z1), R_J, 0.128, cap_side=-1, ring_side=+1)


@part("Upper_Arm", (0, 0.064, Z1), "Y", "Shoulder_Joint")
def _upper(bm, hi=False):
    joint(bm, "Y", (0, Y_UA, Z1), R_J, 0.120, cap_side=+1, ring_side=-1, ring=False)
    flared_tube(bm, "Z", (0, Y_UA, Z1 + R_J * 0.6), L1 - 2 * R_J * 0.6, 0.044, 0.056)
    joint(bm, "Y", (0, Y_UA, Z2), R_J, 0.120, cap_side=+1, ring_side=-1, ring=True)


@part("Elbow_Joint", (0, 0.068, Z2), "Y", "Upper_Arm")
def _elbow(bm, hi=False):
    joint(bm, "Y", (0, 0.0095, Z2), R_J * 0.94, 0.115, cap_side=-1, ring_side=+1, ring=False)
    flared_tube(bm, "Z", (0, 0.010, Z2 + R_J * 0.55), L2 - R_J * 0.55 - R_W * 0.6, 0.036, 0.048)
    joint(bm, "Y", (0, 0.010, Z3), R_W, 0.104, cap_side=-1, ring_side=+1, ring=True)


@part("Wrist_1_Joint", (0, 0.062, Z3), "Y", "Elbow_Joint")
def _wrist1(bm, hi=False):
    joint(bm, "Y", (0, Y_W1 + 0.0005, Z3), R_W, 0.099, cap_side=+1, ring_side=-1, ring=False)
    # Cuello hacia el eje J5 (vertical)
    cyl(bm, "Z", (0, Y_W1, Z3 + R_W * 0.75), R_W * 0.98, 0.030, ALU, (ALU, ALU))
    cyl(bm, "Z", (0, Y_W1, Z3 + R_W * 0.75 + 0.019), R_W * 1.0, 0.008, RUBBER, (RUBBER, RUBBER))


@part("Wrist_2_Joint", (0, Y_W1, Z3 + R_W * 0.75 + 0.023), "Z", "Wrist_1_Joint")
def _wrist2(bm, hi=False):
    z0 = Z3 + R_W * 0.75 + 0.023
    top = Z5 + R_W
    crowned(bm, "Z", (0, Y_W1, (z0 + top) / 2), R_W, top - z0, crown=0.03)
    # Tapa azul arriba (J5)
    e = Vector((0, Y_W1, top))
    lofted(bm, "Z", e, [(0, R_W * 0.95), (0.006, R_W * 0.95), (0.011, R_W * 0.78), (0.013, R_W * 0.6)], side=BLUE, cap_end=BLUE)
    # Asiento de la brida (J6, eje Y) con anillo de goma
    cyl(bm, "Y", (0, Y6 + 0.004, Z5), R_W * 0.88, 0.008, RUBBER, (RUBBER, RUBBER))
    # Conector del cable de herramienta
    cyl(bm, "X", (R_W + 0.006, Y_W1, Z5 - 0.022), 0.008, 0.016, RUBBER, (RUBBER, RUBBER), SEG_S)


@part("Wrist_3_Flange", (0, Y6 + 0.008, Z5), "Y", "Wrist_2_Joint")
def _flange(bm, hi=False):
    y = Y6 + 0.008
    lofted(bm, "Y", (0, y, Z5), [(0, R_W * 0.84), (0.016, R_W * 0.84), (0.018, R_W * 0.76), (0.024, R_W * 0.66)],
           side=ALU, cap_start=ALU, cap_end=ALU)
    # Brida ISO 9409 (Ø 63 mm) con centrador
    cyl(bm, "Y", (0, y + 0.028, Z5), 0.0315, 0.008, ALU, (ALU, ALU))
    cyl(bm, "Y", (0, y + 0.034, Z5), 0.0125, 0.004, RUBBER, (RUBBER, RUBBER), SEG_S)


ORDER = ["Base_Mesh", "Shoulder_Joint", "Upper_Arm", "Elbow_Joint", "Wrist_1_Joint", "Wrist_2_Joint", "Wrist_3_Flange"]
UCX_NAME = {"Base_Mesh": "UCX_Base", "Shoulder_Joint": "UCX_Shoulder", "Upper_Arm": "UCX_Upper_Arm", "Elbow_Joint": "UCX_Elbow",
            "Wrist_1_Joint": "UCX_Wrist_1", "Wrist_2_Joint": "UCX_Wrist_2", "Wrist_3_Flange": "UCX_Wrist_3"}


# ---------------------------------------------------------------------------------------------------------------------
# Escena
# ---------------------------------------------------------------------------------------------------------------------
def pivot_matrix(name) -> Matrix:
    p = PARTS[name]
    return axis_matrix(p["axis"], p["pivot"])


def mesh_from_bmesh(name, bm, world_to_local: Matrix):
    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=1e-6)
    # Sin recalc_face_normals: en tubos abiertos puede darlos vuelta. Las primitivas ya se construyen hacia afuera.
    bm.normal_update()
    # Triangulado acá (antes del UV y del horneado): el motor y el normal map usan la misma diagonal en cada quad.
    bmesh.ops.triangulate(bm, faces=bm.faces, quad_method="BEAUTY", ngon_method="BEAUTY")
    bm.transform(world_to_local)
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    return me


def mark_sharp(me, angle_deg=40):
    """Bordes duros por ángulo (tapas/laterales): sombreado limpio y costuras UV en los mismos bordes."""
    bm = bmesh.new()
    bm.from_mesh(me)
    lim = math.radians(angle_deg)
    for e in bm.edges:
        if len(e.link_faces) == 2:
            a, b = e.link_faces
            if a.normal.angle(b.normal, 0) > lim or a.material_index != b.material_index:
                e.smooth = False
                e.seam = True
        else:
            e.smooth = False
            e.seam = True
    bm.to_mesh(me)
    bm.free()


def new_object(name, me, coll, parent=None):
    ob = bpy.data.objects.new(name, me)
    coll.objects.link(ob)
    return ob


def clean_scene():
    for ob in list(bpy.data.objects):
        bpy.data.objects.remove(ob, do_unlink=True)
    for c in list(bpy.data.collections):
        bpy.data.collections.remove(c)
    for block in (bpy.data.meshes, bpy.data.materials, bpy.data.images, bpy.data.curves):
        for d in list(block):
            block.remove(d)
    sc = bpy.context.scene
    sc.unit_settings.system = "METRIC"
    sc.unit_settings.scale_length = 1.0
    return sc


def collection(name, parent=None):
    c = bpy.data.collections.new(name)
    (parent or bpy.context.scene.collection).children.link(c)
    return c


def build_low(coll):
    obs = {}
    for name in ORDER:
        p = PARTS[name]
        bm = bmesh.new()
        p["build"](bm)
        M = pivot_matrix(name)
        me = mesh_from_bmesh(name, bm, M.inverted())
        mark_sharp(me)
        ob = new_object(name, me, coll)
        ob.matrix_world = M
        obs[name] = ob
    # Jerarquía: matriz local = inversa del padre @ mundo (sin matrix_parent_inverse oculto)
    for name in ORDER:
        par = PARTS[name]["parent"]
        if par:
            ob = obs[name]
            mw = ob.matrix_world.copy()
            ob.parent = obs[par]
            ob.matrix_parent_inverse = Matrix.Identity(4)
            ob.matrix_basis = obs[par].matrix_world.inverted() @ mw
    bpy.context.view_layer.update()
    return obs


def tri_count(ob):
    me = ob.data
    return sum(len(p.vertices) - 2 for p in me.polygons)


def quick_render(path, objs, res=900, ang=(-45, 18), dist=2.3, target=(0, 0.05, 0.55), shading="MATERIAL"):
    sc = bpy.context.scene
    sc.render.engine = "BLENDER_WORKBENCH"
    sc.display.shading.light = "STUDIO"
    sc.display.shading.color_type = shading
    sc.render.resolution_x = res
    sc.render.resolution_y = res
    sc.render.film_transparent = False
    cam_d = bpy.data.cameras.new("Revision")
    cam = bpy.data.objects.new("Revision", cam_d)
    sc.collection.objects.link(cam)
    az, el = map(math.radians, ang)
    t = Vector(target)
    cam.location = t + Vector((math.cos(el) * math.sin(az), -math.cos(el) * math.cos(az), math.sin(el))) * dist
    cam.rotation_euler = (t - cam.location).to_track_quat("-Z", "Y").to_euler()
    cam_d.lens = 50
    sc.camera = cam
    sc.render.filepath = path
    bpy.ops.render.render(write_still=True)
    bpy.data.objects.remove(cam)


# ---------------------------------------------------------------------------------------------------------------------
# Colisiones y plano de sombra
# ---------------------------------------------------------------------------------------------------------------------
def build_colliders(obs, coll):
    """Un casco convexo por pieza (UCX_*), hijo de su pieza y con el mismo pivote: se mueve con ella."""
    out = {}
    for name in ORDER:
        ob = obs[name]
        M = ob.matrix_world
        pts = [v.co.copy() for v in ob.data.vertices]
        if name == "Base_Mesh":
            # El cable apoyado en la mesa no entra en el casco de la base.
            pts = [p for p in pts if (M @ p).x > -R_BASE - 0.02]
        bm = bmesh.new()
        verts = [bm.verts.new(p) for p in pts]
        res = bmesh.ops.convex_hull(bm, input=verts)
        bmesh.ops.delete(bm, geom=list(set(res["geom_interior"]) | set(res["geom_unused"])), context="VERTS")
        # Simplificar: fusionar caras casi coplanares y triangular (cascos livianos para el motor físico)
        bmesh.ops.dissolve_limit(bm, angle_limit=math.radians(8), verts=bm.verts, edges=bm.edges)
        bmesh.ops.triangulate(bm, faces=bm.faces)
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
        me = bpy.data.meshes.new(UCX_NAME[name])
        bm.to_mesh(me)
        bm.free()
        c = bpy.data.objects.new(UCX_NAME[name], me)
        coll.objects.link(c)
        c.parent = ob
        c.matrix_parent_inverse = Matrix.Identity(4)
        c.matrix_basis = Matrix.Identity(4)
        c.display_type = "WIRE"
        c.hide_render = True
        c["collider"] = True
        out[name] = c
    return out


def build_shadow_catcher(coll, size=1.6):
    """Plano a la altura de la base (z = 0) que solo recibe sombras (Cycles: shadow catcher)."""
    bm = bmesh.new()
    bmesh.ops.create_grid(bm, x_segments=1, y_segments=1, size=size / 2)
    me = bpy.data.meshes.new("ShadowCatcher")
    bm.to_mesh(me)
    bm.free()
    ob = bpy.data.objects.new("ShadowCatcher", me)
    coll.objects.link(ob)
    ob.is_shadow_catcher = True
    ob["shadow_catcher"] = True  # sale como "extras" en el glTF
    mat = bpy.data.materials.new("M_ShadowCatcher")
    bsdf = next(n for n in mat.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
    bsdf.inputs["Base Color"].default_value = (0, 0, 0, 1)
    bsdf.inputs["Roughness"].default_value = 1.0
    me.materials.append(mat)
    return ob


# ---------------------------------------------------------------------------------------------------------------------
# UV en un solo atlas
# ---------------------------------------------------------------------------------------------------------------------
TEX = 2048
PAD_PX = 8   # margen entre islas (pedido: ≥ 4 px)


def store_zones(obs):
    """Guarda el acabado de cada cara (aluminio, azul, goma) en un atributo y deja un solo material."""
    for ob in obs.values():
        me = ob.data
        attr = me.attributes.new("zona", "INT", "FACE")
        vals = [p.material_index for p in me.polygons]
        attr.data.foreach_set("value", vals)
        for p in me.polygons:
            p.material_index = 0
        me.materials.clear()


def unwrap_atlas(obs):
    sc = bpy.context.scene
    vl = bpy.context.view_layer
    lows = list(obs.values())
    for ob in lows:
        if not ob.data.uv_layers:
            ob.data.uv_layers.new(name="UVMap")
    for ob in vl.objects:
        ob.select_set(False)
    for ob in lows:
        ob.select_set(True)
    vl.objects.active = lows[0]
    with bpy.context.temp_override(active_object=lows[0], object=lows[0], selected_objects=lows, selected_editable_objects=lows):
        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.mesh.select_all(action="SELECT")
        # Costuras en bordes duros (marcadas al construir): el desplegado por ángulo las respeta.
        r = bpy.ops.uv.unwrap(method="ANGLE_BASED", fill_holes=True, correct_aspect=True, margin=0.0)
        assert r == {"FINISHED"}, r
        r = bpy.ops.uv.pack_islands(udim_source="CLOSEST_UDIM", rotate=True, rotate_method="ANY", scale=True,
                                    merge_overlap=False, margin_method="FRACTION", margin=PAD_PX / TEX,
                                    shape_method="CONCAVE")
        assert r == {"FINISHED"}, r
        bpy.ops.object.mode_set(mode="OBJECT")


def uv_triangles(ob):
    """Triángulos UV (en 0..1) de un objeto, con la zona de cada uno."""
    me = ob.data
    me.calc_loop_triangles()
    uv = me.uv_layers.active.data
    zona = me.attributes["zona"].data if "zona" in me.attributes else None
    out = []
    for t in me.loop_triangles:
        out.append(([tuple(uv[li].uv) for li in t.loops], zona[t.polygon_index].value if zona else 0))
    return out


def raster(tris, res, values=None):
    """Rasteriza triángulos UV en el centro de cada texel. Devuelve (cuenta por texel, valor por texel)."""
    import numpy as np
    count = np.zeros((res, res), np.uint8)
    val = np.full((res, res), -1, np.int16)
    for k, (t, z) in enumerate(tris):
        P = np.array(t) * res
        x0, y0 = np.floor(P.min(0)).astype(int)
        x1, y1 = np.ceil(P.max(0)).astype(int)
        x0, y0 = max(x0, 0), max(y0, 0)
        x1, y1 = min(x1, res - 1), min(y1, res - 1)
        if x1 < x0 or y1 < y0:
            continue
        xs, ys = np.meshgrid(np.arange(x0, x1 + 1) + 0.5, np.arange(y0, y1 + 1) + 0.5)
        (ax, ay), (bx, by), (cx, cy) = P
        d = (by - cy) * (ax - cx) + (cx - bx) * (ay - cy)
        if abs(d) < 1e-12:
            continue
        l1 = ((by - cy) * (xs - cx) + (cx - bx) * (ys - cy)) / d
        l2 = ((cy - ay) * (xs - cx) + (ax - cx) * (ys - cy)) / d
        l3 = 1 - l1 - l2
        inside = (l1 >= 0) & (l2 >= 0) & (l3 >= 0)
        # filas de la imagen: v = 0 abajo
        rows = res - 1 - (ys[inside] - 0.5).astype(int)
        cols = (xs[inside] - 0.5).astype(int)
        count[rows, cols] += 1
        val[rows, cols] = z
    return count, val


def uv_overlap_check(obs, res=1024):
    tris = [t for ob in obs.values() for t in uv_triangles(ob)]
    count, _ = raster(tris, res)
    used = (count > 0).sum()
    return dict(cobertura=round(float(used) / res / res, 3), texels_solapados=int((count > 1).sum()))


# ---------------------------------------------------------------------------------------------------------------------
# High-poly de horneado: biseles, tornillos, ranuras de tapa y placa con texto (todo va al normal map)
# ---------------------------------------------------------------------------------------------------------------------
def _bevel_sharp(bm, width=0.0022, angle=35):
    lim = math.radians(angle)
    edges = [e for e in bm.edges if len(e.link_faces) == 2 and e.link_faces[0].normal.angle(e.link_faces[1].normal, 0) > lim]
    if edges:
        bmesh.ops.bevel(bm, geom=edges, offset=width, offset_type="OFFSET", segments=3, profile=0.5, affect="EDGES",
                        clamp_overlap=True)
    for f in bm.faces:
        f.smooth = True


def _obj(name, bm, coll):
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    ob = bpy.data.objects.new(name, me)
    coll.objects.link(ob)
    return ob


def _screw_ring(bm, axis, center, ring_r, n, r=0.0028, h=0.0016, start=0.0):
    """Cabezas de tornillo Allen alrededor de un eje, apoyadas sobre una cara plana perpendicular al eje."""
    a = AX[axis]
    m = axis_matrix(axis, center)
    for i in range(n):
        ang = start + 2 * math.pi * i / n
        p = m @ Vector((ring_r * math.cos(ang), ring_r * math.sin(ang), 0))
        cyl(bm, axis, p + a * (h / 2 - 0.0002), r, h, ALU, (ALU, ALU), seg=4)   # ×3 = 12 lados
        # hexágono rebajado: un cilindro de 6 lados más chico que sobresale menos (lee como cavidad en el normal map)
        cyl(bm, axis, p + a * (h - 0.0002), r * 0.45, 0.0004, ALU, (ALU, ALU), seg=2)


def _groove(bool_coll, axis, center, r, width=0.0009, depth=0.0007):
    """Arandela fina que, restada con Boolean, deja una línea de panel alrededor de la carcasa."""
    outer = bmesh.new()
    cyl(outer, axis, center, r + 0.004, width)
    inner = bmesh.new()
    cyl(inner, axis, center, r - depth, width + 0.002)
    o = _obj("_ranura", outer, bool_coll)
    i = _obj("_ranura_int", inner, bool_coll)
    mod = o.modifiers.new("hueco", "BOOLEAN")
    mod.operation = "DIFFERENCE"
    mod.object = i
    mod.solver = "EXACT"
    i.hide_render = True
    i.hide_viewport = True
    return o


PLACA = ("Universidad Tecnológica", "ITR Norte")


def _badge(coll, axis_xy, z_center, r, lines=PLACA, size=0.0125, length=0.20, width=0.037):
    """Placa genérica en relieve sobre el tubo (cara -X), envuelta en el cilindro para que apoye en toda su superficie.
    El texto corre a lo largo del tubo (Z). Va al normal map: no agrega polígonos a la malla final."""
    # --- placa: caja delgada en coordenadas (u = a lo largo, v = alrededor, w = hacia afuera)
    bm = bmesh.new()
    nu, nv = 4, 20
    top, bot = 0.0004, -0.0015
    grid = {}
    for k, w in ((0, top), (1, bot)):
        for a in range(nu + 1):
            for b in range(nv + 1):
                grid[k, a, b] = bm.verts.new((-length / 2 + length * a / nu, -width / 2 + width * b / nv, w))
    for a in range(nu):
        for b in range(nv):
            bm.faces.new((grid[0, a, b], grid[0, a + 1, b], grid[0, a + 1, b + 1], grid[0, a, b + 1]))
            bm.faces.new((grid[1, a, b + 1], grid[1, a + 1, b + 1], grid[1, a + 1, b], grid[1, a, b]))
    for a in range(nu):
        for b0, sgn in ((0, 1), (nv, -1)):
            q = (grid[0, a, b0], grid[1, a, b0], grid[1, a + 1, b0], grid[0, a + 1, b0])
            bm.faces.new(q if sgn > 0 else tuple(reversed(q)))
    for b in range(nv):
        for a0, sgn in ((0, 1), (nu, -1)):
            q = (grid[0, a0, b], grid[0, a0, b + 1], grid[1, a0, b + 1], grid[1, a0, b])
            bm.faces.new(q if sgn > 0 else tuple(reversed(q)))
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    for f in bm.faces:
        f.material_index = 0
    n_placa = len(bm.faces)
    # --- texto (dos renglones), en relieve sobre la placa
    cu = bpy.data.curves.new("_texto", "FONT")
    cu.body = "\n".join(lines)
    cu.size = size
    cu.space_line = 1.05
    cu.extrude = 0.0003
    cu.align_x = "CENTER"
    cu.align_y = "CENTER"
    cu.resolution_u = 6
    t = bpy.data.objects.new("_texto", cu)
    coll.objects.link(t)
    bpy.context.view_layer.update()
    dg = bpy.context.evaluated_depsgraph_get()
    me_t = bpy.data.meshes.new_from_object(t.evaluated_get(dg), depsgraph=dg)
    bpy.data.objects.remove(t)
    bpy.data.curves.remove(cu)
    me_t.transform(Matrix.Translation((0, 0, top + 0.0003)))
    bm.from_mesh(me_t)          # texto: x = a lo largo, y = renglones, z = afuera
    bpy.data.meshes.remove(me_t)
    bm.faces.ensure_lookup_table()
    for f in bm.faces[n_placa:]:
        f.material_index = 1
    # --- envolver sobre el cilindro (eje Z en x=cx, y=cy): u → Z, v → ángulo, w → radio
    cx, cy = axis_xy
    for v in bm.verts:
        u, vv, w = v.co
        th = vv / r
        v.co = Vector((cx - (r + w) * math.cos(th), cy + (r + w) * math.sin(th), z_center + u))
    bm.normal_update()
    ob = _obj("_placa_texto", bm, coll)
    ob.data.materials.append(_mask_mat("_M_placa", 0.5))
    ob.data.materials.append(_mask_mat("_M_texto", 1.0))
    return ob


def _mask_mat(name, value):
    """Material de emisión plana: sirve para hornear la máscara placa/texto (0 = brazo, 0,5 = placa, 1 = letras)."""
    m = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    nt = m.node_tree
    for n in list(nt.nodes):
        if n.type != "OUTPUT_MATERIAL":
            nt.nodes.remove(n)
    em = nt.nodes.new("ShaderNodeEmission")
    em.inputs["Color"].default_value = (value, value, value, 1)
    out = next(n for n in nt.nodes if n.type == "OUTPUT_MATERIAL")
    nt.links.new(em.outputs[0], out.inputs["Surface"])
    return m


def build_high(coll, bool_coll):
    """Construye una versión densa de cada pieza (×3 lados), biselada, más los detalles finos."""
    global HI_MULT
    HI_MULT = 3
    highs = {}
    try:
        for name in ORDER:
            bm = bmesh.new()
            PARTS[name]["build"](bm)
            bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=1e-6)
            bm.normal_update()
            _bevel_sharp(bm)
            parts = [_obj(f"{name}_high", bm, coll)]
            det = bmesh.new()
            if name == "Base_Mesh":
                _screw_ring(det, "Z", (0, 0, 0.014), 0.080, 8, start=math.pi / 8)
            elif name == "Shoulder_Joint":
                _screw_ring(det, "Y", (0, -0.064 - 0.014 + 0.0001, Z1), 0.030, 6)
            elif name == "Upper_Arm":
                _screw_ring(det, "Y", (0, Y_UA + 0.060 + 0.014 - 0.0001, Z1), 0.030, 6)
                _screw_ring(det, "Y", (0, Y_UA + 0.060 + 0.014 - 0.0001, Z2), 0.030, 6)
            elif name == "Elbow_Joint":
                _screw_ring(det, "Y", (0, 0.010 - 0.058 - 0.014 + 0.0001, Z2), 0.028, 6)
            elif name == "Wrist_1_Joint":
                _screw_ring(det, "Y", (0, Y_W1 + 0.050 + 0.014 - 0.0001, Z3), 0.022, 6)
            elif name == "Wrist_2_Joint":
                _screw_ring(det, "Z", (0, Y_W1, Z5 + R_W + 0.013 - 0.0001), 0.022, 6)
            elif name == "Wrist_3_Flange":
                _screw_ring(det, "Y", (0, Y6 + 0.008 + 0.032 - 0.0001, Z5), 0.025, 4, r=0.0032, start=math.pi / 4)
            if det.verts:
                # los tornillos no llevan bisel; quedan como piezas sueltas apoyadas
                parts.append(_obj(f"{name}_high_tornillos", det, coll))
            else:
                det.free()
            highs[name] = parts
        # Ranuras de panel junto a las tapas (restadas de la carcasa con Boolean)
        grooves = {
            "Shoulder_Joint": [("Y", (0, -0.040, Z1), R_J)],
            "Upper_Arm": [("Y", (0, Y_UA + 0.036, Z1), R_J), ("Y", (0, Y_UA + 0.036, Z2), R_J)],
            "Elbow_Joint": [("Y", (0, 0.010 - 0.034, Z2), R_J * 0.94)],
            "Wrist_1_Joint": [("Y", (0, Y_W1 + 0.030, Z3), R_W)],
            "Wrist_2_Joint": [("Z", (0, Y_W1, Z5 + R_W - 0.020), R_W)],
        }
        for name, lst in grooves.items():
            body = highs[name][0]
            for k, (ax, c, r) in enumerate(lst):
                g = _groove(bool_coll, ax, c, r)
                mod = body.modifiers.new(f"ranura_{k}", "BOOLEAN")
                mod.operation = "DIFFERENCE"
                mod.object = g
                mod.solver = "EXACT"
                g.hide_render = True
                g.hide_viewport = True
        # Placa con texto en el brazo superior (cara -X del tubo)
        highs["Upper_Arm"].append(_badge(coll, (0, Y_UA), (Z1 + Z2) / 2, 0.044))
    finally:
        HI_MULT = 1
    return highs


# ---------------------------------------------------------------------------------------------------------------------
# Material único y horneado
# ---------------------------------------------------------------------------------------------------------------------
NAME = "Robot6Ejes"


def new_image(name, color, non_color):
    img = bpy.data.images.new(name, TEX, TEX, alpha=False, float_buffer=False)
    img.generated_color = color
    img.colorspace_settings.name = "Non-Color" if non_color else "sRGB"
    return img


def build_material(obs, imgs):
    """M_Robot6Ejes: Principled con atlas BC (sRGB), ORM (R=AO, G=rugosidad, B=metal) y normal OpenGL."""
    mat = bpy.data.materials.new(f"M_{NAME}")
    nt = mat.node_tree
    nodes, links = nt.nodes, nt.links
    bsdf = next(n for n in nodes if n.type == "BSDF_PRINCIPLED")
    out = next(n for n in nodes if n.type == "OUTPUT_MATERIAL")

    def tex(img, x, y):
        n = nodes.new("ShaderNodeTexImage")
        n.image = img
        n.location = (x, y)
        return n
    bc = tex(imgs["BC"], -700, 300)
    orm = tex(imgs["ORM"], -700, 0)
    nrm = tex(imgs["N"], -700, -300)
    sep = nodes.new("ShaderNodeSeparateColor")
    sep.location = (-400, 0)
    nm = nodes.new("ShaderNodeNormalMap")
    nm.location = (-400, -300)
    links.new(bc.outputs["Color"], bsdf.inputs["Base Color"])
    links.new(orm.outputs["Color"], sep.inputs["Color"])
    links.new(sep.outputs["Green"], bsdf.inputs["Roughness"])
    links.new(sep.outputs["Blue"], bsdf.inputs["Metallic"])
    links.new(nrm.outputs["Color"], nm.inputs["Color"])
    links.new(nm.outputs["Normal"], bsdf.inputs["Normal"])
    # Oclusión para glTF: grupo "glTF Material Output" (lo reconoce el exportador)
    grp = bpy.data.node_groups.get("glTF Material Output") or bpy.data.node_groups.new("glTF Material Output", "ShaderNodeTree")
    if not grp.interface.items_tree:
        grp.interface.new_socket("Occlusion", in_out="INPUT", socket_type="NodeSocketFloat")
    g = nodes.new("ShaderNodeGroup")
    g.node_tree = grp
    g.location = (-150, -500)
    links.new(sep.outputs["Red"], g.inputs["Occlusion"])
    for ob in obs.values():
        ob.data.materials.clear()
        ob.data.materials.append(mat)
    return mat, {"BC": bc, "ORM": orm, "N": nrm}


def _set_active_image(mat, node):
    for n in mat.node_tree.nodes:
        n.select = False
    node.select = True
    mat.node_tree.nodes.active = node


def bake_maps(obs, highs, mat, nodes, imgs_tmp):
    sc = bpy.context.scene
    vl = bpy.context.view_layer
    sc.render.engine = "CYCLES"
    sc.cycles.device = "CPU"
    sc.render.bake.margin = 16
    sc.render.bake.margin_type = "EXTEND"
    sc.render.bake.use_clear = False
    all_high = [o for l in highs.values() for o in l]

    def select(objs, active):
        for o in vl.objects:
            o.select_set(False)
        for o in objs:
            o.select_set(True)
        vl.objects.active = active

    # --- Normal (tangente, OpenGL) desde el high-poly, pieza por pieza
    sc.cycles.samples = 8
    nodes["N"].image = imgs_tmp["N"]
    _set_active_image(mat, nodes["N"])
    for o in all_high:
        o.hide_render = False
    for name in ORDER:
        low = obs[name]
        srcs = highs[name]
        select(srcs + [low], low)
        r = bpy.ops.object.bake(type="NORMAL", normal_space="TANGENT", normal_r="POS_X", normal_g="POS_Y", normal_b="POS_Z",
                                use_selected_to_active=True, cage_extrusion=0.004, max_ray_distance=0.012,
                                margin=16, use_clear=False, target="IMAGE_TEXTURES")
        assert r == {"FINISHED"}, (name, r)
    # --- Oclusión ambiental sobre la malla low, cada pieza sola (sin sombras de contacto que dependen de la pose)
    for o in all_high:
        o.hide_render = True
    sc.cycles.samples = 48
    nodes["ORM"].image = imgs_tmp["AO"]
    _set_active_image(mat, nodes["ORM"])
    for name in ORDER:
        for other in obs.values():
            other.hide_render = other is not obs[name]
        select([obs[name]], obs[name])
        r = bpy.ops.object.bake(type="AO", use_selected_to_active=False, margin=16, use_clear=False, target="IMAGE_TEXTURES")
        assert r == {"FINISHED"}, (name, r)
    for o in obs.values():
        o.hide_render = False

    # --- Máscara de la placa (solo el brazo superior): emisión 0 / 0,5 / 1 desde el high-poly
    placa = [o for o in highs["Upper_Arm"] if o.name.startswith("_placa")]
    if placa and "MASK" in imgs_tmp:
        negro = _mask_mat("_M_cuerpo", 0.0)
        for o in highs["Upper_Arm"]:
            if o not in placa:
                o.data.materials.clear()
                o.data.materials.append(negro)
            o.hide_render = False
        sc.cycles.samples = 64
        nodes["ORM"].image = imgs_tmp["MASK"]
        _set_active_image(mat, nodes["ORM"])
        low = obs["Upper_Arm"]
        for other in obs.values():
            other.hide_render = other is not low
        select(highs["Upper_Arm"] + [low], low)
        r = bpy.ops.object.bake(type="EMIT", use_selected_to_active=True, cage_extrusion=0.004, max_ray_distance=0.012,
                                margin=2, use_clear=False, target="IMAGE_TEXTURES")
        assert r == {"FINISHED"}, r
        for o in highs["Upper_Arm"]:
            o.hide_render = True
        for o in obs.values():
            o.hide_render = False


def _srgb(c):
    return [((1.055 * v ** (1 / 2.4) - 0.055) if v > 0.0031308 else 12.92 * v) for v in c]


def _dilate(arr, mask, px):
    """Extiende los colores de las islas `px` texels hacia afuera (evita bordes oscuros al bajar mipmaps)."""
    import numpy as np
    a = arr.copy()
    m = mask.copy()
    for _ in range(px):
        if m.all():
            break
        acc = np.zeros_like(a, dtype=np.float32)
        cnt = np.zeros(m.shape, np.float32)
        for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (-1, -1), (1, -1), (-1, 1)):
            sm = np.roll(np.roll(m, dy, 0), dx, 1)
            sa = np.roll(np.roll(a, dy, 0), dx, 1)
            acc += sa * sm[..., None]
            cnt += sm
        new = (~m) & (cnt > 0)
        a[new] = (acc[new] / cnt[new][:, None]).astype(a.dtype)
        m = m | new
    return a


def compose_textures(obs, ao_img, outdir, mask_img=None):
    """BC y ORM desde las zonas de cada cara (+ AO horneado). Aluminio con veta de cepillado sutil."""
    import numpy as np
    tris = [t for ob in obs.values() for t in uv_triangles(ob)]
    _, zone = raster(tris, TEX)
    mask = zone >= 0
    rng = np.random.default_rng(7)
    # Veta de cepillado: ruido por fila suavizado (en espacio UV; las islas de tubos corren a lo largo)
    streak = rng.normal(0, 1, (TEX, 1)).repeat(TEX, 1)
    k = np.ones(9) / 9
    streak = np.apply_along_axis(lambda c: np.convolve(c, k, mode="same"), 0, streak)
    streak = streak / (np.abs(streak).max() + 1e-6) + 0.35 * rng.normal(0, 1, (TEX, TEX)) / 3

    bc = np.zeros((TEX, TEX, 3), np.float32)
    rough = np.zeros((TEX, TEX), np.float32)
    metal = np.zeros((TEX, TEX), np.float32)
    for z, (col, r, m) in FINISH.items():
        sel = zone == z
        bc[sel] = _srgb(col)
        rough[sel] = r
        metal[sel] = m
    alu = zone == ALU
    bc[alu] *= (1 + 0.025 * streak[alu])[:, None]
    rough[alu] = np.clip(rough[alu] + 0.04 * streak[alu], 0.2, 0.42)

    # AO horneado (Blender guarda las imágenes de abajo hacia arriba)
    px = np.array(ao_img.pixels[:], np.float32).reshape(TEX, TEX, 4)[::-1, :, 0]
    ao = np.where(mask, np.clip(px, 0, 1), 1.0)
    if mask_img is not None:
        mk = np.array(mask_img.pixels[:], np.float32).reshape(TEX, TEX, 4)[::-1, :, 0]
        # Mezcla suave (el horneado con varias muestras deja bordes con valores intermedios: antialias)
        a_placa = (np.clip(mk / 0.5, 0, 1) * mask)[..., None]
        a_letra = (np.clip((mk - 0.5) / 0.5, 0, 1) * mask)[..., None]
        # Placa de aluminio anodizado grafito (satinada) con letras claras grabadas
        bc = bc * (1 - a_placa) + np.array(_srgb((0.035, 0.038, 0.045)), np.float32) * a_placa
        bc = bc * (1 - a_letra) + np.array(_srgb((0.80, 0.82, 0.84)), np.float32) * a_letra
        rough = rough * (1 - a_placa[..., 0]) + 0.45 * a_placa[..., 0]
        rough = rough * (1 - a_letra[..., 0]) + 0.28 * a_letra[..., 0]
        metal = metal * (1 - a_placa[..., 0]) + 0.6 * a_placa[..., 0]
        metal = metal * (1 - a_letra[..., 0]) + 0.9 * a_letra[..., 0]
    orm = np.stack([ao, rough, metal], -1)

    bc = _dilate(np.clip(bc, 0, 1), mask, 16)
    orm = _dilate(orm, mask, 16)
    bc[~_grow(mask, 16)] = _srgb(FINISH[ALU][0])
    from PIL import Image
    os.makedirs(outdir, exist_ok=True)
    paths = {}
    for key, arr in (("BC", bc), ("ORM", orm)):
        p = os.path.join(outdir, f"T_{NAME}_{key}.png")
        Image.fromarray((np.clip(arr, 0, 1) * 255 + 0.5).astype(np.uint8), "RGB").save(p, optimize=True)
        paths[key] = p
    return paths


def _grow(mask, px):
    import numpy as np
    m = mask.copy()
    for _ in range(px):
        m = m | np.roll(m, 1, 0) | np.roll(m, -1, 0) | np.roll(m, 1, 1) | np.roll(m, -1, 1)
    return m


def save_image(img, path):
    img.filepath_raw = path
    img.file_format = "PNG"
    img.save()


# ---------------------------------------------------------------------------------------------------------------------
# Exportación
# ---------------------------------------------------------------------------------------------------------------------
def _select_only(objs):
    vl = bpy.context.view_layer
    for o in vl.objects:
        o.select_set(False)
    for o in objs:
        o.hide_set(False)
        o.select_set(True)
    vl.objects.active = objs[0]


def export_gltf(path, objs, image_format="AUTO"):
    _select_only(objs)
    r = bpy.ops.export_scene.gltf(filepath=path, export_format="GLB", use_selection=True, export_extras=True, export_yup=True,
                                  export_apply=True, export_tangents=True, export_image_format=image_format, export_image_quality=90,
                                  export_materials="EXPORT",
                                  export_cameras=False, export_lights=False, export_animations=False)
    assert r == {"FINISHED"}, r


def export_usdz(path, objs):
    _select_only(objs)
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


def glb_summary(path):
    import json
    import struct
    with open(path, "rb") as f:
        data = f.read()
    n = struct.unpack_from("<I", data, 12)[0]
    j = json.loads(data[20:20 + n])
    return dict(nodos=[nd.get("name") for nd in j.get("nodes", [])], mallas=len(j.get("meshes", [])),
                materiales=[m.get("name") for m in j.get("materials", [])], imagenes=len(j.get("images", [])),
                kb=round(len(data) / 1024))


# ---------------------------------------------------------------------------------------------------------------------
# Todo junto
# ---------------------------------------------------------------------------------------------------------------------
def main(outdir):
    import json
    outdir = os.path.abspath(outdir)
    texdir = os.path.join(outdir, "textures")
    os.makedirs(texdir, exist_ok=True)
    clean_scene()
    root = collection(NAME)
    c_low = collection("Robot", root)
    c_col = collection("Colisiones", root)
    c_shadow = collection("Sombra_AR", root)
    c_high = collection("Horneado_HighPoly", root)
    c_bool = collection("Horneado_Cortes", c_high)

    obs = build_low(c_low)
    cols = build_colliders(obs, c_col)
    shadow = build_shadow_catcher(c_shadow)
    store_zones(obs)
    unwrap_atlas(obs)
    uv = uv_overlap_check(obs, 1024)

    imgs = {"BC": new_image(f"T_{NAME}_BC", (0.8, 0.8, 0.8, 1), False),
            "ORM": new_image(f"T_{NAME}_ORM", (1, 0.3, 0.85, 1), True),
            "N": new_image(f"T_{NAME}_N", (0.5, 0.5, 1.0, 1), True)}
    ao = new_image(f"_AO_{NAME}", (1, 1, 1, 1), True)
    mask = new_image(f"_MASK_{NAME}", (0, 0, 0, 1), True)
    mat, nodes = build_material(obs, imgs)
    highs = build_high(c_high, c_bool)
    bake_maps(obs, highs, mat, nodes, {"N": imgs["N"], "AO": ao, "MASK": mask})
    save_image(imgs["N"], os.path.join(texdir, f"T_{NAME}_N.png"))
    paths = compose_textures(obs, ao, texdir, mask)
    for key in ("BC", "ORM"):
        imgs[key].filepath = paths[key]
        imgs[key].source = "FILE"
        imgs[key].reload()
    nodes["ORM"].image = imgs["ORM"]
    bpy.data.images.remove(ao)
    bpy.data.images.remove(mask)
    # El high-poly queda en el .blend (para volver a hornear), oculto y fuera de los exportes.
    for o in [o for o in c_high.all_objects if o is not None]:
        o.hide_render = True
        o.hide_set(True)
    c_high.hide_render = True

    lows = [obs[n] for n in ORDER]
    # En el glTF el plano va invisible (alpha 0, BLEND) y marcado con extras.shadow_catcher; en el .blend queda opaco,
    # porque el shadow catcher de Cycles necesita una superficie que reciba los rayos.
    sm = shadow.data.materials[0]
    sb = next(n for n in sm.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
    sb.inputs["Alpha"].default_value = 0.0
    sm.surface_render_method = "BLENDED"
    export_gltf(os.path.join(outdir, f"{NAME}.glb"), lows + [shadow])
    export_gltf(os.path.join(outdir, f"{NAME}_motor.glb"), lows + [shadow] + list(cols.values()))
    # Versión liviana para el navegador del Quest (texturas WebP, EXT_texture_webp)
    export_gltf(os.path.join(outdir, f"{NAME}_web.glb"), lows + [shadow], image_format="WEBP")
    export_usdz(os.path.join(outdir, f"{NAME}.usdz"), lows)
    sb.inputs["Alpha"].default_value = 1.0
    sm.surface_render_method = "DITHERED"
    for o in cols.values():
        o.hide_set(False)
    bpy.ops.file.make_paths_relative() if bpy.data.filepath else None
    blend = os.path.join(outdir, f"{NAME}.blend")
    bpy.ops.wm.save_as_mainfile(filepath=blend, relative_remap=True, compress=True)

    rep = {
        "triangulos": {n: tri_count(obs[n]) for n in ORDER},
        "triangulos_total": sum(tri_count(obs[n]) for n in ORDER),
        "colisiones": {c.name: tri_count(c) for c in cols.values()},
        "uv": uv,
        "escala": {n: tuple(round(v, 6) for v in obs[n].matrix_world.to_scale()) for n in ORDER},
        "pivotes": {n: dict(pos=tuple(round(v, 4) for v in obs[n].matrix_world.translation),
                            eje_z=tuple(round(v, 3) for v in (obs[n].matrix_world.to_3x3() @ Vector((0, 0, 1))))) for n in ORDER},
        "padres": {n: (obs[n].parent.name if obs[n].parent else None) for n in ORDER},
        "dimensiones": dict(base_diametro=round(R_BASE * 2, 3), alcance_brazo_extendido=round(math.hypot(L1 + L2 + (Z5 - Z3), Y6 + 0.040), 3)),
        "archivos": {f: os.path.getsize(os.path.join(outdir, f)) for f in sorted(os.listdir(outdir)) if os.path.isfile(os.path.join(outdir, f))},
        "glb": glb_summary(os.path.join(outdir, f"{NAME}.glb")),
    }
    print("@@JSON@@" + json.dumps(rep, ensure_ascii=False))
    return rep


if __name__ == "__main__":
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else sys.argv[1:]
    out = argv[argv.index("--out") + 1] if "--out" in argv else os.path.join(os.getcwd(), "salida")
    main(out)

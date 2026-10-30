"""
ATLAS XR — globo logístico de mesa para RA (Quest passthrough, ARCore, ARKit / Quick Look).

Uso (bpy 5.2 de pip o Blender 5.2):
    python3 build_atlas.py --out salida
    blender -b -P build_atlas.py -- --out salida

Convenciones
- Metros, escala 1:1. Origen (0,0,0) en el centro de la cara inferior de la base: apoya al ras sobre la mesa.
- Jerarquía:  Atlas_Base ─► Globe_Sphere ─► Logistics_Nodes_Group ─► Node_<id>
                                        └► Logistics_Routes      ─► Route_<nn>
- Globe_Sphere tiene su pivote en el centro de la esfera y su eje Z local = eje terrestre, inclinado 23,5°.
  Girar el globo = rotar Globe_Sphere sobre su Z local (en glTF/three.js: su Y local).
- Un único material M_AtlasXR con un atlas PBR de 2048×2048: BaseColor (sRGB), ORM (R=AO, G=rugosidad, B=metal),
  Normal (OpenGL) y Emisivo (rutas, nodos y costas).
- Cada Node_<id> y Route_<nn> lleva sus datos como propiedades personalizadas → "extras" en glTF (userData en three.js).
- Escalas en 1 en todos los objetos; las rotaciones solo están donde son el eje de giro (Globe_Sphere) o la normal
  del pin (Node_*): la geometría ya está horneada en el espacio de cada pivote.
"""
import json
import math
import os
import sys

import bpy  # antes que bmesh (con el módulo bpy de pip)
import bmesh
import numpy as np
from mathutils import Matrix, Vector
from PIL import Image, ImageDraw, ImageFilter, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
NAME = "AtlasXR"
TEX = 2048

# ---------------------------------------------------------------------------------------------------------------------
# Medidas (m)
# ---------------------------------------------------------------------------------------------------------------------
R = 0.225                 # radio del globo → Ø 45 cm
TILT = math.radians(23.5)
RM = 0.243                # radio (línea media) del meridiano
MW, MT = 0.014, 0.004     # meridiano: ancho radial y espesor
BASE_R, BASE_H = 0.118, 0.028
STEM_R = 0.009
CZ = BASE_H + 0.045 + RM  # altura del centro del globo
C = Vector((0, 0, CZ))
AXIS = Vector((math.sin(TILT), 0, math.cos(TILT)))   # eje terrestre (Blender, mundo)
NRM = Vector((math.cos(TILT), 0, -math.sin(TILT)))   # perpendicular al eje en el plano del meridiano
LON_FRONT = -56.0         # longitud que mira al frente (−Y) en reposo: Uruguay
LON_OFF = -90.0 - LON_FRONT
SEG_LON, SEG_LAT = 56, 36
ROUTE_H, ROUTE_R, ROUTE_SIDES, ROUTE_STEP = 0.0035, 0.0012, 3, 4.2

FONT_B = "/usr/share/fonts/opentype/inter/Inter-Bold.otf"
FONT_R = "/usr/share/fonts/opentype/inter/Inter-Medium.otf"

# ---------------------------------------------------------------------------------------------------------------------
# Datos (los 38 nodos y 12 corredores de Atlas Portuario XR + Montevideo)
# ---------------------------------------------------------------------------------------------------------------------
DATA = json.load(open(os.path.join(HERE, "datos_atlas.json"), encoding="utf-8"))
if not any(n["id"] == "montevideo" for n in DATA["NODES"]):
    DATA["NODES"].append(dict(
        id="montevideo", kind="port", region="latam", name="Montevideo", country="Uruguay", lat=-34.90, lon=-56.21,
        teu=0.857, year="2025", src="ANP, cifras preliminares ene-dic 2025",
        info="Principal puerto de Uruguay, sobre el Río de la Plata y puerta de la hidrovía Paraguay-Paraná. "
             "En 2025 movió 857.491 TEU (dato preliminar de la ANP), por debajo del año anterior tras perder tránsitos de navieras."))
WP = DATA["WP"]
for n in DATA["NODES"]:
    WP.setdefault(n["id"], [n["lat"], n["lon"]])


def hex2rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


# ---------------------------------------------------------------------------------------------------------------------
# Atlas: regiones en píxeles (x0, y0, w, h) con y desde arriba (PIL). UV de Blender: v = 1 − y/TEX.
# ---------------------------------------------------------------------------------------------------------------------
REG = {
    "earth":    (0, 0, 2048, 1016),
    "wood":     (8, 1032, 1008, 504),
    "brass":    (1032, 1032, 1008, 248),
    "meridian": (1032, 1296, 1008, 56),
    "swatch":   (1032, 1368, 1008, 56),
    "plate":    (8, 1552, 1008, 120),
    "steel":    (1032, 1440, 1008, 120),
}
SW = 48  # ancho de cada muestra de color
SWATCHES = []  # (clave, rgb, emisivo)


def swatch(key, rgb, emissive):
    for i, (k, _, _) in enumerate(SWATCHES):
        if k == key:
            return i
    SWATCHES.append((key, rgb, emissive))
    return len(SWATCHES) - 1


def uv_px(x, y):
    return (x / TEX, 1.0 - y / TEX)


def uv_region(name, s, t, inset=4):
    """(s, t) ∈ [0,1]² dentro de la región, con un margen interno."""
    x0, y0, w, h = REG[name]
    return uv_px(x0 + inset + s * (w - 2 * inset), y0 + inset + t * (h - 2 * inset))


def uv_swatch(i):
    x0, y0, w, h = REG["swatch"]
    return uv_px(x0 + i * SW + SW / 2, y0 + h / 2)


def uv_earth(lat, lon):
    x0, y0, w, h = REG["earth"]
    return ((lon + 180.0) / 360.0, 1.0 - (y0 + (90.0 - lat) / 180.0 * h) / TEX)


# ---------------------------------------------------------------------------------------------------------------------
# Geometría (bmesh) con UV en el atlas
# ---------------------------------------------------------------------------------------------------------------------
class Mesh:
    def __init__(self):
        self.bm = bmesh.new()
        self.uv = self.bm.loops.layers.uv.new("UVMap")

    def face(self, pts, uvs, smooth=True):
        vs = [self.bm.verts.new(p) for p in pts]
        f = self.bm.faces.new(vs)
        f.smooth = smooth
        for loop, uv in zip(f.loops, uvs):
            loop[self.uv].uv = uv
        return f

    def finish(self, name, coll, weld=1e-6, sharp_deg=40):
        bm = self.bm
        bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=weld)
        me = bpy.data.meshes.new(name)
        bm.to_mesh(me)
        bm.free()
        ob = bpy.data.objects.new(name, me)
        coll.objects.link(ob)
        if sharp_deg:
            try:
                bpy.context.view_layer.objects.active = ob
                me.set_sharp_from_angle(angle=math.radians(sharp_deg))
            except AttributeError:
                pass
        return ob


def frame_from(z, x_hint=Vector((1, 0, 0))):
    z = z.normalized()
    if abs(z.dot(x_hint)) > 0.95:
        x_hint = Vector((0, 1, 0))
    x = (x_hint - z * z.dot(x_hint)).normalized()
    y = z.cross(x)
    return Matrix((x, y, z)).transposed()


def lathe(m, profile, seg, uv_fn, center=Vector((0, 0, 0)), axis_m=Matrix.Identity(3), cap_top=None, cap_bottom=None):
    """Revolución de un perfil [(r, z), ...]. uv_fn(k_perfil, s_ángulo) → uv."""
    P, U = [], []
    for k, (r, z) in enumerate(profile):
        row, rowu = [], []
        for j in range(seg + 1):
            a = 2 * math.pi * j / seg
            row.append(center + axis_m @ Vector((r * math.cos(a), r * math.sin(a), z)))
            rowu.append(uv_fn(k, j / seg))
        P.append(row)
        U.append(rowu)
    for i in range(len(P) - 1):
        for j in range(seg):
            m.face([P[i][j], P[i][j + 1], P[i + 1][j + 1], P[i + 1][j]], [U[i][j], U[i][j + 1], U[i + 1][j + 1], U[i + 1][j]])
    for cap, k, flip in ((cap_bottom, 0, True), (cap_top, len(profile) - 1, False)):
        if cap is None:
            continue
        pts = P[k][:seg]
        uvs = [cap(math.cos(2 * math.pi * j / seg), math.sin(2 * math.pi * j / seg)) for j in range(seg)]
        if flip:
            pts, uvs = pts[::-1], uvs[::-1]
        m.face(pts, uvs, smooth=False)


def tube(m, pts, r, sides, uv, close_ends=True):
    """Tubo a lo largo de una polilínea con marcos de transporte paralelo. uv: un punto (muestra de color)."""
    n = len(pts)
    tang = [(pts[min(i + 1, n - 1)] - pts[max(i - 1, 0)]).normalized() for i in range(n)]
    ref = Vector((0, 0, 1)) if abs(tang[0].z) < 0.9 else Vector((1, 0, 0))
    nrm = (ref - tang[0] * tang[0].dot(ref)).normalized()
    rings = []
    for i in range(n):
        if i:
            nrm = (nrm - tang[i] * tang[i].dot(nrm)).normalized()
        bin_ = tang[i].cross(nrm)
        rings.append([pts[i] + r * (math.cos(2 * math.pi * s / sides) * nrm + math.sin(2 * math.pi * s / sides) * bin_)
                      for s in range(sides)])
    for i in range(n - 1):
        for s in range(sides):
            s2 = (s + 1) % sides
            m.face([rings[i][s], rings[i][s2], rings[i + 1][s2], rings[i + 1][s]], [uv] * 4)
    if close_ends:
        m.face(rings[0][::-1], [uv] * sides, smooth=False)
        m.face(rings[-1], [uv] * sides, smooth=False)


def cylinder(m, a, b, r, seg, uv_side, uv_cap=None, caps=True):
    d = b - a
    M = frame_from(d)
    ring = lambda c: [c + M @ Vector((r * math.cos(2 * math.pi * j / seg), r * math.sin(2 * math.pi * j / seg), 0)) for j in range(seg)]
    A, B = ring(a), ring(b)
    for j in range(seg):
        j2 = (j + 1) % seg
        m.face([A[j], A[j2], B[j2], B[j]], [uv_side(j / seg, 0), uv_side((j + 1) / seg, 0), uv_side((j + 1) / seg, 1), uv_side(j / seg, 1)])
    if caps:
        uc = uv_side(0.5, 0.5)
        m.face(A[::-1], [uc] * seg, smooth=False)
        m.face(B, [uc] * seg, smooth=False)


def uv_sphere_pts(r, nu, nv):
    pts = []
    for i in range(nv + 1):
        th = math.pi * i / nv
        pts.append([Vector((r * math.sin(th) * math.cos(2 * math.pi * j / nu), r * math.sin(th) * math.sin(2 * math.pi * j / nu), r * math.cos(th)))
                    for j in range(nu)])
    return pts


def small_sphere(m, c, r, uv, nu=8, nv=6):
    P = uv_sphere_pts(r, nu, nv)
    for i in range(nv):
        for j in range(nu):
            j2 = (j + 1) % nu
            if i == 0:
                m.face([c + P[0][0], c + P[1][j], c + P[1][j2]], [uv] * 3)
            elif i == nv - 1:
                m.face([c + P[nv][0], c + P[i][j2], c + P[i][j]], [uv] * 3)
            else:
                m.face([c + P[i + 1][j], c + P[i + 1][j2], c + P[i][j2], c + P[i][j]], [uv] * 4)


def octahedron(m, c, r, h, uv):
    eq = [c + Vector((r * math.cos(k * math.pi / 2), r * math.sin(k * math.pi / 2), 0)) for k in range(4)]
    top, bot = c + Vector((0, 0, h)), c - Vector((0, 0, h))
    for k in range(4):
        a, b = eq[k], eq[(k + 1) % 4]
        m.face([a, b, top], [uv] * 3, smooth=False)
        m.face([b, a, bot], [uv] * 3, smooth=False)


# ---------------------------------------------------------------------------------------------------------------------
# Escena
# ---------------------------------------------------------------------------------------------------------------------
def clean_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)


def collection(name, parent=None):
    c = bpy.data.collections.new(name)
    (parent or bpy.context.scene.collection).children.link(c)
    return c


def parent_keep(ob, par, world):
    """Emparenta sin matrix_parent_inverse oculto: matrix_basis = inversa(padre) @ mundo."""
    ob.parent = par
    ob.matrix_parent_inverse = Matrix.Identity(4)
    ob.matrix_basis = par.matrix_world.inverted() @ world if par else world


def geo_dir(lat, lon):
    """Dirección unitaria en el espacio local del globo (Z = eje terrestre)."""
    la, lo = math.radians(lat), math.radians(lon + LON_OFF)
    return Vector((math.cos(la) * math.cos(lo), math.cos(la) * math.sin(lo), math.sin(la)))


def build_base(coll):
    m = Mesh()
    seg = 36
    wood = lambda k, s: uv_region("wood", s, k / 6)
    # Base de madera torneada (perfil r, z)
    prof = [(BASE_R - 0.004, 0.0), (BASE_R, 0.003), (BASE_R, 0.012), (BASE_R - 0.006, 0.020), (0.086, 0.024), (0.060, BASE_H - 0.001)]
    lathe(m, prof, seg, wood, cap_bottom=lambda x, y: uv_region("wood", 0.5 + 0.45 * x, 0.5 + 0.45 * y))
    # Collar de bronce y vástago
    brass = lambda k, s: uv_region("brass", s, min(1, k / 5))
    lathe(m, [(0.060, BASE_H - 0.001), (0.026, BASE_H + 0.002), (0.018, BASE_H + 0.008), (STEM_R * 1.25, BASE_H + 0.012),
              (STEM_R, BASE_H + 0.016), (STEM_R, CZ - RM - 0.010), (STEM_R * 1.5, CZ - RM - 0.004), (STEM_R * 1.5, CZ - RM + MW / 2)],
          24, brass)
    # Meridiano: banda plana en el plano XZ (el del eje), de N a S pasando por el lado +X y por abajo
    n_seg, a0, a1 = 56, math.radians(-5), math.radians(185)
    rings = []
    for i in range(n_seg + 1):
        th = a0 + (a1 - a0) * i / n_seg
        d = math.cos(th) * AXIS + math.sin(th) * NRM
        ri, ro = C + d * (RM - MW / 2), C + d * (RM + MW / 2)
        y = Vector((0, MT / 2, 0))
        rings.append(((ri - y, ro - y, ro + y, ri + y), i / n_seg))
    for i in range(n_seg):
        (A, s0), (B, s1) = rings[i], rings[i + 1]
        mu = lambda s, t: uv_region("meridian", s, t, inset=2)
        br = lambda s: uv_region("brass", s, 0.5)
        # caras ±Y con la graduación grabada
        m.face([B[0], B[1], A[1], A[0]], [mu(s1, 1), mu(s1, 0), mu(s0, 0), mu(s0, 1)], smooth=False)
        m.face([A[3], A[2], B[2], B[3]], [mu(s0, 1), mu(s0, 0), mu(s1, 0), mu(s1, 1)], smooth=False)
        # cantos interior y exterior
        m.face([B[1], B[2], A[2], A[1]], [br(s1), br(s1), br(s0), br(s0)])
        m.face([A[0], A[3], B[3], B[0]], [br(s0), br(s0), br(s1), br(s1)])
    for (Q, s), flip in ((rings[0], False), (rings[-1], True)):
        m.face(list(Q)[::-1] if flip else list(Q), [uv_region("brass", 0.5, 0.5)] * 4, smooth=False)
    # Ejes (pernos) en los polos
    pin_uv = lambda s, t: uv_region("brass", s, 0.2 + 0.6 * t)
    for sgn in (1, -1):
        cylinder(m, C + sgn * AXIS * (R - 0.003), C + sgn * AXIS * (RM - MW / 2 + 0.001), 0.0032, 12, pin_uv)
        small_sphere(m, C + sgn * AXIS * (RM + MW / 2 + 0.001), 0.0045, uv_region("brass", 0.3, 0.5), 10, 6)
    # Placa grabada en el frente de la base (sobre la cara inclinada)
    z0, z1 = 0.0205, 0.0237
    r0, r1 = BASE_R - 0.0065, 0.0875
    w = 0.060
    a, b = (r0, z0), (r1, z1)
    off = Vector((0, 0, 0))
    q = [Vector((-w / 2, -a[0], a[1])), Vector((w / 2, -a[0], a[1])), Vector((w / 2, -b[0], b[1])), Vector((-w / 2, -b[0], b[1]))]
    # levantarla 0,4 mm sobre la madera, siguiendo la normal de la cara inclinada
    nrm = Vector((0, -(b[1] - a[1]), (a[0] - b[0]))).normalized() * -1
    nrm = Vector((0, -abs(nrm.y), abs(nrm.z)))
    q = [p + nrm * 0.0004 for p in q]
    m.face(q, [uv_region("plate", 0, 1, 2), uv_region("plate", 1, 1, 2), uv_region("plate", 1, 0, 2), uv_region("plate", 0, 0, 2)], smooth=False)
    ob = m.finish("Atlas_Base", coll)
    return ob


def build_globe(coll, base):
    m = Mesh()
    # Esfera UV con costura en la longitud −180°/180° (columna duplicada) y polos en abanico
    rows = []
    for i in range(SEG_LAT + 1):
        lat = 90.0 - 180.0 * i / SEG_LAT
        row = []
        for j in range(SEG_LON + 1):
            lon = -180.0 + 360.0 * j / SEG_LON
            row.append((geo_dir(lat, lon) * R, uv_earth(lat, lon)))
        rows.append(row)
    for i in range(SEG_LAT):
        for j in range(SEG_LON):
            a, b, c, d = rows[i][j], rows[i][j + 1], rows[i + 1][j + 1], rows[i + 1][j]
            if i == 0:   # abanico norte: triángulo con u en el medio
                top = (a[0], ((a[1][0] + b[1][0]) / 2, a[1][1]))
                m.face([top[0], d[0], c[0]], [top[1], d[1], c[1]])
            elif i == SEG_LAT - 1:
                bot = (d[0], ((d[1][0] + c[1][0]) / 2, d[1][1]))
                m.face([a[0], bot[0], b[0]], [a[1], bot[1], b[1]])
            else:
                m.face([a[0], d[0], c[0], b[0]], [a[1], d[1], c[1], b[1]])
    # Los vértices del polo se sueldan; la costura conserva UV distintas por loop
    ob = m.finish("Globe_Sphere", coll, sharp_deg=None)
    world = Matrix.Translation(C) @ Matrix.Rotation(TILT, 4, "Y")
    parent_keep(ob, base, world)
    ob["eje"] = "Z local (glTF: Y local) = eje terrestre, inclinado 23,5°"
    ob["lon_frente_deg"] = LON_FRONT
    ob["lon_offset_deg"] = LON_OFF
    ob["radio_m"] = R
    return ob


def build_nodes(coll, globe):
    grp = bpy.data.objects.new("Logistics_Nodes_Group", None)
    grp.empty_display_type = "SPHERE"
    grp.empty_display_size = R
    coll.objects.link(grp)
    parent_keep(grp, globe, globe.matrix_world.copy())
    stalk_uv = uv_swatch(swatch("stalk", (226, 232, 238), False))
    nodes = []
    for n in DATA["NODES"]:
        reg = DATA["REGIONS"][n["region"]]
        col_i = swatch("reg_" + n["region"], hex2rgb(reg["color"]), True)
        m = Mesh()
        if n["kind"] == "port":
            h = 0.009 + 0.011 * math.sqrt(min(n.get("teu", 1), 55) / 55)
            tube(m, [Vector((0, 0, -0.001)), Vector((0, 0, h))], 0.0009, 4, stalk_uv)
            small_sphere(m, Vector((0, 0, h + 0.0030)), 0.0034, uv_swatch(col_i), 8, 4)
        else:
            tube(m, [Vector((0, 0, -0.001)), Vector((0, 0, 0.006))], 0.0008, 4, stalk_uv)
            octahedron(m, Vector((0, 0, 0.0105)), 0.0040, 0.0050, uv_swatch(col_i))
        ob = m.finish(f"Node_{n['id']}", coll, sharp_deg=50)
        d = geo_dir(n["lat"], n["lon"])
        local = Matrix.Translation(d * R) @ frame_from(d, Vector((0, 0, 1)) if abs(d.z) < 0.95 else Vector((1, 0, 0))).to_4x4()
        parent_keep(ob, grp, grp.matrix_world @ local)
        for k in ("id", "kind", "region", "name", "country", "lat", "lon", "teu", "year", "src", "info", "status"):
            if k in n and n[k] is not None:
                ob[k] = n[k]
        ob["region_name"] = reg["name"]
        ob["color"] = reg["color"]
        ob["selectable"] = True
        nodes.append(ob)
    return grp, nodes


def slerp(a, b, t):
    om = math.acos(max(-1, min(1, a.dot(b))))
    if om < 1e-6:
        return a.copy()
    return (math.sin((1 - t) * om) * a + math.sin(t * om) * b) / math.sin(om)


def build_routes(coll, globe):
    grp = bpy.data.objects.new("Logistics_Routes", None)
    grp.empty_display_type = "PLAIN_AXES"
    grp.empty_display_size = 0.05
    coll.objects.link(grp)
    parent_keep(grp, globe, globe.matrix_world.copy())
    routes = []
    for k, cor in enumerate(DATA["CORRIDORS"]):
        col_i = swatch(f"route_{k}", hex2rgb(cor["color"]), True)
        dirs = [geo_dir(*WP[p]) for p in cor["path"]]
        pts = []
        for a, b in zip(dirs, dirs[1:]):
            ang = math.degrees(math.acos(max(-1, min(1, a.dot(b)))))
            n = max(1, math.ceil(ang / ROUTE_STEP))
            for i in range(n):
                pts.append(slerp(a, b, i / n))
        pts.append(dirs[-1])
        pts = [p.normalized() * (R + ROUTE_H) for p in pts]
        m = Mesh()
        tube(m, pts, ROUTE_R, ROUTE_SIDES, uv_swatch(col_i))
        ob = m.finish(f"Route_{k + 1:02d}", coll, sharp_deg=None)
        parent_keep(ob, grp, grp.matrix_world.copy())
        ob["name"] = cor["name"]
        ob["kind"] = "corridor"
        ob["color"] = cor["color"]
        ob["status"] = cor.get("status", "")
        ob["info"] = cor.get("info", "")
        ob["path"] = ", ".join(cor["path"])
        ob["selectable"] = True
        routes.append(ob)
    return grp, routes


def build_colliders(coll, base, globe):
    out = []
    m = Mesh()
    uv = (0, 0)
    lathe(m, [(BASE_R, 0), (BASE_R, BASE_H)], 12, lambda k, s: uv, cap_top=lambda x, y: uv, cap_bottom=lambda x, y: uv)
    ob = m.finish("UCX_Atlas_Base", coll, sharp_deg=None)
    parent_keep(ob, base, Matrix.Identity(4))
    out.append(ob)
    m = Mesh()
    cylinder(m, Vector((0, 0, BASE_H)), Vector((0, 0, CZ - RM)), STEM_R * 1.6, 8, lambda s, t: uv)
    ob = m.finish("UCX_Stem", coll, sharp_deg=None)
    parent_keep(ob, base, Matrix.Identity(4))
    out.append(ob)
    bm = bmesh.new()
    bmesh.ops.create_icosphere(bm, subdivisions=1, radius=RM + MW / 2 + 0.004)
    me = bpy.data.meshes.new("UCX_Globe")
    bm.to_mesh(me)
    bm.free()
    ob = bpy.data.objects.new("UCX_Globe", me)
    coll.objects.link(ob)
    parent_keep(ob, globe, globe.matrix_world.copy())
    out.append(ob)
    for o in out:
        o.display_type = "WIRE"
        o.hide_render = True
    return out


def build_shadow_catcher(coll, size=1.2):
    bm = bmesh.new()
    bmesh.ops.create_grid(bm, x_segments=1, y_segments=1, size=size / 2)
    me = bpy.data.meshes.new("ShadowCatcher")
    bm.to_mesh(me)
    bm.free()
    ob = bpy.data.objects.new("ShadowCatcher", me)
    coll.objects.link(ob)
    ob.is_shadow_catcher = True
    ob["shadow_catcher"] = True
    mat = bpy.data.materials.new("M_ShadowCatcher")
    bsdf = next(n for n in mat.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
    bsdf.inputs["Base Color"].default_value = (0, 0, 0, 1)
    bsdf.inputs["Roughness"].default_value = 1.0
    me.materials.append(mat)
    return ob


# ---------------------------------------------------------------------------------------------------------------------
# Texturas (numpy + PIL)
# ---------------------------------------------------------------------------------------------------------------------
def _blur(a, r):
    im = Image.fromarray(np.clip(a * 255, 0, 255).astype(np.uint8)) if a.dtype != np.uint8 else Image.fromarray(a)
    return np.asarray(im.filter(ImageFilter.GaussianBlur(r)), dtype=np.float32) / 255.0


def _noise(rng, h, w, r):
    n = rng.normal(0.5, 0.18, (h, w)).astype(np.float32)
    n = _blur(np.clip(n, 0, 1), r)
    return (n - n.mean()) / (n.std() + 1e-6)


def paint_textures(texdir):
    rng = np.random.default_rng(7)
    bc = np.zeros((TEX, TEX, 3), np.float32) + 0.5
    rough = np.ones((TEX, TEX), np.float32) * 0.6
    metal = np.zeros((TEX, TEX), np.float32)
    ao = np.ones((TEX, TEX), np.float32)
    hgt = np.zeros((TEX, TEX), np.float32)
    emi = np.zeros((TEX, TEX, 3), np.float32)

    def sl(name, pad=0):
        x0, y0, w, h = REG[name]
        return slice(y0 - pad, y0 + h + pad), slice(x0 - pad, x0 + w + pad), w + 2 * pad, h + 2 * pad

    # --- Tierra: Blue Marble 2048×1024 (de Atlas Portuario XR) + máscara de costas Natural Earth 1:50m
    ys, xs, w, h = sl("earth")
    earth = np.asarray(Image.open(os.path.join(HERE, "earth_src.jpg")).convert("RGB").resize((w, h), Image.LANCZOS), np.float32) / 255
    sys.path.insert(0, HERE)
    from land_mask import mask as land_mask
    land = np.asarray(land_mask(w, h, os.path.join(HERE, "land50.json")), np.float32) / 255
    land[int(h * 0.975):] = 1.0       # casquete antártico completo
    lat = (90 - (np.arange(h) + 0.5) / h * 180)[:, None]
    lum = earth.mean(axis=2)
    ice = np.clip((lum - 0.55) / 0.2, 0, 1) * (np.abs(lat) > 55)
    # costa: borde de la máscara (gradiente del desenfoque)
    lb = _blur(land, 1.2)
    gy, gx = np.gradient(lb)
    coast = np.clip(np.hypot(gx, gy) * 3.0, 0, 1)
    coast *= (np.abs(lat) < 80)
    # tierra "resaltada": algo más clara y cálida; océano un poco más profundo
    e = earth.copy()
    e = e * (1 + 0.18 * land[..., None]) * (1 - 0.12 * (1 - land[..., None]))
    cyan = np.array([0.55, 0.92, 1.0], np.float32)
    e = e * (1 - 0.55 * coast[..., None]) + cyan * 0.55 * coast[..., None]
    bc[ys, xs] = e
    rough[ys, xs] = 0.30 * (1 - land) + 0.78 * land - 0.2 * ice * land
    hgt[ys, xs] = _blur(land, 2.5) * 0.9 + (lum - lum.mean()) * 0.6 * land
    emi[ys, xs] = cyan * (coast * 0.45)[..., None]

    # --- Madera (nogal)
    ys, xs, w, h = sl("wood", 6)
    U, V = np.meshgrid(np.linspace(0, 1, w), np.linspace(0, 1, h))
    warp = _noise(rng, h, w, 18) * 0.25
    grain = np.sin((V * 30 + 2.2 * np.sin(U * 9 + V * 4) + warp) * math.pi) * 0.5 + 0.5
    fine = _noise(rng, h, w, 1.2)
    base = np.array([0.30, 0.17, 0.09], np.float32)
    bc[ys, xs] = base * (0.78 + 0.32 * grain + 0.05 * fine)[..., None]
    rough[ys, xs] = 0.42 + 0.08 * grain
    hgt[ys, xs] = grain * 0.25 + fine * 0.02
    ao[ys, xs] = 1.0

    # --- Bronce cepillado
    for name in ("brass", "meridian"):
        ys, xs, w, h = sl(name, 6)
        streak = _blur(np.clip(rng.normal(0.5, 0.2, (h, 1)).repeat(w, 1), 0, 1), 0.6)
        bc[ys, xs] = np.array([0.80, 0.60, 0.30], np.float32) * (0.92 + 0.12 * (streak - 0.5))[..., None]
        rough[ys, xs] = 0.30 + 0.10 * streak
        metal[ys, xs] = 1.0
        hgt[ys, xs] = streak * 0.05
    # graduación del meridiano: 180 grados en el arco de 190°, marcas cada 5° y largas cada 15°
    x0, y0, w, h = REG["meridian"]
    img = Image.new("L", (w, h), 0)
    d = ImageDraw.Draw(img)
    for deg in range(0, 181, 5):
        s = (deg + 5) / 190.0
        x = 2 + s * (w - 4)
        L = h * (0.62 if deg % 15 == 0 else 0.34)
        d.line([(x, h - 3), (x, h - 3 - L)], fill=255, width=2 if deg % 15 == 0 else 1)
    marks = np.asarray(img, np.float32) / 255
    bc[y0:y0 + h, x0:x0 + w] *= (1 - 0.72 * marks)[..., None]
    hgt[y0:y0 + h, x0:x0 + w] -= marks * 0.6
    rough[y0:y0 + h, x0:x0 + w] += marks * 0.35

    # --- Acero gris (reservado / tornillos)
    ys, xs, w, h = sl("steel", 6)
    bc[ys, xs] = 0.55
    rough[ys, xs] = 0.35
    metal[ys, xs] = 1.0

    # --- Placa grabada
    x0, y0, w, h = REG["plate"]
    S = 3
    img = Image.new("L", (w * S, h * S), 0)
    d = ImageDraw.Draw(img)
    fb = ImageFont.truetype(FONT_B, int(h * S * 0.36))
    fr = ImageFont.truetype(FONT_R, int(h * S * 0.20))
    for text, font, cy in (("ATLAS XR", fb, 0.36), ("Universidad Tecnológica · ITR Norte", fr, 0.76)):
        bb = d.textbbox((0, 0), text, font=font)
        d.text(((w * S - (bb[2] - bb[0])) / 2 - bb[0], cy * h * S - (bb[3] - bb[1]) / 2 - bb[1]), text, font=font, fill=255)
    bw = int(h * S * 0.05)
    d.rectangle([bw, bw, w * S - bw, h * S - bw], outline=255, width=max(2, bw // 2))
    txt = np.asarray(img.resize((w, h), Image.LANCZOS), np.float32) / 255
    plate = np.array([0.78, 0.60, 0.32], np.float32)
    bc[y0:y0 + h, x0:x0 + w] = plate * (1 - 0.78 * txt[..., None])
    rough[y0:y0 + h, x0:x0 + w] = 0.28 + 0.45 * txt
    metal[y0:y0 + h, x0:x0 + w] = 1.0 - 0.8 * txt
    hgt[y0:y0 + h, x0:x0 + w] = -txt * 0.8

    # --- Muestras de color (rutas/nodos emisivos)
    x0, y0, w, h = REG["swatch"]
    assert len(SWATCHES) * SW <= w, len(SWATCHES)
    for i, (key, rgb, em) in enumerate(SWATCHES):
        c = np.array(rgb, np.float32) / 255
        lin = c  # sRGB
        sx = slice(x0 + i * SW + 2, x0 + (i + 1) * SW - 2)
        sy = slice(y0 + 2, y0 + h - 2)
        bc[sy, sx] = lin
        rough[sy, sx] = 0.35
        metal[sy, sx] = 0.0
        if em:
            emi[sy, sx] = lin

    # --- Normal (OpenGL) por Sobel
    def normal_from(hh, strength):
        gy, gx = np.gradient(_blur(np.clip(hh * 0.5 + 0.5, 0, 1), 0.7))
        nx, ny = -gx * strength, gy * strength
        nz = np.ones_like(nx)
        ln = np.sqrt(nx * nx + ny * ny + nz * nz)
        return np.stack([nx / ln, ny / ln, nz / ln], -1) * 0.5 + 0.5
    nrm = normal_from(hgt, 9.0)

    def save(arr, name):
        a = np.clip(arr, 0, 1)
        Image.fromarray((a * 255 + 0.5).astype(np.uint8)).save(os.path.join(texdir, name))
        return os.path.join(texdir, name)
    paths = {
        "BC": save(bc, f"T_{NAME}_BaseColor.png"),
        "ORM": save(np.stack([ao, np.clip(rough, 0.05, 1), metal], -1), f"T_{NAME}_ORM.png"),
        "N": save(nrm, f"T_{NAME}_Normal.png"),
        "E": save(emi, f"T_{NAME}_Emissive.png"),
    }
    save(np.clip(rough, 0, 1), f"T_{NAME}_Roughness.png")
    save(metal, f"T_{NAME}_Metallic.png")
    return paths


def build_material(paths):
    mat = bpy.data.materials.new(f"M_{NAME}")
    nt = mat.node_tree
    nodes, links = nt.nodes, nt.links
    bsdf = next(n for n in nodes if n.type == "BSDF_PRINCIPLED")

    def tex(key, x, y, non_color):
        n = nodes.new("ShaderNodeTexImage")
        n.image = bpy.data.images.load(paths[key])
        n.image.colorspace_settings.name = "Non-Color" if non_color else "sRGB"
        n.location = (x, y)
        return n
    bc = tex("BC", -700, 400, False)
    orm = tex("ORM", -700, 100, True)
    nrm = tex("N", -700, -200, True)
    em = tex("E", -700, -500, False)
    sep = nodes.new("ShaderNodeSeparateColor")
    sep.location = (-400, 100)
    nm = nodes.new("ShaderNodeNormalMap")
    nm.location = (-400, -200)
    links.new(bc.outputs["Color"], bsdf.inputs["Base Color"])
    links.new(orm.outputs["Color"], sep.inputs["Color"])
    links.new(sep.outputs["Green"], bsdf.inputs["Roughness"])
    links.new(sep.outputs["Blue"], bsdf.inputs["Metallic"])
    links.new(nrm.outputs["Color"], nm.inputs["Color"])
    links.new(nm.outputs["Normal"], bsdf.inputs["Normal"])
    links.new(em.outputs["Color"], bsdf.inputs["Emission Color"])
    bsdf.inputs["Emission Strength"].default_value = 1.0
    mat.use_backface_culling = True
    grp = bpy.data.node_groups.get("glTF Material Output") or bpy.data.node_groups.new("glTF Material Output", "ShaderNodeTree")
    if not grp.interface.items_tree:
        grp.interface.new_socket("Occlusion", in_out="INPUT", socket_type="NodeSocketFloat")
    g = nodes.new("ShaderNodeGroup")
    g.node_tree = grp
    g.location = (-150, -600)
    links.new(sep.outputs["Red"], g.inputs["Occlusion"])
    return mat


# ---------------------------------------------------------------------------------------------------------------------
# Limpieza, verificación y exportación
# ---------------------------------------------------------------------------------------------------------------------
def tri_count(ob):
    return sum(len(p.vertices) - 2 for p in ob.data.polygons) if ob.type == "MESH" else 0


def clean_mesh(ob):
    """Limpieza estándar: soldar duplicados, quitar geometría suelta y caras degeneradas, normales coherentes."""
    bm = bmesh.new()
    bm.from_mesh(ob.data)
    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=1e-6)
    bmesh.ops.dissolve_degenerate(bm, edges=bm.edges, dist=1e-7)
    ngons = [f for f in bm.faces if len(f.verts) > 4]   # tapas: triangular para que el glTF tenga tangentes
    if ngons:
        bmesh.ops.triangulate(bm, faces=ngons, quad_method="BEAUTY", ngon_method="BEAUTY")
    loose = [v for v in bm.verts if not v.link_faces]
    if loose:
        bmesh.ops.delete(bm, geom=loose, context="VERTS")
    bm.to_mesh(ob.data)
    bm.free()
    ob.data.validate(clean_customdata=False)
    ob.data.update()


def apply_scale_rotation(objs, keep_rotation):
    """Aplica escala (y rotación cuando no es un eje de giro) sin mover los hijos: equivalente a Ctrl+A › Scale/Rotation."""
    vl = bpy.context.view_layer
    for ob in objs:
        for o in vl.objects:
            o.select_set(False)
        ob.select_set(True)
        vl.objects.active = ob
        rot = ob.name not in keep_rotation and not ob.name.startswith("Node_")
        bpy.ops.object.transform_apply(location=False, rotation=rot, scale=True, properties=False, isolate_users=True)


def _select_only(objs):
    vl = bpy.context.view_layer
    for o in vl.objects:
        o.select_set(False)
    for o in objs:
        o.hide_set(False)
        o.select_set(True)
    vl.objects.active = objs[0]


def export_gltf(path, objs, image_format="AUTO", fmt="GLB"):
    _select_only(objs)
    r = bpy.ops.export_scene.gltf(filepath=path, export_format=fmt, use_selection=True, export_extras=True, export_yup=True,
                                  export_apply=True, export_tangents=True, export_image_format=image_format, export_image_quality=90,
                                  export_materials="EXPORT", export_cameras=False, export_lights=False, export_animations=False)
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
    import struct
    with open(path, "rb") as f:
        data = f.read()
    n = struct.unpack_from("<I", data, 12)[0]
    j = json.loads(data[20:20 + n])
    return dict(nodos=len(j.get("nodes", [])), mallas=len(j.get("meshes", [])), materiales=[m.get("name") for m in j.get("materials", [])],
                imagenes=len(j.get("images", [])), kb=round(len(data) / 1024),
                raiz=[j["nodes"][i]["name"] for i in j["scenes"][0]["nodes"]])


def main(outdir):
    outdir = os.path.abspath(outdir)
    texdir = os.path.join(outdir, "textures")
    os.makedirs(texdir, exist_ok=True)
    clean_scene()
    root = collection(NAME)
    c_geo = collection("Atlas", root)
    c_nodes = collection("Nodos", c_geo)
    c_routes = collection("Rutas", c_geo)
    c_col = collection("Colisiones", root)
    c_sh = collection("Sombra_AR", root)

    base = build_base(c_geo)
    globe = build_globe(c_geo, base)
    grp, nodes = build_nodes(c_nodes, globe)
    rgrp, routes = build_routes(c_routes, globe)
    cols = build_colliders(c_col, base, globe)
    shadow = build_shadow_catcher(c_sh)

    meshes = [base, globe] + nodes + routes
    for ob in meshes + cols:
        clean_mesh(ob)
    apply_scale_rotation([base] + cols, keep_rotation={"Globe_Sphere"})

    paths = paint_textures(texdir)
    mat = build_material(paths)
    for ob in meshes:
        ob.data.materials.clear()
        ob.data.materials.append(mat)

    lows = [base, globe, grp, rgrp] + nodes + routes
    sm = shadow.data.materials[0]
    sb = next(n for n in sm.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
    sb.inputs["Alpha"].default_value = 0.0
    sm.surface_render_method = "BLENDED"
    export_gltf(os.path.join(outdir, f"{NAME}.glb"), lows + [shadow])
    export_gltf(os.path.join(outdir, f"{NAME}_motor.glb"), lows + [shadow] + cols)
    export_gltf(os.path.join(outdir, f"{NAME}_web.glb"), lows + [shadow], image_format="WEBP")
    gdir = os.path.join(outdir, "gltf")
    os.makedirs(gdir, exist_ok=True)
    export_gltf(os.path.join(gdir, f"{NAME}.gltf"), lows + [shadow], fmt="GLTF_SEPARATE")
    export_usdz(os.path.join(outdir, f"{NAME}.usdz"), [base, globe] + nodes + routes)
    sb.inputs["Alpha"].default_value = 1.0
    sm.surface_render_method = "DITHERED"
    bpy.context.preferences.filepaths.save_version = 0
    bpy.ops.wm.save_as_mainfile(filepath=os.path.join(outdir, f"{NAME}.blend"), compress=True, relative_remap=True)
    bpy.ops.file.make_paths_relative()
    bpy.ops.wm.save_mainfile(compress=True)

    zmin = min((base.matrix_world @ v.co).z for v in base.data.vertices)
    zmax = max((globe.matrix_world @ v.co).z for v in globe.data.vertices)
    rep = {
        "triangulos": {"Atlas_Base": tri_count(base), "Globe_Sphere": tri_count(globe),
                       "Nodos (%d)" % len(nodes): sum(tri_count(o) for o in nodes),
                       "Rutas (%d)" % len(routes): sum(tri_count(o) for o in routes)},
        "triangulos_total": sum(tri_count(o) for o in meshes),
        "colisiones": {o.name: tri_count(o) for o in cols},
        "muestras_color": len(SWATCHES),
        "escala": sorted({tuple(round(v, 6) for v in o.matrix_world.to_scale()) for o in meshes}),
        "globo": dict(diametro=2 * R, centro=tuple(round(v, 4) for v in globe.matrix_world.translation),
                      eje_z=tuple(round(v, 4) for v in globe.matrix_world.to_3x3() @ Vector((0, 0, 1))),
                      inclinacion_deg=round(math.degrees(math.acos((globe.matrix_world.to_3x3() @ Vector((0, 0, 1))).z)), 2)),
        "altura_total": round(max(zmax, CZ + RM + MW / 2), 4), "z_min": round(zmin, 5),
        "padres": {o.name: o.parent.name if o.parent else None for o in [base, globe, grp, rgrp, nodes[0], routes[0]] + cols},
        "archivos": {f: os.path.getsize(os.path.join(outdir, f)) for f in sorted(os.listdir(outdir)) if os.path.isfile(os.path.join(outdir, f))},
        "glb": glb_summary(os.path.join(outdir, f"{NAME}.glb")),
    }
    print("@@JSON@@" + json.dumps(rep, ensure_ascii=False))
    return rep


if __name__ == "__main__":
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else sys.argv[1:]
    out = argv[argv.index("--out") + 1] if "--out" in argv else os.path.join(os.getcwd(), "salida")
    main(out)

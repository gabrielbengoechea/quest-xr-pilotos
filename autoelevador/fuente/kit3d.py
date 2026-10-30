"""
kit3d: construcción de assets low-poly para tiempo real con UV ya ubicadas en un atlas y texturas pintadas por código.

Cada primitiva (caja, cilindro, torno, toro, calcomanía) pide regiones del atlas según su superficie real y una densidad
de texels. Al final se empaquetan las regiones (estantes), se escriben las UV definitivas y se pintan los mapas:
color base, altura (→ normal map), rugosidad, metalicidad y la máscara. Los detalles finos (dibujo de cubiertas, rejillas,
tornillos, chapa antideslizante, biseles de borde, texto, bandera, franjas de peligro) van en el mapa de altura y en el
color, no en la geometría.
"""
import math
import os

import bpy  # noqa: F401  (antes que bmesh con el módulo de pip)
import bmesh
import numpy as np
from mathutils import Matrix, Vector

FONT_DIR = "/usr/share/fonts/opentype/inter"
FONT_BOLD = os.path.join(FONT_DIR, "Inter-Bold.otf")
FONT_BLACK = os.path.join(FONT_DIR, "Inter-Black.otf")
FONT_SEMI = os.path.join(FONT_DIR, "Inter-SemiBold.otf")


def srgb_to_lin(c):
    return tuple(((v + 0.055) / 1.055) ** 2.4 if v > 0.04045 else v / 12.92 for v in c)


def hexc(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))


# ---------------------------------------------------------------------------------------------------------------------
# Regiones del atlas
# ---------------------------------------------------------------------------------------------------------------------
class Region:
    __slots__ = ("w_m", "h_m", "mat", "patterns", "density", "rect", "shared", "key", "min_px")

    def __init__(self, w_m, h_m, mat, patterns=(), density=None, key=None, min_px=4):
        self.w_m, self.h_m = max(w_m, 1e-4), max(h_m, 1e-4)
        self.mat = mat
        self.patterns = list(patterns)
        self.density = density
        self.rect = None
        self.key = key          # regiones con la misma clave se comparten (calcomanías repetidas)
        self.min_px = min_px


class Atlas:
    def __init__(self, name, size=2048, density=300.0, pad=6):
        self.name, self.size, self.density, self.pad = name, size, density, pad
        self.regions: list[Region] = []
        self.shared: dict[str, Region] = {}
        self.uv_jobs = []   # (mesh_loop_uv_layer_ref, [(loop_index, region, u, v)])

    def region(self, w_m, h_m, mat, patterns=(), density=None, key=None, min_px=4):
        if key and key in self.shared:
            return self.shared[key]
        r = Region(w_m, h_m, mat, patterns, density, key, min_px)
        self.regions.append(r)
        if key:
            self.shared[key] = r
        return r

    def pack(self):
        """Empaqueta en estantes. Si no entra, baja la densidad global y reintenta."""
        scale = 1.0
        for _ in range(40):
            ok = self._try_pack(scale)
            if ok:
                return scale
            scale *= 0.93
        raise RuntimeError(f"No entran las regiones en el atlas {self.name}")

    def _try_pack(self, scale):
        S, P = self.size, self.pad
        items = []
        for r in self.regions:
            d = (r.density or self.density) * scale
            w = max(r.min_px, int(math.ceil(r.w_m * d)))
            h = max(r.min_px, int(math.ceil(r.h_m * d)))
            # una región no puede ser más grande que el atlas
            k = min(1.0, (S - 2 * P) / max(w, h))
            items.append((r, max(2, int(w * k)), max(2, int(h * k))))
        items.sort(key=lambda t: (-t[2], -t[1]))
        x = y = P
        shelf_h = 0
        for r, w, h in items:
            if x + w + P > S:
                x = P
                y += shelf_h + P
                shelf_h = 0
            if y + h + P > S:
                return False
            r.rect = (x, y, w, h)   # y medido desde arriba (fila de imagen)
            x += w + P
            shelf_h = max(shelf_h, h)
        return True

    def uv_of(self, r: Region, u, v):
        """(u, v) en 0..1 dentro de la región → UV del atlas (v hacia arriba)."""
        x, y, w, h = r.rect
        S = self.size
        return ((x + u * w) / S, 1 - (y + (1 - v) * h) / S)


# ---------------------------------------------------------------------------------------------------------------------
# Constructor de mallas con UV diferidas
# ---------------------------------------------------------------------------------------------------------------------
class Builder:
    """Acumula geometría en un bmesh (coordenadas del mundo) y la UV de cada esquina como (región, u, v)."""

    def __init__(self, atlas: Atlas, density=None):
        self.atlas = atlas
        self.bm = bmesh.new()
        self.uvl = self.bm.loops.layers.uv.new("UVMap")
        self.pending = []   # (face, [(region, u, v) por esquina])
        self.density = density
        self.mat_slots = {}  # material externo (espejos, pantalla) → índice

    # -- utilidades
    def _face(self, verts, uvs, smooth=False, mat_index=0):
        f = self.bm.faces.new(verts)
        f.smooth = smooth
        f.material_index = mat_index
        self.pending.append((f, uvs))
        return f

    def _reg(self, w, h, mat, patterns=(), key=None, density=None):
        return self.atlas.region(w, h, mat, patterns, density or self.density, key)

    # -- primitivas
    def box(self, size, center=(0, 0, 0), rot=None, mat="pintura", patterns=(), face_patterns=None, skip=(), bevel=True,
            density=None):
        """Caja. `face_patterns` = {'+x': [...], '-y': [...]} agrega patrones por cara. `skip` = caras que no se crean."""
        sx, sy, sz = size
        M = Matrix.Translation(Vector(center)) @ (rot.to_4x4() if rot is not None else Matrix.Identity(4))
        hx, hy, hz = sx / 2, sy / 2, sz / 2
        faces = {
            # nombre: (centro local, eje u, eje v, ancho u, alto v)
            "+x": (Vector((hx, 0, 0)), Vector((0, 1, 0)), Vector((0, 0, 1)), sy, sz),
            "-x": (Vector((-hx, 0, 0)), Vector((0, -1, 0)), Vector((0, 0, 1)), sy, sz),
            "+y": (Vector((0, hy, 0)), Vector((-1, 0, 0)), Vector((0, 0, 1)), sx, sz),
            "-y": (Vector((0, -hy, 0)), Vector((1, 0, 0)), Vector((0, 0, 1)), sx, sz),
            "+z": (Vector((0, 0, hz)), Vector((1, 0, 0)), Vector((0, 1, 0)), sx, sy),
            "-z": (Vector((0, 0, -hz)), Vector((1, 0, 0)), Vector((0, -1, 0)), sx, sy),
        }
        made = []
        for name, (c, u, v, wu, wv) in faces.items():
            if name in skip:
                continue
            pats = list(patterns) + list((face_patterns or {}).get(name, []))
            if bevel:
                pats.append(("bevel",))
            r = self._reg(wu, wv, mat, pats, density=density)
            corners = [c - u * wu / 2 - v * wv / 2, c + u * wu / 2 - v * wv / 2, c + u * wu / 2 + v * wv / 2, c - u * wu / 2 + v * wv / 2]
            vs = [self.bm.verts.new(M @ p) for p in corners]
            made.append(self._face(vs, [(r, 0, 0), (r, 1, 0), (r, 1, 1), (r, 0, 1)]))
        return made

    def lathe(self, profile, axis_m: Matrix, seg=24, mat="pintura", patterns=(), cap_start=None, cap_end=None, smooth=True,
              arc=None, density=None, sharp_rings=()):
        if arc is not None:
            return self._lathe_arc(profile, axis_m, seg, mat, patterns, arc, density)
        """Sólido de revolución alrededor del Z local de `axis_m`. `profile` = [(radio, z), ...].
        `cap_start/cap_end` = (material, patrones) para tapar los extremos con un disco."""
        n = seg
        rings = []
        for r, z in profile:
            ring = [self.bm.verts.new(axis_m @ Vector((r * math.cos(2 * math.pi * i / n), r * math.sin(2 * math.pi * i / n), z)))
                    for i in range(n)]
            rings.append(ring)
        # longitud del perfil (v) y circunferencia máxima (u)
        lens = [0.0]
        for (r0, z0), (r1, z1) in zip(profile, profile[1:]):
            lens.append(lens[-1] + math.hypot(r1 - r0, z1 - z0))
        L = max(lens[-1], 1e-4)
        C = 2 * math.pi * max(r for r, _ in profile)
        reg = self._reg(C, L, mat, list(patterns) + [("profile", [l / L for l in lens])], density=density)
        for k in range(len(rings) - 1):
            a, b = rings[k], rings[k + 1]
            v0, v1 = lens[k] / L, lens[k + 1] / L
            for i in range(n):
                j = (i + 1) % n
                u0, u1 = i / n, (i + 1) / n
                self._face([a[i], a[j], b[j], b[i]], [(reg, u0, v0), (reg, u1, v0), (reg, u1, v1), (reg, u0, v1)], smooth=smooth)
        for ring, cap, rr, flip in ((rings[0], cap_start, profile[0][0], True), (rings[-1], cap_end, profile[-1][0], False)):
            if cap is None or rr < 1e-5:
                continue
            cm, cp = cap if isinstance(cap, tuple) else (cap, [])
            cr = self._reg(2 * rr, 2 * rr, cm, list(cp) + [("disc",)], density=density)
            uvs = [(cr, 0.5 + 0.5 * math.cos(2 * math.pi * i / n), 0.5 + 0.5 * math.sin(2 * math.pi * i / n)) for i in range(n)]
            vs = list(ring)
            if flip:
                vs = vs[::-1]
                uvs = uvs[::-1]
            self._face(vs, uvs, smooth=False)
        return rings

    def _lathe_arc(self, profile, axis_m, seg, mat, patterns, arc, density):
        """Revolución parcial (de arc[0] a arc[1] radianes), abierta: guardabarros, cubiertas curvas."""
        a0, a1 = arc
        n = seg
        rings = []
        for r, z in profile:
            rings.append([self.bm.verts.new(axis_m @ Vector((r * math.cos(a0 + (a1 - a0) * i / n), r * math.sin(a0 + (a1 - a0) * i / n), z)))
                          for i in range(n + 1)])
        lens = [0.0]
        for (r0, z0), (r1, z1) in zip(profile, profile[1:]):
            lens.append(lens[-1] + math.hypot(r1 - r0, z1 - z0))
        L = max(lens[-1], 1e-4)
        C = (a1 - a0) * max(r for r, _ in profile)
        reg = self._reg(C, L, mat, list(patterns) + [("bevel",)], density=density)
        for k in range(len(rings) - 1):
            a, b = rings[k], rings[k + 1]
            for i in range(n):
                self._face([a[i], a[i + 1], b[i + 1], b[i]], [(reg, i / n, lens[k] / L), (reg, (i + 1) / n, lens[k] / L),
                                                               (reg, (i + 1) / n, lens[k + 1] / L), (reg, i / n, lens[k + 1] / L)], smooth=True)

    def tube(self, pts, r, seg=10, sub=6, mat="goma", patterns=(), density=None):
        """Tubo que sigue una curva Catmull-Rom (mangueras, cables, agarraderas)."""
        P = [Vector(p) for p in pts]
        path = []
        for i in range(len(P) - 1):
            p0, p1, p2, p3 = P[max(i - 1, 0)], P[i], P[i + 1], P[min(i + 2, len(P) - 1)]
            for k in range(sub):
                t = k / sub
                path.append(0.5 * ((2 * p1) + (-p0 + p2) * t + (2 * p0 - 5 * p1 + 4 * p2 - p3) * t * t + (-p0 + 3 * p1 - 3 * p2 + p3) * t ** 3))
        path.append(P[-1])
        L = sum((b - a).length for a, b in zip(path, path[1:]))
        reg = self._reg(2 * math.pi * r, L, mat, patterns, density=density)
        rings = []
        ref = Vector((0, 0, 1))
        for i, p in enumerate(path):
            t = (path[min(i + 1, len(path) - 1)] - path[max(i - 1, 0)]).normalized()
            if abs(t.dot(ref)) > 0.95:
                ref = Vector((1, 0, 0))
            x = t.cross(ref).normalized()
            y = t.cross(x).normalized()
            rings.append([self.bm.verts.new(p + (x * math.cos(2 * math.pi * j / seg) + y * math.sin(2 * math.pi * j / seg)) * r) for j in range(seg)])
        acc = [0.0]
        for a, b in zip(path, path[1:]):
            acc.append(acc[-1] + (b - a).length)
        for k in range(len(rings) - 1):
            a, b = rings[k], rings[k + 1]
            for j in range(seg):
                q = (j + 1) % seg
                self._face([a[j], a[q], b[q], b[j]], [(reg, j / seg, acc[k] / L), ((reg, (j + 1) / seg, acc[k] / L)),
                                                       (reg, (j + 1) / seg, acc[k + 1] / L), (reg, j / seg, acc[k + 1] / L)], smooth=True)

    def cyl(self, r, length, axis_m: Matrix, seg=16, mat="pintura", patterns=(), caps=True, cap_mat=None, cap_patterns=(),
            density=None):
        cap = ((cap_mat or mat), list(cap_patterns)) if caps else None
        return self.lathe([(r, -length / 2), (r, length / 2)], axis_m, seg, mat, patterns, cap, cap, density=density)

    def torus(self, R, r, axis_m: Matrix, seg=32, seg_minor=8, mat="goma", patterns=(), density=None):
        n, m = seg, seg_minor
        rings = []
        for i in range(n):
            a = 2 * math.pi * i / n
            ca, sa = math.cos(a), math.sin(a)
            rings.append([self.bm.verts.new(axis_m @ Vector(((R + r * math.cos(2 * math.pi * k / m)) * ca,
                                                              (R + r * math.cos(2 * math.pi * k / m)) * sa,
                                                              r * math.sin(2 * math.pi * k / m)))) for k in range(m)])
        reg = self._reg(2 * math.pi * R, 2 * math.pi * r, mat, patterns, density=density)
        for i in range(n):
            a, b = rings[i], rings[(i + 1) % n]
            for k in range(m):
                q = (k + 1) % m
                self._face([a[k], b[k], b[q], a[q]], [(reg, i / n, k / m), (reg, (i + 1) / n, k / m), (reg, (i + 1) / n, (k + 1) / m),
                                                       (reg, i / n, (k + 1) / m)], smooth=True)

    def quad(self, corners, mat, patterns=(), key=None, density=None, w_m=None, h_m=None, smooth=False):
        """Cuadrilátero (calcomanía, franja, cartel): esquinas en orden u0v0, u1v0, u1v1, u0v1."""
        c = [Vector(p) for p in corners]
        w = w_m or (c[1] - c[0]).length
        h = h_m or (c[3] - c[0]).length
        r = self._reg(w, h, mat, patterns, key=key, density=density)
        vs = [self.bm.verts.new(p) for p in c]
        return self._face(vs, [(r, 0, 0), (r, 1, 0), (r, 1, 1), (r, 0, 1)], smooth=smooth)

    def plain_quad(self, corners, mat_index):
        """Cuadrilátero con UV 0..1 propias y material aparte (espejos, pantalla): no usa el atlas."""
        vs = [self.bm.verts.new(Vector(p)) for p in corners]
        f = self.bm.faces.new(vs)
        f.material_index = mat_index
        f.smooth = False
        self.pending.append((f, [("raw", 0, 0), ("raw", 1, 0), ("raw", 1, 1), ("raw", 0, 1)]))
        return f

    def extrude_profile(self, pts2d, depth, axis_m: Matrix, mat="pintura", patterns=(), density=None):
        """Prisma: polígono 2D (en XY local, antihorario) extruido `depth` en Z local, centrado."""
        n = len(pts2d)
        lo = [self.bm.verts.new(axis_m @ Vector((x, y, -depth / 2))) for x, y in pts2d]
        hi = [self.bm.verts.new(axis_m @ Vector((x, y, depth / 2))) for x, y in pts2d]
        xs = [p[0] for p in pts2d]
        ys = [p[1] for p in pts2d]
        W, H = max(xs) - min(xs), max(ys) - min(ys)
        rt = self._reg(W, H, mat, list(patterns) + [("bevel",)], density=density)
        rb = self._reg(W, H, mat, list(patterns), density=density)
        uv = [((x - min(xs)) / max(W, 1e-6), (y - min(ys)) / max(H, 1e-6)) for x, y in pts2d]
        self._face(hi, [(rt, u, v) for u, v in uv])
        self._face(lo[::-1], [(rb, 1 - u, v) for u, v in uv[::-1]])
        for i in range(n):
            j = (i + 1) % n
            L = (Vector(pts2d[j]) - Vector(pts2d[i])).length
            rs = self._reg(L, depth, mat, list(patterns) + [("bevel",)], density=density)
            self._face([lo[i], lo[j], hi[j], hi[i]], [(rs, 0, 0), (rs, 1, 0), (rs, 1, 1), (rs, 0, 1)])

    # -- salida
    def to_object(self, name, coll, pivot: Matrix, extra_materials=()):
        """Crea el objeto con origen en `pivot` (la geometría se guarda en coordenadas locales)."""
        bm = self.bm
        bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=1e-7)
        me = bpy.data.meshes.new(name)
        ob = bpy.data.objects.new(name, me)
        coll.objects.link(ob)
        ob.matrix_world = pivot
        self._pivot_inv = pivot.inverted()
        self._me = me
        return ob

    def finalize(self, ob):
        """Escribe las UV definitivas (después de empaquetar el atlas), triangula y marca bordes duros."""
        bm = self.bm
        uvl = self.uvl
        S = self.atlas
        for f, uvs in self.pending:
            if not f.is_valid:
                continue
            for loop, item in zip(f.loops, uvs):
                if item[0] == "raw":
                    loop[uvl].uv = (item[1], item[2])
                else:
                    reg, u, v = item
                    loop[uvl].uv = S.uv_of(reg, min(max(u, 0), 1), min(max(v, 0), 1))
        bm.transform(self._pivot_inv)
        bm.normal_update()
        # bordes duros entre caras planas y curvas, o con mucho ángulo
        for e in bm.edges:
            if len(e.link_faces) != 2:
                e.smooth = False
                continue
            a, b = e.link_faces
            if (a.smooth != b.smooth) or a.normal.angle(b.normal, 0) > math.radians(55) or a.material_index != b.material_index:
                e.smooth = False
        bmesh.ops.triangulate(bm, faces=bm.faces, quad_method="BEAUTY", ngon_method="BEAUTY")
        bm.to_mesh(self._me)
        bm.free()
        return ob


def tris(ob):
    return sum(len(p.vertices) - 2 for p in ob.data.polygons) if ob.type == "MESH" else 0


# ---------------------------------------------------------------------------------------------------------------------
# Pintado del atlas
# ---------------------------------------------------------------------------------------------------------------------
class Painter:
    """Pinta todas las regiones del atlas. `materials`: nombre → dict(color sRGB, rough, metal, noise, height)."""

    def __init__(self, atlas: Atlas, materials: dict, seed=3):
        S = atlas.size
        self.a = atlas
        self.M = materials
        self.bc = np.zeros((S, S, 3), np.float32)
        self.h = np.zeros((S, S), np.float32)
        self.r = np.ones((S, S), np.float32) * 0.6
        self.m = np.zeros((S, S), np.float32)
        self.mask = np.zeros((S, S), bool)
        self.rng = np.random.default_rng(seed)

    # ---- helpers de región
    def _slices(self, reg):
        x, y, w, h = reg.rect
        return slice(y, y + h), slice(x, x + w), w, h

    def paint_all(self):
        for reg in self.a.regions:
            self.paint(reg)

    def paint(self, reg):
        ys, xs, w, h = self._slices(reg)
        mat = self.M[reg.mat]
        col = np.array(mat["color"], np.float32)
        n = self.rng.normal(0, 1, (h, w)).astype(np.float32)
        noise_amt = mat.get("noise", 0.03)
        self.bc[ys, xs] = col[None, None, :] * (1 + noise_amt * _blur(n, 2)[..., None])
        self.r[ys, xs] = mat["rough"] + mat.get("rough_var", 0.04) * _blur(n, 3)
        self.m[ys, xs] = mat["metal"]
        self.h[ys, xs] = mat.get("grain", 0.0) * _blur(self.rng.normal(0, 1, (h, w)).astype(np.float32), 1)
        self.mask[ys, xs] = True
        for p in reg.patterns:
            fn = getattr(self, "p_" + p[0], None)
            if fn:
                fn(reg, ys, xs, w, h, *p[1:])

    # ---- patrones (u → columnas, v → filas invertidas)
    def _uv(self, w, h):
        u = (np.arange(w) + 0.5) / w
        v = 1 - (np.arange(h) + 0.5) / h
        return np.meshgrid(u, v)

    def p_bevel(self, reg, ys, xs, w, h, width_m=0.004):
        d = (reg.density or self.a.density) * width_m * (w / max(reg.w_m * (reg.density or self.a.density), 1))
        d = max(1.5, d)
        X, Y = np.meshgrid(np.arange(w) + 0.5, np.arange(h) + 0.5)
        e = np.minimum(np.minimum(X, w - X), np.minimum(Y, h - Y))
        ramp = np.clip(e / d, 0, 1)
        self.h[ys, xs] += (np.sin(ramp * math.pi / 2) - 1) * 1.2
        # filo levemente más claro y gastado
        edge = (1 - ramp)[..., None]
        self.bc[ys, xs] = self.bc[ys, xs] * (1 + 0.10 * edge)

    def p_profile(self, reg, *a):
        pass

    def p_disc(self, reg, *a):
        pass

    def p_tread(self, reg, ys, xs, w, h, v0=0.25, v1=0.75, n=36):
        """Dibujo de cubierta industrial: tacos en V sobre la banda de rodadura (v0..v1 del perfil)."""
        U, V = self._uv(w, h)
        band = (V > v0) & (V < v1)
        t = (V - v0) / max(v1 - v0, 1e-6)
        chevron = ((U * n + np.abs(t - 0.5) * 1.6) % 1.0)
        groove = band & (chevron < 0.28)
        self.h[ys, xs] -= groove * 3.0
        self.bc[ys, xs] *= np.where(groove, 0.6, 1.0)[..., None]
        self.r[ys, xs] = np.where(band, np.clip(self.r[ys, xs] + 0.05, 0, 1), self.r[ys, xs])

    def p_sidewall(self, reg, ys, xs, w, h, v0=0.0, v1=0.25):
        U, V = self._uv(w, h)
        ring = (V > v0) & (V < v1)
        ribs = (np.abs(((V - v0) / max(v1 - v0, 1e-6)) * 6 % 1 - 0.5) < 0.08) & ring
        self.h[ys, xs] += ribs * 0.8

    def p_vent(self, reg, ys, xs, w, h, n=8, u0=0.15, u1=0.85, v0=0.2, v1=0.8):
        """Rejilla de ventilación: ranuras horizontales rebajadas."""
        U, V = self._uv(w, h)
        inside = (U > u0) & (U < u1) & (V > v0) & (V < v1)
        t = (V - v0) / max(v1 - v0, 1e-6)
        slot = inside & ((t * n) % 1 < 0.55)
        self.h[ys, xs] -= slot * 3.5
        self.bc[ys, xs] *= np.where(slot, 0.35, 1.0)[..., None]

    def p_screws(self, reg, ys, xs, w, h, inset=0.08, r_px=None, n_u=2, n_v=2):
        """Tornillos en las esquinas (o grilla n_u × n_v)."""
        rp = r_px or max(2.0, min(w, h) * 0.035)
        X, Y = np.meshgrid(np.arange(w) + 0.5, np.arange(h) + 0.5)
        for iu in range(n_u):
            for iv in range(n_v):
                cx = w * (inset + (1 - 2 * inset) * (iu / max(n_u - 1, 1)))
                cy = h * (inset + (1 - 2 * inset) * (iv / max(n_v - 1, 1)))
                d = np.hypot(X - cx, Y - cy) / rp
                dome = np.clip(1 - d * d, 0, 1)
                self.h[ys, xs] += np.sqrt(dome) * 2.0
                hexa = (np.abs(X - cx) < rp * 0.35) & (np.abs(Y - cy) < rp * 0.35)
                self.h[ys, xs] -= hexa * (d < 1) * 1.2
                self.m[ys, xs] = np.where(d < 1, 0.9, self.m[ys, xs])
                self.r[ys, xs] = np.where(d < 1, 0.35, self.r[ys, xs])
                self.bc[ys, xs] = np.where((d < 1)[..., None], np.array(srgb_to_lin_np((0.62, 0.63, 0.65))), self.bc[ys, xs])

    def p_checker(self, reg, ys, xs, w, h, pitch_m=0.03):
        """Chapa antideslizante (lágrimas en diagonal alternada)."""
        d = (reg.density or self.a.density)
        X, Y = np.meshgrid(np.arange(w) + 0.5, np.arange(h) + 0.5)
        p = max(4.0, pitch_m * d * (w / max(reg.w_m * d, 1)))
        gx, gy = X / p, Y / p
        cx, cy = np.floor(gx), np.floor(gy)
        fx, fy = gx - cx - 0.5, gy - cy - 0.5
        alt = ((cx + cy) % 2) == 0
        a = np.where(alt, 1.0, -1.0)
        rx = (fx + a * fy) / 1.414
        ry = (fx - a * fy) / 1.414
        tear = (rx / 0.32) ** 2 + (ry / 0.09) ** 2 < 1
        self.h[ys, xs] += tear * 2.0

    def p_ribs(self, reg, ys, xs, w, h, n=7, axis="v"):
        """Estrías (pedales, empuñaduras)."""
        U, V = self._uv(w, h)
        t = V if axis == "v" else U
        rib = (t * n) % 1 < 0.45
        self.h[ys, xs] += rib * 1.6
        self.bc[ys, xs] *= np.where(rib, 1.0, 0.75)[..., None]

    def p_grid(self, reg, ys, xs, w, h, n_u=6, n_v=4, bar=0.12):
        """Malla / rejilla (protección del respaldo, techo)."""
        U, V = self._uv(w, h)
        g = ((U * n_u) % 1 < bar) | ((V * n_v) % 1 < bar)
        self.h[ys, xs] += g * 2.0

    def p_hazard(self, reg, ys, xs, w, h, stripes=None, a="#f2c200", b="#141414"):
        """Franjas de peligro amarillas y negras a 45°."""
        U, V = self._uv(w, h)
        n = stripes or max(2, int(round(reg.w_m / 0.10)))
        k = reg.h_m / max(reg.w_m, 1e-6)
        s = ((U + V * k) * n) % 1 < 0.5
        ca = np.array(srgb_to_lin_np(hexc(a)))
        cb = np.array(srgb_to_lin_np(hexc(b)))
        self.bc[ys, xs] = np.where(s[..., None], ca, cb)
        self.r[ys, xs] = 0.55

    def p_flag_uy(self, reg, ys, xs, w, h):
        """Bandera de Uruguay: 9 franjas (5 blancas, 4 azules) y el Sol de Mayo en el cantón."""
        from PIL import Image, ImageDraw
        W, H = w * 4, h * 4
        img = Image.new("RGB", (W, H), "white")
        dr = ImageDraw.Draw(img)
        blue = (0, 56, 168)
        sh = H / 9
        for i in range(9):
            if i % 2 == 1:
                dr.rectangle([0, i * sh, W, (i + 1) * sh], fill=blue)
        cw, ch = W * 0.4, sh * 5
        dr.rectangle([0, 0, cw, ch], fill="white")
        cx, cy, rr = cw / 2, ch / 2, ch * 0.22
        gold = (252, 209, 22)
        brown = (125, 83, 21)
        for k in range(16):
            a = 2 * math.pi * k / 16
            ray = rr * (2.0 if k % 2 == 0 else 1.75)
            w2 = 0.11
            pts = [(cx + rr * 0.9 * math.cos(a - w2), cy + rr * 0.9 * math.sin(a - w2)), (cx + ray * math.cos(a), cy + ray * math.sin(a)),
                   (cx + rr * 0.9 * math.cos(a + w2), cy + rr * 0.9 * math.sin(a + w2))]
            dr.polygon(pts, fill=gold, outline=brown)
        dr.ellipse([cx - rr, cy - rr, cx + rr, cy + rr], fill=gold, outline=brown, width=max(1, int(rr * 0.08)))
        self._put_image(img, ys, xs, w, h, rough=0.4, raised=0.5)

    def p_text(self, reg, ys, xs, w, h, lines, fg="#ffffff", bg=None, raised=0.8, rough=None, align="center", border=None,
               font=FONT_BOLD, pad=0.08, metal=None):
        """Texto (una o varias líneas) ajustado a la región; opcionalmente con fondo, borde y relieve."""
        from PIL import Image, ImageDraw, ImageFont
        Wd, Hd = w * 4, h * 4
        img = Image.new("RGBA", (Wd, Hd), (0, 0, 0, 0))
        dr = ImageDraw.Draw(img)
        if bg:
            dr.rectangle([0, 0, Wd, Hd], fill=bg)
        if border:
            bw = max(2, int(min(Wd, Hd) * 0.04))
            dr.rectangle([bw / 2, bw / 2, Wd - bw / 2, Hd - bw / 2], outline=border, width=bw)
        lines = [lines] if isinstance(lines, str) else list(lines)
        # tamaño de letra que entra
        avail_w, avail_h = Wd * (1 - 2 * pad), Hd * (1 - 2 * pad)
        size = int(avail_h / len(lines) * 0.82)
        while size > 4:
            f = ImageFont.truetype(font, size)
            widths = [dr.textbbox((0, 0), ln, font=f)[2] for ln in lines]
            if max(widths) <= avail_w:
                break
            size = int(size * 0.92)
        f = ImageFont.truetype(font, size)
        lh = avail_h / len(lines)
        for i, ln in enumerate(lines):
            bb = dr.textbbox((0, 0), ln, font=f)
            tw, th = bb[2] - bb[0], bb[3] - bb[1]
            x = (Wd - tw) / 2 - bb[0] if align == "center" else Wd * pad - bb[0]
            y = Hd * pad + lh * i + (lh - th) / 2 - bb[1]
            dr.text((x, y), ln, font=f, fill=fg)
        im = np.asarray(img.resize((w, h), Image.LANCZOS), np.float32) / 255
        rgb = srgb_to_lin_np(im[..., :3])
        a = im[..., 3:4]
        self.bc[ys, xs] = self.bc[ys, xs] * (1 - a) + rgb * a
        # relieve solo de las letras (no del fondo): diferencia de luminancia con el fondo
        if raised:
            tm = _text_mask(lines, w, h, font, size / 4, pad, align)
            self.h[ys, xs] += tm * raised
        if rough is not None:
            self.r[ys, xs] = np.where(a[..., 0] > 0.5, rough, self.r[ys, xs])
        if metal is not None:
            self.m[ys, xs] = np.where(a[..., 0] > 0.5, metal, self.m[ys, xs])

    def p_image(self, reg, ys, xs, w, h, fn):
        img = fn(w * 4, h * 4)
        self._put_image(img, ys, xs, w, h)

    def _put_image(self, img, ys, xs, w, h, rough=None, raised=0.0):
        from PIL import Image
        im = np.asarray(img.convert("RGBA").resize((w, h), Image.LANCZOS), np.float32) / 255
        a = im[..., 3:4]
        self.bc[ys, xs] = self.bc[ys, xs] * (1 - a) + srgb_to_lin_np(im[..., :3]) * a
        if rough is not None:
            self.r[ys, xs] = rough
        if raised:
            self.h[ys, xs] += raised

    def p_display(self, reg, ys, xs, w, h):
        self.bc[ys, xs] = np.array(srgb_to_lin_np((0.02, 0.03, 0.04)))
        self.r[ys, xs] = 0.15

    def p_wood(self, reg, ys, xs, w, h, along="u"):
        U, V = self._uv(w, h)
        t = U if along == "u" else V
        s = V if along == "u" else U
        grain = np.sin((s * 40 + 3 * np.sin(t * 6 + s * 9)) * math.pi) * 0.5 + 0.5
        self.bc[ys, xs] *= (0.85 + 0.25 * grain)[..., None]
        self.h[ys, xs] += grain * 0.4

    def p_concrete(self, reg, ys, xs, w, h):
        n = _blur(self.rng.normal(0, 1, (h, w)).astype(np.float32), 6)
        n2 = _blur(self.rng.normal(0, 1, (h, w)).astype(np.float32), 1)
        self.bc[ys, xs] *= (1 + 0.08 * n + 0.03 * n2)[..., None]
        self.r[ys, xs] = 0.75 + 0.08 * n
        self.h[ys, xs] += n2 * 0.3

    def p_corrugated(self, reg, ys, xs, w, h, pitch_m=0.2, axis="u"):
        U, V = self._uv(w, h)
        t = U if axis == "u" else V
        L = reg.w_m if axis == "u" else reg.h_m
        self.h[ys, xs] += np.sin(t * L / pitch_m * 2 * math.pi) * 3.0

    def p_dots(self, reg, ys, xs, w, h, color="#ffb000"):
        pass

    def p_tint(self, reg, ys, xs, w, h, color, u0=0, u1=1, v0=0, v1=1, rough=None, metal=None):
        U, V = self._uv(w, h)
        sel = (U >= u0) & (U <= u1) & (V >= v0) & (V <= v1)
        self.bc[ys, xs] = np.where(sel[..., None], np.array(srgb_to_lin_np(hexc(color))), self.bc[ys, xs])
        if rough is not None:
            self.r[ys, xs] = np.where(sel, rough, self.r[ys, xs])
        if metal is not None:
            self.m[ys, xs] = np.where(sel, metal, self.m[ys, xs])

    def p_band(self, reg, ys, xs, w, h, color, v0, v1):
        self.p_tint(reg, ys, xs, w, h, color, 0, 1, v0, v1)

    # ---- salida
    def finish(self, outdir, name, ao=None, normal_strength=1.0):
        from PIL import Image
        S = self.a.size
        mask = self.mask
        # normal map desde la altura (Sobel), OpenGL (verde hacia arriba)
        h = self.h * normal_strength
        hp = np.pad(h, 1, mode="edge")
        dx = (hp[1:-1, 2:] - hp[1:-1, :-2]) * 0.5
        dy = (hp[:-2, 1:-1] - hp[2:, 1:-1]) * 0.5   # filas hacia abajo → v hacia arriba
        k = 0.35
        nx, ny, nz = -dx * k, -dy * k, np.ones_like(h)
        ln = np.sqrt(nx * nx + ny * ny + nz * nz)
        nrm = np.stack([nx / ln, ny / ln, nz / ln], -1) * 0.5 + 0.5
        ao_arr = np.ones((S, S), np.float32) if ao is None else ao
        bc = lin_to_srgb_np(np.clip(self.bc, 0, 1))
        orm = np.stack([ao_arr, np.clip(self.r, 0.04, 1), np.clip(self.m, 0, 1)], -1)
        bc = _dilate(bc, mask, 8)
        orm = _dilate(orm, mask, 8)
        nrm = _dilate(nrm, mask, 8)
        nrm[~_grow(mask, 8)] = (0.5, 0.5, 1.0)
        os.makedirs(outdir, exist_ok=True)
        out = {}

        def save(arr, key, mode="RGB"):
            p = os.path.join(outdir, f"{name}_{key}.png")
            data = (np.clip(arr, 0, 1) * 255 + 0.5).astype(np.uint8)
            Image.fromarray(data, mode).save(p, optimize=True)
            out[key] = p
        save(bc, "BaseColor")
        save(nrm, "Normal")
        save(orm, "ORM")
        save(orm[..., 2], "Metallic", "L")
        save(orm[..., 1], "Roughness", "L")
        save(orm[..., 0], "AO", "L")
        return out


# ---------------------------------------------------------------------------------------------------------------------
# numpy auxiliares
# ---------------------------------------------------------------------------------------------------------------------
def srgb_to_lin_np(c):
    c = np.asarray(c, np.float32)
    return np.where(c > 0.04045, ((c + 0.055) / 1.055) ** 2.4, c / 12.92)


def lin_to_srgb_np(c):
    c = np.asarray(c, np.float32)
    return np.where(c > 0.0031308, 1.055 * np.power(np.maximum(c, 0), 1 / 2.4) - 0.055, 12.92 * c)


def _blur(a, r):
    if r <= 0:
        return a
    k = np.ones(2 * r + 1, np.float32) / (2 * r + 1)
    a = np.apply_along_axis(lambda x: np.convolve(x, k, mode="same"), 0, a) if a.shape[0] > 2 * r else a
    a = np.apply_along_axis(lambda x: np.convolve(x, k, mode="same"), 1, a) if a.shape[1] > 2 * r else a
    s = a.std()
    return a / s if s > 1e-6 else a


def _dilate(arr, mask, px):
    a = arr.copy()
    m = mask.copy()
    for _ in range(px):
        if m.all():
            break
        acc = np.zeros(a.shape, np.float32)
        cnt = np.zeros(m.shape, np.float32)
        for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            sm = np.roll(np.roll(m, dy, 0), dx, 1)
            sa = np.roll(np.roll(a, dy, 0), dx, 1)
            acc += sa * (sm[..., None] if a.ndim == 3 else sm)
            cnt += sm
        new = (~m) & (cnt > 0)
        if a.ndim == 3:
            a[new] = acc[new] / cnt[new][:, None]
        else:
            a[new] = acc[new] / cnt[new]
        m = m | new
    return a


def _grow(mask, px):
    m = mask.copy()
    for _ in range(px):
        m = m | np.roll(m, 1, 0) | np.roll(m, -1, 0) | np.roll(m, 1, 1) | np.roll(m, -1, 1)
    return m


def _text_mask(lines, w, h, font, size_px, pad, align):
    from PIL import Image, ImageDraw, ImageFont
    Wd, Hd = w * 4, h * 4
    img = Image.new("L", (Wd, Hd), 0)
    dr = ImageDraw.Draw(img)
    f = ImageFont.truetype(font, max(4, int(size_px * 4)))
    lh = Hd * (1 - 2 * pad) / len(lines)
    for i, ln in enumerate(lines):
        bb = dr.textbbox((0, 0), ln, font=f)
        tw, th = bb[2] - bb[0], bb[3] - bb[1]
        x = (Wd - tw) / 2 - bb[0] if align == "center" else Wd * pad - bb[0]
        y = Hd * pad + lh * i + (lh - th) / 2 - bb[1]
        dr.text((x, y), ln, font=f, fill=255)
    return np.asarray(img.resize((w, h), Image.LANCZOS), np.float32) / 255


def axis_m(axis, center, roll=0.0):
    """Matriz con el Z local sobre `axis` ('X','Y','Z' o un Vector) centrada en `center`."""
    c = Vector(center)
    if isinstance(axis, str):
        rot = {"Z": Matrix.Identity(4), "Y": Matrix.Rotation(-math.pi / 2, 4, "X"), "X": Matrix.Rotation(math.pi / 2, 4, "Y")}[axis]
    else:
        q = Vector((0, 0, 1)).rotation_difference(Vector(axis).normalized())
        rot = q.to_matrix().to_4x4()
    if roll:
        rot = rot @ Matrix.Rotation(roll, 4, "Z")
    return Matrix.Translation(c) @ rot

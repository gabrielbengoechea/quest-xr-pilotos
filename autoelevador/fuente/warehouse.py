"""
Centro logístico compacto para el minijuego: nave, estanterías de paletización de 3 niveles, pallets EUR con huecos para
las horquillas, cargas genéricas de la industria uruguaya, conos de slalom, zonas de descarga y señalética en español.

Marco: metros, Z arriba. Nave de 28 × 20 m centrada en el origen; el portón está en la pared sur (y = -10).
"""
import math

from mathutils import Matrix, Vector

from kit3d import Builder, axis_m, hexc, srgb_to_lin


def M(h, rough, metal, noise=0.03, grain=0.0, rough_var=0.04):
    return dict(color=srgb_to_lin(hexc(h)), rough=rough, metal=metal, noise=noise, grain=grain, rough_var=rough_var)


MATS_ENV = {
    "concreto": M("#a3a5a6", 0.8, 0.0, noise=0.06, grain=0.4),
    "pared": M("#dde2e7", 0.6, 0.3),
    "techo": M("#6f7882", 0.6, 0.4),
    "columna": M("#2d5fa8", 0.45, 0.3),
    "rack_azul": M("#1f4f9a", 0.42, 0.3),
    "rack_naranja": M("#ee6f19", 0.4, 0.25),
    "madera": M("#c8a46e", 0.78, 0.0, noise=0.08, grain=0.6),
    "madera_osc": M("#9c7a4a", 0.8, 0.0, noise=0.08, grain=0.6),
    "caja_azul": M("#2b6fbe", 0.5, 0.0),
    "caja_blanca": M("#eef1f3", 0.55, 0.0),
    "carton": M("#c79b67", 0.85, 0.0, noise=0.06, grain=0.3),
    "tambor_rojo": M("#b8261f", 0.4, 0.5),
    "tambor_azul": M("#1d58a6", 0.4, 0.5),
    "metal": M("#9aa0a6", 0.35, 0.9),
    "cono": M("#ff6a13", 0.5, 0.0),
    "reflectivo": M("#f4f4f4", 0.25, 0.0),
    "amarillo": M("#f2c200", 0.5, 0.0),
    "negro": M("#1b1c1e", 0.6, 0.0),
    "verde": M("#1a9e4a", 0.5, 0.0),
    "blanco": M("#f3f5f7", 0.5, 0.0),
    "puerta": M("#c4cad1", 0.45, 0.6),
    "lampara": M("#fffbea", 0.2, 0.0, noise=0.0),
    "film": M("#dfe6ec", 0.2, 0.0, noise=0.05),
}

W, D, H = 28.0, 20.0, 8.0          # nave
RACK_Y = 8.45                      # fondo: centro de la estantería
RACK_LEVELS = (0.0, 1.50, 3.00)    # altura del apoyo de cada nivel (piso, medio, alto)
BAY = 2.70                         # luz libre entre puntales
RACK_DEPTH = 1.10
PALLET = (0.80, 1.20, 0.144)       # EUR: ancho (X), largo (Y), alto
DENS = 90


# ---------------------------------------------------------------------------------------------------------------------
def build_building(b: Builder):
    hx, hy = W / 2, D / 2
    # piso
    b.quad([(-hx, -hy, 0), (hx, -hy, 0), (hx, hy, 0), (-hx, hy, 0)], "concreto", [("concrete",)], density=14)
    # paredes interiores (chapa ondulada) con zócalo amarillo/negro
    walls = [((-hx, -hy), (hx, -hy)), ((hx, -hy), (hx, hy)), ((hx, hy), (-hx, hy)), ((-hx, hy), (-hx, -hy))]
    for (x0, y0), (x1, y1) in walls:
        # la cara mira hacia adentro: orden de esquinas antihorario visto desde el interior
        # recorrido horario visto desde arriba → la normal apunta hacia adentro de la nave
        b.quad([(x1, y1, 0.5), (x0, y0, 0.5), (x0, y0, H), (x1, y1, H)], "pared", [("corrugated", 0.25, "u")], density=12)
        b.quad([(x1, y1, 0.0), (x0, y0, 0.0), (x0, y0, 0.5), (x1, y1, 0.5)], "blanco", [("hazard", int(math.hypot(x1 - x0, y1 - y0) / 0.4))],
               density=14, key=f"zocalo_{round(math.hypot(x1 - x0, y1 - y0))}")
    # techo
    b.quad([(-hx, hy, H), (hx, hy, H), (hx, -hy, H), (-hx, -hy, H)], "techo", [("corrugated", 0.3, "v")], density=8)
    # cerchas del techo (vigas) y columnas
    for x in (-7.0, 0.0, 7.0):
        b.box((0.30, D, 0.40), (x, 0, H - 0.25), mat="columna", density=20)
    for x in (-hx + 0.2, hx - 0.2):
        for y in (-5.0, 3.0):
            b.box((0.30, 0.30, H), (x, y, H / 2), mat="columna", density=30, skip=("-z", "+z"))
    # luminarias LED
    for x in (-10.5, -3.5, 3.5, 10.5):
        for y in (-5.0, 1.0, 6.5):
            b.box((1.2, 0.30, 0.06), (x, y, H - 0.50), mat="lampara", density=40, face_patterns={"-z": [("grid", 6, 1, 0.08)]})
    # portón (pared sur), marco y franjas
    b.quad([(11.5, -hy + 0.02, 0.0), (7.0, -hy + 0.02, 0.0), (7.0, -hy + 0.02, 4.6), (11.5, -hy + 0.02, 4.6)], "puerta",
           [("corrugated", 0.12, "v"), ("text", ["PORTÓN 1 · MUELLE DE CARGA"], "#1b1c1e", None, 0.3)], density=40)
    for x in (6.85, 11.65):
        b.box((0.30, 0.20, 4.8), (x, -hy + 0.10, 2.4), mat="amarillo", density=60, face_patterns={"+y": [("hazard", 16)]})
    # señalética en las paredes
    signs = [
        # (centro, ancho, alto, pared, líneas, fondo, texto)
        ((0.0, hy - 0.02, 6.2), 11.0, 1.2, "N", ["URUGUAY LOGÍSTICA · CENTRO DE DISTRIBUCIÓN"], "#123a6b", "#ffffff"),
        ((-6.5, -hy + 0.02, 5.6), 7.0, 1.0, "S", ["PUERTO DE MONTEVIDEO"], "#0d2f57", "#ffffff"),
        ((-hx + 0.02, 0.0, 3.6), 3.2, 1.6, "W", ["VELOCIDAD", "MÁXIMA 10 km/h"], "#ffffff", "#b3121a"),
        ((-hx + 0.02, -6.0, 3.6), 3.2, 1.6, "W", ["USO OBLIGATORIO", "DE CINTURÓN"], "#1d58a6", "#ffffff"),
        ((hx - 0.02, 2.0, 3.6), 3.2, 1.6, "E", ["ATENCIÓN", "PEATONES"], "#f2c200", "#1b1c1e"),
        ((hx - 0.02, -5.0, 3.6), 3.2, 1.6, "E", ["HECHO EN URUGUAY", "TRABAJO SEGURO"], "#ffffff", "#123a6b"),
        ((0.0, hy - 0.02, 4.85), 4.0, 0.6, "N", ["NIVEL ALTO · 3,00 m"], "#ee6f19", "#ffffff"),
    ]
    for (cx, cy, cz), w, h, side, lines, bg, fg in signs:
        _wall_quad(b, (cx, cy, cz), w, h, side, "blanco", [("text", lines, fg, bg, 0.3, None, "center", None)], density=80)
    # bandera grande colgada en la pared norte
    _wall_quad(b, (-10.5, hy - 0.03, 5.2), 3.6, 2.4, "N", "blanco", [("flag_uy",)], density=60)
    _wall_quad(b, (10.5, hy - 0.03, 5.2), 3.6, 2.4, "N", "blanco", [("flag_uy",)], density=60)
    # senda peatonal (verde) junto a la pared oeste
    _floor_quad(b, (-hx + 0.9, 0.0), 1.2, D - 1.0, "verde", [("text", ["SENDA PEATONAL"] , "#ffffff", None, 0.0)], density=20)


def _wall_quad(b, c, w, h, side, mat, patterns, density):
    cx, cy, cz = c
    if side == "N":      # pared norte: el cartel mira hacia -Y (se lee de izquierda a derecha en +X)
        pts = [(cx - w / 2, cy, cz - h / 2), (cx + w / 2, cy, cz - h / 2), (cx + w / 2, cy, cz + h / 2), (cx - w / 2, cy, cz + h / 2)]
    elif side == "S":    # mira hacia +Y
        pts = [(cx + w / 2, cy, cz - h / 2), (cx - w / 2, cy, cz - h / 2), (cx - w / 2, cy, cz + h / 2), (cx + w / 2, cy, cz + h / 2)]
    elif side == "W":    # mira hacia +X
        pts = [(cx, cy - w / 2, cz - h / 2), (cx, cy + w / 2, cz - h / 2), (cx, cy + w / 2, cz + h / 2), (cx, cy - w / 2, cz + h / 2)]
    else:                # E: mira hacia -X
        pts = [(cx, cy + w / 2, cz - h / 2), (cx, cy - w / 2, cz - h / 2), (cx, cy - w / 2, cz + h / 2), (cx, cy + w / 2, cz + h / 2)]
    b.quad(pts, mat, patterns, density=density)


def _floor_quad(b, c, w, d, mat, patterns, density, z=0.004, key=None, rot=0.0):
    cx, cy = c
    ca, sa = math.cos(rot), math.sin(rot)
    loc = [(-w / 2, -d / 2), (w / 2, -d / 2), (w / 2, d / 2), (-w / 2, d / 2)]
    pts = [(cx + x * ca - y * sa, cy + x * sa + y * ca, z) for x, y in loc]
    return b.quad(pts, mat, patterns, density=density, key=key)


def build_racks(b: Builder, n_bays=4, x0=None):
    """Una fila de estanterías selectivas frente a la pared norte: puntales azules, largueros naranjas, 3 niveles."""
    post = 0.09
    n_up = n_bays + 1
    width = n_bays * (BAY + post) + post
    x0 = -width / 2 if x0 is None else x0
    yf, yb = RACK_Y - RACK_DEPTH / 2, RACK_Y + RACK_DEPTH / 2
    top = 3.95
    for i in range(n_up):
        x = x0 + post / 2 + i * (BAY + post)
        for y in (yf, yb):
            b.box((post, 0.07, top), (x, y, top / 2), mat="rack_azul", density=60, face_patterns={"-y": [("vent", 30, 0.3, 0.7, 0.02, 0.98)]})
            b.box((0.16, 0.16, 0.01), (x, y, 0.005), mat="metal", density=60)      # placa base
        # arriostramiento en zigzag del bastidor
        for k in range(6):
            z0, z1 = 0.15 + k * 0.62, 0.15 + (k + 1) * 0.62
            p0 = Vector((x, yf, z0)) if k % 2 == 0 else Vector((x, yb, z0))
            p1 = Vector((x, yb, z1)) if k % 2 == 0 else Vector((x, yf, z1))
            b.box((0.03, 0.03, (p1 - p0).length), (p0 + p1) / 2, rot=Vector((0, 0, 1)).rotation_difference((p1 - p0).normalized()).to_matrix(),
                  mat="rack_azul", density=40, bevel=False)
    # largueros (pares delantero/trasero) en los niveles medio y alto, con cartel de nivel
    names = {1.50: "NIVEL MEDIO · 1,50 m", 3.00: "NIVEL ALTO · 3,00 m"}
    for j in range(n_bays):
        xc = x0 + post + j * (BAY + post) + BAY / 2
        for z in RACK_LEVELS[1:]:
            for y in (yf, yb):
                b.box((BAY, 0.05, 0.12), (xc, y, z - 0.06), mat="rack_naranja", density=60)
            # rejilla de seguridad (malla) apoyada en los largueros
            b.box((BAY - 0.04, RACK_DEPTH - 0.04, 0.012), (xc, RACK_Y, z + 0.006), mat="metal", density=40,
                  face_patterns={"+z": [("grid", 30, 12, 0.18)]})
            # cartel del nivel en el larguero delantero
            b.quad([(xc - 0.30, yf - 0.026, z - 0.10), (xc + 0.30, yf - 0.026, z - 0.10), (xc + 0.30, yf - 0.026, z - 0.02),
                    (xc - 0.30, yf - 0.026, z - 0.02)], "amarillo", [("text", [names[z]], "#1b1c1e", None, 0.2)], density=300,
                   key=f"nivel_{z}")
        # rótulo del nivel bajo (en el piso)
        _floor_quad(b, (xc, yf - 0.25), 0.9, 0.3, "amarillo", [("text", ["NIVEL BAJO · PISO"], "#1b1c1e", None, 0.0)], density=200,
                    key="nivel_piso")
        # número de ubicación arriba
        b.quad([(xc - 0.25, yf - 0.04, 3.70), (xc + 0.25, yf - 0.04, 3.70), (xc + 0.25, yf - 0.04, 3.90), (xc - 0.25, yf - 0.04, 3.90)],
               "blanco", [("text", [f"RACK {chr(65 + j)}"], "#123a6b", None, 0.2)], density=200)
    return x0, width


def rack_slots(x0, n_bays=4):
    """Centros de las posiciones de pallet en la estantería: (x, y, z, nivel)."""
    post = 0.09
    out = []
    for j in range(n_bays):
        xc = x0 + post + j * (BAY + post) + BAY / 2
        for k in (-1, 1):
            for z, nv in zip((0.0,) + tuple(z + 0.012 for z in RACK_LEVELS[1:]), ("bajo", "medio", "alto")):
                out.append((xc + k * 0.62, RACK_Y, z, nv))
    return out


def build_pallet(b: Builder, c=(0, 0, 0), rot=0.0):
    """Pallet EUR 1200 × 800 × 144 mm con bloques: huecos de 78 mm de alto para las horquillas desde los lados de 800."""
    R = Matrix.Translation(Vector(c)) @ Matrix.Rotation(rot, 4, "Z")

    def bx(size, ctr, mat="madera", pats=(("wood", "v"),)):
        b.box(size, R @ Vector(ctr), rot=R.to_3x3(), mat=mat, patterns=pats, density=200, bevel=False)
    xs = (-0.35, 0.0, 0.35)
    ws = (0.10, 0.145, 0.10)
    for x, w in zip(xs, ws):
        bx((w, 1.20, 0.022), (x, 0, 0.011))                                   # tablas inferiores
        for y in (-0.5275, 0.0, 0.5275):
            bx((w, 0.145, 0.078), (x, y, 0.061), "madera_osc", (("wood", "u"),))   # tacos
    for y in (-0.5275, 0.0, 0.5275):
        bx((0.80, 0.145, 0.022), (0, y, 0.111), "madera", (("wood", "u"),))    # tablas transversales
    for x, w in zip((-0.3275, -0.165, 0.0, 0.165, 0.3275), (0.145, 0.10, 0.145, 0.10, 0.145)):
        bx((w, 1.20, 0.022), (x, 0, 0.133))                                   # tablas superiores
    # sello EPAL genérico grabado en el taco central delantero (texto)
    b.quad([R @ Vector((-0.06, -0.6006, 0.03)), R @ Vector((0.06, -0.6006, 0.03)), R @ Vector((0.06, -0.6006, 0.09)),
            R @ Vector((-0.06, -0.6006, 0.09))], "madera_osc", [("text", ["UY · EUR"], "#3b2a16", None, 0.4)], density=400, key="sello")


CARGOS = {
    "lacteos": ("Cajones de lácteos", 520),
    "combustible": ("Tambores de combustible", 760),
    "transformador": ("Transformador eléctrico", 900),
    "carne": ("Carne vacuna de exportación", 640),
}


def build_cargo(b: Builder, kind, c=(0, 0, 0), rot=0.0):
    """Carga apoyada sobre un pallet (c = centro de la cara superior del pallet)."""
    R = Matrix.Translation(Vector(c)) @ Matrix.Rotation(rot, 4, "Z")
    r3 = R.to_3x3()
    if kind == "lacteos":
        # cajones plásticos apilados (4 × 2 × 3) con etiqueta, envueltos en film
        for i in range(2):
            for j in range(3):
                for k in range(3):
                    ctr = Vector((-0.20 + i * 0.40, -0.40 + j * 0.40, 0.15 + k * 0.30))
                    b.box((0.38, 0.38, 0.28), R @ ctr, rot=r3, mat="caja_azul" if (i + j + k) % 2 == 0 else "caja_blanca", density=120,
                          face_patterns={"-y": [("vent", 3, 0.15, 0.85, 0.55, 0.85)], "+y": [("vent", 3, 0.15, 0.85, 0.55, 0.85)]})
        _label(b, R, (0, -0.605, 0.62), 0.70, 0.22, ["LÁCTEOS", "PRODUCTO URUGUAYO"], "#1d58a6", "#ffffff")
    elif kind == "combustible":
        for i, (x, y) in enumerate(((-0.2, -0.3), (0.2, -0.3), (-0.2, 0.3), (0.2, 0.3))):
            m = R @ Matrix.Translation((x, y, 0.0))
            prof = [(0.0, 0.0), (0.285, 0.0), (0.29, 0.02), (0.29, 0.28), (0.30, 0.29), (0.29, 0.30), (0.29, 0.58), (0.30, 0.59),
                    (0.29, 0.60), (0.29, 0.86), (0.285, 0.88), (0.0, 0.88)]
            b.lathe(prof, m, 16, "tambor_azul" if i % 2 else "tambor_rojo", [("band", "#f2f4f6", 0.36, 0.62)], density=150)
        _label(b, R, (-0.2, -0.592, 0.45), 0.24, 0.20, ["COMBUSTIBLE", "INFLAMABLE"], "#f2c200", "#1b1c1e")
        _label(b, R, (0.2, -0.592, 0.45), 0.24, 0.20, ["UN 1202", "CLASE 3"], "#f2c200", "#1b1c1e")
    elif kind == "transformador":
        # jaula de madera con el transformador adentro (aisladores arriba)
        b.box((0.78, 1.10, 0.95), R @ Vector((0, 0, 0.48)), rot=r3, mat="madera", patterns=[("wood", "u")], density=100,
              face_patterns={"-y": [("grid", 4, 4, 0.22)], "+y": [("grid", 4, 4, 0.22)], "+x": [("grid", 5, 4, 0.22)], "-x": [("grid", 5, 4, 0.22)]})
        for x in (-0.22, 0.0, 0.22):
            m = R @ Matrix.Translation((x, 0.25, 0.95))
            b.lathe([(0.05, 0.0), (0.05, 0.03), (0.07, 0.04), (0.04, 0.07), (0.07, 0.09), (0.04, 0.12), (0.06, 0.14), (0.0, 0.16)], m, 12,
                    "blanco", density=150)
        _label(b, R, (0, -0.555, 0.55), 0.55, 0.40, ["ALTA TENSIÓN", "TRANSFORMADOR", "MANIPULAR CON CUIDADO"], "#f2c200", "#1b1c1e")
    elif kind == "carne":
        for j in range(3):
            for k in range(4):
                b.box((0.76, 0.38, 0.22), R @ Vector((0, -0.40 + j * 0.40, 0.12 + k * 0.23)), rot=r3, mat="carton",
                      patterns=[("bevel",)], density=110)
        _label(b, R, (0, -0.595, 0.55), 0.70, 0.36, ["CARNE VACUNA", "EXPORTACIÓN · URUGUAY", "MANTENER A -18 °C"], "#ffffff", "#7a1414")
    # film strech (lámina semibrillante) sobre la carga de lácteos y carne
    return CARGOS[kind]


def _label(b, R, c, w, h, lines, bg, fg):
    c = Vector(c)
    pts = [c + Vector((-w / 2, 0, -h / 2)), c + Vector((w / 2, 0, -h / 2)), c + Vector((w / 2, 0, h / 2)), c + Vector((-w / 2, 0, h / 2))]
    b.quad([R @ p for p in pts], "blanco", [("text", lines, fg, bg, 0.3)], density=420)


def build_cone(b: Builder, c=(0, 0, 0)):
    m = Matrix.Translation(Vector(c))
    b.box((0.36, 0.36, 0.03), Vector(c) + Vector((0, 0, 0.015)), mat="negro", density=150, bevel=False)
    prof = [(0.15, 0.03), (0.13, 0.20), (0.115, 0.28), (0.10, 0.36), (0.07, 0.52), (0.03, 0.70), (0.0, 0.71)]
    b.lathe(prof, m, 16, "cono", [("band", "#f4f4f4", 0.30, 0.42), ("band", "#f4f4f4", 0.58, 0.68)], density=180)


def build_drop_zone(b: Builder, c, size=(1.8, 2.2), label="ZONA A"):
    """Zona de descarga: borde de franjas amarillas y negras y rótulo en el piso."""
    cx, cy = c
    w, d = size
    s = 0.15
    _floor_quad(b, (cx, cy - d / 2 + s / 2), w, s, "amarillo", [("hazard", None)], density=120, key=f"borde_{w}")
    _floor_quad(b, (cx, cy + d / 2 - s / 2), w, s, "amarillo", [("hazard", None)], density=120, key=f"borde_{w}")
    _floor_quad(b, (cx - w / 2 + s / 2, cy), d - 2 * s, s, "amarillo", [("hazard", None)], density=120, key=f"borde_{d - 2 * s:.2f}",
                rot=math.pi / 2)
    _floor_quad(b, (cx + w / 2 - s / 2, cy), d - 2 * s, s, "amarillo", [("hazard", None)], density=120, key=f"borde_{d - 2 * s:.2f}",
                rot=math.pi / 2)
    _floor_quad(b, (cx, cy - d / 2 - 0.35), w, 0.5, "negro", [("text", [label], "#f2c200", None, 0.0)], density=150)


def build_slalom_lane(b: Builder, x0, x1, y):
    """Líneas del carril de slalom y flechas pintadas."""
    for dy in (-1.6, 1.6):
        _floor_quad(b, ((x0 + x1) / 2, y + dy), x1 - x0, 0.10, "amarillo", [], density=20, key="linea_slalom")
    _floor_quad(b, (x0 - 1.0, y), 1.6, 1.4, "negro", [("text", ["SLALOM", "INICIO →"], "#ffffff", None, 0.0)], density=150)

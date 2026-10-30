"""
Autoelevador eléctrico contrapesado (2,5 t) para conducción en VR.

Marco: metros, Z arriba, el frente mira hacia -Y (convención de Blender), la derecha del conductor es -X.
Origen (0,0,0) = suelo, a mitad del eje delantero. Cada pieza móvil tiene su origen en su centro mecánico.
"""
import math

from mathutils import Euler, Matrix, Vector

from kit3d import Builder, axis_m, hexc, srgb_to_lin

# ---------------------------------------------------------------------------------------------------------------------
# Materiales del atlas del autoelevador (color sRGB → lineal, rugosidad, metalicidad)
# ---------------------------------------------------------------------------------------------------------------------
def M(h, rough, metal, noise=0.03, grain=0.0, rough_var=0.03):
    return dict(color=srgb_to_lin(hexc(h)), rough=rough, metal=metal, noise=noise, grain=grain, rough_var=rough_var)


MATS_FK = {
    "celeste": M("#4f9fdc", 0.36, 0.1, grain=0.15),
    "blanco": M("#eceff2", 0.38, 0.05, grain=0.15),
    "grafito": M("#2b2f35", 0.5, 0.25, grain=0.2),
    "negro": M("#1c1e21", 0.55, 0.1),
    "acero": M("#8f959c", 0.38, 0.9, noise=0.05, rough_var=0.06),
    "cromo": M("#cfd3d7", 0.14, 1.0, noise=0.02),
    "goma": M("#161616", 0.88, 0.0, noise=0.05),
    "llanta": M("#d8dce1", 0.4, 0.6),
    "vinilo": M("#1d1f22", 0.62, 0.0, grain=0.4),
    "plastico": M("#24272b", 0.52, 0.0),
    "rojo": M("#c8102e", 0.32, 0.05),
    "amarillo": M("#f2c200", 0.4, 0.05),
    "ambar": M("#ff9e1b", 0.2, 0.0),
    "lente": M("#f4f7ff", 0.08, 0.0, noise=0.0),
    "calabaza": M("#6e4a2a", 0.7, 0.0, noise=0.08, grain=0.6),
    "yerba": M("#5d7a2c", 0.9, 0.0, noise=0.1, grain=0.8),
    "termo": M("#9aa1a8", 0.25, 0.95),
    "placa": M("#c9ccd0", 0.3, 0.85),
    "pantalla": M("#05080b", 0.15, 0.0, noise=0.0),
}

# ---------------------------------------------------------------------------------------------------------------------
# Medidas
# ---------------------------------------------------------------------------------------------------------------------
FRONT_R, FRONT_W, FRONT_X = 0.28, 0.18, 0.50
REAR_R, REAR_W, REAR_X, REAR_Y = 0.23, 0.15, 0.42, 1.45
MAST_Y = -0.40           # plano del mástil
TILT_PIVOT = Vector((0, -0.33, 0.30))
OUTER_H = 2.15
INNER_H = 2.00
LIFT_INNER_MAX = 1.85    # carrera del mástil interior
LIFT_CARRIAGE_MAX = 1.55 # carrera libre del carro dentro del interior
SIDESHIFT_MAX = 0.10
FORK_MIN_X, FORK_MAX_X = 0.15, 0.46
FORK_X = 0.19
CARRIAGE_Y = MAST_Y - 0.13
FORK_LEN = 1.15
SEAT = Vector((0.0, 0.95, 1.08))
WHEEL_HUB = Vector((0.05, 0.30, 1.28))   # centro del volante
COLUMN_DIR = Vector((0, 0.42, 1.0)).normalized()   # eje de la columna (hacia el conductor y arriba)
ESTOP = Vector((-0.40, 0.02, 1.235))      # cabeza del hongo de parada (sobre el tablero, a la derecha)
KEY = Vector((-0.28, 0.095, 1.06))         # boca de la llave (cara trasera del tablero)
DENS = 300
DENS_DECAL = 900


def rot_x(deg):
    return Euler((math.radians(deg), 0, 0)).to_matrix()


def tire(b: Builder, center, r, width, seg=48):
    """Cubierta industrial con dibujo (en el normal map) y llanta de chapa."""
    m = axis_m("X", center)
    w = width / 2
    prof = [(r * 0.62, -w), (r * 0.86, -w), (r * 0.96, -w * 0.82), (r, -w * 0.5), (r, w * 0.5), (r * 0.96, w * 0.82),
            (r * 0.86, w), (r * 0.62, w)]
    # banda de rodadura entre los puntos 3 y 4 del perfil → v relativo
    lens = [0.0]
    for (r0, z0), (r1, z1) in zip(prof, prof[1:]):
        lens.append(lens[-1] + math.hypot(r1 - r0, z1 - z0))
    L = lens[-1]
    b.lathe(prof, m, seg, "goma", [("tread", lens[2] / L, lens[5] / L, 30), ("sidewall", 0.0, lens[2] / L)])
    # llanta: disco rebajado con buje y tuercas
    rim = [(r * 0.62, w * 0.98), (r * 0.55, w * 0.7), (r * 0.30, w * 0.55), (r * 0.18, w * 0.75), (r * 0.12, w * 0.75)]
    b.lathe(rim, m, seg, "llanta", [("screws", 0.3, None, 3, 2)], cap_end=("llanta", [("screws", 0.25, None, 3, 3)]))
    rim2 = [(r * 0.12, -w * 0.75), (r * 0.18, -w * 0.75), (r * 0.30, -w * 0.55), (r * 0.55, -w * 0.7), (r * 0.62, -w * 0.98)]
    b.lathe(rim2, m, seg, "llanta", cap_start=("llanta", []))
    # tuercas de rueda (hexagonales) en ambas caras
    for side in (1, -1):
        for k in range(6):
            a = 2 * math.pi * k / 6
            p = m @ Vector((r * 0.22 * math.cos(a), r * 0.22 * math.sin(a), side * w * 0.78))
            b.cyl(0.011, 0.018, axis_m(Vector(m.to_3x3() @ Vector((0, 0, side))), p), 6, "cromo")


# ---------------------------------------------------------------------------------------------------------------------
# Piezas (cada función llena un Builder en coordenadas del mundo)
# ---------------------------------------------------------------------------------------------------------------------
def build_chassis(b: Builder, mirror_slots):
    # --- carrocería: tramo delantero entre ruedas, tramo medio completo, tramo trasero con pasaruedas
    b.box((0.76, 0.56, 0.54), (0, 0.08, 0.41), mat="celeste", skip=("-z",))
    b.box((1.10, 0.84, 0.54), (0, 0.78, 0.41), mat="celeste", skip=("-z",),
          face_patterns={"+x": [("vent", 6, 0.70, 0.95, 0.2, 0.62)], "-x": [("vent", 6, 0.05, 0.30, 0.2, 0.62)]})
    b.box((1.10, 0.55, 0.20), (0, 1.475, 0.58), mat="celeste")
    b.box((0.62, 0.55, 0.34), (0, 1.475, 0.31), mat="negro", skip=("-z",))
    b.box((1.12, 0.84, 0.10), (0, 0.78, 0.15), mat="negro", skip=("-z",))
    # guardabarros sobre las ruedas delanteras y traseras
    for sx in (1, -1):
        b.lathe([(FRONT_R + 0.05, -FRONT_W / 2 - 0.02), (FRONT_R + 0.05, FRONT_W / 2 + 0.02)], axis_m("X", (sx * FRONT_X, 0, FRONT_R)), 20,
                "negro", arc=(math.pi / 2 + 0.25, 3 * math.pi / 2 - 0.05))
    # escalones de acceso con chapa antideslizante
    for sx in (1, -1):
        b.box((0.16, 0.30, 0.04), (sx * 0.62, 0.48, 0.30), mat="acero", face_patterns={"+z": [("checker", 0.03)]})
        b.box((0.03, 0.04, 0.16), (sx * 0.62, 0.36, 0.38), mat="negro")
    # piso del operador
    b.box((0.86, 0.62, 0.03), (0, 0.18, 0.67), mat="acero", face_patterns={"+z": [("checker", 0.03)]}, skip=("-z",))
    # frente (pared hasta el piso) y cubierta del tablero; debajo queda el hueco de los pies con los pedales
    b.box((1.02, 0.06, 0.56), (0, -0.21, 0.94), mat="celeste", face_patterns={"-y": [("vent", 5, 0.2, 0.8, 0.2, 0.55)]})
    b.box((1.02, 0.30, 0.20), (0, -0.06, 1.10), mat="celeste")
    b.box((1.02, 0.30, 0.02), (0, -0.06, 1.21), mat="negro", face_patterns={"+z": [("screws", 0.05, None, 2, 2)]})
    # capó de la batería (bajo el asiento) y guardabarros
    b.box((1.04, 0.86, 0.40), (0, 0.98, 0.88), mat="blanco", face_patterns={"+x": [("screws", 0.06, None, 2, 2)], "-x": [("screws", 0.06, None, 2, 2)]})
    # --- contrapeso redondeado (prisma de un rectángulo con extremos curvos)
    # contrapeso: planta rectangular con esquinas traseras redondeadas (la cara trasera queda plana para los rótulos)
    pts = [(x, y + 1.66) for x, y in rounded_rect(1.12, 0.72, 0.17, 8)]
    b.extrude_profile(pts, 0.62, Matrix.Translation((0, 0, 0.79)), mat="grafito", patterns=[("noise",)])
    b.box((0.60, 0.70, 0.34), (0, 1.64, 0.31), mat="grafito", skip=("-z",))
    # ojales de izaje del contrapeso y luz azul de advertencia (proyecta un punto en el piso)
    for sx in (1, -1):
        b.torus(0.04, 0.012, axis_m("X", (sx * 0.30, 1.75, 1.13)), 24, 8, "acero")
    b.lathe([(0.0, 0.0), (0.04, 0.0), (0.045, 0.05), (0.04, 0.06)], axis_m(Vector((0, 1, -0.6)), (0.0, 2.02, 1.02)), 16, "grafito",
            cap_end=("celeste", []))
    # perno de remolque y luces traseras
    b.cyl(0.03, 0.18, axis_m("Z", (0, 2.06, 0.50)), 12, "acero")
    for sx in (1, -1):
        b.box((0.10, 0.03, 0.07), (sx * 0.30, 2.03, 0.98), rot=None, mat="rojo", face_patterns={"+y": [("grid", 4, 2, 0.15)]})
        b.box((0.06, 0.03, 0.07), (sx * 0.19, 2.03, 0.98), mat="lente")
    # franja de peligro trasera y textos del contrapeso
    b.quad([(0.38, 2.022, 0.52), (-0.38, 2.022, 0.52), (-0.38, 2.022, 0.62), (0.38, 2.022, 0.62)], "amarillo",
           [("hazard", 10)], density=DENS_DECAL)
    b.quad([(0.38, 2.022, 0.67), (-0.38, 2.022, 0.67), (-0.38, 2.022, 0.89), (0.38, 2.022, 0.89)], "grafito",
           [("text", ["PUERTO DE MONTEVIDEO", "URUGUAY LOGÍSTICA"], "#f2f4f6", None)], density=DENS_DECAL)
    for sx in (1, -1):
        y0, y1 = (0.60, 1.12) if sx > 0 else (1.12, 0.60)
        b.quad([(sx * 0.522, y0, 0.95), (sx * 0.522, y1, 0.95), (sx * 0.522, y1, 1.05), (sx * 0.522, y0, 1.05)], "blanco",
               [("text", ["ORIENTAL E25"], "#2f7fc4", None, 0.4)], density=DENS_DECAL)
        y0, y1 = (0.40, 1.25) if sx > 0 else (1.25, 0.40)
        b.quad([(sx * 0.552, y0, 0.48), (sx * 0.552, y1, 0.48), (sx * 0.552, y1, 0.63), (sx * 0.552, y0, 0.63)], "celeste",
               [("text", ["URUGUAY LOGÍSTICA"], "#ffffff", None, 0.5)], density=DENS_DECAL)
        # bandera en el lateral del capó
        fy0, fy1 = (1.18, 1.33) if sx > 0 else (1.33, 1.18)
        b.quad([(sx * 0.522, fy0, 0.92), (sx * 0.522, fy1, 0.92), (sx * 0.522, fy1, 1.02), (sx * 0.522, fy0, 1.02)], "blanco",
               [("flag_uy",)], density=DENS_DECAL, key=None)
    # --- asiento (almohadón y respaldo con perfil redondeado)
    yz = Matrix(((0, 0, 1, 0), (1, 0, 0, 0), (0, 1, 0, 0), (0, 0, 0, 1)))   # X local → Y, Y local → Z, Z local → X
    b.extrude_profile(rounded_rect(0.46, 0.11, 0.035), 0.48, Matrix.Translation((SEAT.x, SEAT.y, SEAT.z)) @ yz, mat="vinilo",
                      patterns=[("grid", 3, 4, 0.05)])
    back = Matrix.Translation((SEAT.x, SEAT.y + 0.25, SEAT.z + 0.33)) @ rot_x(-12).to_4x4() @ yz
    b.extrude_profile(rounded_rect(0.11, 0.56, 0.04), 0.46, back, mat="vinilo", patterns=[("grid", 3, 5, 0.05)])
    b.extrude_profile(rounded_rect(0.08, 0.13, 0.03), 0.30, Matrix.Translation((SEAT.x, SEAT.y + 0.33, SEAT.z + 0.68)) @
                      rot_x(-12).to_4x4() @ yz, mat="vinilo")
    # suspensión del asiento: fuelle de goma (revolución con pliegues)
    prof = [(0.17 + (0.02 if k % 2 else 0.0), -0.13 + k * 0.016) for k in range(8)]
    b.lathe(prof, axis_m("Z", (SEAT.x, SEAT.y, SEAT.z - 0.06)) @ Matrix.Diagonal((1.0, 1.05, 1.0, 1.0)), 24, "goma")
    # cinturón de seguridad (cinta que cae del respaldo)
    b.tube([(SEAT.x + 0.22, SEAT.y + 0.22, SEAT.z + 0.10), (SEAT.x + 0.24, SEAT.y + 0.05, SEAT.z + 0.05),
            (SEAT.x + 0.20, SEAT.y - 0.12, SEAT.z + 0.04)], 0.012, 6, 5, "ambar")
    # laterales del asiento (apoyo de cadera)
    for sx in (1, -1):
        b.extrude_profile(rounded_rect(0.40, 0.08, 0.03), 0.04, Matrix.Translation((SEAT.x + sx * 0.25, SEAT.y, SEAT.z + 0.07)) @ yz, mat="vinilo")
    # cinturón (franja naranja sobre el asiento)
    b.quad([(0.22, SEAT.y + 0.185, SEAT.z + 0.10), (-0.22, SEAT.y + 0.185, SEAT.z + 0.10), (-0.22, SEAT.y + 0.185, SEAT.z + 0.16),
            (0.22, SEAT.y + 0.185, SEAT.z + 0.16)], "ambar", [("text", ["CINTURÓN"], "#1c1e21", None, 0.2)], density=DENS_DECAL)
    # --- consola del apoyabrazos (derecha del conductor = -X)
    b.box((0.14, 0.42, 0.14), (-0.33, 0.78, 1.14), mat="plastico", face_patterns={"+x": [("text", ["ELEVAR · INCLINAR · DESPLAZAR"], "#9fb3c8", None, 0.2)]})
    b.box((0.12, 0.26, 0.05), (-0.33, 0.88, 1.235), mat="vinilo")          # apoyabrazos acolchado
    # --- tablero: pantalla, placa "Hecho en Uruguay", bandera, parada de emergencia, llave
    dash_top = 1.21
    # pantalla (material propio M_Dash_Screen, UV 0..1)
    s = mirror_slots["M_Dash_Screen"]
    # pantalla inclinada 30° hacia el conductor sobre una base trapezoidal
    b.extrude_profile([(0.0, 0.0), (0.12, 0.0), (0.0, 0.07)], 0.26, Matrix.Translation((-0.06, -0.04, dash_top + 0.01)) @
                      Matrix(((0, 0, 1, 0), (1, 0, 0, 0), (0, 1, 0, 0), (0, 0, 0, 1))), mat="negro")
    b.plain_quad([(0.06, 0.07, dash_top + 0.016), (-0.18, 0.07, dash_top + 0.016), (-0.18, -0.025, dash_top + 0.071),
                  (0.06, -0.025, dash_top + 0.071)], s)
    b.quad([(0.40, 0.165, dash_top + 0.001), (0.22, 0.165, dash_top + 0.001), (0.22, 0.05, dash_top + 0.001), (0.40, 0.05, dash_top + 0.001)],
           "placa", [("text", ["HECHO EN", "URUGUAY"], "#1d2733", None, 0.6, 0.35, "center", "#1d2733")], density=DENS_DECAL)
    b.quad([(0.47, 0.06, dash_top + 0.001), (0.41, 0.06, dash_top + 0.001), (0.41, 0.10, dash_top + 0.001), (0.47, 0.10, dash_top + 0.001)],
           "blanco", [("flag_uy",)], density=DENS_DECAL)
    # base de la parada de emergencia y de la llave (las piezas móviles van aparte)
    b.cyl(0.035, 0.03, axis_m("Z", ESTOP + Vector((0, 0, -0.013))), 16, "amarillo")
    b.cyl(0.022, 0.02, axis_m("Y", KEY + Vector((0, -0.008, 0))), 16, "cromo")
    # portamate y termo (accesorio del tablero, a la izquierda)
    b.lathe([(0.048, 0.0), (0.048, 0.11), (0.052, 0.115)], axis_m("Z", (0.42, 0.02, 1.10)), 16, "negro", cap_start=("negro", []))
    b.lathe([(0.042, 0.0), (0.045, 0.05), (0.038, 0.10), (0.025, 0.125)], axis_m("Z", (0.42, 0.02, 1.115)), 16, "calabaza",
            cap_start=("calabaza", []), cap_end=("yerba", []))
    b.cyl(0.004, 0.11, axis_m(Vector((0.15, 0.1, 1)), (0.425, 0.025, 1.27)), 6, "cromo")     # bombilla
    b.lathe([(0.040, 0.0), (0.040, 0.24)], axis_m("Z", (0.32, -0.05, 1.10)), 16, "termo", cap_start=("termo", []))
    b.lathe([(0.040, 0.24), (0.036, 0.27), (0.020, 0.29), (0.020, 0.31)], axis_m("Z", (0.32, -0.05, 1.10)), 16, "negro",
            cap_end=("negro", []))
    b.lathe([(0.044, 0.0), (0.044, 0.12), (0.047, 0.125)], axis_m("Z", (0.32, -0.05, 1.09)), 16, "negro", cap_start=("negro", []))
    # botonera del tablero (luces, bocina, baliza, freno de mano) a la derecha del volante
    for k in range(4):
        b.lathe([(0.0, 0.0), (0.014, 0.0), (0.014, 0.008), (0.010, 0.012), (0.0, 0.012)],
                axis_m("Z", (-0.30 + (k % 2) * 0.045, 0.00 + (k // 2) * 0.05, dash_top + 0.01)), 16, ["negro", "ambar", "celeste", "plastico"][k])
    # columna de dirección
    col_base = Vector((WHEEL_HUB.x, 0.08, 1.05))
    L = (WHEEL_HUB - col_base).length
    b.lathe([(0.075, 0.0), (0.07, 0.05), (0.05, 0.12), (0.045, 0.16), (0.045, L - 0.07), (0.05, L - 0.05)],
            axis_m(COLUMN_DIR, col_base), 24, "negro", cap_end=("negro", []))
    # --- techo protector (FOPS): 4 parantes, marco y travesaños
    posts = [(0.50, -0.12), (-0.50, -0.12), (0.50, 1.50), (-0.50, 1.50)]
    for x, y in posts:
        z0 = 0.70 if y < 0 else 1.08
        top = Vector((x * 0.98, y + (0.06 if y < 0 else 0), 2.12))
        base = Vector((x, y, z0))
        # tubo rectangular con esquinas redondeadas y cartela en la base
        b.extrude_profile(rounded_rect(0.07, 0.07, 0.015, 3), (top - base).length, axis_m(top - base, (base + top) / 2), mat="grafito")
        b.box((0.12, 0.12, 0.012), base + Vector((0, 0, 0.006)), mat="grafito", face_patterns={"+z": [("screws", 0.15, None, 2, 2)]})
    for x in (0.50, -0.50):
        b.box((0.07, 1.80, 0.07), (x, 0.70, 2.15), mat="grafito")
    for y in (-0.18, 1.58):
        b.box((1.07, 0.07, 0.07), (0, y, 2.15), mat="grafito")
    for k in range(9):
        b.box((0.93, 0.05, 0.035), (0, -0.02 + k * 0.18, 2.16), mat="grafito")
    # agarraderas en los parantes delanteros
    for sx in (1, -1):
        b.tube([(sx * 0.50, -0.06, 1.15), (sx * 0.53, 0.02, 1.25), (sx * 0.53, 0.02, 1.55), (sx * 0.50, -0.06, 1.65)], 0.016, 10, 5,
               "amarillo", [("ribs", 20, "v")])
    # agarradera trasera
    b.lathe([(0.018, -0.25), (0.018, 0.25)], axis_m("X", (0, 1.52, 1.30)), 12, "amarillo", [("ribs", 12, "v")])
    # luces de trabajo y baliza
    for x in (0.50, -0.50):
        b.lathe([(0.05, 0), (0.06, 0.06), (0.06, 0.07)], axis_m("Y", (x, -0.10, 2.02)) @ Matrix.Rotation(math.pi, 4, "X"), 16, "negro",
                cap_end=("lente", []))
    b.lathe([(0.06, 0), (0.06, 0.03), (0.045, 0.11), (0.0, 0.12)], axis_m("Z", (0.40, 1.40, 2.18)), 24, "ambar", cap_start=("negro", []))
    # faro de trabajo trasero
    b.lathe([(0.04, 0), (0.05, 0.05), (0.05, 0.06)], axis_m("Y", (-0.40, 1.60, 2.10)), 20, "negro", cap_end=("lente", []))
    # carteles de seguridad en el techo (frente)
    b.quad([(0.30, -0.155, 2.08), (-0.30, -0.155, 2.08), (-0.30, -0.155, 2.17), (0.30, -0.155, 2.17)], "amarillo",
           [("text", ["CAPACIDAD 2500 kg · USAR CINTURÓN"], "#1c1e21", None, 0.4)], density=DENS_DECAL)
    # brazos y carcasas de los espejos (los vidrios son objetos aparte)
    for x in (0.53, -0.53):
        sx = 1 if x > 0 else -1
        b.tube([(x, -0.08, 1.74), (x + sx * 0.05, -0.085, 1.80), (x + sx * 0.10, -0.08, 1.80)], 0.011, 8, 4, "negro")
        # carcasa del espejo: cuenco (revolución) abierto hacia el conductor
        b.lathe([(0.0, -0.035), (0.06, -0.03), (0.085, -0.015), (0.09, 0.02)], axis_m(Vector((-sx * 0.25, 1, 0)), (x + sx * 0.18, -0.08, 1.80)) @
                Matrix.Diagonal((1.0, 0.68, 1.0, 1.0)), 20, "negro")
    b.box((0.36, 0.06, 0.14), (0, -0.04, 2.05), mat="negro", skip=("+y",))        # carcasa del espejo central (convexo)
    # cilindros de inclinación (del chasis al mástil, decorativos)
    for x in (0.42, -0.42):
        b.cyl(0.04, 0.16, axis_m(Vector((0, -1, 0.35)), (x, -0.30, 0.86)), 16, "grafito")
        b.cyl(0.022, 0.12, axis_m(Vector((0, -1, 0.35)), (x, -0.40, 0.90)), 12, "cromo")
    # bocina y conector de batería
    b.lathe([(0.0, 0.0), (0.03, 0.0), (0.035, 0.02), (0.04, 0.03), (0.0, 0.03)], axis_m("Y", (0.25, -0.245, 0.80)) @
            Matrix.Rotation(math.pi, 4, "X"), 16, "negro")
    b.box((0.08, 0.06, 0.10), (-0.54, 1.05, 0.80), mat="rojo", face_patterns={"-x": [("grid", 2, 2, 0.2)]})
    b.tube([(-0.54, 1.05, 0.74), (-0.56, 1.10, 0.66), (-0.555, 1.20, 0.60)], 0.012, 8, 4, "goma")


def rounded_rect(w, h, r, seg=6):
    """Rectángulo redondeado (antihorario) centrado en el origen."""
    pts = []
    for cx, cy, a0 in ((w / 2 - r, -h / 2 + r, -math.pi / 2), (w / 2 - r, h / 2 - r, 0), (-w / 2 + r, h / 2 - r, math.pi / 2),
                       (-w / 2 + r, -h / 2 + r, math.pi)):
        for i in range(seg + 1):
            a = a0 + (math.pi / 2) * i / seg
            pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    return pts


def _move_last(b, n_faces, M):
    """Transforma las últimas `n_faces` caras agregadas (para rotar una caja ya creada)."""
    faces = [f for f, _ in b.pending[-n_faces:]]
    verts = {v for f in faces for v in f.verts}
    c = sum((v.co for v in verts), Vector()) / len(verts)
    for v in verts:
        v.co = M @ (v.co - c)


def build_mast_outer(b: Builder):
    for x in (0.40, -0.40):
        sx = 1 if x > 0 else -1
        # perfil en C: alma + dos alas
        b.box((0.03, 0.14, OUTER_H), (x, MAST_Y, 0.12 + OUTER_H / 2), mat="grafito")
        b.box((0.07, 0.03, OUTER_H), (x - sx * 0.035, MAST_Y - 0.055, 0.12 + OUTER_H / 2), mat="grafito")
        b.box((0.07, 0.03, OUTER_H), (x - sx * 0.035, MAST_Y + 0.055, 0.12 + OUTER_H / 2), mat="grafito")
        # cilindro de elevación detrás del canal
        b.cyl(0.045, 1.70, axis_m("Z", (x * 0.72, MAST_Y + 0.13, 0.25 + 0.85)), 24, "acero")
        b.lathe([(0.052, 0.0), (0.052, 0.06), (0.046, 0.07)], axis_m("Z", (x * 0.72, MAST_Y + 0.13, 1.95)), 24, "grafito")
        b.cyl(0.05, 0.08, axis_m("Z", (x * 0.72, MAST_Y + 0.13, 0.20)), 16, "grafito")
    for z in (0.20, 1.20, 2.22):
        b.box((0.86, 0.10, 0.08), (0, MAST_Y + 0.04, z), mat="grafito",
              face_patterns={"-y": [("hazard", 9)]} if z > 2 else None)
    # mangueras de los cilindros de inclinación y del desplazador lateral
    for sx in (1, -1):
        b.tube([(sx * 0.42, TILT_PIVOT.y + 0.02, 0.62), (sx * 0.36, MAST_Y + 0.10, 0.50), (sx * 0.30, MAST_Y + 0.14, 0.32)], 0.011, 8, 6, "goma")
    # mangueras hidráulicas que suben por el mástil hasta la polea
    for sx in (1, -1):
        b.tube([(sx * 0.18, TILT_PIVOT.y - 0.02, 0.40), (sx * 0.20, MAST_Y + 0.12, 0.70), (sx * 0.22, MAST_Y + 0.12, 1.50),
                (sx * 0.22, MAST_Y + 0.10, 2.10), (sx * 0.20, MAST_Y + 0.02, 2.24)], 0.014, 12, 8, "goma")
    for x in (0.22, -0.22):
        b.cyl(0.05, 0.05, axis_m("X", (x, MAST_Y + 0.02, 2.26)), 16, "acero")
    # rodillos/soportes de la bisagra de inclinación
    for x in (0.40, -0.40):
        b.cyl(0.05, 0.08, axis_m("X", (x, TILT_PIVOT.y, TILT_PIVOT.z)), 16, "acero")


def build_mast_inner(b: Builder):
    for x in (0.30, -0.30):
        sx = 1 if x > 0 else -1
        b.box((0.025, 0.10, INNER_H), (x, MAST_Y - 0.02, 0.16 + INNER_H / 2), mat="acero")
        b.box((0.06, 0.025, INNER_H), (x + sx * 0.03, MAST_Y - 0.06, 0.16 + INNER_H / 2), mat="acero")
        b.box((0.06, 0.025, INNER_H), (x + sx * 0.03, MAST_Y + 0.02, 0.16 + INNER_H / 2), mat="acero")
        # rodillos guía del interior dentro del exterior
        for z in (0.30, 0.16 + INNER_H - 0.15):
            b.lathe([(0.0, -0.02), (0.045, -0.02), (0.05, 0.0), (0.045, 0.02), (0.0, 0.02)], axis_m("X", (x + sx * 0.07, MAST_Y - 0.02, z)), 16, "acero")
        # polea de cadena arriba
        b.cyl(0.06, 0.05, axis_m("X", (x * 0.85, MAST_Y - 0.02, 0.16 + INNER_H)), 16, "grafito")
        # cadena (franja con eslabones en el normal map)
        b.box((0.03, 0.012, INNER_H * 0.9), (x * 0.85, MAST_Y - 0.085, 0.16 + INNER_H * 0.52), mat="negro",
              face_patterns={"-y": [("ribs", 60, "v")], "+y": [("ribs", 60, "v")]})
    for z in (0.20, 0.16 + INNER_H - 0.06):
        b.box((0.66, 0.08, 0.07), (0, MAST_Y - 0.02, z), mat="acero")


def build_carriage(b: Builder):
    y = CARRIAGE_Y
    # dos barras portahorquillas (ISO 2328)
    b.box((1.04, 0.06, 0.12), (0, y, 0.28), mat="grafito", face_patterns={"-y": [("hazard", 14)]})
    b.box((1.04, 0.06, 0.10), (0, y, 0.62), mat="grafito")
    b.box((0.06, 0.06, 0.46), (0.48, y, 0.45), mat="grafito")
    b.box((0.06, 0.06, 0.46), (-0.48, y, 0.45), mat="grafito")
    # respaldo de carga (rejilla)
    # respaldo de carga: marco y barrotes (se ve a través, como en un autoelevador real)
    b.box((1.04, 0.04, 0.05), (0, y + 0.01, 1.20), mat="grafito")
    b.box((1.04, 0.04, 0.04), (0, y + 0.01, 0.92), mat="grafito")
    for k in range(9):
        x = -0.50 + k * 0.125
        b.box((0.035 if k in (0, 8) else 0.022, 0.03, 0.55), (x, y + 0.01, 0.95), mat="grafito")
    # placa del desplazador lateral
    b.box((0.70, 0.04, 0.30), (0, y + 0.05, 0.45), mat="negro", face_patterns={"+y": [("screws", 0.08, None, 4, 2)]})
    # rodillos de carga del carro (giran dentro de los canales del mástil interior)
    for x in (0.27, -0.27):
        for z in (0.30, 0.65):
            b.lathe([(0.0, -0.016), (0.04, -0.016), (0.045, -0.01), (0.045, 0.01), (0.04, 0.016), (0.0, 0.016)],
                    axis_m("X", (x, y + 0.08, z)), 16, "acero")
    # cilindro y mangueras del desplazador lateral
    b.cyl(0.03, 0.40, axis_m("X", (0, y + 0.09, 0.45)), 16, "acero")
    for sx in (1, -1):
        b.tube([(sx * 0.18, y + 0.09, 0.47), (sx * 0.12, y + 0.14, 0.62), (sx * 0.08, y + 0.18, 0.80)], 0.009, 8, 6, "goma")


def build_fork(b: Builder, x):
    y = CARRIAGE_Y - 0.04
    # caña vertical con gancho, talón curvo y pala con punta afinada
    b.box((0.10, 0.045, 0.50), (x, y - 0.025, 0.36), mat="acero", face_patterns={"-y": [("text", ["2500 kg"], "#1c1e21", None, 0.3)]})
    b.box((0.10, 0.06, 0.05), (x, y + 0.015, 0.62), mat="acero")    # gancho superior
    # talón: cuarto de toro aproximado con 3 cajas en abanico
    for k in range(3):
        a = (k + 0.5) / 3 * 90
        c = Vector((x, y - 0.05 - 0.05 * math.sin(math.radians(a)), 0.11 - 0.05 * (1 - math.cos(math.radians(a)))))
        b.box((0.10, 0.045, 0.045), c, rot=rot_x(a), mat="acero", bevel=False)
    # pala (sección 100 × 40 mm, punta en cuña)
    L = FORK_LEN
    pts = [(0.0, 0.0), (L - 0.12, 0.0), (L, 0.012), (L, 0.028), (L - 0.12, 0.04), (0.0, 0.04)]
    # prisma: perfil en (largo, alto) extruido en el ancho
    b.extrude_profile([(px, pz) for px, pz in pts], 0.10, Matrix.Translation((x, y - 0.07, 0.015)) @ _blade_frame(), mat="acero",
                      patterns=[("noise",)])


def _blade_frame():
    """Ejes del perfil de la pala: X local → -Y del mundo (hacia adelante), Y local → +Z, Z local → X (ancho)."""
    return Matrix(((0, 0, -1, 0), (-1, 0, 0, 0), (0, 1, 0, 0), (0, 0, 0, 1)))


def build_steering_wheel(b: Builder, knob: Builder):
    m = axis_m(COLUMN_DIR, WHEEL_HUB)
    b.torus(0.165, 0.018, m, 48, 10, "goma", [("ribs", 48, "u")])
    for k in range(3):
        a = math.pi / 2 + 2 * math.pi * k / 3
        p = m @ Vector((0.085 * math.cos(a), 0.085 * math.sin(a), -0.01))
        d = (m.to_3x3() @ Vector((math.cos(a), math.sin(a), 0))).normalized()
        b.cyl(0.011, 0.16, axis_m(d, p), 8, "negro", caps=False)
    b.lathe([(0.05, -0.03), (0.055, 0.0), (0.045, 0.025), (0.0, 0.03)], m, 16, "negro", cap_start=("negro", []))
    # perilla giratoria (spinner): objeto aparte para que gire sobre su propio eje
    kp = m @ Vector((0.165 * math.cos(-math.pi / 4), 0.165 * math.sin(-math.pi / 4), 0.0))
    km = axis_m(COLUMN_DIR, kp)
    knob.lathe([(0.0, 0.0), (0.012, 0.0), (0.012, 0.02), (0.022, 0.03), (0.024, 0.075), (0.016, 0.09), (0.0, 0.095)], km, 16, "plastico",
               [("ribs", 10, "u")])
    return kp


def build_lever(b: Builder, base: Vector, color):
    """Palanca de dedo de la consola: vástago y pomo. Pivote en la base (eje X)."""
    b.cyl(0.006, 0.11, axis_m("Z", base + Vector((0, 0, 0.055))), 8, "cromo")
    b.lathe([(0.0, 0.0), (0.016, 0.004), (0.018, 0.02), (0.012, 0.035), (0.0, 0.04)], axis_m("Z", base + Vector((0, 0, 0.105))), 12, color)
    b.cyl(0.016, 0.012, axis_m("Z", base + Vector((0, 0, 0.004))), 12, "goma")   # fuelle


def build_pedal(b: Builder, hinge: Vector, width, color="negro"):
    """Pedal articulado en la base: placa que sube 35° desde el piso hacia el conductor."""
    length = 0.24
    m = Matrix.Translation(hinge) @ rot_x(-55).to_4x4()
    plate_c = m @ Vector((0, 0, length / 2))
    b.box((width, 0.02, length), plate_c, rot=rot_x(-55), mat=color, face_patterns={"+y": [("ribs", 9, "v")], "-y": [("ribs", 9, "v")]})
    b.cyl(0.015, width * 0.6, axis_m("X", hinge), 8, "acero")


def build_shuttle(b: Builder, base: Vector):
    b.cyl(0.006, 0.09, axis_m(Vector((1, 0, 0.3)), base + Vector((0.045, 0, 0.013))), 8, "negro")
    b.lathe([(0.0, 0.0), (0.012, 0.005), (0.012, 0.03), (0.0, 0.035)], axis_m(Vector((1, 0, 0.3)), base + Vector((0.085, 0, 0.026))),
            10, "plastico", [("text", ["F N R"], "#ffffff", None, 0.2)])


def build_estop(b: Builder, base: Vector):
    b.lathe([(0.0, 0.0), (0.012, 0.0), (0.012, 0.02), (0.032, 0.025), (0.034, 0.04), (0.026, 0.05), (0.0, 0.052)],
            axis_m("Z", base), 16, "rojo")


def build_key(b: Builder, base: Vector):
    # llave saliendo del tablero hacia el conductor (+Y); gira sobre su propio eje
    b.cyl(0.004, 0.03, axis_m("Y", base + Vector((0, 0.015, 0))), 6, "cromo")
    b.box((0.03, 0.006, 0.026), base + Vector((0, 0.04, 0)), mat="plastico", face_patterns={"+y": [("text", ["UY"], "#5ea9e6", None, 0.2)]})


def build_mirror_glass(b: Builder, slot, center: Vector, w, h, facing: Vector):
    """Vidrio del espejo: quad con su propio material (UV 0..1) para un render-to-texture."""
    f = facing.normalized()
    up = Vector((0, 0, 1))
    right = up.cross(f).normalized()
    up = f.cross(right).normalized()
    c = center
    corners = [c - right * w / 2 - up * h / 2, c + right * w / 2 - up * h / 2, c + right * w / 2 + up * h / 2, c - right * w / 2 + up * h / 2]
    b.plain_quad(corners, slot)

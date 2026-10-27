# -*- coding: utf-8 -*-
"""Fondos, planos de camara y tipografia."""
import numpy as np
from PIL import Image

FUENTE = r"C:\Windows\Fonts\seguibl.ttf"

# ---------------- fondos ----------------
# (arriba, abajo, resplandor)
FONDOS = {
    'violeta': ((28, 22, 56), (86, 30, 74), (120, 60, 150)),
    'noche':   ((12, 18, 34), (22, 48, 78), (40, 110, 170)),
    'ambar':   ((38, 20, 12), (104, 48, 16), (190, 110, 30)),
    'verde':   ((10, 32, 30), (16, 70, 58), (40, 160, 120)),
    'carmin':  ((34, 10, 26), (96, 20, 48), (190, 50, 90)),
}

def fondo(nombre, W, H):
    top, bot, glow = FONDOS.get(nombre, FONDOS['violeta'])
    y = np.linspace(0, 1, H)[:, None]
    g = np.array(top) * (1 - y) + np.array(bot) * y
    bg = np.repeat(g[:, None, :], W, axis=1)
    xx = (np.arange(W) - W * .5) / (W * .6)
    yy = (np.arange(H) - H * .34) / (H * .45)
    r = np.sqrt(xx[None, :] ** 2 + yy[:, None] ** 2)
    bg = bg + (np.clip(1 - r, 0, 1) ** 2.2)[..., None] * np.array(glow)
    vig = np.clip(1.25 - np.sqrt((xx[None, :] * .9) ** 2 + (yy[:, None] * .7) ** 2) * .8, 0, 1)
    return Image.fromarray((bg * vig[..., None]).clip(0, 255).astype(np.uint8), 'RGB')

# ---------------- planos ----------------
# Los encuadres se derivan de las medidas del rig, no de coordenadas fijas: asi
# sirven para cualquier personaje que se mida.
#   modo 'sujeto' -> frac = altura del cuerpo respecto al lienzo
#                    foco = punto del cuerpo (0 cabeza, 1 pies) que se centra
#   modo 'ojos'   -> frac = separacion ocular respecto al ancho del lienzo
PLANOS = {
    'completo': dict(modo='sujeto', frac=0.82, foco=0.500, ancla=0.531),
    'amplio':   dict(modo='sujeto', frac=0.95, foco=0.460, ancla=0.520),
    'medio':    dict(modo='sujeto', frac=1.12, foco=0.395, ancla=0.535),
    'cerca':    dict(modo='ojos',   frac=0.283,             ancla=0.396),
}
SECUENCIA = ['completo', 'medio', 'completo', 'cerca',
             'completo', 'medio', 'completo', 'cerca']

EMPUJE = 0.035        # zoom lento dentro de cada plano
MIN_PLANO = 1.8       # no cortar antes de esto
OBJ_PLANO = 3.2       # duracion que se busca
MAX_PLANO = 5.2       # si no hay corte antes, se acepta el siguiente
DUR_RECURSO = 2.0     # lo que dura una pose de recurso
# orden en que entran las poses: alterna expresion y accion, en vez de
# alfabetico (que sacaba las dos de caminar seguidas)
ORDEN_RECURSOS = ['pensativo', 'hombros', 'caminando', 'sorprendido',
                  'saludando', 'caminando2', 'pulgar']


def encuadre(nombre, avance, rig, W, H):
    """Devuelve (escala, foco_x, foco_y, ancla_x, ancla_y) para este rig."""
    p = PLANOS.get(nombre, PLANOS['medio'])
    z = 1.0 + EMPUJE * avance
    if p['modo'] == 'ojos':
        esc = p['frac'] * W / max(rig.sep, 1.0) * z
        fx, fy = rig.ojos_centro
    else:
        sx0, sy0, sx1, sy1 = rig.sujeto
        alto = max(sy1 - sy0, 1)
        esc = p['frac'] * H / alto * z
        fx = (sx0 + sx1) / 2.0
        fy = sy0 + p['foco'] * alto
    return esc, fx, fy, W * 0.5, H * p['ancla']

# -*- coding: utf-8 -*-
"""Fondos, planos de camara y tipografia."""
import numpy as np

import entorno
from PIL import Image

FUENTE = entorno.fuente()

# ---------------- fondos ----------------
# Tres modos:
#   'degradado'  uno de los presets de abajo
#   'color'      un color propio, del que se deriva un degradado con la misma
#                estructura que los presets (plano queda muerto en video)
#   'imagen'     una foto subida, recortada y tratada para que el personaje y
#                los subtitulos sigan leyendose encima
#
# (arriba, abajo, resplandor)
FONDOS = {
    'violeta': ((28, 22, 56), (86, 30, 74), (120, 60, 150)),
    'noche':   ((12, 18, 34), (22, 48, 78), (40, 110, 170)),
    'ambar':   ((38, 20, 12), (104, 48, 16), (190, 110, 30)),
    'verde':   ((10, 32, 30), (16, 70, 58), (40, 160, 120)),
    'carmin':  ((34, 10, 26), (96, 20, 48), (190, 50, 90)),
}

# cuanto se agranda el fondo para poder desplazarlo sin que falte borde
MARGEN_DERIVA = 0.09


def _hex_a_rgb(c):
    c = str(c).lstrip('#').strip()
    if len(c) == 3:
        c = ''.join(ch * 2 for ch in c)
    if len(c) != 6:
        raise ValueError(f'color no válido: {c}')
    return tuple(int(c[i:i+2], 16) for i in (0, 2, 4))


def desde_color(color):
    """Deriva (arriba, abajo, resplandor) de un color cualquiera.

    Un color plano en video se ve muerto. Se construye el mismo esqueleto que
    tienen los presets: oscuro arriba, el color a media altura y un resplandor
    más vivo detrás de la cabeza.
    """
    import colorsys
    r, g, b = [v / 255 for v in _hex_a_rgb(color)]
    h, l, s = colorsys.rgb_to_hls(r, g, b)
    s = max(s, 0.22)                       # un gris puro no da degradado
    def rgb(lum, sat):
        return tuple(int(255 * v) for v in colorsys.hls_to_rgb(h, lum, sat))
    return (rgb(min(l, 0.9) * 0.20, s * 0.80),
            rgb(min(l, 0.9) * 0.42, s * 0.88),
            rgb(max(l, 0.5) * 0.92, min(s * 1.05, 1.0)))


def _degradado(tri, W, H):
    top, bot, glow = tri
    y = np.linspace(0, 1, H)[:, None]
    g = np.array(top) * (1 - y) + np.array(bot) * y
    bg = np.repeat(g[:, None, :], W, axis=1)
    xx = (np.arange(W) - W * .5) / (W * .6)
    yy = (np.arange(H) - H * .34) / (H * .45)
    r = np.sqrt(xx[None, :] ** 2 + yy[:, None] ** 2)
    bg = bg + (np.clip(1 - r, 0, 1) ** 2.2)[..., None] * np.array(glow)
    vig = np.clip(1.25 - np.sqrt((xx[None, :] * .9) ** 2 + (yy[:, None] * .7) ** 2) * .8, 0, 1)
    return Image.fromarray((bg * vig[..., None]).clip(0, 255).astype(np.uint8), 'RGB')


def _desde_imagen(ruta, W, H, oscurecer=0.45, desenfoque=0.35):
    """Recorta la foto a lo alto y la trata para que no compita con el personaje.

    Sin tratar, una foto detrás de un recorte se ve como un collage: los dos
    planos están igual de nítidos y de contrastados. El desenfoque simula
    profundidad de campo y el oscurecido devuelve el peso visual a la cara.
    """
    from PIL import ImageEnhance, ImageFilter
    im = Image.open(ruta).convert('RGB')
    # recorte "cover": llena el lienzo y sobra por el lado largo
    esc = max(W / im.width, H / im.height)
    im = im.resize((max(int(im.width * esc) + 1, W),
                    max(int(im.height * esc) + 1, H)), Image.LANCZOS)
    iz, ar = (im.width - W) // 2, (im.height - H) // 2
    im = im.crop((iz, ar, iz + W, ar + H))

    if desenfoque > 0.01:
        im = im.filter(ImageFilter.GaussianBlur(2 + 22 * desenfoque))
    if desenfoque > 0.2:                        # al desenfocar, bajar saturación
        im = ImageEnhance.Color(im).enhance(1 - 0.35 * desenfoque)

    a = np.asarray(im).astype(np.float32)
    xx = (np.arange(W) - W * .5) / (W * .62)
    yy = (np.arange(H) - H * .40) / (H * .56)
    vig = np.clip(1.18 - np.sqrt(xx[None, :] ** 2 + yy[:, None] ** 2) * .62, 0, 1)
    a *= (1 - oscurecer) * vig[..., None]
    return Image.fromarray(a.clip(0, 255).astype(np.uint8), 'RGB')


def normalizar(spec):
    """Admite 'violeta', '#1b2a4a', 'img:atardecer' o un dict ya formado."""
    if isinstance(spec, dict):
        d = dict(spec)
    elif isinstance(spec, str) and spec.startswith('#'):
        d = {'tipo': 'color', 'color': spec}
    elif isinstance(spec, str) and spec.startswith('img:'):
        d = {'tipo': 'imagen', 'imagen': spec[4:]}
    else:
        d = {'tipo': 'degradado', 'id': spec if spec in FONDOS else 'violeta'}
    d.setdefault('tipo', 'degradado')
    return d


def fondo(spec, W, H):
    """Devuelve (imagen, deriva). `deriva` indica si se puede desplazar."""
    import fondos
    d = normalizar(spec)
    if d['tipo'] == 'imagen':
        ruta = fondos.ruta(d.get('imagen', ''))
        if ruta:
            m = 1 + MARGEN_DERIVA
            im = _desde_imagen(ruta, int(W * m), int(H * m),
                               float(d.get('oscurecer', 0.45)),
                               float(d.get('desenfoque', 0.35)))
            return im, True
        d = {'tipo': 'degradado', 'id': 'violeta'}     # la imagen ya no está
    if d['tipo'] == 'color':
        try:
            return _degradado(desde_color(d.get('color', '#7C3AED')), W, H), False
        except ValueError:
            pass
    return _degradado(FONDOS.get(d.get('id'), FONDOS['violeta']), W, H), False


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

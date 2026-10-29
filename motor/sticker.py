# -*- coding: utf-8 -*-
"""Convierte un logotipo en PNG transparente y SVG listos para imprimir.

    python sticker.py ../logo.jpeg
    python sticker.py ../logo.jpeg --cm 12 --ppp 300 --borde-mm 2

El original suele ser un JPEG pequeño con el logo pegado sobre un fondo. Aquí
no se recorta y se amplía: eso siempre acaba borroso. Lo que se hace es:

  1. detectar el soporte (el círculo del logo) con precisión subpíxel,
  2. separar los colores planos de la mezcla que inventa el JPEG en los bordes,
  3. revectorizar cada color a curvas de Bézier,
  4. rasterizar esas curvas al tamaño de impresión que se pida.

El paso 3 es el que importa: a partir de ahí el logo ya no tiene resolución, se
dibuja igual de nítido a 3 cm que a 30. Deja en `salida/stickers/<nombre>/`:

    <nombre>_transparente.png     recorte fiel, a la resolución del original
    <nombre>.svg                  trazado vectorial (lo que pide la imprenta)
    <nombre>_<N>cm_<P>ppp.png     rasterizado del vector al tamaño de impresión
    <nombre>_revision.png         original contra resultado, para mirarlo

Requisitos: numpy, opencv-python, scikit-image, pillow.
"""
import os
import argparse
import numpy as np
import cv2
from PIL import Image
from scipy.ndimage import gaussian_filter1d
from skimage import measure

AQUI = os.path.dirname(os.path.abspath(__file__))
SALIDA = os.path.join(AQUI, '..', 'salida', 'stickers')

ESCALA = 4           # aumentos maximos a los que se clasifica y se traza
OBJETIVO = 4000      # lado de trabajo: acota la memoria con logos grandes
MAX_LADO = 1800      # lado maximo del original; por encima no se gana nada
TOL_TRAZO = 0.14     # error máximo del ajuste de Bézier, en píxeles del original
ANGULO_ESQUINA = 58  # grados de giro a partir de los cuales hay esquina viva
PASO_TRAZO = 0.45    # separación de los puntos del contorno, en píxeles
SUAVIZADO = 1.6      # puntos de contorno que se promedian para quitar el ruido


# ===================================================================== recorte
def _ajustar_circulo(pts, vueltas=12):
    """Círculo de mínimos cuadrados con rechazo iterativo de puntos sueltos."""
    p = np.asarray(pts, np.float64)
    cx = cy = r = 0.0
    n = len(p)
    for _ in range(vueltas):
        A = np.c_[2 * p[:, 0], 2 * p[:, 1], np.ones(len(p))]
        sol, *_ = np.linalg.lstsq(A, (p ** 2).sum(1), rcond=None)
        cx, cy, c = sol
        r = float(np.sqrt(max(c + cx * cx + cy * cy, 1e-9)))
        res = np.abs(np.hypot(p[:, 0] - cx, p[:, 1] - cy) - r)
        corte = max(1.5, float(np.percentile(res, 80)))
        if (res < corte).sum() < 60:
            break
        p = p[res < corte]
        n = len(p)
    return float(cx), float(cy), r, n


def _lab(rgb):
    """La imagen en LAB, donde una distancia se parece a lo que ve el ojo."""
    return cv2.cvtColor((rgb / 255.).astype(np.float32), cv2.COLOR_RGB2LAB)


# Los logos llegan de cuatro maneras, y cada una se reconoce por su lado. Se
# prueban en este orden, de la pista mas fiable a la mas costosa.
METODOS = {
    'alfa':   'la transparencia que ya traía el archivo',
    'fondo':  'un fondo de un solo color',
    'centro': 'la mancha de color del centro',
    'modelo': 'un modelo de recorte automático',
}


def _mascara_alfa(alfa):
    """El archivo ya venía recortado: su propio canal alfa manda."""
    if alfa is None:
        return None
    m = alfa > 0.5
    ocupa = float(m.mean())
    # Un alfa opaco entero, o casi vacío, no dice nada: hay que buscar por otro lado.
    if ocupa > 0.995 or ocupa < 0.005:
        return None
    return m.astype(np.uint8)


def _mascara_fondo_plano(rgb, tol=7.0):
    """Fondo de un color uniforme (el típico blanco): se inunda desde el borde.

    Solo cuenta como fondo lo que toca el borde de la imagen. Así, un hueco
    interior del mismo color —el ojo de una «o», el centro de un aro— se queda
    dentro del logo en vez de abrirse un agujero.
    """
    lab = _lab(rgb)
    h, w, _ = lab.shape
    marco = np.concatenate([lab[0], lab[-1], lab[:, 0], lab[:, -1]])
    color = np.median(marco, axis=0)
    if float((np.linalg.norm(marco - color, axis=1) < tol).mean()) < 0.92:
        return None                       # el borde no es de un solo color
    fondo = (np.linalg.norm(lab - color, axis=2) < tol).astype(np.uint8)
    n, etiq, _, _ = cv2.connectedComponentsWithStats(fondo, 8)
    if n < 2:
        return None
    tocan = set(etiq[0]) | set(etiq[-1]) | set(etiq[:, 0]) | set(etiq[:, -1])
    tocan.discard(0)
    if not tocan:
        return None
    m = (~np.isin(etiq, list(tocan))).astype(np.uint8)
    ocupa = float(m.mean())
    if ocupa < 0.004 or ocupa > 0.99:
        return None
    return m


def _mascara_central(rgb, tol=7.0):
    """Soporte de color plano, como la pastilla redonda de un logo de perfil."""
    lab = _lab(rgb)
    h, w, _ = lab.shape
    # Mediana y no media: el centro de la imagen suele caer sobre una letra, y
    # un promedio ahí devuelve un color que no existe en el logo.
    ventana = lab[int(h * .3):int(h * .7), int(w * .3):int(w * .7)].reshape(-1, 3)
    centro = np.median(ventana, axis=0)
    m = (np.linalg.norm(lab - centro, axis=2) < tol).astype(np.uint8)
    k = max(9, (min(h, w) // 26) | 1)
    m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, np.ones((k, k), np.uint8))
    n, etiq, est, _ = cv2.connectedComponentsWithStats(m, 8)
    if n < 2:
        return None
    mayor = 1 + int(np.argmax(est[1:, cv2.CC_STAT_AREA]))
    if est[mayor, cv2.CC_STAT_AREA] < 0.05 * h * w:
        return None
    comp = (etiq == mayor).astype(np.uint8)
    return cv2.morphologyEx(comp, cv2.MORPH_CLOSE, np.ones((15, 15), np.uint8))


def _mascara_modelo(rgb):
    """Ultimo recurso: un fondo que no es plano ni una pastilla, una foto.

    Lo resuelve rembg, que ya es una dependencia del equipo. Es lo más lento y
    lo menos exacto de los cuatro, por eso va al final.
    """
    try:
        from rembg import remove
    except Exception:
        return None
    try:
        salida = remove(cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR), only_mask=True)
    except Exception:
        return None
    if salida is None or not hasattr(salida, 'shape'):
        return None
    if salida.ndim == 3:
        salida = salida[..., -1]
    m = (salida > 127).astype(np.uint8)
    ocupa = float(m.mean())
    if ocupa < 0.004 or ocupa > 0.995:
        return None
    return m


def _limpiar_mascara(m, minimo=0.0015):
    """Quita motas y tapa agujeros de ruido, pero respeta las piezas sueltas.

    Un logotipo bien puede ser varias piezas —las letras de una palabra—, así
    que no vale quedarse solo con la mayor.
    """
    if m is None:
        return None
    m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
    total = m.shape[0] * m.shape[1]
    n, etiq, est, _ = cv2.connectedComponentsWithStats(m, 8)
    if n < 2:
        return None
    grandes = [k for k in range(1, n) if est[k, cv2.CC_STAT_AREA] > minimo * total]
    if not grandes:
        return None
    out = np.isin(etiq, grandes).astype(np.uint8)
    return _quitar_motas(out, max(int(minimo * total * 0.2), 12))


def _afinar_circulo(m):
    """Si la máscara es un círculo, devuelve el círculo exacto; si no, None.

    Merece la pena comprobarlo con cualquier máscara: cuando el logo es una
    pastilla redonda, el círculo ajustado da un borde mucho mejor que el
    contorno medido píxel a píxel.
    """
    cnts, _ = cv2.findContours(m, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    if not cnts:
        return None
    c = max(cnts, key=cv2.contourArea)
    area = cv2.contourArea(c)
    if area < 0.05 * m.shape[0] * m.shape[1] or area < 0.92 * float(m.sum()):
        return None                        # hay mas piezas: no es una pastilla
    cx, cy, r, n = _ajustar_circulo(c.reshape(-1, 2))
    if n > 200 and abs(area - np.pi * r * r) / (np.pi * r * r) < 0.06:
        return cx, cy, r
    return None


def detectar_soporte(rgb, alfa=None):
    """Devuelve (metodo, mascara) con el primer método que reconozca el logo."""
    for nombre, buscar in (('alfa', lambda: _mascara_alfa(alfa)),
                           ('fondo', lambda: _mascara_fondo_plano(rgb)),
                           ('centro', lambda: _mascara_central(rgb)),
                           ('modelo', lambda: _mascara_modelo(rgb))):
        m = _limpiar_mascara(buscar())
        if m is not None:
            return nombre, m
    return None, None


def _cobertura_circulo(alto, ancho, cx, cy, r):
    """Alfa del círculo con el borde resuelto a nivel de subpíxel."""
    yy, xx = np.mgrid[0:alto, 0:ancho].astype(np.float32)
    d = np.hypot(xx - cx, yy - cy)
    return np.clip(r - d + 0.5, 0, 1)


def _despegar_halo(rgb, alfa):
    """Quita el color de fondo que el JPEG mezcló en el borde del recorte.

    Los píxeles que no son opacos del todo llevan fondo dentro; se les asigna el
    color del píxel firme más cercano, que ya es sólo del logo.
    """
    firme = (alfa > 0.995).astype(np.uint8)
    if firme.all() or not firme.any():
        return rgb
    _, etiquetas = cv2.distanceTransformWithLabels(
        1 - firme, cv2.DIST_L2, 5, labelType=cv2.DIST_LABEL_PIXEL)
    ys, xs = np.nonzero(firme)
    tabla = np.zeros((int(etiquetas.max()) + 1, 2), np.int32)
    tabla[etiquetas[firme.astype(bool)]] = np.c_[ys, xs]
    fuente = tabla[etiquetas]
    out = rgb.copy()
    flojo = alfa <= 0.995
    out[flojo] = rgb[fuente[..., 0][flojo], fuente[..., 1][flojo]]
    return out


def cargar(ruta, max_lado=None):
    """Lee la imagen. Devuelve (rgb uint8, alfa 0..1 o None).

    Se lee sin tocar los canales para no perder la transparencia: si el logo ya
    venía recortado, ese alfa es la mejor pista que hay.
    """
    datos = cv2.imread(ruta, cv2.IMREAD_UNCHANGED)
    if datos is None:
        raise RuntimeError('No se puede abrir la imagen: %s' % ruta)
    if datos.dtype == np.uint16:
        datos = (datos // 257).astype(np.uint8)
    elif datos.dtype != np.uint8:
        datos = np.clip(datos, 0, 255).astype(np.uint8)
    if datos.ndim == 2:
        datos = cv2.cvtColor(datos, cv2.COLOR_GRAY2BGR)
    alfa = None
    if datos.shape[2] == 4:
        alfa = datos[..., 3].astype(np.float32) / 255.
        datos = datos[..., :3]
    elif datos.shape[2] != 3:
        datos = datos[..., :3]
    rgb = cv2.cvtColor(datos, cv2.COLOR_BGR2RGB)

    # El trazado ya trabaja a varios aumentos del original, asi que partir de
    # 4000 px no afina el dibujo: solo multiplica la memoria, el tiempo y el
    # numero de curvas del SVG. Se reduce la entrada a un tamano razonable.
    largo = max(rgb.shape[:2])
    if max_lado and largo > max_lado:
        f = max_lado / float(largo)
        rgb = cv2.resize(rgb, None, fx=f, fy=f, interpolation=cv2.INTER_AREA)
        if alfa is not None:
            alfa = cv2.resize(alfa, (rgb.shape[1], rgb.shape[0]),
                              interpolation=cv2.INTER_AREA)
    return rgb, alfa


def recortar(rgb, alfa_origen=None, margen=1.0):
    """Separa el logo del fondo. Devuelve (rgb, alfa, caja, soporte, metodo)."""
    metodo, m = detectar_soporte(rgb, alfa_origen)
    if m is None:
        raise RuntimeError(
            'No se reconoce ninguna figura clara en esta imagen. Se ha probado '
            'con la transparencia del archivo, con un fondo de un solo color, '
            'con la mancha de color del centro y con el recorte automático, y '
            'ninguno la ha encontrado. Recórtala a mano, o súbela en PNG con el '
            'fondo ya transparente.')
    h, w, _ = rgb.shape
    circulo = _afinar_circulo(m)
    if circulo:
        cx, cy, r = circulo
        r -= margen                                   # un pelo hacia dentro: el
        alfa = _cobertura_circulo(h, w, cx, cy, r)    # borde del JPEG está sucio
        x0, y0 = int(np.floor(cx - r)), int(np.floor(cy - r))
        x1, y1 = int(np.ceil(cx + r)) + 1, int(np.ceil(cy + r)) + 1
        x0, y0 = max(x0, 0), max(y0, 0)
        x1, y1 = min(x1, w), min(y1, h)
        soporte = ('circulo', (cx - x0, cy - y0, r))
    else:
        duro = m
        if metodo != 'alfa' and margen >= 1:
            # Un archivo que ya venia transparente tiene el borde limpio; los
            # demas llevan fondo mezclado en el ultimo pixel y conviene comerlo.
            duro = cv2.erode(m, np.ones((3, 3), np.uint8), iterations=int(margen))
            if not duro.any():
                duro = m
        if metodo == 'alfa':
            alfa = np.minimum(alfa_origen, duro.astype(np.float32))
        else:
            alfa = cv2.GaussianBlur(duro.astype(np.float32), (0, 0), 0.6)
        xs, ys = np.nonzero(duro.any(0))[0], np.nonzero(duro.any(1))[0]
        x0, x1, y0, y1 = int(xs[0]), int(xs[-1]) + 1, int(ys[0]), int(ys[-1]) + 1
        soporte = ('silueta', None)
    rec = rgb[y0:y1, x0:x1]
    alf = alfa[y0:y1, x0:x1]
    return _despegar_halo(rec, alf), alf, (x0, y0, x1, y1), soporte, metodo


# ====================================================================== paleta
def _a_lab(rgb):
    return cv2.cvtColor((rgb.reshape(-1, 1, 3) / 255.).astype(np.float32),
                        cv2.COLOR_RGB2LAB).reshape(-1, 3)


def _es_mezcla(c, previos, umbral=6.0):
    """¿El color cae sobre la recta entre dos colores ya aceptados?

    Si cae, no es tinta del logo: es el degradado con el que el antialias une
    dos tintas vecinas, y vectorizarlo sólo añade halos.
    """
    for i in range(len(previos)):
        for j in range(i + 1, len(previos)):
            a, b = previos[i], previos[j]
            ab = b - a
            n2 = float(ab @ ab)
            if n2 < 1e-6:
                continue
            t = float((c - a) @ ab) / n2
            if 0.12 < t < 0.88 and np.linalg.norm(c - (a + t * ab)) < umbral:
                return True
    return False


def paleta(rgb, alfa, maximo=16, minimo=0.0002):
    """Colores planos reales del logo, sin las mezclas que inventa el JPEG."""
    px = rgb[alfa > 0.9].reshape(-1, 3)
    if len(px) > 160000:
        px = px[np.random.default_rng(7).choice(len(px), 160000, replace=False)]
    lab = _a_lab(px)
    crit = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 40, 0.4)
    _, etiq, centros = cv2.kmeans(lab, 28, None, crit, 4, cv2.KMEANS_PP_CENTERS)
    peso = np.bincount(etiq.ravel(), minlength=28) / len(lab)

    elegidos = []
    for i in np.argsort(-peso):
        if peso[i] < minimo or len(elegidos) >= maximo:
            continue
        c = centros[i]
        if any(np.linalg.norm(c - e) < 9 for e in elegidos):
            continue
        if _es_mezcla(c, elegidos):
            continue
        elegidos.append(c)
    if not elegidos:
        elegidos = [centros[int(np.argmax(peso))]]
    lab_pal = np.array(elegidos, np.float32)
    rgb_pal = cv2.cvtColor(lab_pal.reshape(-1, 1, 3), cv2.COLOR_LAB2RGB)
    return lab_pal, np.clip(rgb_pal.reshape(-1, 3) * 255, 0, 255).round().astype(int)


def _quitar_motas(m, minimo):
    """Borra islas y agujeros más pequeños que `minimo` píxeles."""
    for hueco in (False, True):
        a = (1 - m) if hueco else m
        n, etiq, est, _ = cv2.connectedComponentsWithStats(a, 8)
        malas = [k for k in range(1, n) if est[k, cv2.CC_STAT_AREA] < minimo]
        if malas:
            borrar = np.isin(etiq, malas)
            m = (m | borrar) if hueco else (m & ~borrar)
            m = m.astype(np.uint8)
    return m


def escala_trabajo(ancho, alto, objetivo=OBJETIVO, tope=ESCALA):
    """Aumentos a los que conviene trabajar este recorte.

    El borde subpixel sale de clasificar la imagen ampliada, pero ampliar x4 un
    logo que ya viene a 3000 px pide gigabytes y no aporta nada: el detalle ya
    estaba. Se fija el lado de trabajo y se deduce el factor.
    """
    return int(max(2, min(tope, round(objetivo / max(ancho, alto, 1)))))


def capas(rgb, alfa, lab_pal, escala=ESCALA):
    """Máscara binaria de cada color de la paleta, a `escala` aumentos.

    Clasificar sobre la imagen ampliada es lo que da el borde subpíxel: el
    contorno que sale después tiene precisión de 1/escala de píxel original.
    """
    h, w, _ = rgb.shape
    gr = cv2.resize(rgb, (w * escala, h * escala), interpolation=cv2.INTER_LANCZOS4)
    gr = cv2.bilateralFilter(gr, 7, 28, 7)            # calma el ruido del JPEG
    ga = cv2.resize(alfa, (w * escala, h * escala), interpolation=cv2.INTER_LINEAR)

    etiq = np.zeros(gr.shape[:2], np.int16)
    banda = max(1, 2000000 // (w * escala))
    for y in range(0, gr.shape[0], banda):
        trozo = _a_lab(gr[y:y + banda])
        d = ((trozo[:, None, :] - lab_pal[None]) ** 2).sum(2)
        etiq[y:y + banda] = d.argmin(1).reshape(-1, gr.shape[1])

    dentro = ga > 0.5
    minimo = int((escala * 2.0) ** 2)   # por debajo de 4 px del original es ruido
    salida = []
    for i in range(len(lab_pal)):
        m = ((etiq == i) & dentro).astype(np.uint8)
        m = cv2.morphologyEx(m, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
        m = _quitar_motas(m, minimo)
        m = (cv2.GaussianBlur(m.astype(np.float32), (0, 0), escala * 0.55) > 0.5)
        m = _quitar_motas(m.astype(np.uint8), minimo)
        if m.any():
            salida.append((i, m))
    salida.sort(key=lambda t: -int(t[1].sum()))
    return salida


# ===================================================================== trazado
def _remuestrear(pts, paso):
    """Reparte los puntos del contorno cada `paso` unidades de longitud."""
    d = np.r_[0, np.cumsum(np.hypot(*np.diff(pts, axis=0).T))]
    if d[-1] < paso * 3:
        return pts
    u = np.arange(0, d[-1], paso)
    return np.c_[np.interp(u, d, pts[:, 0]), np.interp(u, d, pts[:, 1])]


def _suavizar(pts, esquinas, sigma=SUAVIZADO, radio=3):
    """Quita el temblor del contorno sin redondear las esquinas.

    El contorno que sale de un JPEG viene ondulado por el ruido de compresión;
    si se traza tal cual, las rectas salen temblorosas. Se promedia a lo largo
    de la curva, pero alrededor de cada esquina se devuelve el punto original:
    sin eso, las puntas de las estrellas se achatarían.
    """
    if len(pts) < 6:
        return pts
    sua = np.c_[gaussian_filter1d(pts[:, 0], sigma, mode='wrap'),
                gaussian_filter1d(pts[:, 1], sigma, mode='wrap')]
    if not esquinas:
        return sua
    peso = np.ones(len(pts))
    for k in esquinas:
        for d in range(-radio, radio + 1):
            peso[(k + d) % len(pts)] = min(peso[(k + d) % len(pts)],
                                           abs(d) / float(radio + 1))
    return sua * peso[:, None] + pts * (1 - peso)[:, None]


def _esquinas(pts, grados=ANGULO_ESQUINA, salto=5):
    """Índices donde el contorno gira de golpe: ahí no se puede suavizar."""
    n = len(pts)
    if n < salto * 3:
        return []
    i = np.arange(n)
    a = pts[i] - pts[(i - salto) % n]
    b = pts[(i + salto) % n] - pts[i]
    na, nb = np.linalg.norm(a, axis=1), np.linalg.norm(b, axis=1)
    cos = np.clip((a * b).sum(1) / np.maximum(na * nb, 1e-9), -1, 1)
    ang = np.degrees(np.arccos(cos))
    picos, ultimo = [], -99
    for k in np.nonzero(ang > grados)[0]:
        if k - ultimo <= salto and picos:
            if ang[k] > ang[picos[-1]]:
                picos[-1] = int(k)
        else:
            picos.append(int(k))
        ultimo = k
    return picos


def _tangente(pts, i, hacia, salto=3):
    """Dirección unitaria del contorno en `i`, mirando adelante o atrás."""
    j = min(i + salto, len(pts) - 1) if hacia > 0 else max(i - salto, 0)
    v = pts[j] - pts[i]
    nv = np.linalg.norm(v)
    return v / nv if nv > 1e-9 else np.array([1.0, 0.0])


def _bezier(b, t):
    s = 1 - t
    return (s ** 3)[:, None] * b[0] + (3 * s * s * t)[:, None] * b[1] + \
           (3 * s * t * t)[:, None] * b[2] + (t ** 3)[:, None] * b[3]


def _generar(d, u, t1, t2):
    """Bézier de mínimos cuadrados con extremos y tangentes fijados."""
    s = 1 - u
    a1 = (3 * s * s * u)[:, None] * t1
    a2 = (3 * s * u * u)[:, None] * t2
    tmp = d - ((s ** 3) + 3 * s * s * u)[:, None] * d[0] \
            - ((u ** 3) + 3 * s * u * u)[:, None] * d[-1]
    c = np.array([[(a1 * a1).sum(), (a1 * a2).sum()],
                  [(a1 * a2).sum(), (a2 * a2).sum()]])
    x = np.array([(a1 * tmp).sum(), (a2 * tmp).sum()])
    det = c[0, 0] * c[1, 1] - c[0, 1] * c[1, 0]
    largo = float(np.linalg.norm(d[-1] - d[0]))
    if abs(det) < 1e-12:
        a = b = largo / 3
    else:
        a = (x[0] * c[1, 1] - c[0, 1] * x[1]) / det
        b = (c[0, 0] * x[1] - x[0] * c[1, 0]) / det
        if a < 1e-6 or b < 1e-6:
            a = b = largo / 3
    return np.array([d[0], d[0] + t1 * a, d[-1] + t2 * b, d[-1]])


def _error(d, b, u):
    dif = _bezier(b, u) - d
    e = (dif * dif).sum(1)
    k = int(np.argmax(e))
    return float(e[k]), k


def _reparametrizar(d, b, u):
    """Un paso de Newton sobre t, para que cada punto mire a su sitio."""
    q1 = 3 * (b[1:] - b[:-1])
    q2 = 2 * (q1[1:] - q1[:-1])
    s = 1 - u
    p = _bezier(b, u) - d
    d1 = (s * s)[:, None] * q1[0] + (2 * s * u)[:, None] * q1[1] + (u * u)[:, None] * q1[2]
    d2 = s[:, None] * q2[0] + u[:, None] * q2[1]
    den = (d1 * d1).sum(1) + (p * d2).sum(1)
    paso = np.where(np.abs(den) < 1e-9, 0.0, (p * d1).sum(1) / np.where(den == 0, 1, den))
    return np.clip(u - paso, 0, 1)


def _ajustar(pts, t1, t2, tol):
    """Curvas de Bézier que siguen `pts` con error menor que `tol`."""
    salida, pila = [], [(pts, t1, t2, 0)]
    tol2 = tol * tol
    while pila:
        d, ta, tb, prof = pila.pop()
        if len(d) < 3:
            largo = float(np.linalg.norm(d[-1] - d[0])) / 3
            salida.append(np.array([d[0], d[0] + ta * largo, d[-1] + tb * largo, d[-1]]))
            continue
        dist = np.r_[0, np.cumsum(np.hypot(*np.diff(d, axis=0).T))]
        u = dist / dist[-1] if dist[-1] > 0 else np.linspace(0, 1, len(d))
        b = _generar(d, u, ta, tb)
        err, corte = _error(d, b, u)
        if err > tol2 and prof < 18:
            for _ in range(4):
                u = _reparametrizar(d, b, u)
                b = _generar(d, u, ta, tb)
                err, corte = _error(d, b, u)
                if err <= tol2:
                    break
        if err <= tol2 or prof >= 18 or corte in (0, len(d) - 1):
            salida.append(b)
            continue
        tc = d[corte + 1] - d[corte - 1]
        nc = np.linalg.norm(tc)
        tc = tc / nc if nc > 1e-9 else ta
        pila.append((d[corte:], tc, tb, prof + 1))
        pila.append((d[:corte + 1], ta, -tc, prof + 1))
    return salida


def trazar(mask, escala=ESCALA, tol=TOL_TRAZO):
    """Contornos de una máscara convertidos en curvas, en píxeles del original."""
    anillos = []
    # El margen de un pixel no es un detalle: sin el, una figura que llega al
    # borde del recorte devuelve contornos abiertos, y al cerrarlos el relleno
    # par-impar los anula entre si y la capa entera desaparece. Y el recorte de
    # una silueta toca el borde siempre, porque se ajusta a la figura.
    relleno = np.pad(mask.astype(np.float32), 1)
    for cont in measure.find_contours(relleno, 0.5):
        pts = (np.c_[cont[:, 1], cont[:, 0]] - 1.0) / escala   # (fila,col)->(x,y)
        if len(pts) < 8:
            continue
        if np.linalg.norm(pts[0] - pts[-1]) < 1e-6:
            pts = pts[:-1]
        pts = _remuestrear(pts, PASO_TRAZO)
        if len(pts) < 8:
            continue
        # Perímetro mínimo: por debajo de esto es ruido del JPEG, no dibujo.
        if np.hypot(*(pts - np.roll(pts, 1, 0)).T).sum() < 4:
            continue
        cortes = _esquinas(pts)
        pts = _suavizar(pts, cortes)
        cerrado = np.r_[pts, pts[:1]]
        if len(cortes) < 2:
            cortes = [0, len(pts) // 2]
        curvas = []
        for k in range(len(cortes)):
            i, j = cortes[k], cortes[(k + 1) % len(cortes)]
            tramo = cerrado[i:j + 1] if j > i else np.r_[cerrado[i:], pts[1:j + 1]]
            if len(tramo) < 2:
                continue
            curvas += _ajustar(tramo, _tangente(tramo, 0, +1),
                               _tangente(tramo, len(tramo) - 1, -1), tol)
        if curvas:
            anillos.append(curvas)
    return anillos


# ========================================================================= svg
def _hex(c):
    return '#%02X%02X%02X' % tuple(int(v) for v in c)


def _d(anillo, dec=3):
    p = ['M%s,%s' % (round(anillo[0][0][0], dec), round(anillo[0][0][1], dec))]
    for b in anillo:
        p.append('C%s,%s %s,%s %s,%s' % tuple(
            round(v, dec) for pt in b[1:] for v in pt))
    p.append('Z')
    return ' '.join(p)


def escribir_svg(ruta, ancho, alto, figuras, soporte=None, fondo_color=None):
    """Guarda el SVG. `figuras` es una lista de (color_rgb, anillos)."""
    t = ['<?xml version="1.0" encoding="UTF-8"?>',
         '<svg xmlns="http://www.w3.org/2000/svg" width="%d" height="%d" '
         'viewBox="0 0 %d %d" shape-rendering="geometricPrecision">'
         % (ancho, alto, ancho, alto)]
    if soporte and soporte[0] == 'circulo' and fondo_color is not None:
        cx, cy, r = soporte[1]
        t.append('<circle cx="%.3f" cy="%.3f" r="%.3f" fill="%s"/>'
                 % (cx, cy, r, _hex(fondo_color)))
    for color, anillos in figuras:
        d = ' '.join(_d(a) for a in anillos)
        t.append('<path fill="%s" fill-rule="evenodd" d="%s"/>' % (_hex(color), d))
    t.append('</svg>')
    with open(ruta, 'w', encoding='utf-8') as f:
        f.write('\n'.join(t))


# ================================================================= rasterizado
def _polilinea(anillo, escala, paso=0.33):
    """Pasa las curvas de un anillo a puntos, denso para el tamaño final."""
    out = []
    for b in anillo:
        largo = (np.linalg.norm(b[1] - b[0]) + np.linalg.norm(b[2] - b[1]) +
                 np.linalg.norm(b[3] - b[2])) * escala
        n = int(np.clip(largo / paso, 2, 4000))
        out.append(_bezier(b * escala, np.linspace(0, 1, n, endpoint=False)))
    return np.concatenate(out) if out else np.zeros((0, 2))


def _pintar(col, alf, anillos, color, desp):
    """Rellena los anillos con regla par-impar: así salen los huecos."""
    puntos = []
    for p in anillos:
        if len(p) >= 3:
            q = p.copy()
            q[:, 1] -= desp
            puntos.append(np.round(q * 16).astype(np.int32))
    if not puntos:
        return
    cv2.fillPoly(col, puntos, tuple(float(v) for v in color), cv2.LINE_8, 4)
    cv2.fillPoly(alf, puntos, 255, cv2.LINE_8, 4)


def _disco(col, alf, cx, cy, r, color):
    c = (int(round(cx * 16)), int(round(cy * 16)))
    cv2.circle(col, c, int(round(r * 16)), tuple(float(v) for v in color),
               -1, cv2.LINE_8, 4)
    cv2.circle(alf, c, int(round(r * 16)), 255, -1, cv2.LINE_8, 4)


def rasterizar(ancho, alto, figuras, soporte, fondo_color, lado, ss=4):
    """Dibuja el vector a `lado` píxeles de ancho. Devuelve RGBA uint8.

    Se pinta a `ss` aumentos y se reduce con INTER_AREA, que es lo que da el
    borde suave; y se trabaja con el color premultiplicado por el alfa, para que
    al reducir no aparezca una orla oscura alrededor del recorte.
    """
    esc = lado / float(ancho)
    alto_px = int(round(alto * esc))
    polis = [(np.asarray(c, np.float64),
              [_polilinea(a, esc * ss) for a in anillos]) for c, anillos in figuras]

    out = np.zeros((alto_px, lado, 4), np.float32)
    filas = max(32, 4000000 // max(lado * ss * ss, 1))
    for y0 in range(0, alto_px, filas):
        y1 = min(y0 + filas, alto_px)
        col = np.zeros(((y1 - y0) * ss, lado * ss, 3), np.float32)
        alf = np.zeros(((y1 - y0) * ss, lado * ss), np.uint8)
        desp = y0 * ss

        if soporte and soporte[0] == 'circulo':
            cx, cy, r = soporte[1]
            _disco(col, alf, cx * esc * ss, cy * esc * ss - desp, r * esc * ss, fondo_color)
        for c, anillos in polis:
            _pintar(col, alf, anillos, c, desp)

        a = (alf > 0).astype(np.float32)
        banda = np.dstack([col * a[..., None], a])
        out[y0:y1] = cv2.resize(banda, (lado, y1 - y0), interpolation=cv2.INTER_AREA)

    alfa = np.clip(out[..., 3], 0, 1)
    rgb = out[..., :3] / np.maximum(alfa, 1e-6)[..., None]
    return np.dstack([np.clip(rgb, 0, 255), alfa * 255]).round().astype(np.uint8)


def con_borde(rgba, grosor_px, color=(255, 255, 255)):
    """Añade la pestaña blanca del troquel alrededor de la silueta."""
    if grosor_px <= 0:
        return rgba
    m = int(np.ceil(grosor_px)) + 2
    g = cv2.copyMakeBorder(rgba, m, m, m, m, cv2.BORDER_CONSTANT, value=(0, 0, 0, 0))
    a = g[..., 3].astype(np.float32) / 255.
    d = cv2.distanceTransform((g[..., 3] < 8).astype(np.uint8), cv2.DIST_L2, 5)
    halo = np.maximum(np.clip(grosor_px - d + 0.5, 0, 1), a)
    base = np.full(g[..., :3].shape, color, np.float32)
    rgb = g[..., :3].astype(np.float32) * a[..., None] + base * (1 - a[..., None])
    return np.dstack([rgb, halo * 255]).round().clip(0, 255).astype(np.uint8)


# ======================================================================== main
def guardar_png(ruta, rgba, ppp):
    im = Image.fromarray(rgba, 'RGBA')
    im.save(ruta, 'PNG', optimize=True, dpi=(ppp, ppp))
    return im.size


def revision(ruta, original, nuevo):
    """Original contra resultado, y un detalle ampliado, para mirarlo a ojo."""
    h = 520
    o, n = original.shape[0], nuevo.shape[0]
    rec = (0.47, 0.63, 0.17, 0.33)        # trozo de la 'g' de glamshop
    vistas = [
        Image.fromarray(original, 'RGBA').resize((h, h), Image.LANCZOS),
        Image.fromarray(nuevo, 'RGBA').resize((h, h), Image.LANCZOS),
        Image.fromarray(original[int(o * rec[0]):int(o * rec[1]),
                                 int(o * rec[2]):int(o * rec[3])], 'RGBA')
             .resize((h, h), Image.LANCZOS),
        Image.fromarray(nuevo[int(n * rec[0]):int(n * rec[1]),
                              int(n * rec[2]):int(n * rec[3])], 'RGBA')
             .resize((h, h), Image.LANCZOS),
    ]
    lienzo = Image.new('RGB', (h * 4 + 50, h + 20), (205, 205, 210))
    for i, im in enumerate(vistas):
        celda = Image.new('RGB', (h, h), (255, 255, 255) if i % 2 == 0 else (240, 240, 244))
        celda.paste(im, (0, 0), im)
        lienzo.paste(celda, (i * (h + 10) + 10, 10))
    lienzo.save(ruta, 'PNG')


def procesar(ruta, nombre=None, cm=10.0, ppp=300, colores=16, margen=1.0,
             borde_mm=0.0, sin_vector=False, destino=None, minimo=0.0002,
             con_revision=True, cb=None, max_lado=MAX_LADO):
    """Hace todo el recorrido y devuelve los datos del resultado.

    `cb(pct, mensaje)` recibe el avance; la interfaz web lo usa para la barra de
    progreso. Cuando no se pasa, el recorrido se cuenta por consola.
    """
    def info(linea):
        if cb is None:
            print(linea)

    def paso(pct, msg):
        if cb is not None:
            cb(pct, msg)

    rgb, alfa_origen = cargar(ruta, max_lado)
    nombre = nombre or os.path.splitext(os.path.basename(ruta))[0]
    dst = destino or os.path.join(SALIDA, nombre)
    os.makedirs(dst, exist_ok=True)
    info('origen        %s  %dx%d px%s'
         % (os.path.basename(ruta), rgb.shape[1], rgb.shape[0],
            '  (con alfa)' if alfa_origen is not None else ''))

    paso(4, 'Buscando el logo dentro de la imagen…')
    rec, alfa, caja, soporte, metodo = recortar(rgb, alfa_origen, margen)
    h, w, _ = rec.shape
    fiel = np.dstack([rec, (alfa * 255).round().clip(0, 255)]).astype(np.uint8)
    p_fiel = os.path.join(dst, nombre + '_transparente.png')
    guardar_png(p_fiel, fiel, ppp)
    info('recorte       %s  %dx%d  (%s -> %s)'
         % (os.path.basename(p_fiel), w, h, METODOS[metodo], soporte[0]))
    r = {'carpeta': dst, 'nombre': nombre, 'soporte': soporte[0],
         'metodo': metodo, 'recorte': [w, h], 'fiel': os.path.basename(p_fiel)}
    if sin_vector:
        paso(100, 'Listo')
        return r

    paso(16, 'Separando las tintas…')
    lab_pal, rgb_pal = paleta(rec, alfa, colores, minimo)
    info('paleta        %s' % '  '.join(_hex(c) for c in rgb_pal))

    escala = escala_trabajo(w, h)
    paso(24, 'Clasificando los colores a %d aumentos…' % escala)
    capas_m = capas(rec, alfa, lab_pal, escala)
    base = rgb_pal[capas_m[0][0]]

    # La capa de fondo solo se puede dar por pintada cuando el soporte es un
    # circulo, porque entonces el disco la cubre entera. Con una silueta hay
    # que trazarla como una figura mas, o el sticker sale agujereado.
    pendientes = capas_m[1:] if soporte[0] == 'circulo' else capas_m
    figuras = []
    for k, (i, m) in enumerate(pendientes):
        paso(52 + int(26 * k / max(len(pendientes), 1)),
             'Trazando las curvas… capa %d de %d' % (k + 1, len(pendientes)))
        anillos = trazar(m, escala)
        if anillos:
            figuras.append((rgb_pal[i], anillos))
    curvas = sum(len(a) for _, fs in figuras for a in fs)
    info('vector        %d capas, %d curvas de Bezier' % (len(figuras), curvas))

    paso(80, 'Escribiendo el SVG…')
    p_svg = os.path.join(dst, nombre + '.svg')
    escribir_svg(p_svg, w, h, figuras, soporte, base)
    info('              %s  (%.0f KB)'
         % (os.path.basename(p_svg), os.path.getsize(p_svg) / 1024))

    paso(86, 'Dibujando el PNG al tamaño de impresión…')
    # El tamano pedido es el del lado mayor: asi el sticker cabe siempre en el
    # cuadrado que se eligio. Si el logo no es cuadrado, el otro lado sale en
    # proporcion, que es lo que se espera de un logo apaisado.
    objetivo = int(round(cm / 2.54 * ppp))
    lado = objetivo if w >= h else max(1, int(round(objetivo * w / float(h))))
    rgba = rasterizar(w, h, figuras, soporte, base, lado)
    if borde_mm > 0:
        rgba = con_borde(rgba, borde_mm / 25.4 * ppp)
    p_imp = os.path.join(dst, '%s_%gcm_%dppp.png' % (nombre, cm, ppp))
    tam = guardar_png(p_imp, rgba, ppp)
    info('impresion     %s  %dx%d px  = %.1f x %.1f cm a %d ppp'
         % (os.path.basename(p_imp), tam[0], tam[1],
            tam[0] / ppp * 2.54, tam[1] / ppp * 2.54, ppp))

    r.update(paleta=[_hex(c) for c in rgb_pal], capas=len(figuras), curvas=curvas,
             svg=os.path.basename(p_svg), svg_kb=round(os.path.getsize(p_svg) / 1024),
             png=os.path.basename(p_imp), px=list(tam), cm=cm, ppp=ppp,
             borde_mm=borde_mm,
             cm_real=[round(tam[0] / ppp * 2.54, 1), round(tam[1] / ppp * 2.54, 1)])

    if con_revision:
        paso(96, 'Montando la comparación…')
        p_rev = os.path.join(dst, nombre + '_revision.png')
        revision(p_rev, fiel, rasterizar(w, h, figuras, soporte, base, h))
        info('revision      %s' % os.path.basename(p_rev))
        r['revision'] = os.path.basename(p_rev)
    paso(100, 'Listo')
    return r


def main(argv=None):
    ap = argparse.ArgumentParser(
        description='Recorta un logo, lo revectoriza y lo deja listo para imprimir.')
    ap.add_argument('imagen')
    ap.add_argument('--nombre', help='nombre de los archivos de salida')
    ap.add_argument('--cm', type=float, default=10.0, help='lado impreso en cm (10)')
    ap.add_argument('--ppp', type=int, default=300, help='puntos por pulgada (300)')
    ap.add_argument('--colores', type=int, default=16, help='colores planos como mucho (16)')
    ap.add_argument('--max-lado', type=int, default=MAX_LADO,
                    help='lado maximo del original; 0 lo deja tal cual (%d)' % MAX_LADO)
    ap.add_argument('--minimo', type=float, default=0.0002,
                    help='superficie minima para que un color cuente, en tanto por uno (0.0002)')
    ap.add_argument('--margen', type=float, default=1.0,
                    help='pixeles que se recortan hacia dentro del borde (1)')
    ap.add_argument('--borde-mm', type=float, default=0.0,
                    help='pestana blanca de troquel, en mm (0)')
    ap.add_argument('--sin-vector', action='store_true',
                    help='solo recortar el fondo, sin revectorizar')
    ap.add_argument('--destino', help='carpeta de salida')
    a = ap.parse_args(argv)
    r = procesar(a.imagen, a.nombre, a.cm, a.ppp, a.colores, a.margen,
                 a.borde_mm, a.sin_vector, a.destino, a.minimo,
                 max_lado=a.max_lado)
    print('\nlisto -> %s' % os.path.abspath(r['carpeta']))


if __name__ == '__main__':
    main()

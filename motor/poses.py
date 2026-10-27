# -*- coding: utf-8 -*-
"""Prepara las poses de recurso: recorta el fondo blanco y guarda un catalogo.

    python poses.py            # procesa lo que haya nuevo
    python poses.py --forzar

Las imagenes se buscan en `poses_fuente/` y en la carpeta del proyecto.
Son planos de recurso: el personaje NO habla en ellas, se usan en tramos cortos
entre frases. Por eso valen poses de perfil o con la boca cerrada.
"""
import glob, json, os, sys
from collections import deque
import numpy as np
from PIL import Image, ImageFilter
from scipy import ndimage

AQUI = os.path.dirname(os.path.abspath(__file__))
FUENTE = os.path.join(AQUI, 'poses_fuente')
DESTINO = os.path.join(AQUI, 'poses')
CATALOGO = os.path.join(DESTINO, 'poses.json')

# nombres para las imagenes que ya estaban en el proyecto
CONOCIDAS = {
    '7j1t8q': 'caminando',   'faauf8': 'sorprendido', 'ghz7m9': 'hombros',
    'l0ezjx': 'pulgar',      'w3r3t1': 'caminando2',  'wge1rh': 'pensativo',
    'wjkiwt': 'saludando',
}


def recortar(ruta):
    """Quita el fondo blanco y la sombra de suelo, conservando dientes y tenis.

    La sombra que dibuja el generador es gris claro (210-240) con saturacion
    casi nula: sobre un fondo oscuro se ve como una mancha blanca. Los tenis
    tienen un `min_canal` mediano de 191, asi que el umbral no puede bajar sin
    mas; lo que los salva es que estan rodeados de pixeles mas oscuros.
    """
    src = Image.open(ruta).convert('RGB')
    a = np.asarray(src).astype(np.int16)
    h, w, _ = a.shape
    mn = a.min(axis=2)
    sat = a.max(axis=2) - mn
    fondo = (mn > 186) & (sat < 22)

    bg = np.zeros((h, w), bool)
    dq = deque()
    for x in range(w):
        for y in (0, h - 1):
            if fondo[y, x] and not bg[y, x]:
                bg[y, x] = True; dq.append((y, x))
    for y in range(h):
        for x in (0, w - 1):
            if fondo[y, x] and not bg[y, x]:
                bg[y, x] = True; dq.append((y, x))
    while dq:
        y, x = dq.popleft()
        for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            ny, nx = y + dy, x + dx
            if 0 <= ny < h and 0 <= nx < w and fondo[ny, nx] and not bg[ny, nx]:
                bg[ny, nx] = True; dq.append((ny, nx))

    # Al cruzarse las piernas quedan bolsas de fondo que el relleno no alcanza
    # desde el borde. Se quitan por color: la sombra es gris neutro, mientras
    # que dientes y tenis son calidos (saturacion mas alta).
    sueltas, n = ndimage.label(fondo & ~bg)
    for i in range(1, n + 1):
        m = sueltas == i
        if m.sum() > 120 and mn[m].mean() > 205 and sat[m].mean() < 12:
            bg |= m

    alpha = Image.fromarray(np.where(bg, 0, 255).astype(np.uint8), 'L')
    alpha = alpha.filter(ImageFilter.GaussianBlur(0.8))
    alpha = alpha.point(lambda v: 0 if v < 110 else min(255, int(v * 1.25)))
    out = src.copy(); out.putalpha(alpha)
    caja = alpha.getbbox()
    return out.crop(caja), caja


def nombre_de(ruta):
    base = os.path.splitext(os.path.basename(ruta))[0]
    for clave, nom in CONOCIDAS.items():
        if clave in base:
            return nom
    return base.lower().replace(' ', '_')


def fuentes():
    rutas = sorted(glob.glob(os.path.join(FUENTE, '*.[jp][pn]*g')))
    rutas += sorted(glob.glob(os.path.join(AQUI, '..', 'Gemini_Generated_Image_*.jpeg')))
    return rutas


def preparar(forzar=False, hablar=True):
    os.makedirs(DESTINO, exist_ok=True)
    cat = {}
    if os.path.exists(CATALOGO) and not forzar:
        cat = json.load(open(CATALOGO, encoding='utf-8'))
    for ruta in fuentes():
        nom = nombre_de(ruta)
        png = os.path.join(DESTINO, nom + '.png')
        if nom in cat and os.path.exists(png) and not forzar:
            continue
        im, caja = recortar(ruta)
        im.save(png)
        cat[nom] = {'archivo': nom + '.png', 'w': im.width, 'h': im.height,
                    'origen': os.path.basename(ruta)}
        if hablar:
            print(f'  {nom:14s} {im.width}x{im.height}')
    json.dump(cat, open(CATALOGO, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    return cat


_cache = {}

def cargar():
    """Devuelve {nombre: PIL RGBA ya recortada}. Vacio si no hay poses."""
    if _cache:
        return _cache
    if not os.path.exists(CATALOGO):
        return {}
    cat = json.load(open(CATALOGO, encoding='utf-8'))
    for nom, d in cat.items():
        p = os.path.join(DESTINO, d['archivo'])
        if os.path.exists(p):
            _cache[nom] = Image.open(p).convert('RGBA')
    return _cache


if __name__ == '__main__':
    cat = preparar('--forzar' in sys.argv)
    print(f'{len(cat)} poses en {DESTINO}')
    for n in sorted(cat):
        print('  -', n)

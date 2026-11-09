# -*- coding: utf-8 -*-
"""Segundo método de animación: boca dibujada.

El rig normal (`avatar.Rig`) **destapa** una boca: baja la mandíbula desde la
línea entre el labio y los dientes. Eso necesita que esa línea exista, y en un
Papá Noel con barba o en un personaje de anime con la boca de una raya, no
existe.

Aquí se hace lo contrario, que es como se anima en 2D de toda la vida: se
**borra** la boca original y se **dibuja** una nueva en cada fotograma. Funciona
precisamente porque esos personajes tienen la boca pequeña y de colores planos.

Lo único que hace falta es saber dónde está la boca. El color del interior y del
contorno se sacan de la boca original, así que la boca dibujada mantiene la
paleta del personaje.
"""
import math
import os

import numpy as np
from PIL import Image, ImageDraw
from scipy import ndimage

AQUI = os.path.dirname(os.path.abspath(__file__))
RIGS = os.path.join(AQUI, 'rigs')


COMBA = 0.085       # cuanto curva la boca hacia abajo, en anchos de boca
HOLGURA = 0.10      # cuanto se agranda la mancha de boca, en anchos de recuadro
PASOS = 20          # pasadas de difusion al rellenar el hueco


def mascara_boca(a, caja):
    """Que parte del recuadro marcado es boca y que parte es su entorno.

    Borrar el recuadro entero deja un parche rectangular evidente: en Papa Noel
    se veia un trozo plano pegado sobre la barba. Asi que primero hay que saber
    que es boca.

    El criterio no mira colores concretos, que cambian de un personaje a otro,
    sino el CONTRASTE con lo que rodea al recuadro: se saca la paleta del anillo
    de alrededor y se marca como boca lo que no se parece a ninguno de esos
    colores. Vale igual para una boca roja sobre barba blanca que para una raya
    negra sobre piel de anime.

    Devuelve la mascara y si hubo que recurrir al recuadro entero.
    """
    H, W, _ = a.shape
    x0, y0, x1, y1 = caja
    dentro = np.zeros((H, W), bool)
    dentro[y0:y1, x0:x1] = True
    radio = max(int(0.12 * max(x1 - x0, y1 - y0)), 6)
    anillo = ndimage.binary_dilation(dentro, iterations=radio) & ~dentro
    if not anillo.any():
        raise ValueError('No hay alrededor suficiente para borrar la boca.')

    # paleta del entorno, en cubos gruesos de color, quedandose con los que pesan
    q = (a[anillo] // 16).astype(np.int32)
    llaves, cuenta = np.unique(q[:, 0] * 1024 + q[:, 1] * 32 + q[:, 2],
                               return_counts=True)
    vivos = llaves[cuenta >= 0.004 * anillo.sum()]
    if not len(vivos):
        vivos = llaves
    cen = (np.stack([vivos // 1024, (vivos // 32) % 32, vivos % 32], 1) * 16
           + 8).astype(np.float32)

    reg = a[y0:y1, x0:x1].reshape(-1, 3)
    lejos = np.sqrt(((reg[:, None, :] - cen[None, :, :]) ** 2).sum(2)).min(1)
    m = (lejos > 46).reshape(y1 - y0, x1 - x0)
    m = ndimage.binary_closing(m, np.ones((3, 3)), iterations=2)
    m = ndimage.binary_fill_holes(m)
    et, n = ndimage.label(m)
    if n:
        tam = ndimage.sum(m, et, range(1, n + 1))
        m = np.isin(et, [k + 1 for k in range(n) if tam[k] > 0.02 * m.size])

    plena = m.mean() < 0.02 or m.mean() > 0.92
    full = np.zeros((H, W), bool)
    if plena:
        # o no hay contraste o lo hay en todo: mejor fiarse de lo que marco
        # la persona y borrar el recuadro tal cual.
        full[y0:y1, x0:x1] = True
    else:
        full[y0:y1, x0:x1] = m
        full = ndimage.binary_dilation(
            full, iterations=max(int(HOLGURA * (x1 - x0)), 3))
    return full, plena


def analizar(rgba, caja):
    """Saca del personaje lo que hace falta para dibujarle la boca.

    Devuelve el fotograma con la boca ya borrada y los colores de su paleta.
    """
    a = np.asarray(rgba.convert('RGB')).astype(np.float32)
    H, W, _ = a.shape
    x0, y0, x1, y1 = [int(v) for v in caja]
    x0, y0 = max(x0, 0), max(y0, 0)
    x1, y1 = min(x1, W), min(y1, H)
    if x1 - x0 < 6 or y1 - y0 < 4:
        raise ValueError('La zona de la boca es demasiado pequena.')

    marca, _ = mascara_boca(a, (x0, y0, x1, y1))
    lum = a.mean(axis=2)

    # La tinta del dibujo no sirve de fuente para rellenar: se arrastraria hacia
    # dentro y dejaria un borron oscuro.
    anillo = ndimage.binary_dilation(marca, iterations=14) & ~marca
    if not anillo.any():
        raise ValueError('No hay alrededor suficiente para borrar la boca.')
    fuente = (~marca) & (lum >= np.percentile(lum[anillo], 40))
    if not fuente.any():
        raise ValueError('No hay alrededor suficiente para borrar la boca.')

    # Cada pixel tapado copia el valido mas cercano, y luego se difunde: copiar
    # a secas deja vetas horizontales, porque todos los pixeles de una fila
    # acaban clonando el mismo vecino.
    _, idx = ndimage.distance_transform_edt(~fuente, return_indices=True)
    b = a.copy()
    b[marca] = a[idx[0][marca], idx[1][marca]]
    for _ in range(PASOS):
        b[marca] = ndimage.gaussian_filter(b, (3, 3, 0))[marca]

    # el borde del parche se funde con lo de alrededor, para que no se vea el filo
    peso = ndimage.gaussian_filter(marca.astype(np.float32), 2.2)[..., None]
    b = a * (1 - peso) + b * peso

    lienzo = Image.fromarray(b.clip(0, 255).astype(np.uint8)).convert('RGBA')
    lienzo.putalpha(rgba.getchannel('A'))

    # los colores de la boca nueva salen de la vieja, no del recuadro entero
    reg = a[marca]
    if len(reg) < 12:
        reg = a[y0:y1, x0:x1].reshape(-1, 3)
    orden = np.argsort(reg.mean(axis=1))
    # El contorno se oscurece a proposito: el tono mas oscuro de una boca
    # pintada sigue siendo mas claro que la linea de tinta que la rodea, y sin
    # esto la boca nueva se ve desvaida al lado del resto del dibujo.
    contorno = np.median(reg[orden[:max(len(orden) // 10, 1)]], axis=0) * 0.55
    interior = np.median(reg[orden[:max(len(orden) // 3, 1)]], axis=0)
    # si la boca original era clara (una raya fina sobre piel) el interior sale
    # casi del color de la cara: se oscurece para que la boca abierta se vea
    if interior.mean() > 150:
        interior = interior * 0.42
    return lienzo, contorno, interior, (x0, y0, x1, y1)


class RigDibujado:
    """Mismo interfaz que `avatar.Rig`, pero dibujando la boca."""

    def __init__(self, nombre):
        d = np.load(os.path.join(RIGS, nombre + '.npz'))
        full = Image.open(os.path.join(RIGS, nombre + '.png')).convert('RGBA')
        self.nombre = nombre
        self.tipo = 'dibujada'

        sx0, sy0, sx1, sy1 = [int(v) for v in d['sujeto']]
        mx = int(0.06 * (sx1 - sx0)); my = int(0.015 * (sy1 - sy0))
        self.CROP = (max(sx0 - mx, 0), max(sy0 - my, 0),
                     min(sx1 + mx + 1, full.width), min(sy1 + my + 1, full.height))
        OX, OY = self.CROP[0], self.CROP[1]
        self.sujeto = (sx0 - OX, sy0 - OY, sx1 - OX, sy1 - OY)

        bx0, by0, bx1, by1 = [int(v) for v in d['boca']]
        self.boca = (bx0 - OX, by0 - OY, bx1 - OX, by1 - OY)
        self.contorno = tuple(int(v) for v in d['contorno'])
        self.interior = tuple(int(v) for v in d['interior'])

        self.LIENZO = full.crop(self.CROP)   # el .png guardado ya tiene la boca borrada
        self.CW, self.CH = self.LIENZO.size

        # Sin ojos medidos, la separación ocular se estima a partir del ancho de
        # la boca. Solo se usa para encuadrar el primer plano.
        an = max(bx1 - bx0, 4)
        self.sep = an / 0.75
        cx, cy = (self.boca[0] + self.boca[2]) / 2, (self.boca[1] + self.boca[3]) / 2
        self.ojos_centro = (cx, max(cy - 1.15 * an, 0))

    def _contorno_boca(self, cx, cy, aw, ah, comba):
        """Puntos del labio: dos arcos, el de arriba y el de abajo.

        Una elipse cerrada se queda en una raya recta, que sobre una cara
        dibujada se lee como un guion y no como una boca. Con los dos arcos la
        boca cerrada es una linea curvada, que es como se dibuja de verdad.
        """
        N = 30
        arriba, abajo = [], []
        for k in range(N + 1):
            t = -1.0 + 2.0 * k / N
            media = cy + comba * (1.0 - t * t)
            alto = (ah / 2.0) * math.sqrt(max(1.0 - t * t, 0.0))
            x = cx + t * aw / 2.0
            arriba.append((x, media - alto))
            abajo.append((x, media + alto))
        return arriba + abajo[::-1]

    def base_frame(self, d_jaw=0.0, e_brow=0.0, k_blink=0.0, tilt=0.0,
                   w_mouth=1.0, c_close=0.0):
        im = self.LIENZO.copy()
        d = ImageDraw.Draw(im, 'RGBA')
        x0, y0, x1, y1 = self.boca
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2

        # d_jaw viene en las unidades del otro rig (0-19); aqui es apertura 0-1
        ap = min(max(d_jaw / 19.0, 0.0), 1.0) * (1.0 - min(c_close, 1.0))
        an = min(max(w_mouth, 0.45), 1.25)
        aw = (x1 - x0) * 0.88 * an
        ah = (y1 - y0) * 0.94 * max(ap, 0.02)
        grosor = max(2, int(round((x1 - x0) * 0.035)))
        comba = COMBA * aw * (1.0 - 0.45 * ap)   # al abrir, la sonrisa se endereza

        pts = self._contorno_boca(cx, cy, aw, ah, comba)
        d.polygon(pts, fill=self.interior)
        d.line(pts + [pts[0]], fill=self.contorno, width=grosor, joint='curve')

        if ap > 0.45:                                 # lengua al fondo
            lw, lh = aw * 0.62, ah * 0.42
            leng = tuple(min(int(v * 1.35 + 40), 255) for v in self.interior)
            d.ellipse([cx - lw / 2, cy + comba + ah / 2 - lh * 1.05,
                       cx + lw / 2, cy + comba + ah / 2 - lh * 0.05], fill=leng)
        if abs(tilt) > 0.01:
            im = im.rotate(tilt, resample=Image.BILINEAR,
                           center=(self.CW / 2, self.CH * 0.93))
        return im

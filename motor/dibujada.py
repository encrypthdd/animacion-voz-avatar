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
from PIL import Image, ImageDraw, ImageFilter
from scipy import ndimage

AQUI = os.path.dirname(os.path.abspath(__file__))
RIGS = os.path.join(AQUI, 'rigs')


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
        raise ValueError('La zona de la boca es demasiado pequeña.')

    lum = a.mean(axis=2)
    marca = np.zeros((H, W), bool)
    marca[y0:y1, x0:x1] = True

    # La tinta del dibujo no sirve de fuente para rellenar: se arrastraría
    # hacia dentro y dejaría un borrón oscuro.
    anillo = ndimage.binary_dilation(marca, iterations=14) & ~marca
    tinta = lum < np.percentile(lum[anillo], 40)
    fuente = (~marca) & (~tinta)
    if not fuente.any():
        raise ValueError('No hay alrededor suficiente para borrar la boca.')

    # cada píxel de la boca copia el píxel válido más cercano
    _, idx = ndimage.distance_transform_edt(~fuente, return_indices=True)
    b = a.copy()
    b[marca] = a[idx[0][marca], idx[1][marca]]

    lienzo = Image.fromarray(b.clip(0, 255).astype(np.uint8)).convert('RGBA')
    lienzo.putalpha(rgba.getchannel('A'))
    sello = Image.new('L', (W, H), 0)
    ImageDraw.Draw(sello).rectangle([x0 - 3, y0 - 3, x1 + 3, y1 + 3], fill=255)
    lienzo = Image.composite(lienzo.filter(ImageFilter.GaussianBlur(1.8)), lienzo, sello)

    reg = a[y0:y1, x0:x1].reshape(-1, 3)
    orden = np.argsort(reg.mean(axis=1))
    contorno = np.median(reg[orden[:max(len(orden) // 20, 1)]], axis=0)
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

    def base_frame(self, d_jaw=0.0, e_brow=0.0, k_blink=0.0, tilt=0.0,
                   w_mouth=1.0, c_close=0.0):
        im = self.LIENZO.copy()
        d = ImageDraw.Draw(im, 'RGBA')
        x0, y0, x1, y1 = self.boca
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2

        # d_jaw viene en las unidades del otro rig (0-19); aquí es apertura 0-1
        ap = min(max(d_jaw / 19.0, 0.0), 1.0) * (1.0 - min(c_close, 1.0))
        an = min(max(w_mouth, 0.45), 1.25)
        aw = (x1 - x0) * 0.88 * an
        ah = (y1 - y0) * 0.94 * max(ap, 0.035)
        grosor = max(2, int(round((x1 - x0) * 0.035)))
        d.ellipse([cx - aw / 2, cy - ah / 2, cx + aw / 2, cy + ah / 2],
                  fill=self.interior, outline=self.contorno, width=grosor)
        if ap > 0.45:                                 # lengua al fondo
            lw, lh = aw * 0.62, ah * 0.42
            leng = tuple(min(int(v * 1.35 + 40), 255) for v in self.interior)
            d.ellipse([cx - lw / 2, cy + ah / 2 - lh * 1.05,
                       cx + lw / 2, cy + ah / 2 - lh * 0.05], fill=leng)
        if abs(tilt) > 0.01:
            im = im.rotate(tilt, resample=Image.BILINEAR,
                           center=(self.CW / 2, self.CH * 0.93))
        return im

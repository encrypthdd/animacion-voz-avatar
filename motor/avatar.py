# -*- coding: utf-8 -*-
"""Rig del avatar, parametrizado por las medidas de `medir.py`.

Nada esta fijado a un personaje concreto: todas las coordenadas salen del .npz
y todas las amplitudes se escalan con la separacion ocular, de modo que una
apertura de boca de 17 "unidades" significa lo mismo en una cabeza grande que en
una pequena.
"""
import math, os
import numpy as np
from PIL import Image

AQUI = os.path.dirname(os.path.abspath(__file__))
RIGS = os.path.join(AQUI, 'rigs')

SEP_REF = 119.0          # separacion ocular del personaje de referencia
CAV_D = np.array([52, 18, 20], np.float32)
CAV_T = np.array([148, 66, 62], np.float32)
LASH = np.array([70, 40, 28], np.float32)


class Rig:
    def __init__(self, nombre, margen=0.06):
        d = np.load(os.path.join(RIGS, nombre + '.npz'))
        full = Image.open(os.path.join(RIGS, nombre + '.png')).convert('RGBA')
        self.nombre = nombre
        sx0, sy0, sx1, sy1 = [int(v) for v in d['sujeto']]
        mx = int(margen * (sx1 - sx0)); my = int(margen * (sy1 - sy0) * 0.25)
        self.CROP = (max(sx0 - mx, 0), max(sy0 - my, 0),
                     min(sx1 + mx + 1, full.width), min(sy1 + my + 1, full.height))
        OX, OY = self.CROP[0], self.CROP[1]
        self.OX, self.OY = OX, OY
        self.BASE = np.asarray(full.crop(self.CROP)).astype(np.float32)
        self.CH, self.CW, _ = self.BASE.shape
        self.sujeto = (sx0 - OX, sy0 - OY, sx1 - OX, sy1 - OY)

        self.sep = float(d['eye_sep'])
        self.esc = self.sep / SEP_REF           # escala de todas las amplitudes

        self._IDX_X = np.broadcast_to(np.arange(self.CW), (self.CH, self.CW))
        self._mandibula(d)
        self._cierre(d)
        self._ancho()
        self._cejas(d)
        self._parpados(d)
        self.ojos_centro = self._centro_ojos()

    # ------------------------------------------------------------ utilidades
    def _warp(self, buf, y0, y1, x0, x1, sy):
        sub = buf[y0:y1, x0:x1]
        r = np.clip(sy - y0, 0, (y1 - y0) - 1)
        i0 = np.floor(r).astype(np.int32); i1 = np.minimum(i0 + 1, (y1 - y0) - 1)
        f = (r - i0)[..., None]
        cols = np.arange(x1 - x0)
        return sub[i0, cols] * (1 - f) + sub[i1, cols] * f

    def _warp_x(self, buf, y0, y1, x0, x1, sx):
        sub = buf[y0:y1, x0:x1]
        c = np.clip(sx - x0, 0, (x1 - x0) - 1)
        i0 = np.floor(c).astype(np.int32); i1 = np.minimum(i0 + 1, (x1 - x0) - 1)
        f = (c - i0)[..., None]
        rows = np.arange(y1 - y0)[:, None]
        return sub[rows, i0] * (1 - f) + sub[rows, i1] * f

    # ------------------------------------------------------------ mandibula
    def _mandibula(self, d):
        self.MLX0 = int(d['mouth_x0']) - self.OX
        self.MLX1 = int(d['mouth_x1']) - self.OX
        mline = d['mouth_line'].astype(np.float32) - self.OY
        self.mtop = d['mouth_top'].astype(np.float32) - self.OY
        self.JAW_BOT = float(d['chin']) - self.OY
        self.NECK_K = 0.55 * self.sep

        self.JY0 = max(int(mline.min()) - 30, 0)
        self.JY1 = min(int(self.JAW_BOT + self.NECK_K) + 3, self.CH)
        self.JX0 = max(self.MLX0 - 10, 0)
        self.JX1 = min(self.MLX1 + 10, self.CW)

        self._jy = np.arange(self.JY0, self.JY1, dtype=np.float32)[:, None]
        self._jxi = np.arange(self.JX0, self.JX1)
        cols = np.arange(self.MLX0, self.MLX1)
        self.LINE = np.interp(self._jxi, cols, mline).astype(np.float32)[None, :]
        # perfil de apertura: meseta y coseno alzado. sqrt(1-t^2) tiene pendiente
        # infinita en el borde y dejaba una escalera de puntos en la comisura
        c, h = (self.MLX0 + self.MLX1) / 2.0, (self.MLX1 - self.MLX0) / 2.0
        t = np.clip(np.abs(self._jxi - c) / max(h, 1), 0, 1)
        tp = np.clip((t - 0.5) / 0.5, 0, 1)
        self.WX = np.where(t <= 0.5, 1.0, 0.5 * (1 + np.cos(np.pi * tp))
                           ).astype(np.float32)[None, :]

    def jaw(self, buf, d):
        d = d * self.esc
        if d <= 0.05:
            return
        de = d * self.WX
        _jy, LINE = self._jy, self.LINE
        sy = _jy + np.zeros_like(LINE)
        jw = (_jy >= LINE + de) & (_jy < self.JAW_BOT + de)
        nk = (_jy >= self.JAW_BOT + de) & (_jy < self.JAW_BOT + self.NECK_K)
        sy = np.where(jw, _jy - de, sy)
        sy = np.where(nk, self.JAW_BOT + (_jy - self.JAW_BOT - de) * self.NECK_K
                      / np.maximum(self.NECK_K - de, 1e-3), sy)
        out = self._warp(buf, self.JY0, self.JY1, self.JX0, self.JX1, sy)
        # cerca de la comisura la cavidad mide menos de un pixel y el alfa
        # fraccionario dejaba puntos naranjas: ahi se apaga
        ca = (np.clip(_jy - LINE, 0, 1) * np.clip(LINE + de - _jy, 0, 1)
              * np.clip(de / 2.5, 0, 1))[..., None]
        t = np.clip((_jy - LINE) / np.maximum(de, 1e-3), 0, 1)
        m = np.clip((t - 0.58) / 0.42, 0, 1); m = (m * m * (3 - 2 * m))[..., None]
        sh = (0.50 + 0.50 * np.clip(t / 0.28, 0, 1))[..., None]
        cav = (CAV_D * (1 - m) + CAV_T * m) * sh
        out[..., :3] = out[..., :3] * (1 - ca) + cav * ca
        out[..., 3:] = np.maximum(out[..., 3:], ca * 255.0)
        borde = LINE + de
        sb = (np.clip(1.0 - (_jy - borde) / (0.06 * self.sep), 0, 1) * (_jy > borde))[..., None]
        out[..., :3] *= (1.0 - 0.45 * sb * float(min(d / (19 * self.esc), 1.0)))
        buf[self.JY0:self.JY1, self.JX0:self.JX1] = out

    # ------------------------------------------------------------ cierre de labios
    def _cierre(self, d):
        cols = np.arange(self.MLX0, self.MLX1)
        self.TOP_C = np.interp(self._jxi, cols, self.mtop).astype(np.float32)[None, :]
        self.ULT = self.TOP_C - 0.115 * self.sep
        self.ABS_A0 = self.ULT - 0.27 * self.sep
        self.CY0 = max(int(self.ABS_A0.min()) - 3, 0)
        self.CY1 = min(int(self.JAW_BOT) + 5, self.CH)
        self._cy = np.arange(self.CY0, self.CY1, dtype=np.float32)[:, None]
        cf = (np.clip((self._jxi - self.MLX0) / 18.0, 0, 1)
              * np.clip((self.MLX1 - self._jxi) / 18.0, 0, 1))
        self.CFE = (cf * cf * (3 - 2 * cf)).astype(np.float32)[None, :]

    def close(self, buf, c):
        """El labio superior baja hasta tapar el diente (M, B, P)."""
        if c <= 0.01:
            return
        LINE, TOP_C, _cy = self.LINE, self.TOP_C, self._cy
        sh = c * (LINE - TOP_C + 0.03 * self.sep) * self.CFE
        sy = _cy + np.zeros_like(LINE)
        absorb = (_cy >= self.ABS_A0) & (_cy < self.ULT + sh)
        lip = (_cy >= self.ULT + sh) & (_cy < TOP_C + sh)
        teeth = (_cy >= TOP_C + sh) & (_cy < LINE)
        sy = np.where(absorb, self.ABS_A0 + (_cy - self.ABS_A0) * (self.ULT - self.ABS_A0)
                      / np.maximum(self.ULT + sh - self.ABS_A0, 1e-3), sy)
        sy = np.where(lip, _cy - sh, sy)
        sy = np.where(teeth, TOP_C + (_cy - TOP_C - sh) * (LINE - TOP_C)
                      / np.maximum(LINE - TOP_C - sh, 1e-3), sy)
        out = self._warp(buf, self.CY0, self.CY1, self.JX0, self.JX1, sy)
        band = (np.clip((_cy - (TOP_C + sh)) / 1.8, 0, 1)
                * np.clip((LINE - _cy) / 1.8, 0, 1))[..., None]
        out[..., :3] *= (1.0 - 0.42 * c * band)
        buf[self.CY0:self.CY1, self.JX0:self.JX1] = out

    # ------------------------------------------------------------ ancho de boca
    def _ancho(self):
        self.WY0 = max(int(self.LINE.min() - 0.28 * self.sep), 0)
        self.WY1 = min(int(self.LINE.max() + 0.30 * self.sep), self.CH)
        self.WXA = max(int(self.MLX0 - 0.26 * self.sep), 0)
        self.WXB = min(int(self.MLX1 + 0.26 * self.sep), self.CW)
        _wy = np.arange(self.WY0, self.WY1, dtype=np.float32)[:, None]
        self._wxc = np.arange(self.WXA, self.WXB, dtype=np.float32)[None, :]
        self._mcx = (self.MLX0 + self.MLX1) / 2.0
        wv = np.clip(np.minimum((_wy - self.WY0) / 14.0, (self.WY1 - 1 - _wy) / 16.0), 0, 1)
        wv = wv * wv * (3 - 2 * wv)
        r = 0.93 * self.sep
        wh = np.clip((r - np.abs(self._wxc - self._mcx)) / (0.40 * self.sep), 0, 1)
        wh = wh * wh * (3 - 2 * wh)
        self.WWT = (wv * wh).astype(np.float32)

    def width(self, buf, w):
        if abs(w - 1.0) < 0.004:
            return
        sx = self._wxc + (self._wxc - self._mcx) * (1.0 / w - 1.0) * self.WWT
        buf[self.WY0:self.WY1, self.WXA:self.WXB] = self._warp_x(
            buf, self.WY0, self.WY1, self.WXA, self.WXB, sx)

    # ------------------------------------------------------------ cejas
    def _cejas(self, d):
        self.BT = float(d['brow_y0']) - self.OY
        self.BB = float(d['brow_y1']) - self.OY
        self.FORE_K = 0.51 * self.sep
        self.LID_K = 0.07 * self.sep
        bx0 = float(d['brow_x0']) - self.OX
        bx1 = float(d['brow_x1']) - self.OX
        self.BY0 = max(int(self.BT - self.FORE_K) - 2, 0)
        self.BY1 = min(int(self.BB + self.LID_K) + 2, self.CH)
        self.BX0 = max(int(bx0) - 12, 0)
        self.BX1 = min(int(bx1) + 12, self.CW)
        self._by = np.arange(self.BY0, self.BY1, dtype=np.float32)[:, None]
        _bx = np.arange(self.BX0, self.BX1, dtype=np.float32)[None, :]
        self.BW = (np.clip((_bx - bx0) / 14, 0, 1) * np.clip((bx1 - _bx) / 14, 0, 1)
                   ).astype(np.float32)

    def brow(self, buf, e):
        e = e * self.esc
        if e <= 0.05:
            return
        ee = e * self.BW
        _by, BT, BB = self._by, self.BT, self.BB
        sy = _by + np.zeros_like(self.BW)
        up = (_by >= BT - ee) & (_by < BB - ee)
        fore = (_by >= BT - self.FORE_K) & (_by < BT - ee)
        lid = (_by >= BB - ee) & (_by < BB + self.LID_K)
        sy = np.where(up, _by + ee, sy)
        sy = np.where(fore, BT - self.FORE_K + (_by - (BT - self.FORE_K)) * self.FORE_K
                      / np.maximum(self.FORE_K - ee, 1e-3), sy)
        sy = np.where(lid, BB + (_by - BB + ee) * self.LID_K
                      / np.maximum(self.LID_K + ee, 1e-3), sy)
        buf[self.BY0:self.BY1, self.BX0:self.BX1] = self._warp(
            buf, self.BY0, self.BY1, self.BX0, self.BX1, sy)

    # ------------------------------------------------------------ parpados
    def _parpados(self, d):
        from PIL import ImageFilter
        self._ojos = []
        for clave in ('eye_izq', 'eye_der'):
            m = d[clave][self.OY:self.OY + self.CH, self.OX:self.OX + self.CW]
            cols = np.nonzero(m.any(axis=0))[0]
            if len(cols) == 0:
                continue
            x0, x1 = cols.min(), cols.max() + 1
            rows = np.nonzero(m.any(axis=1))[0]
            y0, y1 = rows.min(), rows.max() + 1
            sub = m[y0:y1, x0:x1]
            top = np.array([np.nonzero(sub[:, i])[0].min() + y0 for i in range(x1 - x0)], np.float32)
            bot = np.array([np.nonzero(sub[:, i])[0].max() + y0 for i in range(x1 - x0)], np.float32)
            g = np.exp(-(np.arange(-6, 7) ** 2) / (2 * 2.6 ** 2)); g /= g.sum()
            top = np.convolve(np.pad(top, 6, mode='edge'), g, 'valid').astype(np.float32)
            bot = np.convolve(np.pad(bot, 6, mode='edge'), g, 'valid').astype(np.float32)
            soft = np.asarray(Image.fromarray((sub * 255).astype(np.uint8), 'L')
                              .filter(ImageFilter.GaussianBlur(2.0)), np.float32) / 255.0
            nc = x1 - x0
            colw = (np.clip(np.arange(nc) / 5.0, 0, 1)
                    * np.clip((nc - 1 - np.arange(nc)) / 5.0, 0, 1)).astype(np.float32)
            src = np.clip(bot + 0.08 * self.sep, 0, self.CH - 1).astype(np.int32)
            raw = self.BASE[src, np.arange(x0, x1)][:, :3]
            ker = np.ones(15) / 15.0
            sm = np.stack([np.convolve(np.pad(raw[:, c], 7, mode='edge'), ker, 'valid')
                           for c in range(3)], 1)
            self._ojos.append((soft, colw, y0, y1, x0, x1, top, bot,
                               (sm * 1.03).astype(np.float32)))

    def blink(self, buf, k):
        if k <= 0.01:
            return
        for soft, colw, y0, y1, x0, x1, top, bot, lidcol in self._ojos:
            ly = (top + k * (bot - top))[None, :]
            yy = np.arange(y0, y1, dtype=np.float32)[:, None]
            reg = buf[y0:y1, x0:x1]
            a = (soft * np.clip(ly - yy + 0.5, 0, 1))[..., None]
            depth = np.clip((yy - top[None, :]) / np.maximum(bot - top, 1)[None, :], 0, 1)[..., None]
            lid = lidcol[None, :, :] * (1.0 - 0.13 * depth)
            reg[..., :3] = reg[..., :3] * (1 - a) + lid * a
            reg[..., 3:] = np.maximum(reg[..., 3:], a * 255.0)
            cr = (colw[None, :] * np.clip(1.0 - np.abs(yy - (ly - 3.0)) / 3.0, 0, 1))[..., None] * (0.16 * k)
            reg[..., :3] = reg[..., :3] * (1 - cr) + lidcol[None, :, :] * 0.72 * cr
            lash = (colw[None, :] * np.clip(1.8 - np.abs(yy - ly), 0, 1))[..., None] * (k ** 0.45)
            reg[..., :3] = reg[..., :3] * (1 - lash) + LASH * lash
            reg[..., 3:] = np.maximum(reg[..., 3:], lash * 255.0)

    # ------------------------------------------------------------ salida
    def _centro_ojos(self):
        xs, ys = [], []
        for _, _, y0, y1, x0, x1, top, bot, _ in self._ojos:
            xs.append((x0 + x1) / 2.0); ys.append((top.mean() + bot.mean()) / 2.0)
        if not xs:
            return self.CW / 2.0, self.CH * 0.2
        return float(np.mean(xs)), float(np.mean(ys))

    def base_frame(self, d_jaw=0.0, e_brow=0.0, k_blink=0.0, tilt=0.0,
                   w_mouth=1.0, c_close=0.0):
        """Personaje a resolucion base. La camara recorta y escala despues solo
        la parte visible, asi un primer plano no cuesta mas que uno abierto."""
        buf = self.BASE.copy()
        self.close(buf, c_close); self.jaw(buf, d_jaw); self.width(buf, w_mouth)
        self.brow(buf, e_brow); self.blink(buf, k_blink)
        im = Image.fromarray(buf.clip(0, 255).astype(np.uint8), 'RGBA')
        if abs(tilt) > 0.01:
            im = im.rotate(tilt, resample=Image.BILINEAR,
                           center=(self.CW / 2, self.CH * 0.93))
        return im


_cache = {}

def cargar(nombre='base'):
    if nombre not in _cache:
        _cache[nombre] = Rig(nombre)
    return _cache[nombre]


def disponibles():
    if not os.path.isdir(RIGS):
        return []
    return sorted(f[:-4] for f in os.listdir(RIGS)
                  if f.endswith('.npz') and os.path.exists(os.path.join(RIGS, f[:-4] + '.png')))

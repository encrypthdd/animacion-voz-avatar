# -*- coding: utf-8 -*-
"""Extrae el borde real de la boca columna por columna.

Dos bordes:
  line = costura inferior del diente (donde empieza la banda movil de la mandibula)
  top  = borde superior del diente  (hasta donde debe bajar el labio en M/B/P)

Los dientes tienen filo festoneado (~0.7 px de media, hasta 4.2 px). Hay que
rebajar ese feston sin tocar la curva de la sonrisa, que llega a tener 1.7 px de
pendiente por columna: una envolvente directa confunde feston con pendiente y
arrastra la linea hasta 13 px. Por eso se separa tendencia de residuo, y la
envolvente se aplica SOLO al residuo.
"""
import numpy as np
from PIL import Image, ImageDraw

X0, X1 = 352, 498          # comisuras reales
YA, YB = 362, 428

im = Image.open('carlos_rgba.png').convert('RGB')
A = np.asarray(im).astype(float)
lum = A.mean(axis=2)
R2, B2 = A[:, :, 0], A[:, :, 2]
es_diente = (lum > 150) & ((R2 - B2) < 60)
xs = np.arange(X0, X1)

_g = np.exp(-(np.arange(-7, 8) ** 2) / (2 * 3.0 ** 2)); _g /= _g.sum()
def tendencia(c):
    return np.convolve(np.pad(c, 7, mode='edge'), _g, 'valid')

def envolvente(c, R, hacia_abajo):
    """Envolvente del feston, sin arrastrar la pendiente de la sonrisa."""
    t = tendencia(c)
    res = c - t
    p = np.pad(res, R, mode='edge')
    e = np.array([(p[i:i+2*R+1].max() if hacia_abajo else p[i:i+2*R+1].min())
                  for i in range(len(res))])
    return tendencia(t + e)

# ---- costura inferior del diente ----
raw = np.zeros(len(xs))
for i, x in enumerate(xs):
    seg = lum[YA:YB, x]
    yd = int(np.argmin(seg))
    thr = max(seg.min() + 45, 72)
    y = yd
    while y > 0 and seg[y-1] < thr:
        y -= 1
    raw[i] = y + YA
line = envolvente(raw, 5, True)

# ---- borde superior del diente ----
raw_t = np.zeros(len(xs))
for i, x in enumerate(xs):
    lo = int(round(line[i])); hi = max(lo - 36, 0)
    col = es_diente[hi:lo, x]
    mejor, ini = (0, lo), None
    for j in range(len(col) + 1):
        on = j < len(col) and col[j]
        if on and ini is None: ini = j
        elif not on and ini is not None:
            if j - ini > mejor[0]: mejor = (j - ini, hi + ini)
            ini = None
    raw_t[i] = mejor[1] if mejor[0] >= 3 else lo
top = np.minimum(envolvente(raw_t, 4, False), line)

print('desplazamiento de la envolvente: %.2f px de media (max %.2f)'
      % ((line - raw).mean(), (line - raw).max()))
print('comisuras x %d-%d | costura y %.1f -> %.1f  (arco %.1f px)'
      % (X0, X1, line.min(), line.max(), line.max() - line.min()))
print('alto de diente: %.1f px (centro) | %.1f px (comisura)'
      % ((line - top)[len(top)//2], (line - top)[3]))

np.savez('mouth_line.npz', x0=X0, x1=X1, line=line, top=top)

# verificacion: verde = costura, magenta = borde superior del diente
chk = im.copy(); d = ImageDraw.Draw(chk)
d.point([(int(x), int(round(y))) for x, y in zip(xs, line)], fill=(0, 255, 0))
d.point([(int(x), int(round(y))) for x, y in zip(xs, top)],  fill=(255, 0, 255))
chk.crop((335, 355, 515, 425)).resize((900, 350), Image.NEAREST).save('mouthline_check.png')

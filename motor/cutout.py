import numpy as np
from PIL import Image, ImageFilter
from collections import deque

src = Image.open(r'G:\Imagenes\IA\Carlos\yo.jpeg').convert('RGB')
a = np.asarray(src).astype(np.int16)
h, w, _ = a.shape

# "casi blanco" = los 3 canales altos y poca saturacion
near_white = (a.min(axis=2) > 228) & ((a.max(axis=2) - a.min(axis=2)) < 26)

# flood fill desde los bordes: solo quita blanco CONECTADO al exterior,
# asi los dientes y los tenis blancos se conservan
bg = np.zeros((h, w), bool)
dq = deque()
for x in range(w):
    for y in (0, h - 1):
        if near_white[y, x] and not bg[y, x]:
            bg[y, x] = True; dq.append((y, x))
for y in range(h):
    for x in (0, w - 1):
        if near_white[y, x] and not bg[y, x]:
            bg[y, x] = True; dq.append((y, x))
while dq:
    y, x = dq.popleft()
    for dy, dx in ((1,0),(-1,0),(0,1),(0,-1)):
        ny, nx = y+dy, x+dx
        if 0 <= ny < h and 0 <= nx < w and near_white[ny, nx] and not bg[ny, nx]:
            bg[ny, nx] = True; dq.append((ny, nx))

alpha = Image.fromarray(np.where(bg, 0, 255).astype(np.uint8), 'L')
alpha = alpha.filter(ImageFilter.GaussianBlur(0.8))          # suaviza el borde
alpha = alpha.point(lambda v: 0 if v < 110 else min(255, int(v * 1.25)))

out = src.copy(); out.putalpha(alpha)
bbox = alpha.getbbox()
out.save('carlos_rgba.png')
print('recortado ->', out.size, '| bbox sujeto:', bbox)
print('pixeles de fondo eliminados: %.1f%%' % (100 * bg.sum() / bg.size))

# vista previa sobre fondo oscuro para revisar el borde
chk = Image.new('RGB', out.size, (24, 26, 34)); chk.paste(out, (0, 0), out)
chk.resize((out.size[0]//2, out.size[1]//2), Image.LANCZOS).save('cutout_check.png')

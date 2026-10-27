import numpy as np
from PIL import Image, ImageFilter

im = Image.open('carlos_rgba.png').convert('RGB')
A = np.asarray(im).astype(int)
R, B = A[:,:,0], A[:,:,2]
skin = (R - B > 72) & (R > 140)
eye = ~skin

EYES = {'izq': (336, 244, 410, 306), 'der': (449, 244, 528, 306)}

def runs(col, y0, y1, minlen=3):
    out, s = [], None
    for y in range(y0, y1 + 1):
        on = y < y1 and col[y]
        if on and s is None: s = y
        elif not on and s is not None:
            if y - s >= minlen: out.append((s, y))
            s = None
    return out

def merged_span(col, y0, y1, maxgap=5):
    rs = runs(col, y0, y1)
    if not rs: return None
    groups, cur = [], [rs[0]]
    for a, b in rs[1:]:
        if a - cur[-1][1] <= maxgap: cur.append((a, b))
        else: groups.append(cur); cur = [(a, b)]
    groups.append(cur)
    g = max(groups, key=lambda G: G[-1][1] - G[0][0])
    return g[0][0], g[-1][1]

masks = {}
for name, (x0, y0, x1, y1) in EYES.items():
    m = np.zeros(A.shape[:2], bool)
    for x in range(x0, x1):
        sp = merged_span(eye[:, x], y0, y1)
        if sp and sp[1] - sp[0] >= 8:
            m[sp[0]:sp[1], x] = True
    mi = Image.fromarray((m * 255).astype(np.uint8), 'L').filter(ImageFilter.MaxFilter(5))
    masks[name] = np.asarray(mi) > 127
    ys, xs = np.nonzero(masks[name])
    print(f'{name}: x {xs.min()}-{xs.max()} y {ys.min()}-{ys.max()} | {masks[name].sum()} px')

np.save('eye_masks.npy', np.stack([masks['izq'], masks['der']]))
ar = np.asarray(im).copy()
ar[masks['izq']] = [0, 255, 0]; ar[masks['der']] = [255, 0, 255]
Image.fromarray(ar).crop((310, 220, 560, 330)).resize((1000, 440), Image.NEAREST).save('eyemask_check.png')
print('ok')

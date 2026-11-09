# -*- coding: utf-8 -*-
"""Mide automaticamente los rasgos de un personaje para poder animarlo.

    python medir.py imagen.png [nombre]

Produce `rigs/<nombre>.npz` con el recorte y las medidas que necesita el rig:
comisuras y borde de la boca, borde superior del diente, mascaras de los ojos,
banda de las cejas y barbilla. Deja tambien `rigs/<nombre>_check.png` para
revisar a ojo: una medida mal tomada se nota en todos los videos.
"""
import os, sys
from collections import deque
import numpy as np
from PIL import Image, ImageDraw, ImageFilter
from scipy import ndimage

AQUI = os.path.dirname(os.path.abspath(__file__))
RIGS = os.path.join(AQUI, 'rigs')


# Una boca más estrecha que esto respecto a la separación de los ojos no es una
# boca: es otra cosa que se le parece. Medido: en los personajes que funcionan
# sale entre 1.7 y 1.9 veces.
MIN_BOCA = 0.55
# Cuánto puede desviarse el centro de la boca del centro de los ojos.
MAX_DESVIO = 0.35


class NoMedible(Exception):
    pass


# ---------------------------------------------------------------- recorte
def recortar(ruta):
    """Quita fondo plano y sombra de suelo. Devuelve RGBA sin recortar la caja."""
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

    # Bolsas de fondo que el relleno no alcanza desde el borde: la sombra del
    # suelo entre las piernas, por ejemplo. Se quitan por color, porque la
    # sombra es gris neutro y los dientes o los tenis son cálidos.
    #
    # El tope de tamaño NO es opcional: sin él esto se come una barba blanca o
    # un ribete de piel, que también son zonas neutras grandes y encerradas.
    sueltas, n = ndimage.label(fondo & ~bg)
    tope = 0.02 * (~bg).sum()
    for i in range(1, n + 1):
        m = sueltas == i
        if 120 < m.sum() < tope and mn[m].mean() > 205 and sat[m].mean() < 12:
            bg |= m

    alpha = Image.fromarray(np.where(bg, 0, 255).astype(np.uint8), 'L')
    alpha = alpha.filter(ImageFilter.GaussianBlur(0.8))
    alpha = alpha.point(lambda v: 0 if v < 110 else min(255, int(v * 1.25)))
    out = src.copy(); out.putalpha(alpha)
    return out, np.asarray(alpha) > 110


# ---------------------------------------------------------------- ojos
def candidatos_ojos(a, suj):
    """Parejas candidatas a ojos, de más a menos plausible.

    Busca el ojo por su ESTRUCTURA, no por el color de alrededor.

    La versión anterior exigía que el ojo fuera una isla rodeada de piel, con
    umbrales de tono humano. Eso descarta a Papá Noel —ojos rodeados de barba
    blanca— y a cualquier personaje que no sea de color carne, como Sonic.

    Lo que sí tienen todos los ojos dibujados: una zona clara y poco saturada
    (la esclerótica) con una zona oscura dentro o pegada (el iris). Esa pareja
    es lo que se busca aquí. La esclerótica se dilata antes de agrupar porque
    el iris la parte en dos medialunas que ningún filtro de forma aceptaría.
    """
    lum = a.mean(axis=2)
    R, B = a[:, :, 0], a[:, :, 2]
    ys, xs = np.nonzero(suj)
    y0, y1, x0, x1 = ys.min(), ys.max(), xs.min(), xs.max()
    alto, ancho = y1 - y0, x1 - x0
    cabeza = slice(y0, y0 + int(alto * 0.5))
    area_cabeza = ancho * alto * 0.5

    claro = (lum > 140) & (np.abs(R - B) < 60) & suj
    oscuro = (lum < 110) & suj
    for m in (claro, oscuro):
        m[:cabeza.start, :] = False
        m[cabeza.stop:, :] = False

    # el iris parte la esclerótica en dos: se cierra el hueco antes de agrupar
    radio = max(2, int(0.012 * alto))
    unido = ndimage.binary_closing(claro, np.ones((radio * 2 + 1,) * 2))
    lab, n = ndimage.label(unido)

    blobs = []
    for i in range(1, n + 1):
        m = lab == i
        area = int(m.sum())
        if area < max(60, 0.00025 * area_cabeza) or area > 0.05 * area_cabeza:
            continue
        yy, xx = np.nonzero(m)
        an, al = xx.max() - xx.min() + 1, yy.max() - yy.min() + 1
        if not (0.45 <= an / al <= 3.4):
            continue
        # La pupila tiene que estar DENTRO de la esclerótica, no al lado: el
        # cierre de antes ya rellenó el hueco del iris. Aceptando "pegada" se
        # colaban los brillos del pelo, que lindan con su contorno oscuro.
        dentro = (oscuro & m).sum()
        if dentro < 0.06 * area:
            continue
        blobs.append(dict(m=m, n=area, cx=xx.mean(), cy=yy.mean(), an=an, al=al))
    if len(blobs) < 2:
        raise NoMedible(f'solo {len(blobs)} candidatos a ojo')

    parejas = []
    for i in range(len(blobs)):
        for j in range(i + 1, len(blobs)):
            A, Bc = blobs[i], blobs[j]
            sep = abs(A['cx'] - Bc['cx'])
            if sep < 0.7 * max(A['an'], Bc['an']) or sep > 0.75 * ancho:
                continue
            razon = max(A['n'], Bc['n']) / min(A['n'], Bc['n'])
            if razon > 3.2:
                continue
            alt_med = (A['cy'] + Bc['cy']) / 2 - y0
            p = (abs(A['cy'] - Bc['cy']) / max(sep, 1)     # a la misma altura
                 + 0.25 * razon                            # del mismo tamaño
                 + 0.3 * alt_med / alto)                   # algo más arriba, mejor
            parejas.append((p, tuple(sorted((A, Bc), key=lambda d: d['cx']))))
    if not parejas:
        raise NoMedible('no hay pareja de ojos plausible')
    parejas.sort(key=lambda t: t[0])
    return [par for _, par in parejas]


def detectar_ojos(a, suj):
    return candidatos_ojos(a, suj)[0]


def mascara_ojo(a, suj, blob):
    """Abertura del ojo, a partir del blob ya detectado.

    Se rellena por columnas entre el borde superior e inferior del blob: así
    entra el iris, que es oscuro y por tanto no formaba parte de la esclerótica.
    No se usa ningún umbral de color de piel, para que valga con cualquier
    personaje.
    """
    m0 = blob['m']
    yy, xx = np.nonzero(m0)
    x0, x1 = xx.min(), xx.max() + 1
    m = np.zeros(a.shape[:2], bool)
    for x in range(x0, x1):
        col = np.nonzero(m0[:, x])[0]
        if len(col):
            m[col.min():col.max() + 1, x] = True
    radio = max(1, int(round(0.06 * (x1 - x0))))
    mi = Image.fromarray((m * 255).astype(np.uint8), 'L').filter(
        ImageFilter.MaxFilter(radio * 2 + 1))
    return (np.asarray(mi) > 127) & suj


# ---------------------------------------------------------------- boca
def _tendencia(c, sig=3.0):
    g = np.exp(-(np.arange(-7, 8) ** 2) / (2 * sig * sig)); g /= g.sum()
    return np.convolve(np.pad(c, 7, mode='edge'), g, 'valid')


def _envolvente(c, R, hacia_abajo):
    """Envolvente del feston sin arrastrar la pendiente de la sonrisa."""
    t = _tendencia(c)
    res = c - t
    p = np.pad(res, R, mode='edge')
    e = np.array([(p[i:i+2*R+1].max() if hacia_abajo else p[i:i+2*R+1].min())
                  for i in range(len(res))])
    return _tendencia(t + e)


def detectar_boca(a, suj, izq, der):
    """La boca cae bajo los ojos, a una distancia proporcional a su separacion."""
    lum = a.mean(axis=2)
    ey = (izq['cy'] + der['cy']) / 2
    ex = (izq['cx'] + der['cx']) / 2
    sep = abs(der['cx'] - izq['cx'])
    # La boca cae a ~1.05 separaciones oculares. Con una ventana mas larga se
    # engancha al cuello de la camisa, que es mas oscuro que la costura.
    ya, yb = int(ey + 0.62 * sep), int(ey + 1.75 * sep)
    xa, xb = int(ex - 1.00 * sep), int(ex + 1.00 * sep)
    h, w = lum.shape
    ya, yb = max(ya, 0), min(yb, h - 1)
    xa, xb = max(xa, 0), min(xb, w - 1)
    if yb - ya < 10 or xb - xa < 20:
        raise NoMedible('ventana de boca degenerada')

    piel_ref = np.median(lum[int(ey + 0.3*sep):int(ey + 0.5*sep), int(ex-0.2*sep):int(ex+0.2*sep)])
    umbral = min(piel_ref * 0.52, 95)

    # La costura de la boca es un trazo ancho; la sombra de la nariz, una mancha
    # pequena. Quedarse con la componente oscura de mayor extension horizontal
    # evita que la nariz hunda la curva y corte la medida.
    dark = (lum[ya:yb, xa:xb] < umbral) & suj[ya:yb, xa:xb]
    lab, n = ndimage.label(dark)
    if n == 0:
        raise NoMedible('no se encuentra la costura de la boca')
    mejor_i, mejor_an = 0, 0
    for i in range(1, n + 1):
        cols = np.nonzero((lab == i).any(axis=0))[0]
        if len(cols) and cols.max() - cols.min() > mejor_an:
            mejor_an, mejor_i = cols.max() - cols.min(), i
    comp = lab == mejor_i
    if mejor_an < 20:
        raise NoMedible('costura de boca demasiado corta')

    # La componente de la boca suele venir pegada a la sombra de la nariz. Por
    # columna hay entonces dos tramos: el de arriba es la nariz, el de abajo la
    # boca. Se toma el de abajo.
    fila = np.zeros(xb - xa); oscuro = np.zeros(xb - xa, bool)
    for i in range(xb - xa):
        col = comp[:, i]
        ini, ult = None, None
        for y in range(len(col) + 1):
            on = y < len(col) and col[y]
            if on and ini is None:
                ini = y
            elif not on and ini is not None:
                if y - ini >= 2:
                    ult = (ini, y)
                ini = None
        if ult:
            fila[i] = ult[0] + ya
            oscuro[i] = True

    idx = np.nonzero(oscuro)[0]
    cortes = np.split(idx, np.nonzero(np.diff(idx) > 4)[0] + 1)
    tramo = max(cortes, key=len)
    i0, i1 = tramo[0], tramo[-1] + 1

    # Los pliegues de la sonrisa son oscuros y continuan la costura hacia abajo.
    # Caminando hacia fuera desde el centro, la costura sube hasta la comisura y
    # luego vuelve a bajar: la boca acaba en ese minimo.
    # se camina sobre la tendencia: el feston del diente hace saltar la curva
    # cruda mas de 4 px y cortaria el recorrido en la primera muesca
    suave = _tendencia(fila[i0:i1], 4.0)
    # se parte del centro de la cara, no del punto mas bajo: el pliegue baja
    # mas que la propia boca y arrastraba el arranque
    c = int(np.clip(round(ex) - (xa + i0), 0, len(suave) - 1))
    izq_i, mn = c, suave[c]
    for i in range(c - 1, -1, -1):
        mn = min(mn, suave[i])
        if suave[i] > mn + 3:
            break
        izq_i = i
    der_i, mn = c, suave[c]
    for i in range(c + 1, len(suave)):
        mn = min(mn, suave[i])
        if suave[i] > mn + 3:
            break
        der_i = i
    izq_i += i0; der_i += i0; c += i0
    i0, i1 = izq_i, der_i + 1
    if i1 - i0 < 20:
        raise NoMedible('boca demasiado estrecha tras recortar los pliegues')
    x0, x1 = xa + i0, xa + i1
    line = _envolvente(fila[i0:i1], 5, True)

    # borde superior del diente
    R2, B2 = a[:, :, 0], a[:, :, 2]
    es_diente = (lum > 150) & ((R2 - B2) < 60)
    raw_t = np.zeros(x1 - x0)
    for i, x in enumerate(range(x0, x1)):
        lo = int(round(line[i])); hi = max(lo - 36, 0)
        col = es_diente[hi:lo, x]
        mejor, ini = (0, lo), None
        for j in range(len(col) + 1):
            on = j < len(col) and col[j]
            if on and ini is None:
                ini = j
            elif not on and ini is not None:
                if j - ini > mejor[0]:
                    mejor = (j - ini, hi + ini)
                ini = None
        raw_t[i] = mejor[1] if mejor[0] >= 3 else lo
    top = np.minimum(_envolvente(raw_t, 4, False), line)
    return x0, x1, line, top


# ---------------------------------------------------------------- cejas y menton
def detectar_cejas(a, suj, izq, der):
    lum = a.mean(axis=2)
    ey = min(izq['cy'] - izq['al'] / 2, der['cy'] - der['al'] / 2)
    sep = abs(der['cx'] - izq['cx'])
    # pegada al ojo: mas arriba empieza el pelo, igual de oscuro
    ya, yb = int(ey - 0.45 * sep), int(ey + 0.05 * sep)
    xa, xb = int(izq['cx'] - 0.55 * sep), int(der['cx'] + 0.55 * sep)
    h, w = lum.shape
    ya, yb, xa, xb = max(ya, 0), min(yb, h), max(xa, 0), min(xb, w)
    ceja = (lum[ya:yb, xa:xb] < 95) & suj[ya:yb, xa:xb]
    ys, xs = np.nonzero(ceja)
    if len(ys) < 80:
        raise NoMedible('no se encuentran las cejas')
    return (int(xs.min() + xa), int(xs.max() + xa),
            int(np.percentile(ys, 3) + ya), int(np.percentile(ys, 97) + ya))


def detectar_menton(a, suj, line, sep):
    """La barbilla queda ~0.62 separaciones oculares bajo la boca.

    Se usa la proporcion y no la silueta: este personaje tiene el cuello ancho y
    la silueta no se estrecha, asi que buscar el estrechamiento se iba hasta el
    torso.
    """
    y_boca = int(np.max(line))
    h = suj.shape[0]
    est = int(y_boca + 0.62 * sep)
    lim = min(int(y_boca + 1.0 * sep), h - 1)
    anchos = [suj[y].sum() for y in range(y_boca, lim)]
    if anchos:
        base = anchos[0]
        for k, an in enumerate(anchos):      # si se estrecha antes, manda la silueta
            if an < base * 0.55:
                return min(y_boca + k, est)
    return min(est, h - 1)


# ---------------------------------------------------------------- medir
def medir(ruta, nombre=None, guardar=True):
    nombre = nombre or os.path.splitext(os.path.basename(ruta))[0]
    rgba, suj = recortar(ruta)
    a = np.asarray(rgba)[:, :, :3].astype(int)

    # Detección conjunta: lo que valida una pareja de ojos es que haya una boca
    # creíble debajo. Con la pareja suelta se colaban la cinta de la frente de
    # un personaje o una púa del pelo, y salía un rig con medidas absurdas.
    ultimo = None
    for izq, der in candidatos_ojos(a, suj)[:8]:
        sep = abs(der['cx'] - izq['cx'])
        try:
            x0, x1, line, top = detectar_boca(a, suj, izq, der)
        except NoMedible as e:
            ultimo = e
            continue
        if (x1 - x0) < MIN_BOCA * sep:
            ultimo = NoMedible(
                f'la boca encontrada mide {(x1-x0)/sep:.2f} veces la separación de '
                f'los ojos, y hace falta al menos {MIN_BOCA}')
            continue
        # y tiene que caer centrada bajo los ojos: si no, lo detectado como
        # ojos estaba en otro sitio de la cabeza
        desvio = abs((x0 + x1) / 2 - (izq['cx'] + der['cx']) / 2) / sep
        if desvio > MAX_DESVIO:
            ultimo = NoMedible(
                f'la boca queda descentrada respecto a los ojos ({desvio:.2f} veces '
                'su separación): lo detectado como ojos no lo es')
            continue
        break
    else:
        raise ultimo or NoMedible('no se encuentra una cara que se pueda animar')

    m_izq, m_der = mascara_ojo(a, suj, izq), mascara_ojo(a, suj, der)
    bx0, bx1, by0, by1 = detectar_cejas(a, suj, izq, der)
    menton = detectar_menton(a, suj, line, sep)

    ys, xs = np.nonzero(suj)
    datos = dict(
        mouth_x0=x0, mouth_x1=x1, mouth_line=line, mouth_top=top,
        eye_izq=m_izq, eye_der=m_der,
        brow_x0=bx0, brow_x1=bx1, brow_y0=by0, brow_y1=by1,
        chin=menton, eye_sep=sep,
        sujeto=np.array([xs.min(), ys.min(), xs.max(), ys.max()]),
    )
    if guardar:
        os.makedirs(RIGS, exist_ok=True)
        rgba.save(os.path.join(RIGS, nombre + '.png'))
        np.savez_compressed(os.path.join(RIGS, nombre + '.npz'), **datos)
        _verificacion(rgba, datos, os.path.join(RIGS, nombre + '_check.png'))
    return datos, rgba


def _verificacion(rgba, d, destino):
    vis = rgba.convert('RGB'); arr = np.asarray(vis).copy()
    arr[d['eye_izq']] = (0, 255, 0)
    arr[d['eye_der']] = (255, 0, 255)
    vis = Image.fromarray(arr)
    dr = ImageDraw.Draw(vis)
    xs = range(int(d['mouth_x0']), int(d['mouth_x1']))
    dr.point([(x, int(round(y))) for x, y in zip(xs, d['mouth_line'])], fill=(0, 255, 255))
    dr.point([(x, int(round(y))) for x, y in zip(xs, d['mouth_top'])], fill=(255, 220, 0))
    dr.rectangle([d['brow_x0'], d['brow_y0'], d['brow_x1'], d['brow_y1']], outline=(255, 90, 0))
    dr.line([d['mouth_x0'] - 20, d['chin'], d['mouth_x1'] + 20, d['chin']], fill=(255, 0, 0))
    x0, y0, x1, y1 = d['sujeto']
    alto = y1 - y0
    vis.crop((max(x0 - 10, 0), y0, x1 + 10, y0 + int(alto * 0.45))).save(destino)


def medir_dibujada(ruta, nombre, caja, guardar=True):
    """Prepara un rig de boca dibujada a partir de la caja que marque el usuario.

    No hace falta medir ojos ni dientes: la boca se borra y se dibuja encima,
    así que lo único imprescindible es saber dónde está.
    """
    import dibujada
    rgba, suj = recortar(ruta)
    lienzo, contorno, interior, caja = dibujada.analizar(rgba, caja)
    ys, xs = np.nonzero(suj)
    datos = dict(tipo='dibujada', boca=np.array(caja),
                 contorno=np.array(contorno), interior=np.array(interior),
                 sujeto=np.array([xs.min(), ys.min(), xs.max(), ys.max()]))
    if guardar:
        os.makedirs(RIGS, exist_ok=True)
        lienzo.save(os.path.join(RIGS, nombre + '.png'))
        np.savez_compressed(os.path.join(RIGS, nombre + '.npz'), **datos)
        chk = rgba.convert('RGB')
        dr = ImageDraw.Draw(chk)
        dr.rectangle(list(caja), outline=(0, 230, 230), width=3)
        x0, y0, x1, y1 = [int(v) for v in datos['sujeto']]
        alto = y1 - y0
        chk.crop((max(x0 - 10, 0), y0, x1 + 10, y0 + int(alto * 0.55))).save(
            os.path.join(RIGS, nombre + '_check.png'))
    return datos


def borrar(nombre):
    """Quita el rig medido y la imagen de origen del avatar."""
    import glob as _g
    hubo = False
    for p in (os.path.join(RIGS, nombre + e) for e in ('.npz', '.png', '_check.png')):
        if os.path.isfile(p):
            os.remove(p); hubo = True
    for p in _g.glob(os.path.join(AQUI, 'avatares', nombre + '.*')):
        os.remove(p); hubo = True
    return hubo


def medir_carpeta(carpeta=None, hablar=True):
    """Mide todas las imagenes de `avatares/`. Devuelve (logrados, fallidos)."""
    import glob
    carpeta = carpeta or os.path.join(AQUI, 'avatares')
    os.makedirs(carpeta, exist_ok=True)
    rutas = sorted(sum((glob.glob(os.path.join(carpeta, e))
                        for e in ('*.png', '*.jpg', '*.jpeg', '*.webp')), []))
    ok, mal = [], []
    for r in rutas:
        nom = os.path.splitext(os.path.basename(r))[0]
        try:
            d, _ = medir(r, nom)
            alt = d['mouth_line'] - d['mouth_top']
            diente = float(alt[len(alt) // 2])
            ancho = int(d['mouth_x1'] - d['mouth_x0'])
            sep = float(d['eye_sep'])
            # Sin dientes visibles el cierre de labios no tiene nada que tapar, y
            # una boca estrecha suele significar que se midio otra cosa.
            # Poco diente no impide hablar: la mandibula abre igual. Lo que sale
            # flojo es el cierre de labios en M/B/P, que necesita diente que tapar.
            nota = ''
            if ancho < 0.9 * sep:
                nota = '  <- boca estrecha, revisa el _check'
            elif diente < 0.05 * sep:
                nota = '  <- poco diente: el cierre en M/B/P sera flojo'
            if hablar:
                print(f'  OK    {nom:16s} sep {sep:3.0f} | boca {ancho:3d} px | '
                      f'diente {diente:4.1f} px{nota}')
            ok.append(nom)
        except Exception as e:
            if hablar:
                print(f'  FALLA {nom:16s} {e}')
            mal.append((nom, str(e)))
    return ok, mal


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print('Midiendo todo lo que haya en avatares/ ...')
        ok, mal = medir_carpeta()
        print(f'\n{len(ok)} medidos, {len(mal)} fallidos')
        if ok:
            print('Revisa rigs/<nombre>_check.png antes de usarlos.')
            print('Luego en el guion:  # avatar: ' + ', '.join(ok))
        if mal:
            print('\nLos fallos suelen ser poses de perfil (falta un ojo) o con la')
            print('boca ya abierta (no hay costura que abrir). Sirven como poses')
            print('de recurso: ponlas en poses_fuente/ y corre poses.py')
        sys.exit(0)
    d, _ = medir(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None)
    print(f"boca      x {d['mouth_x0']}-{d['mouth_x1']} | "
          f"costura y {d['mouth_line'].min():.0f}-{d['mouth_line'].max():.0f}")
    print(f"diente    alto {(d['mouth_line']-d['mouth_top'])[len(d['mouth_top'])//2]:.1f} px (centro)")
    ys, xs = np.nonzero(d['eye_izq']); print(f"ojo izq   x {xs.min()}-{xs.max()} y {ys.min()}-{ys.max()}")
    ys, xs = np.nonzero(d['eye_der']); print(f"ojo der   x {xs.min()}-{xs.max()} y {ys.min()}-{ys.max()}")
    print(f"cejas     x {d['brow_x0']}-{d['brow_x1']} y {d['brow_y0']}-{d['brow_y1']}")
    print(f"barbilla  y {d['chin']} | separacion ocular {d['eye_sep']:.0f} px")

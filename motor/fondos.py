# -*- coding: utf-8 -*-
"""Fondos de imagen subidos por el usuario.

    python fondos.py            # procesa lo que haya en fondos_fuente/
    python fondos.py --listar

Las imágenes se guardan ya recortadas a vertical y a un tamaño acotado: así el
render no paga el coste de una foto de 6000 px cada vez, y el disco no crece sin
control. El tratamiento (desenfoque, oscurecido) NO se aplica aquí, porque es
una decisión por video y se ajusta desde la interfaz.
"""
import glob, json, os, sys
from PIL import Image

AQUI = os.path.dirname(os.path.abspath(__file__))
FUENTE = os.path.join(AQUI, 'fondos_fuente')
DESTINO = os.path.join(AQUI, 'fondos')
CATALOGO = os.path.join(DESTINO, 'fondos.json')

# El lienzo es 1080x1920. Se guarda con margen de sobra para poder desplazar el
# fondo y para que aguante un primer plano sin verse blando.
ANCHO, ALTO = 1500, 2667
MINI = (150, 267)


def _catalogo():
    if os.path.exists(CATALOGO):
        try:
            return json.load(open(CATALOGO, encoding='utf-8'))
        except (ValueError, OSError):
            pass
    return {}


def _guardar_catalogo(cat):
    os.makedirs(DESTINO, exist_ok=True)
    json.dump(cat, open(CATALOGO, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)


def nombre_de(ruta):
    return os.path.splitext(os.path.basename(ruta))[0].lower().replace(' ', '_')


def guardar(origen, nombre=None):
    """Recorta a vertical, acota el tamaño y añade al catálogo."""
    nombre = nombre or nombre_de(origen)
    os.makedirs(DESTINO, exist_ok=True)
    im = Image.open(origen).convert('RGB')
    esc = max(ANCHO / im.width, ALTO / im.height)
    if esc < 1:                                   # solo se reduce, nunca se amplía
        im = im.resize((max(int(im.width * esc) + 1, ANCHO),
                        max(int(im.height * esc) + 1, ALTO)), Image.LANCZOS)
    iz, ar = (im.width - min(im.width, ANCHO)) // 2, (im.height - min(im.height, ALTO)) // 2
    im = im.crop((iz, ar, iz + min(im.width, ANCHO), ar + min(im.height, ALTO)))

    archivo = nombre + '.jpg'
    im.save(os.path.join(DESTINO, archivo), quality=88, optimize=True)
    mini = im.copy(); mini.thumbnail(MINI, Image.LANCZOS)
    mini.save(os.path.join(DESTINO, nombre + '_mini.jpg'), quality=80)

    cat = _catalogo()
    cat[nombre] = {'archivo': archivo, 'w': im.width, 'h': im.height}
    _guardar_catalogo(cat)
    return nombre


def ruta(nombre):
    """Ruta del fondo, o None si no existe."""
    if not nombre:
        return None
    d = _catalogo().get(nombre)
    if not d:
        return None
    p = os.path.join(DESTINO, d['archivo'])
    return p if os.path.isfile(p) else None


def listar():
    return [{'nombre': n, 'mini': f'/media/fondos/{n}_mini.jpg'}
            for n in sorted(_catalogo()) if ruta(n)]


def borrar(nombre):
    cat = _catalogo()
    if nombre not in cat:
        return False
    for f in (cat[nombre]['archivo'], nombre + '_mini.jpg'):
        try:
            os.remove(os.path.join(DESTINO, f))
        except OSError:
            pass
    cat.pop(nombre)
    _guardar_catalogo(cat)
    return True


def preparar(hablar=True):
    """Procesa lo que haya en fondos_fuente/."""
    os.makedirs(FUENTE, exist_ok=True)
    n = 0
    for r in sorted(glob.glob(os.path.join(FUENTE, '*.[jpw][pne]*'))):
        try:
            nom = guardar(r)
            n += 1
            if hablar:
                print(f'  {nom}')
        except Exception as e:
            if hablar:
                print(f'  FALLA {os.path.basename(r)}: {e}')
    return n


if __name__ == '__main__':
    if '--listar' in sys.argv:
        for f in listar():
            print(' ', f['nombre'])
    else:
        print(f'{preparar()} fondos en {DESTINO}')

# -*- coding: utf-8 -*-
"""Pistas de música para la cama de fondo.

    python musica.py            # procesa lo que haya en musica_fuente/
    python musica.py --listar

Las pistas se normalizan a un nivel conocido al guardarlas, para que cambiar de
canción no cambie la mezcla: el volumen de la cama y el ducking ya están
ajustados y no deberían depender de lo fuerte que viniera el archivo.

De dónde sacar música libre: la propia librería de TikTok o Instagram (lo mejor
para el alcance, pero se añade allí, no aquí), Pixabay Music, Free Music Archive
o la Biblioteca de Audio de YouTube.
"""
import glob, json, os, subprocess, sys

import entorno

AQUI = os.path.dirname(os.path.abspath(__file__))
FUENTE = os.path.join(AQUI, 'musica_fuente')
DESTINO = os.path.join(AQUI, 'musica')
CATALOGO = os.path.join(DESTINO, 'musica.json')

NIVEL = -20.0        # LUFS a los que se deja cada pista al guardarla
MAX_SEG = 600        # no guardar más de 10 minutos


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


def duracion(ruta):
    ff = entorno.ffmpeg()
    fp = ff[:-len('ffmpeg.exe')] + 'ffprobe.exe' if ff.lower().endswith('ffmpeg.exe') else 'ffprobe'
    o = subprocess.run([fp, '-v', 'error', '-show_entries', 'format=duration',
                        '-of', 'csv=p=0', ruta], capture_output=True, text=True)
    try:
        return float(o.stdout.strip())
    except ValueError:
        return 0.0


def guardar(origen, nombre=None):
    """Normaliza y deja la pista lista para usar como cama."""
    nombre = nombre or nombre_de(origen)
    os.makedirs(DESTINO, exist_ok=True)
    dur = duracion(origen)
    if dur <= 0:
        raise ValueError('El archivo no tiene audio legible.')
    destino = os.path.join(DESTINO, nombre + '.m4a')
    subprocess.run([entorno.ffmpeg(), '-y', '-v', 'error', '-i', origen,
                    '-t', str(min(dur, MAX_SEG)),
                    '-af', f'loudnorm=I={NIVEL}:TP=-2:LRA=11',
                    '-ac', '2', '-ar', '48000', '-c:a', 'aac', '-b:a', '160k',
                    destino], check=True)
    cat = _catalogo()
    cat[nombre] = {'archivo': nombre + '.m4a', 'dur': round(min(dur, MAX_SEG), 1)}
    _guardar_catalogo(cat)
    return nombre, cat[nombre]['dur']


def ruta(nombre):
    if not nombre:
        return None
    d = _catalogo().get(nombre)
    if not d:
        return None
    p = os.path.join(DESTINO, d['archivo'])
    return p if os.path.isfile(p) else None


def listar():
    cat = _catalogo()
    return [{'nombre': n, 'dur': cat[n].get('dur', 0),
             'url': f'/media/musica/{cat[n]["archivo"]}'}
            for n in sorted(cat) if ruta(n)]


def borrar(nombre):
    cat = _catalogo()
    if nombre not in cat:
        return False
    try:
        os.remove(os.path.join(DESTINO, cat[nombre]['archivo']))
    except OSError:
        pass
    cat.pop(nombre)
    _guardar_catalogo(cat)
    return True


def preparar(hablar=True):
    os.makedirs(FUENTE, exist_ok=True)
    n = 0
    for r in sorted(glob.glob(os.path.join(FUENTE, '*.*'))):
        if os.path.splitext(r)[1].lower() not in ('.mp3', '.wav', '.m4a', '.ogg', '.flac', '.aac'):
            continue
        try:
            nom, dur = guardar(r)
            n += 1
            if hablar:
                print(f'  {nom}  ({dur:.0f} s)')
        except Exception as e:
            if hablar:
                print(f'  FALLA {os.path.basename(r)}: {e}')
    return n


if __name__ == '__main__':
    if '--listar' in sys.argv:
        for m in listar():
            print(f'  {m["nombre"]}  {m["dur"]:.0f} s')
    else:
        print(f'{preparar()} pistas en {DESTINO}')

# -*- coding: utf-8 -*-
"""Biblioteca de medios del editor: lo que entra, se prepara para editarlo.

Un archivo recién importado no sirve para montar. Un MP4 de móvil de 1080p
viene con fotogramas clave cada dos o tres segundos, así que al arrastrar el
cabezal por la línea de tiempo el navegador tiene que descodificar medio
segundo de vídeo para enseñar un fotograma, y el editor se arrastra.

Por eso de cada archivo se preparan cuatro cosas:

  copia ligera  un MP4 pequeño con fotograma clave cada 10, que es lo que ve
                el navegador mientras editas. El original no se toca y es el
                que se usa al exportar.
  tira          una fila de miniaturas para pintar el clip en la pista.
  póster        un fotograma suelto para la bandeja de medios.
  picos         el volumen resumido, para dibujar la onda del audio.

Todo se guarda junto al catálogo, en `medios/`.
"""
import glob
import json
import os
import shutil
import subprocess
import uuid

import entorno

AQUI = os.path.dirname(os.path.abspath(__file__))
BASE = os.path.join(AQUI, 'medios')
CATALOGO = os.path.join(BASE, 'medios.json')

ANCHO_COPIA = 480           # ancho de la copia ligera
SALTO_CLAVE = 10            # fotogramas entre claves: scrubbing fino
ALTO_TIRA = 72              # alto de cada miniatura de la tira
MAX_TIRA = 80               # miniaturas como mucho, para no hacer tiras enormes
PICOS = 1200                # cuántos valores de volumen por pista
MAX_SEG = 60 * 30           # media hora por archivo

VIDEO = {'.mp4', '.mov', '.m4v', '.webm', '.mkv', '.avi'}
IMAGEN = {'.png', '.jpg', '.jpeg', '.webp', '.bmp'}
AUDIO = {'.mp3', '.wav', '.m4a', '.aac', '.ogg', '.flac'}
ACEPTADAS = VIDEO | IMAGEN | AUDIO


def _dirs():
    for d in ('orig', 'copia', 'tira', 'poster', 'picos'):
        os.makedirs(os.path.join(BASE, d), exist_ok=True)


def _catalogo():
    try:
        with open(CATALOGO, encoding='utf-8') as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _guardar(cat):
    _dirs()
    tmp = CATALOGO + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(cat, f, ensure_ascii=False, indent=1)
    os.replace(tmp, CATALOGO)


def clase(ext):
    ext = ext.lower()
    if ext in VIDEO:
        return 'video'
    if ext in IMAGEN:
        return 'imagen'
    if ext in AUDIO:
        return 'audio'
    return None


# ------------------------------------------------------------------ sondeo
def sondear(ruta):
    """Lo que ffprobe sabe del archivo: duración, tamaño, si trae audio."""
    o = subprocess.run(
        [entorno.ffprobe(), '-v', 'error', '-show_streams', '-show_format',
         '-of', 'json', ruta], capture_output=True, text=True)
    try:
        d = json.loads(o.stdout or '{}')
    except ValueError:
        raise ValueError('El archivo no se puede leer como vídeo o audio.')
    flujos = d.get('streams') or []
    if not flujos:
        raise ValueError('El archivo no tiene vídeo ni audio dentro.')

    v = next((s for s in flujos if s.get('codec_type') == 'video'), None)
    a = next((s for s in flujos if s.get('codec_type') == 'audio'), None)
    try:
        dur = float((d.get('format') or {}).get('duration') or 0)
    except (TypeError, ValueError):
        dur = 0.0

    fps = 30.0
    if v and v.get('avg_frame_rate', '0/0') not in ('0/0', '', None):
        try:
            num, den = v['avg_frame_rate'].split('/')
            fps = float(num) / float(den) if float(den) else 30.0
        except (ValueError, ZeroDivisionError):
            fps = 30.0

    # Un móvil graba en horizontal y marca "gíralo 90°" en los metadatos. Si no
    # se mira esa marca, el vídeo entra tumbado en la línea de tiempo.
    an = al = 0
    if v:
        an, al = int(v.get('width') or 0), int(v.get('height') or 0)
        giro = 0
        for lado in (v.get('side_data_list') or []):
            if 'rotation' in lado:
                try:
                    giro = int(float(lado['rotation'])) % 360
                except (TypeError, ValueError):
                    giro = 0
        if giro in (90, 270):
            an, al = al, an
    return {'dur': dur, 'w': an, 'h': al, 'fps': round(fps, 3),
            'audio': a is not None, 'video': v is not None}


# ------------------------------------------------------------- preparacion
def _copia_video(origen, destino, dur):
    """MP4 pequeño y con muchas claves: es lo que se ve mientras editas."""
    subprocess.run(
        [entorno.ffmpeg(), '-y', '-v', 'error', '-i', origen,
         '-t', str(min(dur or MAX_SEG, MAX_SEG)),
         '-vf', f'scale={ANCHO_COPIA}:-2:flags=bilinear',
         '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '30',
         '-g', str(SALTO_CLAVE), '-keyint_min', str(SALTO_CLAVE),
         '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-b:a', '96k', '-ac', '2',
         '-movflags', '+faststart', destino], check=True)


def _copia_audio(origen, destino, dur):
    subprocess.run(
        [entorno.ffmpeg(), '-y', '-v', 'error', '-i', origen,
         '-t', str(min(dur or MAX_SEG, MAX_SEG)),
         '-c:a', 'aac', '-b:a', '128k', '-ac', '2', '-ar', '48000',
         '-movflags', '+faststart', destino], check=True)


def _tira(origen, destino, dur, ancho_mini):
    """Fila de miniaturas. Es lo que hace que un clip se reconozca de un vistazo."""
    n = max(min(int(dur / 1.0) + 1, MAX_TIRA), 1)
    paso = max(dur / n, 0.04) if dur > 0 else 1.0
    subprocess.run(
        [entorno.ffmpeg(), '-y', '-v', 'error', '-i', origen,
         '-vf', (f'fps=1/{paso:.4f},scale={ancho_mini}:{ALTO_TIRA}:'
                 f'force_original_aspect_ratio=increase,'
                 f'crop={ancho_mini}:{ALTO_TIRA},tile={n}x1'),
         '-frames:v', '1', '-q:v', '5', destino], check=True)
    return n


def _poster(origen, destino, dur):
    t = max(min(dur * 0.25, 5.0), 0.0)
    subprocess.run(
        [entorno.ffmpeg(), '-y', '-v', 'error', '-ss', str(t), '-i', origen,
         '-vf', 'scale=320:-2', '-frames:v', '1', '-q:v', '4', destino],
        check=True)


def _picos(origen, destino, dur):
    """Volumen resumido en PICOS valores, de 0 a 1, para dibujar la onda."""
    import array
    o = subprocess.run(
        [entorno.ffmpeg(), '-v', 'error', '-i', origen,
         '-ac', '1', '-ar', '6000', '-f', 's16le', '-'],
        capture_output=True)
    cruda = array.array('h')
    cruda.frombytes(o.stdout[:len(o.stdout) // 2 * 2])
    if not len(cruda):
        return False
    n = min(PICOS, max(len(cruda) // 64, 1))
    paso = max(len(cruda) // n, 1)
    vals = []
    for i in range(0, paso * n, paso):
        trozo = cruda[i:i + paso]
        vals.append(round(max(abs(min(trozo)), abs(max(trozo))) / 32768.0, 3))
    with open(destino, 'w', encoding='utf-8') as f:
        json.dump(vals, f)
    return True


# ------------------------------------------------------------- importacion
def importar(origen, nombre=None):
    """Mete un archivo en la biblioteca y lo deja listo para la línea de tiempo."""
    _dirs()
    ext = os.path.splitext(origen)[1].lower()
    tipo = clase(ext)
    if not tipo:
        raise ValueError(f'Formato no admitido ({ext or "sin extensión"}). '
                         'Se aceptan vídeo, imagen y audio corrientes.')

    if tipo == 'imagen':
        from PIL import Image
        with Image.open(origen) as im:
            an, al = im.size
        datos = {'dur': 0.0, 'w': an, 'h': al, 'fps': 0, 'audio': False,
                 'video': True}
    else:
        datos = sondear(origen)
        if datos['dur'] <= 0:
            raise ValueError('El archivo no tiene duración legible.')
        if datos['dur'] > MAX_SEG:
            raise ValueError('El archivo dura más de media hora. '
                             'Córtalo antes de importarlo.')

    mid = uuid.uuid4().hex[:12]
    guardado = os.path.join(BASE, 'orig', mid + ext)
    shutil.copy2(origen, guardado)

    m = {'id': mid, 'nombre': (nombre or os.path.basename(origen))[:80],
         'tipo': tipo, 'archivo': os.path.basename(guardado),
         'dur': round(datos['dur'], 3), 'w': datos['w'], 'h': datos['h'],
         'fps': datos['fps'], 'audio': datos['audio']}

    try:
        if tipo == 'video':
            cop = os.path.join(BASE, 'copia', mid + '.mp4')
            _copia_video(guardado, cop, datos['dur'])
            m['copia'] = mid + '.mp4'
            ancho_mini = max(int(ALTO_TIRA * (datos['w'] or 16) /
                                 (datos['h'] or 9) / 2) * 2, 24)
            m['minis'] = _tira(cop, os.path.join(BASE, 'tira', mid + '.jpg'),
                               datos['dur'], ancho_mini)
            m['mini_w'] = ancho_mini
            _poster(cop, os.path.join(BASE, 'poster', mid + '.jpg'), datos['dur'])
            if datos['audio'] and _picos(guardado,
                                         os.path.join(BASE, 'picos', mid + '.json'),
                                         datos['dur']):
                m['picos'] = True
        elif tipo == 'audio':
            cop = os.path.join(BASE, 'copia', mid + '.m4a')
            _copia_audio(guardado, cop, datos['dur'])
            m['copia'] = mid + '.m4a'
            if _picos(guardado, os.path.join(BASE, 'picos', mid + '.json'),
                      datos['dur']):
                m['picos'] = True
        else:
            from PIL import Image
            with Image.open(origen) as im:
                im = im.convert('RGB')
                im.thumbnail((320, 320))
                im.save(os.path.join(BASE, 'poster', mid + '.jpg'), quality=86)
    except subprocess.CalledProcessError as e:
        # si la preparación falla, no dejar un medio a medias en el catálogo
        borrar_archivos(mid)
        raise ValueError('FFmpeg no pudo preparar el archivo: '
                         f'{(e.stderr or b"")[:200]}')

    cat = _catalogo()
    cat[mid] = m
    _guardar(cat)
    return ficha(m)


def ficha(m):
    """Lo que necesita la interfaz, con las URLs ya resueltas."""
    mid = m['id']
    f = dict(m)
    f['url'] = f'/medios/copia/{m["copia"]}' if m.get('copia') else \
               f'/medios/orig/{m["archivo"]}'
    f['original'] = f'/medios/orig/{m["archivo"]}'
    if m['tipo'] != 'audio':
        f['poster'] = f'/medios/poster/{mid}.jpg'
    if m.get('minis'):
        f['tira'] = f'/medios/tira/{mid}.jpg'
    if m.get('picos'):
        f['picos_url'] = f'/medios/picos/{mid}.json'
    return f


def listar():
    cat = _catalogo()
    return [ficha(m) for m in sorted(cat.values(), key=lambda x: x['nombre'].lower())
            if os.path.isfile(ruta(m['id']) or '')]


def obtener(mid):
    return _catalogo().get(mid)


def ruta(mid):
    """Ruta del archivo ORIGINAL: es el que se usa al exportar."""
    m = _catalogo().get(mid)
    if not m:
        return None
    p = os.path.join(BASE, 'orig', m['archivo'])
    return p if os.path.isfile(p) else None


def borrar_archivos(mid):
    for d, patron in (('orig', mid + '.*'), ('copia', mid + '.*'),
                      ('tira', mid + '.*'), ('poster', mid + '.*'),
                      ('picos', mid + '.*')):
        for p in glob.glob(os.path.join(BASE, d, patron)):
            try:
                os.remove(p)
            except OSError:
                pass


def borrar(mid):
    cat = _catalogo()
    if mid not in cat:
        return False
    borrar_archivos(mid)
    cat.pop(mid)
    _guardar(cat)
    return True

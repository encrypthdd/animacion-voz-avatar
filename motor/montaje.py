# -*- coding: utf-8 -*-
"""El proyecto: qué clip va en qué pista, desde cuándo y hasta cuándo.

Un montaje es un archivo JSON y nada más. No guarda vídeo: guarda decisiones.
Eso es lo que permite deshacer, duplicar un montaje entero, o cambiar el
tamaño del lienzo sin volver a tocar un solo fotograma.

La interfaz y el exportador leen el MISMO archivo, así que lo que ves mientras
editas y lo que sale al exportar vienen de la misma descripción. Cuando eso se
separa en dos modelos distintos, la vista previa y el resultado acaban
diciendo cosas diferentes, que es el fallo más caro de un editor.

Un clip se describe con cuatro tiempos, y conviene no confundirlos:

    t        segundo de la LÍNEA DE TIEMPO en que aparece
    dur      lo que ocupa en la línea de tiempo
    entrada  segundo del ARCHIVO por el que empieza
    veloc    a qué velocidad se reproduce; con 2.0, `dur` segundos de línea
             consumen el doble de archivo
"""
import json
import os
import time
import uuid

AQUI = os.path.dirname(os.path.abspath(__file__))
BASE = os.path.join(AQUI, 'montajes')

VERSION = 1
LIENZOS = {
    'vertical': (1080, 1920), 'horizontal': (1920, 1080),
    'cuadrado': (1080, 1080), 'clasico': (1440, 1080),
}
MAX_CLIPS = 400
MAX_PISTAS = 12
MAX_DUR = 60 * 20          # 20 minutos de montaje
ENCAJES = ('cubrir', 'contener', 'estirar')

# ─── Clips de texto ────────────────────────────────────────────────────────
# Un rotulo es un clip mas: ocupa un tramo de una pista y se superpone a lo
# que haya debajo. La diferencia es que no sale de ningun archivo, asi que no
# tiene `medio` ni `entrada`.
#
# Lo que se guarda aqui es la DESCRIPCION del rotulo, no su imagen. La imagen
# la dibuja el navegador, tanto en la vista previa como al exportar, y por eso
# el MP4 sale exactamente igual que lo que viste. Dibujarlo dos veces -una en
# el navegador y otra con drawtext de FFmpeg- es lo que hace que en casi todos
# los editores caseros el texto acabe un poco mas grande, o partido en otro
# sitio, en el video final.
FUENTES = ('gruesa', 'redonda', 'serif', 'maquina')
ALINEACIONES = ('izq', 'centro', 'der')
MAX_TEXTO = 400
TEXTO_POR_DEFECTO = {
    'texto': 'Tu texto aquí', 'fuente': 'gruesa', 'tam': 0.062,
    'color': '#FFFFFF', 'contorno': 0.14, 'color_contorno': '#000000',
    'caja': False, 'color_caja': '#000000', 'alfa_caja': 0.55,
    'x': 0.5, 'y': 0.78, 'align': 'centro', 'fundido': 0.25,
    'karaoke': False, 'color_activo': '#FFD60A', 'palabras': [],
}
MAX_PALABRAS = 40      # por rotulo: una linea de subtitulo no lleva mas


def _color(v, defecto):
    v = str(v or '')
    if len(v) == 7 and v[0] == '#':
        try:
            int(v[1:], 16)
            return v.upper()
        except ValueError:
            pass
    return defecto


def _limpiar_texto(c):
    """Los campos propios de un rotulo, dentro de limites razonables."""
    d = dict(TEXTO_POR_DEFECTO)
    t = str(c.get('texto') or '')[:MAX_TEXTO]
    d['texto'] = t if t.strip() else TEXTO_POR_DEFECTO['texto']
    if c.get('fuente') in FUENTES:
        d['fuente'] = c['fuente']
    if c.get('align') in ALINEACIONES:
        d['align'] = c['align']
    d['tam'] = round(_num(c.get('tam'), d['tam'], 0.015, 0.30), 4)
    d['contorno'] = round(_num(c.get('contorno'), d['contorno'], 0, 0.4), 3)
    d['x'] = round(_num(c.get('x'), d['x'], -0.2, 1.2), 4)
    d['y'] = round(_num(c.get('y'), d['y'], -0.2, 1.2), 4)
    d['fundido'] = round(_num(c.get('fundido'), d['fundido'], 0, 2.0), 3)
    d['alfa_caja'] = round(_num(c.get('alfa_caja'), d['alfa_caja'], 0, 1), 3)
    d['caja'] = bool(c.get('caja'))
    d['color'] = _color(c.get('color'), d['color'])
    d['color_contorno'] = _color(c.get('color_contorno'), d['color_contorno'])
    d['color_caja'] = _color(c.get('color_caja'), d['color_caja'])
    d['color_activo'] = _color(c.get('color_activo'), d['color_activo'])
    d['karaoke'] = bool(c.get('karaoke'))
    # Las palabras de un subtitulo, con su momento MEDIDO DESDE EL PRINCIPIO
    # DEL CLIP: asi el rotulo se puede mover por la linea de tiempo sin que se
    # desarme el resaltado.
    pal = []
    for w in (c.get('palabras') or [])[:MAX_PALABRAS]:
        if not isinstance(w, dict):
            continue
        t0 = _num(w.get('t0'), 0, 0, MAX_DUR)
        t1 = _num(w.get('t1'), t0, 0, MAX_DUR)
        pal.append({'w': str(w.get('w') or '')[:40],
                    't0': round(t0, 3), 't1': round(max(t1, t0), 3)})
    d['palabras'] = pal
    if not pal:
        d['karaoke'] = False
    return d


def _ahora():
    return time.strftime('%Y-%m-%d %H:%M')


def nuevo(nombre='Montaje nuevo', lienzo='vertical'):
    an, al = LIENZOS.get(lienzo, LIENZOS['vertical'])
    return {
        'version': VERSION,
        'id': uuid.uuid4().hex[:12],
        'nombre': nombre[:80],
        'creado': _ahora(),
        'lienzo': {'w': an, 'h': al, 'fps': 30, 'forma': lienzo},
        'pistas': [
            {'id': 'v2', 'tipo': 'video', 'nombre': 'Vídeo 2', 'muda': False, 'oculta': False},
            {'id': 'v1', 'tipo': 'video', 'nombre': 'Vídeo 1', 'muda': False, 'oculta': False},
            {'id': 'a1', 'tipo': 'audio', 'nombre': 'Audio 1', 'muda': False, 'oculta': False},
        ],
        'clips': [],
    }


# ----------------------------------------------------------- normalizacion
def _num(v, defecto=0.0, minimo=None, maximo=None):
    try:
        x = float(v)
    except (TypeError, ValueError):
        return defecto
    if x != x:                      # NaN
        return defecto
    if minimo is not None:
        x = max(x, minimo)
    if maximo is not None:
        x = min(x, maximo)
    return x


def limpiar(p, medios=None):
    """Deja el proyecto en forma: lo que llega del navegador no es de fiar.

    Un clip que apunta a un medio borrado, una duración negativa o dos pistas
    con el mismo id harían que el exportador fabricase un comando de FFmpeg
    sin sentido. Más vale descartarlos aquí, que es donde se puede explicar.
    """
    if not isinstance(p, dict):
        raise ValueError('El montaje no es un objeto.')
    base = nuevo()
    out = {'version': VERSION, 'id': str(p.get('id') or base['id'])[:32],
           'nombre': (str(p.get('nombre') or 'Montaje'))[:80],
           'creado': str(p.get('creado') or _ahora())[:32]}

    li = p.get('lienzo') or {}
    forma = li.get('forma') if li.get('forma') in LIENZOS else None
    if forma:
        an, al = LIENZOS[forma]
    else:
        an = int(_num(li.get('w'), 1080, 240, 3840))
        al = int(_num(li.get('h'), 1920, 240, 3840))
        forma = 'libre'
    out['lienzo'] = {'w': an - an % 2, 'h': al - al % 2,
                     'fps': int(_num(li.get('fps'), 30, 12, 60)), 'forma': forma}

    pistas, vistos = [], set()
    for t in (p.get('pistas') or [])[:MAX_PISTAS]:
        if not isinstance(t, dict):
            continue
        tid = str(t.get('id') or '')[:12]
        if not tid or tid in vistos:
            continue
        vistos.add(tid)
        pistas.append({'id': tid,
                       'tipo': 'audio' if t.get('tipo') == 'audio' else 'video',
                       'nombre': (str(t.get('nombre') or tid))[:40],
                       'muda': bool(t.get('muda')),
                       'oculta': bool(t.get('oculta'))})
    out['pistas'] = pistas or base['pistas']
    ids_pista = {t['id'] for t in out['pistas']}

    clips, descartados = [], 0
    for c in (p.get('clips') or [])[:MAX_CLIPS]:
        if not isinstance(c, dict):
            continue
        pista = str(c.get('pista') or '')[:12]
        mid = str(c.get('medio') or '')[:32]
        if pista not in ids_pista:
            descartados += 1
            continue
        es_texto = c.get('tipo') == 'texto'
        m = medios.get(mid) if (medios is not None and not es_texto) else None
        if medios is not None and not es_texto and not m:
            descartados += 1
            continue
        dur = _num(c.get('dur'), 0, 0.04, MAX_DUR)
        if dur <= 0:
            descartados += 1
            continue
        clip = {
            'id': str(c.get('id') or uuid.uuid4().hex[:10])[:16],
            'pista': pista, 'medio': '' if es_texto else mid,
            't': round(_num(c.get('t'), 0, 0, MAX_DUR), 3),
            'dur': round(dur, 3),
            'entrada': round(_num(c.get('entrada'), 0, 0, MAX_DUR), 3),
            'veloc': round(_num(c.get('veloc'), 1.0, 0.25, 4.0), 3),
            'volumen': round(_num(c.get('volumen'), 1.0, 0, 4.0), 3),
            'opacidad': round(_num(c.get('opacidad'), 1.0, 0, 1.0), 3),
            'encaje': c.get('encaje') if c.get('encaje') in ENCAJES else 'cubrir',
            'nombre': (str(c.get('nombre') or ''))[:80],
        }
        if es_texto:
            clip['tipo'] = 'texto'
            clip['veloc'] = 1.0
            clip['entrada'] = 0.0
            clip.update(_limpiar_texto(c))
            clip['nombre'] = clip['texto'].split(chr(10))[0][:40]
            clips.append(clip)
            continue
        # Un clip no puede pedir más archivo del que hay: al exportar, FFmpeg
        # rellenaría el final con el ultimo fotograma congelado sin avisar.
        if m and m.get('tipo') != 'imagen' and m.get('dur'):
            resto = max(float(m['dur']) - clip['entrada'], 0.0)
            tope = resto / clip['veloc']
            if tope < 0.04:
                descartados += 1
                continue
            clip['dur'] = round(min(clip['dur'], tope), 3)
        clips.append(clip)

    clips.sort(key=lambda c: (c['t'], c['id']))
    out['clips'] = clips
    out['descartados'] = descartados
    return out


def duracion(p):
    return round(max([c['t'] + c['dur'] for c in p.get('clips') or []] or [0.0]), 3)


# --------------------------------------------------------------- almacen
def _ruta(mid):
    return os.path.join(BASE, mid + '.json')


def guardar(p):
    os.makedirs(BASE, exist_ok=True)
    p = dict(p)
    p['guardado'] = _ahora()
    tmp = _ruta(p['id']) + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(p, f, ensure_ascii=False, indent=1)
    os.replace(tmp, _ruta(p['id']))
    return p


def cargar(mid):
    try:
        with open(_ruta(mid), encoding='utf-8') as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def listar():
    os.makedirs(BASE, exist_ok=True)
    out = []
    for f in os.listdir(BASE):
        if not f.endswith('.json'):
            continue
        p = cargar(f[:-5])
        if p:
            out.append({'id': p.get('id'), 'nombre': p.get('nombre'),
                        'guardado': p.get('guardado') or p.get('creado'),
                        'clips': len(p.get('clips') or []),
                        'dur': duracion(p)})
    out.sort(key=lambda x: x.get('guardado') or '', reverse=True)
    return out


def borrar(mid):
    try:
        os.remove(_ruta(mid))
        return True
    except OSError:
        return False

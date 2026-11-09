# -*- coding: utf-8 -*-
"""Convierte un montaje en un MP4, con FFmpeg y los archivos originales.

Mientras editas, el navegador trabaja con las copias ligeras de `medios.py`.
Al exportar no: aquí se vuelve a los originales, a tamaño completo. Por eso la
vista previa va fluida y la exportación sale en calidad.

La forma del comando es siempre la misma:

  1. un lienzo negro que dura todo el montaje
  2. cada clip de vídeo se recorta, se escala al lienzo y se desplaza al
     segundo que le toca con `setpts`
  3. los clips se superponen uno sobre otro de la pista de abajo a la de
     arriba, cada uno activo solo en su tramo
  4. el audio de cada clip se retrasa con `adelay` y todo se suma con `amix`

`amix` lleva `normalize=0` a propósito: por defecto reparte el volumen entre
las entradas, así que un solo clip con una pista de música debajo sonaría a la
mitad sin que nada lo explique.
"""
import os
import subprocess
import threading

import entorno
import medios
import montaje

AQUI = os.path.dirname(os.path.abspath(__file__))


def _encaje(modo, W, H):
    if modo == 'estirar':
        return f'scale={W}:{H}'
    if modo == 'contener':
        return (f'scale={W}:{H}:force_original_aspect_ratio=decrease,'
                f'pad={W}:{H}:(ow-iw)/2:(oh-ih)/2:color=black')
    return (f'scale={W}:{H}:force_original_aspect_ratio=increase,'
            f'crop={W}:{H}')


def _fx(fx, W):
    """Los ajustes de color, en el mismo orden en que los aplica el navegador.

    El orden no es un detalle: subir el brillo y luego el contraste no da lo
    mismo que al reves. La vista previa encadena los filtros de canvas en este
    orden, asi que aqui tienen que ir igual.

    Cada pareja hace la misma cuenta que su equivalente de CSS:
      brightness(k)   multiplica los tres canales  -> colorchannelmixer
      contrast(k)     separa del gris medio        -> eq=contrast
      saturate(k)     separa del gris              -> eq=saturation
      hue-rotate(g)   gira el tono                 -> hue=h
      blur(n px)      gaussiana de radio n         -> gblur=sigma
    """
    fx = fx or {}
    cad = []
    b = float(fx.get('brillo', 1))
    if abs(b - 1) > 1e-3:
        cad.append(f'colorchannelmixer=rr={b:.4f}:gg={b:.4f}:bb={b:.4f}')
    c = float(fx.get('contraste', 1))
    if abs(c - 1) > 1e-3:
        cad.append(f'eq=contrast={c:.4f}')
    sa = float(fx.get('saturacion', 1))
    if abs(sa - 1) > 1e-3:
        cad.append(f'eq=saturation={sa:.4f}')
    t = float(fx.get('tono', 0))
    if abs(t) > 0.5:
        cad.append(f'hue=h={t:.2f}')
    d = float(fx.get('desenfoque', 0))
    if d > 1e-4:
        # el desenfoque se guarda en anchos de lienzo, para que se vea igual
        # en la vista previa pequena y en el video a tamano completo
        cad.append(f'gblur=sigma={max(d * W, 0.3):.3f}')
    return cad


def _atempo(veloc):
    """atempo solo admite de 0.5 a 2.0, así que para el resto se encadena."""
    v = max(min(float(veloc), 4.0), 0.25)
    pasos = []
    while v > 2.0:
        pasos.append(2.0); v /= 2.0
    while v < 0.5:
        pasos.append(0.5); v /= 0.5
    pasos.append(v)
    return ','.join(f'atempo={p:.4f}' for p in pasos)


def construir(p, destino, calidad='alta', rotulos=None, trabajo=None):
    """Devuelve (comando, duracion, grafo, carpeta). No ejecuta nada.

    El grafo de filtros NO va en el comando: se devuelve aparte para
    escribirlo en un archivo. Y los archivos de entrada no se nombran con su
    ruta entera, sino relativos a la carpeta desde la que se lanza FFmpeg.

    Las dos cosas son por el mismo motivo. Windows corta la linea de comandos
    en 32767 caracteres, y un montaje de 81 clips ya la pasaba: el grafo solo
    son ~300 caracteres por clip, y cada ruta absoluta, otros 90.

    `rotulos` son las imagenes de los clips de texto, ya dibujadas por el
    navegador: {id_de_clip: [{'ruta', 'x', 'y', 'desde', 'hasta'}, ...]}. Es
    una LISTA porque un subtitulo que resalta la palabra que se esta diciendo
    cambia de aspecto varias veces mientras dura: cada trozo es una imagen con
    su tramo. Un rotulo normal trae un solo trozo.

    Dibujarlos aqui, en vez de aceptar lo que mando el navegador, daria un
    resultado distinto al que la persona vio en la vista previa.
    """
    cat = {m['id']: m for m in medios.listar()}
    rotulos = rotulos or {}
    p = montaje.limpiar(p, cat)
    # Un rotulo sin imagen no se puede dibujar aqui: fuera, y que se note.
    clips = [c for c in p['clips']
             if c.get('tipo') != 'texto' or rotulos.get(c['id'])]
    if not clips:
        raise ValueError('El montaje está vacío: añade al menos un clip.')

    W, H = p['lienzo']['w'], p['lienzo']['h']
    FPS = p['lienzo']['fps']
    total = montaje.duracion(p)
    trabajo = trabajo or os.path.join(medios.BASE, 'orig')

    def rel(ruta):
        try:
            return os.path.relpath(os.path.abspath(ruta), trabajo)
        except ValueError:          # otra unidad de disco
            return os.path.abspath(ruta)

    pistas = {t['id']: t for t in p['pistas']}
    # de abajo arriba: la última pista de la lista es la de más abajo
    orden = {t['id']: i for i, t in enumerate(reversed(p['pistas']))}

    def es_texto(c):
        return c.get('tipo') == 'texto'

    visibles = [c for c in clips
                if not pistas[c['pista']]['oculta']
                and (es_texto(c) or (pistas[c['pista']]['tipo'] == 'video'
                                     and cat[c['medio']]['tipo'] != 'audio'))]
    visibles.sort(key=lambda c: (orden[c['pista']], c['t']))
    sonoros = [c for c in clips
               if not es_texto(c) and not pistas[c['pista']]['muda']
               and c['volumen'] > 0
               and (cat[c['medio']].get('audio') or cat[c['medio']]['tipo'] == 'audio')]

    # Una entrada de FFmpeg por clip, o por trozo de rotulo. El recorte se hace
    # al abrir el archivo (-ss y -t), que es mucho mas rapido que leerlo entero
    # y cortar despues.
    ent, filtros, capas, etiquetas_a = [], [], [], []
    indice = {}
    for c in clips:
        if es_texto(c):
            continue
        ruta = medios.ruta(c['medio'])
        if not ruta:
            continue
        indice[c['id']] = len(ent)
        if cat[c['medio']]['tipo'] == 'imagen':
            ent.append(['-loop', '1', '-t', f'{c["dur"]:.3f}', '-i', rel(ruta)])
        else:
            ent.append(['-ss', f'{c["entrada"]:.3f}',
                        '-t', f'{c["dur"] * c["veloc"]:.3f}', '-i', rel(ruta)])

    for c in visibles:
        if es_texto(c):
            trozos = rotulos.get(c['id']) or []
            ultimo = len(trozos) - 1
            f = c.get('fundido', 0)
            for k, tr in enumerate(trozos):
                desde = max(float(tr.get('desde', 0)), 0.0)
                hasta = min(float(tr.get('hasta', c['dur'])), c['dur'])
                if hasta - desde < 1 / FPS:
                    continue
                i = len(ent)
                ent.append(['-loop', '1', '-t', f'{hasta - desde:.3f}',
                            '-i', rel(tr['ruta'])])
                # La imagen ya viene al tamano del lienzo: solo hay que
                # colocarla, desplazarla en el tiempo y, si toca, fundirla.
                cad = ['format=rgba', f'fps={FPS}']
                if f > 0.01 and k == 0:
                    cad.append(f'fade=t=in:st=0:d={f:.3f}:alpha=1')
                if f > 0.01 and k == ultimo:
                    cad.append(f'fade=t=out:st={max(hasta - desde - f, 0):.3f}:'
                               f'd={f:.3f}:alpha=1')
                if c['opacidad'] < 0.999:
                    cad.append(f'colorchannelmixer=aa={c["opacidad"]:.3f}')
                cad.append(f'setpts=PTS-STARTPTS+{c["t"] + desde:.3f}/TB')
                filtros.append(f'[{i}:v]' + ','.join(cad) + f'[v{i}]')
                capas.append({'i': i, 'desde': c['t'] + desde,
                              'hasta': c['t'] + hasta,
                              'x': int(tr.get('x', 0)), 'y': int(tr.get('y', 0))})
            continue

        i = indice.get(c['id'])
        if i is None:
            continue
        cad = [_encaje(c['encaje'], W, H), 'setsar=1', f'fps={FPS}']
        cad += _fx(c.get('fx'), W)
        if abs(c['veloc'] - 1.0) > 1e-3:
            cad.append(f'setpts=PTS/{c["veloc"]:.4f}')
        # ojo con el nombre: `ent` es la lista de entradas de FFmpeg
        f_ent, f_sal = c.get('fundido_ent', 0), c.get('fundido_sal', 0)
        if f_ent > 0.01 or f_sal > 0.01 or c['opacidad'] < 0.999:
            # hace falta canal alfa: un fundido sin el oscurece hacia negro en
            # vez de dejar ver lo que haya debajo
            cad.append('format=rgba')
        if f_ent > 0.01:
            cad.append(f'fade=t=in:st=0:d={f_ent:.3f}:alpha=1')
        if f_sal > 0.01:
            cad.append(f'fade=t=out:st={max(c["dur"] - f_sal, 0):.3f}:'
                       f'd={f_sal:.3f}:alpha=1')
        # desplaza el clip al segundo que le toca en la linea de tiempo
        cad.append(f'setpts=PTS-STARTPTS+{c["t"]:.3f}/TB')
        if c['opacidad'] < 0.999:
            cad.append(f'colorchannelmixer=aa={c["opacidad"]:.3f}')
        filtros.append(f'[{i}:v]' + ','.join(cad) + f'[v{i}]')
        capas.append({'i': i, 'desde': c['t'], 'hasta': c['t'] + c['dur'],
                      'x': 0, 'y': 0})

    for c in sonoros:
        i = indice.get(c['id'])
        if i is None:
            continue
        m = cat[c['medio']]
        if m['tipo'] == 'imagen':
            continue
        cad = []
        if abs(c['veloc'] - 1.0) > 1e-3:
            cad.append(_atempo(c['veloc']))
        if abs(c['volumen'] - 1.0) > 1e-3:
            cad.append(f'volume={c["volumen"]:.3f}')
        ms = int(round(c['t'] * 1000))
        cad.append(f'adelay={ms}|{ms}')
        cad.append('aformat=sample_fmts=fltp:sample_rates=48000:'
                   'channel_layouts=stereo')
        filtros.append(f'[{i}:a]' + ','.join(cad) + f'[a{i}]')
        etiquetas_a.append(f'[a{i}]')

    filtros.insert(0, f'color=c=black:s={W}x{H}:r={FPS}:d={total:.3f}[base]')
    previo = '[base]'
    for k, cp in enumerate(capas):
        sal = f'[m{k}]'
        filtros.append(
            f'{previo}[v{cp["i"]}]overlay={cp["x"]}:{cp["y"]}:eof_action=pass:'
            f"enable='between(t,{cp['desde']:.3f},{cp['hasta']:.3f})'{sal}")
        previo = sal
    filtros.append(f'{previo}format=yuv420p[vout]')

    if etiquetas_a:
        filtros.append(''.join(etiquetas_a) +
                       f'amix=inputs={len(etiquetas_a)}:normalize=0:'
                       f'dropout_transition=0,'
                       f'aresample=48000[aout]')
    else:
        filtros.append(f'anullsrc=r=48000:cl=stereo,atrim=0:{total:.3f}[aout]')

    crf, preset = ('18', 'slow') if calidad == 'alta' else ('23', 'veryfast')
    cmd = [entorno.ffmpeg(), '-y', '-v', 'error']
    for e in ent:
        cmd += e
    cmd += ['-map', '[vout]', '-map', '[aout]',
            '-c:v', 'libx264', '-preset', preset, '-crf', crf,
            '-pix_fmt', 'yuv420p', '-r', str(FPS),
            '-c:a', 'aac', '-b:a', '192k',
            '-t', f'{total:.3f}', '-movflags', '+faststart',
            os.path.abspath(destino)]
    # un filtro por linea: si FFmpeg se queja, el archivo se puede leer
    grafo = (';' + os.linesep).join(filtros)
    return cmd, total, grafo, trabajo


# Cómo se le pasa a FFmpeg un grafo guardado en un archivo. Cambió: hasta la 6
# era `-filter_complex_script fichero`, y de la 7 en adelante esa opción no
# existe y se usa `-/filter_complex fichero`, la forma general de leer el valor
# de cualquier opción desde un archivo. En vez de adivinar la versión por el
# texto de `-version` —que viene de mil formas según quién compile— se prueba
# la primera y, si FFmpeg dice que no la conoce, se usa la otra y se recuerda.
GRAFO_NUEVO, GRAFO_VIEJO = '-/filter_complex', '-filter_complex_script'
_flag_grafo = None


def _desconocida(stderr):
    return ('Unrecognized option' in stderr or 'Option not found' in stderr)


def _con_grafo(cmd, flag, ruta_grafo):
    i = cmd.index('-map')
    return cmd[:i] + [flag, ruta_grafo] + cmd[i:]


def _correr(cmd, carpeta, total, avisar, cancelar):
    pr = subprocess.Popen(cmd + ['-progress', 'pipe:1', '-nostats'],
                          cwd=carpeta, stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE, text=True, bufsize=1)
    errores = []
    hilo = threading.Thread(target=lambda: errores.append(pr.stderr.read()),
                            daemon=True)
    hilo.start()
    parado = False
    try:
        for linea in pr.stdout:
            if cancelar and cancelar():
                parado = True
                pr.kill()
                break
            if linea.startswith('out_time_ms=') and avisar and total > 0:
                try:
                    seg = int(linea.split('=')[1]) / 1e6
                except (ValueError, IndexError):
                    continue
                avisar(min(seg / total, 1.0))
    finally:
        pr.wait()
        hilo.join(timeout=2)
    if parado:
        raise RuntimeError('Exportación cancelada.')
    return pr.returncode, (errores[0] if errores else '') or ''


def exportar(p, destino, calidad='alta', avisar=None, cancelar=None,
             rotulos=None, trabajo=None):
    """Lanza FFmpeg y va informando del avance en tanto por ciento."""
    global _flag_grafo
    cmd, total, grafo, carpeta = construir(p, destino, calidad, rotulos, trabajo)
    os.makedirs(os.path.dirname(os.path.abspath(destino)) or '.', exist_ok=True)
    grafo_ruta = os.path.abspath(destino) + '.filtros.txt'
    with open(grafo_ruta, 'w', encoding='utf-8') as f:
        f.write(grafo)

    intentos = [_flag_grafo] if _flag_grafo else [GRAFO_NUEVO, GRAFO_VIEJO]
    try:
        for n, flag in enumerate(intentos):
            rc, err = _correr(_con_grafo(cmd, flag, grafo_ruta), carpeta,
                              total, avisar, cancelar)
            if rc == 0:
                _flag_grafo = flag
                return destino, total
            if _desconocida(err) and n + 1 < len(intentos):
                continue
            raise RuntimeError('FFmpeg falló al exportar.\n' + err.strip()[-600:])
    finally:
        try:
            os.remove(grafo_ruta)
        except OSError:
            pass

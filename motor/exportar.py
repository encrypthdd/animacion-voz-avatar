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


def construir(p, destino, calidad='alta'):
    """Devuelve (comando, duracion). No ejecuta nada."""
    cat = {m['id']: m for m in medios.listar()}
    p = montaje.limpiar(p, cat)
    clips = p['clips']
    if not clips:
        raise ValueError('El montaje está vacío: añade al menos un clip.')

    W, H = p['lienzo']['w'], p['lienzo']['h']
    FPS = p['lienzo']['fps']
    total = montaje.duracion(p)

    pistas = {t['id']: t for t in p['pistas']}
    # de abajo arriba: la última pista de la lista es la de más abajo
    orden = {t['id']: i for i, t in enumerate(reversed(p['pistas']))}
    visibles = [c for c in clips
                if pistas[c['pista']]['tipo'] == 'video'
                and not pistas[c['pista']]['oculta']
                and cat[c['medio']]['tipo'] != 'audio']
    visibles.sort(key=lambda c: (orden[c['pista']], c['t']))
    sonoros = [c for c in clips
               if not pistas[c['pista']]['muda'] and c['volumen'] > 0
               and (cat[c['medio']].get('audio') or cat[c['medio']]['tipo'] == 'audio')]

    # Una entrada de FFmpeg por clip. El recorte se hace al abrir el archivo
    # (-ss y -t), que es mucho mas rapido que leerlo entero y cortar despues.
    ent, filtros, etiquetas_v, etiquetas_a = [], [], [], []
    indice = {}
    for c in clips:
        ruta = medios.ruta(c['medio'])
        if not ruta:
            continue
        indice[c['id']] = len(ent)
        if cat[c['medio']]['tipo'] == 'imagen':
            ent.append(['-loop', '1', '-t', f'{c["dur"]:.3f}', '-i', ruta])
        else:
            ent.append(['-ss', f'{c["entrada"]:.3f}',
                        '-t', f'{c["dur"] * c["veloc"]:.3f}', '-i', ruta])

    for c in visibles:
        i = indice.get(c['id'])
        if i is None:
            continue
        cad = [_encaje(c['encaje'], W, H), 'setsar=1', f'fps={FPS}']
        if abs(c['veloc'] - 1.0) > 1e-3:
            cad.append(f'setpts=PTS/{c["veloc"]:.4f}')
        # desplaza el clip al segundo que le toca en la linea de tiempo
        cad.append(f'setpts=PTS-STARTPTS+{c["t"]:.3f}/TB')
        if c['opacidad'] < 0.999:
            cad.append(f'format=rgba,colorchannelmixer=aa={c["opacidad"]:.3f}')
        filtros.append(f'[{i}:v]' + ','.join(cad) + f'[v{i}]')
        etiquetas_v.append((i, c))

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
    for k, (i, c) in enumerate(etiquetas_v):
        fin = c['t'] + c['dur']
        sal = f'[m{k}]'
        filtros.append(
            f'{previo}[v{i}]overlay=0:0:eof_action=pass:'
            f"enable='between(t,{c['t']:.3f},{fin:.3f})'{sal}")
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
    cmd = [entorno.ffmpeg(), '-y', '-v', 'error', '-stats_period', '0.5']
    for e in ent:
        cmd += e
    cmd += ['-filter_complex', ';'.join(filtros),
            '-map', '[vout]', '-map', '[aout]',
            '-c:v', 'libx264', '-preset', preset, '-crf', crf,
            '-pix_fmt', 'yuv420p', '-r', str(FPS),
            '-c:a', 'aac', '-b:a', '192k',
            '-t', f'{total:.3f}', '-movflags', '+faststart', destino]
    return cmd, total


def exportar(p, destino, calidad='alta', avisar=None, cancelar=None):
    """Lanza FFmpeg y va informando del avance en tanto por ciento."""
    cmd, total = construir(p, destino, calidad)
    os.makedirs(os.path.dirname(destino) or '.', exist_ok=True)
    pr = subprocess.Popen(cmd + ['-progress', 'pipe:1', '-nostats'],
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          text=True, bufsize=1)
    errores = []
    hilo = threading.Thread(target=lambda: errores.append(pr.stderr.read()),
                            daemon=True)
    hilo.start()
    try:
        for linea in pr.stdout:
            if cancelar and cancelar():
                pr.kill()
                raise RuntimeError('Exportación cancelada.')
            if linea.startswith('out_time_ms=') and avisar and total > 0:
                try:
                    seg = int(linea.split('=')[1]) / 1e6
                except (ValueError, IndexError):
                    continue
                avisar(min(seg / total, 1.0))
    finally:
        pr.wait()
        hilo.join(timeout=2)

    if pr.returncode != 0:
        detalle = (errores[0] if errores else '') or ''
        raise RuntimeError('FFmpeg falló al exportar.\n' + detalle.strip()[-600:])
    return destino, total

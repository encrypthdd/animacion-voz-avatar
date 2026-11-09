# -*- coding: utf-8 -*-
"""Voz locutada para el editor, con el momento exacto de cada palabra.

Esto es lo que hace posibles los subtítulos automáticos sin transcribir nada.
Cuando la voz la genera uno mismo, el servicio devuelve, junto al audio, en qué
milisegundo empieza y acaba cada palabra. No hay que adivinar nada: los
subtítulos caen clavados porque vienen del mismo sitio que la voz.

Sobre una voz **grabada** esto no existe, y entonces sí haría falta reconocer
el habla. Es la diferencia entre las dos mitades del problema.

El trabajo pesado ya lo hace `crear.preparar()`, que guarda en caché la voz y
los tiempos por el texto y los ajustes. Aquí solo se envuelve: se pasa el audio
a un formato cómodo y se mete en la biblioteca de medios como un archivo más,
con sus palabras al lado.
"""
import json
import os
import subprocess

import crear
import entorno
import medios

AQUI = os.path.dirname(os.path.abspath(__file__))
MAX_TEXTO = 3000           # ~3 minutos locutados


def _m4a(carpeta_voz, destino):
    subprocess.run([entorno.ffmpeg(), '-y', '-v', 'error',
                    '-i', os.path.join(carpeta_voz, 'voz.mp3'),
                    '-c:a', 'aac', '-b:a', '160k', '-ac', '2', '-ar', '48000',
                    '-movflags', '+faststart', destino], check=True)


def generar(texto, voz, rate='+0%', pitch='-2Hz', nombre=None):
    """Locuta el texto y lo deja importado en la biblioteca.

    Devuelve (ficha_del_medio, palabras).
    """
    texto = ' '.join((texto or '').split())
    if len(texto) < 2:
        raise ValueError('Escribe algo que locutar.')
    if len(texto) > MAX_TEXTO:
        raise ValueError(f'El texto pasa de {MAX_TEXTO} caracteres. '
                         'Pártelo en varios trozos.')

    cfg = {'voz': voz, 'rate': rate, 'pitch': pitch}
    carpeta = crear.preparar(texto, cfg, hablar=False)
    with open(os.path.join(carpeta, 'words.json'), encoding='utf-8') as f:
        crudas = json.load(f)

    # al editor le sirve {palabra, desde, hasta}; la puntuacion se conserva
    # porque es lo que marca donde cortar una linea de subtitulo
    palabras = [{'w': p['w'], 'p': p.get('p', ''),
                 't0': round(p['t'], 3), 't1': round(p['t'] + p['d'], 3)}
                for p in crudas]
    if not palabras:
        raise ValueError('El servicio de voz no devolvió ninguna palabra.')

    tmp = os.path.join(AQUI, 'cache', 'voz_tmp')
    os.makedirs(tmp, exist_ok=True)
    suelto = os.path.join(tmp, 'voz.m4a')
    _m4a(carpeta, suelto)
    try:
        corto = texto[:38] + ('…' if len(texto) > 38 else '')
        ficha = medios.importar(suelto, nombre or f'Voz · {corto}')
        medios.guardar_palabras(ficha['id'], palabras)
        ficha = medios.ficha(medios.obtener(ficha['id']))
    finally:
        try:
            os.remove(suelto)
        except OSError:
            pass
    return ficha, palabras

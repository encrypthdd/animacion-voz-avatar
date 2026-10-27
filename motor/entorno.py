# -*- coding: utf-8 -*-
"""Resuelve lo que cambia de un equipo a otro: el binario de FFmpeg y la
tipografía de los subtítulos.

Antes estaban escritos a fuego con rutas de Windows, lo que hacía imposible
desplegar en Linux sin editar el código.

Variables de entorno:
    ESTUDIO_FFMPEG   ruta al binario. Si falta, se busca en el PATH.
    ESTUDIO_FUENTE   ruta a un .ttf para los subtítulos.
"""
import os
import shutil

AQUI = os.path.dirname(os.path.abspath(__file__))

# Tipografías candidatas, de más a menos deseable. La primera que exista gana.
# Segoe UI Black es de Microsoft y no se puede redistribuir, por eso en Linux
# se recurre a DejaVu o Liberation, que vienen en los repositorios.
FUENTES = [
    os.path.join(AQUI, 'fuentes', 'subtitulos.ttf'),       # si la empaquetas tú
    r'C:\Windows\Fonts\seguibl.ttf',                       # Segoe UI Black
    r'C:\Windows\Fonts\ariblk.ttf',                        # Arial Black
    '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf',
    '/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf',
    '/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf',
    '/System/Library/Fonts/Supplemental/Arial Black.ttf',
]


def _candidatos_ffmpeg():
    """En Windows, winget deja el binario fuera del PATH de algunas consolas."""
    import glob
    base = os.environ.get('LOCALAPPDATA', '')
    if base:
        yield from glob.glob(os.path.join(
            base, 'Microsoft', 'WinGet', 'Packages', '*FFmpeg*', '*', 'bin', 'ffmpeg.exe'))
    yield os.path.join('C:' + os.sep, 'ffmpeg', 'bin', 'ffmpeg.exe')
    yield '/usr/bin/ffmpeg'
    yield '/usr/local/bin/ffmpeg'
    yield '/snap/bin/ffmpeg'


def ffmpeg():
    """Ruta del binario de FFmpeg. Lanza error con instrucciones si no está."""
    env = os.environ.get('ESTUDIO_FFMPEG')
    if env and os.path.isfile(env):
        return env
    hallado = shutil.which('ffmpeg')
    if hallado:
        return hallado
    for c in _candidatos_ffmpeg():
        if os.path.isfile(c):
            return c
    raise RuntimeError(
        'No se encuentra FFmpeg. Instálalo y asegúrate de que esté en el PATH:\n'
        '  Ubuntu:  sudo apt install ffmpeg\n'
        '  Windows: winget install --id Gyan.FFmpeg -e\n'
        'O indica la ruta con la variable ESTUDIO_FFMPEG.')


def fuente():
    """Ruta a la tipografía de los subtítulos."""
    env = os.environ.get('ESTUDIO_FUENTE')
    if env and os.path.isfile(env):
        return env
    for f in FUENTES:
        if os.path.isfile(f):
            return f
    raise RuntimeError(
        'No se encuentra ninguna tipografía para los subtítulos.\n'
        '  Ubuntu: sudo apt install fonts-dejavu-core\n'
        'O indica un .ttf con la variable ESTUDIO_FUENTE.')

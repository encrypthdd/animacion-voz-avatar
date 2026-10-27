# -*- coding: utf-8 -*-
"""Un guion -> un video.

    python crear.py guiones/mi_video.txt
    python crear.py guiones/mi_video.txt ../salida/otro_nombre.mp4

El guion puede llevar opciones en las primeras lineas:

    # titulo: 3 ganchos que no fallan
    # voz: es-MX-JorgeNeural
    # fondo: violeta
    # planos: si
"""
import asyncio, hashlib, json, os, subprocess, sys, time
import numpy as np
import edge_tts

import entorno

FF = entorno.ffmpeg()
AQUI = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(AQUI, 'cache')

POR_DEFECTO = {'voz': 'es-MX-JorgeNeural', 'rate': '+9%', 'pitch': '-2Hz',
               'fondo': 'violeta', 'planos': 'si', 'titulo': '',
               'recursos': 'si', 'avatar': 'base'}
SI = {'si', 'sí', 'true', '1', 'yes'}
NO = {'no', 'false', '0'}


def leer_guion(ruta):
    """Separa la cabecera de opciones del texto a locutar."""
    cfg = dict(POR_DEFECTO)
    lineas, texto = open(ruta, encoding='utf-8').read().splitlines(), []
    for ln in lineas:
        s = ln.strip()
        if s.startswith('#') and ':' in s:
            k, v = s[1:].split(':', 1)
            cfg[k.strip().lower()] = v.strip()
        elif s:
            texto.append(s)
    v = str(cfg['planos']).strip().lower()
    # `planos` admite si / no / el nombre de un plano fijo
    cfg['planos'] = True if v in SI else (False if v in NO else v)
    # `recursos` admite si / no / lista de poses separadas por comas
    r = str(cfg['recursos']).strip().lower()
    cfg['recursos'] = True if r in SI else (False if r in NO else r)
    return cfg, ' '.join(texto)


async def _voz(texto, cfg, destino):
    c = edge_tts.Communicate(texto, cfg['voz'], rate=cfg['rate'], pitch=cfg['pitch'],
                             boundary="WordBoundary")
    pal = []
    with open(os.path.join(destino, 'voz.mp3'), 'wb') as f:
        async for ch in c.stream():
            if ch["type"] == "audio":
                f.write(ch["data"])
            elif ch["type"] == "WordBoundary":
                pal.append({"t": ch["offset"]/1e7, "d": ch["duration"]/1e7,
                            "w": ch["text"]})
    # edge-tts devuelve las palabras sin puntuacion. Se recupera recorriendo el
    # texto original en paralelo, para poder cortar subtitulos y planos por frase.
    pos = 0
    for p in pal:
        i = texto.find(p["w"], pos)
        if i < 0:
            p["p"] = ""
            continue
        j = i + len(p["w"]); k = j
        while k < len(texto) and texto[k] in '.,;:!?)"\u2026\u00bb':
            k += 1
        p["p"] = texto[j:k]
        pos = j
    json.dump(pal, open(os.path.join(destino, 'words.json'), 'w', encoding='utf-8'),
              ensure_ascii=False)
    return pal


def _envolvente(destino):
    raw = os.path.join(destino, 'voz.raw')
    subprocess.run([FF, "-v", "error", "-y", "-i", os.path.join(destino, 'voz.mp3'),
                    "-ac", "1", "-ar", "16000", "-f", "s16le", raw], check=True)
    x = np.fromfile(raw, np.int16).astype(np.float32) / 32768.0
    hop = 16000 // 30
    np.save(os.path.join(destino, 'rms.npy'),
            np.array([np.sqrt((x[i*hop:(i+1)*hop]**2).mean() + 1e-12)
                      for i in range(len(x)//hop)]))
    os.remove(raw)


def preparar(texto, cfg, hablar=True):
    """Genera (o reutiliza) voz, tiempos y envolvente. Devuelve la carpeta."""
    clave = hashlib.sha1(
        (texto + '|' + cfg['voz'] + '|' + cfg['rate'] + '|' + cfg['pitch'])
        .encode('utf-8')).hexdigest()[:12]
    destino = os.path.join(CACHE, clave)
    listo = all(os.path.exists(os.path.join(destino, f))
                for f in ('voz.mp3', 'words.json', 'rms.npy'))
    if listo:
        if hablar:
            print(f"  voz en cache ({clave})")
        return destino
    os.makedirs(destino, exist_ok=True)
    if hablar:
        print(f"  voz nueva ({cfg['voz']})...")
    # El endpoint de voz de Microsoft no es oficial y rechaza peticiones de vez
    # en cuando con "No audio was received". Casi siempre va a la segunda.
    ultimo = None
    for intento in range(3):
        try:
            pal = asyncio.run(_voz(texto, cfg, destino))
            break
        except Exception as e:
            ultimo = e
            if hablar:
                print(f'  reintentando ({intento + 1}/3)…')
            time.sleep(1.5 * (intento + 1))
    else:
        raise RuntimeError(
            'El servicio de voz de Microsoft no respondió después de 3 intentos. '
            'Suele ser pasajero: vuelve a darle en un minuto. '
            f'(detalle: {ultimo})')
    _envolvente(destino)
    if hablar:
        print(f"  {len(pal)} palabras, {pal[-1]['t']+pal[-1]['d']:.1f}s")
    return destino


def procesar(ruta_guion, salida=None, hablar=True):
    import render
    cfg, texto = leer_guion(ruta_guion)
    if not texto:
        raise ValueError(f'{ruta_guion}: no hay texto que locutar')
    if salida is None:
        nombre = os.path.splitext(os.path.basename(ruta_guion))[0]
        salida = os.path.join(AQUI, '..', 'salida', nombre + '.mp4')
    os.makedirs(os.path.dirname(os.path.abspath(salida)), exist_ok=True)
    datos = preparar(texto, cfg, hablar)
    rc, v = render.producir(datos, salida, cfg, progreso=hablar)
    return rc, salida, v


if __name__ == "__main__":
    g = sys.argv[1] if len(sys.argv) > 1 else 'guiones/demo.txt'
    s = sys.argv[2] if len(sys.argv) > 2 else None
    rc, ruta, v = procesar(g, s)
    print(f'listo -> {ruta} (ffmpeg {rc}) | {len(v.planos)} planos')

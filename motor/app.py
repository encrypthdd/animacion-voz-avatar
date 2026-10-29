# -*- coding: utf-8 -*-
"""Servidor web del estudio de avatares.

    python app.py            -> http://127.0.0.1:5000

Envuelve el motor existente: medir.py para dar de alta avatares, poses.py para
las poses de recurso, crear.py para la voz y render.py para el montaje.
"""
import asyncio, io, json, os, re, threading, time, traceback, unicodedata, uuid
import numpy as np
from flask import Flask, jsonify, request, send_file, send_from_directory, abort

import avatar, crear, estilo, medir, poses, render, seguridad, sticker

AQUI = os.path.dirname(os.path.abspath(__file__))
WEB = os.path.join(AQUI, 'web')
SALIDA = os.path.join(AQUI, '..', 'salida')
MUESTRAS = os.path.join(AQUI, 'cache', 'muestras')
STICKERS = os.path.join(SALIDA, 'stickers')
LOGOS = os.path.join(AQUI, 'cache', 'logos')
TAMANOS = [3, 4, 5, 6, 7, 8, 9, 10]      # lado del sticker, en centimetros

app = Flask(__name__, static_folder=None)
CLAVE, CLAVE_GENERADA = seguridad.configurar(app, SALIDA)

TRABAJOS = {}
_lock = threading.Lock()
_voces = None


# ----------------------------------------------------------------- utilidades
def limpio(nombre, defecto='avatar'):
    """Nombre de archivo seguro y sin acentos."""
    base = os.path.splitext(os.path.basename(nombre))[0]
    base = unicodedata.normalize('NFKD', base).encode('ascii', 'ignore').decode()
    base = re.sub(r'[^A-Za-z0-9_-]+', '_', base).strip('_').lower()
    return base[:40] or defecto


def voces():
    global _voces
    if _voces is None:
        todas = asyncio.run(__import__('edge_tts').list_voices())
        _voces = []
        for v in todas:
            if not v['Locale'].startswith('es-'):
                continue
            _voces.append({
                'id': v['ShortName'],
                'genero': 'femenino' if v['Gender'] == 'Female' else 'masculino',
                'pais': v['LocaleName'].split('(')[-1].rstrip(')').strip(),
                'locale': v['Locale'],
            })
        _voces.sort(key=lambda v: (v['pais'], v['genero'], v['id']))
    return _voces


def estado_avatares():
    rigs = []
    for n in avatar.disponibles():
        d = np.load(os.path.join(avatar.RIGS, n + '.npz'))
        alt = d['mouth_line'] - d['mouth_top']
        diente = float(alt[len(alt) // 2]); sep = float(d['eye_sep'])
        aviso = ''
        if diente < 0.05 * sep:
            aviso = 'Poco diente visible: el cierre de labios en M, B y P será flojo.'
        rigs.append({'nombre': n, 'img': f'/media/rigs/{n}.png',
                     'check': f'/media/rigs/{n}_check.png', 'aviso': aviso,
                     'diente': round(diente, 1)})
    recursos = [{'nombre': n, 'img': f'/media/poses/{n}.png'}
                for n in sorted(poses.cargar())]
    return rigs, recursos


# ----------------------------------------------------------------- paginas
@app.route('/')
def index():
    return send_from_directory(WEB, 'index.html')


@app.route('/stickers')
def pagina_stickers():
    return send_from_directory(WEB, 'stickers.html')


@app.route('/web/<path:ruta>')
def estaticos(ruta):
    return send_from_directory(WEB, ruta)


@app.route('/media/<path:ruta>')
def media(ruta):
    destino = os.path.normpath(os.path.join(AQUI, ruta))
    if not destino.startswith(AQUI) or not os.path.isfile(destino):
        abort(404)
    return send_file(destino)


# ----------------------------------------------------------------- API
@app.get('/api/inicio')
def api_inicio():
    rigs, recursos = estado_avatares()
    fondos = [{'id': n,
               'css': f'linear-gradient(160deg,rgb{tuple(top)},rgb{tuple(bot)})'}
              for n, (top, bot, _) in estilo.FONDOS.items()]
    return jsonify({'voces': voces(), 'fondos': fondos,
                    'planos': list(estilo.PLANOS), 'avatares': rigs,
                    'recursos': recursos})


@app.post('/api/avatar')
def api_avatar():
    f = request.files.get('archivo')
    if not f or not f.filename:
        return jsonify({'ok': False, 'error': 'No llegó ningún archivo.'}), 400
    nombre = limpio(request.form.get('nombre') or f.filename)
    os.makedirs(medir.AQUI, exist_ok=True)
    carpeta = os.path.join(AQUI, 'avatares')
    os.makedirs(carpeta, exist_ok=True)
    ext = os.path.splitext(f.filename)[1].lower() or '.png'
    if ext not in ('.png', '.jpg', '.jpeg', '.webp'):
        return jsonify({'ok': False, 'error': 'Formato no admitido. Usa PNG, JPG o WEBP.'}), 400
    ruta = os.path.join(carpeta, nombre + ext)
    f.save(ruta)
    mal = seguridad.revisar_imagen(ruta)
    if mal:
        os.remove(ruta)
        return jsonify({'ok': False, 'error': mal}), 400
    try:
        d, _ = medir.medir(ruta, nombre)
    except medir.NoMedible as e:
        return jsonify({'ok': False, 'nombre': nombre, 'medible': False,
                        'error': str(e)}), 200
    except Exception as e:
        return jsonify({'ok': False, 'error': f'No se pudo procesar: {e}'}), 500
    avatar._cache.pop(nombre, None)
    alt = d['mouth_line'] - d['mouth_top']
    diente = float(alt[len(alt) // 2]); sep = float(d['eye_sep'])
    aviso = ''
    if int(d['mouth_x1']) - int(d['mouth_x0']) < 0.9 * sep:
        aviso = 'La boca detectada es estrecha. Revisa la imagen de control.'
    elif diente < 0.05 * sep:
        aviso = 'Poco diente visible: el cierre de labios en M, B y P será flojo.'
    sello = int(time.time())
    return jsonify({'ok': True, 'medible': True, 'nombre': nombre, 'aviso': aviso,
                    'diente': round(diente, 1),
                    'img': f'/media/rigs/{nombre}.png?t={sello}',
                    'check': f'/media/rigs/{nombre}_check.png?t={sello}'})


@app.post('/api/pose')
def api_pose():
    f = request.files.get('archivo')
    if not f or not f.filename:
        return jsonify({'ok': False, 'error': 'No llegó ningún archivo.'}), 400
    nombre = limpio(request.form.get('nombre') or f.filename)
    os.makedirs(poses.FUENTE, exist_ok=True)
    ext = os.path.splitext(f.filename)[1].lower() or '.png'
    ruta = os.path.join(poses.FUENTE, nombre + ext)
    f.save(ruta)
    mal = seguridad.revisar_imagen(ruta)
    if mal:
        os.remove(ruta)
        return jsonify({'ok': False, 'error': mal}), 400
    try:
        im, _ = poses.recortar(ruta)
        os.makedirs(poses.DESTINO, exist_ok=True)
        im.save(os.path.join(poses.DESTINO, nombre + '.png'))
        cat = {}
        if os.path.exists(poses.CATALOGO):
            cat = json.load(open(poses.CATALOGO, encoding='utf-8'))
        cat[nombre] = {'archivo': nombre + '.png', 'w': im.width, 'h': im.height,
                       'origen': os.path.basename(ruta)}
        json.dump(cat, open(poses.CATALOGO, 'w', encoding='utf-8'),
                  ensure_ascii=False, indent=1)
        poses._cache.clear()
    except Exception as e:
        return jsonify({'ok': False, 'error': f'No se pudo recortar: {e}'}), 500
    return jsonify({'ok': True, 'nombre': nombre,
                    'img': f'/media/poses/{nombre}.png?t={int(time.time())}'})


@app.get('/api/muestra')
def api_muestra():
    """Breve muestra de voz para poder elegirla escuchando."""
    vid = request.args.get('voz', '')
    if vid not in {v['id'] for v in voces()}:
        abort(404)
    os.makedirs(MUESTRAS, exist_ok=True)
    ruta = os.path.join(MUESTRAS, vid + '.mp3')
    if not os.path.exists(ruta):
        texto = 'Hola, así sueno yo. Con esta voz puedo narrar tu video.'
        async def gen():
            import edge_tts
            c = edge_tts.Communicate(texto, vid, rate='+9%', pitch='-2Hz')
            with open(ruta, 'wb') as fh:
                async for ch in c.stream():
                    if ch['type'] == 'audio':
                        fh.write(ch['data'])
        try:
            asyncio.run(gen())
        except Exception as e:
            return jsonify({'error': str(e)}), 502
    return send_file(ruta, mimetype='audio/mpeg')


def _trabajar(tid, cfg, texto, salida):
    def paso(estado, pct, msg):
        with _lock:
            TRABAJOS[tid].update(estado=estado, pct=pct, mensaje=msg)
    try:
        paso('voz', 4, 'Generando la voz…')
        datos = crear.preparar(texto, cfg, hablar=False)
        pal = json.load(open(os.path.join(datos, 'words.json'), encoding='utf-8'))
        dur = (pal[-1]['t'] + pal[-1]['d']) if pal else 0
        if dur > seguridad.MAX_SEGUNDOS:
            raise RuntimeError(f'El guion da {dur:.0f} s de video y el máximo son '
                               f'{seguridad.MAX_SEGUNDOS} s. Acórtalo.')
        paso('render', 8, 'Montando el video…')

        def cb(i, total):
            paso('render', 8 + int(88 * i / max(total, 1)),
                 f'Montando el video… {int(100*i/max(total,1))}%')

        rc, v = render.producir(datos, salida, cfg, progreso=False, cb=cb)
        if rc != 0:
            raise RuntimeError(f'ffmpeg devolvió {rc}')
        with _lock:
            TRABAJOS[tid].update(estado='listo', pct=100, mensaje='Listo',
                                 video=f'/media/../salida/{os.path.basename(salida)}',
                                 planos=[{'tipo': n, 'desde': round(f0/30, 1),
                                          'hasta': round(f1/30, 1)}
                                         for f0, f1, n, _ in v.planos],
                                 duracion=round(v.NF / 30, 1))
    except Exception as e:
        traceback.print_exc()
        with _lock:
            TRABAJOS[tid].update(estado='error', pct=0, mensaje=str(e))
    finally:
        seguridad.soltar_turno()


@app.post('/api/generar')
def api_generar():
    d = request.get_json(force=True, silent=True) or {}
    texto = (d.get('guion') or '').strip()
    if len(texto) < 10:
        return jsonify({'error': 'Escribe un guion de al menos 10 caracteres.'}), 400
    if len(texto) > seguridad.MAX_CARACTERES:
        return jsonify({'error': 'El guion es demasiado largo (máximo '
                        f'{seguridad.MAX_CARACTERES} caracteres).'}), 400
    elegidos = [n for n in (d.get('avatares') or []) if n in avatar.disponibles()]
    if not elegidos:
        return jsonify({'error': 'Elige al menos un avatar que pueda hablar.'}), 400
    vid = d.get('voz')
    if vid not in {v['id'] for v in voces()}:
        return jsonify({'error': 'Voz no válida.'}), 400

    cfg = dict(crear.POR_DEFECTO)
    cfg.update(voz=vid, titulo=(d.get('titulo') or '').strip(),
               fondo=d.get('fondo') if d.get('fondo') in estilo.FONDOS else 'violeta',
               avatar=','.join(elegidos))
    pl = d.get('planos', 'si')
    cfg['planos'] = True if pl == 'si' else (False if pl == 'no' else pl)
    cfg['recursos'] = bool(d.get('recursos', True))
    try:
        cfg['rate'] = f"{int(d.get('velocidad', 9)):+d}%"
    except (TypeError, ValueError):
        cfg['rate'] = '+9%'

    if not seguridad.tomar_turno():
        return jsonify({'error': 'El servidor está montando otros videos. '
                        'Prueba en un par de minutos.'}), 429

    tid = uuid.uuid4().hex
    os.makedirs(SALIDA, exist_ok=True)
    seguridad.purgar_videos(SALIDA)
    salida = os.path.join(SALIDA, f'web_{tid}.mp4')
    with _lock:
        TRABAJOS[tid] = {'estado': 'cola', 'pct': 0, 'mensaje': 'En cola…',
                         'archivo': salida}
    try:
        threading.Thread(target=_trabajar, args=(tid, cfg, texto, salida),
                         daemon=True).start()
    except Exception:
        seguridad.soltar_turno()
        raise
    return jsonify({'id': tid})


@app.get('/api/trabajo/<tid>')
def api_trabajo(tid):
    with _lock:
        t = TRABAJOS.get(tid)
    if not t:
        abort(404)
    r = {k: v for k, v in t.items() if k != 'archivo'}
    if t['estado'] == 'listo':
        r['video'] = f'/video/{tid}.mp4'
        r['descarga'] = f'/descargar/{tid}'
    return jsonify(r)


@app.get('/video/<tid>.mp4')
def api_video(tid):
    with _lock:
        t = TRABAJOS.get(tid)
    if not t or not os.path.exists(t['archivo']):
        abort(404)
    return send_file(t['archivo'], mimetype='video/mp4', conditional=True)


@app.get('/descargar/<tid>')
def api_descargar(tid):
    with _lock:
        t = TRABAJOS.get(tid)
    if not t or not os.path.exists(t['archivo']):
        abort(404)
    return send_file(t['archivo'], mimetype='video/mp4', as_attachment=True,
                     download_name='avatar.mp4')


# ----------------------------------------------------------------- stickers
def _trabajar_sticker(tid, origen, nombre, cm, borde_mm):
    def paso(pct, msg):
        with _lock:
            TRABAJOS[tid].update(estado='trabajando', pct=pct, mensaje=msg)
    try:
        r = sticker.procesar(origen, nombre=nombre, cm=cm, borde_mm=borde_mm,
                             destino=os.path.join(STICKERS, 'web_' + tid),
                             con_revision=False, cb=paso)
        with _lock:
            TRABAJOS[tid].update(estado='listo', pct=100, mensaje='Listo',
                                 carpeta=r['carpeta'], datos=r,
                                 archivos={n for n in (r.get('png'), r.get('svg'),
                                                       r.get('fiel')) if n})
        try:
            os.remove(origen)          # salio bien: el logo subido ya no hace falta
        except OSError:
            pass
    except Exception as e:
        # Al fallar NO se borra: sin la imagen no hay forma de averiguar por que
        # no se reconocio. La purga de la siguiente subida se la lleva.
        traceback.print_exc()
        print('sticker: fallo con %s' % origen)
        with _lock:
            TRABAJOS[tid].update(estado='error', pct=0, mensaje=str(e))
    finally:
        seguridad.soltar_turno()


@app.post('/api/sticker')
def api_sticker():
    f = request.files.get('archivo')
    if not f or not f.filename:
        return jsonify({'error': 'No llegó ningún archivo.'}), 400
    try:
        cm = int(request.form.get('cm', 10))
    except (TypeError, ValueError):
        cm = 0
    if cm not in TAMANOS:
        return jsonify({'error': 'Tamaño no válido. Elige uno de la lista.'}), 400
    borde_mm = 2.0 if request.form.get('borde') == '1' else 0.0

    ext = os.path.splitext(f.filename)[1].lower()
    if ext not in ('.png', '.jpg', '.jpeg', '.webp'):
        return jsonify({'error': 'Formato no admitido. Usa PNG, JPG o WEBP.'}), 400
    nombre = limpio(f.filename, 'logo')
    tid = uuid.uuid4().hex
    os.makedirs(LOGOS, exist_ok=True)
    seguridad.purgar_sueltos(LOGOS, horas=1)
    origen = os.path.join(LOGOS, 'web_' + tid + ext)
    f.save(origen)
    # Un logotipo no necesita ser alto como un avatar, pero por debajo de
    # 300 px no hay forma de sacar un trazado decente para imprimir.
    mal = seguridad.revisar_imagen(origen, minimo=(300, 300),
                                   uso='para vectorizarla con calidad de imprenta')
    if mal:
        os.remove(origen)
        return jsonify({'error': mal}), 400

    if not seguridad.tomar_turno():
        os.remove(origen)
        return jsonify({'error': 'El servidor está ocupado con otros trabajos. '
                        'Prueba en un par de minutos.'}), 429

    os.makedirs(STICKERS, exist_ok=True)
    seguridad.purgar_carpetas(STICKERS)
    with _lock:
        TRABAJOS[tid] = {'estado': 'cola', 'pct': 0, 'mensaje': 'En cola…',
                         'tipo': 'sticker', 'archivos': set()}
    try:
        threading.Thread(target=_trabajar_sticker,
                         args=(tid, origen, nombre, cm, borde_mm),
                         daemon=True).start()
    except Exception:
        seguridad.soltar_turno()
        raise
    return jsonify({'id': tid})


@app.get('/api/trabajo-sticker/<tid>')
def api_trabajo_sticker(tid):
    with _lock:
        t = TRABAJOS.get(tid)
    if not t or t.get('tipo') != 'sticker':
        abort(404)
    r = {'estado': t['estado'], 'pct': t['pct'], 'mensaje': t['mensaje']}
    if t['estado'] == 'listo':
        d = t['datos']
        r['resultado'] = {
            'png': f'/media-sticker/{tid}/{d["png"]}',
            'svg': f'/media-sticker/{tid}/{d["svg"]}' if d.get('svg') else None,
            'fiel': f'/media-sticker/{tid}/{d["fiel"]}',
            'nombre_png': d['png'], 'nombre_svg': d.get('svg'),
            'tipo': d['tipo'], 'planitud': d['planitud'],
            'ppp_real': d['ppp_real'],
            'px': d['px'], 'cm': d['cm_real'], 'ppp': d['ppp'],
            'cm_pedido': d['cm'], 'borde_mm': d['borde_mm'],
            'metodo': sticker.METODOS.get(d['metodo'], d['metodo']),
            'fiable': d['metodo'] != 'modelo',
            'curvas': d['curvas'], 'capas': d['capas'], 'paleta': d['paleta'],
            'svg_kb': d['svg_kb'], 'soporte': d['soporte'], 'recorte': d['recorte'],
        }
    return jsonify(r)


@app.get('/media-sticker/<tid>/<nombre>')
def api_sticker_archivo(tid, nombre):
    """Sirve un resultado. El nombre se compara con los que produjo el trabajo,
    así que no hay forma de pedir un archivo de fuera de su carpeta."""
    with _lock:
        t = TRABAJOS.get(tid)
    if not t or t.get('tipo') != 'sticker' or nombre not in t.get('archivos', ()):
        abort(404)
    ruta = os.path.join(t['carpeta'], nombre)
    if not os.path.isfile(ruta):
        abort(404)
    tipo = 'image/svg+xml' if nombre.endswith('.svg') else 'image/png'
    return send_file(ruta, mimetype=tipo,
                     as_attachment=request.args.get('descargar') == '1',
                     download_name=nombre, conditional=True)


if __name__ == '__main__':
    print('Estudio de avatares -> http://127.0.0.1:5000')
    if CLAVE_GENERADA:
        print()
        print('  No hay ESTUDIO_CLAVE, así que se generó una para esta sesión:')
        print(f'      {CLAVE}')
        print('  Cambia al arrancar. Para fijarla:  set ESTUDIO_CLAVE=tu-clave')
        print()
    app.run(host='127.0.0.1', port=5000, threaded=True, debug=False)

# -*- coding: utf-8 -*-
"""Capa de seguridad de la aplicación web.

Lo que esto cubre: autenticación, abuso de CPU, entradas maliciosas y cabeceras.
Lo que NO cubre: un DDoS de verdad. Eso se para antes de llegar aquí, en nginx
o en Cloudflare — un proceso de Python no puede defenderse de saturación de red.

Variables de entorno:
    ESTUDIO_CLAVE     contraseña de acceso. Sin ella se genera una al arrancar
                      y se imprime en consola (cómodo en local, inútil en red).
    ESTUDIO_SECRETO   clave de firma de las sesiones. Si falta se guarda una
                      aleatoria en cache/.secreto.
    ESTUDIO_PROXY=1   confiar en X-Forwarded-For. Actívalo SOLO si hay un proxy
                      inverso delante; si no, cualquiera falsea su IP y se salta
                      los límites por IP.
    ESTUDIO_HTTPS=1   marca la cookie como Secure. Actívalo al servir por HTTPS.
"""
import hmac, os, secrets, threading, time
from functools import wraps

from flask import jsonify, redirect, request, send_from_directory, session

AQUI = os.path.dirname(os.path.abspath(__file__))
WEB = os.path.join(AQUI, 'web')

# ─── Límites de gasto ───────────────────────────────────────────────────────
MAX_CARACTERES = 1500      # 4000 daban un video de 276 s = 38 min de CPU
MAX_SEGUNDOS = 100         # se comprueba con la duración real, ya locutada
MAX_RENDERS = 2            # renders a la vez; cada uno ocupa un núcleo entero
MAX_PIXELES = 40_000_000   # contra bombas de descompresión (un PNG de 20k×20k)
MAX_LADO = 6000
HORAS_VIDEO = 12           # los videos se borran pasado este tiempo

# peticiones permitidas por ventana, por IP
LIMITES = {
    'generar': (6, 900),       # 6 cada 15 min: es lo caro
    'sticker': (15, 900),      # vectorizar cuesta ~25 s, menos que un video
    'subir':   (20, 900),
    'muestra': (60, 900),
    'entrar':  (8, 900),       # contra fuerza bruta
    'general': (300, 60),
}
# Ojo con los prefijos: el sondeo del progreso y las descargas van por rutas
# distintas (/api/trabajo-sticker, /media-sticker) justamente para que no
# consuman el cupo de 'sticker', que es el de crear uno nuevo.
RUTAS = {
    '/api/generar': 'generar', '/api/avatar': 'subir', '/api/pose': 'subir',
    '/api/sticker': 'sticker', '/api/muestra': 'muestra', '/entrar': 'entrar',
}

_cubos = {}
_lock = threading.Lock()
_renders = threading.BoundedSemaphore(MAX_RENDERS)
_ultima_purga = [0.0]


# ─── Identidad del cliente ──────────────────────────────────────────────────
def _ip():
    """Con proxy delante, la IP real va en X-Forwarded-For. Sin proxy, ese
    encabezado lo pone el atacante: por eso solo se mira si se activa."""
    if os.environ.get('ESTUDIO_PROXY') == '1':
        reenviada = request.headers.get('X-Forwarded-For', '')
        if reenviada:
            return reenviada.split(',')[0].strip()[:45]
    return request.remote_addr or '?'


# ─── Límite de peticiones ───────────────────────────────────────────────────
def _grupo(ruta):
    for pre, g in RUTAS.items():
        if ruta.startswith(pre):
            return g
    return 'general'


def _permitido(ip, grupo):
    tope, ventana = LIMITES[grupo]
    ahora = time.time()
    with _lock:
        if ahora - _ultima_purga[0] > 300:           # no crecer sin fin
            for k, v in list(_cubos.items()):
                if not v or ahora - v[-1] > 3600:
                    _cubos.pop(k, None)
            _ultima_purga[0] = ahora
        clave = (ip, grupo)
        marcas = [t for t in _cubos.get(clave, []) if ahora - t < ventana]
        if len(marcas) >= tope:
            _cubos[clave] = marcas
            return False, int(ventana - (ahora - marcas[0])) + 1
        marcas.append(ahora)
        _cubos[clave] = marcas
        return True, 0


# ─── Imágenes ───────────────────────────────────────────────────────────────
def revisar_imagen(ruta, minimo=(120, 240), uso='para medir la cara'):
    """Devuelve None si la imagen es sana, o el motivo del rechazo.

    No basta con mirar la extensión: cualquiera renombra un archivo. Se abre de
    verdad y se comprueba el formato y el tamaño, porque una imagen enorme tumba
    el proceso al descomprimirla aunque pese poco en disco.

    El mínimo cambia según para qué se suba: un avatar necesita alto (es una
    persona de cuerpo entero), un logotipo no.
    """
    from PIL import Image
    Image.MAX_IMAGE_PIXELS = MAX_PIXELES
    try:
        with Image.open(ruta) as im:
            fmt, (an, al) = im.format, im.size
            im.verify()
    except Image.DecompressionBombError:
        # Pillow corta antes de reservar memoria: un PNG de 9000x9000 pesa
        # 250 KB en disco y 243 MB al descomprimirlo.
        return ('La imagen declara demasiados píxeles y se ha rechazado sin '
                'abrirla. El máximo son %.0f millones.' % (MAX_PIXELES / 1e6))
    except Exception:
        return 'El archivo no es una imagen válida.'
    if fmt not in ('PNG', 'JPEG', 'WEBP'):
        return f'Formato {fmt or "desconocido"} no admitido. Usa PNG, JPG o WEBP.'
    if an * al > MAX_PIXELES:
        return f'La imagen es demasiado grande ({an}×{al}).'
    if an > MAX_LADO or al > MAX_LADO:
        return f'Ningún lado puede pasar de {MAX_LADO} px (esta es {an}×{al}).'
    if an < minimo[0] or al < minimo[1]:
        return f'La imagen es muy pequeña ({an}×{al}) {uso}.'
    return None


# ─── Renders simultáneos ────────────────────────────────────────────────────
def tomar_turno(espera=0):
    """Reserva uno de los huecos de render. False si están todos ocupados."""
    return _renders.acquire(blocking=bool(espera), timeout=espera or None)


def soltar_turno():
    try:
        _renders.release()
    except ValueError:
        pass


def huecos_libres():
    return _renders._value


# ─── Limpieza de disco ──────────────────────────────────────────────────────
def purgar_carpetas(raiz, horas=HORAS_VIDEO, prefijo='web_'):
    """Borra las carpetas de resultados que la web dejó y ya nadie va a bajar.

    Cada sticker deja una carpeta con varios archivos, así que aquí se borra el
    árbol entero y no archivo a archivo.
    """
    import shutil
    if not os.path.isdir(raiz):
        return 0
    limite = time.time() - horas * 3600
    n = 0
    for d in os.listdir(raiz):
        if not d.startswith(prefijo):
            continue
        p = os.path.join(raiz, d)
        try:
            if os.path.isdir(p) and os.path.getmtime(p) < limite:
                shutil.rmtree(p, ignore_errors=True); n += 1
        except OSError:
            pass
    return n


def purgar_sueltos(carpeta, horas=HORAS_VIDEO, prefijo='web_'):
    """Lo mismo, pero para los archivos sueltos (los logos recién subidos)."""
    if not os.path.isdir(carpeta):
        return 0
    limite = time.time() - horas * 3600
    n = 0
    for f in os.listdir(carpeta):
        p = os.path.join(carpeta, f)
        try:
            if f.startswith(prefijo) and os.path.isfile(p) and os.path.getmtime(p) < limite:
                os.remove(p); n += 1
        except OSError:
            pass
    return n


def purgar_videos(carpeta, horas=HORAS_VIDEO):
    """Borra los videos generados por la web que ya nadie va a descargar."""
    if not os.path.isdir(carpeta):
        return 0
    limite = time.time() - horas * 3600
    n = 0
    for f in os.listdir(carpeta):
        if not (f.startswith('web_') and f.endswith('.mp4')):
            continue
        p = os.path.join(carpeta, f)
        try:
            if os.path.getmtime(p) < limite:
                os.remove(p); n += 1
        except OSError:
            pass
    return n


# ─── Sesión ─────────────────────────────────────────────────────────────────
def _secreto():
    env = os.environ.get('ESTUDIO_SECRETO')
    if env:
        return env.encode()
    ruta = os.path.join(AQUI, 'cache', '.secreto')
    os.makedirs(os.path.dirname(ruta), exist_ok=True)
    if os.path.exists(ruta):
        return open(ruta, 'rb').read()
    s = secrets.token_bytes(32)
    with open(ruta, 'wb') as f:
        f.write(s)
    try:
        os.chmod(ruta, 0o600)
    except OSError:
        pass
    return s


def configurar(app, salida):
    clave = os.environ.get('ESTUDIO_CLAVE')
    generada = not clave
    if generada:
        clave = secrets.token_urlsafe(9)

    app.secret_key = _secreto()
    app.config.update(
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE='Lax',
        SESSION_COOKIE_SECURE=os.environ.get('ESTUDIO_HTTPS') == '1',
        PERMANENT_SESSION_LIFETIME=12 * 3600,
        MAX_CONTENT_LENGTH=40 * 1024 * 1024,
    )
    if os.environ.get('ESTUDIO_PROXY') == '1':
        from werkzeug.middleware.proxy_fix import ProxyFix
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

    libres = {'/entrar'}

    @app.before_request
    def _portero():
        ruta = request.path
        ok, espera = _permitido(_ip(), _grupo(ruta))
        if not ok:
            r = jsonify({'error': f'Demasiadas peticiones. Prueba en {espera} s.'})
            r.status_code = 429
            r.headers['Retry-After'] = str(espera)
            return r
        if ruta in libres:
            return None
        if not session.get('ok'):
            if ruta.startswith('/api/'):
                return jsonify({'error': 'Sesión caducada.', 'entrar': True}), 401
            return redirect('/entrar')
        return None

    @app.after_request
    def _cabeceras(r):
        r.headers['X-Content-Type-Options'] = 'nosniff'
        r.headers['X-Frame-Options'] = 'DENY'
        r.headers['Referrer-Policy'] = 'no-referrer'
        r.headers['Permissions-Policy'] = 'camera=(), microphone=(), geolocation=()'
        r.headers['Content-Security-Policy'] = (
            "default-src 'self'; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
            "font-src 'self' https://fonts.gstatic.com; "
            # blob: lo necesita el creador de stickers para enseñar el logo
            # recién elegido sin tener que subirlo antes al servidor.
            "img-src 'self' data: blob:; media-src 'self'; "
            "script-src 'self'; frame-ancestors 'none'; base-uri 'none'; "
            "form-action 'self'")
        return r

    @app.route('/entrar', methods=['GET', 'POST'])
    def entrar():
        if request.method == 'GET':
            return send_from_directory(WEB, 'entrar.html')
        dada = (request.form.get('clave') or '')[:200]
        # compare_digest evita filtrar la clave por el tiempo de respuesta
        if hmac.compare_digest(dada, clave):
            session.permanent = True
            session['ok'] = True
            return redirect('/')
        return send_from_directory(WEB, 'entrar.html'), 401

    @app.route('/salir')
    def salir():
        session.clear()
        return redirect('/entrar')

    return clave, generada

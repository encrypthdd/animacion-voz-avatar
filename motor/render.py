# -*- coding: utf-8 -*-
"""Compone el video: camara, fondo, subtitulos y codificacion."""
import json, math, os, subprocess, sys
import numpy as np
from PIL import Image, ImageDraw, ImageFont
import avatar, anim, entorno, estilo, poses
import entorno

W, H, FPS = 1080, 1920, 30
FF = entorno.ffmpeg()
DURO = set('.;:!?\u2026')          # fin de frase


def camara(base, esc, fx, fy, cx, cy):
    """Recorta de la imagen base SOLO lo que entra en el lienzo y lo escala.
    Asi el coste depende del lienzo, no del zoom."""
    x0, x1 = (0 - cx) / esc + fx, (W - cx) / esc + fx
    y0, y1 = (0 - cy) / esc + fy, (H - cy) / esc + fy
    ix0, iy0 = max(int(math.floor(x0)), 0), max(int(math.floor(y0)), 0)
    ix1 = min(int(math.ceil(x1)) + 1, base.width)
    iy1 = min(int(math.ceil(y1)) + 1, base.height)
    if ix1 <= ix0 or iy1 <= iy0:
        return None, (0, 0)
    rec = base.crop((ix0, iy0, ix1, iy1))
    ow = max(1, int(round((ix1 - ix0) * esc)))
    oh = max(1, int(round((iy1 - iy0) * esc)))
    rec = rec.resize((ow, oh), Image.BICUBIC)
    return rec, (int(round(cx + (ix0 - fx) * esc)), int(round(cy + (iy0 - fy) * esc)))


class Video:
    def __init__(self, datos='.', cfg=None):
        self.cfg = cfg or {}
        self.datos = datos
        self.A = anim.build(os.path.join(datos, 'rms.npy'),
                            os.path.join(datos, 'words.json'))
        self.NF = self.A['NF']
        nombres = [n.strip() for n in str(self.cfg.get('avatar', 'base')).split(',')
                   if n.strip()]
        disp = avatar.disponibles()
        nombres = [n for n in nombres if n in disp] or (['base'] if 'base' in disp
                                                        else disp[:1])
        if not nombres:
            raise RuntimeError('no hay ningun avatar medido en rigs/ '
                               '(usa: python medir.py imagen.png nombre)')
        self.rigs = [avatar.cargar(n) for n in nombres]
        self.bg = estilo.fondo(self.cfg.get('fondo', 'violeta'), W, H)
        self.fuente = ImageFont.truetype(estilo.FUENTE, 84)
        self.f_tit = ImageFont.truetype(estilo.FUENTE, 52)
        self.words = json.load(open(os.path.join(datos, 'words.json'), encoding='utf-8'))
        self._medidor = ImageDraw.Draw(Image.new('RGB', (8, 8)))
        self.chunks = self._agrupar()
        self.planos = self._planos()

    # ---------------- subtitulos ----------------
    def _ancho(self, ws):
        return self._medidor.textlength(' '.join(x['w'] for x in ws), font=self.fuente)

    def _agrupar(self):
        chunks, cur = [], []
        for w in self.words:
            punt = w.get('p', '')
            salto = bool(cur) and (w['t'] - (cur[-1]['t'] + cur[-1]['d'])) > 0.35
            tr = cur + [w]
            if cur and (self._ancho(tr) > 950 or
                        (tr[-1]['t'] + tr[-1]['d'] - tr[0]['t']) > 1.9 or salto):
                chunks.append(cur); cur = [w]
            else:
                cur = tr
            if cur and (set(punt) & DURO or (',' in punt and self._ancho(cur) > 620)):
                chunks.append(cur); cur = []
        if cur:
            chunks.append(cur)
        # una sola palabra queda huerfana: se le pasa la ultima del grupo anterior,
        # salvo que ese grupo cierre frase (ahi el corte es intencionado)
        for i in range(1, len(chunks)):
            if len(chunks[i]) == 1 and len(chunks[i-1]) >= 3:
                ult = chunks[i-1][-1]
                if not (set(ult.get('p', '')) & DURO) and self._ancho([ult] + chunks[i]) <= 950:
                    chunks[i].insert(0, chunks[i-1].pop())
        return chunks

    def _subs(self, img, t):
        ch = next((c for c in self.chunks
                   if c[0]['t'] - .12 <= t <= c[-1]['t'] + c[-1]['d'] + .22), None)
        if not ch:
            return
        d = ImageDraw.Draw(img)
        partes = [x['w'] for x in ch]
        anchos = [d.textlength(p + ' ', font=self.fuente) for p in partes]
        x = (W - (sum(anchos) - d.textlength(' ', font=self.fuente))) / 2
        for p, pw, wo in zip(partes, anchos, ch):
            hot = wo['t'] - .05 <= t <= wo['t'] + wo['d'] + .10
            y = 1395 - (7 if hot else 0)
            d.text((x + 4, y + 6), p, font=self.fuente, fill=(0, 0, 0, 170))
            d.text((x, y), p, font=self.fuente,
                   fill=(255, 214, 10) if hot else (255, 255, 255),
                   stroke_width=9, stroke_fill=(12, 8, 24))
            x += pw

    def _titulo(self, img):
        """Capsula oscura detras: en los primeros planos el titulo caia sobre el
        pelo del personaje y se ensuciaba."""
        txt = self.cfg.get('titulo')
        if not txt:
            return
        d0 = ImageDraw.Draw(img)
        an = d0.textlength(txt, font=self.f_tit)
        x, y = (W - an) / 2, 104
        pad_x, pad_y = 34, 18
        capa = Image.new('RGBA', (W, H), (0, 0, 0, 0))
        dc = ImageDraw.Draw(capa)
        caja = [x - pad_x, y - pad_y, x + an + pad_x, y + 58 + pad_y]
        dc.rounded_rectangle(caja, radius=38, fill=(10, 6, 20, 150))
        img.paste(Image.alpha_composite(img.convert('RGBA'), capa).convert('RGB'), (0, 0))
        d = ImageDraw.Draw(img)
        d.text((x, y), txt, font=self.f_tit, fill=(255, 255, 255),
               stroke_width=5, stroke_fill=(12, 8, 24))

    # ---------------- camara ----------------
    def _planos(self):
        """Corta en finales de frase, eligiendo el mas cercano a la duracion
        objetivo. Con un minimo rigido se perdian cortes por decimas y quedaban
        planos de 6 segundos."""
        p = self.cfg.get('planos', True)
        if p is False:
            return [(0, self.NF, 'completo', 0)]
        if isinstance(p, str):
            return [(0, self.NF, p if p in estilo.PLANOS else 'completo', 0)]
        fines = sorted(int((w['t'] + w['d']) * FPS) for w in self.words
                       if set(w.get('p', '')) & DURO)
        cand = [f for f in fines if 0 < f < self.NF]
        cortes = [0]
        while True:
            resto = [f for f in cand if f > cortes[-1] + estilo.MIN_PLANO * FPS]
            if not resto:
                break
            objetivo = cortes[-1] + estilo.OBJ_PLANO * FPS
            ventana = [f for f in resto if f <= cortes[-1] + estilo.MAX_PLANO * FPS]
            cortes.append(min(ventana, key=lambda f: abs(f - objetivo))
                          if ventana else resto[0])
        cortes.append(self.NF)
        if len(cortes) > 2 and cortes[-1] - cortes[-2] < 1.3 * FPS:
            cortes.pop(-2)                       # no dejar un plano de coletilla
        plan = [[cortes[i], cortes[i+1], estilo.SECUENCIA[i % len(estilo.SECUENCIA)],
                 i % len(self.rigs)]
                for i in range(len(cortes) - 1)]
        return self._meter_recursos(plan)

    def _meter_recursos(self, plan):
        """Cambia algunos planos por una pose de recurso. El personaje no habla
        en ellas, asi que solo se usan en tramos cortos: en un corte de menos de
        tres segundos se lee como un plano de recurso, no como un fallo."""
        cfg = self.cfg.get('recursos', True)
        if cfg is False:
            return [tuple(p) for p in plan]
        disp = {n: im for n, im in poses.cargar().items()
                if n not in [r.nombre for r in self.rigs]}   # los que hablan no son recurso
        if not disp:
            return [tuple(p) for p in plan]
        if isinstance(cfg, str):
            orden = [n.strip() for n in cfg.split(',') if n.strip() in disp]
        else:
            orden = [n for n in estilo.ORDEN_RECURSOS if n in disp]
            orden += [n for n in sorted(disp) if n not in orden]
        if not orden:
            return [tuple(p) for p in plan]
        salida, k = [], 0
        for i, (f0, f1, nom, ri) in enumerate(plan):
            # el primer plano establece quien habla; luego, uno de cada tres
            elegible = i > 0 and i % 3 == 2 and (f1 - f0) / FPS >= 1.2
            if not elegible:
                salida.append((f0, f1, nom, ri))
                continue
            corte = f0 + int(min(estilo.DUR_RECURSO * FPS, f1 - f0))
            if f1 - corte < 0.5 * FPS:
                corte = f1                     # resto muy corto: la pose lo ocupa
            salida.append((f0, corte, 'pose:' + orden[k % len(orden)], ri))
            k += 1
            if corte < f1:                     # el resto vuelve al personaje
                salida.append((corte, f1, nom, ri))
        return salida

    def _plano_en(self, i):
        for f0, f1, nombre, ri in self.planos:
            if f0 <= i < f1:
                return nombre, (i - f0) / max(f1 - f0, 1), self.rigs[ri]
        return 'medio', 0.0, self.rigs[0]

    # ---------------- fotograma ----------------
    def _capa_pose(self, nombre, avance, j):
        im = poses.cargar().get(nombre)
        if im is None:
            return None, (0, 0)
        esc = (H * 0.82) / im.height * (1.0 + estilo.EMPUJE * avance)
        w = max(1, int(round(im.width * esc)))
        h = max(1, int(round(im.height * esc)))
        cap = im.resize((w, h), Image.BICUBIC)
        t = j / FPS
        dx = 4.0 * math.sin(2 * math.pi * t / 4.3)
        dy = 5.0 * math.sin(2 * math.pi * t / 3.1)      # respiracion
        return cap, (int((W - w) / 2 + dx), int(H * 0.94 - h + dy))

    def frame(self, i):
        j = min(i, self.NF - 1)
        A = self.A
        nombre, avance, rig = self._plano_en(j)
        if nombre.startswith('pose:'):
            cap, pos = self._capa_pose(nombre[5:], avance, j)
            img = self.bg.copy()
            if cap is not None:
                img.paste(cap, pos, cap)
            self._titulo(img)
            self._subs(img, i / FPS)
            return img
        base = rig.base_frame(A['jaw'][j], A['brow'][j], A['blink'][j],
                              A['tilt'][j], A['width'][j], A['close'][j])
        esc, fx, fy, cx, cy = estilo.encuadre(nombre, avance, rig, W, H)
        k = esc / (estilo.PLANOS['medio']['frac'] * H / max(rig.sujeto[3] - rig.sujeto[1], 1))
        cap, pos = camara(base, esc, fx, fy,
                          cx + A['dx'][j] * k, cy + A['dy'][j] * k)
        img = self.bg.copy()
        if cap is not None:
            img.paste(cap, pos, cap)
        self._titulo(img)
        self._subs(img, i / FPS)
        return img

    def encode(self, salida, progreso=True, cb=None):
        total = self.NF + 10
        audio = os.path.join(self.datos, 'voz.mp3')
        p = subprocess.Popen(
            [FF, '-y', '-v', 'error', '-f', 'rawvideo', '-pix_fmt', 'rgb24',
             '-s', f'{W}x{H}', '-r', str(FPS), '-i', '-', '-i', audio,
             '-c:v', 'libx264', '-preset', 'medium', '-crf', '20',
             '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-b:a', '192k',
             '-shortest', salida], stdin=subprocess.PIPE)
        try:
            for i in range(total):
                p.stdin.write(self.frame(i).tobytes())
                if cb is not None and i % 5 == 0:
                    cb(i, total)
                if progreso and i % 150 == 0:
                    print(f'  {i}/{total}', flush=True)
        except OSError:
            # Con -shortest ffmpeg cierra la entrada al agotarse el audio. En
            # Windows eso no siempre llega como BrokenPipeError: puede salir
            # como OSError errno 22, y capturar solo el primero marcaba como
            # fallido un video que estaba bien. Quien decide es el codigo de
            # salida de ffmpeg, no esta excepcion.
            pass
        try:
            p.stdin.close()
        except OSError:
            pass
        p.wait()
        return p.returncode


def producir(datos, salida, cfg=None, progreso=True, cb=None):
    v = Video(datos, cfg)
    rc = v.encode(salida, progreso, cb)
    if rc == 0 and (not os.path.exists(salida) or os.path.getsize(salida) < 10000):
        raise RuntimeError('ffmpeg terminó sin error pero el archivo está vacío')
    return rc, v


if __name__ == '__main__':
    # vista rapida de los planos del primer guion
    import glob, crear
    g = sorted(glob.glob(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                      'guiones', '*.txt')))
    if not g:
        print('no hay guiones'); sys.exit(1)
    cfg, texto = crear.leer_guion(g[0])
    v = Video(crear.preparar(texto, cfg, False), cfg)
    print(os.path.basename(g[0]), '->', len(v.planos), 'planos')
    for f0, f1, n in v.planos:
        print('  %-7s %5.1fs - %5.1fs' % (n, f0 / FPS, f1 / FPS))
    s = Image.new('RGB', (len(v.planos) * 300, 533))
    for i, (f0, f1, n) in enumerate(v.planos):
        s.paste(v.frame((f0 + f1) // 2).resize((300, 533), Image.LANCZOS), (i * 300, 0))
    s.save('planos.png')
    print('-> planos.png')

"""Genera las curvas de animacion por fotograma a partir del audio y el texto."""
import json, math
import numpy as np
import fonemas

FPS = 30

def _ss(x):                       # smoothstep
    x = np.clip(x, 0, 1); return x * x * (3 - 2 * x)

def _gauss(x, sig):
    k = np.exp(-(np.arange(-9, 10) ** 2) / (2 * sig * sig)); k /= k.sum()
    return np.convolve(np.pad(x, 9, mode='edge'), k, 'valid')

def build(rms_path='rms.npy', words_path='words.json', seed=7):
    rng = np.random.default_rng(seed)
    rms = np.load(rms_path)
    words = json.load(open(words_path, encoding='utf-8'))
    NF = len(rms)
    T = np.arange(NF) / FPS

    # ---- envolvente de audio: sirve de amplitud y de plan B ----
    p95 = np.percentile(rms, 95)
    e = np.clip(rms / max(p95, 1e-6), 0, 1.15) ** 0.75
    e = np.convolve(e, [.25, .5, .25], mode='same')
    e[rms < 0.012] = 0.0
    jaw_rms = np.clip(e * 19.0, 0, 19.0)

    # ---- visemas desde el texto ----
    # Un fonema dura ~1.8 fotogramas. Rasterizar tramos y suavizar los aplana,
    # asi que se pone una clave en el CENTRO de cada fonema y se interpola:
    # el pico llega intacto y las transiciones salen suaves igual.
    cf, co, cw, cc = [], [], [], []
    unk = np.zeros(NF, bool)
    fin_prev = None
    for w in words:
        ph = fonemas.fonemas(w['w'])
        if fin_prev is not None and w['t'] - fin_prev > 0.15:
            cf.append((fin_prev + w['t']) / 2 * FPS); co.append(0.0); cw.append(1.0); cc.append(0.0)
        if not ph:                      # numeros y simbolos: no hay grafema util
            f0 = max(int(round(w['t'] * FPS)), 0)
            f1 = min(int(round((w['t'] + w['d']) * FPS)) + 1, NF)
            unk[f0:f1] = True
            fin_prev = w['t'] + w['d']
            continue
        pes = np.array([fonemas.peso(p) for p in ph], float)
        dur = w['d'] * pes / pes.sum()
        t = w['t']
        for p, dd in zip(ph, dur):
            o, wd, cl = fonemas.objetivo(p)
            cf.append((t + dd / 2) * FPS); co.append(o); cw.append(wd); cc.append(cl)
            t += dd
        fin_prev = w['t'] + w['d']

    fr = np.arange(NF, dtype=float)
    if cf:
        jaw_v = np.interp(fr, cf, co)
        wid_v = np.interp(fr, cf, cw)
        clo_v = np.interp(fr, cf, cc)
    else:
        jaw_v, wid_v, clo_v = jaw_rms.copy(), np.ones(NF), np.zeros(NF)

    jaw_s = _gauss(np.where(unk, jaw_rms, jaw_v), 0.8)
    wid_s = _gauss(wid_v, 0.9)
    clo_s = _gauss(np.where(unk, 0.0, clo_v), 0.5)

    amp = np.clip(_gauss(np.clip(rms / max(p95, 1e-6), 0, 1.2), 3.0), 0.45, 1.15)
    GANANCIA = 1.5        # el suavizado recorta los picos; esto los recupera
    # Solo un cierre FUERTE (M/B/P) anula la apertura. La O y la U bajan el labio
    # hasta ~0.6 y deben seguir abriendo: antes `1-cierre` se las cerraba.
    supr = np.clip((clo_s - 0.55) / 0.45, 0, 1)
    jaw = jaw_s * GANANCIA * amp * (1.0 - supr)
    jaw[rms < 0.012] = 0.0
    jaw = np.clip(jaw, 0, 19.0)
    width = np.clip(wid_s, 0.70, 1.14)
    close = np.clip(clo_s, 0, 1)

    # ---- pausas (para colocar parpadeos donde caen de verdad) ----
    quiet = rms < 0.015
    pauses, i = [], 0
    while i < NF:
        if quiet[i]:
            j = i
            while j < NF and quiet[j]: j += 1
            if j - i >= 5: pauses.append(i)
            i = j
        else: i += 1

    # ---- calendario de parpadeos ----
    blink_t, last = [], -3.0
    for p in pauses:                                  # uno al entrar en cada pausa
        t = p / FPS + 0.10
        if t - last > 1.4: blink_t.append(t); last = t
    t = 0.7                                           # rellenar huecos largos
    while t < NF / FPS:
        if all(abs(t - b) > 1.5 for b in blink_t):
            blink_t.append(t); last = t
        t += rng.uniform(2.6, 5.2)
    blink_t.sort()
    doubles = {b for b in blink_t if rng.random() < 0.18}   # algun parpadeo doble

    CL, HOLD, OP = 0.085, 0.035, 0.115
    blink = np.zeros(NF)
    def stamp(t0):
        for i in range(NF):
            dt = T[i] - t0
            if dt < 0 or dt > CL + HOLD + OP: continue
            k = (_ss(dt / CL) if dt < CL else
                 1.0 if dt < CL + HOLD else
                 1.0 - _ss((dt - CL - HOLD) / OP))
            blink[i] = max(blink[i], k)
    for b in blink_t:
        stamp(b)
        if b in doubles: stamp(b + 0.26)

    # ---- acentos de ceja en palabras marcadas ----
    brow = np.zeros(NF)
    prev_end = 0.0
    for w in words:
        gap = w['t'] - prev_end
        stressed = w['d'] > 0.33 or gap > 0.26 or w['w'][:1].isupper() or w['w'].isdigit()
        prev_end = w['t'] + w['d']
        if not stressed: continue
        amp_b = float(rng.uniform(2.4, 4.3))
        a, b = w['t'] - 0.10, w['t'] + w['d']
        for i in range(NF):
            dt = T[i] - a
            if dt < 0 or dt > (b - a) + 0.22: continue
            k = (_ss(dt / 0.13) if dt < 0.13 else
                 1.0 if T[i] <= b else
                 1.0 - _ss((T[i] - b) / 0.22))
            brow[i] = max(brow[i], amp_b * k)
    brow += 0.55 + 0.45 * np.sin(2 * math.pi * T / 6.7)      # micro-movimiento de reposo
    brow = np.convolve(brow, np.ones(3) / 3, mode='same')
    brow = np.clip(brow, 0, 5.0)

    # ---- cabeza y cuerpo ----
    tilt = 0.85 * np.sin(2*math.pi*T/5.3) + 0.42 * np.sin(2*math.pi*T/3.1 + 1.0)
    dy   = 4.0 * np.sin(2*math.pi*T/3.1) + 2.5 * np.sin(2*math.pi*T/1.73) + jaw*0.22
    dx   = 3.0 * np.sin(2*math.pi*T/4.3)

    return dict(jaw=jaw, brow=brow, blink=blink, tilt=tilt, dx=dx, dy=dy,
                width=width, close=close, NF=NF,
                blinks=len(blink_t) + len(doubles), sin_fonema=float(unk.mean()))

if __name__ == '__main__':
    a = build()
    print(f"frames {a['NF']} | parpadeos {a['blinks']} "
          f"({a['blinks']/(a['NF']/FPS)*60:.0f}/min)")
    print('mand.  min %.2f max %.2f' % (a['jaw'].min(), a['jaw'].max()))
    print('ancho  min %.2f max %.2f' % (a['width'].min(), a['width'].max()))
    print('cierre max %.2f | fotogramas con cierre>0.6: %d'
          % (a['close'].max(), int((a['close'] > 0.6).sum())))
    print('ceja   min %.2f max %.2f' % (a['brow'].min(), a['brow'].max()))
    print('sin fonema %.0f%%' % (a['sin_fonema']*100))

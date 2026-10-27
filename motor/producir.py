# -*- coding: utf-8 -*-
"""Procesa por lotes todos los guiones de la carpeta `guiones/`.

    python producir.py              # solo lo que haga falta
    python producir.py --forzar     # rehace todo
    python producir.py tips ganchos # solo esos guiones
"""
import glob, os, sys, time
import crear

AQUI = os.path.dirname(os.path.abspath(__file__))
GUIONES = os.path.join(AQUI, 'guiones')
SALIDA = os.path.join(AQUI, '..', 'salida')


def hay_que_rehacer(guion, destino, forzar):
    if forzar or not os.path.exists(destino):
        return True
    return os.path.getmtime(guion) > os.path.getmtime(destino)


def main():
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    forzar = '--forzar' in sys.argv
    os.makedirs(GUIONES, exist_ok=True)
    os.makedirs(SALIDA, exist_ok=True)

    guiones = sorted(glob.glob(os.path.join(GUIONES, '*.txt')))
    if args:
        guiones = [g for g in guiones
                   if os.path.splitext(os.path.basename(g))[0] in args]
    if not guiones:
        print(f'No hay guiones en {GUIONES}')
        print('Crea un .txt ahi y vuelve a lanzarlo.')
        return

    hechos, saltados, fallos = 0, 0, []
    t0 = time.time()
    for g in guiones:
        nombre = os.path.splitext(os.path.basename(g))[0]
        destino = os.path.join(SALIDA, nombre + '.mp4')
        if not hay_que_rehacer(g, destino, forzar):
            print(f'[=] {nombre}: al dia')
            saltados += 1
            continue
        print(f'[>] {nombre}')
        t = time.time()
        try:
            rc, ruta, v = crear.procesar(g, destino)
            if rc != 0:
                raise RuntimeError(f'ffmpeg devolvio {rc}')
            print(f'    {os.path.basename(ruta)} | {len(v.planos)} planos | '
                  f'{v.NF/30:.1f}s de video en {time.time()-t:.0f}s')
            hechos += 1
        except Exception as e:
            print(f'    FALLO: {e}')
            fallos.append(nombre)

    print(f'\n{hechos} hechos, {saltados} al dia, {len(fallos)} fallidos '
          f'en {time.time()-t0:.0f}s')
    if fallos:
        print('fallaron:', ', '.join(fallos))
        sys.exit(1)


if __name__ == '__main__':
    main()

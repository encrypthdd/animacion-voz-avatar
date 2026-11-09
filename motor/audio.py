# -*- coding: utf-8 -*-
"""Mezcla de audio: normalización de volumen y cama musical con ducking.

Dos cosas que separan un video casero de uno que suena profesional:

**Normalizar.** Sin esto cada video sale con un volumen distinto, y en un feed
eso se nota y se castiga. Se lleva todo a −14 LUFS, que es el objetivo habitual
de las plataformas, con el pico por debajo de −1.5 dBTP para que no sature al
recomprimir.

**Ducking.** Una cama musical a volumen fijo se come la voz. El ducking la baja
automáticamente mientras hablas y la deja subir en las pausas: es lo que hace
que la música acompañe en vez de estorbar. Se consigue con `sidechaincompress`,
usando la voz como disparador.
"""

LUFS = -14.0        # objetivo de volumen integrado
PICO = -1.5         # techo real, en dBTP
VOL_MUSICA = -18.0  # cama por debajo de la voz, antes del ducking
ENTRADA = 0.8       # segundos de entrada de la música
SALIDA = 1.4        # segundos de salida


def entradas(musica=None):
    """Argumentos `-i` extra. La música se repite sola hasta cubrir la voz."""
    if not musica:
        return []
    return ['-stream_loop', '-1', '-i', musica]


def filtro(dur, musica=None, volumen=VOL_MUSICA, ducking=True, normalizar=True,
           i_voz=1, i_mus=2):
    """Devuelve (filter_complex, etiqueta).

    `i_voz` e `i_mus` son los índices de entrada en la orden de ffmpeg. Al
    renderizar, la 0 es la tubería de video; en una prueba de solo audio, la voz
    es la 0."""
    norm = (f',loudnorm=I={LUFS}:TP={PICO}:LRA=11' if normalizar else '')

    if not musica:
        return (f'[{i_voz}:a]aformat=sample_fmts=fltp:sample_rates=48000{norm}[mez]',
                '[mez]')

    fin = max(dur - SALIDA, 0.1)
    partes = [
        # la voz se duplica: una copia va a la mezcla y otra dispara el ducking
        f'[{i_voz}:a]aformat=sample_fmts=fltp:sample_rates=48000:'
        f'channel_layouts=stereo,asplit=2[voz][disparo]',
        f'[{i_mus}:a]aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo,'
        f'atrim=0:{dur:.3f},volume={volumen}dB,'
        f'afade=t=in:st=0:d={ENTRADA},afade=t=out:st={fin:.3f}:d={SALIDA}[mus]',
    ]
    if ducking:
        partes.append(
            # Medido sobre la música aislada: ratio 3 la baja 9.2 dB mientras
            # se habla, que es el rango de ducking de radio. Con ratio 8 bajaba
            # 12 dB y la cama desaparecía. La soltada de 350 ms evita que suba
            # y baje entre palabra y palabra.
            '[mus][disparo]sidechaincompress=threshold=0.04:ratio=3:'
            'attack=15:release=350:makeup=1[musd]')
        pista = '[musd]'
    else:
        partes.append('[disparo]anullsink')
        pista = '[mus]'
    partes.append(f'[voz]{pista}amix=inputs=2:duration=first:'
                  f'dropout_transition=0:normalize=0{norm}[mez]')
    return ';'.join(partes), '[mez]'


def args(dur, musica=None, volumen=VOL_MUSICA, ducking=True, normalizar=True,
         i_voz=1, i_mus=2, con_video=True):
    """Todo lo que hay que añadir a la orden de ffmpeg, ya montado."""
    f, etiqueta = filtro(dur, musica, volumen, ducking, normalizar, i_voz, i_mus)
    mapas = (['-map', '0:v'] if con_video else []) + ['-map', etiqueta]
    return entradas(musica) + ['-filter_complex', f] + mapas

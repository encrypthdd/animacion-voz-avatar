# Motor de avatar — Fase 4

Convierte guiones de texto en videos verticales con el personaje hablando. Todo
local, sin coste, sin marca de agua, sin GPU.

## Uso

```
python producir.py              # hace todos los guiones que lo necesiten
python producir.py --forzar     # rehace todos
python producir.py ganchos      # solo ese guion
python crear.py guiones/x.txt   # uno suelto
```

Pon un `.txt` en `guiones/` y sale un `.mp4` en `../salida/` con el mismo nombre.

Ritmo: **10 segundos de video por minuto de render**.

## Un guion

```
# titulo: 3 ganchos que no fallan
# voz: es-MX-JorgeNeural
# fondo: violeta
# planos: si

Nueve de cada diez videos se pierden en los primeros tres segundos.
No es el algoritmo. Es tu gancho.
```

Las líneas `#` son opciones; el resto es lo que se locuta. Todas tienen valor por
defecto, así que un guion puede ser solo texto.

| Opción | Valores |
|---|---|
| `titulo` | Texto fijo arriba, en cápsula oscura. Vacío = sin título |
| `voz` | Cualquier ID de `python -m edge_tts --list-voices` |
| `fondo` | `violeta`, `noche`, `ambar`, `verde`, `carmin` |
| `planos` | `si` (alterna), `no` (fijo), o el nombre de un plano |
| `recursos` | `si`, `no`, o lista de poses separadas por comas |
| `rate` | Velocidad, por defecto `+9%` |
| `pitch` | Tono, por defecto `-2Hz` |

Para que salga siempre de cuerpo entero sin cortes: `# planos: completo`.

**Escribe con tildes y puntuación.** La voz las usa para entonar, y los cortes de
subtítulo y de cámara salen de los puntos y comas.

### Voces recomendadas (español latino)

| ID | Notas |
|---|---|
| `es-MX-JorgeNeural` | Por defecto. Grave, con energía |
| `es-US-AlonsoNeural` | Neutro, sirve para toda Latinoamérica |
| `es-CO-GonzaloNeural` | Más claro y pausado, bueno para explicar |
| `es-AR-TomasNeural` | Rioplatense |

## Incremental y caché

`producir.py` solo rehace un video si su guion cambió después del `.mp4`.

La voz se guarda en `cache/` con una clave que depende del texto y de la voz, no del
estilo. Cambiar el fondo o el título **no** vuelve a pedir el audio a la red: se
reaprovecha. Si borras `cache/`, se regenera sola.

## Qué hace cada archivo

| Archivo | Función |
|---|---|
| `producir.py` | Lotes: recorre `guiones/`, decide qué rehacer |
| `crear.py` | Un guion: cabecera, voz, envolvente, render |
| `render.py` | Cámara, fondo, subtítulos y codificación |
| `estilo.py` | Fondos, planos de cámara, tipografía |
| `poses.py` | Recorta y cataloga las poses de recurso |
| `avatar.py` | El rig: mandíbula, ancho de boca, cierre de labios, párpados, cejas, ladeo |
| `fonemas.py` | Texto → fonemas → visemas (reglas del español) |
| `anim.py` | Forma de boca por fotograma, parpadeos y acentos |
| `cutout.py` | Recorta el fondo blanco (ya ejecutado) |
| `eyemask.py` | Detecta la abertura de los ojos (ya ejecutado) |
| `mouthline.py` | Mide los bordes de la boca (ya ejecutado) |
| `carlos_rgba.png` | Personaje con fondo transparente |
| `eye_masks.npy`, `mouth_line.npz` | Medidas del personaje |

`cutout.py`, `eyemask.py` y `mouthline.py` solo hay que volver a correrlos si cambias
la imagen base. Cada uno deja una imagen de verificación al lado: míralas antes de
renderizar, porque un rasgo mal medido se nota en todos los videos.

## Poses de recurso

`poses/` guarda el personaje en otras poses, recortado. Son **planos de recurso**:
el personaje no habla en ellas, así que entran en tramos de 2 segundos entre frases,
donde se leen como un corte intencionado y no como un fallo de sincronía.

```
python poses.py            # procesa lo nuevo de poses_fuente/
python poses.py --forzar
```

Pon imágenes nuevas en `poses_fuente/` (fondo blanco, cuerpo entero, mismo
personaje). El nombre del archivo será el nombre de la pose.

Entra una pose cada tres planos, nunca en el primero —ese establece quién habla—,
en el orden de `ORDEN_RECURSOS` de `estilo.py`, que alterna expresión y acción.
Por orden alfabético salían las dos poses de caminar seguidas.

**El recorte tuvo trampa.** El generador dibuja una sombra de suelo gris claro
(210-240, saturación casi nula) que sobre un fondo oscuro se ve como una mancha
blanca. No basta con bajar el umbral: los tenis tienen un `min_canal` mediano de 191
y se los comería. Lo que funciona es umbral 186 con saturación < 22 —los tenis se
salvan porque están rodeados de píxeles más oscuros— y después quitar por color las
bolsas de fondo que quedan encerradas al cruzarse las piernas: la sombra es gris
neutro, los dientes y los tenis son cálidos.

## Cámara

Cuatro encuadres (`completo`, `amplio`, `medio`, `cerca`) que se alternan, más un
zoom lento dentro de cada uno. `completo` enseña el cuerpo entero con los pies.
Los cortes caen **en finales de frase**, nunca a mitad de idea.

Se elige el corte más cercano a 3.2 s, no el primero que pase un mínimo: con un
mínimo rígido se perdían cortes por décimas y quedaban planos de 6 segundos.

Para ajustar, edita `estilo.py`: `PLANOS` (escala y encuadre), `SECUENCIA` (en qué
orden se alternan), `OBJ_PLANO` (duración buscada), `EMPUJE` (zoom interno).

La cámara recorta de la imagen base solo lo que entra en el lienzo y escala eso, así
un primer plano no cuesta más que uno abierto.

## Visemas

La boca no se mueve por volumen de audio sino por **lo que se dice**. El español se
escribe casi como suena, así que `fonemas.py` deriva los fonemas del texto con
reglas: no hace falta diccionario ni modelo.

Cada fonema define apertura de mandíbula, ancho de boca y cierre de labios. Se pone
una clave en el **centro** de cada fonema y se interpola — rasterizar el tramo entero
y luego suavizar aplanaba los picos, porque un fonema dura ~1.8 fotogramas y el
suavizado es más ancho que eso.

Lo que más se nota: **M, B y P cierran los labios**. En español salen a cada rato
(*también, porque, bueno, mismo*), y verlos con la boca abierta es lo que más delata
un lip-sync falso.

**El labio y la mandíbula son independientes.** En una O real el labio superior baja
tapando parte del diente *a la vez* que la mandíbula abre. Al principio los tenía como
excluyentes (`apertura *= 1-cierre`) y la O salía igual que una sonrisa. Ahora solo un
cierre fuerte (>0.55, o sea M/B/P) anula la apertura.

Para cambiar una forma de boca, edita `VISEMAS` en `fonemas.py`:
`'o': (apertura_px, factor_ancho, cierre_0a1)`. El volumen del audio sigue usándose,
pero solo como amplitud: modula cuánto se abre, no cuándo.

Los números y símbolos (`80%`, `2026`) no tienen grafema aprovechable, así que esos
tramos vuelven automáticamente a la envolvente de audio.

## Subtítulos

Se cortan por **puntuación**, no por ancho. `crear.py` recupera los signos
recorriendo el texto original en paralelo, porque `edge-tts` devuelve las palabras
peladas. Sin esto salían grupos como *"segundos No es el"*, mezclando el final de una
frase con el principio de otra.

Un grupo de una sola palabra queda huérfano, así que se le pasa la última del grupo
anterior — salvo que ese grupo cierre frase, donde el corte es intencionado
(*Uno:*, *Dos:*, *Tres:* se quedan solos a propósito).

## Coordenadas del personaje (imagen base 853×1280)

Medidas sobre `carlos_rgba.png`. Si cambias la imagen, hay que volver a medirlas.

- Boca: comisuras x 352–497. El borde **no** es una fórmula: se mide por columna y se
  guarda en `mouth_line.npz`. Va de y 367 en las comisuras a y 399 en el centro
  (32 px de arco). Una parábola de 9 px dejaba el filo de los dientes superiores
  dentro de la banda móvil y parecía una segunda boca debajo.
- Mandíbula: hasta y 470, cuello absorbe 62 px
- Ojos: izq x 334–404, der x 447–514, ambos y 246–302
- Cejas: y 196–240, x 308–562

### Dos trampas al medir el borde

**El festón y la pendiente se confunden.** Los dientes tienen filo festoneado
(0.7 px de media, hasta 4.2) y hay que rebajarlo, pero la curva de la sonrisa tiene
pendientes de 1.7 px por columna. Una envolvente directa de ±5 columnas captura
8.6 px de pendiente además del festón y arrastra la línea hasta 13 px, dejando
esquirlas de labio claro sobre la cavidad. Por eso `mouthline.py` separa tendencia de
residuo y aplica la envolvente **solo al residuo**.

**El perfil de apertura necesita pendiente nula en las comisuras.** Usaba
`sqrt(1-t²)`, que tiene pendiente infinita en el borde: la cavidad caía de 5 px a 0 en
dos columnas y dejaba una escalera de puntos naranjas. Ahora es un coseno alzado con
meseta central.

## Ajustes rápidos

- Frecuencia de parpadeo → `rng.uniform(2.6, 5.2)` en `anim.py`
- Fuerza de las cejas → `rng.uniform(2.4, 4.3)` en `anim.py` (tope 5.0)
- Colores de fondo → `FONDOS` en `estilo.py`
- Tamaño y posición de subtítulos → `fuente` y la `y` de `_subs` en `render.py`

## Limitaciones actuales

- **Las poses de recurso no mueven la boca.** Son imágenes fijas con respiración y
  zoom. Por eso duran 2 segundos: más tiempo y se nota. Para que una pose hablase
  habría que medirle boca y ojos como a la imagen base, y solo *pulgar* y *saludando*
  tienen la estructura de dientes + costura que el rig necesita; el resto tiene la
  boca cerrada, en O, o está de perfil.
- La pose que habla es siempre la misma: sonríe incluso en frases serias.
- `edge-tts` usa un endpoint no oficial de Microsoft; si deja de funcionar, el
  reemplazo local es Piper TTS.

# Motor de avatar

Convierte guiones de texto en videos verticales con un personaje hablando. Todo
local, sin coste, sin marca de agua, sin GPU.

**Sirve para cualquier avatar**, no solo para este. Nada está fijado a un personaje:
las coordenadas salen de una medición automática y las amplitudes se escalan con la
separación ocular, así que una apertura de boca significa lo mismo en una cabeza
grande que en una pequeña.

## Dar de alta un avatar nuevo

1. Deja las imágenes en `avatares/` (fondo plano, cuerpo entero, cara de frente).
2. `python medir.py` — mide todas y dice cuáles salieron.
3. **Mira `rigs/<nombre>_check.png`.** Verde y magenta son los ojos, cian el borde
   de la boca, amarillo el borde del diente, naranja las cejas, rojo la barbilla.
   Una medida mal tomada se nota en todos los videos.
4. En el guion: `# avatar: nombre1, nombre2` — si pones varios, se alternan por plano.

Para una sola imagen suelta: `python medir.py ruta.png nombre`.

### Cuándo falla, y por qué está bien que falle

- *"solo 1 candidatos a ojo"* → pose de perfil. No se puede animar la boca de perfil.
- *"no se encuentra la costura de la boca"* o diente ≈ 0 → la boca ya está abierta o
  cerrada sin dientes. El rig abre desde una costura; si no la hay, no hay nada que
  abrir.

Esas imágenes no se pierden: sirven como **poses de recurso** (ver más abajo).

## Interfaz web

```
pip install flask          # una sola vez
python app.py              # -> http://127.0.0.1:5000
```

Todo desde el navegador: subir el avatar, subir poses, escuchar y elegir voz,
escribir el guion, ver el video y descargarlo. Se corta con `Ctrl+C`.

Solo escucha en `127.0.0.1`, así que no queda expuesta a la red.

Cada video generado desde la web se guarda en `../salida/web_<id>.mp4`. Se
acumulan: bórralos de vez en cuando.

## Uso por línea de comandos

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
| `avatar` | Nombre(s) de `rigs/`. Varios separados por coma se alternan |
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
| `app.py` | Servidor web: envuelve todo lo de abajo |
| `web/` | La interfaz: `index.html`, `estilo.css`, `app.js` (sin dependencias) |
| `estilo.py` | Fondos, planos de cámara, tipografía |
| `medir.py` | Mide ojos, boca, cejas y barbilla de cualquier imagen |
| `poses.py` | Recorta y cataloga las poses de recurso |
| `avatar.py` | El rig: mandíbula, ancho de boca, cierre de labios, párpados, cejas, ladeo |
| `fonemas.py` | Texto → fonemas → visemas (reglas del español) |
| `anim.py` | Forma de boca por fotograma, parpadeos y acentos |
| `avatares/` | Imágenes de origen que quieres medir |
| `rigs/` | Lo medido: `<nombre>.png`, `<nombre>.npz` y `<nombre>_check.png` |
| `poses/` | Poses de recurso ya recortadas |
| `guiones/` | Tus guiones `.txt` |
| `cache/` | Voz reutilizable, indexada por texto y voz |

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

## Cómo se mide (y qué se aprendió midiendo)

El borde de la boca **no es una fórmula**: se mide columna por columna. En el
personaje de referencia va de y 367 en las comisuras a y 399 en el centro, 32 px de
arco. Una parábola de 9 px dejaba el filo de los dientes superiores dentro de la
banda móvil y parecía una segunda boca debajo.

**Un ojo no es la esclerótica.** El iris la parte en dos medialunas finas que
cualquier filtro de forma descarta. Lo que funciona es buscar la *abertura* entera
—esclerótica, iris y contorno— como región no-piel rodeada de piel.

**Una ceja también es una isla oscura rodeada de piel**, pareada y más arriba. Con
una puntuación que premiaba estar arriba, el medidor detectaba las cejas como ojos.
Lo que las separa: un ojo contiene esclerótica clara, una ceja no.

**La boca no es el punto más oscuro bajo los ojos.** El cuello de la camisa es más
oscuro que la costura, así que la ventana de búsqueda tiene que ser estrecha. Y
dentro de ella, la costura viene pegada a la sombra de la nariz: por columna hay dos
tramos y hay que quedarse con el de abajo.

**Los pliegues de la sonrisa continúan la costura hacia abajo.** Caminando hacia
fuera desde el centro de la cara, la costura sube hasta la comisura y luego vuelve a
bajar: la boca acaba en ese mínimo.

### Dos trampas más

**El festón y la pendiente se confunden.** Los dientes tienen filo festoneado
(0.7 px de media, hasta 4.2) y hay que rebajarlo, pero la curva de la sonrisa tiene
pendientes de 1.7 px por columna. Una envolvente directa de ±5 columnas captura
8.6 px de pendiente además del festón y arrastra la línea hasta 13 px, dejando
esquirlas de labio claro sobre la cavidad. Por eso `medir.py` separa tendencia de
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
  zoom. Por eso duran 2 segundos: más tiempo y se nota.
- De las siete poses generadas, solo **`pulgar`** pasó la medición como pose
  parlante. `saludando` ya tiene la boca abierta (no hay costura que abrir), las de
  perfil esconden un ojo, y el resto tiene la boca cerrada sin dientes. No es una
  limitación del medidor: es que una pose con la boca abierta no se puede abrir más.
- El rig abre la mandíbula desde una costura; no forma la boca desde cero. Un avatar
  con la boca muy abierta de partida no es rigeable con este método.
- `edge-tts` usa un endpoint no oficial de Microsoft; si deja de funcionar, el
  reemplazo local es Piper TTS.

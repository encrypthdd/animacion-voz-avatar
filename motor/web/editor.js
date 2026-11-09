'use strict';
/* Editor de vídeo.
 *
 * El montaje es un objeto plano: pistas y clips, con tiempos en segundos. Todo
 * lo demás son vistas de ese objeto. Cuando algo cambia se llama a `cambiado()`
 * y se vuelve a pintar; no hay estado escondido en el DOM.
 *
 * La vista previa NO renderiza en el servidor. Dibuja en un canvas los mismos
 * clips que exportará FFmpeg, leyendo las copias ligeras que preparó
 * `medios.py`. Por eso se puede arrastrar el cabezal y ver el resultado al
 * instante, sin esperar a ningún render.
 */

const E = {
  montaje: null,
  medios: new Map(),
  elegido: null,
  t: 0,                 // cabezal, en segundos
  zoom: 60,             // píxeles por segundo
  reproduciendo: false,
  ancla: null,
  guardando: null,
  sucio: false,
};

const RELOJ = (s) => {
  s = Math.max(s, 0);
  const m = Math.floor(s / 60);
  return `${m}:${String(Math.floor(s % 60)).padStart(2, '0')}.${Math.floor((s % 1) * 10)}`;
};
const px = (s) => s * E.zoom;
const seg = (p) => p / E.zoom;

/* ═════════════════════════════════════════════════════════ arranque */
async function arrancar() {
  let d;
  try {
    d = await (await pedir('/api/editor/inicio')).json();
  } catch (e) {
    error('No se pudo contactar con el servidor. ¿Sigue corriendo app.py?');
    return;
  }
  d.medios.forEach((m) => E.medios.set(m.id, m));
  pintarMedios();
  llenarVoces(d.voces);

  const ultimo = localStorage.getItem('montaje-abierto');
  if (ultimo && d.montajes.some((m) => m.id === ultimo)) {
    await abrirMontaje(ultimo);
  } else {
    nuevoMontaje();
  }
  conectar();
  bucle();
}

function nuevoMontaje() {
  E.montaje = {
    version: 1, id: null, nombre: 'Montaje nuevo',
    lienzo: { w: 1080, h: 1920, fps: 30, forma: 'vertical' },
    pistas: [
      { id: 'v2', tipo: 'video', nombre: 'Vídeo 2', muda: false, oculta: false },
      { id: 'v1', tipo: 'video', nombre: 'Vídeo 1', muda: false, oculta: false },
      { id: 'a1', tipo: 'audio', nombre: 'Audio 1', muda: false, oculta: false },
    ],
    clips: [],
  };
  E.elegido = null; E.t = 0;
  $('#nombre-montaje').value = E.montaje.nombre;
  $('#forma-lienzo').value = 'vertical';
  ajustarLienzo();
  pintarTodo();
  arrancarHistoria();
}

async function abrirMontaje(id) {
  try {
    const r = await pedir('/api/montaje/' + id);
    if (!r.ok) throw new Error('no está');
    E.montaje = await r.json();
    if (!E.montaje.id) E.montaje.id = id;
    localStorage.setItem('montaje-abierto', id);
    E.elegido = null; E.t = 0;
    $('#nombre-montaje').value = E.montaje.nombre || 'Montaje';
    $('#forma-lienzo').value = E.montaje.lienzo.forma || 'vertical';
    ajustarLienzo();
    pintarTodo();
    arrancarHistoria();
  } catch (e) {
    error('No se pudo abrir ese montaje.');
  }
}

/* ═════════════════════════════════════════════════════ deshacer y rehacer
 *
 * La historia guarda el montaje entero en cada paso, no la diferencia. Con
 * clips que son objetos de diez campos, un montaje completo ocupa unos pocos
 * kilobytes; guardar diferencias seria mas fino y mucho mas facil de
 * equivocar, y un deshacer que a veces restaura mal es peor que no tenerlo.
 *
 * Dos pasos con la MISMA etiqueta y muy seguidos se funden en uno: arrastrar
 * el mando de velocidad lanza decenas de cambios, y deshacerlos de uno en uno
 * seria inservible. Por eso las acciones sueltas -anadir, partir, borrar,
 * duplicar- llevan etiqueta unica: dos clips soltados seguidos tienen que ser
 * dos pasos, no uno.
 */
const H = { pila: [], i: -1, etiqueta: '', ultima: 0 };
const TOPE_HISTORIA = 80;
const SALTO_GORDO = 0.5;  // s de desfase a partir del cual el medio salta
const FUSION = 700;      // ms dentro de los cuales dos pasos iguales son uno

function instantanea() {
  return JSON.stringify({
    nombre: E.montaje.nombre, lienzo: E.montaje.lienzo,
    pistas: E.montaje.pistas, clips: E.montaje.clips,
  });
}

function arrancarHistoria() {
  H.pila = [instantanea()]; H.i = 0; H.etiqueta = ''; H.ultima = 0;
  botonesHistoria();
}

function anotar(etiqueta) {
  const estado = instantanea();
  if (H.pila[H.i] === estado) return;
  const ahora = performance.now();
  if (etiqueta && etiqueta === H.etiqueta && ahora - H.ultima < FUSION) {
    H.pila[H.i] = estado;
    H.ultima = ahora;
    return;
  }
  H.etiqueta = etiqueta || ''; H.ultima = ahora;
  H.pila.length = H.i + 1;
  H.pila.push(estado);
  if (H.pila.length > TOPE_HISTORIA) H.pila.shift();
  H.i = H.pila.length - 1;
  botonesHistoria();
}

function botonesHistoria() {
  const a = $('#btn-deshacer'), b = $('#btn-rehacer');
  if (a) a.disabled = H.i <= 0;
  if (b) b.disabled = H.i >= H.pila.length - 1;
}

function viajar(paso) {
  const destino = H.i + paso;
  if (destino < 0 || destino >= H.pila.length) return;
  H.i = destino;
  H.etiqueta = '';
  Object.assign(E.montaje, JSON.parse(H.pila[H.i]));
  if (!clip(E.elegido)) E.elegido = null;
  $('#nombre-montaje').value = E.montaje.nombre;
  $('#forma-lienzo').value = E.montaje.lienzo.forma || 'vertical';
  ajustarLienzo();
  pintarTodo();
  botonesHistoria();
  marcarSucio();
}

/* ═════════════════════════════════════════════════════════ guardado */
function marcarSucio() {
  E.sucio = true;
  $('#estado-guardado').textContent = 'sin guardar';
  clearTimeout(E.guardando);
  E.guardando = setTimeout(guardar, 900);
}

function cambiado({ repintar = true, paso = '' } = {}) {
  anotar(paso);
  if (repintar) pintarTiempo();
  marcarSucio();
}

async function guardar() {
  if (!E.montaje) return;
  E.montaje.nombre = $('#nombre-montaje').value.trim() || 'Montaje';
  try {
    const r = await pedir('/api/montaje', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(E.montaje),
    });
    const d = await r.json();
    if (!d.ok) throw new Error(d.error || 'no se guardó');
    E.montaje.id = d.montaje.id;
    localStorage.setItem('montaje-abierto', d.montaje.id);
    E.sucio = false;
    $('#estado-guardado').textContent = 'guardado';
    if (d.montaje.descartados) {
      error(`Se descartaron ${d.montaje.descartados} clip(s): su archivo ya no está.`);
      E.montaje.clips = d.montaje.clips;
      pintarTiempo();
    }
  } catch (e) {
    $('#estado-guardado').textContent = 'error al guardar';
  }
}

/* ═════════════════════════════════════════════════════════ medios */
function pintarMedios() {
  const ul = $('#lista-medios');
  ul.textContent = '';
  const ms = [...E.medios.values()];
  $('#vacio-medios').hidden = ms.length > 0;
  for (const m of ms) {
    const li = document.createElement('li');
    li.className = 'medio';
    li.draggable = true;
    li.dataset.medio = m.id;
    const dur = m.tipo === 'imagen' ? '—' : RELOJ(m.dur);
    const vista = m.poster
      ? `<img src="${m.poster}" alt="">`
      : `<div class="sinimg"><svg viewBox="0 0 24 24"><path d="M9 18V5l10-2v13"/><circle cx="6" cy="18" r="3"/><circle cx="16" cy="16" r="3"/></svg></div>`;
    li.innerHTML = `${vista}
      <div><b title="${m.nombre}">${m.nombre}</b><small>${m.tipo} · ${dur}</small></div>
      <button class="descartar" title="Quitar de la biblioteca" aria-label="Quitar ${m.nombre}">
        <svg viewBox="0 0 24 24"><path d="M6 6l12 12M18 6L6 18"/></svg></button>`;
    li.addEventListener('dragstart', (ev) => {
      ev.dataTransfer.setData('text/medio', m.id);
      ev.dataTransfer.effectAllowed = 'copy';
    });
    li.querySelector('.descartar').onclick = () => quitarMedio(m);
    ul.appendChild(li);
  }
}

async function quitarMedio(m) {
  const usado = (E.montaje.clips || []).filter((c) => c.medio === m.id).length;
  if (usado && !confirm(
    `"${m.nombre}" está en ${usado} clip(s) del montaje. Si lo quitas, esos clips se van también. ¿Seguimos?`)) return;
  await pedir('/api/medios/borrar', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ id: m.id }),
  }).catch(() => {});
  E.medios.delete(m.id);
  E.montaje.clips = E.montaje.clips.filter((c) => c.medio !== m.id);
  const viejo = reproductores.get(m.id);
  if (viejo && viejo.remove) { viejo.pause(); viejo.remove(); }
  reproductores.delete(m.id);
  pintarMedios(); cambiado();
}

async function subirArchivos(lista) {
  for (const f of lista) {
    const fila = document.createElement('li');
    fila.className = 'medio subiendo';
    fila.innerHTML = `<div class="sinimg">…</div><div><b>${f.name}</b><small>preparando…</small></div><span></span>`;
    $('#lista-medios').appendChild(fila);
    $('#vacio-medios').hidden = true;
    const fd = new FormData();
    fd.append('archivo', f);
    try {
      const r = await pedir('/api/medios', { method: 'POST', body: fd });
      const d = await r.json();
      if (!d.ok) throw new Error(d.error || 'no se pudo importar');
      E.medios.set(d.medio.id, d.medio);
      error('');
    } catch (e) {
      error(`${f.name}: ${e.message}`);
    } finally {
      fila.remove();
      pintarMedios();
    }
  }
}

/* ═════════════════════════════════════════════════════════ clips */
const nuevoId = () => Math.random().toString(36).slice(2, 10);

function clip(id) {
  return (E.montaje.clips || []).find((c) => c.id === id) || null;
}

function duracionTotal() {
  return (E.montaje.clips || []).reduce((a, c) => Math.max(a, c.t + c.dur), 0);
}

function anadirClip(medioId, pistaId, t) {
  const m = E.medios.get(medioId);
  if (!m) return null;
  const pista = E.montaje.pistas.find((p) => p.id === pistaId);
  if (!pista) return null;
  if (pista.tipo === 'audio' && m.tipo === 'imagen') {
    error('Una imagen no cabe en una pista de audio.');
    return null;
  }
  const c = {
    id: nuevoId(), pista: pistaId, medio: medioId,
    t: Math.max(t, 0), dur: m.tipo === 'imagen' ? 4 : Math.min(m.dur, 600),
    entrada: 0, veloc: 1, volumen: 1, opacidad: 1, encaje: 'cubrir',
    fundido_ent: 0, fundido_sal: 0, fx: Object.assign({}, FX_NEUTRO),
    nombre: m.nombre,
  };
  c.t = acomodar(c, c.t);
  E.montaje.clips.push(c);
  E.elegido = c.id;
  cambiado({ paso: 'anadir' + c.id });
  return c;
}

function choca(c, t, dur) {
  /* El primer clip de la misma pista al que pisaria.
     Un solape se permite cuando es exactamente la transicion de entrada de
     este clip: ahi los dos tienen que convivir un momento, porque uno se
     funde sobre el otro. */
  const tolera = c.fundido_ent || 0;
  return E.montaje.clips.find((o) => {
    if (o.id === c.id || o.pista !== c.pista) return false;
    if (!(t < o.t + o.dur - 1e-4 && t + dur > o.t + 1e-4)) return false;
    if (tolera > 0 && o.t < t && (o.t + o.dur) - t <= tolera + 0.02) return false;
    return true;
  }) || null;
}

function acomodar(c, t) {
  /* Dos clips de la misma pista no pueden sonar a la vez: la pista es una
     sola, y si se pisan hay que inventarse cual gana. En vez de eso, el clip
     se desplaza al hueco libre mas cercano. */
  let p = Math.max(t, 0);
  for (let k = 0; k < 40; k++) {
    const o = choca(c, p, c.dur);
    if (!o) return p;
    const izq = o.t - c.dur, der = o.t + o.dur;
    p = (izq >= 0 && Math.abs(p - izq) <= Math.abs(p - der)) ? izq : der;
  }
  return p;
}

function vecinoDerecha(c) {
  return E.montaje.clips
    .filter((o) => o.id !== c.id && o.pista === c.pista && o.t >= c.t + 1e-4)
    .reduce((m, o) => (m === null || o.t < m.t ? o : m), null);
}

function vecinoIzquierda(c) {
  return E.montaje.clips
    .filter((o) => o.id !== c.id && o.pista === c.pista && o.t + o.dur <= c.t + c.dur + 1e-4)
    .reduce((m, o) => (m === null || o.t + o.dur > m.t + m.dur ? o : m), null);
}

function topeClip(c) {
  /* Hasta dónde puede estirarse: lo que queda de archivo. */
  if (c.tipo === 'texto') return 3600;
  const m = E.medios.get(c.medio);
  if (!m || m.tipo === 'imagen') return 3600;
  return Math.max((m.dur - c.entrada) / c.veloc, 0.04);
}

function partir() {
  const c = clip(E.elegido);
  if (!c || E.t <= c.t + 0.05 || E.t >= c.t + c.dur - 0.05) {
    error('Pon el cabezal dentro del clip elegido para partirlo.');
    return;
  }
  const corte = E.t - c.t;
  const b = { ...c, id: nuevoId(), t: E.t, dur: c.dur - corte,
              entrada: c.entrada + corte * c.veloc };
  c.dur = corte;
  E.montaje.clips.push(b);
  E.elegido = b.id;
  error(''); cambiado({ paso: 'partir' + b.id });
}

function borrarClip() {
  if (!E.elegido) return;
  E.montaje.clips = E.montaje.clips.filter((c) => c.id !== E.elegido);
  E.elegido = null;
  cambiado({ paso: 'borrar' + nuevoId() });
}

function fundirConAnterior() {
  /* Encadena el clip elegido con el que tiene justo delante en su pista.
     El clip entrante se adelanta lo que dura la transicion y se funde sobre
     el saliente: eso es un encadenado de toda la vida, y no hace falta
     material de mas porque cada uno sigue tocando lo suyo. */
  const c = clip(E.elegido);
  if (!c || c.tipo === 'texto') {
    error('Elige el clip que quieras encadenar con el de delante.');
    return;
  }
  const antes = E.montaje.clips
    .filter((o) => o.pista === c.pista && o.id !== c.id && o.t + o.dur <= c.t + 0.05)
    .sort((a, b) => (b.t + b.dur) - (a.t + a.dur))[0];
  if (!antes) {
    error('No hay ningún clip delante de este en su pista.');
    return;
  }
  const hueco = c.t - (antes.t + antes.dur);
  const d = Math.min(0.6, antes.dur * 0.5, c.dur * 0.5);
  if (d < 0.08) { error('Los clips son demasiado cortos para encadenarlos.'); return; }
  c.fundido_ent = Math.round(d * 1000) / 1000;
  c.t = Math.round((c.t - hueco - d) * 1000) / 1000;
  error('');
  cambiado({ paso: 'fundir' + c.id });
  pintarInspector();
}

function duplicar() {
  const c = clip(E.elegido);
  if (!c) return;
  const b = { ...c, id: nuevoId(), t: c.t + c.dur };
  b.t = acomodar(b, b.t);
  E.montaje.clips.push(b);
  E.elegido = b.id;
  cambiado({ paso: 'duplicar' + b.id });
}

/* ═════════════════════════════════════════════════════ dibujo del tiempo */
function pintarTodo() {
  pintarPistas();
  pintarTiempo();
  pintarInspector();
}

function pintarPistas() {
  const cont = $('#nombres-pistas');
  const caja = $('#pistas');
  cont.textContent = ''; caja.textContent = '';
  for (const p of E.montaje.pistas) {
    const n = document.createElement('div');
    n.className = 'nombre-pista';
    n.innerHTML = `<span title="${p.nombre}">${p.nombre}</span>
      <button class="ojo" aria-pressed="${p.oculta}" title="Ver u ocultar">
        <svg viewBox="0 0 24 24"><path d="M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12Z"/><circle cx="12" cy="12" r="3"/></svg></button>
      <button class="son" aria-pressed="${p.muda}" title="Silenciar">
        <svg viewBox="0 0 24 24"><path d="M11 5 6 9H3v6h3l5 4V5Z"/><path d="M16 9l5 6M21 9l-5 6"/></svg></button>`;
    n.querySelector('.ojo').onclick = () => { p.oculta = !p.oculta; pintarPistas(); cambiado({ paso: 'ver' + p.id }); };
    n.querySelector('.son').onclick = () => { p.muda = !p.muda; pintarPistas(); cambiado({ paso: 'son' + p.id }); };
    cont.appendChild(n);

    const d = document.createElement('div');
    d.className = 'carril';
    d.dataset.pista = p.id;
    caja.appendChild(d);
  }
}

function fondoClip(c) {
  /* La tira de miniaturas se escala para que 1 s de archivo ocupe lo mismo
     que 1 s de línea de tiempo; si no, las miniaturas no coinciden con lo
     que se ve al reproducir. */
  const m = E.medios.get(c.medio);
  if (!m) return {};
  if (m.tipo === 'imagen' && m.poster) {
    return { backgroundImage: `url(${m.poster})`, backgroundSize: 'auto 100%' };
  }
  const img = m.tira ? m.tira : (m.picos_url ? ondaURL(m) : null);
  if (!img) return {};
  const anchoTotal = px(m.dur / Math.max(c.veloc, 0.01));
  return {
    backgroundImage: `url(${img})`,
    backgroundSize: `${anchoTotal}px 100%`,
    backgroundPosition: `${-px(c.entrada / Math.max(c.veloc, 0.01))}px 0`,
    backgroundRepeat: 'no-repeat',
  };
}

const ondasCache = new Map();
function ondaURL(m) {
  if (ondasCache.has(m.id)) return ondasCache.get(m.id);
  ondasCache.set(m.id, null);
  fetch(m.picos_url).then((r) => r.json()).then((picos) => {
    const cv = document.createElement('canvas');
    cv.width = Math.min(Math.max(picos.length, 200), 2000); cv.height = 64;
    const g = cv.getContext('2d');
    g.fillStyle = 'rgba(167,255,235,.85)';
    for (let x = 0; x < cv.width; x++) {
      const v = picos[Math.floor(x / cv.width * picos.length)] || 0;
      const h = Math.max(v * cv.height, 1);
      g.fillRect(x, (cv.height - h) / 2, 1, h);
    }
    ondasCache.set(m.id, cv.toDataURL('image/png'));
    pintarTiempo();
  }).catch(() => {});
  return null;
}

function pintarTiempo() {
  const total = Math.max(duracionTotal(), 10);
  const ancho = px(total) + 400;
  $('#interior').style.width = ancho + 'px';
  pintarRegla(total);

  for (const d of document.querySelectorAll('.carril')) {
    d.textContent = '';
    d.style.width = ancho + 'px';
  }
  for (const c of E.montaje.clips) {
    const pista = document.querySelector(`.carril[data-pista="${c.pista}"]`);
    if (!pista) continue;
    const el = document.createElement('div');
    const m = E.medios.get(c.medio);
    el.className = 'clip' + (c.id === E.elegido ? ' elegido' : '') +
                   (c.tipo === 'texto' ? ' texto'
                    : (m && m.tipo === 'audio' ? ' audio' : ''));
    el.dataset.clip = c.id;
    el.style.left = px(c.t) + 'px';
    el.style.width = Math.max(px(c.dur), 8) + 'px';
    if (c.tipo !== 'texto') Object.assign(el.style, fondoClip(c));
    if (c.fundido_ent > 0.01) {
      el.classList.add('fundido-ent');
      el.style.setProperty('--fx', Math.min(px(c.fundido_ent), 60) + 'px');
    }
    if (c.fundido_sal > 0.01) el.classList.add('fundido-sal');
    el.innerHTML = `<div class="asa izq"></div><div class="asa der"></div>
                    <div class="etiqueta">${c.nombre || (m ? m.nombre : '?')}${
                      c.veloc !== 1 ? ` · ${c.veloc.toFixed(2)}×` : ''}</div>`;
    pista.appendChild(el);
  }
  moverCabezal();
  $('#reloj').textContent = `${RELOJ(E.t)} / ${RELOJ(duracionTotal())}`;
}

function pintarRegla(total) {
  const r = $('#regla');
  r.textContent = '';
  r.style.width = (px(total) + 400) + 'px';
  const pasos = [0.5, 1, 2, 5, 10, 15, 30, 60, 120];
  const paso = pasos.find((p) => px(p) > 62) || 300;
  for (let t = 0; t <= total + 10; t += paso) {
    const i = document.createElement('i');
    i.className = 'hito';
    i.style.left = px(t) + 'px';
    i.textContent = RELOJ(t).replace(/\.\d$/, '');
    r.appendChild(i);
  }
}

function moverCabezal() {
  $('#cabezal').style.left = px(E.t) + 'px';
}

/* ═════════════════════════════════════════════════════════ inspector */
function pintarInspector() {
  const c = clip(E.elegido);
  $('#inspector').hidden = !c;
  $('#inspector-texto').hidden = !(c && c.tipo === 'texto');
  for (const b of ['#btn-cortar', '#btn-borrar', '#btn-duplicar']) $(b).disabled = !c;
  if (!c) return;
  const m = E.medios.get(c.medio);
  $('#inspector-nombre').textContent = c.nombre || (m ? m.nombre : 'Clip');
  if (c.tipo === 'texto') {
    if (document.activeElement !== $('#t-texto')) $('#t-texto').value = c.texto;
    $('#t-fuente').value = c.fuente;
    $('#t-align').value = c.align;
    $('#t-tam').value = c.tam; $('#o-tam').textContent = Math.round(c.tam * 1000) / 10 + '%';
    $('#t-color').value = c.color;
    $('#t-contorno').value = c.contorno;
    $('#o-contorno').textContent = Math.round(c.contorno * 100) + '%';
    $('#t-color-contorno').value = c.color_contorno;
    $('#t-caja').checked = c.caja;
    $('#t-color-caja').value = c.color_caja;
    $('#t-fundido').value = c.fundido;
    $('#o-fundido').textContent = c.fundido.toFixed(2) + ' s';
    $('#inspector-nombre').textContent = 'Rótulo';
  }
  $('#p-veloc').value = c.veloc; $('#o-veloc').textContent = c.veloc.toFixed(2) + '×';
  $('#p-volumen').value = c.volumen; $('#o-volumen').textContent = Math.round(c.volumen * 100) + '%';
  $('#p-opacidad').value = c.opacidad; $('#o-opacidad').textContent = Math.round(c.opacidad * 100) + '%';
  $('#p-encaje').value = c.encaje;
  const fx = Object.assign({}, FX_NEUTRO, c.fx || {});
  for (const [k, sel] of [['brillo', '#f-brillo'], ['contraste', '#f-contraste'],
                          ['saturacion', '#f-saturacion'], ['tono', '#f-tono'],
                          ['desenfoque', '#f-desenfoque']]) {
    const n = $(sel);
    if (!n) continue;
    n.value = fx[k];
    const o = $(sel.replace('#f-', '#o-f-'));
    if (o) o.textContent = k === 'tono' ? Math.round(fx[k]) + '°'
         : k === 'desenfoque' ? Math.round(fx[k] * 1000) / 10 + '%'
         : Math.round(fx[k] * 100) + '%';
  }
  $('#f-ent').value = c.fundido_ent || 0;
  $('#o-f-ent').textContent = (c.fundido_ent || 0).toFixed(2) + ' s';
  $('#f-sal').value = c.fundido_sal || 0;
  $('#o-f-sal').textContent = (c.fundido_sal || 0).toFixed(2) + ' s';

  const texto = c.tipo === 'texto';
  $('#inspector-fx').hidden = texto;
  const esVideo = texto || (m && m.tipo !== 'audio');
  $('#p-veloc').closest('.campo-fila').hidden = texto;
  $('#p-opacidad').closest('.campo-fila').hidden = !esVideo;
  $('#p-encaje').closest('.campo-fila').hidden = !esVideo || texto;
  $('#p-volumen').closest('.campo-fila').hidden =
    texto || !(m && (m.audio || m.tipo === 'audio'));
}


/* ═══════════════════════════════════════════════════════════ rotulos
 *
 * Un rotulo se dibuja UNA sola vez, aqui, y esa misma funcion sirve para la
 * vista previa y para la imagen que se manda al exportar. Es la unica forma
 * de que el MP4 salga igual que lo que se ve: en cuanto el texto se dibuja
 * dos veces con dos motores distintos, cambia el ancho de una letra, la linea
 * parte en otro sitio y el rotulo acaba descuadrado en el video.
 */
const SALTO = String.fromCharCode(10);
const FAMILIAS = {
  gruesa:  '800 1px Inter, "Segoe UI", system-ui, sans-serif',
  redonda: '600 1px "Trebuchet MS", Verdana, system-ui, sans-serif',
  serif:   '700 1px Georgia, "Times New Roman", serif',
  maquina: '600 1px "Courier New", ui-monospace, monospace',
};

function fuenteDe(c, H) {
  const px = Math.max(c.tam * H, 6);
  return FAMILIAS[c.fuente].replace('1px', px.toFixed(2) + 'px');
}

function medirRotulo(g, c, W, H) {
  /* Caja que ocupa el rotulo en el lienzo, en pixeles. */
  const lineas = String(c.texto).split(SALTO);
  g.font = fuenteDe(c, H);
  const alto = c.tam * H;
  const salto = alto * 1.22;
  const grueso = c.contorno * alto;
  const anchos = lineas.map((l) => g.measureText(l).width);
  const ancho = Math.max(...anchos, 1);
  const relleno = c.caja ? alto * 0.34 : 0;
  const w = ancho + 2 * (relleno + grueso);
  const h = salto * lineas.length + 2 * (relleno + grueso) - (salto - alto) * 0.3;
  return { lineas, anchos, alto, salto, grueso, relleno, w, h,
           x: c.x * W - w / 2, y: c.y * H - h / 2 };
}

function pintarRotulo(g, c, W, H, alfa, dx, dy, activa) {
  const m = medirRotulo(g, c, W, H);
  const x0 = (dx === undefined ? m.x : dx), y0 = (dy === undefined ? m.y : dy);
  g.save();
  g.globalAlpha = Math.max(Math.min(alfa, 1), 0);
  if (c.caja) {
    g.fillStyle = c.color_caja;
    g.globalAlpha *= c.alfa_caja;
    const r = Math.min(m.alto * 0.28, m.w / 2, m.h / 2);
    g.beginPath();
    if (g.roundRect) g.roundRect(x0, y0, m.w, m.h, r);
    else g.rect(x0, y0, m.w, m.h);
    g.fill();
    g.globalAlpha = Math.max(Math.min(alfa, 1), 0);
  }
  g.font = fuenteDe(c, H);
  g.textBaseline = 'alphabetic';
  g.lineJoin = 'round';
  g.miterLimit = 2;
  const izq = x0 + m.relleno + m.grueso;
  const util = m.w - 2 * (m.relleno + m.grueso);
  m.lineas.forEach((linea, i) => {
    const ancho = m.anchos[i];
    const x = c.align === 'izq' ? izq
            : c.align === 'der' ? izq + util - ancho
            : izq + (util - ancho) / 2;
    const y = y0 + m.relleno + m.grueso + m.alto + m.salto * i;
    if (!(c.karaoke && c.palabras && c.palabras.length)) {
      if (m.grueso > 0.3) {
        g.strokeStyle = c.color_contorno;
        g.lineWidth = m.grueso * 2;
        g.strokeText(linea, x, y);
      }
      g.fillStyle = c.color;
      g.fillText(linea, x, y);
      return;
    }
    /* Con resaltado hay que pintar palabra a palabra, porque solo una cambia
       de color. Se dibujan todas con el mismo espaciado que tendria la linea
       entera, para que al cambiar de palabra activa nada se mueva. */
    let px = x;
    for (const trozo of linea.split(' ')) {
      const an = g.measureText(trozo + ' ').width;
      if (m.grueso > 0.3) {
        g.strokeStyle = c.color_contorno;
        g.lineWidth = m.grueso * 2;
        g.strokeText(trozo, px, y);
      }
      g.fillStyle = (activa && trozo === activa.w) ? c.color_activo : c.color;
      g.fillText(trozo, px, y);
      px += an;
    }
  });
  g.restore();
  return m;
}

function palabraEn(c, dentro) {
  /* Que palabra se esta diciendo, en segundos desde que empieza el rotulo. */
  if (!c.karaoke || !c.palabras) return null;
  return c.palabras.find((w) => dentro >= w.t0 - 0.03 && dentro <= w.t1 + 0.06) || null;
}

function alfaRotulo(c, t) {
  /* Entra y sale con fundido, igual que hara FFmpeg al exportar. */
  const f = c.fundido || 0;
  if (f <= 0.01) return c.opacidad;
  const dentro = t - c.t, queda = c.t + c.dur - t;
  const k = Math.min(dentro / f, queda / f, 1);
  return c.opacidad * Math.max(k, 0);
}

function anadirTexto() {
  const pista = E.montaje.pistas.find((p) => p.tipo === 'video');
  if (!pista) return;
  const c = {
    id: nuevoId(), pista: pista.id, medio: '', tipo: 'texto',
    t: Math.max(E.t, 0), dur: 3, entrada: 0, veloc: 1, volumen: 1,
    opacidad: 1, encaje: 'cubrir',
    texto: 'Tu texto aquí', fuente: 'gruesa', tam: 0.062,
    color: '#FFFFFF', contorno: 0.14, color_contorno: '#000000',
    caja: false, color_caja: '#000000', alfa_caja: 0.55,
    x: 0.5, y: 0.78, align: 'centro', fundido: 0.25,
  };
  c.nombre = c.texto;
  c.t = acomodar(c, c.t);
  E.montaje.clips.push(c);
  E.elegido = c.id;
  cambiado({ paso: 'texto' + c.id });
  pintarInspector();
  $('#t-texto').focus();
  $('#t-texto').select();
}

function tramosRotulo(c) {
  /* En que trozos se parte un rotulo. Uno normal es uno solo; uno con
     resaltado cambia cada vez que cambia la palabra que se esta diciendo. */
  if (!c.karaoke || !c.palabras || !c.palabras.length) {
    return [{ desde: 0, hasta: c.dur, activa: null }];
  }
  const cortes = [];
  let t = 0;
  for (const w of c.palabras) {
    if (w.t0 > t + 0.02) cortes.push({ desde: t, hasta: Math.min(w.t0, c.dur), activa: null });
    const fin = Math.min(w.t1, c.dur);
    if (fin > w.t0) cortes.push({ desde: Math.max(w.t0, 0), hasta: fin, activa: w });
    t = fin;
  }
  if (t < c.dur - 0.02) cortes.push({ desde: t, hasta: c.dur, activa: null });
  return cortes.filter((x) => x.hasta > x.desde + 0.01);
}

function rotulosParaExportar() {
  /* Cada rotulo, dibujado a la resolucion real del lienzo y recortado a su
     caja, para no mandar un PNG del tamano del video por cada texto. */
  const L = E.montaje.lienzo;
  const salida = {};
  const medidor = document.createElement('canvas').getContext('2d');
  for (const c of E.montaje.clips) {
    if (c.tipo !== 'texto') continue;
    const m = medirRotulo(medidor, c, L.w, L.h);
    const marco = Math.ceil(m.grueso + 4);
    const w = Math.max(Math.ceil(m.w) + 2 * marco, 2);
    const h = Math.max(Math.ceil(m.h) + 2 * marco, 2);
    salida[c.id] = tramosRotulo(c).map((tr) => {
      const cv = document.createElement('canvas');
      cv.width = w; cv.height = h;
      pintarRotulo(cv.getContext('2d'), c, L.w, L.h, 1, marco, marco, tr.activa);
      return { png: cv.toDataURL('image/png'),
               x: Math.round(m.x - marco), y: Math.round(m.y - marco),
               desde: Math.round(tr.desde * 1000) / 1000,
               hasta: Math.round(tr.hasta * 1000) / 1000 };
    });
  }
  return salida;
}


/* ═══════════════════════════════════════════ subtitulos automaticos
 *
 * No hay transcripcion aqui, y no hace falta: cuando la voz la genera el
 * propio programa, el servicio devuelve en que milisegundo empieza y acaba
 * cada palabra. Los subtitulos salen de ahi, asi que caen clavados.
 *
 * Con una voz GRABADA esto no existe y habria que reconocer el habla. Es la
 * mitad del problema que todavia no esta hecha, y conviene no confundirlas.
 */
const DURO = new Set(['.', ';', ':', '!', '?', '…']);
const SUB = {           // como se agrupan las palabras en subtitulos
  segundos: 2.4,        // lo que dura como mucho un subtitulo
  hueco: 0.35,          // silencio que obliga a cortar
  anchoLinea: 0.86,     // ancho util de UNA linea, respecto al lienzo
  lineas: 2,            // lineas por subtitulo
  anchoComa: 1.0,       // a partir de ahi, una coma ya corta
};
const ESTILO_SUB = {
  fuente: 'gruesa', tam: 0.052, color: '#FFFFFF', contorno: 0.17,
  color_contorno: '#0C0818', caja: false, color_caja: '#000000',
  alfa_caja: 0.55, x: 0.5, y: 0.8, align: 'centro', fundido: 0,
  karaoke: true, color_activo: '#FFD60A',
};

function agrupar(palabras, L) {
  /* Mismas reglas que usa el estudio de avatares, para que los subtitulos
     tengan el mismo ritmo: corta por fin de frase, por silencio, cuando la
     linea se pasa de ancha o cuando dura demasiado. */
  const g = document.createElement('canvas').getContext('2d');
  g.font = fuenteDe(ESTILO_SUB, L.h);
  const ancho = (ws) => g.measureText(ws.map((x) => x.w).join(' ')).width;
  const cabe = SUB.anchoLinea * L.w;
  /* Lo que decide si un grupo es demasiado largo no es su ancho total, sino si
     se puede repartir en dos lineas sin que ninguna se salga. Medir solo el
     total deja pasar grupos que luego no hay por donde partir, y el subtitulo
     acaba con una palabra sola arriba. */
  const repartible = (ws) => {
    const t = ws.map((x) => x.w);
    if (g.measureText(t.join(' ')).width <= cabe) return true;
    for (let k = 1; k < t.length; k++) {
      if (g.measureText(t.slice(0, k).join(' ')).width <= cabe &&
          g.measureText(t.slice(k).join(' ')).width <= cabe) return true;
    }
    return false;
  };
  const grupos = [];
  let cur = [];
  for (const w of palabras) {
    const punt = w.p || '';
    const salto = cur.length && (w.t0 - cur[cur.length - 1].t1) > SUB.hueco;
    const tr = cur.concat([w]);
    if (cur.length && (!repartible(tr) ||
                       (tr[tr.length - 1].t1 - tr[0].t0) > SUB.segundos || salto)) {
      grupos.push(cur); cur = [w];
    } else {
      cur = tr;
    }
    const corta = [...punt].some((ch) => DURO.has(ch)) ||
                  (punt.includes(',') && ancho(cur) > SUB.anchoComa * L.w);
    if (cur.length && corta) { grupos.push(cur); cur = []; }
  }
  if (cur.length) grupos.push(cur);
  // una palabra sola queda huerfana: se le pasa la ultima del grupo anterior
  for (let i = 1; i < grupos.length; i++) {
    if (grupos[i].length === 1 && grupos[i - 1].length >= 3) {
      const ult = grupos[i - 1][grupos[i - 1].length - 1];
      if (![...(ult.p || '')].some((ch) => DURO.has(ch)) &&
          repartible([ult].concat(grupos[i]))) {
        grupos[i].unshift(grupos[i - 1].pop());
      }
    }
  }
  return grupos;
}

function repartirLineas(grupo, L) {
  /* Parte el grupo en hasta dos lineas sin pasarse de ancho.
     Permitir la segunda linea es lo que deja frasear bien: con una sola, un
     subtitulo grande cabe en tres palabras y las frases quedan cortadas por
     donde no toca ("diez videos se" / "pierden en los"). */
  const g = document.createElement('canvas').getContext('2d');
  g.font = fuenteDe(ESTILO_SUB, L.h);
  const cabe = SUB.anchoLinea * L.w;
  const palabras = grupo.map((w) => w.w);
  if (g.measureText(palabras.join(' ')).width <= cabe) return palabras.join(' ');
  // El corte que deja la linea mas larga lo mas corta posible. Buscar el mas
  // parejo "siempre que quepa" deja sin respuesta a los grupos que no caben, y
  // entonces hay que elegir igual: mejor el menos malo que una palabra suelta.
  let mejor = 1, peor = Infinity;
  for (let k = 1; k < palabras.length; k++) {
    const a = g.measureText(palabras.slice(0, k).join(' ')).width;
    const b = g.measureText(palabras.slice(k).join(' ')).width;
    if (Math.max(a, b) < peor) { peor = Math.max(a, b); mejor = k; }
  }
  return palabras.slice(0, mejor).join(' ') + SALTO + palabras.slice(mejor).join(' ');
}

function pistaLibreArriba() {
  /* Una pista de video por encima de todo, para que los subtitulos no tapen
     nada que importe ni se los coma otro clip. */
  const arriba = E.montaje.pistas.find((p) => p.tipo === 'video');
  const ocupada = E.montaje.clips.some((c) => arriba && c.pista === arriba.id);
  if (arriba && !ocupada) return arriba.id;
  const id = 'v' + nuevoId().slice(0, 4);
  E.montaje.pistas.unshift({ id, tipo: 'video', nombre: 'Subtítulos',
                             muda: false, oculta: false });
  pintarPistas();
  return id;
}

function ponerSubtitulos(palabras, desfase, recorte) {
  /* Crea un rotulo por grupo de palabras. `desfase` es donde empieza el audio
     en la linea de tiempo; `recorte` es [entrada, fin] del clip de audio, para
     no poner subtitulos de un trozo que no se oye. */
  const L = E.montaje.lienzo;
  const pista = pistaLibreArriba();
  const [ini, fin] = recorte || [0, Infinity];
  const grupos = agrupar(palabras, L);
  /* A cada subtitulo se le da una cola para que no desaparezca en seco al
     acabar la ultima palabra. Pero esa cola NO puede morder al siguiente: si
     se pisan, los dos se dibujan a la vez y el texto sale superpuesto. */
  const tramos = grupos.map((g) => ({
    g, a: Math.max(g[0].t0, ini), b: Math.min(g[g.length - 1].t1 + 0.18, fin),
  }));
  for (let i = 0; i < tramos.length - 1; i++) {
    tramos[i].b = Math.min(tramos[i].b, tramos[i + 1].a);
  }
  let puestos = 0;
  for (const { g: grupo, a, b } of tramos) {
    const t0 = grupo[0].t0, t1 = grupo[grupo.length - 1].t1;
    if (t1 <= ini || t0 >= fin) continue;
    if (b - a < 0.08) continue;
    const c = {
      id: nuevoId(), pista, medio: '', tipo: 'texto',
      t: Math.round((desfase + a - ini) * 1000) / 1000,
      dur: Math.round((b - a) * 1000) / 1000,
      entrada: 0, veloc: 1, volumen: 1, opacidad: 1, encaje: 'cubrir',
      texto: repartirLineas(grupo, L),
      palabras: grupo.map((w) => ({ w: w.w,
                                    t0: Math.round((w.t0 - a) * 1000) / 1000,
                                    t1: Math.round((w.t1 - a) * 1000) / 1000 })),
      ...ESTILO_SUB,
    };
    c.nombre = c.texto.slice(0, 40);
    E.montaje.clips.push(c);
    puestos++;
  }
  return puestos;
}

async function palabrasDe(medioId) {
  try {
    const r = await pedir('/api/medios/' + medioId + '/palabras');
    if (!r.ok) return null;
    return await r.json();
  } catch (e) { return null; }
}

async function subtitularClip() {
  /* Subtitula el clip elegido, si su audio lo genero el programa. */
  const c = clip(E.elegido);
  if (!c || c.tipo === 'texto') {
    error('Elige el clip de voz al que quieras ponerle subtítulos.');
    return;
  }
  const m = E.medios.get(c.medio);
  if (!m || !m.palabras) {
    error('Ese clip no trae los tiempos de sus palabras. Los subtítulos ' +
          'automáticos solo funcionan con la voz que genera el propio editor; ' +
          'una voz grabada necesitaría reconocimiento del habla.');
    return;
  }
  const pal = await palabrasDe(c.medio);
  if (!pal) { error('No se pudieron leer los tiempos de esa voz.'); return; }
  const n = ponerSubtitulos(pal, c.t, [c.entrada, c.entrada + c.dur * c.veloc]);
  error(n ? '' : 'No salió ningún subtítulo en ese tramo.');
  cambiado({ paso: 'subtitular' + nuevoId() });
  pintarInspector();
}

async function generarVoz() {
  const texto = $('#voz-texto').value.trim();
  if (texto.length < 2) { error('Escribe el guion que quieres locutar.'); return; }
  const boton = $('#voz-generar');
  boton.disabled = true;
  const antes = boton.textContent;
  boton.textContent = 'Locutando…';
  try {
    const r = await pedir('/api/voz', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ texto, voz: $('#voz-id').value,
                             velocidad: +$('#voz-vel').value }),
    });
    const d = await r.json();
    if (!d.ok) throw new Error(d.error || 'no se pudo locutar');
    E.medios.set(d.medio.id, d.medio);
    pintarMedios();

    const pistaAudio = E.montaje.pistas.find((p) => p.tipo === 'audio');
    const inicio = E.t;
    if (pistaAudio) {
      const c = {
        id: nuevoId(), pista: pistaAudio.id, medio: d.medio.id,
        t: inicio, dur: d.medio.dur, entrada: 0, veloc: 1, volumen: 1,
        opacidad: 1, encaje: 'cubrir', nombre: d.medio.nombre,
      };
      c.t = acomodar(c, c.t);
      E.montaje.clips.push(c);
      E.elegido = c.id;
      if ($('#voz-subs').checked) {
        ponerSubtitulos(d.palabras, c.t, [0, d.medio.dur]);
      }
    }
    error('');
    cambiado({ paso: 'voz' + nuevoId() });
    pintarInspector();
  } catch (e) {
    error('Voz: ' + e.message);
  } finally {
    boton.disabled = false;
    boton.textContent = antes;
  }
}

function llenarVoces(voces) {
  const sel = $('#voz-id');
  if (!sel || !voces) return;
  const porPais = {};
  for (const v of voces) (porPais[v.pais] = porPais[v.pais] || []).push(v);
  sel.textContent = '';
  for (const pais of Object.keys(porPais).sort()) {
    const g = document.createElement('optgroup');
    g.label = pais;
    for (const v of porPais[pais]) {
      const o = document.createElement('option');
      o.value = v.id;
      o.textContent = `${v.id.split('-')[2].replace('Neural', '')} · ${v.genero}`;
      g.appendChild(o);
    }
    sel.appendChild(g);
  }
  const guardada = localStorage.getItem('voz-editor');
  if (guardada && voces.some((v) => v.id === guardada)) sel.value = guardada;
  else if (voces.some((v) => v.id === 'es-MX-JorgeNeural')) sel.value = 'es-MX-JorgeNeural';
  sel.onchange = () => localStorage.setItem('voz-editor', sel.value);
}

/* ═════════════════════════════════════════════ vista previa en canvas */
const reproductores = new Map();

function corral() {
  /* Los <video> y <audio> de la vista previa tienen que estar DENTRO del
     documento. Sueltos en memoria se pueden dibujar, pero el navegador no
     garantiza que suenen, y aqui el sonido es la mitad del montaje. Se
     esconden en un rincon de 2 px: con display:none algunos navegadores ni
     descodifican. */
  let c = $('#reproductores');
  if (!c) {
    c = document.createElement('div');
    c.id = 'reproductores';
    c.setAttribute('aria-hidden', 'true');
    document.body.appendChild(c);
  }
  return c;
}

function reproductor(m) {
  if (reproductores.has(m.id)) return reproductores.get(m.id);
  let el;
  if (m.tipo === 'imagen') {
    el = new Image();
    el.src = m.original;
  } else {
    el = document.createElement(m.tipo === 'audio' ? 'audio' : 'video');
    el.src = m.url;
    el.preload = 'auto';
    el.playsInline = true;
    el.muted = false;
    el.dataset.medio = m.id;
    corral().appendChild(el);
  }
  reproductores.set(m.id, el);
  return el;
}

function activos(t) {
  const porPista = new Map(E.montaje.pistas.map((p, i) => [p.id, i]));
  // Mismo orden que usa exportar.py al superponer: primero la pista de abajo
  // y, dentro de una pista, el que empieza antes. Si los dos modelos ordenan
  // distinto, la vista previa ensena una cosa y el MP4 sale con otra.
  return E.montaje.clips
    .filter((c) => t >= c.t && t < c.t + c.dur)
    .sort((a, b) => (porPista.get(b.pista) - porPista.get(a.pista)) || (a.t - b.t));
}

function ajustarLienzo() {
  const L = E.montaje.lienzo;
  const cv = $('#lienzo');
  const lado = 540;
  if (L.w >= L.h) { cv.width = lado; cv.height = Math.round(lado * L.h / L.w); }
  else { cv.height = Math.round(lado * 16 / 9); cv.width = Math.round(cv.height * L.w / L.h); }
  encajarLienzo();
}

function encajarLienzo() {
  /* El canvas se dibuja siempre a su resolucion interna; lo que cambia es el
     tamano al que se ve. Se mide el hueco y se escoge la escala que cabe. */
  const cv = $('#lienzo'), marco = $('.marco-vista');
  if (!cv || !marco) return;
  const caja = marco.getBoundingClientRect();
  if (caja.width < 2 || caja.height < 2) return;
  const k = Math.min(caja.width / cv.width, caja.height / cv.height);
  cv.style.width = Math.floor(cv.width * k) + 'px';
  cv.style.height = Math.floor(cv.height * k) + 'px';
}

const FX_NEUTRO = { brillo: 1, contraste: 1, saturacion: 1, tono: 0, desenfoque: 0 };
const RECETAS = {
  vivo:   { contraste: 1.18, saturacion: 1.35 },
  calido: { brillo: 1.06, saturacion: 1.15, tono: -8 },
  frio:   { contraste: 1.08, saturacion: 0.95, tono: 12 },
  cine:   { contraste: 1.22, saturacion: 0.82, brillo: 0.96 },
  gris:   { saturacion: 0 },
  suave:  { contraste: 0.92, saturacion: 0.9, desenfoque: 0.0015 },
};

function filtroCanvas(c, W) {
  /* El MISMO orden que arma exportar.py. Cambiar el orden cambia el
     resultado: subir el brillo y luego el contraste no da lo mismo que al
     reves, asi que los dos lados tienen que encadenar igual. */
  const f = Object.assign({}, FX_NEUTRO, c.fx || {});
  const partes = [];
  if (Math.abs(f.brillo - 1) > 1e-3) partes.push(`brightness(${f.brillo})`);
  if (Math.abs(f.contraste - 1) > 1e-3) partes.push(`contrast(${f.contraste})`);
  if (Math.abs(f.saturacion - 1) > 1e-3) partes.push(`saturate(${f.saturacion})`);
  if (Math.abs(f.tono) > 0.5) partes.push(`hue-rotate(${f.tono}deg)`);
  if (f.desenfoque > 1e-4) partes.push(`blur(${(f.desenfoque * W).toFixed(2)}px)`);
  return partes.length ? partes.join(' ') : 'none';
}

function alfaClip(c, t) {
  /* Opacidad con los fundidos de entrada y salida ya aplicados. */
  let a = c.opacidad;
  const ent = c.fundido_ent || 0, sal = c.fundido_sal || 0;
  if (ent > 0.01) a *= Math.min((t - c.t) / ent, 1);
  if (sal > 0.01) a *= Math.min((c.t + c.dur - t) / sal, 1);
  return Math.max(Math.min(a, 1), 0);
}

function encajar(g, src, sw, sh, W, H, modo) {
  if (!sw || !sh) return;
  if (modo === 'estirar') { g.drawImage(src, 0, 0, W, H); return; }
  const k = modo === 'contener' ? Math.min(W / sw, H / sh) : Math.max(W / sw, H / sh);
  const w = sw * k, h = sh * k;
  g.drawImage(src, (W - w) / 2, (H - h) / 2, w, h);
}

function dibujar() {
  const cv = $('#lienzo'), g = cv.getContext('2d');
  g.fillStyle = '#000';
  g.fillRect(0, 0, cv.width, cv.height);
  const vistos = new Set();
  let maestro = true;   // el primer medio de la tanda manda en el reloj

  for (const c of activos(E.t)) {
    if (c.tipo === 'texto') {
      const pistaT = E.montaje.pistas.find((p) => p.id === c.pista);
      if (!pistaT || !pistaT.oculta) {
        pintarRotulo(g, c, cv.width, cv.height, alfaRotulo(c, E.t),
                     undefined, undefined, palabraEn(c, E.t - c.t));
      }
      continue;
    }
    const m = E.medios.get(c.medio);
    if (!m) continue;
    const pista = E.montaje.pistas.find((p) => p.id === c.pista);
    const el = reproductor(m);
    vistos.add(m.id);

    const st = c.entrada + (E.t - c.t) * c.veloc;
    if (m.tipo !== 'imagen') {
      const suena = !pista.muda && c.volumen > 0;
      el.volume = suena ? Math.min(c.volumen, 1) : 0;
      el.muted = !suena;
      el.playbackRate = Math.min(Math.max(c.veloc, 0.25), 4);
      if (E.reproduciendo) {
        if (el.paused) el.play().catch(() => {});
        const desfase = el.currentTime - st;
        if (Math.abs(desfase) > SALTO_GORDO) {
          // de verdad esta en otro sitio (se movio el cabezal): saltar
          el.currentTime = st;
        } else if (maestro && !el.paused && el.readyState >= 2 &&
                   Math.abs(desfase) > 0.02 && E.ancla) {
          /* Desfase pequeno. Forzar el medio cada fotograma le haria dar
             saltitos, porque un <video> tarda en posicionarse. Se mueve el
             RELOJ hacia el medio, poco a poco: el cabezal acaba marcando lo
             que de verdad se esta viendo y oyendo. */
          E.ancla.reloj -= desfase * 1000 * 0.25;
        }
      } else {
        if (!el.paused) el.pause();
        if (Math.abs(el.currentTime - st) > 0.04) el.currentTime = st;
      }
      maestro = false;
    }
    if (m.tipo === 'audio' || (pista && pista.oculta)) continue;

    const sw = m.tipo === 'imagen' ? el.naturalWidth : el.videoWidth;
    const sh = m.tipo === 'imagen' ? el.naturalHeight : el.videoHeight;
    if (!sw) continue;
    g.save();
    g.globalAlpha = alfaClip(c, E.t);
    g.filter = filtroCanvas(c, cv.width);
    encajar(g, el, sw, sh, cv.width, cv.height, c.encaje);
    g.restore();
  }

  for (const [id, el] of reproductores) {
    if (!vistos.has(id) && el.pause && !el.paused) el.pause();
  }
}

function bucle() {
  if (E.reproduciendo && E.ancla) {
    E.t = E.ancla.t + (performance.now() - E.ancla.reloj) / 1000;
    const fin = duracionTotal();
    if (E.t >= fin) { E.t = fin; pausar(); }
    moverCabezal();
    $('#reloj').textContent = `${RELOJ(E.t)} / ${RELOJ(fin)}`;
    seguirCabezal();
  }
  dibujar();
  requestAnimationFrame(bucle);
}

function seguirCabezal() {
  const d = $('#desplaza');
  const x = px(E.t);
  if (x < d.scrollLeft + 40 || x > d.scrollLeft + d.clientWidth - 90) {
    d.scrollLeft = x - d.clientWidth * 0.35;
  }
}

function tocar() {
  if (duracionTotal() <= 0) return;
  if (E.t >= duracionTotal() - 0.02) E.t = 0;
  E.reproduciendo = true;
  E.ancla = { t: E.t, reloj: performance.now() };
  $('#btn-play').innerHTML = '<svg viewBox="0 0 24 24"><path d="M7 5h4v14H7zM13 5h4v14h-4z"/></svg>';
  $('#btn-play').setAttribute('aria-label', 'Pausa');
}

function pausar() {
  E.reproduciendo = false; E.ancla = null;
  for (const el of reproductores.values()) if (el.pause) el.pause();
  $('#btn-play').innerHTML = '<svg viewBox="0 0 24 24"><path d="M7 4l13 8-13 8V4Z"/></svg>';
  $('#btn-play').setAttribute('aria-label', 'Reproducir');
}

function irA(t) {
  E.t = Math.max(Math.min(t, Math.max(duracionTotal(), 0)), 0);
  if (E.reproduciendo) E.ancla = { t: E.t, reloj: performance.now() };
  moverCabezal();
  $('#reloj').textContent = `${RELOJ(E.t)} / ${RELOJ(duracionTotal())}`;
}

/* ═════════════════════════════════════════════════════════ arrastre */
const IMAN = 8;   // píxeles dentro de los cuales un clip se pega a otro

function imanes(menos) {
  const xs = [0, E.t];
  for (const c of E.montaje.clips) {
    if (c.id === menos) continue;
    xs.push(c.t, c.t + c.dur);
  }
  return xs;
}

function pegar(valor, menos) {
  for (const x of imanes(menos)) {
    if (Math.abs(px(valor) - px(x)) < IMAN) return x;
  }
  return valor;
}

function conectarArrastre() {
  const caja = $('#pistas');

  caja.addEventListener('pointerdown', (ev) => {
    const el = ev.target.closest('.clip');
    if (!el) return;
    const c = clip(el.dataset.clip);
    if (!c) return;
    E.elegido = c.id;
    document.querySelectorAll('.clip.elegido').forEach((n) => n.classList.remove('elegido'));
    el.classList.add('elegido');
    pintarInspector();

    const asa = ev.target.closest('.asa');
    const modo = asa ? (asa.classList.contains('izq') ? 'izq' : 'der') : 'mover';
    const x0 = ev.clientX, y0 = ev.clientY;
    const ini = { t: c.t, dur: c.dur, entrada: c.entrada, pista: c.pista };
    el.setPointerCapture(ev.pointerId);
    ev.preventDefault();

    const mover = (e) => {
      const d = seg(e.clientX - x0);
      if (modo === 'mover') {
        c.t = Math.max(pegar(ini.t + d, c.id), 0);
        // cambiar de pista: se mira sobre cuál está el puntero
        const bajo = document.elementFromPoint(e.clientX, e.clientY);
        const p = bajo && bajo.closest('.carril');
        if (p && p.dataset.pista !== c.pista) {
          const dest = E.montaje.pistas.find((x) => x.id === p.dataset.pista);
          const m = E.medios.get(c.medio);
          // en una pista de audio no pinta nada lo que no suena
          const sinSonido = c.tipo === 'texto' || (m && m.tipo === 'imagen');
          if (dest && !(dest.tipo === 'audio' && sinSonido)) {
            c.pista = dest.id;
          }
        }
      } else if (modo === 'der') {
        const der = vecinoDerecha(c);
        const tope = Math.min(topeClip(c), der ? der.t - c.t : Infinity);
        c.dur = Math.max(Math.min(pegar(ini.t + ini.dur + d, c.id) - c.t, tope), 0.08);
      } else {
        const izq = vecinoIzquierda(c);
        const suelo = izq ? izq.t + izq.dur : 0;
        const nt = Math.max(pegar(ini.t + d, c.id), suelo);
        const corrido = nt - ini.t;
        const nuevaEntrada = ini.entrada + corrido * c.veloc;
        if (nuevaEntrada < 0) return;
        const nd = ini.dur - corrido;
        if (nd < 0.08) return;
        c.t = nt; c.dur = nd; c.entrada = nuevaEntrada;
      }
      el.style.left = px(c.t) + 'px';
      el.style.width = Math.max(px(c.dur), 8) + 'px';
      Object.assign(el.style, fondoClip(c));
      if (c.pista !== ini.pista) {
        const p = document.querySelector(`.carril[data-pista="${c.pista}"]`);
        if (p && el.parentElement !== p) p.appendChild(el);
      }
    };
    const soltar = () => {
      el.releasePointerCapture(ev.pointerId);
      el.removeEventListener('pointermove', mover);
      el.removeEventListener('pointerup', soltar);
      c.dur = Math.round(c.dur * 1000) / 1000;
      c.t = Math.round(acomodar(c, c.t) * 1000) / 1000;
      cambiado({ paso: 'mover' + c.id });
      pintarInspector();
    };
    el.addEventListener('pointermove', mover);
    el.addEventListener('pointerup', soltar);
    el.addEventListener('pointercancel', soltar);
  });

  // soltar un medio de la bandeja sobre una pista
  caja.addEventListener('dragover', (ev) => {
    if (!ev.dataTransfer.types.includes('text/medio')) return;
    ev.preventDefault();
    ev.dataTransfer.dropEffect = 'copy';
    document.querySelectorAll('.carril.destino').forEach((p) => p.classList.remove('destino'));
    const p = ev.target.closest('.carril');
    if (p) p.classList.add('destino');
  });
  caja.addEventListener('dragleave', () => {
    document.querySelectorAll('.carril.destino').forEach((p) => p.classList.remove('destino'));
  });
  caja.addEventListener('drop', (ev) => {
    const id = ev.dataTransfer.getData('text/medio');
    const p = ev.target.closest('.carril');
    document.querySelectorAll('.carril.destino').forEach((x) => x.classList.remove('destino'));
    if (!id || !p) return;
    ev.preventDefault();
    const r = $('#interior').getBoundingClientRect();
    anadirClip(id, p.dataset.pista, Math.max(pegar(seg(ev.clientX - r.left)), 0));
    pintarInspector();
  });

  // el cabezal se arrastra desde la regla
  const regla = $('#regla');
  const desdeRegla = (e) => {
    const r = $('#interior').getBoundingClientRect();
    irA(seg(e.clientX - r.left));
  };
  regla.addEventListener('pointerdown', (ev) => {
    regla.setPointerCapture(ev.pointerId);
    desdeRegla(ev);
    const mv = (e) => desdeRegla(e);
    const up = () => {
      regla.releasePointerCapture(ev.pointerId);
      regla.removeEventListener('pointermove', mv);
      regla.removeEventListener('pointerup', up);
    };
    regla.addEventListener('pointermove', mv);
    regla.addEventListener('pointerup', up);
  });
}

function conectarArrastreRotulo() {
  /* Colocar un rotulo con dos mandos de numeros es un suplicio: se arrastra
     sobre la propia vista previa, que es donde se ve si queda bien. */
  const cv = $('#lienzo');
  cv.addEventListener('pointerdown', (ev) => {
    const c = clip(E.elegido);
    if (!c || c.tipo !== 'texto') return;
    if (E.t < c.t || E.t >= c.t + c.dur) return;
    const r = cv.getBoundingClientRect();
    const ini = { x: c.x, y: c.y, px: ev.clientX, py: ev.clientY };
    cv.setPointerCapture(ev.pointerId);
    cv.classList.add('moviendo');
    ev.preventDefault();
    const mover = (e) => {
      c.x = Math.min(Math.max(ini.x + (e.clientX - ini.px) / r.width, -0.2), 1.2);
      c.y = Math.min(Math.max(ini.y + (e.clientY - ini.py) / r.height, -0.2), 1.2);
    };
    const soltar = () => {
      cv.releasePointerCapture(ev.pointerId);
      cv.classList.remove('moviendo');
      cv.removeEventListener('pointermove', mover);
      cv.removeEventListener('pointerup', soltar);
      c.x = Math.round(c.x * 1e4) / 1e4; c.y = Math.round(c.y * 1e4) / 1e4;
      cambiado({ repintar: false, paso: 'situar' + c.id });
    };
    cv.addEventListener('pointermove', mover);
    cv.addEventListener('pointerup', soltar);
    cv.addEventListener('pointercancel', soltar);
  });
}

/* ═════════════════════════════════════════════════════════ exportar */
async function exportar() {
  const dlg = $('#dlg-exportar');
  $('#exp-resumen').textContent =
    `${E.montaje.clips.length} clip(s) · ${RELOJ(duracionTotal())} · ` +
    `${E.montaje.lienzo.w}×${E.montaje.lienzo.h}`;
  $('#exp-barra').hidden = true;
  $('#exp-video').hidden = true;
  $('#exp-descarga').hidden = true;
  $('#exp-cancelar').hidden = true;
  $('#exp-estado').textContent = '';
  $('#exp-lanzar').disabled = E.montaje.clips.length === 0;
  dlg.showModal();
}

async function lanzarExportacion() {
  pausar();
  await guardar();
  $('#exp-lanzar').disabled = true;
  $('#exp-barra').hidden = false;
  $('#exp-cancelar').hidden = false;
  $('#exp-estado').textContent = 'Preparando…';
  let tid;
  try {
    const r = await pedir('/api/exportar', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ montaje: E.montaje, calidad: $('#exp-calidad').value,
                             rotulos: rotulosParaExportar() }),
    });
    const d = await r.json();
    if (!r.ok || d.error) throw new Error(d.error || 'no se pudo lanzar');
    tid = d.id;
  } catch (e) {
    $('#exp-estado').textContent = e.message;
    $('#exp-lanzar').disabled = false;
    $('#exp-cancelar').hidden = true;
    return;
  }
  $('#exp-cancelar').onclick = () => {
    $('#exp-estado').textContent = 'Cancelando…';
    pedir('/api/exportacion/' + tid + '/cancelar', { method: 'POST' }).catch(() => {});
  };
  const tic = setInterval(async () => {
    let d;
    try { d = await (await pedir('/api/exportacion/' + tid)).json(); } catch { return; }
    $('#exp-barra').querySelector('i').style.width = (d.pct || 0) + '%';
    $('#exp-estado').textContent = d.mensaje || '';
    if (d.estado === 'listo') {
      clearInterval(tic);
      $('#exp-cancelar').hidden = true;
      $('#exp-video').src = d.video; $('#exp-video').hidden = false;
      $('#exp-descarga').href = d.descarga; $('#exp-descarga').hidden = false;
      $('#exp-lanzar').disabled = false;
    } else if (d.estado === 'error') {
      clearInterval(tic);
      $('#exp-cancelar').hidden = true;
      $('#exp-lanzar').disabled = false;
    }
  }, 900);
}

/* ═════════════════════════════════════════════════════════ montajes */
async function listaMontajes() {
  const d = await (await pedir('/api/editor/inicio')).json();
  const ul = $('#lista-montajes');
  ul.textContent = '';
  if (!d.montajes.length) {
    ul.innerHTML = '<li class="mini tenue">Todavía no hay ninguno guardado.</li>';
  }
  for (const m of d.montajes) {
    const li = document.createElement('li');
    li.innerHTML = `<div class="crece"><b>${m.nombre}</b><br>
      <small>${m.clips} clip(s) · ${RELOJ(m.dur)} · ${m.guardado || ''}</small></div>
      <button class="boton secundario chico abrir">Abrir</button>
      <button class="icono descartar" aria-label="Borrar montaje">
        <svg viewBox="0 0 24 24"><path d="M4 7h16M9 7V5h6v2M7 7l1 13h8l1-13"/></svg></button>`;
    li.querySelector('.abrir').onclick = async () => {
      $('#dlg-montajes').close(); await abrirMontaje(m.id);
    };
    li.querySelector('.descartar').onclick = async () => {
      if (!confirm(`¿Borrar "${m.nombre}"? No se puede deshacer.`)) return;
      await pedir('/api/montaje/borrar', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ id: m.id }),
      }).catch(() => {});
      listaMontajes();
    };
    ul.appendChild(li);
  }
  $('#dlg-montajes').showModal();
}

/* ═════════════════════════════════════════════════════════ conectar */
function conectar() {
  conectarArrastre();
  new ResizeObserver(encajarLienzo).observe($('.marco-vista'));

  $('#archivo-medios').onchange = (e) => { subirArchivos(e.target.files); e.target.value = ''; };
  const zona = $('#soltar-medios');
  ['dragenter', 'dragover'].forEach((n) => zona.addEventListener(n, (e) => {
    e.preventDefault(); zona.classList.add('encima');
  }));
  ['dragleave', 'drop'].forEach((n) => zona.addEventListener(n, (e) => {
    e.preventDefault(); zona.classList.remove('encima');
  }));
  zona.addEventListener('drop', (e) => subirArchivos(e.dataTransfer.files));

  $('#btn-play').onclick = () => (E.reproduciendo ? pausar() : tocar());
  $('#btn-inicio').onclick = () => { irA(0); };
  $('#btn-cortar').onclick = partir;
  $('#btn-borrar').onclick = borrarClip;
  $('#btn-duplicar').onclick = duplicar;

  const zoom = $('#zoom');
  zoom.oninput = () => { E.zoom = +zoom.value; pintarTiempo(); };
  $('#btn-zoom-mas').onclick = () => { zoom.value = Math.min(+zoom.value * 1.4, 320); zoom.oninput(); };
  $('#btn-zoom-menos').onclick = () => { zoom.value = Math.max(+zoom.value / 1.4, 10); zoom.oninput(); };

  $('#btn-pista').onclick = () => {
    const vs = E.montaje.pistas.filter((p) => p.tipo === 'video').length;
    E.montaje.pistas.unshift({ id: 'v' + (vs + 1) + nuevoId().slice(0, 3),
      tipo: 'video', nombre: `Vídeo ${vs + 1}`, muda: false, oculta: false });
    pintarPistas(); cambiado({ paso: 'pista' + nuevoId() });
  };

  $('#nombre-montaje').oninput = () => {
    E.montaje.nombre = $('#nombre-montaje').value.trim() || 'Montaje';
    cambiado({ repintar: false, paso: 'nombre' });
  };
  $('#forma-lienzo').onchange = (e) => {
    const f = { vertical: [1080, 1920], horizontal: [1920, 1080],
                cuadrado: [1080, 1080], clasico: [1440, 1080] }[e.target.value];
    E.montaje.lienzo = { w: f[0], h: f[1], fps: E.montaje.lienzo.fps || 30,
                         forma: e.target.value };
    ajustarLienzo(); cambiado({ repintar: false, paso: 'lienzo' });
  };

  const prop = (sel, campo, fmt) => {
    $(sel).oninput = () => {
      const c = clip(E.elegido);
      if (!c) return;
      c[campo] = campo === 'encaje' ? $(sel).value : +$(sel).value;
      if (campo === 'veloc') {
        const der = vecinoDerecha(c);
        c.dur = Math.min(c.dur, topeClip(c), der ? der.t - c.t : Infinity);
      }
      pintarInspector(); cambiado({ paso: campo + c.id });
    };
  };
  prop('#p-veloc', 'veloc'); prop('#p-volumen', 'volumen');
  prop('#p-opacidad', 'opacidad'); prop('#p-encaje', 'encaje');

  const propTexto = (sel, campo, tipo) => {
    $(sel).oninput = () => {
      const c = clip(E.elegido);
      if (!c || c.tipo !== 'texto') return;
      const n = $(sel);
      c[campo] = tipo === 'num' ? +n.value : tipo === 'bool' ? n.checked : n.value;
      if (campo === 'texto') c.nombre = String(c.texto).split(SALTO)[0].slice(0, 40);
      pintarInspector();
      cambiado({ paso: campo + c.id });
    };
  };
  propTexto('#t-texto', 'texto'); propTexto('#t-fuente', 'fuente');
  propTexto('#t-align', 'align'); propTexto('#t-tam', 'tam', 'num');
  propTexto('#t-color', 'color'); propTexto('#t-contorno', 'contorno', 'num');
  propTexto('#t-color-contorno', 'color_contorno');
  propTexto('#t-caja', 'caja', 'bool'); propTexto('#t-color-caja', 'color_caja');
  propTexto('#t-fundido', 'fundido', 'num');
  $('#btn-texto').onclick = anadirTexto;
  $('#btn-subtitular').onclick = subtitularClip;
  $('#btn-fundir').onclick = fundirConAnterior;
  const propFx = (sel, campo) => {
    $(sel).oninput = () => {
      const c = clip(E.elegido);
      if (!c) return;
      c.fx = Object.assign({}, FX_NEUTRO, c.fx || {});
      c.fx[campo] = +$(sel).value;
      pintarInspector(); cambiado({ repintar: false, paso: campo + c.id });
    };
  };
  propFx('#f-brillo', 'brillo'); propFx('#f-contraste', 'contraste');
  propFx('#f-saturacion', 'saturacion'); propFx('#f-tono', 'tono');
  propFx('#f-desenfoque', 'desenfoque');
  const propFund = (sel, campo) => {
    $(sel).oninput = () => {
      const c = clip(E.elegido);
      if (!c) return;
      c[campo] = +$(sel).value;
      pintarInspector(); cambiado({ repintar: false, paso: campo + c.id });
    };
  };
  propFund('#f-ent', 'fundido_ent'); propFund('#f-sal', 'fundido_sal');
  $('#f-reset').onclick = () => {
    const c = clip(E.elegido);
    if (!c) return;
    c.fx = Object.assign({}, FX_NEUTRO);
    pintarInspector(); cambiado({ paso: 'fxreset' + nuevoId() });
  };
  for (const b of document.querySelectorAll('[data-receta]')) {
    b.onclick = () => {
      const c = clip(E.elegido);
      if (!c) return;
      c.fx = Object.assign({}, FX_NEUTRO, RECETAS[b.dataset.receta]);
      pintarInspector(); cambiado({ paso: 'receta' + nuevoId() });
    };
  }
  $('#voz-generar').onclick = generarVoz;
  $('#voz-vel').oninput = () => {
    $('#o-voz-vel').textContent = ($('#voz-vel').value > 0 ? '+' : '') +
                                  $('#voz-vel').value + '%';
  };
  $('#voz-vel').oninput();
  conectarArrastreRotulo();

  $('#btn-deshacer').onclick = () => viajar(-1);
  $('#btn-rehacer').onclick = () => viajar(1);
  $('#btn-exportar').onclick = exportar;
  $('#exp-lanzar').onclick = lanzarExportacion;
  $('#exp-cerrar').onclick = () => $('#dlg-exportar').close();
  $('#btn-montajes').onclick = listaMontajes;
  $('#mon-cerrar').onclick = () => $('#dlg-montajes').close();
  $('#mon-nuevo').onclick = () => {
    $('#dlg-montajes').close();
    localStorage.removeItem('montaje-abierto');
    nuevoMontaje();
  };

  document.addEventListener('keydown', (e) => {
    if (/^(INPUT|TEXTAREA|SELECT)$/.test(e.target.tagName)) return;
    if (document.querySelector('dialog[open]')) return;
    const salto = e.shiftKey ? 1 : 1 / 30;
    if ((e.ctrlKey || e.metaKey) && (e.key === 'z' || e.key === 'Z')) {
      e.preventDefault(); viajar(e.shiftKey ? 1 : -1); return;
    }
    if ((e.ctrlKey || e.metaKey) && (e.key === 'y' || e.key === 'Y')) {
      e.preventDefault(); viajar(1); return;
    }
    if (e.ctrlKey || e.metaKey) return;
    if (e.code === 'Space') { e.preventDefault(); E.reproduciendo ? pausar() : tocar(); }
    else if (e.key === 'ArrowRight') { e.preventDefault(); irA(E.t + salto); }
    else if (e.key === 'ArrowLeft') { e.preventDefault(); irA(E.t - salto); }
    else if (e.key === 's' || e.key === 'S') partir();
    else if (e.key === 'd' || e.key === 'D') duplicar();
    else if (e.key === 't' || e.key === 'T') { e.preventDefault(); anadirTexto(); }
    else if (e.key === 'Delete' || e.key === 'Backspace') { e.preventDefault(); borrarClip(); }
    else if (e.key === 'Home') irA(0);
  });

  window.addEventListener('beforeunload', (e) => {
    if (E.sucio) { e.preventDefault(); e.returnValue = ''; }
  });
}

arrancar();

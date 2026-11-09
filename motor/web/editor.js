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
  } catch (e) {
    error('No se pudo abrir ese montaje.');
  }
}

/* ═════════════════════════════════════════════════════════ guardado */
function cambiado({ repintar = true } = {}) {
  E.sucio = true;
  if (repintar) pintarTiempo();
  $('#estado-guardado').textContent = 'sin guardar';
  clearTimeout(E.guardando);
  E.guardando = setTimeout(guardar, 900);
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
    nombre: m.nombre,
  };
  E.montaje.clips.push(c);
  E.elegido = c.id;
  cambiado();
  return c;
}

function topeClip(c) {
  /* Hasta dónde puede estirarse: lo que queda de archivo. */
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
  error(''); cambiado();
}

function borrarClip() {
  if (!E.elegido) return;
  E.montaje.clips = E.montaje.clips.filter((c) => c.id !== E.elegido);
  E.elegido = null;
  cambiado();
}

function duplicar() {
  const c = clip(E.elegido);
  if (!c) return;
  const b = { ...c, id: nuevoId(), t: c.t + c.dur };
  E.montaje.clips.push(b);
  E.elegido = b.id;
  cambiado();
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
    n.querySelector('.ojo').onclick = () => { p.oculta = !p.oculta; pintarPistas(); cambiado(); };
    n.querySelector('.son').onclick = () => { p.muda = !p.muda; pintarPistas(); cambiado(); };
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
                   (m && m.tipo === 'audio' ? ' audio' : '');
    el.dataset.clip = c.id;
    el.style.left = px(c.t) + 'px';
    el.style.width = Math.max(px(c.dur), 8) + 'px';
    Object.assign(el.style, fondoClip(c));
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
  for (const b of ['#btn-cortar', '#btn-borrar', '#btn-duplicar']) $(b).disabled = !c;
  if (!c) return;
  const m = E.medios.get(c.medio);
  $('#inspector-nombre').textContent = c.nombre || (m ? m.nombre : 'Clip');
  $('#p-veloc').value = c.veloc; $('#o-veloc').textContent = c.veloc.toFixed(2) + '×';
  $('#p-volumen').value = c.volumen; $('#o-volumen').textContent = Math.round(c.volumen * 100) + '%';
  $('#p-opacidad').value = c.opacidad; $('#o-opacidad').textContent = Math.round(c.opacidad * 100) + '%';
  $('#p-encaje').value = c.encaje;
  const esVideo = m && m.tipo !== 'audio';
  $('#p-opacidad').closest('.campo-fila').hidden = !esVideo;
  $('#p-encaje').closest('.campo-fila').hidden = !esVideo;
  $('#p-volumen').closest('.campo-fila').hidden = !(m && (m.audio || m.tipo === 'audio'));
}

/* ═════════════════════════════════════════════ vista previa en canvas */
const reproductores = new Map();

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
  }
  reproductores.set(m.id, el);
  return el;
}

function activos(t) {
  const porPista = new Map(E.montaje.pistas.map((p, i) => [p.id, i]));
  return E.montaje.clips
    .filter((c) => t >= c.t && t < c.t + c.dur)
    .sort((a, b) => porPista.get(b.pista) - porPista.get(a.pista));  // abajo primero
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

  for (const c of activos(E.t)) {
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
        if (Math.abs(el.currentTime - st) > 0.3) el.currentTime = st;
        if (el.paused) el.play().catch(() => {});
      } else {
        if (!el.paused) el.pause();
        if (Math.abs(el.currentTime - st) > 0.04) el.currentTime = st;
      }
    }
    if (m.tipo === 'audio' || (pista && pista.oculta)) continue;

    const sw = m.tipo === 'imagen' ? el.naturalWidth : el.videoWidth;
    const sh = m.tipo === 'imagen' ? el.naturalHeight : el.videoHeight;
    if (!sw) continue;
    g.save();
    g.globalAlpha = c.opacidad;
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
          if (dest && !(dest.tipo === 'audio' && m && m.tipo === 'imagen')) {
            c.pista = dest.id;
          }
        }
      } else if (modo === 'der') {
        c.dur = Math.max(Math.min(pegar(ini.t + ini.dur + d, c.id) - c.t, topeClip(c)), 0.08);
      } else {
        const nt = Math.max(pegar(ini.t + d, c.id), 0);
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
      c.t = Math.round(c.t * 1000) / 1000;
      c.dur = Math.round(c.dur * 1000) / 1000;
      cambiado();
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

/* ═════════════════════════════════════════════════════════ exportar */
async function exportar() {
  const dlg = $('#dlg-exportar');
  $('#exp-resumen').textContent =
    `${E.montaje.clips.length} clip(s) · ${RELOJ(duracionTotal())} · ` +
    `${E.montaje.lienzo.w}×${E.montaje.lienzo.h}`;
  $('#exp-barra').hidden = true;
  $('#exp-video').hidden = true;
  $('#exp-descarga').hidden = true;
  $('#exp-estado').textContent = '';
  $('#exp-lanzar').disabled = E.montaje.clips.length === 0;
  dlg.showModal();
}

async function lanzarExportacion() {
  pausar();
  await guardar();
  $('#exp-lanzar').disabled = true;
  $('#exp-barra').hidden = false;
  $('#exp-estado').textContent = 'Preparando…';
  let tid;
  try {
    const r = await pedir('/api/exportar', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ montaje: E.montaje, calidad: $('#exp-calidad').value }),
    });
    const d = await r.json();
    if (!r.ok || d.error) throw new Error(d.error || 'no se pudo lanzar');
    tid = d.id;
  } catch (e) {
    $('#exp-estado').textContent = e.message;
    $('#exp-lanzar').disabled = false;
    return;
  }
  const tic = setInterval(async () => {
    let d;
    try { d = await (await pedir('/api/exportacion/' + tid)).json(); } catch { return; }
    $('#exp-barra').querySelector('i').style.width = (d.pct || 0) + '%';
    $('#exp-estado').textContent = d.mensaje || '';
    if (d.estado === 'listo') {
      clearInterval(tic);
      $('#exp-video').src = d.video; $('#exp-video').hidden = false;
      $('#exp-descarga').href = d.descarga; $('#exp-descarga').hidden = false;
      $('#exp-lanzar').disabled = false;
    } else if (d.estado === 'error') {
      clearInterval(tic);
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
    pintarPistas(); cambiado();
  };

  $('#nombre-montaje').oninput = () => cambiado({ repintar: false });
  $('#forma-lienzo').onchange = (e) => {
    const f = { vertical: [1080, 1920], horizontal: [1920, 1080],
                cuadrado: [1080, 1080], clasico: [1440, 1080] }[e.target.value];
    E.montaje.lienzo = { w: f[0], h: f[1], fps: E.montaje.lienzo.fps || 30,
                         forma: e.target.value };
    ajustarLienzo(); cambiado({ repintar: false });
  };

  const prop = (sel, campo, fmt) => {
    $(sel).oninput = () => {
      const c = clip(E.elegido);
      if (!c) return;
      c[campo] = campo === 'encaje' ? $(sel).value : +$(sel).value;
      if (campo === 'veloc') c.dur = Math.min(c.dur, topeClip(c));
      pintarInspector(); cambiado();
    };
  };
  prop('#p-veloc', 'veloc'); prop('#p-volumen', 'volumen');
  prop('#p-opacidad', 'opacidad'); prop('#p-encaje', 'encaje');

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
    if (e.code === 'Space') { e.preventDefault(); E.reproduciendo ? pausar() : tocar(); }
    else if (e.key === 'ArrowRight') { e.preventDefault(); irA(E.t + salto); }
    else if (e.key === 'ArrowLeft') { e.preventDefault(); irA(E.t - salto); }
    else if (e.key === 's' || e.key === 'S') partir();
    else if (e.key === 'd' || e.key === 'D') duplicar();
    else if (e.key === 'Delete' || e.key === 'Backspace') { e.preventDefault(); borrarClip(); }
    else if (e.key === 'Home') irA(0);
  });

  window.addEventListener('beforeunload', (e) => {
    if (E.sucio) { e.preventDefault(); e.returnValue = ''; }
  });
}

arrancar();

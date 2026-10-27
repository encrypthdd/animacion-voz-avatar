'use strict';

const $ = (s) => document.querySelector(s);
const ico = {
  check: '<svg viewBox="0 0 24 24"><path d="M5 13l4 4L19 7"/></svg>',
  equis: '<svg viewBox="0 0 24 24"><path d="M6 6l12 12M18 6L6 18"/></svg>',
  play:  '<svg viewBox="0 0 24 24"><path d="M6 4l14 8-14 8V4Z"/></svg>',
  carga: '<svg viewBox="0 0 24 24"><path d="M12 3a9 9 0 1 0 9 9"/></svg>',
};

const estado = {
  voces: [], genero: '', pais: '', voz: null,
  avatares: [], elegidos: new Set(),
  poses: [], fondo: 'violeta', trabajo: null,
};

// ───────────────────────────────────────────────────────────── arranque
async function arrancar() {
  let d;
  try {
    d = await (await fetch('/api/inicio')).json();
  } catch (e) {
    return error('No se pudo contactar con el servidor. ¿Sigue corriendo app.py?');
  }
  estado.voces = d.voces;
  estado.avatares = d.avatares;
  estado.poses = d.recursos;
  pintarFondos(d.fondos);
  pintarPaises();
  pintarVoces();
  pintarAvatares();
  pintarPoses();
  if (estado.avatares.length) estado.elegidos.add(estado.avatares[0].nombre);
  pintarAvatares();
}

// ───────────────────────────────────────────────────────────── avatares
function pintarAvatares() {
  const ul = $('#lista-avatares');
  ul.innerHTML = '';
  estado.avatares.forEach((a, i) => {
    const li = document.createElement('li');
    li.style.animationDelay = (i * 45) + 'ms';
    if (estado.elegidos.has(a.nombre)) li.classList.add('elegido');
    li.innerHTML = `
      <img src="${a.img || a.check}" alt="Avatar ${a.nombre}">
      <button class="quitar ver" type="button" aria-pressed="false"
              title="Ver la medición" aria-label="Ver la medición de ${a.nombre}">
        <svg viewBox="0 0 24 24"><path d="M2 12s4-7 10-7 10 7 10 7-4 7-10 7-10-7-10-7Z"/><circle cx="12" cy="12" r="3"/></svg>
      </button>
      ${a.aviso ? `<span class="marca-aviso" title="${a.aviso}">aviso</span>` : ''}
      <div class="pie">
        <span class="nom">${a.nombre}</span>
        <button class="sel" type="button" role="switch"
                aria-checked="${estado.elegidos.has(a.nombre)}"
                aria-label="Usar ${a.nombre} como avatar que habla">${ico.check}</button>
      </div>`;
    const img = li.querySelector('img'), ver = li.querySelector('.ver');
    ver.onclick = () => {
      const viendo = ver.getAttribute('aria-pressed') === 'true';
      img.src = viendo ? (a.img || a.check) : a.check;
      img.alt = viendo ? `Avatar ${a.nombre}`
                       : `Medición de ${a.nombre}: ojos, boca y cejas marcados`;
      ver.setAttribute('aria-pressed', String(!viendo));
    };
    li.querySelector('.sel').onclick = () => {
      estado.elegidos.has(a.nombre) ? estado.elegidos.delete(a.nombre)
                                    : estado.elegidos.add(a.nombre);
      pintarAvatares();
    };
    ul.appendChild(li);
  });
  $('#vacio-avatares').hidden = estado.avatares.length > 0;
  const av = estado.avatares.find((x) => estado.elegidos.has(x.nombre) && x.aviso);
  mostrarAviso(av ? av.aviso : '');
}

function mostrarAviso(txt) {
  let n = $('#aviso-avatar');
  if (!txt) { if (n) n.remove(); return; }
  if (!n) {
    n = document.createElement('p');
    n.id = 'aviso-avatar';
    n.className = 'aviso-error';
    n.style.marginTop = '14px';
    $('#lista-avatares').after(n);
  }
  n.textContent = txt;
}

function pintarPoses() {
  const ul = $('#lista-poses');
  ul.innerHTML = '';
  estado.poses.forEach((p, i) => {
    const li = document.createElement('li');
    li.style.animationDelay = (i * 40) + 'ms';
    li.innerHTML = `<img src="${p.img}" alt="Pose ${p.nombre}">
      <div class="pie"><span class="nom">${p.nombre}</span></div>`;
    ul.appendChild(li);
  });
}

// ───────────────────────────────────────────────────────────── subidas
function conectarSubida(zonaSel, inputSel, url, multiple) {
  const zona = $(zonaSel), input = $(inputSel);
  const mandar = async (archivos) => {
    for (const f of archivos) {
      const fd = new FormData();
      fd.append('archivo', f);
      fd.append('nombre', f.name);
      zona.classList.add('encima');
      const prev = zona.querySelector('p strong').textContent;
      zona.querySelector('p strong').textContent = 'Procesando ' + f.name + '…';
      try {
        const r = await (await fetch(url, { method: 'POST', body: fd })).json();
        if (!r.ok) {
          error(r.error || 'No se pudo procesar la imagen.');
        } else if (url.includes('avatar')) {
          estado.avatares = estado.avatares.filter((a) => a.nombre !== r.nombre);
          estado.avatares.push({ nombre: r.nombre, img: r.img, check: r.check, aviso: r.aviso });
          estado.elegidos.add(r.nombre);
          pintarAvatares();
          error('');
        } else {
          estado.poses = estado.poses.filter((p) => p.nombre !== r.nombre);
          estado.poses.push({ nombre: r.nombre, img: r.img });
          pintarPoses();
          error('');
        }
      } catch (e) {
        error('Falló la subida: ' + e.message);
      } finally {
        zona.classList.remove('encima');
        zona.querySelector('p strong').textContent = prev;
      }
    }
    input.value = '';
  };
  input.onchange = () => mandar([...input.files]);
  ['dragenter', 'dragover'].forEach((ev) =>
    zona.addEventListener(ev, (e) => { e.preventDefault(); zona.classList.add('encima'); }));
  ['dragleave', 'drop'].forEach((ev) =>
    zona.addEventListener(ev, (e) => { e.preventDefault(); zona.classList.remove('encima'); }));
  zona.addEventListener('drop', (e) => {
    const fs = [...e.dataTransfer.files].filter((f) => f.type.startsWith('image/'));
    mandar(multiple ? fs : fs.slice(0, 1));
  });
}

// ───────────────────────────────────────────────────────────── voces
function pintarPaises() {
  const sel = $('#pais');
  [...new Set(estado.voces.map((v) => v.pais))].sort().forEach((p) => {
    const o = document.createElement('option');
    o.value = p; o.textContent = p;
    sel.appendChild(o);
  });
  sel.onchange = () => { estado.pais = sel.value; pintarVoces(); };
}

function pintarVoces() {
  const ul = $('#lista-voces');
  const lista = estado.voces.filter((v) =>
    (!estado.genero || v.genero === estado.genero) &&
    (!estado.pais || v.pais === estado.pais));
  ul.innerHTML = '';
  if (!lista.length) {
    ul.innerHTML = '<li style="justify-content:center;color:var(--tenue)">Sin voces para ese filtro</li>';
    return;
  }
  if (!lista.some((v) => v.id === estado.voz)) {
    const pref = lista.find((v) => v.id === 'es-MX-JorgeNeural') || lista[0];
    estado.voz = pref.id;
  }
  lista.forEach((v, i) => {
    const li = document.createElement('li');
    li.setAttribute('role', 'option');
    li.setAttribute('aria-selected', v.id === estado.voz);
    li.tabIndex = 0;
    li.style.animationDelay = (Math.min(i, 12) * 25) + 'ms';
    const ini = v.id.split('-')[2].replace('Neural', '').slice(0, 2).toUpperCase();
    li.innerHTML = `
      <span class="ava ${v.genero === 'femenino' ? 'f' : ''}" aria-hidden="true">${ini}</span>
      <span class="datos">
        <span class="vid">${v.id.replace('Neural', '')}</span>
        <span class="meta">${v.pais} · ${v.genero}</span>
      </span>
      <button class="escuchar" type="button" aria-label="Escuchar ${v.id}">${ico.play}</button>`;
    const elegir = () => {
      estado.voz = v.id;
      [...ul.children].forEach((c) => c.setAttribute('aria-selected', 'false'));
      li.setAttribute('aria-selected', 'true');
    };
    li.onclick = elegir;
    li.onkeydown = (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); elegir(); } };
    li.querySelector('.escuchar').onclick = async (e) => {
      e.stopPropagation();
      const b = e.currentTarget;
      b.classList.add('cargando'); b.innerHTML = ico.carga;
      try {
        const a = $('#reproductor');
        a.src = '/api/muestra?voz=' + encodeURIComponent(v.id);
        await a.play();
      } catch (_) {
        error('No se pudo reproducir la muestra de voz.');
      } finally {
        b.classList.remove('cargando'); b.innerHTML = ico.play;
      }
    };
    ul.appendChild(li);
  });
}

// ───────────────────────────────────────────────────────────── estilo
function pintarFondos(fondos) {
  const c = $('#fondos');
  fondos.forEach((f) => {
    const b = document.createElement('button');
    b.type = 'button';
    b.setAttribute('role', 'radio');
    b.setAttribute('aria-checked', f.id === estado.fondo);
    b.setAttribute('aria-label', 'Fondo ' + f.id);
    b.title = f.id;
    b.style.background = f.css;
    b.onclick = () => {
      estado.fondo = f.id;
      [...c.children].forEach((x) => x.setAttribute('aria-checked', 'false'));
      b.setAttribute('aria-checked', 'true');
    };
    c.appendChild(b);
  });
}

// ───────────────────────────────────────────────────────────── generar
function error(msg) {
  const n = $('#error-global');
  n.hidden = !msg;
  n.textContent = msg || '';
  if (msg) n.scrollIntoView({ behavior: 'smooth', block: 'center' });
}

async function generar() {
  const guion = $('#guion').value.trim();
  if (guion.length < 10) return error('Escribe un guion de al menos 10 caracteres.');
  if (!estado.elegidos.size) return error('Marca al menos un avatar que pueda hablar.');
  if (!estado.voz) return error('Elige una voz.');
  error('');

  const btn = $('#generar');
  btn.setAttribute('aria-disabled', 'true');
  $('#acciones').hidden = true;
  $('#ficha').hidden = true;
  $('#video').hidden = true;
  $('#reposo').hidden = true;
  $('#progreso').hidden = false;
  avance(2, 'Enviando…');

  try {
    const r = await (await fetch('/api/generar', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        guion, titulo: $('#titulo').value.trim(), voz: estado.voz,
        fondo: estado.fondo, avatares: [...estado.elegidos],
        planos: $('#planos').value, recursos: $('#usar-recursos').checked,
        velocidad: +$('#velocidad').value,
      }),
    })).json();
    if (r.error) throw new Error(r.error);
    estado.trabajo = r.id;
    sondear(r.id);
  } catch (e) {
    fallo(e.message);
  }
}

function avance(pct, msg) {
  $('#barra-i').style.width = Math.max(pct, 2) + '%';
  $('#progreso-msg').textContent = msg;
}

function fallo(msg) {
  $('#progreso').hidden = true;
  $('#reposo').hidden = false;
  $('#generar').removeAttribute('aria-disabled');
  error(msg);
}

async function sondear(id) {
  try {
    const t = await (await fetch('/api/trabajo/' + id)).json();
    if (t.estado === 'error') return fallo(t.mensaje);
    avance(t.pct, t.mensaje);
    if (t.estado !== 'listo') return setTimeout(() => sondear(id), 700);

    avance(100, 'Listo');
    setTimeout(() => { $('#progreso').hidden = true; }, 500);
    const v = $('#video');
    v.src = t.video; v.hidden = false; v.load();
    $('#descargar').href = t.descarga;
    $('#acciones').hidden = false;
    $('#generar').removeAttribute('aria-disabled');

    const f = $('#ficha');
    const recursos = (t.planos || []).filter((p) => p.tipo.startsWith('pose:')).length;
    f.innerHTML = `
      <div><dt>Duración</dt><dd>${t.duracion} s</dd></div>
      <div><dt>Planos</dt><dd>${(t.planos || []).length}</dd></div>
      <div><dt>Poses de recurso</dt><dd>${recursos}</dd></div>
      <div><dt>Formato</dt><dd>1080×1920 · 30 fps</dd></div>`;
    f.hidden = false;
    $('#previo').scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  } catch (e) {
    fallo('Se perdió la conexión con el servidor.');
  }
}

// ───────────────────────────────────────────────────────────── eventos
document.querySelectorAll('.segmentado button').forEach((b) => {
  b.onclick = () => {
    document.querySelectorAll('.segmentado button').forEach((x) => x.classList.remove('activo'));
    b.classList.add('activo');
    estado.genero = b.dataset.genero;
    pintarVoces();
  };
});

$('#guion').addEventListener('input', (e) => {
  const n = e.target.value.length;
  $('#cuenta').textContent = n;
  $('#estimado').textContent = Math.round(n / 14.5) + ' s';
});

$('#velocidad').addEventListener('input', (e) => {
  $('#vel-val').textContent = (e.target.value > 0 ? '+' : '') + e.target.value + '%';
});

$('#generar').onclick = generar;
$('#otro').onclick = () => {
  $('#acciones').hidden = true;
  $('#ficha').hidden = true;
  $('#video').hidden = true;
  $('#reposo').hidden = false;
  window.scrollTo({ top: 0, behavior: 'smooth' });
};

conectarSubida('#soltar-avatar', '#file-avatar', '/api/avatar', false);
conectarSubida('#soltar-pose', '#file-pose', '/api/pose', true);
arrancar();

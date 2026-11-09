'use strict';
/* $, ico, pedir y error viven en comun.js, que se carga antes que este. */

const estado = {
  voces: [], genero: '', pais: '', voz: null,
  avatares: [], elegidos: new Set(),
  poses: [], trabajo: null,
  fondo: { modo: 'degradado', id: 'violeta', color: '#7C3AED', imagen: null,
           oscurecer: 0.45, desenfoque: 0.35 },
  musica: null, volMusica: -18, ducking: true, pistas: [],
};

// ───────────────────────────────────────────────────────────── arranque
async function arrancar() {
  let d;
  try {
    d = await (await pedir('/api/inicio')).json();
  } catch (e) {
    return error('No se pudo contactar con el servidor. ¿Sigue corriendo app.py?');
  }
  estado.voces = d.voces;
  estado.avatares = d.avatares;
  estado.poses = d.recursos;
  estado.imagenes = d.imagenes || [];
  // sin contraseña no hay sesión que cerrar
  const salir = document.querySelector('a[href="/salir"]');
  if (salir) salir.hidden = !d.clave;
  pintarFondos(d.fondos);
  pintarFondosImagen();
  estado.pistas = d.musica || [];
  pintarMusica();
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
function conectarSubida(zonaSel, inputSel, url, multiple, alLlegar) {
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
        const r = await (await pedir(url, { method: 'POST', body: fd })).json();
        if (!r.ok) {
          error(r.error || 'No se pudo procesar la imagen.');
        } else {
          alLlegar(r);
          error(r.aviso || '');
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

// ───────────────────────────────────────────────────────────── fondo
function pintarFondos(presets) {
  const c = $('#fondos');
  c.innerHTML = '';
  presets.forEach((f) => {
    const b = document.createElement('button');
    b.type = 'button';
    b.setAttribute('role', 'radio');
    b.setAttribute('aria-checked', f.id === estado.fondo.id);
    b.setAttribute('aria-label', 'Fondo ' + f.id);
    b.title = f.id;
    b.style.background = f.css;
    b.onclick = () => {
      estado.fondo.id = f.id;
      [...c.children].forEach((x) => x.setAttribute('aria-checked', 'false'));
      b.setAttribute('aria-checked', 'true');
    };
    c.appendChild(b);
  });
}

function pintarFondosImagen() {
  const ul = $('#lista-fondos');
  ul.innerHTML = '';
  (estado.imagenes || []).forEach((f, i) => {
    const li = document.createElement('li');
    li.style.animationDelay = (i * 40) + 'ms';
    if (f.nombre === estado.fondo.imagen) li.classList.add('elegido');
    li.innerHTML = `<img src="${f.mini}" alt="Fondo ${f.nombre}">
      <button class="quitar" type="button" aria-label="Quitar ${f.nombre}">${ico.equis}</button>
      <div class="pie"><span class="nom">${f.nombre}</span></div>`;
    li.onclick = () => { estado.fondo.imagen = f.nombre; pintarFondosImagen(); };
    li.querySelector('.quitar').onclick = async (e) => {
      e.stopPropagation();
      await pedir('/api/fondo/borrar', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ nombre: f.nombre }),
      });
      estado.imagenes = estado.imagenes.filter((x) => x.nombre !== f.nombre);
      if (estado.fondo.imagen === f.nombre) estado.fondo.imagen = null;
      pintarFondosImagen();
  estado.pistas = d.musica || [];
  pintarMusica();
    };
    ul.appendChild(li);
  });
  const hay = (estado.imagenes || []).length > 0;
  $('#vacio-fondos').hidden = hay;
  $('#ajustes-fondo').hidden = !estado.fondo.imagen;
  $('#nota-fondo').hidden = !estado.fondo.imagen;
}

function pintarMuestraColor() {
  const c = estado.fondo.color;
  $('#muestra-color').style.background =
    `radial-gradient(70% 50% at 50% 18%, ${c}, transparent 70%), ` +
    `linear-gradient(160deg, #141020, ${c}44)`;
}

function modoFondo(modo) {
  estado.fondo.modo = modo;
  document.querySelectorAll('#seg-fondo button').forEach((b) =>
    b.classList.toggle('activo', b.dataset.modo === modo));
  $('#panel-degradado').hidden = modo !== 'degradado';
  $('#panel-color').hidden = modo !== 'color';
  $('#panel-imagen').hidden = modo !== 'imagen';
}

/* Lo que se manda al servidor. Él vuelve a validarlo todo. */
function specFondo() {
  const f = estado.fondo;
  if (f.modo === 'color') return { tipo: 'color', color: f.color };
  if (f.modo === 'imagen' && f.imagen) {
    return { tipo: 'imagen', imagen: f.imagen,
             oscurecer: f.oscurecer, desenfoque: f.desenfoque };
  }
  return { tipo: 'degradado', id: f.id };
}

// ───────────────────────────────────────────────────────────── música
function pintarMusica() {
  const ul = $('#lista-musica');
  ul.innerHTML = '';
  const fila = (nombre, etiqueta, meta) => {
    const li = document.createElement('li');
    li.setAttribute('role', 'option');
    li.setAttribute('aria-selected', estado.musica === nombre);
    li.tabIndex = 0;
    li.innerHTML = `<span class="datos"><span class="nom">${etiqueta}</span>
        <span class="meta">${meta}</span></span>`;
    const elegir = () => { estado.musica = nombre; pintarMusica(); };
    li.onclick = elegir;
    li.onkeydown = (e) => {
      if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); elegir(); }
    };
    ul.appendChild(li);
    return li;
  };

  fila(null, 'Sin música', 'solo la voz');

  (estado.pistas || []).forEach((m) => {
    const li = fila(m.nombre, m.nombre, Math.round(m.dur) + ' s');
    const oir = document.createElement('button');
    oir.type = 'button'; oir.className = 'escuchar';
    oir.setAttribute('aria-label', 'Escuchar ' + m.nombre);
    oir.innerHTML = ico.play;
    oir.onclick = (e) => {
      e.stopPropagation();
      const a = $('#repro-musica');
      if (!a.paused && a.dataset.n === m.nombre) { a.pause(); return; }
      a.src = m.url; a.dataset.n = m.nombre; a.volume = 0.5;
      a.play().catch(() => error('No se pudo reproducir la pista.'));
    };
    const quitar = document.createElement('button');
    quitar.type = 'button'; quitar.className = 'quitar';
    quitar.setAttribute('aria-label', 'Quitar ' + m.nombre);
    quitar.innerHTML = ico.equis;
    quitar.onclick = async (e) => {
      e.stopPropagation();
      await pedir('/api/musica/borrar', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ nombre: m.nombre }),
      });
      estado.pistas = estado.pistas.filter((x) => x.nombre !== m.nombre);
      if (estado.musica === m.nombre) estado.musica = null;
      pintarMusica();
    };
    li.append(oir, quitar);
  });

  const hay = !!estado.musica;
  $('#ajustes-musica').hidden = !hay;
  $('#nota-musica').hidden = !hay;
  if (!hay) { const a = $('#repro-musica'); if (a) a.pause(); }
}

// ───────────────────────────────────────────────────────────── generar
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
    const r = await (await pedir('/api/generar', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        guion, titulo: $('#titulo').value.trim(), voz: estado.voz,
        fondo: specFondo(), avatares: [...estado.elegidos],
        planos: $('#planos').value, recursos: $('#usar-recursos').checked,
        musica: estado.musica, volumen_musica: estado.volMusica,
        ducking: estado.ducking,
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
    const t = await (await pedir('/api/trabajo/' + id)).json();
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
document.querySelectorAll('#seg-voz button').forEach((b) => {
  b.onclick = () => {
    document.querySelectorAll('#seg-voz button').forEach((x) => x.classList.remove('activo'));
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

conectarSubida('#soltar-avatar', '#file-avatar', '/api/avatar', false, (r) => {
  estado.avatares = estado.avatares.filter((a) => a.nombre !== r.nombre);
  estado.avatares.push({ nombre: r.nombre, img: r.img, check: r.check, aviso: r.aviso });
  estado.elegidos.add(r.nombre);
  pintarAvatares();
});
conectarSubida('#soltar-pose', '#file-pose', '/api/pose', true, (r) => {
  estado.poses = estado.poses.filter((p) => p.nombre !== r.nombre);
  estado.poses.push({ nombre: r.nombre, img: r.img });
  pintarPoses();
});
conectarSubida('#soltar-musica', '#file-musica', '/api/musica', false, (r) => {
  estado.pistas = (estado.pistas || []).filter((x) => x.nombre !== r.nombre);
  estado.pistas.push({ nombre: r.nombre, dur: r.dur, url: r.url });
  estado.musica = r.nombre;
  pintarMusica();
});
$('#vol-musica').addEventListener('input', (e) => {
  estado.volMusica = +e.target.value;
  $('#vol-val').textContent = '−' + Math.abs(e.target.value) + ' dB';
});
$('#ducking').addEventListener('change', (e) => { estado.ducking = e.target.checked; });

conectarSubida('#soltar-fondo', '#file-fondo', '/api/fondo', false, (r) => {
  estado.imagenes = (estado.imagenes || []).filter((x) => x.nombre !== r.nombre);
  estado.imagenes.push({ nombre: r.nombre, mini: r.mini });
  estado.fondo.imagen = r.nombre;
  pintarFondosImagen();
  estado.pistas = d.musica || [];
  pintarMusica();
});

// ── controles del fondo ──────────────────────────────────────────────
document.querySelectorAll('#seg-fondo button').forEach((b) => {
  b.onclick = () => modoFondo(b.dataset.modo);
});

const hex = /^#?[0-9a-fA-F]{6}$/;
function ponColor(v, desdeTexto) {
  if (!hex.test(v)) return;
  estado.fondo.color = v.startsWith('#') ? v : '#' + v;
  $('#color-fondo').value = estado.fondo.color;
  if (!desdeTexto) $('#color-hex').value = estado.fondo.color.toUpperCase();
  pintarMuestraColor();
}
$('#color-fondo').addEventListener('input', (e) => ponColor(e.target.value, false));
$('#color-hex').addEventListener('input', (e) => ponColor(e.target.value.trim(), true));
$('#color-hex').addEventListener('blur', () => {
  $('#color-hex').value = estado.fondo.color.toUpperCase();
});

$('#oscurecer').addEventListener('input', (e) => {
  estado.fondo.oscurecer = +e.target.value / 100;
  $('#osc-val').textContent = e.target.value + '%';
});
$('#desenfoque').addEventListener('input', (e) => {
  estado.fondo.desenfoque = +e.target.value / 100;
  $('#des-val').textContent = e.target.value + '%';
});
pintarMuestraColor();
arrancar();

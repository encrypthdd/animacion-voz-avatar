'use strict';
/* Creador de stickers. $, ico, pedir y error vienen de comun.js. */

const TAMANOS = [3, 4, 5, 6, 7, 8, 9, 10];

const st = {
  archivo: null,     // el File elegido, todavía sin subir
  objeto: null,      // su URL temporal, para la vista previa
  cm: 5,
  trabajo: null,
  resultado: null,
  formato: 'png',
};

// ───────────────────────────────────────────────────────────── tamaños
function pintarTamanos() {
  const c = $('#tamanos');
  c.innerHTML = '';
  TAMANOS.forEach((n) => {
    const b = document.createElement('button');
    b.type = 'button';
    b.setAttribute('role', 'radio');
    b.setAttribute('aria-checked', String(n === st.cm));
    b.innerHTML = `<strong>${n} × ${n}</strong><span>cm</span>`;
    b.onclick = () => {
      st.cm = n;
      [...c.children].forEach((x) => x.setAttribute('aria-checked', 'false'));
      b.setAttribute('aria-checked', 'true');
      $('#nota-tamano').hidden = !st.resultado;
    };
    c.appendChild(b);
  });
}

// ───────────────────────────────────────────────────────────── logotipo
function elegirArchivo(f) {
  if (!f) return;
  if (!f.type.startsWith('image/')) return error('Eso no es una imagen.');
  if (st.objeto) URL.revokeObjectURL(st.objeto);
  st.archivo = f;
  st.objeto = URL.createObjectURL(f);

  const img = $('#previa-logo');
  img.src = st.objeto;
  img.onload = () => {
    $('#medidas-logo').textContent =
      `${img.naturalWidth} × ${img.naturalHeight} px · ${(f.size / 1024).toFixed(0)} KB`;
  };
  $('#nombre-logo').textContent = f.name;
  $('#elegido-logo').hidden = false;
  $('#soltar-logo').hidden = true;
  $('#generar').removeAttribute('aria-disabled');
  error('');
}

function quitarLogo() {
  if (st.objeto) URL.revokeObjectURL(st.objeto);
  st.archivo = null;
  st.objeto = null;
  $('#file-logo').value = '';
  $('#elegido-logo').hidden = true;
  $('#soltar-logo').hidden = false;
  $('#generar').setAttribute('aria-disabled', 'true');
}

function conectarSoltar() {
  const zona = $('#soltar-logo');
  $('#file-logo').onchange = (e) => elegirArchivo(e.target.files[0]);
  $('#quitar-logo').onclick = quitarLogo;
  ['dragenter', 'dragover'].forEach((ev) =>
    zona.addEventListener(ev, (e) => { e.preventDefault(); zona.classList.add('encima'); }));
  ['dragleave', 'drop'].forEach((ev) =>
    zona.addEventListener(ev, (e) => { e.preventDefault(); zona.classList.remove('encima'); }));
  zona.addEventListener('drop', (e) =>
    elegirArchivo([...e.dataTransfer.files].find((f) => f.type.startsWith('image/'))));
}

// ───────────────────────────────────────────────────────────── crear
function avance(pct, msg) {
  $('#barra-i').style.width = Math.max(pct, 2) + '%';
  $('#progreso-msg').textContent = msg;
}

function fallo(msg) {
  $('#progreso').hidden = true;
  $('#reposo').hidden = !!st.resultado;
  $('#generar').removeAttribute('aria-disabled');
  error(msg);
}

async function crear() {
  if (!st.archivo) return error('Elige primero un logotipo.');
  error('');

  $('#generar').setAttribute('aria-disabled', 'true');
  $('#acciones').hidden = true;
  $('#ficha').hidden = true;
  $('#resultado').hidden = true;
  $('#reposo').hidden = true;
  $('#progreso').hidden = false;
  $('#nota-tamano').hidden = true;
  avance(2, 'Subiendo el logotipo…');

  const fd = new FormData();
  fd.append('archivo', st.archivo);
  fd.append('cm', String(st.cm));
  fd.append('borde', $('#borde').checked ? '1' : '0');

  try {
    const r = await (await pedir('/api/sticker', { method: 'POST', body: fd })).json();
    if (r.error) throw new Error(r.error);
    st.trabajo = r.id;
    sondear(r.id);
  } catch (e) {
    fallo(e.message);
  }
}

async function sondear(id) {
  try {
    const t = await (await pedir('/api/trabajo-sticker/' + id)).json();
    if (t.estado === 'error') return fallo(t.mensaje);
    avance(t.pct, t.mensaje);
    if (t.estado !== 'listo') return setTimeout(() => sondear(id), 900);
    mostrar(t.resultado);
  } catch (e) {
    fallo('Se perdió la conexión con el servidor.');
  }
}

function mostrar(r) {
  st.resultado = r;
  avance(100, 'Listo');
  setTimeout(() => { $('#progreso').hidden = true; }, 500);

  verFormato(st.formato);
  $('#resultado').hidden = false;
  $('#bajar-png').href = r.png + '?descargar=1';
  $('#bajar-png').setAttribute('download', r.nombre_png);
  $('#bajar-svg').href = r.svg + '?descargar=1';
  $('#bajar-svg').setAttribute('download', r.nombre_svg);
  $('#acciones').hidden = false;
  $('#generar').removeAttribute('aria-disabled');
  document.querySelectorAll('.formatos button')
    .forEach((b) => b.removeAttribute('aria-disabled'));

  const troquel = r.borde_mm
    ? ` <em>(${r.cm_pedido} + ${r.borde_mm} mm de troquel)</em>` : '';
  const muestras = r.paleta
    .map((c) => `<i style="background:${c}" title="${c}"></i>`).join('');
  $('#ficha').innerHTML = `
    <div><dt>PNG</dt><dd>${r.px[0]} × ${r.px[1]} px · ${r.ppp} ppp</dd></div>
    <div><dt>Impreso</dt><dd>${r.cm[0]} × ${r.cm[1]} cm${troquel}</dd></div>
    <div><dt>SVG</dt><dd>${r.curvas} curvas · ${r.svg_kb} KB</dd></div>
    <div><dt>Tintas</dt><dd><span class="muestras">${muestras}</span></dd></div>`;
  $('#ficha').hidden = false;
  $('#previo').scrollIntoView({ behavior: 'smooth', block: 'nearest' });
}

function verFormato(f) {
  st.formato = f;
  document.querySelectorAll('.formatos button').forEach((b) =>
    b.classList.toggle('activo', b.dataset.formato === f));
  if (!st.resultado) return;
  const img = $('#resultado');
  img.src = f === 'svg' ? st.resultado.svg : st.resultado.png;
  img.alt = f === 'svg'
    ? 'Sticker generado, versión vectorial'
    : `Sticker generado, ${st.resultado.px[0]} por ${st.resultado.px[1]} píxeles`;
}

// ───────────────────────────────────────────────────────────── eventos
document.querySelectorAll('.formatos button').forEach((b) => {
  b.onclick = () => { if (st.resultado) verFormato(b.dataset.formato); };
});
$('#generar').onclick = crear;

pintarTamanos();
conectarSoltar();

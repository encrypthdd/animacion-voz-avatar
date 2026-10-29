'use strict';
/* Lo que comparten el estudio de avatares y el creador de stickers. */

const $ = (s) => document.querySelector(s);

const ico = {
  check: '<svg viewBox="0 0 24 24"><path d="M5 13l4 4L19 7"/></svg>',
  equis: '<svg viewBox="0 0 24 24"><path d="M6 6l12 12M18 6L6 18"/></svg>',
  play:  '<svg viewBox="0 0 24 24"><path d="M6 4l14 8-14 8V4Z"/></svg>',
  carga: '<svg viewBox="0 0 24 24"><path d="M12 3a9 9 0 1 0 9 9"/></svg>',
};

async function pedir(url, opciones) {
  const r = await fetch(url, opciones);
  if (r.status === 401) { location.href = '/entrar'; throw new Error('sesión caducada'); }
  if (r.status === 429) {
    const d = await r.json().catch(() => ({}));
    throw new Error(d.error || 'Demasiadas peticiones seguidas. Espera un poco.');
  }
  return r;
}

/* Mensaje de error de la página, en el hueco que cada una reserve. */
function error(msg, sel) {
  const n = $(sel || '#error-global');
  if (!n) return;
  n.hidden = !msg;
  n.textContent = msg || '';
  if (msg) n.scrollIntoView({ behavior: 'smooth', block: 'center' });
}

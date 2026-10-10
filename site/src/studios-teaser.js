/**
 * Essay teaser for the key art studios page: real numbers from data/studios.json,
 * the top three studios with a few of their posters, and a link to studios/.
 */
const t = (...args) => (typeof window.t === 'function' ? window.t(...args) : args[0]);
const num = (n) => Number(n).toLocaleString('en-US');
const esc = (s) =>
  String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);

/** Same slug as studios/studios.js (anchor of each studio entry). */
const slug = (credit) =>
  String(credit || '')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-|-$/g, '');

const poster = (id, path) => (path ? `https://image.tmdb.org/t/p/w185${path}` : `assets/posters/${id}.jpg`);

let data = null;
let names = {};

function render() {
  const root = document.getElementById('studios-teaser');
  if (!root || !data?.studios?.length) return;
  const lang = document.documentElement.lang === 'es' ? 'es' : 'en';
  const name = (s) => names[s.credit]?.name || s.credit;
  const [a, b, c] = data.studios;
  root.querySelector('[data-studios-lede]').textContent = t('studios_lede', {
    v: num(data.n_verified),
    a: name(a),
    an: num(a.n),
    b: name(b),
    bn: num(b.n),
    c: name(c),
    cn: num(c.n),
  });
  root.querySelector('[data-studios-top]').innerHTML = data.studios
    .slice(0, 3)
    .map(
      (s) => `<a class="studios-card" href="studios/?lang=${lang}#${slug(s.credit)}">
        <span class="studios-card-thumbs">${s.posters
          .slice(0, 3)
          .map(([id, , , path]) => `<img src="${esc(poster(id, path))}" alt="" loading="lazy">`)
          .join('')}</span>
        <span class="studios-card-name">${esc(name(s))}</span>
        <span class="studios-card-n">${esc(t('studios_card_n', { n: num(s.n) }))}</span>
      </a>`,
    )
    .join('');
  const cta = root.querySelector('[data-studios-cta]');
  cta.textContent = t('studios_cta', { n: num(data.studios.length) });
  cta.setAttribute('href', `studios/?lang=${lang}`);
}

export async function initStudiosTeaser() {
  if (!document.getElementById('studios-teaser')) return;
  try {
    const [d, copy] = await Promise.all([
      fetch('data/studios.json').then((r) => r.json()),
      fetch('studios/i18n.json').then((r) => (r.ok ? r.json() : {})),
    ]);
    data = d;
    names = copy.studios || {};
  } catch (err) {
    console.warn('[studios-teaser] data failed', err);
    document.getElementById('studios-teaser').hidden = true;
    return;
  }
  render();
  document.addEventListener('aof:lang', render);
}

/**
 * "Who Designs Fear": key art studios ranked by verified horror poster credits.
 * Data: ../data/studios.json (pipeline/export_key_art.py). Copy: ./i18n.json.
 */
const STRIP_MAX = 14;
const STORAGE = 'aof-lang';

const esc = (s) =>
  String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);

function fill(tpl, vars) {
  return String(tpl).replace(/\{(\w+)\}/g, (_, k) => (vars[k] ?? `{${k}}`));
}

/** Same slug as src/autopsy/data.js studioSlug: the autopsy credit links here. */
function slug(credit) {
  return String(credit || '')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-|-$/g, '');
}

function posterSrc(id, path) {
  return path ? `https://image.tmdb.org/t/p/w185${path}` : `../assets/posters/${id}.jpg`;
}

function render(lang, copy, data) {
  const t = (key, vars = {}) => fill(copy.ui[key]?.[lang] ?? copy.ui[key]?.en ?? key, vars);
  // Same grouping as the essay (33,622) in both languages.
  const num = (n) => Number(n).toLocaleString('en-US');
  document.documentElement.lang = lang;
  document.title = t('page_title');
  document.querySelectorAll('[data-i18n]').forEach((el) => {
    el.textContent = t(el.dataset.i18n);
  });
  document.querySelector('[data-i18n-dek]').textContent = t('dek', {
    n: num(data.n_corpus),
    v: num(data.n_verified),
  });
  document.querySelectorAll('[data-lang-btn]').forEach((b) => {
    const on = b.dataset.langBtn === lang;
    b.classList.toggle('is-active', on);
    b.setAttribute('aria-pressed', on ? 'true' : 'false');
  });
  document.querySelectorAll('a[href="../"]').forEach((a) => a.setAttribute('href', `../?lang=${lang}`));

  const top = data.studios[0]?.n || 1;
  document.getElementById('st-list').innerHTML = data.studios
    .map((s, i) => {
      const prof = copy.studios[s.credit];
      const name = prof?.name || s.credit;
      const links = (prof?.links || [])
        .map(([label, url]) => `<a href="${esc(url)}" target="_blank" rel="noopener">${esc(label)}</a>`)
        .join(' · ');
      const strip = s.posters
        .slice(0, STRIP_MAX)
        .map(
          ([id, title, year, path]) =>
            `<a href="../?id=${id}&lang=${lang}" title="${esc(`${title} (${year})`)}" aria-label="${esc(`${t('open_autopsy')}: ${title} (${year})`)}"><img src="${esc(posterSrc(id, path))}" alt="" loading="lazy"></a>`,
        )
        .join('');
      const more = s.posters.length > STRIP_MAX ? `<span class="st-more">${t('more', { n: s.posters.length - STRIP_MAX })}</span>` : '';
      return `<li class="st-item" id="${slug(s.credit)}">
        <div class="st-rank">${i + 1}</div>
        <div>
          <h3 class="st-name">${esc(name)}</h3>
          <p class="st-stat"><b>${t('posters_n', { n: num(s.n) })}</b>${s.impawards_total ? ` · ${t('of_total', { n: num(s.impawards_total) })}` : ''}</p>
          <div class="st-bar" aria-hidden="true"><i style="width:${((100 * s.n) / top).toFixed(1)}%"></i></div>
          ${prof ? `<p class="st-bio">${esc(prof[lang] || prof.en)}</p>` : ''}
          ${links ? `<p class="st-src">${t('sources')}: ${links}</p>` : ''}
          <div class="st-strip">${strip}${more}</div>
        </div>
      </li>`;
    })
    .join('');
}

async function main() {
  const [copy, data] = await Promise.all([
    fetch('i18n.json').then((r) => r.json()),
    fetch('../data/studios.json').then((r) => r.json()),
  ]);
  const q = new URLSearchParams(location.search).get('lang');
  let lang = document.documentElement.lang === 'es' || q === 'es' ? 'es' : 'en';
  render(lang, copy, data);
  if (location.hash) document.getElementById(location.hash.slice(1))?.scrollIntoView();
  document.querySelectorAll('[data-lang-btn]').forEach((b) =>
    b.addEventListener('click', () => {
      lang = b.dataset.langBtn;
      try {
        localStorage.setItem(STORAGE, lang);
      } catch {
        /* private mode */
      }
      render(lang, copy, data);
    }),
  );
}

main();

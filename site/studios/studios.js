/**
 * "Who Designs Fear": key art studios ranked by verified horror poster credits.
 * Data: ../data/studios.json (pipeline/export_key_art.py). Copy: ./i18n.json.
 */
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
        .map(
          ([id, title, year, path]) =>
            `<a href="../?id=${id}&lang=${lang}" title="${esc(`${title} (${year})`)}" aria-label="${esc(`${t('open_autopsy')}: ${title} (${year})`)}"><img src="${esc(posterSrc(id, path))}" alt="" loading="lazy"></a>`,
        )
        .join('');
      return `<li class="st-item" id="${slug(s.credit)}">
        <div class="st-rank">${i + 1}</div>
        <div>
          <h3 class="st-name">${esc(name)}</h3>
          <p class="st-stat"><b>${t('posters_n', { n: num(s.n) })}</b>${s.impawards_total ? ` · ${t('of_total', { n: num(s.impawards_total) })}` : ''}</p>
          <div class="st-bar" aria-hidden="true"><i style="width:${((100 * s.n) / top).toFixed(1)}%"></i></div>
          ${prof ? `<p class="st-bio">${esc(prof[lang] || prof.en)}</p>` : ''}
          ${links ? `<p class="st-src">${t('sources')}: ${links}</p>` : ''}
          <div class="st-strip" id="strip-${i}">${strip}</div>
          <button type="button" class="st-toggle" aria-controls="strip-${i}" aria-expanded="false" data-all="${esc(t('show_all', { n: num(s.posters.length) }))}" data-less="${esc(t('show_less'))}" hidden>${t('show_all', { n: num(s.posters.length) })}</button>
        </div>
      </li>`;
    })
    .join('');
  wireToggles();
}

/**
 * Show the toggle only where the collapsed strip hides posters, and keep the
 * clipped ones out of the tab order / accessibility tree until it opens.
 */
function syncStrip(btn) {
  const strip = document.getElementById(btn.getAttribute('aria-controls'));
  const open = strip.classList.contains('is-open');
  const bottom = strip.getBoundingClientRect().bottom + 1;
  let hiddenCount = 0;
  [...strip.children].forEach((a) => {
    const clipped = !open && a.getBoundingClientRect().top >= bottom - 4;
    hiddenCount += clipped;
    if (clipped) {
      a.setAttribute('tabindex', '-1');
      a.setAttribute('aria-hidden', 'true');
    } else {
      a.removeAttribute('tabindex');
      a.removeAttribute('aria-hidden');
    }
  });
  if (!open) btn.hidden = hiddenCount === 0;
}

function wireToggles() {
  document.querySelectorAll('.st-toggle').forEach((btn) => {
    const strip = document.getElementById(btn.getAttribute('aria-controls'));
    syncStrip(btn);
    btn.addEventListener('click', () => {
      const open = strip.classList.toggle('is-open');
      btn.setAttribute('aria-expanded', open ? 'true' : 'false');
      btn.textContent = open ? btn.dataset.less : btn.dataset.all;
      syncStrip(btn);
      if (!open) strip.closest('.st-item')?.scrollIntoView({ block: 'nearest' });
    });
  });
}

let resizeTimer = null;
window.addEventListener('resize', () => {
  clearTimeout(resizeTimer);
  resizeTimer = setTimeout(() => document.querySelectorAll('.st-toggle').forEach(syncStrip), 150);
});

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

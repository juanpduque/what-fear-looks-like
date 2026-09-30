const STORAGE = 'aof-lang';

function byId(content) {
  const m = {};
  content.forEach((r) => {
    m[r.id] = r;
  });
  return m;
}

function initialLang() {
  const q = new URLSearchParams(location.search).get('lang');
  if (q === 'es' || q === 'en') return q;
  const saved = localStorage.getItem(STORAGE);
  if (saved === 'es' || saved === 'en') return saved;
  const nav = (navigator.language || 'en').toLowerCase();
  return nav.startsWith('es') ? 'es' : 'en';
}

function strip(s) {
  return String(s || '').replace(/<[^>]+>/g, '');
}

function setMeta(sel, content) {
  const el = document.querySelector(sel);
  if (el) el.setAttribute('content', content);
}

function wireDemoLinks(lang) {
  document.querySelectorAll('a[href*="poster-decompose"]').forEach((a) => {
    const u = new URL(a.getAttribute('href'), location.href);
    u.searchParams.set('lang', lang);
    a.setAttribute('href', u.pathname + u.search);
  });
}

/**
 * Install EN/ES i18n — sets window.t / window.AOF_applyLang for legacy inline code.
 */
export function installI18n(content, ui) {
  function t(key, vars) {
    const lang = document.documentElement.lang || 'en';
    const row = ui[key];
    if (!row) return key;
    let s = row[lang] || row.en || key;
    if (vars) {
      Object.keys(vars).forEach((k) => {
        s = String(s).split(`{${k}}`).join(vars[k]);
      });
    }
    return s;
  }

  function applyLang(lang, { persist = true, updateUrl = true } = {}) {
    if (lang !== 'en' && lang !== 'es') lang = 'en';
    document.documentElement.lang = lang;
    if (persist) localStorage.setItem(STORAGE, lang);
    if (updateUrl) {
      const u = new URL(location.href);
      u.searchParams.set('lang', lang);
      history.replaceState(null, '', u);
    }
    const map = byId(content);
    document.querySelectorAll('[data-i18n]').forEach((el) => {
      const row = map[el.getAttribute('data-i18n')];
      if (!row) return;
      el.innerHTML = row[lang] || row.en;
      const aria = row[`aria_${lang}`] || row.aria_en;
      if (aria) el.setAttribute('aria-label', aria);
    });
    document.querySelectorAll('[data-i18n-placeholder]').forEach((el) => {
      const row = map[el.getAttribute('data-i18n-placeholder')];
      if (!row) return;
      el.setAttribute('placeholder', row[lang] || row.en);
    });
    document.querySelectorAll('[data-i18n-aria]').forEach((el) => {
      const key = el.getAttribute('data-i18n-aria');
      const row = map[key] || ui[key];
      if (!row) return;
      const val = row[`aria_${lang}`] || row[lang] || row.en;
      if (val) el.setAttribute('aria-label', val);
    });
    const title = map.meta_title;
    if (title) {
      document.title =
        lang === 'es' ? title.es_plain || strip(title.es) : title.en_plain || strip(title.en);
    }
    const desc = map.meta_description;
    if (desc) setMeta('meta[name="description"]', desc[lang] || desc.en);
    const ogt = map.meta_og_title;
    if (ogt) {
      setMeta('meta[property="og:title"]', ogt[lang] || ogt.en);
      setMeta('meta[name="twitter:title"]', ogt[lang] || ogt.en);
    }
    const ogd = map.meta_og_description;
    if (ogd) {
      setMeta('meta[property="og:description"]', ogd[lang] || ogd.en);
      setMeta('meta[name="twitter:description"]', ogd[lang] || ogd.en);
    }
    document.querySelectorAll('[data-lang-btn]').forEach((btn) => {
      const on = btn.getAttribute('data-lang-btn') === lang;
      btn.setAttribute('aria-pressed', on ? 'true' : 'false');
      btn.classList.toggle('is-active', on);
    });
    document.dispatchEvent(new CustomEvent('aof:lang', { detail: { lang } }));
    wireDemoLinks(lang);
  }

  window.t = t;
  window.AOF_applyLang = applyLang;
  window.AOF_CONTENT = content;
  window.AOF_UI = ui;

  const early = initialLang();
  document.documentElement.lang = early;

  function bindToggle() {
    document.querySelectorAll('[data-lang-btn]').forEach((btn) => {
      btn.addEventListener('click', () => {
        const next = btn.getAttribute('data-lang-btn');
        const y = window.scrollY;
        applyLang(next, { persist: true, updateUrl: true });
        requestAnimationFrame(() => window.scrollTo(0, y));
      });
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => {
      applyLang(early, { persist: true, updateUrl: true });
      bindToggle();
    });
  } else {
    applyLang(early, { persist: true, updateUrl: true });
    bindToggle();
  }

  return { t, applyLang };
}

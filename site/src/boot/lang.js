/** Set html[lang] before i18n.js runs — avoids wrong lang on first paint. */
(function () {
  const q = new URLSearchParams(location.search);
  const langQ = q.get('lang');
  const s = localStorage.getItem('aof-lang');
  const nav = (navigator.language || 'en').toLowerCase();
  const lang =
    langQ === 'es' || langQ === 'en'
      ? langQ
      : s === 'es' || s === 'en'
        ? s
        : nav.indexOf('es') === 0
          ? 'es'
          : 'en';
  document.documentElement.lang = lang;
})();

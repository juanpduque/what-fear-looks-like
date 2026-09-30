/**
 * Essay entry — Vite bundle: i18n, styles, charts, lazy lookup.
 */
import './boot/lang.js';
import './styles/essay.css';
import './i18n/boot.js';
import { initFlickerTitles } from './effects/flicker-titles.js';

initFlickerTitles();

import('./charts/essay.js').then(({ initEssayCharts }) => initEssayCharts());

function nearViewport(el, margin = 480) {
  if (!el) return false;
  const r = el.getBoundingClientRect();
  return r.bottom > -margin && r.top < window.innerHeight + margin;
}

function alignExhibitHash() {
  if (location.hash !== '#exhibit-a') return;
  const section = document.getElementById('exhibit-a');
  if (!section) return;
  const align = () => section.scrollIntoView({ behavior: 'auto', block: 'start' });
  align();
  requestAnimationFrame(align);
}

let lookupApi = null;
let lookupMounting = null;

async function mountLookup() {
  if (lookupApi) return lookupApi;
  if (lookupMounting) return lookupMounting;
  lookupMounting = import('./lookup/index.js')
    .then((mod) => {
      lookupApi = mod.initLookup();
      const q = window.__aofPosterQueue || [];
      window.__aofPosterQueue = [];
      q.forEach((p) => lookupApi.openPoster(p));
      return lookupApi;
    })
    .finally(() => {
      lookupMounting = null;
    });
  return lookupMounting;
}

function mountLookupWhenVisible() {
  const root = document.getElementById('lookup');
  const partI = document.getElementById('part-i');
  const exhibit = document.getElementById('exhibit-a');
  if (!root) return;

  const start = () => mountLookup().catch((err) => console.error('[lookup] mount failed', err));

  const ready =
    nearViewport(root, 640) ||
    nearViewport(partI, 800) ||
    nearViewport(exhibit, 800) ||
    location.hash === '#lookup' ||
    new URLSearchParams(location.search).has('id');
  if (ready) {
    start();
    return;
  }

  const io = new IntersectionObserver(
    ([entry]) => {
      if (entry.isIntersecting) {
        io.disconnect();
        start();
      }
    },
    { rootMargin: '800px 0px', threshold: 0 },
  );
  io.observe(root);
  if (partI) io.observe(partI);
  if (exhibit) io.observe(exhibit);

  window.addEventListener('hashchange', () => {
    if (location.hash === '#lookup' || new URLSearchParams(location.search).has('id')) start();
  });
}

document.addEventListener('aof:lookup-request', () => {
  mountLookup().catch((err) => console.error('[lookup] request failed', err));
});

mountLookupWhenVisible();

window.addEventListener('hashchange', alignExhibitHash);
alignExhibitHash();

import './autopsy.css';
import { posterSrc, tmdbImg, HAS_DATA, pct } from '../shared/posters.js';
import { buildLayersHtml, setActiveLayers, applyArtFilter, BEAT_LAYERS, BEAT_MODES, beatMode, bandBarHtml, bandLegendHtml, topHueFamily } from './layers.js';
import { buildBeats, beatsHtml, modeBlurb } from './beats.js';
import {
  ensureLookup,
  ensureCreatureBoxes,
  ensureWeaponBoxes,
  ensurePose,
  ensureSaliency,
  ensureTitleInk,
  ensureMediumCl,
  ensurePosterAlts,
  ensurePosterAltsRek,
  ensurePosterAltsPose,
  ensurePosterAltsSal,
  ensurePosterAltsComp,
  ensurePosterAltsFaces,
  ensurePosterAltsOwl,
  ensurePosterAltsText,
  posterAltsFor,
  rekAltFor,
  poseAltFor,
  salAltFor,
  compAltFor,
  facesAltFor,
  owlAltFor,
  textAltFor,
  mediumClFor,
  poseFor,
  saliencyFor,
  findPosterById,
  PICK_IDS,
  saliencyMapUrls,
} from './data.js';
import { analyzeFromUrl, paintHeat, paintSaliencyFromUrl } from './colorMaps.js';

const t = (...args) =>
  typeof window.t === 'function' ? window.t(...args) : args[0];

let lkQ = null;
let lkSug = null;
let lkStatus = null;
let section = null;

let lkFocus = -1;
let lkHits = [];
let current = null;
let beats = [];
let beatIndex = 0;
let io = null;
let opening = null;
let savedScroll = 0;
let colorMapsToken = 0;
let modeByBeat = {};
let peekPath = null;

function norm(s) {
  return (s || '')
    .toLowerCase()
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '');
}

function searchPosters(q) {
  if (!HAS_DATA || !q || q.length < 2) return [];
  const n = norm(q);
  const hits = [];
  for (let i = 0; i < window.POSTERS.length; i++) {
    const p = window.POSTERS[i];
    const title = norm(p[3]);
    if (!title.includes(n)) continue;
    const score = (title.startsWith(n) ? 0 : 1) + (title === n ? -1 : 0);
    hits.push({ p, score });
  }
  hits.sort((a, b) => a.score - b.score || a.p[0] - b.p[0]);
  return hits.slice(0, 12).map((h) => h.p);
}

function renderSuggest(list) {
  if (!lkSug) return;
  lkHits = list;
  lkFocus = -1;
  if (!list.length) {
    lkSug.classList.remove('open');
    lkSug.innerHTML = '';
    return;
  }
  lkSug.innerHTML = list
    .map((p, i) => `<li role="option" data-i="${i}"><b>${p[3]}</b><span>${p[0]}</span></li>`)
    .join('');
  lkSug.classList.add('open');
}

function setStatus(msg) {
  if (lkStatus) lkStatus.textContent = msg || '';
}

function els() {
  return {
    root: document.getElementById('au-root'),
    pin: document.getElementById('au-pin'),
    frame: document.getElementById('au-frame'),
    art: document.getElementById('au-art'),
    beats: document.getElementById('au-beats'),
    label: document.getElementById('au-beat-label'),
    bar: document.getElementById('au-bar-fill'),
    prev: document.getElementById('au-prev'),
    next: document.getElementById('au-next'),
    share: document.getElementById('au-share'),
    close: document.getElementById('au-close'),
    alts: document.getElementById('au-alts'),
    peekChip: document.getElementById('au-peek-chip'),
    cmp: document.getElementById('au-alt-cmp'),
  };
}

function setPosterUrl(id) {
  const u = new URL(location.href);
  u.searchParams.set('id', String(id));
  u.hash = 'lookup';
  history.replaceState(null, '', u);
}

function syncPicks(id) {
  document.querySelectorAll('.au-pick').forEach((btn) => {
    btn.classList.toggle('is-on', String(btn.dataset.id) === String(id));
  });
}

function placeAlts() {
  const { frame, alts, pin } = els();
  if (!alts || alts.hidden || !frame) return;
  if (window.matchMedia('(max-width: 720px)').matches) {
    alts.style.left = '';
    alts.style.right = '';
    alts.style.top = '';
    alts.style.bottom = '';
    alts.style.height = '';
    return;
  }
  const host = pin || frame.offsetParent;
  if (!host) return;
  const hr = host.getBoundingClientRect();
  const fr = frame.getBoundingClientRect();
  const gap = 12;
  alts.style.left = `${Math.round(fr.right - hr.left + gap)}px`;
  alts.style.right = 'auto';
  alts.style.top = `${Math.round(fr.top - hr.top)}px`;
  alts.style.bottom = 'auto';
  alts.style.height = `${Math.round(fr.height)}px`;
}

function placeFrame() {
  const { frame } = els();
  if (!frame) return;
  frame.style.left = '50%';
  frame.style.top = '50%';
  frame.style.width = '';
  frame.style.height = '';
  frame.style.transform = 'translate(-50%,-50%)';
  placeAlts();
}

function layersFor(beat) {
  const mode = beatMode(beat.id, modeByBeat[beat.id]);
  let layers = mode ? [...mode.layers] : [...(BEAT_LAYERS[beat.id] || [])];
  return layers;
}

function syncBeatModes() {
  const beat = beats[beatIndex];
  const mode = beat ? beatMode(beat.id, modeByBeat[beat.id]) : null;
  const { frame } = els();
  frame?.classList.toggle('is-heat', Boolean(mode?.heat || beat?.heat));
  document.querySelectorAll('.au-cmodes [data-cmode]').forEach((btn) => {
    const on = Boolean(mode && btn.dataset.cmode === mode.id && beat?.id === btn.closest('.au-beat')?.dataset.beat);
    btn.classList.toggle('is-on', on);
    btn.setAttribute('aria-selected', on ? 'true' : 'false');
  });
}

function setBeatMode(id) {
  const beat = beats[beatIndex];
  if (!beat || !BEAT_MODES[beat.id]?.some((m) => m.id === id)) return;
  modeByBeat[beat.id] = id;
  applyBeat(beatIndex);
}

function applyBeat(i, { scroll } = {}) {
  if (!beats.length) return;
  beatIndex = Math.max(0, Math.min(beats.length - 1, i));
  const beat = beats[beatIndex];
  const { root, art, label, bar, prev, next } = els();
  const ov = document.getElementById('lk-ov');
  const mode = beatMode(beat.id, modeByBeat[beat.id]);
  const layers = layersFor(beat);
  const aView = viewAnalysis();
  setActiveLayers(ov, layers, aView);
  if (viewingAlt()) art?.style.removeProperty('filter');
  else applyArtFilter(art, mode?.filter || null, current?.a);
  syncBeatModes();
  const blurbEl = root?.querySelector(`.au-beat[data-i="${beatIndex}"] [data-mode-blurb]`);
  if (blurbEl) {
    const text = mode ? modeBlurb(beat.id, mode.id, current?.p, aView) : '';
    blurbEl.textContent = text;
    blurbEl.hidden = !text;
  }
  if (label) {
    label.innerHTML = `${beat.kicker}<b>${beat.n} / ${beats.length}</b>`;
  }
  if (bar) bar.style.width = `${((beatIndex + 1) / beats.length) * 100}%`;
  if (prev) prev.disabled = beatIndex === 0;
  if (next) next.disabled = beatIndex === beats.length - 1;
  root?.querySelectorAll('.au-beat').forEach((el, j) => {
    el.classList.toggle('is-on', j === beatIndex);
  });
  if (scroll) {
    const el = root?.querySelector(`.au-beat[data-i="${beatIndex}"]`);
    io?.disconnect();
    el?.scrollIntoView({
      behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth',
      block: 'center',
    });
    window.setTimeout(() => wireBeatObserver(), 480);
  }
}

function wireBeatObserver() {
  io?.disconnect();
  const nodes = document.querySelectorAll('#au-beats .au-beat');
  if (!nodes.length) return;
  io = new IntersectionObserver(
    (entries) => {
      const vis = entries
        .filter((e) => e.isIntersecting)
        .sort((a, b) => b.intersectionRatio - a.intersectionRatio)[0];
      if (!vis) return;
      const i = Number(vis.target.dataset.i);
      if (Number.isFinite(i) && i !== beatIndex) applyBeat(i);
    },
    { root: els().root || null, threshold: [0.35, 0.55, 0.75], rootMargin: '-20% 0px -30% 0px' },
  );
  nodes.forEach((n) => io.observe(n));
}

function renderPicks() {
  const host = document.getElementById('au-picks');
  const lab = document.getElementById('au-picks-label');
  if (!host) return;
  if (lab) lab.textContent = t('autopsy_picks_label');
  host.innerHTML = '';
  PICK_IDS.forEach((id) => {
    const p = findPosterById(id);
    if (!p) return;
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'au-pick';
    btn.dataset.id = String(id);
    btn.setAttribute('aria-label', `${p[3]} (${p[0]})`);
    btn.innerHTML = `<img src="${posterSrc(p, 's')}" alt=""><span>${p[3]}</span>`;
    btn.addEventListener('click', () => openPoster(p));
    host.appendChild(btn);
  });
}

function paintColorOverlays(maps) {
  const ov = document.getElementById('lk-ov');
  if (!ov || !maps) return;
  maps.handles.forEach((h, i) => {
    const el = ov.querySelector(`.lk-handle[data-i="${i}"]`);
    if (!el) return;
    el.style.left = `${(h.x * 100).toFixed(1)}%`;
    el.style.top = `${(h.y * 100).toFixed(1)}%`;
    if (h.hex) el.style.background = h.hex;
  });
  const put = (name, data) => paintHeat(ov.querySelector(`canvas[data-heat="${name}"]`), data);
  put('dark', maps.heatDark);
  put('red', maps.heatRed);
  put('L', maps.heatL);
  put('sat', maps.heatSat);
  put('neg', maps.heatNeg);
  put('cx', maps.edges);
  put('poster', maps.poster);
}

function placeSaliencyPeak(ov, x, y, a) {
  if (!ov || x == null || y == null) return;
  const peak = ov.querySelector('.lk-salpeak');
  const lab = ov.querySelector('[data-sal-lab]');
  if (peak) {
    peak.hidden = false;
    peak.style.left = `${(x * 100).toFixed(1)}%`;
    peak.style.top = `${(y * 100).toFixed(1)}%`;
  }
  if (lab) {
    lab.textContent =
      a?.sal?.m != null ? t('lab_saliency', { v: pct(a.sal.m) }) : t('lab_saliency_map');
  }
}

async function paintSaliencyOverlay(ov, p, a, filePath, token) {
  const canvas = ov?.querySelector('canvas[data-heat="saliency"]');
  if (!canvas) return;
  const urls = saliencyMapUrls(p[7], filePath || null);
  for (const url of urls) {
    const hit = await paintSaliencyFromUrl(canvas, url);
    if (token != null && token !== colorMapsToken) return;
    if (!hit) continue;
    if (!canvas.isConnected) return;
    const x = a?.sal?.x ?? hit.x;
    const y = a?.sal?.y ?? hit.y;
    placeSaliencyPeak(ov, x, y, a);
    return;
  }
  if (token != null && token !== colorMapsToken) return;
  const lab = ov?.querySelector('[data-sal-lab]');
  if (lab) lab.textContent = t('lab_saliency_missing');
}

function measuredPath() {
  return current?.p?.[2] || '';
}

function viewingAlt() {
  return Boolean(peekPath && peekPath !== measuredPath());
}

function rekFlagsFromAlt(rek) {
  if (!rek) return [];
  return ['weapon', 'person', 'animal', 'fire', 'water', 'silhouette'].filter(
    (k) => rek[k] != null && Number(rek[k]) >= 0.5,
  );
}

function viewAnalysis() {
  if (!current) return {};
  if (!viewingAlt()) return current.a;
  const id = current.p[7];
  const path = peekPath;
  const a = {
    ...current.a,
    geomAlt: true,
    fboxes: [],
    cboxes: [],
    wboxes: [],
    faces: 0,
    farea: 0,
    nova_faces: null,
    nova_creature: null,
    nova_typo: null,
    nova_ocr: null,
    nova_title: null,
  };
  const faces = facesAltFor(id, path);
  if (faces) {
    a.faces = faces.n;
    a.farea = faces.area;
    a.fboxes = faces.boxes;
  }
  const owl = owlAltFor(id, path);
  if (owl) {
    a.cboxes = owl.c;
    a.wboxes = owl.w;
  }
  const pose = poseAltFor(id, path);
  a.pose = pose || { n: 0 };
  a.sal = salAltFor(id, path);
  const title = textAltFor(id, path);
  a.comp = {
    ...(compAltFor(id, path) || {}),
    tx: title ? title[0] : null,
    tt: title ? title[1] : null,
    tw: title ? title[2] : null,
    th: title ? title[3] : null,
  };
  const rekAlt = rekAltFor(id, path);
  a.rek = {
    bright: rekAlt?.bright,
    contrast: rekAlt?.contrast,
    flags: rekFlagsFromAlt(rekAlt),
    faces: null,
    fboxes: [],
  };
  return a;
}

function sheetSrc() {
  if (viewingAlt()) return tmdbImg(peekPath, 'm');
  return current ? posterSrc(current.p, 'm') : '';
}

function refreshOverlays() {
  const { frame, beats: beatHost } = els();
  if (!frame || !current) return;
  const keep = beatIndex;
  const aView = viewAnalysis();
  frame.querySelector('.lk-ov')?.remove();
  frame.insertAdjacentHTML(
    'beforeend',
    buildLayersHtml(current.p, aView, { sheetSrc: sheetSrc() }),
  );
  beats = buildBeats(current.p, aView);
  if (beatHost) beatHost.innerHTML = beatsHtml(beats);
  beatIndex = Math.max(0, Math.min(keep, beats.length - 1));
  wireBeatObserver();
}

function scheduleColorMaps(p, a) {
  const token = ++colorMapsToken;
  const alt = viewingAlt();
  const src = alt ? tmdbImg(peekPath, 'm') : posterSrc(p, 'm');
  paintSaliencyOverlay(document.getElementById('lk-ov'), p, a, alt ? peekPath : null, token).catch(
    (err) => console.warn('[autopsy] saliency map failed', err),
  );
  analyzeFromUrl(src, alt ? [] : a.pal || [])
    .then((maps) => {
      if (token !== colorMapsToken || current?.p[7] !== p[7]) return;
      if (alt !== viewingAlt()) return;
      paintColorOverlays(maps);
      if (viewingAlt()) applyAltPixelLabs(maps);
    })
    .catch((err) => console.warn('[autopsy] color maps failed', err));
}

function applyAltPixelLabs(maps) {
  const ov = document.getElementById('lk-ov');
  if (!ov || !maps) return;
  const pal = maps.palHex || [];
  ov.querySelectorAll('.lk-palswatch span').forEach((el, i) => {
    const hex = pal[i];
    if (!hex) return;
    const sw = el.querySelector('i');
    if (sw) sw.style.background = hex;
    el.title = hex;
  });
  const top = topHueFamily({ bands: maps.bands });
  const bandsHost = ov.querySelector('.lk-bandsov');
  const legendHost = ov.querySelector('.lk-bandleg');
  if (bandsHost) bandsHost.innerHTML = bandBarHtml(maps.bands);
  if (legendHost) legendHost.outerHTML = bandLegendHtml(maps.bands);
  const setLab = (layer, text) => {
    const el = ov.querySelector(`[data-layer="${layer}"] .lk-lab`);
    if (el) el.textContent = text;
  };
  setLab('heat-dark', t('lab_heat_dark', { n: Math.round((maps.darkShare || 0) * 100) }));
  setLab('heat-red', t('lab_heat_red', { v: pct(maps.redShare) }));
  setLab('heat-L', t('lab_heat_L', { L: Math.round(maps.meanL || 0) }));
  setLab('sat', t('lab_saturation', { v: pct(maps.meanSat) }));
  setLab('palette', t('lab_palette_swatches', { n: pal.length }));
  const hueLab = ov.querySelector('[data-layer="bands"] .lk-lab');
  if (hueLab) hueLab.textContent = t('lab_hue_families_top', { name: top.name, v: pct(top.v) });
}

function syncAltButtons() {
  const { alts } = els();
  if (!alts) return;
  alts.querySelectorAll('.au-alt').forEach((btn) => {
    const path = btn.dataset.path || '';
    const measured = btn.classList.contains('is-measured');
    const on = peekPath ? path === peekPath : measured;
    btn.classList.toggle('is-on', on);
    btn.classList.toggle('is-alt', Boolean(peekPath) && path === peekPath);
    btn.classList.toggle('is-peek', Boolean(peekPath) && path === peekPath);
    btn.setAttribute('aria-pressed', on ? 'true' : 'false');
  });
}

function hideAltCmp() {
  const { cmp } = els();
  if (!cmp) return;
  cmp.hidden = true;
  cmp.innerHTML = '';
}

function unpeek() {
  peekPath = null;
  hideAltCmp();
  const { art, frame, peekChip } = els();
  frame?.classList.remove('is-peek', 'is-alt');
  if (peekChip) {
    peekChip.hidden = true;
    peekChip.textContent = '';
  }
  if (current && art) {
    art.src = posterSrc(current.p, 'm');
    const beat = beats[beatIndex];
    const mode = beat ? beatMode(beat.id, modeByBeat[beat.id]) : null;
    applyArtFilter(art, mode?.filter || null, current.a);
    refreshOverlays();
    scheduleColorMaps(current.p, current.a);
  }
  applyBeat(beatIndex);
  syncAltButtons();
}

function peekAlt(path) {
  const measured = current?.p?.[2];
  if (!path || path === measured) {
    unpeek();
    return;
  }
  if (path === peekPath) {
    unpeek();
    return;
  }
  peekPath = path;
  hideAltCmp();
  const { art, frame, peekChip } = els();
  if (art) {
    art.src = tmdbImg(path, 'm');
    art.style.removeProperty('filter');
  }
  frame?.classList.add('is-alt');
  frame?.classList.remove('is-peek');
  if (peekChip) {
    peekChip.hidden = true;
    peekChip.textContent = '';
  }
  if (current) {
    refreshOverlays();
    scheduleColorMaps(current.p, viewAnalysis());
  }
  applyBeat(beatIndex);
  syncAltButtons();
}

function renderAlts(p) {
  const { alts } = els();
  if (!alts) return;
  peekPath = null;
  const rows = posterAltsFor(p[7]);
  alts.setAttribute('aria-label', t('autopsy_alts_aria'));
  if (rows.length < 2) {
    alts.hidden = true;
    alts.innerHTML = '';
    els().frame?.classList.remove('is-peek', 'is-alt');
    hideAltCmp();
    const chip = els().peekChip;
    if (chip) {
      chip.hidden = true;
      chip.textContent = '';
    }
    return;
  }
  const measuredLabel = t('autopsy_alts_measured');
  alts.hidden = false;
  alts.innerHTML = `<p class="au-alts-kicker">${t('autopsy_alts_kicker')}</p>${rows
    .map((row) => {
      const tag = row.measured ? measuredLabel : (row.iso || '').toUpperCase();
      const hasRek = Boolean(rekAltFor(p[7], row.path));
      const cls = `${row.measured ? 'au-alt is-measured is-on' : 'au-alt'}${hasRek ? ' has-rek' : ''}`;
      const label = row.measured ? measuredLabel : (tag || t('autopsy_alts_kicker'));
      return `<button type="button" class="${cls}" data-path="${row.path}" aria-pressed="${row.measured ? 'true' : 'false'}" aria-label="${label}" title="${label}"><img src="${tmdbImg(row.path, 's')}" alt=""><span class="au-alt-tag">${tag || '·'}</span></button>`;
    })
    .join('')}`;
  placeAlts();
}

function renderStage(p, a) {
  const { root, frame, art, beats: beatHost } = els();
  if (!root || !frame || !art || !beatHost) return;
  root.hidden = false;
  section?.classList.add('au-live');
  peekPath = null;
  hideAltCmp();
  art.src = posterSrc(p, 'm');
  art.alt = `${p[3]} (${p[0]})`;
  frame.classList.remove('is-peek', 'is-alt');
  const chip = els().peekChip;
  if (chip) {
    chip.hidden = true;
    chip.textContent = '';
  }
  frame.querySelector('.lk-ov')?.remove();
  frame.insertAdjacentHTML('beforeend', buildLayersHtml(p, a));
  beats = buildBeats(p, a);
  beatHost.innerHTML = beatsHtml(beats);
  current = { p, a };
  beatIndex = 0;
  modeByBeat = {};
  renderAlts(p);
  applyBeat(0);
  wireBeatObserver();
  syncPicks(p[7]);
  if (lkQ) lkQ.value = p[3];
  scheduleColorMaps(p, a);
}

function enterOverlay() {
  const { root, close } = els();
  if (!root) return;
  if (!document.body.classList.contains('au-open')) {
    savedScroll = window.scrollY;
  }
  root.hidden = false;
  root.classList.add('au-overlay');
  document.body.classList.add('au-open');
  section?.classList.add('au-live');
  root.scrollTop = 0;
  close?.focus();
}

export function closePoster() {
  unpeek();
  const { root } = els();
  io?.disconnect();
  if (root) {
    root.hidden = true;
    root.classList.remove('au-overlay');
  }
  document.body.classList.remove('au-open');
  section?.classList.remove('au-live');
  const y = savedScroll;
  requestAnimationFrame(() => window.scrollTo(0, y));
}

function overlayIsOpen() {
  return document.body.classList.contains('au-open');
}

export async function openPoster(p) {
  if (!p) return;
  const id = p[7];
  opening = id;
  if (lkSug) lkSug.classList.remove('open');
  setStatus(t('lookup_loading_short'));
  enterOverlay();
  try {
    const [L] = await Promise.all([
      ensureLookup(),
      ensureCreatureBoxes().catch(() => ({})),
      ensureWeaponBoxes().catch(() => ({})),
      ensurePose().catch(() => ({})),
      ensureSaliency(),
      ensureTitleInk(),
      ensureMediumCl(),
      ensurePosterAlts(),
      ensurePosterAltsRek(),
      ensurePosterAltsPose(),
      ensurePosterAltsSal(),
      ensurePosterAltsComp(),
      ensurePosterAltsFaces(),
      ensurePosterAltsOwl(),
      ensurePosterAltsText(),
    ]);
    if (opening !== id) return;
    const a = { ...(L[String(id)] || {}) };
    const pose = poseFor(id);
    if (pose) a.pose = pose;
    const sal = saliencyFor(id);
    if (sal) a.sal = sal;
    const mediumCl = mediumClFor(id);
    if (mediumCl) a.medium_cl = mediumCl;
    enterOverlay();
    renderStage(p, a);
    placeFrame();
    setPosterUrl(id);
    setStatus('');
    requestAnimationFrame(() => {
      if (current?.p[7] === id) els().root && (els().root.scrollTop = 0);
    });
  } catch (err) {
    console.error('[autopsy] open failed', err);
    setStatus(t('lookup_load_error'));
  }
}

function openFromQuery() {
  const id = new URLSearchParams(location.search).get('id');
  if (!id) return;
  const p = findPosterById(id);
  if (p) openPoster(p);
}

function wireSearch() {
  if (!lkQ) return;
  lkQ.addEventListener('input', () => {
    ensureLookup();
    ensureCreatureBoxes();
    ensureWeaponBoxes().catch(() => {});
    ensurePose().catch(() => {});
    ensureSaliency();
    ensureTitleInk();
    ensureMediumCl();
    ensurePosterAlts();
    ensurePosterAltsRek();
    ensurePosterAltsPose();
    ensurePosterAltsSal();
    ensurePosterAltsComp();
    ensurePosterAltsFaces();
    ensurePosterAltsOwl();
    ensurePosterAltsText();
    renderSuggest(searchPosters(lkQ.value.trim()));
  });
  lkQ.addEventListener('keydown', (ev) => {
    if (!lkSug?.classList.contains('open')) return;
    if (ev.key === 'ArrowDown') {
      ev.preventDefault();
      lkFocus = Math.min(lkFocus + 1, lkHits.length - 1);
    } else if (ev.key === 'ArrowUp') {
      ev.preventDefault();
      lkFocus = Math.max(lkFocus - 1, 0);
    } else if (ev.key === 'Enter') {
      ev.preventDefault();
      if (lkFocus >= 0) openPoster(lkHits[lkFocus]);
      else if (lkHits[0]) openPoster(lkHits[0]);
      return;
    } else if (ev.key === 'Escape') {
      lkSug.classList.remove('open');
      return;
    } else {
      return;
    }
    [...lkSug.children].forEach((li, i) => li.classList.toggle('on', i === lkFocus));
  });
  lkSug?.addEventListener('click', (ev) => {
    const li = ev.target.closest('li');
    if (!li) return;
    openPoster(lkHits[+li.dataset.i]);
  });
  document.addEventListener('click', (ev) => {
    if (!ev.target.closest('.lk-search')) lkSug?.classList.remove('open');
  });
}

function wireNav() {
  const { prev, next, share, close } = els();
  prev?.addEventListener('click', () => applyBeat(beatIndex - 1, { scroll: true }));
  next?.addEventListener('click', () => applyBeat(beatIndex + 1, { scroll: true }));
  close?.addEventListener('click', () => closePoster());
  document.getElementById('au-alts')?.addEventListener('click', (ev) => {
    const btn = ev.target.closest('.au-alt');
    if (!btn) return;
    peekAlt(btn.dataset.path);
  });
  document.getElementById('au-beats')?.addEventListener('click', (ev) => {
    const btn = ev.target.closest('[data-cmode]');
    if (!btn) return;
    setBeatMode(btn.dataset.cmode);
  });
  share?.addEventListener('click', async () => {
    const url = location.href;
    try {
      await navigator.clipboard.writeText(url);
      share.textContent = t('autopsy_shared');
      setTimeout(() => {
        share.textContent = t('autopsy_share');
      }, 1600);
    } catch {
      window.prompt(t('autopsy_share'), url);
    }
  });
  document.addEventListener('keydown', (ev) => {
    const tag = ev.target?.tagName;
    if (tag === 'INPUT' || tag === 'TEXTAREA' || ev.target?.isContentEditable) return;
    if (ev.key === 'Escape' && overlayIsOpen()) {
      ev.preventDefault();
      if (peekPath) unpeek();
      else closePoster();
      return;
    }
    if (!current || !section) return;
    if (!overlayIsOpen()) {
      const r = section.getBoundingClientRect();
      if (r.bottom < 80 || r.top > window.innerHeight - 80) return;
    }
    if (ev.key === 'ArrowRight') {
      ev.preventDefault();
      applyBeat(beatIndex + 1, { scroll: true });
    } else if (ev.key === 'ArrowLeft') {
      ev.preventDefault();
      applyBeat(beatIndex - 1, { scroll: true });
    }
  });
}

function relabel() {
  renderPicks();
  const { share, close } = els();
  if (share) share.textContent = t('autopsy_share');
  if (close) {
    close.textContent = t('autopsy_close');
    close.setAttribute('aria-label', t('autopsy_close'));
  }
  const prev = document.getElementById('au-prev');
  const next = document.getElementById('au-next');
  if (prev) prev.textContent = t('autopsy_prev');
  if (next) next.textContent = t('autopsy_next');
  if (current) {
    const keep = beatIndex;
    renderStage(current.p, current.a);
    applyBeat(keep);
  }
}

let wired = false;

export function initLookup() {
  section = document.getElementById('lookup');
  lkQ = document.getElementById('lk-q');
  lkSug = document.getElementById('lk-suggest');
  lkStatus = document.getElementById('lk-status');
  if (!section) return { openPoster: () => {}, closePoster: () => {} };
  if (!wired) {
    wireSearch();
    wireNav();
    renderPicks();
    relabel();
    document.addEventListener('aof:lang', relabel);
    window.addEventListener('resize', placeFrame);
    wired = true;
    window.openPoster = openPoster;
    ensureLookup();
    ensureCreatureBoxes().catch(() => {});
    ensureWeaponBoxes().catch(() => {});
    ensurePose().catch(() => {});
    ensureSaliency();
    ensureTitleInk();
    ensureMediumCl();
    ensurePosterAlts();
    ensurePosterAltsRek();
    ensurePosterAltsPose();
    ensurePosterAltsSal();
    ensurePosterAltsComp();
    ensurePosterAltsFaces();
    ensurePosterAltsOwl();
    ensurePosterAltsText();
    const queued = window.__aofPosterQueue || [];
    window.__aofPosterQueue = [];
    queued.forEach((p) => openPoster(p));
    if (!queued.length) openFromQuery();
  }
  return { openPoster, closePoster };
}

/**
 * VHS Decompose — Halloween (948) · teachable cloud pass
 * Cover = poster.jpg (flat corpus art). Never map VHS box photos as albedo.
 * Beats: Hero → OCR → Faces → Palette → Symmetry → Diagonals → Blood → Knife → Archive.
 * Archive holds the closed sleeve (no lid open, no VCR insert).
 */
import * as THREE from './three.module.js';
import { GLTFLoader } from './GLTFLoader.js';

const DEMO_LANG = (() => {
  const q = new URLSearchParams(location.search).get('lang');
  if (q === 'es' || q === 'en') return q;
  const htmlLang = document.documentElement.lang;
  if (htmlLang === 'es' || htmlLang === 'en') return htmlLang;
  const saved = localStorage.getItem('aof-lang');
  if (saved === 'es' || saved === 'en') return saved;
  return (navigator.language || 'en').toLowerCase().startsWith('es') ? 'es' : 'en';
})();

const IS_EMBED = new URLSearchParams(location.search).get('embed') === '1';
const ESSAY_ACT = !!document.getElementById('vhs-act-root');
const ACT_ROOT = ESSAY_ACT ? document.getElementById('exhibit-a') : document.documentElement;
const BASE = ESSAY_ACT ? './demos/poster-decompose/' : './';

function setRootClass(cls, on) {
  ACT_ROOT.classList.toggle(cls, !!on);
}

function viewportSize() {
  if (ESSAY_ACT) {
    const pin = document.querySelector('.vhs-act-pin');
    if (pin) {
      const w = pin.clientWidth;
      const h = pin.clientHeight;
      // Avoid 0×0 WebGL during sticky/layout races
      if (w > 1 && h > 1) return { w, h };
    }
  }
  return {
    w: Math.max(1, window.innerWidth),
    h: Math.max(1, window.innerHeight),
  };
}

function getScrollProgress() {
  if (ESSAY_ACT) {
    const section = document.getElementById('exhibit-a');
    const root = document.getElementById('vhs-act-root');
    const track = el.track;
    const pin = document.querySelector('.vhs-act-pin');
    if (!section || !root || !track || !pin) {
      preludeProgress = 0;
      return 0;
    }
    const pinH = pin.offsetHeight;
    const sectionTop = section.getBoundingClientRect().top + window.scrollY;
    const rootTop = root.getBoundingClientRect().top + window.scrollY;
    const preludePx = Math.max(1, rootTop - sectionTop);
    const scrolled = window.scrollY - sectionTop;

    // Prologue: prose scrolls over the pinned shelf (p stays 0)
    if (window.scrollY < rootTop) {
      preludeProgress = clamp(scrolled / preludePx, 0, 1);
      return 0;
    }
    preludeProgress = 1;

    const trackScrollable = Math.max(1, track.offsetHeight - pinH);
    const actScrolled = window.scrollY - rootTop;
    return clamp(actScrolled / trackScrollable, 0, 1);
  }
  const max = Math.max(1, document.documentElement.scrollHeight - window.innerHeight);
  return clamp(window.scrollY / max, 0, 1);
}

let actInView = true;
let preludeProgress = 0;

function postToParent(type, extra = {}) {
  if (!IS_EMBED || window.parent === window) return;
  window.parent.postMessage({ source: 'poster-decompose', type, ...extra }, location.origin);
}

let demoI18n = null;

function tDemo(path) {
  if (!demoI18n) return '';
  const parts = path.split('.');
  let node = demoI18n;
  for (const p of parts) {
    node = node && node[p];
  }
  if (!node) return '';
  return node[DEMO_LANG] || node.en || '';
}

function localizeMetrics(data, i18n) {
  if (!i18n) return data;
  const out = JSON.parse(JSON.stringify(data));
  out.acts = (out.acts || []).map((act) => {
    const map = i18n.acts || {};
    const row = map[act.id];
    if (row) act.label = row[DEMO_LANG] || row.en || act.label;
    return act;
  });
  out.beats = (out.beats || []).map((beat) => {
    const loc = (i18n.beats || {})[beat.id];
    if (!loc) return beat;
    if (loc.kicker) beat.kicker = loc.kicker[DEMO_LANG] || loc.kicker.en;
    if (loc.title) beat.title = loc.title[DEMO_LANG] || loc.title.en;
    if (loc.body) beat.body = loc.body[DEMO_LANG] || loc.body.en;
    if (loc.cue) beat.cue = loc.cue[DEMO_LANG] || loc.cue.en;
    if (beat.overlay && loc.overlay_label) {
      beat.overlay.label = loc.overlay_label[DEMO_LANG] || loc.overlay_label.en;
    }
    if (beat.overlay && loc.overlay_cue) {
      beat.overlay.cue = loc.overlay_cue[DEMO_LANG] || loc.overlay_cue.en;
    }
    if (beat.overlay?.type === 'palette' && loc.roles && beat.overlay.samples) {
      beat.overlay.samples = beat.overlay.samples.map((s) => {
        const role = loc.roles[s.role];
        if (role) return { ...s, role: role[DEMO_LANG] || role.en || s.role };
        return s;
      });
    }
    return beat;
  });
  return out;
}

function applyDemoChrome() {
  if (!demoI18n) return;
  if (!ESSAY_ACT) {
    document.documentElement.lang = DEMO_LANG;
  }
  if (IS_EMBED) document.documentElement.classList.add('demo-embed');
  if (ESSAY_ACT) ACT_ROOT.classList.add('essay-mode');
  const meta = demoI18n.meta || {};
  if (!ESSAY_ACT && meta.title) document.title = meta.title[DEMO_LANG] || meta.title.en;
  const desc = document.querySelector('meta[name="description"]');
  if (!ESSAY_ACT && desc && meta.description) {
    desc.setAttribute('content', meta.description[DEMO_LANG] || meta.description.en);
  }
  const brandLine1 = document.querySelector('[data-i18n="brand_line1"]');
  const brandLine2 = document.querySelector('[data-i18n="brand_line2"]');
  if (brandLine1) brandLine1.textContent = tDemo('chrome.brand_line1');
  if (brandLine2) brandLine2.textContent = tDemo('chrome.brand_line2');
  const back = document.querySelector('[data-i18n="back_essay"]');
  if (back) back.textContent = tDemo('chrome.back_essay');
  const loaderP = el.loader && el.loader.querySelector('p');
  if (loaderP) loaderP.innerHTML = `<span class="pulse">●</span> ${tDemo('chrome.loader')}`;
  wireEssayLinks();
}

function wireEssayLinks() {
  if (IS_EMBED) {
    document.querySelectorAll('[data-demo-essay-link]').forEach((a) => {
      if (a.dataset.embedWired) return;
      a.dataset.embedWired = '1';
      a.href = '#';
      a.addEventListener('click', (e) => {
        e.preventDefault();
        postToParent('demo:scroll-exhibit');
      });
    });
    document.querySelectorAll('[data-demo-essay-continue]').forEach((a) => {
      if (a.dataset.embedWired) return;
      a.dataset.embedWired = '1';
      const label = tDemo('chrome.essay_continue');
      if (label) a.textContent = label;
      a.setAttribute('aria-label', label || 'Continue to full essay');
      a.href = '#part-i';
      a.addEventListener('click', (e) => {
        e.preventDefault();
        postToParent('demo:continue-essay');
      });
    });
    return;
  }

  if (ESSAY_ACT) {
    document.querySelectorAll('[data-demo-essay-continue]').forEach((a) => {
      if (a.dataset.embedWired) return;
      a.dataset.embedWired = '1';
      const label = tDemo('chrome.essay_continue');
      if (label) a.textContent = label;
      a.setAttribute('aria-label', label || 'Continue to full essay');
      a.href = '#part-i';
      a.addEventListener('click', (e) => {
        e.preventDefault();
        const target = document.getElementById('part-i');
        if (target) {
          target.scrollIntoView({ behavior: reducedMotion ? 'auto' : 'smooth', block: 'start' });
        }
        const u = new URL(location.href);
        u.hash = 'part-i';
        history.replaceState(null, '', u.pathname + u.search + u.hash);
      });
    });
    return;
  }

  const backHref = `../../index.html?lang=${DEMO_LANG}#exhibit-a`;
  const continueHref = `../../index.html?lang=${DEMO_LANG}#part-i`;
  document.querySelectorAll('[data-demo-essay-link]').forEach((a) => {
    a.href = backHref;
  });
  document.querySelectorAll('[data-demo-essay-continue]').forEach((a) => {
    a.href = continueHref;
    const label = tDemo('chrome.essay_continue');
    if (label) a.textContent = label;
    a.setAttribute('aria-label', label || 'Continue to full essay');
  });
}

const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
const isMobile =
  window.matchMedia('(max-width: 720px)').matches ||
  (navigator.maxTouchPoints > 0 && window.innerWidth < 900);

/** Box geometry — outer shell hugs the cassette; poster is cropped onto the lid. */
let BOX_H = 3.32;
let BEZEL = 0.034;
let COVER_H = BOX_H - BEZEL * 2;
let COVER_W = COVER_H * (2 / 3);
let BOX_W = COVER_W + BEZEL * 2;
const BOX_D = 0.54;
const WALL = 0.052;
/** Poster UV → lid UV after object-fit cover crop. */
let coverUvCrop = { repeatX: 1, repeatY: 1, offsetX: 0, offsetY: 0 };
/** Normalized crop of poster.jpg (strips letterbox + inner keyline). */
let posterTrim = { x: 0, y: 0, w: 1, h: 1 };

function spineWidth() {
  return WALL * 1.2;
}

/** Inner well of the clamshell (accounts for thicker spine on the left). */
function cavity() {
  const spineW = spineWidth();
  const left = -BOX_W / 2 + spineW;
  const right = BOX_W / 2 - WALL;
  const top = BOX_H / 2 - WALL;
  const bottom = -BOX_H / 2 + WALL;
  return {
    left,
    right,
    top,
    bottom,
    w: right - left,
    h: top - bottom,
    cx: (left + right) / 2,
    cy: (top + bottom) / 2,
  };
}

const el = {
  stage: document.getElementById('stage'),
  track: document.getElementById('scroll-track'),
  bar: document.getElementById('bar'),
  beatLabel: document.getElementById('beat-label'),
  actLabel: document.getElementById('act-label'),
  tapeStamp: document.getElementById('tape-stamp'),
  loader: document.getElementById('loader'),
  overlays: document.getElementById('overlays'),
  counter: document.getElementById('metric-counter'),
  essayOutro: document.getElementById('essay-outro'),
};

let metricsData = null;
let beatEls = [];
let activeBeat = -1;
let posterAspect = 2 / 3;

let renderer, scene, camera, clock;
let vhsGroup, baseShell, lidPivot, lidContent, interiorGroup, layerGroup;
let layers = {};
let dust;
let contactShadow;
let floor;
let keyLight, rimLight, rimCoolLight;
let scrollProgress = 0;
let targetProgress = 0;
let plasticNoiseMap = null;
let coverAnchor = null;
let overlayNodes = {};
/** Cold-open videoclub: InstancedMesh aisle → pull-out into hero clamshell. */
let storeGroup = null;
let storeSpines = null;
let storeDust = null;
let storeFluoroLight = null;
let storeBayLight = null;
let storeSoftLight = null;
let storeFillLight = null;
let storeStrip = null;
let storeDimPlane = null;
let storeSlotRecess = null;
let storeGodRays = null;
let storeSlotWorld = new THREE.Vector3();
let storeHeroPos = new THREE.Vector3();
let storeHeroRot = new THREE.Euler();
let storeHeroScale = 1;
let frontFillLight = null;
let interiorFillLight = null;
let baseFogDensity = 0.012;
/** Vintage VCR — enters at archive, receives the cassette. */
let playerGroup = null;
const _slotWorld = new THREE.Vector3();
const _slotQuat = new THREE.Quaternion();
const _flightPos = new THREE.Vector3();
const _flightQuat = new THREE.Quaternion();
const _tmpV = new THREE.Vector3();

function lerp(a, b, t) {
  return a + (b - a) * t;
}
function clamp(v, a, b) {
  return Math.max(a, Math.min(b, v));
}
function smoothstep(e0, e1, x) {
  const t = clamp((x - e0) / (e1 - e0), 0, 1);
  return t * t * (3 - 2 * t);
}
function remap(p, a, b) {
  return smoothstep(a, b, p);
}

function setPosterAspect(aspect) {
  posterAspect = aspect;
}

/** Size the clamshell from the tape; poster is fitted onto the lid (contain + black). */
function setBoxFromTapeFootprint(tapeSize) {
  BOX_H = 3.32;
  BEZEL = 0.034;
  const innerH = BOX_H - WALL * 2;
  const s = innerH / Math.max(tapeSize.y, 1e-6);
  const innerW = tapeSize.x * s * 1.004;
  BOX_W = innerW + spineWidth() + WALL;
  COVER_H = BOX_H - BEZEL * 2;
  COVER_W = BOX_W - BEZEL * 2;
  const imageAspect = posterAspect;
  const coverAspect = COVER_W / Math.max(COVER_H, 1e-6);
  if (imageAspect > coverAspect) {
    const fracH = coverAspect / imageAspect;
    coverUvCrop = { repeatX: 1, repeatY: fracH, offsetX: 0, offsetY: (1 - fracH) / 2 };
  } else {
    const fracW = imageAspect / coverAspect;
    coverUvCrop = { repeatX: fracW, repeatY: 1, offsetX: (1 - fracW) / 2, offsetY: 0 };
  }
}

function coverCanvasSize(maxEdge) {
  const aspect = COVER_W / Math.max(COVER_H, 1e-6);
  const h = maxEdge;
  return { w: Math.max(1, Math.round(h * aspect)), h };
}

/** Fit the full poster into the lid (contain). Leftover area stays black. */
function drawImageCoverFit(ctx, src, dw, dh) {
  ctx.fillStyle = '#000000';
  ctx.fillRect(0, 0, dw, dh);
  const srcW = src.naturalWidth || src.width;
  const srcH = src.naturalHeight || src.height;
  const cropX = posterTrim.x * srcW;
  const cropY = posterTrim.y * srcH;
  const cropW = Math.max(1, posterTrim.w * srcW);
  const cropH = Math.max(1, posterTrim.h * srcH);
  const scale = Math.min(dw / cropW, dh / cropH);
  const dwImg = cropW * scale;
  const dhImg = cropH * scale;
  const dx = (dw - dwImg) / 2;
  const dy = (dh - dhImg) / 2;
  ctx.drawImage(src, cropX, cropY, cropW, cropH, dx, dy, dwImg, dhImg);
}

/** Crop just inside the printed copper keyline so that frame is not on the lid. */
function detectPosterTrim(img) {
  const srcW = img.naturalWidth || img.width;
  const srcH = img.naturalHeight || img.height;
  const maxEdge = 480;
  const sc = Math.min(1, maxEdge / Math.max(srcW, srcH));
  const w = Math.max(16, Math.round(srcW * sc));
  const h = Math.max(16, Math.round(srcH * sc));
  const c = document.createElement('canvas');
  c.width = w;
  c.height = h;
  const ctx = c.getContext('2d', { willReadFrequently: true });
  ctx.drawImage(img, 0, 0, w, h);
  const data = ctx.getImageData(0, 0, w, h).data;
  const lumAt = (x, y) => {
    const i = (y * w + x) * 4;
    return 0.2126 * data[i] + 0.7152 * data[i + 1] + 0.0722 * data[i + 2];
  };
  const isCopper = (x, y) => {
    const i = (y * w + x) * 4;
    const r = data[i];
    const g = data[i + 1];
    const b = data[i + 2];
    return r > 52 && r > g + 6 && r > b + 12 && r < 210 && g < 150 && b < 110;
  };
  const rowEnergy = (y) => {
    let lit = 0;
    for (let x = 0; x < w; x++) if (lumAt(x, y) > 16) lit++;
    return lit / w;
  };
  const colEnergy = (x) => {
    let lit = 0;
    for (let y = 0; y < h; y++) if (lumAt(x, y) > 16) lit++;
    return lit / h;
  };
  const rowCopper = (y, x0, x1) => {
    let n = 0;
    let o = 0;
    for (let x = x0; x <= x1; x++) {
      n++;
      if (isCopper(x, y)) o++;
    }
    return n ? o / n : 0;
  };
  const colCopper = (x, y0, y1) => {
    let n = 0;
    let o = 0;
    for (let y = y0; y <= y1; y++) {
      n++;
      if (isCopper(x, y)) o++;
    }
    return n ? o / n : 0;
  };

  const dark = 0.01;
  let top = 0;
  let bottom = h - 1;
  let left = 0;
  let right = w - 1;
  while (top < bottom && rowEnergy(top) < dark) top++;
  while (bottom > top && rowEnergy(bottom) < dark) bottom--;
  while (left < right && colEnergy(left) < dark) left++;
  while (right > left && colEnergy(right) < dark) right--;

  const maxKey = Math.round(Math.min(w, h) * 0.04);
  let t = top;
  let run = 0;
  while (t < bottom && run < maxKey && rowCopper(t, left, right) > 0.12) {
    t++;
    run++;
  }
  top = t;
  run = 0;
  let btm = bottom;
  while (btm > top && run < maxKey && rowCopper(btm, left, right) > 0.12) {
    btm--;
    run++;
  }
  bottom = btm;
  run = 0;
  let l = left;
  while (l < right && run < maxKey && colCopper(l, top, bottom) > 0.12) {
    l++;
    run++;
  }
  left = l;
  run = 0;
  let rgt = right;
  while (rgt > left && run < maxKey && colCopper(rgt, top, bottom) > 0.12) {
    rgt--;
    run++;
  }
  right = rgt;

  const pad = Math.max(2, Math.round(Math.min(right - left, bottom - top) * 0.008));
  top = Math.min(bottom - 8, top + pad);
  bottom = Math.max(top + 8, bottom - pad);
  left = Math.min(right - 8, left + pad);
  right = Math.max(left + 8, right - pad);

  posterTrim = {
    x: left / w,
    y: top / h,
    w: (right - left + 1) / w,
    h: (bottom - top + 1) / h,
  };
  return posterTrim;
}

async function boot() {
  const [rawMetrics, i18n] = await Promise.all([
    fetch(`${BASE}metrics.json`).then((r) => r.json()),
    fetch(`${BASE}i18n.json`).then((r) => r.json()).catch(() => null),
  ]);
  demoI18n = i18n;
  applyDemoChrome();
  metricsData = localizeMetrics(rawMetrics, i18n);
  buildScrollBeats(metricsData);
  buildOverlayDom(metricsData);
  await initThree();
  bindScroll();
  el.loader.classList.add('hide');
  if (IS_EMBED) {
    postToParent('demo:ready', {
      scrollHeight: document.documentElement.scrollHeight,
    });
  }
  if (ESSAY_ACT) {
    const stage = document.querySelector('.vhs-act-stage') || document.getElementById('exhibit-a');
    if (stage) {
      const visIo = new IntersectionObserver(
        ([e]) => {
          actInView = e.isIntersecting;
        },
        { rootMargin: '80px 0px', threshold: 0 },
      );
      visIo.observe(stage);
      const r = stage.getBoundingClientRect();
      actInView = r.bottom > 0 && r.top < window.innerHeight;
    }
  }
  // Layout may settle after textures/GLB — sync canvas to pin size
  onResize();
  requestAnimationFrame(() => onResize());
  window.addEventListener('resize', onResize);
  clock = new THREE.Clock();
  renderer.setAnimationLoop(tick);
}

function escapeHtml(s) {
  return String(s)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

function buildScrollBeats(data) {
  el.track.innerHTML = '';
  beatEls = data.beats.map((beat, i) => {
    const section = document.createElement('section');
    section.className = 'beat';
    section.dataset.id = beat.id;
    section.dataset.act = String(beat.act || 1);
    section.dataset.index = String(i);
    section.setAttribute('aria-label', `${beat.kicker}: ${beat.title}`);
    // Runway proportional to beat.progress span so sticky copy tracks p ranges
    const [pa, pb] = beat.progress;
    const span = Math.max(0.08, pb - pa);
    const hold =
      beat.id === 'hero'
        ? 2.35
        : beat.id === 'archive'
          ? 1.15 + span * 1.2
          : beat.id === 'knife'
            ? 1.35 + span * 2.8 // climax hold before Archive
            : 0.95 + span * 1.65; // compressed Measure runways
    section.style.minHeight = `${hold * 100}vh`;
    // Palette: full swatch cards under sticky copy (not under the poster)
    const palettePanel =
      beat.overlay && beat.overlay.type === 'palette'
        ? `<div class="pal-panel beat-pal-panel">${buildPaletteSwatchesHtml(beat.overlay.samples || [])}</div>`
        : '';
    const swatches =
      !palettePanel && beat.swatches
        ? `<div class="beat-swatches">${beat.swatches
            .map((c) => `<i style="background:${c}" title="${c}"></i>`)
            .join('')}</div>`
        : '';
    const cue =
      beat.id === 'hero'
        ? `<p class="scroll-cue">${escapeHtml(beat.cue || 'SCROLL')} <span aria-hidden="true">↓</span></p>`
        : '';
    // Single CTA lives in #essay-outro — not duplicated in sticky copy
    const actTag = ESSAY_ACT
      ? ''
      : `<div class="beat-act">${escapeHtml(tDemo('chrome.act_prefix'))} ${['', 'I', 'II', 'III', 'IV'][beat.act] || beat.act}</div>`;
    section.innerHTML = `
      <div class="beat-inner">
        ${actTag}
        <div class="beat-kicker">${escapeHtml(beat.kicker)}</div>
        <h2 class="beat-title">${escapeHtml(beat.title)}</h2>
        ${beat.body ? `<p class="beat-body">${escapeHtml(beat.body)}</p>` : ''}
        ${palettePanel}
        ${swatches}
        ${cue}
      </div>
    `;
    el.track.appendChild(section);
    return section;
  });
  wireEssayLinks();
}

function parseHex(hex) {
  const h = String(hex || '').replace('#', '');
  if (h.length !== 6) return { r: 0, g: 0, b: 0 };
  return {
    r: parseInt(h.slice(0, 2), 16) / 255,
    g: parseInt(h.slice(2, 4), 16) / 255,
    b: parseInt(h.slice(4, 6), 16) / 255,
  };
}

/** sRGB hex → OKLCH (approx, no deps). Returns {L,C,H, light}. */
function hexToOklch(hex) {
  const { r: rs, g: gs, b: bs } = parseHex(hex);
  const lin = (c) => (c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4);
  const r = lin(rs);
  const g = lin(gs);
  const b = lin(bs);
  const l = 0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b;
  const m = 0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b;
  const s = 0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b;
  const l_ = Math.cbrt(l);
  const m_ = Math.cbrt(m);
  const s_ = Math.cbrt(s);
  const L = 0.2104542553 * l_ + 0.793617785 * m_ - 0.0040720468 * s_;
  const a = 1.9779984951 * l_ - 2.428592205 * m_ + 0.4505937099 * s_;
  const bb = 0.0259040371 * l_ + 0.7827717662 * m_ - 0.808675766 * s_;
  const C = Math.sqrt(a * a + bb * bb);
  let H = (Math.atan2(bb, a) * 180) / Math.PI;
  if (H < 0) H += 360;
  return {
    L: Math.round(L * 100),
    C: Math.round(C * 1000) / 1000,
    H: Math.round(H),
    light: L > 0.62,
  };
}

function buildPaletteSwatchesHtml(samples) {
  return samples
    .map((s) => {
      const ok = hexToOklch(s.hex);
      const ink = ok.light ? '#0a0806' : '#f0e6d4';
      return `<div class="pal-swatch" data-n="${s.n}" style="background:${escapeHtml(s.hex)};color:${ink}">
        <span class="ps-n">${s.n}</span>
        <span class="ps-hex">${escapeHtml(s.hex.toUpperCase())}</span>
        <span class="ps-oklch-label">OKLCH</span>
        <span class="ps-oklch">${ok.L} ${ok.C.toFixed(3)} ${ok.H}</span>
        <span class="ps-role">${escapeHtml(s.role || '')}</span>
      </div>`;
    })
    .join('');
}

function buildPaletteOverlayHtml(def) {
  const samples = def.samples || [];
  // Handles only on the cover — filled with sample hex (swatch strip lives in beat copy)
  const handles = samples
    .map((s) => {
      const ok = hexToOklch(s.hex);
      const ink = ok.light ? '#0a0806' : '#f0e6d4';
      return `<div class="pal-handle" data-n="${s.n}" aria-hidden="true" style="background:${escapeHtml(s.hex)};color:${ink}">${s.n}</div>`;
    })
    .join('');
  const cue = escapeHtml(def.cue || 'HANDLES · SAMPLE COLORS');
  return `<span class="ov-box" hidden></span>
    <div class="pal-cue">${cue}</div>
    ${handles}
    <span class="ov-label" hidden>${escapeHtml(def.label || '')}</span>`;
}

function buildDiagonalsOverlayHtml(def) {
  const lines = (def.lines || []).map(() => `<div class="diag-line" aria-hidden="true"></div>`).join('');
  return `<span class="ov-box" hidden></span>${lines}<span class="ov-label">${escapeHtml(def.label || '')}</span>`;
}

function buildOverlayDom(data) {
  if (!el.overlays) return;
  el.overlays.innerHTML = '';
  overlayNodes = {};
  data.beats.forEach((beat) => {
    if (!beat.overlay) return;
    const node = document.createElement('div');
    node.className = 'ov';
    node.dataset.beat = beat.id;
    node.setAttribute('aria-hidden', 'true');
    if (beat.overlay.type === 'palette') {
      node.innerHTML = buildPaletteOverlayHtml(beat.overlay);
    } else if (beat.overlay.type === 'diagonals') {
      node.innerHTML = buildDiagonalsOverlayHtml(beat.overlay);
    } else {
      // Chip/label start empty+hidden — CSS :empty / [hidden]!important prevents empty black shells
      node.innerHTML =
        `<span class="ov-box" hidden></span><span class="ov-chip" hidden></span><span class="ov-label" hidden></span>`;
    }
    el.overlays.appendChild(node);
    overlayNodes[beat.id] = { el: node, def: beat.overlay || null };
  });
}

function loadImage(url) {
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.crossOrigin = 'anonymous';
    img.onload = () => resolve(img);
    img.onerror = reject;
    img.src = url;
  });
}

/** Always poster.jpg — vhs_reference*.png are mood board only. */
async function resolveCoverImage() {
  return loadImage(`${BASE}poster.jpg`);
}

function makeCanvasTexture(draw, w = 512, h = 768) {
  const c = document.createElement('canvas');
  c.width = w;
  c.height = h;
  const ctx = c.getContext('2d');
  draw(ctx, w, h);
  const tex = new THREE.CanvasTexture(c);
  tex.colorSpace = THREE.SRGBColorSpace;
  tex.anisotropy = isMobile ? 2 : 8;
  tex.needsUpdate = true;
  return tex;
}

function makeNoiseMap(size = isMobile ? 128 : 256) {
  const c = document.createElement('canvas');
  c.width = size;
  c.height = size;
  const ctx = c.getContext('2d');
  const img = ctx.createImageData(size, size);
  const d = img.data;
  for (let i = 0; i < d.length; i += 4) {
    const n = 95 + Math.random() * 110;
    d[i] = d[i + 1] = d[i + 2] = n;
    d[i + 3] = 255;
  }
  ctx.putImageData(img, 0, 0);
  ctx.globalAlpha = 0.4;
  ctx.drawImage(c, 1, 0);
  ctx.drawImage(c, -1, 0);
  ctx.drawImage(c, 0, 1);
  ctx.globalAlpha = 1;
  const tex = new THREE.CanvasTexture(c);
  tex.wrapS = tex.wrapT = THREE.RepeatWrapping;
  tex.repeat.set(2.8, 4.2);
  return tex;
}

function buildEnvMap() {
  const pmrem = new THREE.PMREMGenerator(renderer);
  const envScene = new THREE.Scene();
  const c = document.createElement('canvas');
  c.width = 512;
  c.height = 256;
  const ctx = c.getContext('2d');
  const g = ctx.createLinearGradient(0, 0, 0, 256);
  g.addColorStop(0, '#3a2a20');
  g.addColorStop(0.35, '#181410');
  g.addColorStop(0.7, '#0c0a08');
  g.addColorStop(1, '#060504');
  ctx.fillStyle = g;
  ctx.fillRect(0, 0, 512, 256);
  const key = ctx.createRadialGradient(360, 70, 10, 360, 70, 160);
  key.addColorStop(0, 'rgba(255,180,100,0.55)');
  key.addColorStop(1, 'rgba(255,180,100,0)');
  ctx.fillStyle = key;
  ctx.fillRect(0, 0, 512, 256);
  const rim = ctx.createRadialGradient(80, 120, 8, 80, 120, 120);
  rim.addColorStop(0, 'rgba(160,30,20,0.35)');
  rim.addColorStop(1, 'rgba(160,30,20,0)');
  ctx.fillStyle = rim;
  ctx.fillRect(0, 0, 512, 256);
  const map = new THREE.CanvasTexture(c);
  map.mapping = THREE.EquirectangularReflectionMapping;
  map.colorSpace = THREE.SRGBColorSpace;
  const rt = pmrem.fromEquirectangular(map);
  map.dispose();
  pmrem.dispose();
  return rt.texture;
}

/** Subtle shell wear only — never on the artwork face. */
function applyShellWear(ctx, w, h, opts = {}) {
  const { yellow = 0.04, edgeDark = 0.14 } = opts;
  if (yellow > 0) {
    ctx.fillStyle = `rgba(170,130,55,${yellow})`;
    ctx.fillRect(0, 0, w, h);
  }
  const eg = ctx.createLinearGradient(0, 0, w * 0.08, 0);
  eg.addColorStop(0, `rgba(0,0,0,${edgeDark})`);
  eg.addColorStop(1, 'rgba(0,0,0,0)');
  ctx.fillStyle = eg;
  ctx.fillRect(0, 0, w * 0.1, h);
  const eg2 = ctx.createLinearGradient(w, 0, w * 0.92, 0);
  eg2.addColorStop(0, `rgba(0,0,0,${edgeDark * 0.55})`);
  eg2.addColorStop(1, 'rgba(0,0,0,0)');
  ctx.fillStyle = eg2;
  ctx.fillRect(w * 0.9, 0, w * 0.1, h);
}

function drawSpine(ctx, w, h, title, year) {
  const g = ctx.createLinearGradient(0, 0, w, 0);
  g.addColorStop(0, '#2a1810');
  g.addColorStop(0.4, '#16100c');
  g.addColorStop(1, '#0a0705');
  ctx.fillStyle = g;
  ctx.fillRect(0, 0, w, h);

  ctx.fillStyle = '#b71c1c';
  ctx.fillRect(w * 0.18, h * 0.05, w * 0.64, h * 0.01);

  ctx.save();
  ctx.translate(w * 0.56, h * 0.5);
  ctx.rotate(-Math.PI / 2);
  ctx.fillStyle = '#c9a227';
  ctx.font = '700 34px "IBM Plex Mono", monospace';
  ctx.textAlign = 'center';
  ctx.fillText(String(year), 0, -20);
  ctx.fillStyle = '#e8dcc8';
  ctx.font = '700 48px "Anton", Impact, sans-serif';
  ctx.fillText(title.toUpperCase(), 0, 36);
  ctx.fillStyle = 'rgba(138,127,110,0.9)';
  ctx.font = '13px "IBM Plex Mono", monospace';
  ctx.fillText('SP · HI-FI · RENTAL', 0, 72);
  ctx.restore();

  ctx.fillStyle = '#e8dcc8';
  ctx.fillRect(w * 0.22, h * 0.88, w * 0.56, h * 0.05);
  ctx.fillStyle = '#120e0c';
  ctx.font = `700 ${Math.max(11, w * 0.2)}px "IBM Plex Mono", monospace`;
  ctx.textAlign = 'center';
  ctx.fillText('948', w / 2, h * 0.916);
  ctx.textAlign = 'left';

  ctx.strokeStyle = 'rgba(229,160,13,.35)';
  ctx.lineWidth = 2;
  ctx.strokeRect(6, 6, w - 12, h - 12);
  applyShellWear(ctx, w, h, { yellow: 0.035, edgeDark: 0.2 });
}

function wrapText(ctx, text, x, y, maxW, lineH) {
  const words = String(text).split(' ');
  let line = '';
  let yy = y;
  for (const word of words) {
    const test = line ? `${line} ${word}` : word;
    if (ctx.measureText(test).width > maxW && line) {
      ctx.fillText(line, x, yy);
      line = word;
      yy += lineH;
    } else {
      line = test;
    }
  }
  if (line) ctx.fillText(line, x, yy);
}

function drawBarcode(ctx, x, y, w, h) {
  ctx.fillStyle = '#e8dcc8';
  ctx.fillRect(x, y, w, h);
  let px = x + 5;
  const end = x + w - 5;
  while (px < end) {
    const bw = 1 + Math.floor(Math.random() * 3);
    if (Math.random() > 0.35) {
      ctx.fillStyle = '#0a0806';
      ctx.fillRect(px, y + 3, bw, h - 6);
    }
    px += bw + 1;
  }
}

function drawBack(ctx, w, h, data) {
  ctx.fillStyle = '#100e0c';
  ctx.fillRect(0, 0, w, h);
  const paper = ctx.createLinearGradient(0, 0, w, h);
  paper.addColorStop(0, '#1a1512');
  paper.addColorStop(1, '#0c0a08');
  ctx.fillStyle = paper;
  ctx.fillRect(16, 16, w - 32, h - 32);

  ctx.strokeStyle = '#c9a227';
  ctx.lineWidth = 2.2;
  ctx.strokeRect(28, 28, w - 56, h - 56);

  ctx.fillStyle = '#0a0806';
  ctx.fillRect(48, 48, 68, 84);
  ctx.strokeStyle = '#e8dcc8';
  ctx.lineWidth = 2;
  ctx.strokeRect(48, 48, 68, 84);
  ctx.fillStyle = '#e8dcc8';
  ctx.font = '700 40px "Anton", Impact, sans-serif';
  ctx.textAlign = 'center';
  ctx.fillText('R', 82, 102);
  ctx.font = '9px "IBM Plex Mono", monospace';
  ctx.fillText('RESTRICTED', 82, 122);
  ctx.textAlign = 'left';

  ctx.fillStyle = '#b71c1c';
  ctx.font = '700 16px "IBM Plex Mono", monospace';
  ctx.fillText('WARNING', 136, 68);
  ctx.fillStyle = '#e8dcc8';
  ctx.font = '24px "Source Serif 4", Georgia, serif';
  wrapText(ctx, data.tagline || 'The Night He Came Home!', 136, 100, w - 200, 28);

  ctx.fillStyle = '#6b6256';
  ctx.font = '12px "IBM Plex Mono", monospace';
  [
    'On Halloween night in Haddonfield, the shape returns.',
    'Flat sleeve art from the corpus — measured, not photographed.',
  ].forEach((line, i) => ctx.fillText(line, 48, 170 + i * 18));

  ctx.fillStyle = '#8a7f6e';
  ctx.font = '14px "IBM Plex Mono", monospace';
  const specs = [
    [`TMDB ${data.id}`, `IMDb ${data.imdb_id}`],
    ['FORMAT  VHS NTSC', 'AUDIO  HI-FI'],
    ['YEAR  1978', 'RUNTIME  91 MIN'],
  ];
  specs.forEach((row, i) => {
    ctx.fillText(row[0], 48, 240 + i * 26);
    ctx.fillText(row[1], w * 0.48, 240 + i * 26);
  });

  const raw = data.raw || {};
  ctx.fillStyle = '#c9a227';
  ctx.font = '11px "IBM Plex Mono", monospace';
  ctx.fillText('CORPUS READOUT', 48, 340);
  ctx.fillStyle = '#8a7f6e';
  ctx.font = '13px "IBM Plex Mono", monospace';
  [
    `symmetry ${Number(raw.symmetry || 0).toFixed(2)} · dark ${(raw.dark_share * 100).toFixed(0)}%`,
    `faces ${raw.faces} · blood ${raw.nova_blood} · knife ${raw.nova_knife}`,
    `OCR ${Number(raw.ocr_conf || 0).toFixed(2)} · creature ${raw.creature}`,
  ].forEach((t, i) => ctx.fillText(t, 48, 368 + i * 22));

  drawBarcode(ctx, 48, h - 150, w * 0.52, 44);
  ctx.fillStyle = '#6b6256';
  ctx.font = '10px "IBM Plex Mono", monospace';
  ctx.fillText('0 94800 19780 3', 48, h - 92);

  ctx.fillStyle = '#e8dcc8';
  ctx.fillRect(w - 140, h - 160, 88, 88);
  ctx.fillStyle = '#120e0c';
  ctx.font = '700 34px "Anton", Impact, sans-serif';
  ctx.textAlign = 'center';
  ctx.fillText('948', w - 96, h - 110);
  ctx.font = '10px "IBM Plex Mono", monospace';
  ctx.fillText('HORROR', w - 96, h - 90);
  ctx.textAlign = 'left';

  ctx.fillStyle = '#6b8f71';
  ctx.font = '12px "IBM Plex Mono", monospace';
  ctx.fillText('VHS · NTSC · CORPUS SLEEVE', 48, h - 56);

  applyShellWear(ctx, w, h, { yellow: 0.04, edgeDark: 0.16 });
}

function drawTopEdge(ctx, w, h) {
  ctx.fillStyle = '#1a1612';
  ctx.fillRect(0, 0, w, h);
  for (let i = 0; i < 18; i++) {
    ctx.fillStyle = i % 2 ? '#26201a' : '#12100e';
    ctx.fillRect((i / 18) * w, 0, w / 18, h);
  }
  ctx.fillStyle = '#c9a227';
  ctx.font = 'bold 24px "IBM Plex Mono", monospace';
  ctx.textAlign = 'center';
  ctx.fillText('VHS', w * 0.3, h * 0.62);
  ctx.fillStyle = '#8a7f6e';
  ctx.font = '13px "IBM Plex Mono", monospace';
  ctx.fillText('SP · HI-FI', w * 0.7, h * 0.62);
  applyShellWear(ctx, w, h, { yellow: 0.03, edgeDark: 0.1 });
}

/**
 * Cover = flat poster art only. No cardboard blowouts / wear on the artwork.
 * Mild contrast lift so oranges read under product lighting.
 */
function drawCoverClean(img) {
  const { w, h } = coverCanvasSize(1024);
  const c = document.createElement('canvas');
  c.width = w;
  c.height = h;
  const ctx = c.getContext('2d');
  ctx.imageSmoothingEnabled = true;
  ctx.imageSmoothingQuality = 'high';
  drawImageCoverFit(ctx, img, w, h);

  const id = ctx.getImageData(0, 0, w, h);
  const d = id.data;
  for (let i = 0; i < d.length; i += 4) {
    let r = d[i];
    let g = d[i + 1];
    let b = d[i + 2];
    r = clamp((r - 128) * 1.06 + 128 + 4, 0, 255);
    g = clamp((g - 128) * 1.04 + 128 + 3, 0, 255);
    b = clamp((b - 128) * 1.02 + 128 + 1, 0, 255);
    d[i] = r;
    d[i + 1] = g;
    d[i + 2] = b;
    d[i + 3] = 255; // force opaque — JPEG/canvas alpha bleed made blacks see-through
  }
  ctx.putImageData(id, 0, 0);

  const tex = new THREE.CanvasTexture(c);
  tex.colorSpace = THREE.SRGBColorSpace;
  tex.anisotropy = isMobile ? 2 : 8;
  tex.generateMipmaps = true;
  tex.minFilter = THREE.LinearMipmapLinearFilter;
  tex.magFilter = THREE.LinearFilter;
  return tex;
}

function rawNum(key, fallback = 0) {
  const r = (metricsData && metricsData.raw) || {};
  return r[key] != null ? r[key] : fallback;
}

/**
 * Analysis layers: visual tint only — numbers live in DOM overlays / counter,
 * not baked as huge glyphs on the canvas.
 */
function posterToLayerTexture(img, mode) {
  const srcW = img.naturalWidth || img.width;
  const srcH = img.naturalHeight || img.height;
  const scale = Math.min(1, 768 / Math.max(srcW, srcH));
  const w = Math.round(srcW * scale);
  const h = Math.round(srcH * scale);
  const c = document.createElement('canvas');
  c.width = w;
  c.height = h;
  const ctx = c.getContext('2d', { willReadFrequently: true });
  ctx.drawImage(img, 0, 0, w, h);
  const imageData = ctx.getImageData(0, 0, w, h);
  const d = imageData.data;

  if (mode === 'ocr') {
    for (let i = 0; i < d.length; i += 4) {
      const y = Math.floor(i / 4 / w);
      // Soft title lift only — don't bury the rest of the sleeve
      const inTitle = y > h * 0.8 && y < h * 0.95;
      const f = inTitle ? 1.08 : 0.55;
      d[i] *= f;
      d[i + 1] *= f;
      d[i + 2] *= f;
      d[i + 3] = inTitle ? 160 : 40;
    }
    ctx.putImageData(imageData, 0, 0);
  } else if (mode === 'faces') {
    // Soft silhouette scan — keep sleeve readable; mint only on midtone mass
    for (let i = 0; i < d.length; i += 4) {
      const r = d[i];
      const g = d[i + 1];
      const b = d[i + 2];
      const lum = 0.2126 * r + 0.7152 * g + 0.0722 * b;
      const mass = lum > 28 && lum < 170 ? 1 : 0;
      d[i] = mass ? Math.min(255, r * 0.35 + 28) : lum * 0.22;
      d[i + 1] = mass ? Math.min(255, g * 0.4 + 72) : lum * 0.26;
      d[i + 2] = mass ? Math.min(255, b * 0.45 + 58) : lum * 0.3;
      d[i + 3] = mass ? 118 : 28;
    }
    ctx.putImageData(imageData, 0, 0);
  } else if (mode === 'colors') {
    for (let i = 0; i < d.length; i += 4) {
      d[i] = Math.min(255, d[i] * 1.25);
      d[i + 1] = d[i + 1] * 0.72;
      d[i + 2] = d[i + 2] * 0.55;
      d[i + 3] = 200;
    }
    ctx.putImageData(imageData, 0, 0);
  } else if (mode === 'symmetry') {
    // Light mirror veil on right half — keep sleeve readable under the axis
    const copy = new Uint8ClampedArray(d);
    for (let y = 0; y < h; y++) {
      for (let x = 0; x < w; x++) {
        const i = (y * w + x) * 4;
        if (x > w / 2) {
          const mx = w - 1 - x;
          const mi = (y * w + mx) * 4;
          const t = 0.28;
          d[i] = Math.min(255, copy[i] * (1 - t) + (copy[mi] * 0.55 + 48) * t);
          d[i + 1] = Math.min(255, copy[i + 1] * (1 - t) + (copy[mi + 1] * 0.55 + 32) * t);
          d[i + 2] = Math.min(255, copy[i + 2] * (1 - t) + (copy[mi + 2] * 0.4 + 18) * t);
          d[i + 3] = 95;
        } else {
          d[i + 3] = 0;
        }
      }
    }
    ctx.putImageData(imageData, 0, 0);
  } else if (mode === 'blood') {
    for (let i = 0; i < d.length; i += 4) {
      const r = d[i];
      const g = d[i + 1];
      const b = d[i + 2];
      const redBias = Math.max(0, r - g * 0.5 - b * 0.5);
      const orange = Math.max(0, r * 0.6 + g * 0.35 - b * 0.8);
      const heat = clamp(Math.max(redBias, orange * 0.7) / 65, 0, 1);
      d[i] = Math.min(255, r * 0.55 + heat * 140);
      d[i + 1] = g * 0.35 + heat * 28;
      d[i + 2] = b * 0.28;
      d[i + 3] = 18 + heat * 110;
    }
    ctx.putImageData(imageData, 0, 0);
  } else if (mode === 'diagonals') {
    // Barely dim — DOM X guides carry the beat; avoid burying the sleeve
    for (let i = 0; i < d.length; i += 4) {
      d[i] = d[i] * 0.72;
      d[i + 1] = d[i + 1] * 0.7;
      d[i + 2] = d[i + 2] * 0.65;
      d[i + 3] = 70;
    }
    ctx.putImageData(imageData, 0, 0);
    ctx.strokeStyle = 'rgba(229,160,13,0.35)';
    ctx.lineWidth = Math.max(1, w * 0.003);
    ctx.beginPath();
    ctx.moveTo(w * 0.06, h * 0.06);
    ctx.lineTo(w * 0.94, h * 0.94);
    ctx.moveTo(w * 0.94, h * 0.06);
    ctx.lineTo(w * 0.06, h * 0.94);
    ctx.stroke();
    ctx.strokeStyle = 'rgba(183,28,28,0.45)';
    ctx.lineWidth = Math.max(1, w * 0.003);
    ctx.stroke();
  } else {
    ctx.putImageData(imageData, 0, 0);
  }

  const sized = coverCanvasSize(768);
  const out = document.createElement('canvas');
  out.width = sized.w;
  out.height = sized.h;
  const octx = out.getContext('2d');
  octx.imageSmoothingEnabled = true;
  drawImageCoverFit(octx, c, sized.w, sized.h);

  const tex = new THREE.CanvasTexture(out);
  tex.colorSpace = THREE.SRGBColorSpace;
  tex.anisotropy = isMobile ? 2 : 4;
  return tex;
}

function makePlasticMat(color = 0x1a1714, opts = {}) {
  const opacity = opts.opacity ?? 1;
  return new THREE.MeshStandardMaterial({
    color,
    roughness: opts.roughness ?? 0.82,
    metalness: opts.metalness ?? 0.06,
    roughnessMap: opts.roughnessMap ?? plasticNoiseMap,
    envMapIntensity: opts.envMapIntensity ?? 0.55,
    // Opaque by default — transparent:true at opacity 1 causes sorting flicker
    transparent: opts.transparent ?? opacity < 1,
    opacity,
    side: opts.side ?? THREE.FrontSide,
  });
}

function makeCoverMat(map) {
  // Opaque cover — never see-through; interior cassette only appears when lid opens
  return new THREE.MeshBasicMaterial({
    map,
    color: 0xffffff,
    transparent: false,
    opacity: 1,
    depthWrite: true,
    depthTest: true,
    toneMapped: false,
    side: THREE.FrontSide,
  });
}

function makePrintMat(map) {
  // Opaque always — transparent:true at opacity 1 still sorts as translucent
  // and lets shelf lines bleed through dark poster ink.
  return new THREE.MeshStandardMaterial({
    map,
    roughness: 0.68,
    metalness: 0.04,
    roughnessMap: plasticNoiseMap,
    envMapIntensity: 0.4,
    transparent: false,
    opacity: 1,
    depthWrite: true,
  });
}

function buildBaseShell(spineTex, backTex, topTex) {
  const g = new THREE.Group();
  g.name = 'baseShell';

  const plastic = makePlasticMat(0x0e0c0a);
  const spineMat = makePrintMat(spineTex);
  const backMat = makePrintMat(backTex);
  const topMat = makePrintMat(topTex);

  const backWall = new THREE.Mesh(new THREE.BoxGeometry(BOX_W, BOX_H, WALL), plastic.clone());
  backWall.position.z = -BOX_D / 2 + WALL / 2;
  backWall.castShadow = true;
  backWall.receiveShadow = true;
  g.add(backWall);
  const backPrint = new THREE.Mesh(new THREE.PlaneGeometry(BOX_W * 0.992, BOX_H * 0.992), backMat);
  backPrint.position.z = -BOX_D / 2 - 0.0015;
  backPrint.rotation.y = Math.PI;
  g.add(backPrint);

  const spineW = spineWidth();
  const spineWall = new THREE.Mesh(new THREE.BoxGeometry(spineW, BOX_H, BOX_D), plastic.clone());
  spineWall.position.set(-BOX_W / 2 + spineW / 2, 0, 0);
  spineWall.castShadow = true;
  g.add(spineWall);
  const spinePrint = new THREE.Mesh(new THREE.PlaneGeometry(BOX_D * 0.96, BOX_H * 0.975), spineMat);
  spinePrint.position.set(-BOX_W / 2 - 0.0015, 0, 0);
  spinePrint.rotation.y = -Math.PI / 2;
  g.add(spinePrint);

  const right = new THREE.Mesh(new THREE.BoxGeometry(WALL, BOX_H, BOX_D), makePlasticMat(0x12100e));
  right.position.set(BOX_W / 2 - WALL / 2, 0, 0);
  right.castShadow = true;
  g.add(right);

  const cav = cavity();
  const topWall = new THREE.Mesh(
    new THREE.BoxGeometry(cav.w, WALL, BOX_D),
    plastic.clone(),
  );
  topWall.position.set(cav.cx, BOX_H / 2 - WALL / 2, 0);
  g.add(topWall);
  const topPrint = new THREE.Mesh(new THREE.PlaneGeometry(BOX_W * 0.9, BOX_D * 0.9), topMat);
  topPrint.position.set(0, BOX_H / 2 + 0.0015, 0);
  topPrint.rotation.x = -Math.PI / 2;
  g.add(topPrint);

  const bottom = new THREE.Mesh(
    new THREE.BoxGeometry(cav.w, WALL, BOX_D),
    makePlasticMat(0x100e0c, { roughness: 0.9 }),
  );
  bottom.position.set(cav.cx, -BOX_H / 2 + WALL / 2, 0);
  bottom.receiveShadow = true;
  g.add(bottom);

  const liner = new THREE.Mesh(
    new THREE.BoxGeometry(cav.w, cav.h, 0.02),
    makePlasticMat(0x080705, { roughness: 0.95, envMapIntensity: 0.2 }),
  );
  liner.position.set(cav.cx, cav.cy, -BOX_D / 2 + WALL + 0.03);
  g.add(liner);

  const hinge = new THREE.Mesh(
    new THREE.BoxGeometry(0.03, BOX_H * 0.92, 0.04),
    makePlasticMat(0x0c0a08, { roughness: 0.7, metalness: 0.15 }),
  );
  hinge.position.set(-BOX_W / 2 + 0.02, 0, BOX_D * 0.15);
  g.add(hinge);

  return g;
}

function buildLidFrame() {
  const g = new THREE.Group();
  g.name = 'lidFrame';
  // Thin dark plastic lip — not a chunky beige museum frame
  const bezelDepth = 0.014;
  const bezelZ = BOX_D / 2 - bezelDepth / 2;
  const bezelMat = makePlasticMat(0x0a0908, {
    roughness: 0.9,
    metalness: 0.1,
    envMapIntensity: 0.4,
  });

  const pieces = [
    { w: BOX_W, h: BEZEL, x: 0, y: BOX_H / 2 - BEZEL / 2 },
    { w: BOX_W, h: BEZEL, x: 0, y: -BOX_H / 2 + BEZEL / 2 },
    { w: BEZEL, h: BOX_H - BEZEL * 2, x: -BOX_W / 2 + BEZEL / 2, y: 0 },
    { w: BEZEL, h: BOX_H - BEZEL * 2, x: BOX_W / 2 - BEZEL / 2, y: 0 },
  ];
  for (const p of pieces) {
    const mesh = new THREE.Mesh(new THREE.BoxGeometry(p.w, p.h, bezelDepth), bezelMat.clone());
    mesh.position.set(p.x, p.y, bezelZ);
    mesh.castShadow = true;
    g.add(mesh);
  }

  return g;
}

/** Real VHS footprint in portrait tray units (short × long × thin). */
function vhsPortraitFootprint() {
  // 103 × 187 × 25 mm → normalize on long axis
  return new THREE.Vector3(103 / 187, 1, 25 / 187);
}

async function loadCassetteFaceTextures() {
  const loader = new THREE.TextureLoader();
  try {
    const face = await loader.loadAsync(`${BASE}vhs-cassette-face.jpg`);
    face.colorSpace = THREE.SRGBColorSpace;
    face.anisotropy = 8;
    face.wrapS = THREE.ClampToEdgeWrapping;
    face.wrapT = THREE.ClampToEdgeWrapping;
    face.needsUpdate = true;
    let side = null;
    try {
      side = await loader.loadAsync(`${BASE}vhs-cassette-side.jpg`);
      side.colorSpace = THREE.SRGBColorSpace;
      side.anisotropy = 4;
      side.wrapS = THREE.ClampToEdgeWrapping;
      side.wrapT = THREE.ClampToEdgeWrapping;
      side.needsUpdate = true;
    } catch (_) {
      /* side map optional */
    }
    return { face, side };
  } catch (err) {
    console.warn('[poster-decompose] cassette face textures failed', err);
    return { face: null, side: null };
  }
}

/**
 * Hybrid photo + simple shell: opaque thick body, real Halloween face albedo,
 * portrait in the tray. No coplanar reel stacks / glass (those caused flicker).
 */
function buildCassetteMesh(faceTex, sideTex) {
  const cav = cavity();
  const fill = 0.94;
  const casW = cav.w * fill;
  const casH = cav.h * fill;
  // Real ~25mm depth relative to long edge (~187mm)
  const casD = Math.min(casH * (25 / 187), Math.max(0.12, BOX_D - WALL * 2 - 0.06));
  const frontZ = casD / 2;
  const faceEps = 0.003;

  const cassette = new THREE.Group();
  cassette.name = 'cassette';
  cassette.userData.casH = casH;
  cassette.userData.casW = casW;
  cassette.userData.casD = casD;
  // Clear gap above tray liner — kills z-fight flicker
  cassette.userData.baseZ = -BOX_D / 2 + WALL + casD / 2 + 0.035;
  cassette.userData.baseX = cav.cx;
  cassette.userData.baseRotX = 0;
  cassette.userData.baseRotY = 0;
  cassette.userData.baseRotZ = 0;
  cassette.userData.fromPhoto = true;

  const shellMat = new THREE.MeshStandardMaterial({
    color: 0x12100e,
    roughness: 0.94,
    metalness: 0.03,
    roughnessMap: plasticNoiseMap || undefined,
    envMapIntensity: 0.35,
  });
  const shell = new THREE.Mesh(new THREE.BoxGeometry(casW, casH, casD), shellMat);
  shell.castShadow = true;
  shell.receiveShadow = true;
  cassette.add(shell);

  // Side skins (matte plastic) — optional map, never transparent
  const sideMat = new THREE.MeshStandardMaterial({
    color: 0x0e0c0a,
    map: sideTex || null,
    roughness: 0.92,
    metalness: 0.04,
    envMapIntensity: 0.3,
  });
  [-1, 1].forEach((side) => {
    const panel = new THREE.Mesh(new THREE.PlaneGeometry(casD * 0.98, casH * 0.98), sideMat);
    panel.rotation.y = side > 0 ? Math.PI / 2 : -Math.PI / 2;
    panel.position.x = side * (casW / 2 + 0.0008);
    cassette.add(panel);
  });

  // Photo face — single opaque plane, slightly proud of the shell (+Z toward lid)
  if (faceTex) {
    const faceMat = new THREE.MeshStandardMaterial({
      map: faceTex,
      color: 0xffffff,
      roughness: 0.78,
      metalness: 0.0,
      envMapIntensity: 0.28,
      transparent: false,
      depthWrite: true,
    });
    const face = new THREE.Mesh(new THREE.PlaneGeometry(casW * 0.995, casH * 0.995), faceMat);
    face.position.z = frontZ + faceEps;
    face.castShadow = false;
    face.receiveShadow = true;
    cassette.add(face);
  }

  // Insert-edge flap as a shallow 3D block on +X (right edge in the reference photo)
  const flapW = casW * 0.07;
  const flapMat = makePlasticMat(0x141210, { roughness: 0.88, envMapIntensity: 0.4 });
  const flap = new THREE.Mesh(
    new THREE.BoxGeometry(flapW, casH * 0.985, casD * 0.55),
    flapMat,
  );
  flap.position.set(casW / 2 - flapW * 0.35, 0, frontZ * 0.15);
  flap.castShadow = true;
  cassette.add(flap);

  // Back face slightly darker so the shell reads as volume when lid swings
  const back = new THREE.Mesh(
    new THREE.PlaneGeometry(casW * 0.98, casH * 0.98),
    makePlasticMat(0x0a0908, { roughness: 0.96, envMapIntensity: 0.15 }),
  );
  back.rotation.y = Math.PI;
  back.position.z = -frontZ - 0.0008;
  cassette.add(back);

  return cassette;
}

/**
 * Load authored VHS tape GLB into a Group named 'cassette'.
 * Oriented and centered only — world scale happens after the shell is sized to the tape.
 *
 * vhs_tape.glb (Sketchfab “VHS”) native axes ≈ X long · Y thin · Z face-height.
 * Portrait tray: long axis along tray height (Y), short along width (X), label toward lid (+Z).
 * Old vhs_cassette.glb was a Y-tall BOX — do not use it as the tape.
 */
async function loadCassetteGlb() {
  try {
    const loader = new GLTFLoader();
    loader.setPath(`${BASE}assets/`);
    loader.setResourcePath('./assets/');
    const gltf = await loader.loadAsync('vhs_tape.glb');

    const cassette = new THREE.Group();
    cassette.name = 'cassette';

    const model = gltf.scene;
    cassette.add(model);

    cassette.traverse((obj) => {
      if (obj.isMesh) {
        obj.castShadow = true;
        obj.receiveShadow = true;
      }
    });

    // Face-up (Rx) then yaw in tray (Rz): long → Y, short → X, thin → +Z (label to lid).
    // Use quaternions — Euler XYZ (π/2,0,π/2) gimbal-swaps long onto Z.
    const qx = new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(1, 0, 0), Math.PI / 2);
    const qz = new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(0, 0, 1), Math.PI / 2);
    model.quaternion.copy(qz).multiply(qx);

    const box = new THREE.Box3().setFromObject(model);
    const center = box.getCenter(new THREE.Vector3());
    model.position.sub(center);

    cassette.userData.fromGlb = true;
    cassette.userData.baseRotX = 0;
    cassette.userData.baseRotY = 0;
    cassette.userData.baseRotZ = 0;
    return cassette;
  } catch (err) {
    console.warn('[poster-decompose] vhs_tape.glb failed, using procedural cassette', err);
    return null;
  }
}

/**
 * Vintage VHS player (Sketchfab CC-BY · Tejay21).
 * Fit-scale lives on the inner model so root.scale can animate without nuking size.
 * Front bay faces +Z after centering; CassetteCover flap lifts for the insert.
 */
async function loadVhsPlayerGlb() {
  try {
    const loader = new GLTFLoader();
    loader.setPath(`${BASE}assets/`);
    loader.setResourcePath('./assets/');
    const gltf = await loader.loadAsync('vhs_player.glb');

    const root = new THREE.Group();
    root.name = 'vhsPlayer';
    const model = gltf.scene;
    model.name = 'vhsPlayerModel';
    root.add(model);

    root.traverse((obj) => {
      if (obj.isMesh) {
        obj.castShadow = !isMobile;
        obj.receiveShadow = true;
        if (obj.material) {
          const mats = Array.isArray(obj.material) ? obj.material : [obj.material];
          mats.forEach((m) => {
            if (m.map) m.map.colorSpace = THREE.SRGBColorSpace;
            m.needsUpdate = true;
          });
        }
      }
    });

    // Sketchfab FBX roots often ship huge / off-center — normalize on the *model*, not root
    const box = new THREE.Box3().setFromObject(model);
    const center = box.getCenter(new THREE.Vector3());
    const size0 = box.getSize(new THREE.Vector3());
    model.position.sub(center);

    // Deck wider than tape (~2.0 world units wide when hero-scale ≈ 1)
    const targetW = 2.05;
    const fit = targetW / Math.max(size0.x, size0.z, 1e-6);
    model.scale.setScalar(fit);

    // Re-center after fit — Sketchfab roots often leave a residual offset
    let boxFit = new THREE.Box3().setFromObject(root);
    model.position.sub(boxFit.getCenter(new THREE.Vector3()));
    boxFit = new THREE.Box3().setFromObject(root);
    const size = boxFit.getSize(new THREE.Vector3());
    const height = size.y;
    const depth = size.z;

    let cover = null;
    root.traverse((obj) => {
      if (cover) return;
      if (obj.name === 'CassetteCover_Baked' || (obj.name && obj.name.startsWith('CassetteCover'))) {
        cover = obj;
      }
    });
    if (cover) {
      cover.userData.baseRot = cover.rotation.clone();
      root.userData.cassetteCover = cover;
      const cb = new THREE.Box3().setFromObject(cover);
      const cs = cb.getSize(new THREE.Vector3());
      // Cover flap width ≈ door opening (slightly inset)
      root.userData.bayWidth = Math.max(cs.x, cs.z) * 0.88;
      root.userData.bayHeight = Math.min(cs.y, Math.min(cs.x, cs.z)) * 0.9;
    } else {
      root.userData.bayWidth = size.x * 0.46;
      root.userData.bayHeight = size.y * 0.22;
    }

    // Front-load bay: CassetteCover marks the door; mouth on the front (+Z) face
    root.updateMatrixWorld(true);
    if (cover) {
      const cb = new THREE.Box3().setFromObject(cover);
      const mouth = cb.getCenter(new THREE.Vector3());
      mouth.z = boxFit.max.z * 0.88;
      root.worldToLocal(mouth);
      root.userData.slotLocal = mouth;
    } else {
      root.userData.slotLocal = new THREE.Vector3(0, height * 0.08, depth * 0.46);
    }
    // Tray: +Y long, +Z thin (label), +X short.
    // Slot: +X long (across door), +Y thin (up), +Z depth.
    // R: e_x→e_z, e_y→e_x, e_z→e_y
    const basis = new THREE.Matrix4().makeBasis(
      new THREE.Vector3(0, 0, 1),
      new THREE.Vector3(1, 0, 0),
      new THREE.Vector3(0, 1, 0),
    );
    root.userData.slotQuat = new THREE.Quaternion().setFromRotationMatrix(basis);
    root.userData.insertAxis = new THREE.Vector3(0, 0, -1);
    root.userData.size = size.clone();
    root.userData.fitScale = fit;
    root.scale.set(1, 1, 1);
    root.visible = false;
    return root;
  } catch (err) {
    console.warn('[poster-decompose] vhs_player.glb failed — archive insert skipped', err);
    return null;
  }
}

function restoreCassetteToTray(cassette) {
  if (!cassette || !cassette.userData.flying) return;
  const home = cassette.userData.homeParent;
  if (home) home.attach(cassette);
  if (cassette.userData.flightStartScale) {
    // scale was world-space while flying; after attach, reset via re-fit from tray pose next frame
    cassette.userData.flightStartScale = null;
  }
  cassette.userData.flying = false;
  cassette.userData.flightStartPos = null;
  cassette.userData.flightStartQuat = null;
  cassette.userData.flightStartSize = null;
}

/**
 * Archive choreography: lid open → VCR takes frame → tape arcs into bay.
 * Waypoints: tray → lift → hover in front of slot → slide in.
 */
function updateArchivePlayerInsert(p, open) {
  const playerReveal = remap(p, 0.80, 0.87);
  const insert = remap(p, 0.84, 0.985);
  const coverLift = remap(p, 0.81, 0.87);

  if (playerGroup) {
    const show = playerReveal > 0.008;
    playerGroup.visible = show;
    const targetX = isMobile ? 0.15 : 0.55;
    const targetY = isMobile ? -0.2 : -0.08;
    const targetZ = isMobile ? 0.7 : 0.55;
    playerGroup.position.set(
      lerp(targetX + 3.4, targetX, playerReveal),
      lerp(targetY - 0.15, targetY, playerReveal),
      lerp(targetZ - 1.0, targetZ, playerReveal),
    );
    playerGroup.rotation.set(
      0.1,
      lerp(-0.7, isMobile ? -0.08 : -0.12, playerReveal),
      0,
    );
    const baseS = isMobile ? 0.85 : 1.05;
    playerGroup.scale.setScalar(baseS * lerp(0.8, 1, playerReveal));

    const cover = playerGroup.userData.cassetteCover;
    if (cover && cover.userData.baseRot) {
      const br = cover.userData.baseRot;
      // Keep flap open (visible) so the top-load well reads
      cover.visible = true;
      cover.rotation.set(br.x + coverLift * -0.55, br.y, br.z);
    }
  }

  if (vhsGroup && playerReveal > 0) {
    vhsGroup.position.x += playerReveal * (isMobile ? -1.1 : -1.9);
    vhsGroup.position.y += playerReveal * 0.25;
    vhsGroup.position.z -= playerReveal * 0.85;
    vhsGroup.scale.multiplyScalar(lerp(1, isMobile ? 0.42 : 0.36, playerReveal));
    // Hide empty clamshell once the tape is in flight — ghost box fights the read
    vhsGroup.visible = insert < 0.35;
    if (baseShell) {
      const fade = Math.max(playerReveal * 0.55, remap(insert, 0.05, 0.45));
      baseShell.traverse((obj) => {
        if (!obj.isMesh || !obj.material) return;
        const mats = Array.isArray(obj.material) ? obj.material : [obj.material];
        mats.forEach((m) => {
          if (m.userData._archiveBaseOp === undefined) m.userData._archiveBaseOp = m.opacity ?? 1;
          if (!m.transparent) {
            m.transparent = true;
            m.needsUpdate = true;
          }
          m.opacity = m.userData._archiveBaseOp * (1 - fade * 0.98);
          m.depthWrite = m.opacity > 0.35;
        });
      });
    }
    if (lidContent) {
      lidContent.visible = fadeShellVisible(playerReveal, insert);
    }
  } else if (vhsGroup) {
    vhsGroup.visible = true;
    if (lidContent) lidContent.visible = true;
  }

  const cassette =
    (interiorGroup && interiorGroup.getObjectByName('cassette')) ||
    (scene && scene.getObjectByName('cassette'));
  if (!cassette) return { playerReveal, insert };

  if (insert < 0.015 || !playerGroup || playerReveal < 0.35) {
    restoreCassetteToTray(cassette);
    return { playerReveal, insert };
  }

  if (!cassette.userData.flying) {
    cassette.userData.homeParent = cassette.parent;
    scene.attach(cassette);
    cassette.userData.flying = true;
    cassette.userData.flightStartPos = cassette.position.clone();
    cassette.userData.flightStartQuat = cassette.quaternion.clone();
    cassette.userData.flightStartScale = cassette.scale.clone();
    const startBox = new THREE.Box3().setFromObject(cassette);
    cassette.userData.flightStartSize = startBox.getSize(new THREE.Vector3());
    cassette.visible = true;
  }

  const startPos = cassette.userData.flightStartPos;
  const startQuat = cassette.userData.flightStartQuat;
  const startS = cassette.userData.flightStartScale;
  const startSize =
    cassette.userData.flightStartSize || new THREE.Vector3(startS.x, startS.y, startS.z);

  // Front-load: hover in front of slot (same Y), then slide into deck along −Z
  playerGroup.updateMatrixWorld(true);
  _slotWorld.copy(playerGroup.userData.slotLocal);
  playerGroup.localToWorld(_slotWorld);
  const into = (playerGroup.userData.insertAxis || new THREE.Vector3(0, 0, -1))
    .clone()
    .transformDirection(playerGroup.matrixWorld)
    .normalize();
  const out = into.clone().multiplyScalar(-1);

  const hover = _slotWorld.clone().addScaledVector(out, isMobile ? 0.75 : 1.05);
  // Keep Y locked to the slot so the tape doesn't climb over the deck
  hover.y = _slotWorld.y;
  const seated = _slotWorld.clone().addScaledVector(into, isMobile ? 0.06 : 0.08);

  // 0–0.2 lift · 0.1–0.5 travel to hover · 0.45–1.0 slide in
  const liftT = smoothstep(0, 0.2, insert);
  const travelT = smoothstep(0.1, 0.5, insert);
  const slideT = smoothstep(0.42, 1, insert);

  const liftPos = startPos.clone();
  liftPos.y += (isMobile ? 0.22 : 0.3) * liftT;
  // Swing sideways toward the deck early so we don't stay trapped behind it
  liftPos.x = lerp(startPos.x, hover.x, liftT * 0.35);
  liftPos.z = lerp(startPos.z, hover.z, liftT * 0.2);

  _flightPos.lerpVectors(liftPos, hover, travelT);
  _flightPos.lerp(seated, slideT);
  cassette.position.copy(_flightPos);

  playerGroup.getWorldQuaternion(_slotQuat);
  _slotQuat.multiply(playerGroup.userData.slotQuat);
  _flightQuat.copy(startQuat).slerp(_slotQuat, smoothstep(0.05, 0.42, insert));
  cassette.quaternion.copy(_flightQuat);

  // Measure width across the slot (X) after insert orientation — not max AABB
  cassette.scale.copy(startS);
  cassette.updateWorldMatrix(true, true);
  const liveBox = new THREE.Box3().setFromObject(cassette);
  const liveSize = liveBox.getSize(_tmpV);
  const liveWidth = liveSize.x; // long axis should sit on X after slotQuat
  const bayW = (playerGroup.userData.bayWidth || 0.9) * playerGroup.scale.x;
  const fitMul = (bayW * 0.94) / Math.max(liveWidth, 1e-6);
  const scaleMul = lerp(1, fitMul, smoothstep(0.1, 0.48, insert));
  cassette.scale.set(startS.x * scaleMul, startS.y * scaleMul, startS.z * scaleMul);

  cassette.visible = true;
  return { playerReveal, insert };
}

function fadeShellVisible(playerReveal, insert) {
  return playerReveal < 0.85 && insert < 0.35;
}

function tapeFootprintOf(cassette) {
  const box = new THREE.Box3().setFromObject(cassette);
  return box.getSize(new THREE.Vector3());
}

function fitCassetteIntoTray(cassette) {
  const box = new THREE.Box3().setFromObject(cassette);
  const size = box.getSize(new THREE.Vector3());
  const cav = cavity();
  const maxD = Math.max(0.12, BOX_D - WALL * 2 - 0.04);
  // Photo hybrid already sized ~94% of cavity; only re-fit GLB leftovers
  const fill = cassette.userData.fromPhoto ? 0.95 : 0.995;
  const sXY = Math.min(cav.w / Math.max(size.x, 1e-6), cav.h / Math.max(size.y, 1e-6)) * fill;
  let sZ = sXY;
  if (size.z * sZ > maxD) sZ = maxD / Math.max(size.z, 1e-6);
  if (!cassette.userData.fromPhoto) cassette.scale.set(sXY, sXY, sZ);

  box.setFromObject(cassette);
  box.getSize(size);
  cassette.userData.casH = size.y;
  cassette.userData.baseZ = -BOX_D / 2 + WALL + size.z / 2 + 0.035;
  cassette.userData.baseX = cav.cx;
}

async function buildInterior(cassette) {
  const g = new THREE.Group();
  g.name = 'interior';
  const cav = cavity();

  const tray = new THREE.Mesh(
    new THREE.BoxGeometry(cav.w, cav.h, 0.028),
    makePlasticMat(0x080705, { roughness: 0.95 }),
  );
  tray.position.set(cav.cx, cav.cy, -BOX_D / 2 + WALL + 0.05);
  tray.receiveShadow = true;
  g.add(tray);

  if (cassette) {
    cassette.position.set(cassette.userData.baseX ?? cav.cx, 0, cassette.userData.baseZ);
    cassette.rotation.set(
      cassette.userData.baseRotX ?? 0,
      cassette.userData.baseRotY ?? 0,
      cassette.userData.baseRotZ ?? 0,
    );
    cassette.visible = false;
    cassette.userData.shown = false;
    g.add(cassette);
  }

  return g;
}

function buildContactShadow() {
  const size = 256;
  const c = document.createElement('canvas');
  c.width = size;
  c.height = size;
  const ctx = c.getContext('2d');
  // Wide soft falloff — studio contact, not a hard sticker
  const g = ctx.createRadialGradient(size / 2, size / 2, size * 0.02, size / 2, size / 2, size * 0.5);
  g.addColorStop(0, 'rgba(0,0,0,0.42)');
  g.addColorStop(0.22, 'rgba(0,0,0,0.2)');
  g.addColorStop(0.5, 'rgba(0,0,0,0.07)');
  g.addColorStop(0.78, 'rgba(0,0,0,0.02)');
  g.addColorStop(1, 'rgba(0,0,0,0)');
  ctx.fillStyle = g;
  ctx.fillRect(0, 0, size, size);
  const tex = new THREE.CanvasTexture(c);
  const mat = new THREE.MeshBasicMaterial({
    map: tex,
    transparent: true,
    opacity: 0.62,
    depthWrite: false,
  });
  const mesh = new THREE.Mesh(new THREE.PlaneGeometry(BOX_W * 1.9, BOX_D * 3.6), mat);
  mesh.rotation.x = -Math.PI / 2;
  mesh.position.y = -BOX_H / 2 - 0.012;
  mesh.renderOrder = -1;
  return mesh;
}

async function initThree() {
  const img = await resolveCoverImage();
  const srcW = img.naturalWidth || img.width;
  const srcH = img.naturalHeight || img.height;
  detectPosterTrim(img);
  setPosterAspect((posterTrim.w * srcW) / Math.max(posterTrim.h * srcH, 1e-6));
  plasticNoiseMap = makeNoiseMap();

  // Closed sleeve only — no interior cassette, no VCR insert.
  setBoxFromTapeFootprint(vhsPortraitFootprint());
  const cassette = null;
  playerGroup = null;

  renderer = new THREE.WebGLRenderer({
    antialias: !isMobile,
    alpha: true,
    powerPreference: 'high-performance',
  });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, isMobile ? 1.25 : 2));
  const { w: vw, h: vh } = viewportSize();
  renderer.setSize(vw, vh);
  renderer.setClearColor(0x000000, 0);
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.toneMapping = THREE.NeutralToneMapping;
  renderer.toneMappingExposure = 1.55;
  renderer.shadowMap.enabled = !isMobile;
  renderer.shadowMap.type = THREE.PCFSoftShadowMap;
  el.stage.appendChild(renderer.domElement);

  scene = new THREE.Scene();
  scene.fog = new THREE.FogExp2(0x0a0806, 0.012);
  scene.environment = buildEnvMap();

  camera = new THREE.PerspectiveCamera(26, vw / vh, 0.1, 80);
  camera.position.set(0.12, 0.06, 7.8);

  scene.add(new THREE.AmbientLight(0x4a4038, 0.72));
  scene.add(new THREE.HemisphereLight(0xfff0e0, 0x100c0a, 0.7));

  keyLight = new THREE.DirectionalLight(0xfff4ea, 2.35);
  keyLight.position.set(2.4, 3.8, 5.6);
  keyLight.castShadow = !isMobile;
  if (keyLight.castShadow) {
    keyLight.shadow.mapSize.set(1024, 1024);
    keyLight.shadow.camera.near = 1;
    keyLight.shadow.camera.far = 18;
    keyLight.shadow.camera.left = -5;
    keyLight.shadow.camera.right = 5;
    keyLight.shadow.camera.top = 5;
    keyLight.shadow.camera.bottom = -5;
    keyLight.shadow.bias = -0.00035;
    keyLight.shadow.radius = 4; // softer penumbra
  }
  scene.add(keyLight);

  const frontFill = new THREE.DirectionalLight(0xfff8f2, 1.05);
  frontFill.position.set(0.15, 0.9, 7.2);
  scene.add(frontFill);
  frontFillLight = frontFill;

  // Soft fill into the open clamshell so black cassette plastic keeps edge definition
  const interiorFill = new THREE.PointLight(0xffe8d0, 14, 8, 2);
  interiorFill.position.set(0.15, 0.35, 1.1);
  scene.add(interiorFill);
  interiorFillLight = interiorFill;

  // Blood-warm rim from behind-left — edge of sleeve, not a flood
  rimLight = new THREE.PointLight(0xc43a28, 26, 14, 1.85);
  rimLight.position.set(-3.4, 2.4, -0.6);
  scene.add(rimLight);

  // Cool rim opposite — separates dark plastic from void
  rimCoolLight = new THREE.PointLight(0x7a92a8, 14, 12, 2);
  rimCoolLight.position.set(3.6, 1.6, -1.0);
  scene.add(rimCoolLight);

  const fill = new THREE.PointLight(0xe8c090, 14, 16, 2.1);
  fill.position.set(3.0, -0.6, 3.6);
  scene.add(fill);

  const bounce = new THREE.DirectionalLight(0x5a4a3c, 0.45);
  bounce.position.set(-1.0, -2.8, 1.0);
  scene.add(bounce);

  floor = new THREE.Mesh(
    new THREE.PlaneGeometry(18, 18),
    new THREE.ShadowMaterial({ opacity: 0.22 }),
  );
  floor.rotation.x = -Math.PI / 2;
  floor.position.y = -BOX_H / 2 - 0.04;
  floor.receiveShadow = true;
  scene.add(floor);

  // Dark floor disk (atmosphere under product)
  const darkFloor = new THREE.Mesh(
    new THREE.CircleGeometry(4.2, 48),
    new THREE.MeshStandardMaterial({
      color: 0x060504,
      roughness: 0.95,
      metalness: 0.02,
      transparent: true,
      opacity: 0.85,
    }),
  );
  darkFloor.rotation.x = -Math.PI / 2;
  darkFloor.position.y = -BOX_H / 2 - 0.038;
  darkFloor.receiveShadow = true;
  scene.add(darkFloor);

  vhsGroup = new THREE.Group();
  vhsGroup.name = 'vhs';

  lidPivot = new THREE.Group();
  lidPivot.name = 'lidPivot';
  lidPivot.position.set(-BOX_W / 2, 0, 0);
  lidContent = new THREE.Group();
  lidContent.name = 'lidContent';
  lidContent.position.set(BOX_W / 2, 0, 0);
  lidPivot.add(lidContent);

  baseShell = new THREE.Group();
  interiorGroup = new THREE.Group();
  layerGroup = new THREE.Group();

  vhsGroup.add(baseShell);
  vhsGroup.add(interiorGroup);
  vhsGroup.add(lidPivot);
  scene.add(vhsGroup);
  if (playerGroup) scene.add(playerGroup);

  const spineTex = makeCanvasTexture(
    (ctx, w, h) => drawSpine(ctx, w, h, metricsData.title, metricsData.year),
    160,
    768,
  );
  const backTex = makeCanvasTexture((ctx, w, h) => drawBack(ctx, w, h, metricsData), 512, 768);
  const topTex = makeCanvasTexture((ctx, w, h) => drawTopEdge(ctx, w, h), 512, 128);

  baseShell.add(buildBaseShell(spineTex, backTex, topTex));
  interiorGroup.add(await buildInterior(cassette));
  lidContent.add(buildLidFrame());

  contactShadow = buildContactShadow();
  vhsGroup.add(contactShadow);

  const coverTex = drawCoverClean(img);
  const frontZ = BOX_D / 2 - 0.001;

  const layerDefs = [
    { key: 'cover', mode: 'poster', z: frontZ, opacity: 1 },
    { key: 'ocr', mode: 'ocr', z: frontZ + 0.008, opacity: 0 },
    { key: 'faces', mode: 'faces', z: frontZ + 0.016, opacity: 0 },
    { key: 'colors', mode: 'colors', z: frontZ + 0.024, opacity: 0 },
    { key: 'symmetry', mode: 'symmetry', z: frontZ + 0.032, opacity: 0 },
    { key: 'diagonals', mode: 'diagonals', z: frontZ + 0.036, opacity: 0 },
    { key: 'blood', mode: 'blood', z: frontZ + 0.04, opacity: 0 },
  ];

  // Opaque black plate behind cover — blocks shelf bleed through dark ink
  const coverBacking = new THREE.Mesh(
    new THREE.PlaneGeometry(COVER_W + 0.01, COVER_H + 0.01),
    new THREE.MeshBasicMaterial({
      color: 0x000000,
      transparent: false,
      opacity: 1,
      depthWrite: true,
      toneMapped: false,
    }),
  );
  coverBacking.position.z = frontZ - 0.002;
  coverBacking.name = 'coverBacking';
  lidContent.add(coverBacking);

  for (const def of layerDefs) {
    const tex = def.key === 'cover' ? coverTex : posterToLayerTexture(img, def.mode);
    // Peel layers: Basic — no specular bloom that washes the sleeve under metric tints
    const mat =
      def.key === 'cover'
        ? makeCoverMat(tex)
        : new THREE.MeshBasicMaterial({
            map: tex,
            transparent: true,
            opacity: def.opacity,
            depthWrite: false,
            toneMapped: false,
          });
    const mesh = new THREE.Mesh(new THREE.PlaneGeometry(COVER_W, COVER_H), mat);
    mesh.position.z = def.z;
    mesh.userData.baseZ = def.z;
    mesh.userData.key = def.key;
    mesh.castShadow = def.key === 'cover';
    mesh.renderOrder = def.key === 'cover' ? 2 : 3;
    layerGroup.add(mesh);
    layers[def.key] = mesh;
  }
  coverBacking.renderOrder = 1;
  lidContent.add(layerGroup);

  coverAnchor = new THREE.Object3D();
  coverAnchor.position.set(0, 0, frontZ);
  lidContent.add(coverAnchor);

  dust = buildDust();
  scene.add(dust);

  storeGroup = await buildVhsStore();
  scene.add(storeGroup);
  updateStoreSlotWorld();
  if (storeGroup.userData.shelfPosterCount) {
    console.info(
      `[poster-decompose] shelf corpus posters: ${storeGroup.userData.shelfPosterCount}`,
    );
  }

  // Hero ¾ — smaller so copy + overlays stay readable
  vhsGroup.rotation.set(-0.08, -0.58, 0.02);
  vhsGroup.position.set(isMobile ? 0 : 0.72, isMobile ? 0.14 : 0.02, 0);
  vhsGroup.scale.setScalar(isMobile ? 0.52 : 0.68);
  storeHeroPos.copy(vhsGroup.position);
  storeHeroRot.copy(vhsGroup.rotation);
  storeHeroScale = vhsGroup.scale.x;

  if (el.tapeStamp) {
    el.tapeStamp.textContent = `${metricsData.title} · ${metricsData.year}`;
  }
}

function buildDust() {
  const n = isMobile ? 36 : 100;
  const pos = new Float32Array(n * 3);
  for (let i = 0; i < n; i++) {
    pos[i * 3] = (Math.random() - 0.5) * 12;
    pos[i * 3 + 1] = (Math.random() - 0.5) * 8;
    pos[i * 3 + 2] = -1 - Math.random() * 5;
  }
  const geo = new THREE.BufferGeometry();
  geo.setAttribute('position', new THREE.BufferAttribute(pos, 3));
  const mat = new THREE.PointsMaterial({
    color: 0xd4550a,
    size: 0.024,
    transparent: true,
    opacity: 0.12,
    depthWrite: false,
    blending: THREE.NormalBlending,
  });
  return new THREE.Points(geo, mat);
}

/**
 * Procedural faux VHS cover — fallback if a corpus poster fails to load.
 */
function makeFakeVhsCoverTexture(seed, title) {
  const w = 256;
  const h = 384;
  const c = document.createElement('canvas');
  c.width = w;
  c.height = h;
  const ctx = c.getContext('2d');
  const rnd = () => {
    seed = (seed * 16807) % 2147483647;
    return (seed - 1) / 2147483646;
  };
  const palettes = [
    ['#1a0806', '#b71c1c', '#c9a227'],
    ['#0c100c', '#2f4a32', '#a8b89a'],
    ['#120a08', '#d4550a', '#f0e6d4'],
    ['#0a0c12', '#1c2838', '#6b8f71'],
    ['#140c08', '#5a2810', '#d4a574'],
    ['#100808', '#8b1a12', '#e8dcc8'],
  ];
  const pal = palettes[Math.floor(rnd() * palettes.length)];
  const g = ctx.createLinearGradient(0, 0, 0, h);
  g.addColorStop(0, pal[0]);
  g.addColorStop(0.55, pal[1]);
  g.addColorStop(1, '#060504');
  ctx.fillStyle = g;
  ctx.fillRect(0, 0, w, h);
  ctx.fillStyle = pal[2];
  ctx.globalAlpha = 0.35 + rnd() * 0.35;
  ctx.beginPath();
  ctx.ellipse(w * (0.3 + rnd() * 0.4), h * (0.35 + rnd() * 0.2), w * 0.28, h * 0.22, rnd(), 0, Math.PI * 2);
  ctx.fill();
  ctx.globalAlpha = 1;
  ctx.fillStyle = 'rgba(0,0,0,0.55)';
  ctx.fillRect(12, h * 0.72, w - 24, h * 0.2);
  ctx.fillStyle = '#f0e6d4';
  ctx.font = '700 22px "Anton", Impact, sans-serif';
  ctx.textAlign = 'center';
  ctx.fillText(String(title).toUpperCase().slice(0, 14), w / 2, h * 0.84);
  if (rnd() > 0.35) {
    ctx.fillStyle = '#c9a227';
    ctx.beginPath();
    ctx.arc(w - 28, 28, 14, 0, Math.PI * 2);
    ctx.fill();
    ctx.fillStyle = '#1a1208';
    ctx.font = '700 10px "IBM Plex Mono", monospace';
    ctx.fillText('VHS', w - 28, 32);
  }
  const tex = new THREE.CanvasTexture(c);
  tex.colorSpace = THREE.SRGBColorSpace;
  tex.anisotropy = isMobile ? 2 : 4;
  return tex;
}

function textureFromImage(img) {
  const tex = new THREE.Texture(img);
  tex.colorSpace = THREE.SRGBColorSpace;
  tex.anisotropy = isMobile ? 2 : 8;
  tex.needsUpdate = true;
  tex.generateMipmaps = true;
  tex.minFilter = THREE.LinearMipmapLinearFilter;
  tex.magFilter = THREE.LinearFilter;
  return tex;
}

/** Slim spine face for sideways tapes (title + rental stripe). */
function makeSpineLabelTexture(seed, title) {
  const w = 96;
  const h = 384;
  const c = document.createElement('canvas');
  c.width = w;
  c.height = h;
  const ctx = c.getContext('2d');
  const rnd = () => {
    seed = (seed * 16807) % 2147483647;
    return (seed - 1) / 2147483646;
  };
  const bases = ['#1a100c', '#2a1410', '#0e1210', '#3a120e', '#141210'];
  ctx.fillStyle = bases[Math.floor(rnd() * bases.length)];
  ctx.fillRect(0, 0, w, h);
  ctx.fillStyle = ['#c9a227', '#b71c1c', '#6b8f71', '#d4550a'][Math.floor(rnd() * 4)];
  ctx.fillRect(0, 0, 8, h);
  ctx.save();
  ctx.translate(w * 0.62, h * 0.5);
  ctx.rotate(-Math.PI / 2);
  ctx.fillStyle = '#e8dcc8';
  ctx.font = '700 22px "Anton", Impact, sans-serif';
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';
  ctx.fillText(String(title).toUpperCase().slice(0, 16), 0, 0);
  ctx.restore();
  ctx.fillStyle = '#c9a227';
  ctx.fillRect(w * 0.2, h * 0.08, w * 0.55, 18);
  ctx.fillStyle = '#1a1208';
  ctx.font = '700 9px "IBM Plex Mono", monospace';
  ctx.textAlign = 'center';
  ctx.fillText('VHS', w * 0.48, h * 0.08 + 13);
  const tex = new THREE.CanvasTexture(c);
  tex.colorSpace = THREE.SRGBColorSpace;
  tex.anisotropy = isMobile ? 2 : 4;
  return tex;
}

/** Load real corpus posters for the shelf (site/assets/posters). */
async function loadShelfPosterTextures(needed) {
  let files = [];
  // Essay page lives at site root; standalone demo lives under demos/poster-decompose/
  const base = ESSAY_ACT ? './assets/posters/' : '../../assets/posters/';
  try {
    const man = await fetch(`${BASE}shelf-posters.json`).then((r) => r.json());
    files = Array.isArray(man.files) ? man.files : [];
  } catch (err) {
    console.warn('[poster-decompose] shelf-posters.json missing', err);
  }
  if (!files.length) return [];

  const pick = files.slice(0, Math.max(needed, 1));
  const maps = await Promise.all(
    pick.map(
      (name) =>
        loadImage(base + name)
          .then((img) => textureFromImage(img))
          .catch(() => null),
    ),
  );
  return maps.filter(Boolean);
}

/**
 * Cold-open videoclub: white gallery shelf, cover-facing boxes (ref: face-out VHS wall).
 * One bay empty — real Halloween vhsGroup sits there during aisle beat.
 */
async function buildVhsStore() {
  const g = new THREE.Group();
  g.name = 'vhsStore';

  const cols = isMobile ? 4 : 5;
  const rows = isMobile ? 4 : 5;
  const coverW = 0.84;
  const coverH = 1.24;
  const coverD = 0.1;
  const gapX = 0.05;
  const gapY = 0.065;
  const pitchX = coverW + gapX;
  const pitchY = coverH + gapY;
  const frame = 0.11;
  const shelfDepth = 0.36;
  const innerW = cols * pitchX - gapX;
  const innerH = rows * pitchY - gapY;
  const shelfW = innerW + frame * 2;
  const shelfH = innerH + frame * 2 + 0.14;

  const slotCol = Math.floor(cols / 2);
  const slotRow = Math.floor(rows * 0.5);
  const coverSlots = cols * rows - 1; // minus Halloween bay
  const shelfMaps = await loadShelfPosterTextures(coverSlots);

  // Videoclub wall + aisle carpet
  const wall = new THREE.Mesh(
    new THREE.PlaneGeometry(shelfW * 2.6, shelfH * 1.85),
    new THREE.MeshStandardMaterial({
      color: 0x3a4248,
      roughness: 0.96,
      metalness: 0.02,
      envMapIntensity: 0.08,
    }),
  );
  wall.position.set(0, 0.06, -shelfDepth * 0.5 - 0.55);
  wall.receiveShadow = true;
  g.add(wall);

  const carpet = new THREE.Mesh(
    new THREE.PlaneGeometry(shelfW * 2.2, 2.8),
    new THREE.MeshStandardMaterial({
      color: 0x1a1410,
      roughness: 0.94,
      metalness: 0.04,
    }),
  );
  carpet.rotation.x = -Math.PI / 2;
  carpet.position.set(0, -shelfH * 0.5 - 0.04, 1.05);
  carpet.receiveShadow = true;
  g.add(carpet);

  // Aged cabinet — stained cream + dirt map
  const dirtC = document.createElement('canvas');
  dirtC.width = 256;
  dirtC.height = 256;
  const dctx = dirtC.getContext('2d');
  dctx.fillStyle = '#d4ccc0';
  dctx.fillRect(0, 0, 256, 256);
  for (let i = 0; i < 900; i++) {
    const x = Math.random() * 256;
    const y = Math.random() * 256;
    const a = 0.04 + Math.random() * 0.12;
    dctx.fillStyle = `rgba(${40 + Math.random() * 40},${30 + Math.random() * 30},${20},${a})`;
    dctx.fillRect(x, y, 1 + Math.random() * 3, 1 + Math.random() * 2);
  }
  // Edge grime
  const eg = dctx.createLinearGradient(0, 0, 0, 256);
  eg.addColorStop(0, 'rgba(30,24,18,0.22)');
  eg.addColorStop(0.15, 'rgba(30,24,18,0)');
  eg.addColorStop(0.85, 'rgba(30,24,18,0)');
  eg.addColorStop(1, 'rgba(20,16,12,0.28)');
  dctx.fillStyle = eg;
  dctx.fillRect(0, 0, 256, 256);
  const dirtMap = new THREE.CanvasTexture(dirtC);
  dirtMap.wrapS = dirtMap.wrapT = THREE.RepeatWrapping;
  dirtMap.repeat.set(2.5, 2.5);
  dirtMap.colorSpace = THREE.SRGBColorSpace;

  const whiteMat = new THREE.MeshStandardMaterial({
    color: 0xcfc6b8,
    map: dirtMap,
    roughness: 0.84,
    metalness: 0.03,
    envMapIntensity: 0.22,
  });
  const backMat = new THREE.MeshStandardMaterial({
    color: 0x343c42,
    roughness: 0.97,
    metalness: 0.02,
    envMapIntensity: 0.06,
  });
  const plasticSide = new THREE.MeshStandardMaterial({
    color: 0x14110f,
    roughness: 0.82,
    metalness: 0.06,
    envMapIntensity: 0.3,
  });

  const back = new THREE.Mesh(new THREE.BoxGeometry(innerW + 0.02, innerH + 0.02, 0.05), backMat);
  back.position.set(0, 0, -shelfDepth * 0.5 + 0.025);
  back.receiveShadow = true;
  g.add(back);

  // Per-bay shadow wash on back panel
  const wash = document.createElement('canvas');
  wash.width = 512;
  wash.height = 512;
  const wctx = wash.getContext('2d');
  for (let c = 0; c < cols; c++) {
    for (let r = 0; r < rows; r++) {
      const bx = (c / cols) * 512;
      const by = (r / rows) * 512;
      const bw = 512 / cols;
      const bh = 512 / rows;
      const g2 = wctx.createRadialGradient(bx + bw * 0.5, by + bh * 0.5, 8, bx + bw * 0.5, by + bh * 0.5, bw * 0.55);
      g2.addColorStop(0, 'rgba(0,0,0,0.18)');
      g2.addColorStop(1, 'rgba(0,0,0,0.55)');
      wctx.fillStyle = g2;
      wctx.fillRect(bx, by, bw, bh);
    }
  }
  const washTex = new THREE.CanvasTexture(wash);
  washTex.colorSpace = THREE.SRGBColorSpace;
  const washPlane = new THREE.Mesh(
    new THREE.PlaneGeometry(innerW * 0.985, innerH * 0.985),
    new THREE.MeshBasicMaterial({
      map: washTex,
      transparent: true,
      opacity: 0.85,
      depthWrite: false,
    }),
  );
  washPlane.position.set(0, 0, -shelfDepth * 0.5 + 0.052);
  g.add(washPlane);

  // Outer frame (left/right/top/bottom)
  const outer = [
    { w: frame, h: shelfH, x: -shelfW * 0.5 + frame * 0.5, y: 0 },
    { w: frame, h: shelfH, x: shelfW * 0.5 - frame * 0.5, y: 0 },
    { w: shelfW, h: frame, x: 0, y: shelfH * 0.5 - frame * 0.5 },
    { w: shelfW, h: frame * 1.2, x: 0, y: -shelfH * 0.5 + frame * 0.58 },
  ];
  outer.forEach((p) => {
    const m = new THREE.Mesh(new THREE.BoxGeometry(p.w, p.h, shelfDepth), whiteMat.clone());
    m.position.set(p.x, p.y, 0);
    m.castShadow = true;
    m.receiveShadow = true;
    g.add(m);
  });

  for (let r = 0; r <= rows; r++) {
    const y = -innerH * 0.5 + r * pitchY - gapY * 0.5;
    const ledge = new THREE.Mesh(
      new THREE.BoxGeometry(innerW + 0.01, 0.038, shelfDepth - 0.06),
      whiteMat.clone(),
    );
    ledge.position.set(0, y, 0.008);
    ledge.castShadow = true;
    ledge.receiveShadow = true;
    g.add(ledge);
  }

  // Dirty fluorescent strip — sick green-amber, not gallery softbox
  const stripMat = new THREE.MeshStandardMaterial({
    color: 0xe8e0c8,
    emissive: 0xc4b060,
    emissiveIntensity: 0.85,
    roughness: 0.55,
    metalness: 0.06,
  });
  const strip = new THREE.Mesh(new THREE.BoxGeometry(innerW * 0.94, 0.028, 0.055), stripMat);
  strip.position.set(0, shelfH * 0.5 - frame * 0.32, shelfDepth * 0.26);
  g.add(strip);
  storeStrip = strip;

  // Uneven aisle wash — hot near center-left, falls off
  const fluoro = new THREE.PointLight(0xe8d8a0, 22, 12, 1.65);
  fluoro.position.set(-0.35, shelfH * 0.38, 2.35);
  g.add(fluoro);
  storeFluoroLight = fluoro;

  const fluoroB = new THREE.PointLight(0xa8b090, 9, 9, 1.8);
  fluoroB.position.set(1.1, shelfH * 0.2, 2.0);
  g.add(fluoroB);

  const soft = new THREE.DirectionalLight(0xf0e0c8, 0.55);
  soft.position.set(-0.9, 0.55, 3.1);
  soft.castShadow = !isMobile;
  if (soft.castShadow) {
    soft.shadow.mapSize.set(1024, 1024);
    soft.shadow.camera.near = 0.5;
    soft.shadow.camera.far = 14;
    soft.shadow.camera.left = -4;
    soft.shadow.camera.right = 4;
    soft.shadow.camera.top = 4;
    soft.shadow.camera.bottom = -4;
    soft.shadow.bias = -0.0002;
  }
  g.add(soft);
  storeSoftLight = soft;

  const fillL = new THREE.DirectionalLight(0x6a7888, 0.18);
  fillL.position.set(2.6, -0.1, 2.0);
  g.add(fillL);
  storeFillLight = fillL;

  const bayLight = new THREE.SpotLight(0xffb878, 16, 9, 0.26, 0.68, 1.45);
  bayLight.position.set(0.05, 0.55, 2.7);
  g.add(bayLight);
  g.add(bayLight.target);
  storeBayLight = bayLight;

  storeGodRays = null;

  const tapes = new THREE.Group();
  tapes.name = 'storeTapes';
  storeSpines = tapes;

  const titles = [
    'NIGHT SHIFT', 'BLOOD FEAST', 'CELLAR', 'REWIND', 'STATIC',
    'THE TENANT', 'GRAVE DIRT', 'AFTERDARK', 'SPLICE', 'MOTEL',
    'VAPOR', 'LONG NIGHT', 'CARVER', 'BASEMENT', 'SIGNAL',
    'RED ROOM', 'WALK-IN', 'TAPE 13', 'HUSH', 'DEAD AIR',
    'CORPUS', 'LATE FEE', 'MIDNIGHT', 'SPINE', 'MASK',
    'PUMPKIN', 'KNIFE', 'FOG', 'AISLE 7', 'RETURN',
  ];

  const originX = -((cols - 1) * pitchX) * 0.5;
  const originY = -((rows - 1) * pitchY) * 0.5;
  let seed = 94801;
  let tIdx = 0;
  let mapIdx = 0;
  const faceZ = -shelfDepth * 0.5 + coverD * 0.55 + 0.04;

  for (let r = 0; r < rows; r++) {
    for (let c = 0; c < cols; c++) {
      if (r === slotRow && c === slotCol) continue;

      const x = originX + c * pitchX;
      const y = originY + r * pitchY;
      // Sparse sideways spines (2–3) — labeled, not wood blocks
      const sideways = (r === 0 && c === cols - 1) || (r === rows - 1 && c === 0);

      const geo = sideways
        ? new THREE.BoxGeometry(coverD * 1.05, coverH * 0.98, coverW * 0.92)
        : new THREE.BoxGeometry(
            coverW * (0.985 + ((seed >> 3) % 3) * 0.008),
            coverH * (0.985 + (seed % 2) * 0.01),
            coverD,
          );

      let mat;
      if (sideways) {
        const spineMap = makeSpineLabelTexture(seed, titles[tIdx % titles.length]);
        const spineFace = new THREE.MeshStandardMaterial({
          map: spineMap,
          roughness: 0.65,
          metalness: 0.04,
          envMapIntensity: 0.3,
        });
        const side = plasticSide.clone();
        // +x is the visible spine face when box is thin in X
        mat = [spineFace, side, side.clone(), side.clone(), side.clone(), side.clone()];
      } else {
        const map =
          shelfMaps[mapIdx] ||
          makeFakeVhsCoverTexture(seed, titles[tIdx % titles.length]);
        mapIdx++;
        const front = new THREE.MeshStandardMaterial({
          map,
          roughness: 0.52,
          metalness: 0.04,
          envMapIntensity: 0.42,
          transparent: false,
          opacity: 1,
          depthWrite: true,
        });
        const side = plasticSide.clone();
        // Box face order: +x -x +y -y +z -z  → front is +z
        mat = [side, side.clone(), side.clone(), side.clone(), front, side.clone()];
      }

      const tape = new THREE.Mesh(geo, mat);
      tape.castShadow = !isMobile;
      tape.receiveShadow = true;
      const jx = (Math.random() - 0.5) * 0.01;
      const jy = (Math.random() - 0.5) * 0.006;
      const jz = sideways ? 0.012 : (Math.random() - 0.5) * 0.008;
      tape.position.set(x + jx, y + 0.01 + jy, faceZ + jz);
      if (!sideways) {
        tape.rotation.y = (Math.random() - 0.5) * 0.022;
        tape.rotation.z = (Math.random() - 0.5) * 0.008;
      } else {
        tape.rotation.y = 0;
        tape.rotation.z = (Math.random() - 0.5) * 0.02;
      }
      tapes.add(tape);
      seed = (seed * 1103515245 + 12345) & 0x7fffffff;
      tIdx++;
    }
  }
  g.add(tapes);

  // Pull-focus veil with hole at Halloween bay — dims neighbors, not the product
  {
    const hw = shelfW * 0.52;
    const hh = shelfH * 0.52;
    const holeW = coverW * 0.72;
    const holeH = coverH * 0.72;
    const shape = new THREE.Shape();
    shape.moveTo(-hw, -hh);
    shape.lineTo(hw, -hh);
    shape.lineTo(hw, hh);
    shape.lineTo(-hw, hh);
    shape.lineTo(-hw, -hh);
    const hole = new THREE.Path();
    const hx = originX + slotCol * pitchX;
    const hy = originY + slotRow * pitchY;
    // Hole winding opposite to outer shape
    hole.moveTo(hx - holeW, hy - holeH);
    hole.lineTo(hx - holeW, hy + holeH);
    hole.lineTo(hx + holeW, hy + holeH);
    hole.lineTo(hx + holeW, hy - holeH);
    hole.lineTo(hx - holeW, hy - holeH);
    shape.holes.push(hole);
    const dimPlane = new THREE.Mesh(
      new THREE.ShapeGeometry(shape),
      new THREE.MeshBasicMaterial({
        color: 0x040302,
        transparent: true,
        opacity: 0,
        depthWrite: false,
        side: THREE.DoubleSide,
      }),
    );
    dimPlane.position.set(0, 0, faceZ + 0.06);
    dimPlane.name = 'storeDim';
    dimPlane.renderOrder = 4;
    g.add(dimPlane);
    storeDimPlane = dimPlane;
  }

  const slotX = originX + slotCol * pitchX;
  const slotY = originY + slotRow * pitchY;

  const recess = new THREE.Mesh(
    new THREE.PlaneGeometry(coverW * 0.94, coverH * 0.94),
    new THREE.MeshBasicMaterial({
      color: 0x080604,
      transparent: true,
      opacity: 0,
      depthWrite: false,
    }),
  );
  recess.position.set(slotX, slotY, -shelfDepth * 0.5 + 0.06);
  recess.name = 'slotRecess';
  g.add(recess);
  storeSlotRecess = recess;

  const slotShadow = new THREE.Mesh(
    new THREE.PlaneGeometry(coverW * 1.02, coverH * 0.08),
    new THREE.MeshBasicMaterial({
      color: 0x000000,
      transparent: true,
      opacity: 0,
      depthWrite: false,
    }),
  );
  slotShadow.position.set(slotX, slotY - coverH * 0.48, faceZ - 0.02);
  slotShadow.rotation.x = -0.08;
  slotShadow.name = 'slotShadow';
  g.add(slotShadow);
  g.userData.slotShadow = slotShadow;

  g.userData.slotLocal = new THREE.Vector3(slotX, slotY, faceZ + 0.015);
  g.userData.shelfW = shelfW;
  g.userData.shelfH = shelfH;
  g.userData.spineH = coverH;
  g.userData.coverH = coverH;
  g.userData.coverW = coverW;
  g.userData.coverD = coverD;
  g.userData.shelfPosterCount = shelfMaps.length;
  bayLight.target.position.set(slotX, slotY, 0.12);

  const dn = isMobile ? 55 : 130;
  const dpos = new Float32Array(dn * 3);
  for (let i = 0; i < dn; i++) {
    dpos[i * 3] = (Math.random() - 0.5) * shelfW * 1.3;
    dpos[i * 3 + 1] = (Math.random() - 0.5) * shelfH;
    dpos[i * 3 + 2] = Math.random() * 2.2 + 0.15;
  }
  const dgeo = new THREE.BufferGeometry();
  dgeo.setAttribute('position', new THREE.BufferAttribute(dpos, 3));
  storeDust = new THREE.Points(
    dgeo,
    new THREE.PointsMaterial({
      color: 0xf2e8dc,
      size: 0.014,
      transparent: true,
      opacity: 0.1,
      depthWrite: false,
      blending: THREE.AdditiveBlending,
    }),
  );
  g.add(storeDust);

  g.position.set(isMobile ? 0.22 : 0.78, -0.04, -0.38);
  g.rotation.y = -0.04;
  g.scale.setScalar(isMobile ? 0.8 : 0.88);
  return g;
}

function updateStoreSlotWorld() {
  if (!storeGroup || !storeGroup.userData.slotLocal) return;
  storeSlotWorld.copy(storeGroup.userData.slotLocal);
  storeGroup.localToWorld(storeSlotWorld);
}

function bindScroll() {
  const onScroll = () => {
    targetProgress = getScrollProgress();
  };
  window.addEventListener('scroll', onScroll, { passive: true });
  onScroll();
}

function setLayerOpacity(key, opacity) {
  const mesh = layers[key];
  if (!mesh) return;
  mesh.material.opacity = clamp(opacity, 0, 1);
  mesh.visible = mesh.material.opacity > 0.02;
}

function worldToScreen(v3) {
  const v = v3.clone().project(camera);
  const canvas = renderer.domElement;
  const rect = canvas.getBoundingClientRect();
  // Coords relative to #overlays (fixed full-page OR absolute inside .vhs-act-pin).
  // Using raw viewport left/top double-counts the pin offset in essay mode.
  const origin = el.overlays
    ? el.overlays.getBoundingClientRect()
    : { left: 0, top: 0 };
  return {
    x: (v.x * 0.5 + 0.5) * rect.width + (rect.left - origin.left),
    y: (-v.y * 0.5 + 0.5) * rect.height + (rect.top - origin.top),
    visible: v.z > -1 && v.z < 1,
  };
}

/** UV on cover plane → world. Poster UVs are remapped through the lid crop; v grows downward. */
function coverUvToWorld(u, v, target, asMeshUv = false) {
  const cover = layers.cover;
  if (!cover) {
    target.set(0, 0, 0);
    return target;
  }
  let uu = u;
  let vv = v;
  if (!asMeshUv) {
    const uTrim = (u - posterTrim.x) / Math.max(posterTrim.w, 1e-6);
    const vTrim = (v - posterTrim.y) / Math.max(posterTrim.h, 1e-6);
    uu = coverUvCrop.offsetX + uTrim * coverUvCrop.repeatX;
    vv = coverUvCrop.offsetY + vTrim * coverUvCrop.repeatY;
  }
  uu = clamp(uu, 0, 1);
  vv = clamp(vv, 0, 1);
  const x = (uu - 0.5) * COVER_W;
  const y = (0.5 - vv) * COVER_H;
  const z = 0.025;
  return target.set(x, y, z).applyMatrix4(cover.matrixWorld);
}

function screenAabbFromUvs(uvs, asMeshUv = false) {
  let minX = Infinity;
  let minY = Infinity;
  let maxX = -Infinity;
  let maxY = -Infinity;
  const tmp = new THREE.Vector3();
  for (const [u, v] of uvs) {
    coverUvToWorld(u, v, tmp, asMeshUv);
    const s = worldToScreen(tmp);
    minX = Math.min(minX, s.x);
    minY = Math.min(minY, s.y);
    maxX = Math.max(maxX, s.x);
    maxY = Math.max(maxY, s.y);
  }
  return { left: minX, top: minY, width: Math.max(2, maxX - minX), height: Math.max(2, maxY - minY) };
}

function overlayLabelText(def) {
  return String((def && def.label) || '').trim();
}

/** True when an overlay has something worth painting (no empty shells). */
function overlayHasContent(def) {
  if (!def || !def.type) return false;
  const label = overlayLabelText(def);
  if (def.type === 'palette') {
    return (def.samples && def.samples.length > 0) || !!(def.cue && String(def.cue).trim());
  }
  if (def.type === 'diagonals') {
    return (def.lines && def.lines.length > 0) || !!label;
  }
  if (def.type === 'chip') return !!label;
  if (def.type === 'faces') {
    // Zero detections still get a dashed null-zone (story: silhouette, not face)
    return !!label;
  }
  if (def.type === 'bbox' || def.type === 'symmetry') return !!label;
  return !!label;
}

function deactivateOverlayNode(node) {
  if (!node) return;
  node.className = 'ov';
  node.style.opacity = '0';
  node.style.visibility = 'hidden';
  node.style.left = '';
  node.style.top = '';
  node.style.width = '';
  node.style.height = '';
  node.style.transform = '';
  node.style.transformOrigin = '';
  node.querySelectorAll('.ov-box, .ov-chip, .ov-label').forEach((child) => {
    child.hidden = true;
    if (child.classList.contains('ov-chip') || child.classList.contains('ov-label')) {
      child.textContent = '';
    }
  });
}

function activeOverlayDef(beatId, p) {
  if (!metricsData) return null;
  const beat = metricsData.beats.find((b) => b.id === beatId);
  if (!beat || !beat.overlay) return null;
  // Hold overlay only while this beat owns progress (no stacking)
  const [a, b] = beat.progress;
  if (p < a || p >= b) return null;
  if (!overlayHasContent(beat.overlay)) return null;
  return beat.overlay;
}

/** DOM overlay fade: copy leads briefly, then metric chrome joins early mid-beat. */
function overlayRevealAmount(beatId, p) {
  if (!metricsData) return 0;
  const beat = metricsData.beats.find((b) => b.id === beatId);
  if (!beat || !beat.overlay) return 0;
  const [a, b] = beat.progress;
  if (p < a || p >= b) return 0;
  const t = beatLocalT(beatId, p);
  // Palette handles need earlier presence so swatches ↔ cover read as one
  if (beatId === 'palette') return smoothstep(0.18, 0.42, t);
  // Symmetry axis / diagonals / blood: arrive with the title, not at section end
  if (beatId === 'symmetry' || beatId === 'diagonals' || beatId === 'blood') {
    return smoothstep(0.06, 0.28, t);
  }
  if (beatId === 'faces' || beatId === 'knife' || beatId === 'read') {
    return smoothstep(0.22, 0.45, t);
  }
  return smoothstep(0.28, 0.5, t);
}

function beatLocalT(beatId, p) {
  if (!metricsData) return 0;
  const beat = metricsData.beats.find((b) => b.id === beatId);
  if (!beat) return 0;
  const [a, b] = beat.progress;
  return clamp((p - a) / Math.max(1e-6, b - a), 0, 1);
}

/**
 * Soft crossfade for left copy: hold through overlay reveal (~0.42–0.62 localT),
 * fade only in the last ~12% / first ~10% of each beat's progress range.
 */
function beatCopyOpacity(beat, p) {
  if (ESSAY_ACT && preludeProgress < 0.999 && p < 0.01) return 0;
  const [a, bEnd] = beat.progress;
  const span = Math.max(1e-6, bEnd - a);
  const t = (p - a) / span;
  if (t <= -0.05 || t >= 1.05) return 0;
  // Hero store copy must stay solid from frame 0 — parent opacity was ghosting the panel
  if (beat.id === 'hero') {
    // Stay solid through aisle/pull; dissolve with store leave into Read
    const leave = remap(p, 0.09, 0.13);
    return clamp(1 - leave, 0, 1);
  }
  if (beat.id === 'archive') {
    // Final beat: hold copy + essay CTA visible through end of scroll
    const fadeIn = smoothstep(-0.02, 0.12, t);
    return clamp(fadeIn, 0, 1);
  }
  const fadeIn = smoothstep(-0.02, 0.1, t);
  const fadeOut = 1 - smoothstep(0.88, 1.02, t);
  return clamp(fadeIn * fadeOut, 0, 1);
}

function updateOverlays(p, beatId) {
  if (!el.overlays || !layers.cover) return;
  const tmpA = new THREE.Vector3();
  const tmpB = new THREE.Vector3();

  // Matrices must be current — overlays run before renderer.render()
  camera.updateMatrixWorld(true);
  layers.cover.updateWorldMatrix(true, false);

  const liveDef = activeOverlayDef(beatId, p);
  const overlayReveal = overlayRevealAmount(beatId, p);

  Object.keys(overlayNodes).forEach((id) => {
    const { el: node } = overlayNodes[id];
    const def = id === beatId ? liveDef : null;
    const active = !!(def && id === beatId && overlayHasContent(def));
    if (!active || !def || overlayReveal <= 0.02) {
      deactivateOverlayNode(node);
      return;
    }

    const boxEl = node.querySelector('.ov-box');
    const chipEl = node.querySelector('.ov-chip');
    const labelEl = node.querySelector('.ov-label');
    const label = overlayLabelText(def);
    node.className = `ov ov-${def.type} on`;
    node.style.opacity = String(overlayReveal);
    node.style.visibility = 'visible';
    node.style.transform = '';
    node.style.left = '';
    node.style.top = '';
    node.style.width = '';
    node.style.height = '';
    node.style.transformOrigin = '';

    // Default: hide chrome; each type opts in
    if (boxEl) boxEl.hidden = true;
    if (chipEl) {
      chipEl.hidden = true;
      chipEl.textContent = '';
    }
    if (labelEl) {
      labelEl.hidden = true;
      labelEl.textContent = '';
    }

    if (def.type === 'palette') {
      const samples = def.samples || [];
      const handles = node.querySelectorAll('.pal-handle');
      handles.forEach((h, i) => {
        const s = samples[i];
        if (!s) {
          h.style.display = 'none';
          return;
        }
        h.style.display = '';
        coverUvToWorld(s.uv[0], s.uv[1], tmpA);
        const scr = worldToScreen(tmpA);
        h.style.left = `${scr.x}px`;
        h.style.top = `${scr.y}px`;
        const ok = hexToOklch(s.hex);
        h.style.background = s.hex;
        h.style.color = ok.light ? '#0a0806' : '#f0e6d4';
      });
      // Cover AABB → cue top-right only (swatch panel is in left copy column)
      const coverBox = screenAabbFromUvs(
        [
          [0, 0],
          [1, 0],
          [0, 1],
          [1, 1],
        ],
        true,
      );
      const cue = node.querySelector('.pal-cue');
      if (cue) {
        const cueText = String(def.cue || '').trim();
        if (!cueText) {
          cue.hidden = true;
          cue.textContent = '';
        } else {
          cue.hidden = false;
          cue.textContent = cueText;
          cue.style.left = `${coverBox.left + coverBox.width - 8}px`;
          cue.style.top = `${coverBox.top + 8}px`;
          cue.style.transform = 'translateX(-100%)';
        }
      }
      return;
    }

    if (def.type === 'diagonals') {
      if (labelEl) {
        if (label) {
          labelEl.hidden = false;
          labelEl.textContent = label;
        } else {
          labelEl.hidden = true;
          labelEl.textContent = '';
        }
      }
      const lines = def.lines || [];
      const lineEls = node.querySelectorAll('.diag-line');
      // Container origin at cover top-left for label placement
      const coverBox = screenAabbFromUvs(
        [
          [0, 0],
          [1, 0],
          [0, 1],
          [1, 1],
        ],
        true,
      );
      node.style.left = `${coverBox.left}px`;
      node.style.top = `${coverBox.top}px`;
      node.style.width = `${coverBox.width}px`;
      node.style.height = `${coverBox.height}px`;
      lineEls.forEach((lineEl, i) => {
        const ln = lines[i];
        if (!ln) {
          lineEl.style.display = 'none';
          return;
        }
        lineEl.style.display = 'block';
        coverUvToWorld(ln.from[0], ln.from[1], tmpA);
        coverUvToWorld(ln.to[0], ln.to[1], tmpB);
        const a = worldToScreen(tmpA);
        const b = worldToScreen(tmpB);
        const dx = b.x - a.x;
        const dy = b.y - a.y;
        const len = Math.hypot(dx, dy) || 2;
        const angle = (Math.atan2(dy, dx) * 180) / Math.PI;
        lineEl.style.left = `${a.x - coverBox.left}px`;
        lineEl.style.top = `${a.y - coverBox.top}px`;
        lineEl.style.width = `${len}px`;
        lineEl.style.transform = `rotate(${angle}deg)`;
      });
      return;
    }

    if (def.type === 'chip') {
      if (!label || !chipEl) {
        deactivateOverlayNode(node);
        return;
      }
      chipEl.hidden = false;
      chipEl.textContent = label;
      const cu = def.uv ? def.uv[0] : 0.9;
      const cv = def.uv ? def.uv[1] : 0.14;
      coverUvToWorld(cu, cv, tmpA);
      const a = worldToScreen(tmpA);
      node.style.left = `${a.x + 10}px`;
      node.style.top = `${a.y}px`;
      node.style.width = 'auto';
      node.style.height = 'auto';
      node.style.transform = 'translateY(-50%)';
      return;
    }

    // bbox / faces / symmetry — require a label so we never paint a naked shell
    if (!label) {
      deactivateOverlayNode(node);
      return;
    }
    if (labelEl) {
      labelEl.hidden = false;
      labelEl.textContent = label;
    }

    if (def.type === 'bbox' || def.type === 'faces') {
      if (boxEl) boxEl.hidden = false;
      const nFaces =
        def.type === 'faces' && metricsData && metricsData.raw
          ? Number(metricsData.raw.faces)
          : NaN;
      if (def.type === 'faces' && Number.isFinite(nFaces) && nFaces <= 0) {
        node.classList.add('ov-faces-null');
      }
      const uv = def.uv || [0.1, 0.1, 0.3, 0.2];
      const [u0, v0, uw, vh] = uv;
      if (!(uw > 0 && vh > 0)) {
        deactivateOverlayNode(node);
        return;
      }
      const box = screenAabbFromUvs([
        [u0, v0],
        [u0 + uw, v0],
        [u0, v0 + vh],
        [u0 + uw, v0 + vh],
      ]);
      if (box.width < 4 || box.height < 4) {
        deactivateOverlayNode(node);
        return;
      }
      node.style.left = `${box.left}px`;
      node.style.top = `${box.top}px`;
      node.style.width = `${box.width}px`;
      node.style.height = `${box.height}px`;
    } else if (def.type === 'symmetry') {
      const axis = def.axis != null ? def.axis : 0.5;
      coverUvToWorld(axis, 0.06, tmpA);
      coverUvToWorld(axis, 0.94, tmpB);
      const a = worldToScreen(tmpA);
      const b = worldToScreen(tmpB);
      const dx = b.x - a.x;
      const dy = b.y - a.y;
      const len = Math.hypot(dx, dy) || 2;
      const angle = (Math.atan2(dy, dx) * 180) / Math.PI;
      node.style.left = `${a.x}px`;
      node.style.top = `${a.y}px`;
      node.style.width = `${len}px`;
      node.style.height = '2px';
      node.style.transformOrigin = '0 50%';
      node.style.transform = `rotate(${angle}deg)`;
    } else {
      deactivateOverlayNode(node);
    }
  });

  if (el.counter && metricsData) {
    const beat = metricsData.beats.find((b) => b.id === beatId);
    const raw = metricsData.raw;
    let html = '';
    const key = beat && beat.metricKey;
    if (key === 'ocr') html = `<b>OCR</b> ${(raw.ocr_conf * 100).toFixed(1)}%`;
    else if (key === 'faces')
      html = `<b>FACES</b> ${raw.faces} · <b>CRT</b> ${Number(raw.creature_score).toFixed(2)}`;
    else if (key === 'colors') html = `<b>DARK</b> ${(raw.dark_share * 100).toFixed(0)}%`;
    else if (key === 'symmetry') html = `<b>SYM</b> ${Number(raw.symmetry).toFixed(2)}`;
    else if (key === 'diagonals')
      html = `<b>DIAG</b> ${Number(raw.diagonal_score).toFixed(2)}`;
    else if (key === 'blood') html = `<b>BLOOD</b> ${Number(raw.nova_blood).toFixed(2)}`;
    else if (key === 'knife') html = `<b>KNIFE</b> ${Number(raw.nova_knife).toFixed(2)}`;
    else if (key === 'archive') {
      html = `<b>VHS</b> ${metricsData.id}`;
    }
    el.counter.innerHTML = html;
    const showCounter = html && beatLocalT(beatId, p) > 0.22;
    el.counter.style.opacity = showCounter
      ? String(smoothstep(0.22, 0.4, beatLocalT(beatId, p)))
      : '0';
  }
}

/**
 * Beat choreography (progress 0–1) — Measure compressed for cinematic rhythm:
 * 0 Store aisle + pull-out (0–0.12 · hero)
 * 1 Hero ¾ closed        (end of pull)
 * 2 Read face-on + OCR   (0.12–0.24)
 * 3 Faces / creature     (0.24–0.34)
 * 4 Palette              (0.34–0.44)
 * 5 Symmetry             (0.44–0.52)
 * 6 Diagonals            (0.52–0.58)
 * 7 Blood                (0.58–0.65)
 * 8 Knife climax         (0.65–0.76 · cover closed)
 * 9 Archive hold         (0.76–1 · closed sleeve + essay CTA)
 */
function exhibitSectionNear() {
  const section = document.getElementById('exhibit-a');
  if (!section) return false;
  const r = section.getBoundingClientRect();
  return r.bottom > 0 && r.top < window.innerHeight;
}

function updateScene(p) {
  const t = clock.elapsedTime;
  const pre = ESSAY_ACT ? preludeProgress : 0;
  const preEase = reducedMotion ? 1 : pre * pre * (3 - 2 * pre);

  // --- Cold open: aisle → pull → dissolve into studio ---
  const aisleHold = 1 - remap(p, 0.0, 0.05);
  const pullOut = remap(p, 0.035, 0.1);
  // Long dissolve — shelf melts into fog after the pull (bleeds slightly into Read)
  const storeFadeLin = 1 - remap(p, 0.075, 0.135);
  const storeFade = storeFadeLin * storeFadeLin; // ease-out: holds longer, dies soft
  // Leave burst: dust + warm flash as the aisle lets go (peaks ~0.10)
  const leaveBurst = remap(p, 0.078, 0.1) * (1 - remap(p, 0.1, 0.132));
  const sectionNear = exhibitSectionNear();
  const inStore =
    sectionNear && (storeFade > 0.015 || (ESSAY_ACT && preEase > 0.04 && p < 0.02));
  setRootClass('store-prelude', ESSAY_ACT && sectionNear && p < 0.01);
  setRootClass('store-open', inStore);
  if (ESSAY_ACT && !inStore) {
    setRootClass('store-aisle', false);
    setRootClass('store-pull', false);
    setRootClass('store-leave', false);
    setRootClass('store-prelude', false);
  } else {
    setRootClass('store-aisle', inStore && pullOut < 0.35);
    setRootClass('store-pull', inStore && pullOut >= 0.35 && leaveBurst < 0.2);
    setRootClass('store-leave', leaveBurst > 0.04);
  }

  if (storeGroup) {
    storeGroup.visible = inStore;
    const preludeStore = ESSAY_ACT && preEase > 0.04 && p < 0.01;
    const preludePull = preludeStore ? preEase * 0.08 : 0;
    // Soft-dissolve cabinet + dust burst on leave
    storeGroup.traverse((obj) => {
      if (obj.isPoints && obj.material) {
        const burst = leaveBurst * 0.6;
        obj.material.opacity = (0.12 * storeFade + burst) * (0.55 + aisleHold * 0.45);
        obj.visible = obj.material.opacity > 0.01;
        return;
      }
      if (!obj.isMesh || !obj.material) return;
      if (obj.name === 'storeDim' || obj.name === 'slotRecess' || obj.name === 'slotShadow') return;
      if (obj.parent && obj.parent.name === 'storeTapes') return; // tapes handled below
      const mats = Array.isArray(obj.material) ? obj.material : [obj.material];
      mats.forEach((m) => {
        if (m.userData._storeMat === undefined) {
          m.userData._storeMat = true;
          m.userData._baseOp = m.opacity ?? 1;
          m.userData._wasTransparent = !!m.transparent;
        }
        const fading = storeFade < 0.985;
        const nextT = fading || m.userData._wasTransparent;
        if (m.transparent !== nextT) {
          m.transparent = nextT;
          m.needsUpdate = true;
        }
        m.opacity = (m.userData._baseOp ?? 1) * storeFade;
        m.depthWrite = storeFade > 0.35;
        if ('emissiveIntensity' in m && obj.name !== 'storeDim') {
          if (m.userData._baseEmissive === undefined) {
            m.userData._baseEmissive = m.emissiveIntensity ?? 0;
          }
          // Kill strip glow with dissolve (leaveBurst only while still mostly visible)
          if (m.userData._baseEmissive > 0) {
            m.emissiveIntensity =
              m.userData._baseEmissive * storeFade * lerp(1, 0.15, pullOut) +
              leaveBurst * 0.35 * storeFade;
          }
        }
      });
    });
    if (storeSpines) {
      storeSpines.visible = storeFade > 0.02;
      const shelfFocus = Math.min(1, pullOut * 1.15) * Math.max(storeFade, 0.001);
      storeSpines.traverse((obj) => {
        if (obj.isMesh && obj.material) {
          const mats = Array.isArray(obj.material) ? obj.material : [obj.material];
          mats.forEach((m) => {
            const fading = storeFade < 0.985;
            const nextT = fading;
            if (m.transparent !== nextT) {
              m.transparent = nextT;
              m.needsUpdate = true;
            }
            m.opacity = fading ? storeFade : 1;
            m.depthWrite = !fading || storeFade > 0.4;
            if (m.color && m.userData._baseColor === undefined) {
              m.userData._baseColor = m.color.getHex();
            }
            if (m.userData._baseColor !== undefined) {
              if (!m.userData._cA) {
                m.userData._cA = new THREE.Color(m.userData._baseColor);
                m.userData._cB = new THREE.Color(0x14110e);
                m.userData._cT = new THREE.Color();
              }
              m.userData._cT.copy(m.userData._cA).lerp(m.userData._cB, shelfFocus * 0.82);
              m.color.copy(m.userData._cT);
            }
            if ('envMapIntensity' in m) {
              if (m.userData._baseEnv === undefined) m.userData._baseEnv = m.envMapIntensity ?? 0.4;
              m.envMapIntensity = m.userData._baseEnv * lerp(1, 0.15, shelfFocus);
            }
            if ('roughness' in m && m.map) {
              if (m.userData._baseRough === undefined) m.userData._baseRough = m.roughness;
              m.roughness = lerp(m.userData._baseRough, 0.92, shelfFocus);
            }
          });
        }
      });
    }
    if (storeGodRays) {
      storeGodRays.children.forEach((ray, i) => {
        const flicker = reducedMotion ? 1 : 0.85 + Math.sin(t * (2.2 + i * 0.35)) * 0.15;
        ray.material.opacity = 0.07 * storeFade * flicker;
      });
    }
    const dirtyFlick = reducedMotion
      ? 1
      : 0.82 + Math.sin(t * 5.1) * 0.08 + Math.sin(t * 17.3) * 0.06 + Math.sin(t * 31.0) * 0.03;
    if (storeFluoroLight) {
      storeFluoroLight.intensity = lerp(20, 2.5, pullOut) * storeFade * dirtyFlick;
    }
    if (storeSoftLight) {
      storeSoftLight.intensity = lerp(0.48, 0.06, pullOut) * storeFade;
    }
    if (storeFillLight) {
      storeFillLight.intensity = lerp(0.16, 0.02, pullOut) * storeFade;
    }
    if (storeStrip && storeStrip.material) {
      // Strip glow handled in cabinet traverse via emissiveIntensity
    }
    if (storeBayLight) {
      storeBayLight.intensity = (lerp(10, 42, pullOut) + leaveBurst * 22) * storeFade;
      storeBayLight.angle = lerp(0.26, 0.42, pullOut) + leaveBurst * 0.08;
    }
    if (storeDimPlane && storeDimPlane.material) {
      const dimAmt = smoothstep(0.05, 0.4, pullOut) * storeFade;
      storeDimPlane.material.opacity = dimAmt * 0.94;
      storeDimPlane.visible = storeDimPlane.material.opacity > 0.02;
    }
    if (storeSlotRecess && storeSlotRecess.material) {
      storeSlotRecess.material.opacity = pullOut * 0.85 * storeFade;
    }
    const slotSh = storeGroup && storeGroup.userData.slotShadow;
    if (slotSh && slotSh.material) {
      slotSh.material.opacity = pullOut * 0.45 * storeFade;
    }
    // Retreat into fog on leave — don't shrink-to-zero (reads as a pop)
    const baseStoreX = isMobile ? 0.22 : 0.78;
    const leavePush = (1 - storeFade) * 2.4;
    storeGroup.position.x = baseStoreX + (1 - pullOut) * Math.sin(t * 0.12) * 0.01 - preludePull * 0.04;
    storeGroup.position.y = -0.04 + aisleHold * 0.015 - leavePush * 0.08;
    storeGroup.position.z = -0.38 + aisleHold * 0.1 - pullOut * 1.15 - leavePush - preludePull * 0.12;
    storeGroup.rotation.y = lerp(-0.04, -0.16, pullOut) + preludePull * 0.03;
    const storeBaseScale = isMobile ? 0.8 : 0.88;
    storeGroup.scale.setScalar(storeBaseScale * lerp(1, 0.62, pullOut) * (1 - preludePull * 0.04));
    updateStoreSlotWorld();
  }

  if (scene.fog) {
    const pullFog = pullOut * (1 - pullOut) * 4;
    const leaveFog = leaveBurst * 3.2 + (1 - storeFade) * 1.8;
    scene.fog.density =
      lerp(baseFogDensity * 1.55, baseFogDensity, pullOut) +
      pullFog * baseFogDensity * 0.9 +
      leaveFog * baseFogDensity;
  }

  const faceOn = remap(p, 0.13, 0.22);
  // Hold face-on through knife; Archive is a closed-sleeve rest (no lid, no VCR).
  const measureZone = remap(p, 0.24, 0.74);
  const open = 0;
  const archiveHold = remap(p, 0.76, 0.9);
  const playerReveal = 0;
  const insert = 0;

  if (renderer) {
    const crtFlick =
      inStore && !reducedMotion && open < 0.02
        ? 1 + Math.sin(t * 11.0) * 0.018 * storeFade * (1 - pullOut * 0.5)
        : 1;
    const leaveFlash = open > 0.02 ? 1 : 1 + leaveBurst * 0.12;
    renderer.toneMappingExposure =
      1.42 * crtFlick * leaveFlash * lerp(0.84, 1.05, pullOut) * lerp(1, 1.02, remap(p, 0.12, 0.16)) *
      lerp(1, 0.92, open);
  }
  if (frontFillLight) {
    frontFillLight.intensity = lerp(0.28, 1.45, pullOut) + leaveBurst * 0.35;
  }
  if (interiorFillLight) {
    // Strong fill helps read closed-lid peels; Archive photo face needs calm light
    interiorFillLight.intensity = lerp(2, 14, pullOut) * lerp(1, 0.22, open);
  }
  if (keyLight) {
    keyLight.intensity = lerp(1.0, 2.35, pullOut) + leaveBurst * 0.5;
  }
  if (rimLight) {
    rimLight.intensity = lerp(6, 24, pullOut) + leaveBurst * 8;
  }

  // Soft idle motion — off once Archive holds the closed sleeve
  const breathe =
    reducedMotion || archiveHold > 0.02
      ? 0
      : Math.sin(t * 0.55) * 0.012 * pullOut;

  const heroRotY = lerp(-0.58, -0.012, faceOn) + measureZone * 0.02 + archiveHold * -0.02;
  const heroRotX = lerp(-0.08, -0.006, faceOn) + measureZone * -0.015;
  const heroRotZ = lerp(0.02, 0.0, faceOn);

  const heroPosX =
    lerp(isMobile ? 0 : 0.72, isMobile ? 0 : 0.55, faceOn) +
    measureZone * (isMobile ? 0 : 0.06);
  // Mobile: lift cover above sticky copy; Archive holds the closed sleeve
  const heroPosY =
    lerp(isMobile ? 0.14 : 0.02, isMobile ? 0.22 : 0.0, faceOn) +
    measureZone * (isMobile ? 0.08 : 0);
  const heroPosZ = lerp(0, 0.18, faceOn) - measureZone * 0.04 + archiveHold * 0.04;

  const baseScale = isMobile ? 0.52 : 0.68;
  const heroScale =
    baseScale *
    lerp(1, 0.9, faceOn) *
    lerp(1, isMobile ? 0.82 : 0.9, measureZone) *
    lerp(1, isMobile ? 1.04 : 1.08, archiveHold);

  // Shelf pose: match neighbor cover size — flatten Z so no black clamshell hole
  const coverH = (storeGroup && storeGroup.userData.coverH) || 1.28;
  const coverW = (storeGroup && storeGroup.userData.coverW) || 0.86;
  const coverD = (storeGroup && storeGroup.userData.coverD) || 0.11;
  const storeS = storeGroup ? storeGroup.scale.x : isMobile ? 0.78 : 0.92;
  const shelfSx = (coverW * storeS * 0.99) / BOX_W;
  const shelfSy = (coverH * storeS * 0.99) / BOX_H;
  // Keep real depth — flat Z + transparent print mats made black ink see-through
  const shelfSz = Math.max((coverD * storeS * 1.35) / BOX_D, 0.22);
  const shelfRotX = -0.01;
  const shelfRotY = -0.04;
  const shelfRotZ = 0.004;

  const u = pullOut;
  vhsGroup.position.set(
    lerp(storeSlotWorld.x, heroPosX, u),
    lerp(storeSlotWorld.y, heroPosY + breathe, u),
    lerp(storeSlotWorld.z, heroPosZ, u),
  );
  vhsGroup.rotation.set(
    lerp(shelfRotX, heroRotX + breathe, u),
    lerp(shelfRotY, heroRotY, u),
    lerp(shelfRotZ, heroRotZ + breathe * 0.2, u),
  );
  vhsGroup.scale.set(
    lerp(shelfSx, heroScale, u),
    lerp(shelfSy, heroScale, u),
    lerp(shelfSz, heroScale, u),
  );
  // Hide product shadow + interior while flush on shelf (reads as a cover, not a hole)
  if (contactShadow) contactShadow.visible = u > 0.35;
  if (interiorGroup) {
    interiorGroup.visible = u > 0.12;
  }

  lidPivot.rotation.y = 0;
  if (playerGroup) playerGroup.visible = false;
  const cassette = interiorGroup && interiorGroup.getObjectByName('cassette');
  if (cassette) cassette.visible = false;

  if (contactShadow) {
    contactShadow.material.opacity = lerp(0.58, 0.48, archiveHold);
    contactShadow.scale.set(1, 1, 1);
  }

  // Keep Halloween cover locked opaque through leave flash (exposure spike used to lift blacks)
  if (layers.cover && layers.cover.material) {
    layers.cover.material.transparent = false;
    layers.cover.material.opacity = 1;
    layers.cover.material.depthWrite = true;
  }

  if (dust) {
    const dustBase = lerp(0.04, 0.12, pullOut);
    dust.material.opacity = dustBase + leaveBurst * 0.28;
    dust.visible = dust.material.opacity > 0.01;
    if (!reducedMotion && leaveBurst > 0.05) {
      dust.rotation.y = t * 0.08;
      dust.position.y = leaveBurst * 0.12;
    } else {
      dust.position.y = 0;
    }
  }

  // --- Layer choreography: one metric layer at a time ---
  // Cover stays fully opaque through Read → Archive (lid never opens)
  setLayerOpacity('cover', 1);

  // Read: light OCR lift — keep sleeve readable under the scan frame
  const ocrOn = smoothstep(0.14, 0.18, p) * (1 - smoothstep(0.20, 0.24, p)) * 0.55;
  setLayerOpacity('ocr', ocrOn);

  // Each measure layer: short lead for sticky copy, then peel for most of the beat.
  // No colors peel during palette — only numbered handles + left-rail swatches.
  const peelWindows = [
    { key: 'faces', a: 0.24, b: 0.33 },
    { key: 'symmetry', a: 0.445, b: 0.515 },
    { key: 'diagonals', a: 0.525, b: 0.575 },
    { key: 'blood', a: 0.585, b: 0.645 },
  ];
  // Force palette-era peels off (OCR / faces / colors) so nothing tints the cover
  setLayerOpacity('colors', 0);
  if (layers.colors) {
    layers.colors.position.set(0, 0, layers.colors.userData.baseZ);
    layers.colors.rotation.set(0, 0, 0);
  }
  peelWindows.forEach(({ key, a, b }) => {
    const on = smoothstep(a, a + 0.02, p) * (1 - smoothstep(b - 0.015, b, p));
    // Soft scan veils — full peel used to bury sleeve art under metric tints
    const strength =
      key === 'faces' ? 0.42 : key === 'symmetry' ? 0.48 : key === 'diagonals' ? 0.28 : key === 'blood' ? 0.4 : 1;
    setLayerOpacity(key, on * strength * (1 - open));
    const mesh = layers[key];
    if (!mesh) return;
    const lift = on * (key === 'faces' || key === 'diagonals' ? 0.012 : 0.022);
    mesh.position.x = 0;
    mesh.position.y = lift * 0.02;
    mesh.position.z = mesh.userData.baseZ + lift;
    mesh.rotation.z = 0;
    mesh.rotation.y = 0;
  });

  // Soft residual tint during knife climax (cover still closed)
  if (p >= 0.65 && p < 0.76) {
    setLayerOpacity('blood', smoothstep(0.65, 0.69, p) * (1 - smoothstep(0.72, 0.76, p)) * 0.22);
    if (layers.blood) {
      layers.blood.position.set(0, 0, layers.blood.userData.baseZ + 0.01);
      layers.blood.rotation.set(0, 0, 0);
    }
  } else if (p >= 0.76) {
    setLayerOpacity('blood', 0);
  }

  // Keep cover on the lid — no fly-away / no fan
  if (layers.cover) {
    layers.cover.position.set(0, 0, layers.cover.userData.baseZ);
    layers.cover.rotation.set(0, 0, 0);
  }

  // Aisle camera → closed-sleeve hold in Archive
  const aisleCamZ = lerp(isMobile ? 5.05 : 5.55, isMobile ? 3.85 : 4.05, preEase);
  const aisleCamX = lerp(isMobile ? -0.42 : -0.52, isMobile ? -0.28 : -0.08, preEase);
  const aisleFov = lerp(isMobile ? 32 : 33, 28, preEase);
  const camZ = lerp(
    aisleCamZ,
    lerp(8.4, 7.2, faceOn) - measureZone * 0.05 - archiveHold * 0.22,
    pullOut,
  );
  const camX =
    lerp(aisleCamX, lerp(0.18, 0.08, faceOn), pullOut) +
    (reducedMotion || pullOut < 0.2 || archiveHold > 0.02 ? 0 : Math.sin(t * 0.08) * 0.008);
  const camY =
    lerp(-0.06, 0.04, pullOut) +
    lerp(-0.04, -0.02, preEase) +
    (reducedMotion || pullOut < 0.2 || archiveHold > 0.02 ? 0 : Math.cos(t * 0.07) * 0.006);
  camera.position.set(camX, camY, camZ);
  const lookX = lerp(storeSlotWorld.x * 0.62, vhsGroup.position.x * 0.35, pullOut);
  const lookY = lerp(storeSlotWorld.y * 0.06, vhsGroup.position.y * 0.08, pullOut);
  const lookZ = lerp(storeSlotWorld.z * 0.12, 0, pullOut);
  camera.lookAt(lookX, lookY, lookZ);
  camera.fov = lerp(aisleFov, 26, pullOut);
  camera.updateProjectionMatrix();
  camera.updateMatrixWorld(true);

  // Steady studio lights in Archive — no pulse on the photo albedo
  if (keyLight) {
    keyLight.intensity = lerp(lerp(1.0, 2.25, pullOut), 2.15, archiveHold);
  }
  if (rimLight) {
    const rimProduct = lerp(22, 18, faceOn);
    rimLight.intensity =
      lerp(5, rimProduct, pullOut) + (archiveHold > 0.02 ? 0 : leaveBurst * 8);
  }
  if (rimCoolLight) {
    rimCoolLight.intensity = lerp(2, lerp(8, 12, faceOn), pullOut);
  }

  if (el.bar) el.bar.style.width = `${(p * 100).toFixed(1)}%`;
  updateActiveBeat(p, insert);
}

function updateActiveBeat(p, insert = 0) {
  if (!metricsData) return;
  let idx = 0;
  metricsData.beats.forEach((b, i) => {
    const [a, bEnd] = b.progress;
    if (p >= a && p < bEnd) idx = i;
    if (p >= 0.999 && i === metricsData.beats.length - 1) idx = i;
  });

  beatEls.forEach((sec, i) => {
    const beat = metricsData.beats[i];
    const op = beatCopyOpacity(beat, p);
    const inner = sec.querySelector('.beat-inner');
    if (inner) inner.style.opacity = String(op);
    sec.classList.toggle('active', i === idx);
  });

  if (idx !== activeBeat) {
    activeBeat = idx;
    const beat = metricsData.beats[idx];
    if (el.beatLabel) {
      el.beatLabel.textContent = `${tDemo('chrome.track') || 'TRACK'} ${String(idx + 1).padStart(2, '0')} · ${beat.kicker}`;
    }
    if (el.actLabel && !ESSAY_ACT) {
      const act = metricsData.acts && metricsData.acts[beat.act - 1];
      el.actLabel.textContent = act ? act.label : `${tDemo('chrome.act_prefix')} ${beat.act}`;
    }
    if (el.tapeStamp) {
      el.tapeStamp.textContent = `${metricsData.title} · ${metricsData.year}`;
    }
  }
  const beat = metricsData.beats[activeBeat];
  setRootClass('beat-palette', isMobile && beat && beat.id === 'palette');
  setRootClass(
    'beat-measure',
    isMobile && beat && ['diagonals', 'blood', 'knife'].includes(beat.id),
  );
  updateOverlays(p, beat ? beat.id : null);
  updateEssayOutro(p, beat, insert);
}

function updateEssayOutro(p, beat, insert = 0) {
  if (!el.essayOutro) return;
  let show = false;
  if (beat && beat.id === 'archive') {
    show = beatLocalT('archive', p) >= 0.18 || p >= 0.82;
  }
  setRootClass('essay-outro-visible', show);
  el.essayOutro.hidden = !show;
  el.essayOutro.setAttribute('aria-hidden', show ? 'false' : 'true');
  if (show && IS_EMBED) postToParent('demo:outro-visible');
}

function tick() {
  const dt = Math.min(clock.getDelta(), 0.05);
  if (typeof window.__demoForceP === 'number') {
    targetProgress = clamp(window.__demoForceP, 0, 1);
    scrollProgress = targetProgress;
  } else {
    const lag = reducedMotion ? 1 : isMobile ? 0.16 : 0.075;
    scrollProgress = lerp(scrollProgress, targetProgress, 1 - Math.pow(1 - lag, dt * 60));
  }
  updateScene(scrollProgress);
  if (dust) dust.rotation.y = clock.elapsedTime * 0.022;
  if (storeDust) storeDust.rotation.y = clock.elapsedTime * -0.01;
  if (ESSAY_ACT && !actInView) return;
  renderer.render(scene, camera);
}

function onResize() {
  if (!camera || !renderer) return;
  const { w: vw, h: vh } = viewportSize();
  camera.aspect = vw / vh;
  camera.updateProjectionMatrix();
  renderer.setSize(vw, vh);
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, isMobile ? 1.25 : 2));
  targetProgress = getScrollProgress();
  scrollProgress = targetProgress;
}

function onBootError(err) {
  console.error(err);
  const msg = err && (err.message || String(err));
  const errTitle = tDemo('chrome.error_title') || 'No se pudo cargar la demo.';
  const errHint = tDemo('chrome.error_hint') || 'cd site && python3 -m http.server 8765';
  if (!el.loader) return;
  el.loader.innerHTML = `<p style="color:#b71c1c;max-width:32rem;text-align:center;line-height:1.6">
    ${escapeHtml(errTitle)}<br>
    <code style="color:#c9a227;font-size:10px;letter-spacing:.04em;text-transform:none">${escapeHtml(msg)}</code><br><br>
    <code style="color:#8a7f6e;font-size:10px">${escapeHtml(errHint)}</code>
  </p>`;
}

let bootStarted = false;

function startBoot() {
  if (bootStarted) return;
  bootStarted = true;
  boot().catch(onBootError);
}

function nearVhsAct(el, margin = 320) {
  if (!el) return false;
  const r = el.getBoundingClientRect();
  return r.bottom > -margin && r.top < window.innerHeight + margin;
}

function alignExhibitHash() {
  if (!ESSAY_ACT || location.hash !== '#exhibit-a') return;
  const section = document.getElementById('exhibit-a');
  if (!section) return;
  const align = () => window.scrollTo({ top: section.offsetTop, left: 0, behavior: 'auto' });
  align();
  requestAnimationFrame(align);
}

function scheduleBoot() {
  if (!el.stage || !el.track) return;
  if (!ESSAY_ACT) {
    startBoot();
    return;
  }
  const root = document.getElementById('exhibit-a') || document.getElementById('vhs-act-root');
  if (!root) return;

  const io = new IntersectionObserver(
    ([e]) => {
      if (e.isIntersecting) {
        io.disconnect();
        startBoot();
      }
    },
    { rootMargin: '640px 0px', threshold: 0 },
  );
  io.observe(root);

  // Hash jumps / late layout: IO initial callback can miss the first paint
  const kick = () => {
    if (bootStarted) return;
    if (nearVhsAct(root, 640)) {
      io.disconnect();
      startBoot();
    }
  };
  requestAnimationFrame(() => requestAnimationFrame(kick));
  window.addEventListener('hashchange', kick);
  // Hard fallback — never leave the loader hanging if the user is reading nearby
  setTimeout(() => {
    if (bootStarted) return;
    if (nearVhsAct(root, 960)) {
      io.disconnect();
      startBoot();
    }
  }, 1800);
  // Absolute last resort after 5s if still on the essay (prefetch before they arrive)
  setTimeout(() => {
    if (!bootStarted) {
      io.disconnect();
      startBoot();
    }
  }, 5000);
}

/** Essay lazy entry (src/main.js) and standalone demo page both call this. */
export function initPosterDecompose() {
  scheduleBoot();
  alignExhibitHash();
  window.addEventListener('hashchange', alignExhibitHash);
}

if (document.body.classList.contains('demo-page')) {
  initPosterDecompose();
}

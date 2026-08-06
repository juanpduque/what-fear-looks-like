/**
 * VHS Decompose — Halloween (948) · teachable cloud pass
 * Cover = poster.jpg (flat corpus art). Never map VHS box photos as albedo.
 * Beats: Hero → OCR → Faces → Palette → Symmetry → Diagonals → Blood → Knife → Archive.
 */
import * as THREE from 'three';
import { GLTFLoader } from './GLTFLoader.js';

const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
const isMobile =
  window.matchMedia('(max-width: 720px)').matches ||
  (navigator.maxTouchPoints > 0 && window.innerWidth < 900);

/** Box geometry — COVER aspect comes from loaded poster.jpg (not hardcoded). */
let BOX_H = 3.32;
let BEZEL = 0.055;
let COVER_H = BOX_H - BEZEL * 2;
let COVER_W = COVER_H * (2 / 3);
let BOX_W = COVER_W + BEZEL * 2;
const BOX_D = 0.54;
const WALL = 0.052;

const el = {
  stage: document.getElementById('stage'),
  track: document.getElementById('scroll-track'),
  bar: document.getElementById('bar'),
  beatLabel: document.getElementById('beat-label'),
  actLabel: document.getElementById('act-label'),
  tapeStamp: document.getElementById('tape-stamp'),
  loader: document.getElementById('loader'),
  btnTop: document.getElementById('btn-top'),
  btnMute: document.getElementById('btn-mute'),
  overlays: document.getElementById('overlays'),
  counter: document.getElementById('metric-counter'),
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
let keyLight, rimLight;
let scrollProgress = 0;
let targetProgress = 0;
let plasticNoiseMap = null;
let audioCtl = null;
let coverAnchor = null;
let overlayNodes = {};

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

function setCoverAspect(aspect) {
  posterAspect = aspect;
  BOX_H = 3.32;
  BEZEL = 0.055;
  COVER_H = BOX_H - BEZEL * 2;
  COVER_W = COVER_H * posterAspect;
  BOX_W = COVER_W + BEZEL * 2;
}

async function boot() {
  metricsData = await fetch('./metrics.json').then((r) => r.json());
  buildScrollBeats(metricsData);
  buildOverlayDom(metricsData);
  await initThree();
  initAudioStub();
  bindScroll();
  el.loader.classList.add('hide');
  el.btnTop.addEventListener('click', () => {
    window.scrollTo({ top: 0, behavior: reducedMotion ? 'auto' : 'smooth' });
  });
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
    const hold = 1.15 + span * 2.4; // ~1.7–1.85vh typical; longer beats get more scroll
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
    const actTag = `<div class="beat-act">Acto ${['', 'I', 'II', 'III', 'IV'][beat.act] || beat.act}</div>`;
    section.innerHTML = `
      <div class="beat-inner">
        ${actTag}
        <div class="beat-kicker">${escapeHtml(beat.kicker)}</div>
        <h2 class="beat-title">${escapeHtml(beat.title)}</h2>
        <p class="beat-body">${escapeHtml(beat.body)}</p>
        ${palettePanel}
        ${swatches}
        ${cue}
      </div>
    `;
    el.track.appendChild(section);
    return section;
  });
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
  return loadImage('./poster.jpg');
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
  ctx.font = '700 48px "Bebas Neue", Impact, sans-serif';
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

  ctx.strokeStyle = 'rgba(201,162,39,.35)';
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
  ctx.font = '700 40px "Bebas Neue", Impact, sans-serif';
  ctx.textAlign = 'center';
  ctx.fillText('R', 82, 102);
  ctx.font = '9px "IBM Plex Mono", monospace';
  ctx.fillText('RESTRICTED', 82, 122);
  ctx.textAlign = 'left';

  ctx.fillStyle = '#b71c1c';
  ctx.font = '700 16px "IBM Plex Mono", monospace';
  ctx.fillText('WARNING', 136, 68);
  ctx.fillStyle = '#e8dcc8';
  ctx.font = '24px "Special Elite", serif';
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
  ctx.font = '700 34px "Bebas Neue", Impact, sans-serif';
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
  const srcW = img.naturalWidth || img.width;
  const srcH = img.naturalHeight || img.height;
  const scale = Math.min(1, 1024 / Math.max(srcW, srcH));
  const w = Math.round(srcW * scale);
  const h = Math.round(srcH * scale);
  const c = document.createElement('canvas');
  c.width = w;
  c.height = h;
  const ctx = c.getContext('2d');
  ctx.imageSmoothingEnabled = true;
  ctx.imageSmoothingQuality = 'high';
  ctx.drawImage(img, 0, 0, w, h);

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
      // Theatrical poster title sits near bottom
      const inTitle = y > h * 0.78 && y < h * 0.96;
      const f = inTitle ? 1.12 : 0.22;
      d[i] *= f;
      d[i + 1] *= f;
      d[i + 2] *= f;
      d[i + 3] = inTitle ? 230 : 85;
    }
    ctx.putImageData(imageData, 0, 0);
  } else if (mode === 'faces') {
    for (let i = 0; i < d.length; i += 4) {
      const r = d[i];
      const g = d[i + 1];
      const b = d[i + 2];
      const lum = 0.2126 * r + 0.7152 * g + 0.0722 * b;
      const edge = lum > 35 && lum < 190 ? 1 : 0;
      d[i] = edge ? 35 : lum * 0.1;
      d[i + 1] = edge ? 190 : lum * 0.16;
      d[i + 2] = edge ? 145 : lum * 0.2;
      d[i + 3] = edge ? 200 : 55;
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
    const copy = new Uint8ClampedArray(d);
    for (let y = 0; y < h; y++) {
      for (let x = 0; x < w; x++) {
        const i = (y * w + x) * 4;
        if (x > w / 2) {
          const mx = w - 1 - x;
          const mi = (y * w + mx) * 4;
          d[i] = Math.min(255, copy[mi] * 0.42 + 95);
          d[i + 1] = Math.min(255, copy[mi + 1] * 0.42 + 65);
          d[i + 2] = Math.min(255, copy[mi + 2] * 0.32 + 28);
          d[i + 3] = 175;
        } else {
          d[i + 3] = 205;
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
      d[i] = Math.min(255, r * 0.28 + heat * 255);
      d[i + 1] = g * 0.1 + heat * 40;
      d[i + 2] = b * 0.06;
      d[i + 3] = 40 + heat * 200;
    }
    ctx.putImageData(imageData, 0, 0);
  } else if (mode === 'diagonals') {
    // Dim cover + draw X guides (visual for diagonal_score)
    for (let i = 0; i < d.length; i += 4) {
      d[i] = d[i] * 0.35;
      d[i + 1] = d[i + 1] * 0.32;
      d[i + 2] = d[i + 2] * 0.28;
      d[i + 3] = 160;
    }
    ctx.putImageData(imageData, 0, 0);
    ctx.strokeStyle = 'rgba(201,162,39,0.85)';
    ctx.lineWidth = Math.max(2, w * 0.006);
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

  const tex = new THREE.CanvasTexture(c);
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
    toneMapped: false,
  });
}

function makePrintMat(map) {
  return new THREE.MeshStandardMaterial({
    map,
    roughness: 0.68,
    metalness: 0.04,
    roughnessMap: plasticNoiseMap,
    envMapIntensity: 0.4,
    transparent: true,
    opacity: 1,
  });
}

function buildBaseShell(spineTex, backTex, topTex) {
  const g = new THREE.Group();
  g.name = 'baseShell';

  const plastic = makePlasticMat(0x15120f);
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

  const spineW = WALL * 1.2;
  const spineWall = new THREE.Mesh(new THREE.BoxGeometry(spineW, BOX_H, BOX_D), plastic.clone());
  spineWall.position.set(-BOX_W / 2 + spineW / 2, 0, 0);
  spineWall.castShadow = true;
  g.add(spineWall);
  const spinePrint = new THREE.Mesh(new THREE.PlaneGeometry(BOX_D * 0.96, BOX_H * 0.975), spineMat);
  spinePrint.position.set(-BOX_W / 2 - 0.0015, 0, 0);
  spinePrint.rotation.y = -Math.PI / 2;
  g.add(spinePrint);

  const right = new THREE.Mesh(new THREE.BoxGeometry(WALL, BOX_H, BOX_D), makePlasticMat(0x1c1814));
  right.position.set(BOX_W / 2 - WALL / 2, 0, 0);
  right.castShadow = true;
  g.add(right);

  const topWall = new THREE.Mesh(
    new THREE.BoxGeometry(BOX_W - WALL * 2, WALL, BOX_D),
    plastic.clone(),
  );
  topWall.position.set(0, BOX_H / 2 - WALL / 2, 0);
  g.add(topWall);
  const topPrint = new THREE.Mesh(new THREE.PlaneGeometry(BOX_W * 0.9, BOX_D * 0.9), topMat);
  topPrint.position.set(0, BOX_H / 2 + 0.0015, 0);
  topPrint.rotation.x = -Math.PI / 2;
  g.add(topPrint);

  const bottom = new THREE.Mesh(
    new THREE.BoxGeometry(BOX_W - WALL * 2, WALL, BOX_D),
    makePlasticMat(0x100e0c, { roughness: 0.9 }),
  );
  bottom.position.set(0, -BOX_H / 2 + WALL / 2, 0);
  bottom.receiveShadow = true;
  g.add(bottom);

  const liner = new THREE.Mesh(
    new THREE.BoxGeometry(BOX_W - WALL * 2.2, BOX_H - WALL * 2.2, 0.02),
    makePlasticMat(0x080705, { roughness: 0.95, envMapIntensity: 0.2 }),
  );
  liner.position.z = -BOX_D / 2 + WALL + 0.03;
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
  const bezelDepth = 0.028;
  const bezelZ = BOX_D / 2 - bezelDepth / 2;
  const bezelMat = makePlasticMat(0x161210, { roughness: 0.72, envMapIntensity: 0.7 });

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

function makeCassetteShellTex() {
  return makeCanvasTexture((ctx, cw, ch) => {
    ctx.fillStyle = '#161412';
    ctx.fillRect(0, 0, cw, ch);
    // Fine stipple / cross-hatch like matte VHS plastic
    for (let i = 0; i < 9000; i++) {
      const x = Math.random() * cw;
      const y = Math.random() * ch;
      const v = 14 + Math.random() * 28;
      ctx.fillStyle = `rgb(${v},${v - 1},${v - 2})`;
      ctx.fillRect(x, y, 1.2, 1.2);
    }
    for (let y = 0; y < ch; y += 3) {
      ctx.fillStyle = `rgba(0,0,0,${0.04 + (y % 6 === 0 ? 0.03 : 0)})`;
      ctx.fillRect(0, y, cw, 1);
    }
    // Soft edge vignette so the face reads as a raised panel
    const g = ctx.createRadialGradient(cw / 2, ch / 2, ch * 0.2, cw / 2, ch / 2, ch * 0.72);
    g.addColorStop(0, 'rgba(40,36,32,0)');
    g.addColorStop(1, 'rgba(0,0,0,0.35)');
    ctx.fillStyle = g;
    ctx.fillRect(0, 0, cw, ch);
  }, 512, 288);
}

function makeCassetteLabelTex() {
  return makeCanvasTexture((ctx, cw, ch) => {
    ctx.fillStyle = '#0a0a0a';
    ctx.fillRect(0, 0, cw, ch);
    // Paper grain
    for (let i = 0; i < 1200; i++) {
      const n = 8 + Math.random() * 18;
      ctx.fillStyle = `rgba(${n},${n},${n},0.5)`;
      ctx.fillRect(Math.random() * cw, Math.random() * ch, 1.5, 1.5);
    }
    // Vertical tracking cue (left)
    ctx.save();
    ctx.translate(22, ch / 2);
    ctx.rotate(-Math.PI / 2);
    ctx.fillStyle = '#d8d4cc';
    ctx.font = '600 11px "IBM Plex Mono", monospace';
    ctx.textAlign = 'center';
    ctx.fillText('FOR CLEANER PICTURE, ADJUST TRACKING', 0, 0);
    ctx.restore();

    ctx.fillStyle = '#f2eee6';
    ctx.font = '700 36px "Bebas Neue", Impact, sans-serif';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillText('HALLOWEEN', cw * 0.55, ch * 0.28);
    ctx.font = '600 18px "Bebas Neue", Impact, sans-serif';
    ctx.fillStyle = '#e4e0d8';
    ctx.fillText('SPECIAL EDITION', cw * 0.55, ch * 0.48);

    ctx.fillStyle = '#b8b0a4';
    ctx.font = '12px "IBM Plex Mono", monospace';
    ctx.fillText('Cat. No. SV10272  ·  1978', cw * 0.55, ch * 0.68);

    // Tiny legal lines
    ctx.fillStyle = '#6a6660';
    ctx.font = '7px "IBM Plex Mono", monospace';
    [
      'Licensed for private home exhibition only.',
      'All rights reserved. Unauthorized duplication prohibited.',
    ].forEach((line, i) => ctx.fillText(line, cw * 0.55, ch * 0.82 + i * 10));
  }, 512, 320);
}

function makeCassetteFlapTex() {
  return makeCanvasTexture((ctx, cw, ch) => {
    ctx.fillStyle = '#12100e';
    ctx.fillRect(0, 0, cw, ch);
    for (let i = 0; i < 2000; i++) {
      const v = 16 + Math.random() * 22;
      ctx.fillStyle = `rgb(${v},${v - 1},${v - 2})`;
      ctx.fillRect(Math.random() * cw, Math.random() * ch, 1, 1);
    }
    // Embossed cue text
    ctx.fillStyle = 'rgba(55,52,48,0.95)';
    ctx.font = '600 22px "IBM Plex Mono", monospace';
    ctx.textAlign = 'left';
    ctx.textBaseline = 'middle';
    ctx.fillText('→  insert this side into recorder', 28, ch * 0.38);
    ctx.font = '14px "IBM Plex Mono", monospace';
    ctx.fillStyle = 'rgba(48,45,42,0.9)';
    ctx.fillText('do not touch the tape inside', 48, ch * 0.68);

    // VHS badge
    ctx.strokeStyle = 'rgba(70,66,60,0.95)';
    ctx.lineWidth = 2;
    ctx.strokeRect(cw - 110, ch * 0.28, 78, ch * 0.44);
    ctx.fillStyle = 'rgba(72,68,62,0.95)';
    ctx.font = '700 26px "Bebas Neue", Impact, sans-serif';
    ctx.textAlign = 'center';
    ctx.fillText('VHS', cw - 71, ch * 0.55);
  }, 768, 128);
}

function buildCassetteMesh() {
  // Classic VHS ~187 × 103 × 25 mm — landscape in open clamshell, label toward +Z (out).
  // Group is rotated 180° about Z at placement so the door/flap edge matches the tray.
  const casW = (BOX_W - WALL * 2.5) * 0.93;
  const casH = casW * (103 / 187);
  const casD = Math.min(0.195, casW * 0.115);
  const frontZ = casD / 2;
  const eps = 0.004;

  const cassette = new THREE.Group();
  cassette.name = 'cassette';
  cassette.userData.casH = casH;
  cassette.userData.baseZ = -BOX_D / 2 + WALL + casD / 2 + 0.025;
  cassette.userData.baseRotZ = Math.PI;

  const shellMap = makeCassetteShellTex();
  const shellMat = new THREE.MeshStandardMaterial({
    color: 0x1a1816,
    map: shellMap,
    roughness: 0.92,
    metalness: 0.04,
    roughnessMap: plasticNoiseMap,
    envMapIntensity: 0.55,
  });
  const darkWellMat = makePlasticMat(0x050504, { roughness: 0.96, envMapIntensity: 0.15 });
  const seamMat = makePlasticMat(0x0a0908, { roughness: 0.7, metalness: 0.08, envMapIntensity: 0.4 });

  // Main body — thick shell with stippled matte faces
  const shell = new THREE.Mesh(new THREE.BoxGeometry(casW, casH, casD), shellMat);
  shell.castShadow = true;
  shell.receiveShadow = true;
  cassette.add(shell);

  // Side panels slightly darker so the shell reads as assembled halves
  const sideSkin = makePlasticMat(0x10100e, { roughness: 0.9, envMapIntensity: 0.45 });
  sideSkin.polygonOffset = true;
  sideSkin.polygonOffsetFactor = -1;
  sideSkin.polygonOffsetUnits = -1;
  [-1, 1].forEach((side) => {
    const panel = new THREE.Mesh(
      new THREE.PlaneGeometry(casD * 0.96, casH * 0.96),
      sideSkin,
    );
    panel.rotation.y = side > 0 ? Math.PI / 2 : -Math.PI / 2;
    panel.position.x = side * (casW / 2 + eps);
    cassette.add(panel);
  });

  // Bevel lip around front face
  const lipMat = makePlasticMat(0x22201c, { roughness: 0.72, envMapIntensity: 0.65 });
  const lipT = 0.022;
  const lipZ = frontZ + eps;
  [
    { w: casW, h: lipT, x: 0, y: casH / 2 - lipT / 2 },
    { w: casW, h: lipT, x: 0, y: -casH / 2 + lipT / 2 },
    { w: lipT, h: casH - lipT * 2, x: -casW / 2 + lipT / 2, y: 0 },
    { w: lipT, h: casH - lipT * 2, x: casW / 2 - lipT / 2, y: 0 },
  ].forEach((p) => {
    const m = new THREE.Mesh(new THREE.BoxGeometry(p.w, p.h, 0.01), lipMat);
    m.position.set(p.x, p.y, lipZ);
    cassette.add(m);
  });

  // Mid-shell seam (two halves) — inset so it never coplanar-fights the shell faces
  const seam = new THREE.Mesh(
    new THREE.BoxGeometry(casW * 0.998, casH * 0.998, 0.006),
    seamMat,
  );
  cassette.add(seam);

  // --- Window + label layout: reel | label | reel (classic VHS face) ---
  const winR = casH * 0.235;
  const reelSep = casW * 0.31;
  const winY = casH * 0.08;
  const labelW = casW * 0.26;
  const labelH = casH * 0.48;

  // Recessed label well — sunk clearly below the shell face
  const labelWell = new THREE.Mesh(
    new THREE.BoxGeometry(labelW + 0.03, labelH + 0.03, 0.028),
    darkWellMat,
  );
  labelWell.position.set(0, winY, frontZ - 0.016);
  cassette.add(labelWell);

  const labelTex = makeCassetteLabelTex();
  const label = new THREE.Mesh(
    new THREE.PlaneGeometry(labelW, labelH),
    new THREE.MeshStandardMaterial({
      map: labelTex,
      roughness: 0.78,
      metalness: 0.0,
      envMapIntensity: 0.25,
      polygonOffset: true,
      polygonOffsetFactor: -1,
      polygonOffsetUnits: -1,
    }),
  );
  label.position.set(0, winY, frontZ + eps * 2);
  cassette.add(label);

  // White hub + dark magnetic tape packs (one fuller) — matte to avoid breathe shimmer
  const hubWhite = makePlasticMat(0xe8e4dc, {
    roughness: 0.62,
    metalness: 0.04,
    envMapIntensity: 0.35,
  });
  const hubCore = makePlasticMat(0xc8c2b6, { roughness: 0.55, metalness: 0.06, envMapIntensity: 0.3 });
  const tapeMat = new THREE.MeshStandardMaterial({
    color: 0x1a1816,
    roughness: 0.55,
    metalness: 0.08,
    envMapIntensity: 0.35,
  });
  const tapeMatDeep = new THREE.MeshStandardMaterial({
    color: 0x0c0b0a,
    roughness: 0.5,
    metalness: 0.1,
    envMapIntensity: 0.4,
  });
  // Opaque tinted window — transparent glass + DoubleSide caused sorting flicker
  const glassMat = new THREE.MeshStandardMaterial({
    color: 0x1a2830,
    roughness: 0.22,
    metalness: 0.05,
    envMapIntensity: 0.45,
    transparent: false,
    opacity: 1,
  });

  const segs = isMobile ? 20 : 36;

  function addReelWindow(side, fullness) {
    const x = side * reelSep;
    const g = new THREE.Group();
    g.position.set(x, winY, 0);

    // Circular well recess (sits in the front face)
    const well = new THREE.Mesh(
      new THREE.CylinderGeometry(winR + 0.02, winR + 0.016, 0.036, segs),
      darkWellMat,
    );
    well.rotation.x = Math.PI / 2;
    well.position.z = frontZ - 0.006;
    g.add(well);

    // Inner cavity floor
    const floor = new THREE.Mesh(
      new THREE.CircleGeometry(winR + 0.008, segs),
      makePlasticMat(0x080706, { roughness: 0.9 }),
    );
    floor.position.z = frontZ - 0.02;
    g.add(floor);

    // Wound magnetic tape disk
    const tapeOuter = winR * (0.4 + fullness * 0.52);
    const tapeInner = winR * 0.2;

    // White spool flange (more visible when tape is low)
    const flange = new THREE.Mesh(
      new THREE.CylinderGeometry(winR * 0.55, winR * 0.55, 0.01, segs),
      hubWhite,
    );
    flange.rotation.x = Math.PI / 2;
    flange.position.z = frontZ - 0.014;
    g.add(flange);

    const tape = new THREE.Mesh(
      new THREE.CylinderGeometry(tapeOuter, tapeOuter, 0.028, segs),
      fullness > 0.55 ? tapeMatDeep : tapeMat,
    );
    tape.rotation.x = Math.PI / 2;
    tape.position.z = frontZ - 0.008;
    tape.castShadow = true;
    g.add(tape);

    // Concentric tape rings for wind — kept below glass, clear of coplanar faces
    for (let i = 0; i < 3; i++) {
      const t = i / 3;
      const r = tapeInner + (tapeOuter - tapeInner) * (0.35 + t * 0.55);
      if (r >= tapeOuter * 0.98) continue;
      const ring = new THREE.Mesh(
        new THREE.TorusGeometry(r, 0.0035, 6, segs),
        i % 2 ? tapeMat : tapeMatDeep,
      );
      ring.position.z = frontZ - 0.002 - i * 0.0015;
      g.add(ring);
    }

    // White reel hub with gear teeth
    const hubR = winR * 0.2;
    const hub = new THREE.Mesh(
      new THREE.CylinderGeometry(hubR, hubR, 0.036, 16),
      hubWhite,
    );
    hub.rotation.x = Math.PI / 2;
    hub.position.z = frontZ + 0.002;
    hub.castShadow = true;
    g.add(hub);

    const core = new THREE.Mesh(
      new THREE.CylinderGeometry(hubR * 0.35, hubR * 0.35, 0.04, 10),
      hubCore,
    );
    core.rotation.x = Math.PI / 2;
    core.position.z = frontZ + 0.006;
    g.add(core);

    // Drive teeth around hub
    const toothN = 8;
    for (let i = 0; i < toothN; i++) {
      const a = (i / toothN) * Math.PI * 2;
      const tooth = new THREE.Mesh(
        new THREE.BoxGeometry(hubR * 0.28, hubR * 0.55, 0.012),
        hubWhite,
      );
      tooth.position.set(
        Math.cos(a) * hubR * 0.72,
        Math.sin(a) * hubR * 0.72,
        frontZ + 0.01,
      );
      tooth.rotation.z = a;
      g.add(tooth);
    }

    // Spoke webs
    for (let i = 0; i < 6; i++) {
      const a = (i / 6) * Math.PI * 2 + 0.2;
      const spoke = new THREE.Mesh(
        new THREE.BoxGeometry(hubR * 0.16, hubR * 1.1, 0.008),
        hubCore,
      );
      spoke.position.set(
        Math.cos(a) * hubR * 0.45,
        Math.sin(a) * hubR * 0.45,
        frontZ + 0.012,
      );
      spoke.rotation.z = a;
      g.add(spoke);
    }

    // Window frame lip (ring)
    const rim = new THREE.Mesh(
      new THREE.TorusGeometry(winR + 0.012, 0.011, 8, segs),
      makePlasticMat(0x0e0c0a, { roughness: 0.65, envMapIntensity: 0.55 }),
    );
    rim.position.z = frontZ + eps * 2;
    g.add(rim);

    // Tinted glass (opaque — no transparent sorting flicker)
    const glass = new THREE.Mesh(new THREE.CircleGeometry(winR, segs), glassMat);
    glass.position.z = frontZ + eps * 3.5;
    g.add(glass);

    cassette.add(g);
  }

  addReelWindow(-1, 0.92); // full supply reel
  addReelWindow(1, 0.22); // nearly empty take-up

  // Tape path between reels (visible dark ribbon under label bottom)
  const path = new THREE.Mesh(
    new THREE.BoxGeometry(reelSep * 2 - winR * 0.6, 0.018, 0.01),
    tapeMatDeep,
  );
  path.position.set(0, winY - winR * 0.72, frontZ + eps);
  cassette.add(path);

  // Front protective flap / door along the long (bottom) edge
  const flapH = casH * 0.16;
  const flapTex = makeCassetteFlapTex();
  const flapBody = new THREE.Mesh(
    new THREE.BoxGeometry(casW * 0.96, flapH, casD * 0.42),
    makePlasticMat(0x171512, { roughness: 0.85, envMapIntensity: 0.5 }),
  );
  flapBody.position.set(0, -casH / 2 + flapH / 2 + 0.008, frontZ - casD * 0.08);
  flapBody.castShadow = true;
  cassette.add(flapBody);

  const flapFace = new THREE.Mesh(
    new THREE.PlaneGeometry(casW * 0.94, flapH * 0.88),
    new THREE.MeshStandardMaterial({
      map: flapTex,
      roughness: 0.82,
      metalness: 0.03,
      envMapIntensity: 0.4,
      polygonOffset: true,
      polygonOffsetFactor: -1,
      polygonOffsetUnits: -1,
    }),
  );
  flapFace.position.set(0, -casH / 2 + flapH / 2 + 0.008, frontZ + eps * 2.5);
  cassette.add(flapFace);

  // Hinge groove above flap
  const hingeGroove = new THREE.Mesh(
    new THREE.BoxGeometry(casW * 0.92, 0.012, 0.01),
    seamMat,
  );
  hingeGroove.position.set(0, -casH / 2 + flapH + 0.02, frontZ + eps);
  cassette.add(hingeGroove);

  // Write-protect notch
  const notch = new THREE.Mesh(
    new THREE.BoxGeometry(0.04, casH * 0.1, casD * 0.35),
    darkWellMat,
  );
  notch.position.set(casW / 2 - 0.01, -casH * 0.18, -casD * 0.05);
  cassette.add(notch);

  // Corner screws + locator holes
  const screwMat = makePlasticMat(0x3a3630, { roughness: 0.5, metalness: 0.25, envMapIntensity: 0.45 });
  const screwHead = makePlasticMat(0x2a2622, { roughness: 0.55, metalness: 0.2 });
  [
    [-casW * 0.44, casH * 0.38],
    [casW * 0.44, casH * 0.38],
    [-casW * 0.44, -casH * 0.22],
    [casW * 0.44, -casH * 0.22],
  ].forEach(([x, y]) => {
    const recess = new THREE.Mesh(
      new THREE.CylinderGeometry(0.028, 0.028, 0.01, 12),
      darkWellMat,
    );
    recess.rotation.x = Math.PI / 2;
    recess.position.set(x, y, frontZ - 0.002);
    cassette.add(recess);

    const screw = new THREE.Mesh(
      new THREE.CylinderGeometry(0.016, 0.016, 0.012, 10),
      screwMat,
    );
    screw.rotation.x = Math.PI / 2;
    screw.position.set(x, y, frontZ + eps);
    cassette.add(screw);

    // Phillips slot
    const slot = new THREE.Mesh(
      new THREE.BoxGeometry(0.02, 0.004, 0.004),
      screwHead,
    );
    slot.position.set(x, y, frontZ + eps * 2.5);
    cassette.add(slot);
  });

  // Small locator / mold holes near label
  [-1, 1].forEach((side) => {
    const hole = new THREE.Mesh(
      new THREE.CylinderGeometry(0.012, 0.012, 0.01, 8),
      darkWellMat,
    );
    hole.rotation.x = Math.PI / 2;
    hole.position.set(side * labelW * 0.62, winY + labelH * 0.42, frontZ - 0.002);
    cassette.add(hole);
  });

  return cassette;
}

/**
 * Load authored VHS tape GLB into a Group named 'cassette'.
 * Fits uniformly into the portrait clamshell tray; returns null on failure (procedural fallback).
 *
 * vhs_tape.glb (Sketchfab “VHS”) native axes ≈ X long · Y thin · Z face-height.
 * Portrait tray: long axis along tray height (Y), short along width (X), label toward lid (+Z).
 * Old vhs_cassette.glb was a Y-tall BOX — do not use it as the tape.
 */
async function loadCassetteGlb() {
  try {
    const loader = new GLTFLoader();
    // GLB embeds textures; resource path covers any relative external refs
    loader.setPath('./assets/');
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
    const size = box.getSize(new THREE.Vector3());
    model.position.sub(center);

    box.setFromObject(model);
    box.getSize(size);

    const trayW = BOX_W - WALL * 2.5;
    const trayH = BOX_H - WALL * 2.5;
    // Interior depth ≈ BOX_D − 2·WALL; leave a thin clearance so 88% height fit isn't crushed.
    const maxD = Math.max(0.12, BOX_D - WALL * 2 - 0.02);
    // Primary fit: long axis fills ~88% of tray height; clamp to width + depth.
    let s = (trayH * 0.88) / Math.max(size.y, 1e-6);
    if (size.x * s > trayW * 0.92) s = (trayW * 0.92) / Math.max(size.x, 1e-6);
    if (size.z * s > maxD) s = Math.min(s, maxD / Math.max(size.z, 1e-6));
    cassette.scale.setScalar(s);

    box.setFromObject(cassette);
    box.getSize(size);
    const casD = size.z;

    cassette.userData.casH = size.y;
    cassette.userData.baseZ = -BOX_D / 2 + WALL + casD / 2 + 0.025;
    cassette.userData.baseRotX = 0;
    cassette.userData.baseRotY = 0;
    cassette.userData.baseRotZ = 0;
    cassette.userData.fromGlb = true;

    return cassette;
  } catch (err) {
    console.warn('[poster-decompose] vhs_tape.glb failed, using procedural cassette', err);
    return null;
  }
}

async function buildInterior() {
  const g = new THREE.Group();
  g.name = 'interior';

  const tray = new THREE.Mesh(
    new THREE.BoxGeometry(BOX_W - WALL * 2.5, BOX_H - WALL * 2.5, 0.028),
    makePlasticMat(0x080705, { roughness: 0.95 }),
  );
  tray.position.z = -BOX_D / 2 + WALL + 0.05;
  tray.receiveShadow = true;
  g.add(tray);

  // Cassette INSIDE the shell — GLB first, procedural fallback
  const cassette = (await loadCassetteGlb()) || buildCassetteMesh();
  cassette.position.set(0, -0.06, cassette.userData.baseZ);
  cassette.rotation.set(
    cassette.userData.baseRotX ?? 0,
    cassette.userData.baseRotY ?? 0,
    cassette.userData.baseRotZ ?? Math.PI,
  );
  cassette.visible = false;
  cassette.userData.shown = false;
  g.add(cassette);

  return g;
}

function buildContactShadow() {
  const size = 256;
  const c = document.createElement('canvas');
  c.width = size;
  c.height = size;
  const ctx = c.getContext('2d');
  const g = ctx.createRadialGradient(size / 2, size / 2, size * 0.04, size / 2, size / 2, size * 0.48);
  g.addColorStop(0, 'rgba(0,0,0,0.62)');
  g.addColorStop(0.3, 'rgba(0,0,0,0.32)');
  g.addColorStop(0.65, 'rgba(0,0,0,0.08)');
  g.addColorStop(1, 'rgba(0,0,0,0)');
  ctx.fillStyle = g;
  ctx.fillRect(0, 0, size, size);
  const tex = new THREE.CanvasTexture(c);
  const mat = new THREE.MeshBasicMaterial({
    map: tex,
    transparent: true,
    opacity: 0.9,
    depthWrite: false,
  });
  const mesh = new THREE.Mesh(new THREE.PlaneGeometry(3.6, 4.8), mat);
  mesh.rotation.x = -Math.PI / 2;
  mesh.position.y = -BOX_H / 2 - 0.015;
  mesh.renderOrder = -1;
  return mesh;
}

function initAudioStub() {
  if (!el.btnMute) return;
  let muted = true;
  let started = false;
  el.btnMute.setAttribute('aria-pressed', 'true');
  el.btnMute.textContent = 'Sound off';

  const ensure = () => {
    if (started) return audioCtl;
    const AC = window.AudioContext || window.webkitAudioContext;
    if (!AC) return null;
    const ctx = new AC();
    const bufferSize = 2 * ctx.sampleRate;
    const buffer = ctx.createBuffer(1, bufferSize, ctx.sampleRate);
    const data = buffer.getChannelData(0);
    for (let i = 0; i < bufferSize; i++) data[i] = (Math.random() * 2 - 1) * 0.035;
    const src = ctx.createBufferSource();
    src.buffer = buffer;
    src.loop = true;
    const gain = ctx.createGain();
    gain.gain.value = 0;
    const filter = ctx.createBiquadFilter();
    filter.type = 'bandpass';
    filter.frequency.value = 1600;
    filter.Q.value = 0.55;
    src.connect(filter);
    filter.connect(gain);
    gain.connect(ctx.destination);
    src.start();
    started = true;
    audioCtl = { ctx, gain };
    return audioCtl;
  };

  el.btnMute.addEventListener('click', async () => {
    muted = !muted;
    const ctl = ensure();
    if (ctl && ctl.ctx.state === 'suspended') await ctl.ctx.resume();
    if (ctl) ctl.gain.gain.setTargetAtTime(muted ? 0 : 0.04, ctl.ctx.currentTime, 0.05);
    el.btnMute.setAttribute('aria-pressed', muted ? 'true' : 'false');
    el.btnMute.textContent = muted ? 'Sound off' : 'Hiss on';
  });
}

async function initThree() {
  const img = await resolveCoverImage();
  const srcW = img.naturalWidth || img.width;
  const srcH = img.naturalHeight || img.height;
  setCoverAspect(srcW / srcH);
  plasticNoiseMap = makeNoiseMap();

  renderer = new THREE.WebGLRenderer({
    antialias: !isMobile,
    alpha: true,
    powerPreference: 'high-performance',
  });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, isMobile ? 1.25 : 2));
  renderer.setSize(window.innerWidth, window.innerHeight);
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

  camera = new THREE.PerspectiveCamera(26, window.innerWidth / window.innerHeight, 0.1, 80);
  camera.position.set(0.12, 0.06, 7.8);

  scene.add(new THREE.AmbientLight(0x6a5a50, 1.15));
  scene.add(new THREE.HemisphereLight(0xfff2e0, 0x1a120e, 0.95));

  keyLight = new THREE.DirectionalLight(0xfff5ea, 2.75);
  keyLight.position.set(2.2, 3.6, 6.2);
  keyLight.castShadow = !isMobile;
  if (keyLight.castShadow) {
    keyLight.shadow.mapSize.set(1024, 1024);
    keyLight.shadow.camera.near = 1;
    keyLight.shadow.camera.far = 18;
    keyLight.shadow.camera.left = -5;
    keyLight.shadow.camera.right = 5;
    keyLight.shadow.camera.top = 5;
    keyLight.shadow.camera.bottom = -5;
    keyLight.shadow.bias = -0.0004;
  }
  scene.add(keyLight);

  const frontFill = new THREE.DirectionalLight(0xffffff, 1.45);
  frontFill.position.set(0.2, 1.0, 7.0);
  scene.add(frontFill);

  // Soft fill into the open clamshell so black cassette plastic keeps edge definition
  const interiorFill = new THREE.PointLight(0xffe8d0, 14, 8, 2);
  interiorFill.position.set(0.15, 0.35, 1.1);
  scene.add(interiorFill);

  rimLight = new THREE.PointLight(0xe03828, 42, 20, 2);
  rimLight.position.set(-4.0, 1.8, 3.0);
  scene.add(rimLight);

  const fill = new THREE.PointLight(0xffd090, 22, 18, 2);
  fill.position.set(3.2, -0.8, 4.0);
  scene.add(fill);

  const bounce = new THREE.DirectionalLight(0x6a5848, 0.8);
  bounce.position.set(-1.2, -3.2, 1.2);
  scene.add(bounce);

  floor = new THREE.Mesh(
    new THREE.PlaneGeometry(18, 18),
    new THREE.ShadowMaterial({ opacity: 0.38 }),
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

  const spineTex = makeCanvasTexture(
    (ctx, w, h) => drawSpine(ctx, w, h, metricsData.title, metricsData.year),
    160,
    768,
  );
  const backTex = makeCanvasTexture((ctx, w, h) => drawBack(ctx, w, h, metricsData), 512, 768);
  const topTex = makeCanvasTexture((ctx, w, h) => drawTopEdge(ctx, w, h), 512, 128);

  baseShell.add(buildBaseShell(spineTex, backTex, topTex));
  interiorGroup.add(await buildInterior());
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

  for (const def of layerDefs) {
    const tex = def.key === 'cover' ? coverTex : posterToLayerTexture(img, def.mode);
    const mat =
      def.key === 'cover'
        ? makeCoverMat(tex)
        : new THREE.MeshStandardMaterial({
            map: tex,
            transparent: true,
            opacity: def.opacity,
            roughness: 0.45,
            metalness: 0.03,
            depthWrite: false,
            envMapIntensity: 0.2,
          });
    const mesh = new THREE.Mesh(new THREE.PlaneGeometry(COVER_W, COVER_H), mat);
    mesh.position.z = def.z;
    mesh.userData.baseZ = def.z;
    mesh.userData.key = def.key;
    mesh.castShadow = def.key === 'cover';
    layerGroup.add(mesh);
    layers[def.key] = mesh;
  }
  lidContent.add(layerGroup);

  coverAnchor = new THREE.Object3D();
  coverAnchor.position.set(0, 0, frontZ);
  lidContent.add(coverAnchor);

  dust = buildDust();
  scene.add(dust);

  // Hero ¾ — smaller so copy + overlays stay readable
  vhsGroup.rotation.set(-0.08, -0.58, 0.02);
  vhsGroup.position.set(isMobile ? 0 : 0.72, 0.02, 0);
  vhsGroup.scale.setScalar(isMobile ? 0.58 : 0.68);

  if (el.tapeStamp) {
    el.tapeStamp.textContent = `${metricsData.title} · ${metricsData.year} · poster.jpg`;
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

function bindScroll() {
  const onScroll = () => {
    const max = Math.max(1, document.documentElement.scrollHeight - window.innerHeight);
    targetProgress = clamp(window.scrollY / max, 0, 1);
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
  return {
    x: (v.x * 0.5 + 0.5) * rect.width + rect.left,
    y: (-v.y * 0.5 + 0.5) * rect.height + rect.top,
    visible: v.z > -1 && v.z < 1,
  };
}

/** UV on cover plane → world (u,v in 0–1, v grows downward). */
function coverUvToWorld(u, v, target) {
  const cover = layers.cover;
  if (!cover) {
    target.set(0, 0, 0);
    return target;
  }
  const x = (u - 0.5) * COVER_W;
  const y = (0.5 - v) * COVER_H;
  const z = 0.025;
  return target.set(x, y, z).applyMatrix4(cover.matrixWorld);
}

function screenAabbFromUvs(uvs) {
  let minX = Infinity;
  let minY = Infinity;
  let maxX = -Infinity;
  let maxY = -Infinity;
  const tmp = new THREE.Vector3();
  for (const [u, v] of uvs) {
    coverUvToWorld(u, v, tmp);
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
    // Prefer hide empty face bbox when zero detections (copy/counter carry the "0")
    const n = metricsData && metricsData.raw ? Number(metricsData.raw.faces) : NaN;
    if (Number.isFinite(n) && n <= 0) return false;
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

/** DOM overlay fade: long lead on beat copy, then reveal mid-beat. */
function overlayRevealAmount(beatId, p) {
  if (!metricsData) return 0;
  const beat = metricsData.beats.find((b) => b.id === beatId);
  if (!beat || !beat.overlay) return 0;
  const [a, b] = beat.progress;
  if (p < a || p >= b) return 0;
  return smoothstep(0.38, 0.58, beatLocalT(beatId, p));
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
  const [a, bEnd] = beat.progress;
  const span = Math.max(1e-6, bEnd - a);
  const t = (p - a) / span;
  if (t <= -0.05 || t >= 1.05) return 0;
  // Soft edges slightly past neighbors for a brief crossfade
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
      const coverBox = screenAabbFromUvs([
        [0.02, 0.02],
        [0.98, 0.02],
        [0.02, 0.98],
        [0.98, 0.98],
      ]);
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
      const coverBox = screenAabbFromUvs([
        [0.02, 0.02],
        [0.98, 0.02],
        [0.02, 0.98],
        [0.98, 0.98],
      ]);
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

    if (def.type === 'faces') {
      const nFaces =
        metricsData && metricsData.raw ? Number(metricsData.raw.faces) : NaN;
      // Hide empty face bbox when zero detections — copy/counter already say "0 faces"
      if (Number.isFinite(nFaces) && nFaces <= 0) {
        deactivateOverlayNode(node);
        return;
      }
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
    else if (key === 'archive') html = `<b>TAPE</b> ${metricsData.id}`;
    el.counter.innerHTML = html;
    const showCounter = html && beatLocalT(beatId, p) > 0.38;
    el.counter.style.opacity = showCounter
      ? String(smoothstep(0.38, 0.55, beatLocalT(beatId, p)))
      : '0';
  }
}

/**
 * Beat choreography (progress 0–1):
 * 1 Hero ¾ closed        (0–0.12)
 * 2 Read face-on + OCR   (0.12–0.26)
 * 3 Faces / creature     (0.26–0.38)
 * 4 Palette              (0.38–0.52)
 * 5 Symmetry             (0.52–0.64)
 * 6 Diagonals            (0.64–0.74)
 * 7 Blood                (0.74–0.82)
 * 8 Knife (cover closed) (0.82–0.90)
 * 9 Archive soft lid     (0.90–1)
 */
function updateScene(p) {
  const t = clock.elapsedTime;

  const faceOn = remap(p, 0.13, 0.24);
  // Hold face-on through knife; lid open only on final archive beat
  const measureZone = remap(p, 0.28, 0.88);
  const open = remap(p, 0.90, 0.98);

  // Soft idle motion; dampen when open so cassette plastics don't shimmer
  const breathe =
    reducedMotion ? 0 : Math.sin(t * 0.55) * 0.012 * (1 - open * 0.85);

  const rotY = lerp(-0.58, -0.012, faceOn) + measureZone * 0.02 + open * -0.18;
  const rotX = lerp(-0.08, -0.006, faceOn) + measureZone * -0.015 + open * -0.06;
  const rotZ = lerp(0.02, 0.0, faceOn) + open * 0.02;

  vhsGroup.rotation.set(rotX + breathe, rotY, rotZ + breathe * 0.2);

  // Keep box on the right (desktop) so left copy + overlays stay clear
  const posX =
    lerp(isMobile ? 0 : 0.72, isMobile ? 0 : 0.55, faceOn) +
    measureZone * (isMobile ? 0 : 0.06) +
    open * (isMobile ? 0.04 : 0.12);
  const posY = lerp(0.02, 0.0, faceOn) + open * 0.03;
  const posZ = lerp(0, 0.18, faceOn) - measureZone * 0.04 - open * 0.1;
  vhsGroup.position.set(posX, posY + breathe, posZ);

  const baseScale = isMobile ? 0.58 : 0.68;
  // Slightly smaller when face-on / measuring so overlays fit the cover
  const scale = baseScale * lerp(1, 0.92, faceOn) * lerp(1, 0.9, measureZone) * lerp(1, 0.95, open);
  vhsGroup.scale.setScalar(scale);

  // Soft hinged lid — swings open to reveal cassette tape inside (no explode / no ficha)
  const openAngle = open * (isMobile ? -1.15 : -1.45);
  lidPivot.rotation.y = openAngle;

  const cassette = interiorGroup.getObjectByName('cassette');
  if (cassette) {
    // Hysteresis: once the lid starts opening, keep cassette visible (no flash at threshold)
    if (open > 0.04) cassette.userData.shown = true;
    if (open < 0.005) cassette.userData.shown = false;
    cassette.visible = !!cassette.userData.shown;
    const baseZ = cassette.userData.baseZ ?? -BOX_D / 2 + WALL + 0.1;
    cassette.position.z = lerp(baseZ, baseZ + 0.06, open);
    cassette.position.y = lerp(-0.06, 0.02, open);
    const baseRotX = cassette.userData.baseRotX ?? 0;
    const baseRotY = cassette.userData.baseRotY ?? 0;
    const baseRotZ = cassette.userData.baseRotZ ?? Math.PI;
    // Gentle lift only — avoid aggressive tilt (z-fighting with tray)
    cassette.rotation.set(baseRotX + open * -0.012, baseRotY, baseRotZ);
  }

  if (contactShadow) {
    contactShadow.material.opacity = lerp(0.9, 0.55, open);
    contactShadow.scale.set(lerp(1, 1.25, open), 1, lerp(1, 1.1, open));
  }

  if (dust) {
    dust.material.opacity = lerp(0.12, 0.02, open);
    dust.visible = dust.material.opacity > 0.01;
  }

  // --- Layer choreography: one metric layer at a time ---
  // Keep cover fully opaque through Read→Knife; only the hinged lid reveals interior
  setLayerOpacity('cover', 1);

  // Read: OCR tint after copy settles (read 0.12–0.26)
  const ocrOn = smoothstep(0.18, 0.22, p) * (1 - smoothstep(0.24, 0.28, p));
  setLayerOpacity('ocr', ocrOn);

  // Each measure layer: delay so sticky copy leads, then fade before next beat.
  // No colors peel during palette — only numbered handles + left-rail swatches.
  const peelWindows = [
    { key: 'faces', a: 0.3, b: 0.375 },
    { key: 'symmetry', a: 0.56, b: 0.635 },
    { key: 'diagonals', a: 0.675, b: 0.735 },
    { key: 'blood', a: 0.765, b: 0.815 },
  ];
  // Force palette-era peels off (OCR / faces / colors) so nothing tints the cover
  setLayerOpacity('colors', 0);
  if (layers.colors) {
    layers.colors.position.set(0, 0, layers.colors.userData.baseZ);
    layers.colors.rotation.set(0, 0, 0);
  }
  peelWindows.forEach(({ key, a, b }) => {
    const on = smoothstep(a, a + 0.02, p) * (1 - smoothstep(b - 0.015, b, p));
    setLayerOpacity(key, on * (1 - open));
    const mesh = layers[key];
    if (!mesh) return;
    const lift = on * 0.028;
    mesh.position.x = 0;
    mesh.position.y = lift * 0.02;
    mesh.position.z = mesh.userData.baseZ + lift;
    mesh.rotation.z = 0;
    mesh.rotation.y = 0;
  });

  // Soft residual tint during knife (cover still closed); fades as lid opens
  if (p >= 0.82 && p < 0.90) {
    setLayerOpacity('blood', smoothstep(0.82, 0.86, p) * (1 - smoothstep(0.875, 0.90, p)) * 0.22);
    if (layers.blood) {
      layers.blood.position.set(0, 0, layers.blood.userData.baseZ + 0.01);
      layers.blood.rotation.set(0, 0, 0);
    }
  } else if (p >= 0.90) {
    setLayerOpacity('blood', smoothstep(0.90, 0.94, p) * (1 - open * 0.45) * 0.18);
    if (layers.blood) {
      layers.blood.position.set(0, 0, layers.blood.userData.baseZ + 0.01);
      layers.blood.rotation.set(0, 0, 0);
    }
  }

  // Keep cover on the lid — no fly-away / no fan
  if (layers.cover) {
    layers.cover.position.set(0, 0, layers.cover.userData.baseZ);
    layers.cover.rotation.set(0, 0, 0);
  }

  const camZ = lerp(8.4, 7.2, faceOn) - measureZone * 0.05 + open * 0.45;
  const camX =
    lerp(0.18, 0.08, faceOn) + (reducedMotion ? 0 : Math.sin(t * 0.08) * 0.015) + open * 0.28;
  const camY = 0.04 + (reducedMotion ? 0 : Math.cos(t * 0.07) * 0.012) + open * 0.06;
  camera.position.set(camX, camY, camZ);
  camera.lookAt(vhsGroup.position.x * 0.35, vhsGroup.position.y * 0.08, open * 0.04);
  camera.updateMatrixWorld(true);

  if (keyLight) keyLight.intensity = lerp(2.6, 2.1, open);
  if (rimLight) rimLight.intensity = lerp(42, 28, faceOn) + open * 10;

  el.bar.style.width = `${(p * 100).toFixed(1)}%`;
  updateActiveBeat(p);
}

function updateActiveBeat(p) {
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
    el.beatLabel.textContent = `TRACK ${String(idx + 1).padStart(2, '0')} · ${beat.kicker}`;
    if (el.actLabel) {
      const act = metricsData.acts && metricsData.acts[beat.act - 1];
      el.actLabel.textContent = act ? act.label : `Acto ${beat.act}`;
    }
    el.tapeStamp.textContent = `${metricsData.title} · ${metricsData.year} · id ${metricsData.id} · poster.jpg`;
  }
  const beat = metricsData.beats[activeBeat];
  updateOverlays(p, beat ? beat.id : null);
}

function tick() {
  const dt = Math.min(clock.getDelta(), 0.05);
  const lag = reducedMotion ? 1 : isMobile ? 0.16 : 0.075;
  scrollProgress = lerp(scrollProgress, targetProgress, 1 - Math.pow(1 - lag, dt * 60));
  updateScene(scrollProgress);
  if (dust) dust.rotation.y = clock.elapsedTime * 0.022;
  renderer.render(scene, camera);
}

function onResize() {
  if (!camera || !renderer) return;
  camera.aspect = window.innerWidth / window.innerHeight;
  camera.updateProjectionMatrix();
  renderer.setSize(window.innerWidth, window.innerHeight);
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, isMobile ? 1.25 : 2));
  const max = Math.max(1, document.documentElement.scrollHeight - window.innerHeight);
  targetProgress = clamp(window.scrollY / max, 0, 1);
  scrollProgress = targetProgress;
}

boot().catch((err) => {
  console.error(err);
  const msg = err && (err.message || String(err));
  el.loader.innerHTML = `<p style="color:#b71c1c;max-width:32rem;text-align:center;line-height:1.6">
    No se pudo cargar la demo.<br>
    <code style="color:#c9a227;font-size:10px;letter-spacing:.04em;text-transform:none">${escapeHtml(msg)}</code><br><br>
    <code style="color:#8a7f6e;font-size:10px">cd site && python3 -m http.server 8765</code>
  </p>`;
});

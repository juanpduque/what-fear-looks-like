/**
 * VHS Decompose — Halloween (948) · contest pass
 * Clamshell hinged lid · Media box art · 4-act scroll · anchored overlays
 */
import * as THREE from 'three';

const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
const isMobile =
  window.matchMedia('(max-width: 720px)').matches ||
  (navigator.maxTouchPoints > 0 && window.innerWidth < 900);

/** Large rental clamshell — cover plane matches Media art aspect (616×1024). */
const MEDIA_ASPECT = 616 / 1024; // ~0.6016 — printed sleeve, not stretched
const BOX_H = 3.32;
const BEZEL = 0.055; // thin frame — Media art is nearly full-bleed
const COVER_H = BOX_H - BEZEL * 2;
const COVER_W = COVER_H * MEDIA_ASPECT;
const BOX_W = COVER_W + BEZEL * 2;
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
let usingMediaCover = false;

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
let coverAnchor = null; // Object3D at cover center for projection
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
    const swatches = beat.swatches
      ? `<div class="beat-swatches">${beat.swatches
          .map((c) => `<i style="background:${c}" title="${c}"></i>`)
          .join('')}</div>`
      : '';
    const cue =
      beat.id === 'hero'
        ? `<p class="scroll-cue">${escapeHtml(beat.cue || 'SCROLL')} <span aria-hidden="true">↓</span></p>`
        : '';
    const actTag =
      beat.act === 1 || beat.act === 2 || beat.act === 4
        ? `<div class="beat-act">Acto ${['', 'I', 'II', 'III', 'IV'][beat.act]}</div>`
        : '';
    section.innerHTML = `
      <div class="beat-inner">
        ${actTag}
        <div class="beat-kicker">${escapeHtml(beat.kicker)}</div>
        <h2 class="beat-title">${escapeHtml(beat.title)}</h2>
        <p class="beat-body">${escapeHtml(beat.body)}</p>
        ${swatches}
        ${cue}
      </div>
    `;
    el.track.appendChild(section);
    return section;
  });
}

function buildOverlayDom(data) {
  if (!el.overlays) return;
  el.overlays.innerHTML = '';
  overlayNodes = {};
  data.beats.forEach((beat) => {
    if (!beat.overlay) return;
    const node = document.createElement('div');
    node.className = `ov ov-${beat.overlay.type}`;
    node.dataset.beat = beat.id;
    node.setAttribute('aria-hidden', 'true');
    if (beat.overlay.type === 'bbox' || beat.overlay.type === 'faces') {
      node.innerHTML = `<span class="ov-box"></span><span class="ov-label">${escapeHtml(beat.overlay.label || '')}</span>`;
    } else if (beat.overlay.type === 'symmetry') {
      node.innerHTML = `<span class="ov-axis"></span><span class="ov-label">${escapeHtml(beat.overlay.label || '')}</span>`;
    } else if (beat.overlay.type === 'palette') {
      const sw = (beat.swatches || []).map((c) => `<i style="background:${c}"></i>`).join('');
      node.innerHTML = `<span class="ov-label">${escapeHtml(beat.overlay.label || '')}</span><div class="ov-swatches">${sw}</div>`;
    } else if (beat.overlay.type === 'heatmap') {
      node.innerHTML = `<span class="ov-label">${escapeHtml(beat.overlay.label || '')}</span>`;
    } else if (beat.overlay.type === 'tags') {
      const tags = (beat.overlay.tags || [])
        .map((t) => `<em>${escapeHtml(t)}</em>`)
        .join('');
      node.innerHTML = `<div class="ov-tags">${tags}</div>`;
    }
    el.overlays.appendChild(node);
    overlayNodes[beat.id] = { el: node, def: beat.overlay };
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

async function resolveCoverImage() {
  try {
    const img = await loadImage('./vhs_reference.png');
    usingMediaCover = true;
    return img;
  } catch {
    usingMediaCover = false;
    return loadImage('./poster.jpg');
  }
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

/** Soft studio cubemap → PMREM for clearcoat plastic. */
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
  // Warm key lobe
  const key = ctx.createRadialGradient(360, 70, 10, 360, 70, 160);
  key.addColorStop(0, 'rgba(255,180,100,0.55)');
  key.addColorStop(1, 'rgba(255,180,100,0)');
  ctx.fillStyle = key;
  ctx.fillRect(0, 0, 512, 256);
  // Blood rim lobe
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

function applyWearOverlay(ctx, w, h, opts = {}) {
  const {
    yellow = 0.06,
    scuff = true,
    crease = false,
    sticker = false,
    edgeDark = 0.2,
    cardboard = true,
  } = opts;

  if (yellow > 0) {
    ctx.fillStyle = `rgba(170,130,55,${yellow})`;
    ctx.fillRect(0, 0, w, h);
  }

  if (scuff) {
    const eg = ctx.createLinearGradient(0, 0, w * 0.1, 0);
    eg.addColorStop(0, `rgba(0,0,0,${edgeDark})`);
    eg.addColorStop(1, 'rgba(0,0,0,0)');
    ctx.fillStyle = eg;
    ctx.fillRect(0, 0, w * 0.12, h);

    const eg2 = ctx.createLinearGradient(w, 0, w * 0.9, 0);
    eg2.addColorStop(0, `rgba(0,0,0,${edgeDark * 0.65})`);
    eg2.addColorStop(1, 'rgba(0,0,0,0)');
    ctx.fillStyle = eg2;
    ctx.fillRect(w * 0.88, 0, w * 0.12, h);

    const top = ctx.createLinearGradient(0, 0, 0, h * 0.07);
    top.addColorStop(0, 'rgba(255,255,255,0.07)');
    top.addColorStop(1, 'rgba(0,0,0,0)');
    ctx.fillStyle = top;
    ctx.fillRect(0, 0, w, h * 0.09);

    ctx.strokeStyle = 'rgba(220,200,170,0.1)';
    ctx.lineWidth = 1.4;
    for (let i = 0; i < 16; i++) {
      const x = Math.random() * w;
      const y = Math.random() * h;
      ctx.beginPath();
      ctx.moveTo(x, y);
      ctx.lineTo(x + 10 + Math.random() * 36, y + (Math.random() - 0.5) * 5);
      ctx.stroke();
    }
  }

  // Media-style cardboard blowouts on edges
  if (cardboard) {
    ctx.fillStyle = 'rgba(246,237,216,0.55)';
    for (let i = 0; i < 28; i++) {
      const side = Math.random() < 0.55 ? 0 : 1;
      const x = side ? w - Math.random() * 14 : Math.random() * 14;
      const y = Math.random() * h;
      ctx.globalAlpha = 0.35 + Math.random() * 0.45;
      ctx.beginPath();
      ctx.ellipse(x, y, 2 + Math.random() * 8, 3 + Math.random() * 14, 0, 0, Math.PI * 2);
      ctx.fill();
    }
    ctx.globalAlpha = 0.75;
    ctx.beginPath();
    ctx.moveTo(0, h);
    ctx.lineTo(0, h - 48);
    ctx.quadraticCurveTo(18, h - 8, 62, h);
    ctx.closePath();
    ctx.fill();
    ctx.globalAlpha = 1;
  }

  if (crease) {
    const cg = ctx.createLinearGradient(w * 0.42, 0, w * 0.58, 0);
    cg.addColorStop(0, 'rgba(0,0,0,0)');
    cg.addColorStop(0.45, 'rgba(0,0,0,0.26)');
    cg.addColorStop(0.55, 'rgba(255,255,255,0.05)');
    cg.addColorStop(1, 'rgba(0,0,0,0)');
    ctx.fillStyle = cg;
    ctx.fillRect(w * 0.4, 0, w * 0.2, h);
  }

  if (sticker) {
    const sx = w * 0.64;
    const sy = h * 0.1;
    const sw = w * 0.26;
    const sh = h * 0.08;
    ctx.fillStyle = 'rgba(232,220,200,0.2)';
    ctx.fillRect(sx, sy, sw, sh);
    ctx.strokeStyle = 'rgba(183,28,28,0.4)';
    ctx.lineWidth = 2;
    ctx.strokeRect(sx + 3, sy + 3, sw - 6, sh - 6);
    ctx.fillStyle = 'rgba(183,28,28,0.5)';
    ctx.font = `600 ${Math.max(10, sh * 0.3)}px "IBM Plex Mono", monospace`;
    ctx.textAlign = 'center';
    ctx.fillText('RENTAL', sx + sw / 2, sy + sh * 0.48);
    ctx.fillStyle = 'rgba(20,16,12,0.45)';
    ctx.font = `${Math.max(8, sh * 0.22)}px "IBM Plex Mono", monospace`;
    ctx.fillText('948 · DUE', sx + sw / 2, sy + sh * 0.78);
    ctx.textAlign = 'left';
  }
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
  ctx.fillText('MEDIA HOME ENTERTAINMENT', 0, 72);
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
  applyWearOverlay(ctx, w, h, { yellow: 0.05, scuff: true, crease: true, cardboard: true, edgeDark: 0.28 });
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
    'This sleeve is the sales pitch the corpus measured:',
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
  ctx.fillText('VHS · NTSC · MEDIA RENTAL SLEEVE', 48, h - 56);

  applyWearOverlay(ctx, w, h, { yellow: 0.055, scuff: true, sticker: true, cardboard: true });
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
  applyWearOverlay(ctx, w, h, { yellow: 0.04, scuff: true, cardboard: false, edgeDark: 0.12 });
}

/**
 * Cover texture at native aspect — never stretch Media art into a wider plane.
 * Mild contrast lift only (no yellow wash / sheen that muddies oranges).
 */
function drawCoverWear(img) {
  const srcW = img.naturalWidth || img.width;
  const srcH = img.naturalHeight || img.height;
  // Keep native pixels; max edge 1024 for GPU
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

  if (usingMediaCover) {
    // Gentle punch: lift mids slightly so pumpkin orange + title whites pop
    const id = ctx.getImageData(0, 0, w, h);
    const d = id.data;
    for (let i = 0; i < d.length; i += 4) {
      let r = d[i];
      let g = d[i + 1];
      let b = d[i + 2];
      // Soft contrast around midtones
      r = clamp((r - 128) * 1.08 + 128 + 6, 0, 255);
      g = clamp((g - 128) * 1.06 + 128 + 4, 0, 255);
      b = clamp((b - 128) * 1.04 + 128 + 2, 0, 255);
      // Warm orange bias on saturated warm pixels (pumpkin)
      const warm = Math.max(0, r - b) * Math.max(0, g - b * 0.5);
      if (warm > 20) {
        const t = clamp(warm / 180, 0, 1) * 0.12;
        r = Math.min(255, r + t * 28);
        g = Math.min(255, g + t * 10);
      }
      d[i] = r;
      d[i + 1] = g;
      d[i + 2] = b;
    }
    ctx.putImageData(id, 0, 0);
  } else {
    applyWearOverlay(ctx, w, h, {
      yellow: 0.04,
      scuff: true,
      sticker: true,
      cardboard: true,
      edgeDark: 0.14,
    });
  }

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

function posterToLayerTexture(img, mode) {
  // Same aspect as cover plane (Media 616∶1024) — no UV stretch vs printed face
  const w = usingMediaCover ? 616 : 512;
  const h = usingMediaCover ? 1024 : 768;
  const c = document.createElement('canvas');
  c.width = w;
  c.height = h;
  const ctx = c.getContext('2d', { willReadFrequently: true });
  ctx.drawImage(img, 0, 0, w, h);
  const imageData = ctx.getImageData(0, 0, w, h);
  const d = imageData.data;
  const dark = rawNum('dark_share', 0.87);
  const sym = rawNum('symmetry', 0.93);
  const blood = rawNum('nova_blood', 0.85);
  const knife = rawNum('nova_knife', 0.95);
  const ocr = rawNum('ocr_conf', 0.98);
  const faces = rawNum('faces', 0);

  if (mode === 'ocr') {
    for (let i = 0; i < d.length; i += 4) {
      const y = Math.floor(i / 4 / w);
      // Media title band is TOP; poster.jpg title was bottom — prefer Media
      const inTitle = usingMediaCover
        ? y > h * 0.03 && y < h * 0.15
        : y > h * 0.78 && y < h * 0.96;
      const f = inTitle ? 1.15 : 0.18;
      d[i] *= f;
      d[i + 1] *= f;
      d[i + 2] *= f;
      d[i + 3] = inTitle ? 235 : 90;
    }
    ctx.putImageData(imageData, 0, 0);
    const bx = usingMediaCover ? [0.08, 0.03, 0.84, 0.12] : [0.08, 0.8, 0.84, 0.14];
    ctx.strokeStyle = 'rgba(107,143,113,.95)';
    ctx.lineWidth = 3;
    ctx.strokeRect(w * bx[0], h * bx[1], w * bx[2], h * bx[3]);
    ctx.fillStyle = 'rgba(107,143,113,.95)';
    ctx.font = '700 20px "IBM Plex Mono", monospace';
    ctx.fillText(`OCR ${ocr.toFixed(2)} · HALLOWEEN`, w * bx[0] + 6, h * bx[1] - 10);
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
      d[i + 3] = edge ? 220 : 65;
    }
    ctx.putImageData(imageData, 0, 0);
    ctx.strokeStyle = 'rgba(107,200,170,.28)';
    ctx.lineWidth = 1;
    for (let gx = 0; gx < w; gx += 40) {
      ctx.beginPath();
      ctx.moveTo(gx, 0);
      ctx.lineTo(gx, h);
      ctx.stroke();
    }
    for (let gy = 0; gy < h; gy += 40) {
      ctx.beginPath();
      ctx.moveTo(0, gy);
      ctx.lineTo(w, gy);
      ctx.stroke();
    }
    // Scan region over artwork (no face found)
    ctx.strokeStyle = 'rgba(107,200,170,.9)';
    ctx.lineWidth = 3;
    ctx.setLineDash([8, 6]);
    ctx.strokeRect(w * 0.22, h * 0.22, w * 0.56, h * 0.42);
    ctx.setLineDash([]);
    ctx.fillStyle = 'rgba(107,200,170,.95)';
    ctx.font = '700 24px "IBM Plex Mono", monospace';
    ctx.fillText(`YuNet · ${faces} FACES`, w * 0.22, h * 0.2);
  } else if (mode === 'colors') {
    for (let i = 0; i < d.length; i += 4) {
      d[i] = Math.min(255, d[i] * 1.3);
      d[i + 1] = d[i + 1] * 0.75;
      d[i + 2] = d[i + 2] * 0.58;
      d[i + 3] = 210;
    }
    ctx.putImageData(imageData, 0, 0);
    const sw = ['#070101', '#370f0e', '#711910', '#c53c0d', '#d5bda2'];
    sw.forEach((hex, i) => {
      ctx.fillStyle = hex;
      ctx.fillRect(20 + i * 48, h - 72, 40, 40);
      ctx.strokeStyle = 'rgba(232,220,200,.3)';
      ctx.strokeRect(20 + i * 48, h - 72, 40, 40);
    });
    ctx.fillStyle = 'rgba(232,220,200,.92)';
    ctx.font = '700 20px "IBM Plex Mono", monospace';
    ctx.fillText(`${(dark * 100).toFixed(0)}% DARK · bri ${rawNum('brightness', 8.1).toFixed(1)}`, 20, h - 84);
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
          d[i + 3] = 185;
        } else {
          d[i + 3] = 215;
        }
      }
    }
    ctx.putImageData(imageData, 0, 0);
    ctx.strokeStyle = 'rgba(201,162,39,.95)';
    ctx.lineWidth = 3;
    ctx.beginPath();
    ctx.moveTo(w / 2, 0);
    ctx.lineTo(w / 2, h);
    ctx.stroke();
    ctx.fillStyle = 'rgba(201,162,39,.95)';
    ctx.font = '700 22px "IBM Plex Mono", monospace';
    ctx.fillText(`SYMMETRY ${sym.toFixed(2)}`, w * 0.52 + 10, 36);
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
      d[i + 3] = 45 + heat * 210;
    }
    ctx.putImageData(imageData, 0, 0);
    ctx.fillStyle = 'rgba(183,28,28,.95)';
    ctx.font = '700 22px "IBM Plex Mono", monospace';
    ctx.fillText(`NOVA BLOOD ${blood.toFixed(2)}`, 18, 34);
    ctx.fillText(`KNIFE ${knife.toFixed(2)}`, 18, 62);
  } else if (mode === 'medium') {
    for (let i = 0; i < d.length; i += 4) {
      const lum = 0.2126 * d[i] + 0.7152 * d[i + 1] + 0.0722 * d[i + 2];
      d[i] = lum;
      d[i + 1] = lum * 0.94;
      d[i + 2] = lum * 0.78;
      d[i + 3] = lum > 85 ? 210 : 30;
    }
    ctx.putImageData(imageData, 0, 0);
    ctx.fillStyle = 'rgba(232,220,200,.92)';
    ctx.font = '700 20px "IBM Plex Mono", monospace';
    ctx.fillText('PHOTOGRAPHIC · DECORATIVE', 16, 32);
    ctx.fillStyle = 'rgba(183,28,28,.85)';
    ctx.font = '16px "IBM Plex Mono", monospace';
    ctx.fillText('dread · suspense · terror', 16, 58);
  } else {
    ctx.putImageData(imageData, 0, 0);
  }

  const tex = new THREE.CanvasTexture(c);
  tex.colorSpace = THREE.SRGBColorSpace;
  tex.anisotropy = isMobile ? 2 : 4;
  return tex;
}

function makePlasticMat(color = 0x1a1714, opts = {}) {
  return new THREE.MeshStandardMaterial({
    color,
    roughness: opts.roughness ?? 0.82,
    metalness: opts.metalness ?? 0.06,
    roughnessMap: opts.roughnessMap ?? plasticNoiseMap,
    envMapIntensity: opts.envMapIntensity ?? 0.55,
    transparent: true,
    opacity: 1,
    side: opts.side ?? THREE.FrontSide,
  });
}

function makeCoverMat(map) {
  // Unlit + no tone-map crush → Media oranges/whites match the reference file
  return new THREE.MeshBasicMaterial({
    map,
    color: 0xffffff,
    transparent: true,
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

/** Base shell: back, walls, tray cavity — no front (lid owns front). */
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

  // Inner cavity lining (reads as hollow when lid opens)
  const liner = new THREE.Mesh(
    new THREE.BoxGeometry(BOX_W - WALL * 2.2, BOX_H - WALL * 2.2, 0.02),
    makePlasticMat(0x080705, { roughness: 0.95, envMapIntensity: 0.2 }),
  );
  liner.position.z = -BOX_D / 2 + WALL + 0.03;
  g.add(liner);

  // Hinge ridge detail on spine edge
  const hinge = new THREE.Mesh(
    new THREE.BoxGeometry(0.03, BOX_H * 0.92, 0.04),
    makePlasticMat(0x0c0a08, { roughness: 0.7, metalness: 0.15 }),
  );
  hinge.position.set(-BOX_W / 2 + 0.02, 0, BOX_D * 0.15);
  g.add(hinge);

  return g;
}

/** Front lid: bezel frame — cover sits flush with front face (no deep recess parallax). */
function buildLidFrame() {
  const g = new THREE.Group();
  g.name = 'lidFrame';
  // Flat frame coplanar with cover — thin Z so edges don't create false trapezoid
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

function buildInterior() {
  const g = new THREE.Group();
  g.name = 'interior';

  const tray = new THREE.Mesh(
    new THREE.BoxGeometry(BOX_W - WALL * 2.5, BOX_H - WALL * 2.5, 0.028),
    makePlasticMat(0x080705, { roughness: 0.95 }),
  );
  tray.position.z = -BOX_D / 2 + WALL + 0.05;
  tray.receiveShadow = true;
  g.add(tray);

  const casW = (BOX_W - WALL * 2.5) * 0.86;
  const casH = casW * 0.62;
  const casD = 0.11;
  const cassette = new THREE.Mesh(
    new THREE.BoxGeometry(casW, casH, casD),
    makePlasticMat(0x1c1a18, { roughness: 0.72 }),
  );
  cassette.position.set(0, -0.12, -BOX_D / 2 + WALL + 0.11);
  cassette.castShadow = true;
  cassette.name = 'cassette';
  g.add(cassette);

  const labelTex = makeCanvasTexture((ctx, cw, ch) => {
    ctx.fillStyle = '#2a2218';
    ctx.fillRect(0, 0, cw, ch);
    ctx.fillStyle = '#c9a227';
    ctx.font = '700 46px "Bebas Neue", Impact, sans-serif';
    ctx.textAlign = 'center';
    ctx.fillText('HALLOWEEN', cw / 2, ch * 0.4);
    ctx.fillStyle = '#8a7f6e';
    ctx.font = '20px "IBM Plex Mono", monospace';
    ctx.fillText('1978 · SP · 948', cw / 2, ch * 0.7);
  }, 512, 128);
  const label = new THREE.Mesh(
    new THREE.PlaneGeometry(casW * 0.7, casH * 0.2),
    new THREE.MeshStandardMaterial({ map: labelTex, roughness: 0.5, metalness: 0.04 }),
  );
  label.position.set(0, casH * 0.28, casD / 2 + 0.001);
  cassette.add(label);

  const winW = casW * 0.52;
  const winH = casH * 0.36;
  const window = new THREE.Mesh(
    new THREE.BoxGeometry(winW, winH, 0.018),
    new THREE.MeshPhysicalMaterial({
      color: 0x1e2830,
      roughness: 0.2,
      metalness: 0.08,
      transparent: true,
      opacity: 0.4,
      clearcoat: 0.6,
      clearcoatRoughness: 0.25,
      depthWrite: false,
    }),
  );
  window.position.set(0, -casH * 0.12, casD / 2 + 0.002);
  cassette.add(window);

  const reelMat = makePlasticMat(0x2a2622, { roughness: 0.6 });
  const hubMat = makePlasticMat(0x0c0a08);
  const reelR = winH * 0.3;
  [-0.2, 0.2].forEach((ox) => {
    const reel = new THREE.Mesh(new THREE.CylinderGeometry(reelR, reelR, 0.022, 28), reelMat);
    reel.rotation.x = Math.PI / 2;
    reel.position.set(ox * winW, -casH * 0.12, casD / 2 + 0.012);
    cassette.add(reel);
    const hub = new THREE.Mesh(
      new THREE.CylinderGeometry(reelR * 0.26, reelR * 0.26, 0.028, 10),
      hubMat,
    );
    hub.rotation.x = Math.PI / 2;
    hub.position.copy(reel.position);
    hub.position.z += 0.002;
    cassette.add(hub);
  });

  const band = new THREE.Mesh(
    new THREE.BoxGeometry(winW * 0.88, reelR * 0.32, 0.006),
    makePlasticMat(0x0a0806, { roughness: 0.9 }),
  );
  band.position.set(0, -casH * 0.12, casD / 2 + 0.016);
  cassette.add(band);

  // Archive card stub behind cassette (visible when open)
  const cardTex = makeCanvasTexture((ctx, cw, ch) => {
    ctx.fillStyle = '#1a1612';
    ctx.fillRect(0, 0, cw, ch);
    ctx.strokeStyle = '#c9a227';
    ctx.strokeRect(12, 12, cw - 24, ch - 24);
    ctx.fillStyle = '#e8dcc8';
    ctx.font = '700 36px "Bebas Neue", Impact, sans-serif';
    ctx.fillText('CORPUS FICHA 948', 28, 70);
    ctx.fillStyle = '#8a7f6e';
    ctx.font = '18px "IBM Plex Mono", monospace';
    const lines = [
      `sym ${rawNum('symmetry').toFixed(3)}`,
      `dark ${(rawNum('dark_share') * 100).toFixed(1)}%`,
      `faces ${rawNum('faces')} · blood ${rawNum('nova_blood')}`,
      `knife ${rawNum('nova_knife')} · OCR ${rawNum('ocr_conf').toFixed(2)}`,
      `creature ${metricsData.raw.creature} ${rawNum('creature_score').toFixed(2)}`,
    ];
    lines.forEach((t, i) => ctx.fillText(t, 28, 120 + i * 36));
  }, 512, 640);
  const card = new THREE.Mesh(
    new THREE.PlaneGeometry(casW * 0.92, casH * 1.15),
    new THREE.MeshStandardMaterial({
      map: cardTex,
      roughness: 0.75,
      metalness: 0.02,
      transparent: true,
      opacity: 0.95,
    }),
  );
  card.position.set(0.08, 0.35, -BOX_D / 2 + WALL + 0.08);
  card.name = 'archiveCard';
  g.add(card);

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
  plasticNoiseMap = makeNoiseMap();

  renderer = new THREE.WebGLRenderer({
    antialias: !isMobile,
    alpha: true,
    powerPreference: 'high-performance',
  });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, isMobile ? 1.4 : 2));
  renderer.setSize(window.innerWidth, window.innerHeight);
  renderer.setClearColor(0x000000, 0);
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  // Neutral preserves orange/white better than ACES (less crush)
  renderer.toneMapping = THREE.NeutralToneMapping;
  renderer.toneMappingExposure = 1.65;
  renderer.shadowMap.enabled = !isMobile;
  renderer.shadowMap.type = THREE.PCFSoftShadowMap;
  el.stage.appendChild(renderer.domElement);

  scene = new THREE.Scene();
  scene.fog = new THREE.FogExp2(0x0a0806, 0.012);
  scene.environment = buildEnvMap();

  // Longer lens → less foreshortening on the printed face
  camera = new THREE.PerspectiveCamera(26, window.innerWidth / window.innerHeight, 0.1, 80);
  camera.position.set(0.12, 0.06, 7.8);

  const amb = new THREE.AmbientLight(0x5a4a40, 1.05);
  scene.add(amb);

  const hemi = new THREE.HemisphereLight(0xfff2e0, 0x1a120e, 0.85);
  scene.add(hemi);

  keyLight = new THREE.DirectionalLight(0xfff5ea, 2.8);
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

  // Strong front fill — cover plane gets even illumination in ¾
  const frontFill = new THREE.DirectionalLight(0xffffff, 1.35);
  frontFill.position.set(0.2, 1.0, 7.0);
  scene.add(frontFill);

  rimLight = new THREE.PointLight(0xe03828, 48, 20, 2);
  rimLight.position.set(-4.0, 1.8, 3.0);
  scene.add(rimLight);

  const fill = new THREE.PointLight(0xffd090, 20, 18, 2);
  fill.position.set(3.2, -0.8, 4.0);
  scene.add(fill);

  const bounce = new THREE.DirectionalLight(0x6a5848, 0.7);
  bounce.position.set(-1.2, -3.2, 1.2);
  scene.add(bounce);

  // Soft floor for real shadows
  floor = new THREE.Mesh(
    new THREE.PlaneGeometry(18, 18),
    new THREE.ShadowMaterial({ opacity: 0.35 }),
  );
  floor.rotation.x = -Math.PI / 2;
  floor.position.y = -BOX_H / 2 - 0.04;
  floor.receiveShadow = true;
  scene.add(floor);

  vhsGroup = new THREE.Group();
  vhsGroup.name = 'vhs';

  // Hinged lid: pivot at left (spine) edge
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
  interiorGroup.add(buildInterior());
  lidContent.add(buildLidFrame());

  contactShadow = buildContactShadow();
  vhsGroup.add(contactShadow);

  const coverTex = drawCoverWear(img);
  // Cover flush with bezel front face — same Z family, tiny epsilon in front of frame back
  const frontZ = BOX_D / 2 - 0.001;

  const layerDefs = [
    { key: 'cover', mode: 'poster', z: frontZ, opacity: 1 },
    { key: 'ocr', mode: 'ocr', z: frontZ + 0.01, opacity: 0 },
    { key: 'faces', mode: 'faces', z: frontZ + 0.02, opacity: 0 },
    { key: 'colors', mode: 'colors', z: frontZ + 0.03, opacity: 0 },
    { key: 'symmetry', mode: 'symmetry', z: frontZ + 0.04, opacity: 0 },
    { key: 'blood', mode: 'blood', z: frontZ + 0.05, opacity: 0 },
    { key: 'medium', mode: 'medium', z: frontZ + 0.06, opacity: 0 },
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
            roughness: 0.4,
            metalness: 0.03,
            depthWrite: false,
            envMapIntensity: 0.25,
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

  // Anchor for screen-space overlays (cover center)
  coverAnchor = new THREE.Object3D();
  coverAnchor.position.set(0, 0, frontZ);
  lidContent.add(coverAnchor);

  dust = buildDust();
  scene.add(dust);

  // Hero ¾ — spine readable, cover plane nearly upright (minimal roll)
  vhsGroup.rotation.set(-0.1, -0.52, 0.015);
  vhsGroup.position.set(isMobile ? 0 : 0.5, 0.04, 0);
  vhsGroup.scale.setScalar(isMobile ? 0.9 : 1.06);

  if (el.tapeStamp) {
    const cov = usingMediaCover ? 'Media box art' : 'poster.jpg';
    el.tapeStamp.textContent = `${metricsData.title} · ${metricsData.year} · ${cov}`;
  }
}

function buildDust() {
  const n = isMobile ? 48 : 140;
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
    size: 0.026,
    transparent: true,
    opacity: 0.22,
    depthWrite: false,
    blending: THREE.AdditiveBlending,
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

function setGroupOpacity(group, opacity) {
  group.traverse((obj) => {
    if (obj.isMesh && obj.material) {
      const mats = Array.isArray(obj.material) ? obj.material : [obj.material];
      for (const m of mats) {
        if (m && 'opacity' in m) {
          m.transparent = true;
          m.opacity = opacity;
        }
      }
    }
  });
}

function worldToScreen(v3) {
  const v = v3.clone().project(camera);
  return {
    x: (v.x * 0.5 + 0.5) * window.innerWidth,
    y: (-v.y * 0.5 + 0.5) * window.innerHeight,
    visible: v.z > -1 && v.z < 1,
  };
}

function updateOverlays(p, beatId) {
  if (!el.overlays || !coverAnchor) return;
  const tmpA = new THREE.Vector3();
  const tmpB = new THREE.Vector3();

  Object.keys(overlayNodes).forEach((id) => {
    const { el: node, def } = overlayNodes[id];
    const active = id === beatId;
    const opacity = active ? 1 : 0;
    node.style.opacity = String(opacity);
    node.classList.toggle('on', active);
    if (!active) return;

    // Position relative to cover corners
    const lidWorld = new THREE.Matrix4();
    lidContent.updateWorldMatrix(true, false);
    lidWorld.copy(lidContent.matrixWorld);

    const toWorld = (u, v, target) => {
      const x = (u - 0.5) * COVER_W;
      const y = (0.5 - v) * COVER_H;
      const z = layers.cover.userData.baseZ + 0.02;
      target.set(x, y, z).applyMatrix4(lidWorld);
      return target;
    };

    if (def.type === 'bbox' || def.type === 'faces') {
      const uv = def.uv || [0.1, 0.1, 0.3, 0.2];
      toWorld(uv[0], uv[1], tmpA);
      toWorld(uv[0] + uv[2], uv[1] + uv[3], tmpB);
      const a = worldToScreen(tmpA);
      const b = worldToScreen(tmpB);
      const left = Math.min(a.x, b.x);
      const top = Math.min(a.y, b.y);
      const width = Math.abs(b.x - a.x);
      const height = Math.abs(b.y - a.y);
      node.style.left = `${left}px`;
      node.style.top = `${top}px`;
      node.style.width = `${width}px`;
      node.style.height = `${height}px`;
    } else if (def.type === 'symmetry') {
      const axis = def.axis != null ? def.axis : 0.5;
      toWorld(axis, 0.05, tmpA);
      toWorld(axis, 0.95, tmpB);
      const a = worldToScreen(tmpA);
      const b = worldToScreen(tmpB);
      node.style.left = `${a.x}px`;
      node.style.top = `${Math.min(a.y, b.y)}px`;
      node.style.width = '2px';
      node.style.height = `${Math.abs(b.y - a.y)}px`;
    } else {
      // Floating label near right edge of cover
      toWorld(0.92, 0.18, tmpA);
      const a = worldToScreen(tmpA);
      node.style.left = `${a.x + 12}px`;
      node.style.top = `${a.y}px`;
      node.style.width = 'auto';
      node.style.height = 'auto';
    }
  });

  // Metric counter HUD
  if (el.counter && metricsData) {
    const beat = metricsData.beats.find((b) => b.id === beatId);
    const raw = metricsData.raw;
    let html = '';
    if (beat && beat.metricKey === 'ocr') {
      html = `<b>OCR</b> ${(raw.ocr_conf * 100).toFixed(1)}%`;
    } else if (beat && beat.metricKey === 'faces') {
      html = `<b>FACES</b> ${raw.faces}`;
    } else if (beat && beat.metricKey === 'colors') {
      html = `<b>DARK</b> ${(raw.dark_share * 100).toFixed(0)}%`;
    } else if (beat && beat.metricKey === 'symmetry') {
      html = `<b>SYM</b> ${raw.symmetry.toFixed(3)}`;
    } else if (beat && beat.metricKey === 'blood') {
      html = `<b>KNIFE</b> ${raw.nova_knife.toFixed(2)}`;
    } else if (beat && beat.metricKey === 'medium') {
      html = `<b>PAINT</b> ${raw.p_painted.toFixed(2)}`;
    } else if (beat && beat.metricKey === 'census') {
      html = `<b>CREATURE</b> ${raw.creature_score.toFixed(2)}`;
    }
    el.counter.innerHTML = html;
    el.counter.style.opacity = html ? '1' : '0';
  }
}

/**
 * 4-act choreography:
 * I  hero ¾  (0–0.12)
 * II face-on (0.12–0.22)
 * III peel one layer/beat (0.22–0.82)
 * IV apertura / archivo (0.82–1) — hinged open, not explode
 */
function updateScene(p) {
  const t = clock.elapsedTime;
  const breathe = reducedMotion ? 0 : Math.sin(t * 0.65) * 0.014;

  const faceOn = remap(p, 0.1, 0.2);
  const peelZone = remap(p, 0.22, 0.8);
  const open = remap(p, 0.8, 0.96);

  const rotY = lerp(-0.52, -0.015, faceOn) + peelZone * 0.03 + open * -0.1;
  const rotX = lerp(-0.1, -0.008, faceOn) + peelZone * -0.02 + open * -0.05;
  const rotZ = lerp(0.015, 0.0, faceOn) + open * 0.02;

  vhsGroup.rotation.set(rotX + breathe, rotY, rotZ + breathe * 0.25);

  const posX =
    lerp(isMobile ? 0 : 0.5, isMobile ? 0 : -0.02, faceOn) +
    peelZone * (isMobile ? 0 : -0.16) +
    open * (isMobile ? 0 : 0.12);
  const posY = lerp(0.04, 0.02, faceOn) + open * 0.06;
  const posZ = lerp(0, 0.32, faceOn) - peelZone * 0.1 - open * 0.28;
  vhsGroup.position.set(posX, posY + breathe, posZ);

  const baseScale = isMobile ? 0.9 : 1.06;
  const scale = baseScale * lerp(1, 1.05, faceOn) * lerp(1, 0.94, open);
  vhsGroup.scale.setScalar(scale);

  // --- Lid apertura (hinged) ---
  const openAngle = open * (isMobile ? -1.05 : -1.25); // radians ~72–72°
  lidPivot.rotation.y = openAngle;

  // Interior / archive card emphasis on open
  const card = interiorGroup.getObjectByName('archiveCard');
  if (card) {
    card.material.opacity = lerp(0.15, 0.95, open);
    card.position.x = lerp(0.08, 0.35, open);
    card.position.z = lerp(-BOX_D / 2 + WALL + 0.08, 0.15, open);
    card.rotation.y = open * -0.15;
  }

  if (contactShadow) {
    contactShadow.material.opacity = lerp(0.9, 0.45, open);
    contactShadow.scale.set(lerp(1, 1.25, open), 1, lerp(1, 1.1, open));
  }

  // --- Layer peel: one beat at a time, gentle lift (not chaos) ---
  const layerKeys = ['ocr', 'faces', 'colors', 'symmetry', 'blood', 'medium'];
  const windows = {
    ocr: [0.22, 0.32],
    faces: [0.32, 0.42],
    colors: [0.42, 0.52],
    symmetry: [0.52, 0.62],
    blood: [0.62, 0.72],
    medium: [0.72, 0.82],
  };

  setLayerOpacity('cover', lerp(1, 0.55, peelZone) * lerp(1, 0.35, open));

  layerKeys.forEach((key, idx) => {
    const [a, b] = windows[key];
    const mid = (a + b) / 2;
    const on = smoothstep(a, a + 0.025, p) * (1 - smoothstep(b - 0.02, b + 0.01, p));
    // Soft residual after each beat during peel
    const residual = smoothstep(a, mid, p) * (1 - open) * 0.08;
    setLayerOpacity(key, Math.max(on, residual) * (1 - open * 0.85));

    const mesh = layers[key];
    if (!mesh) return;
    const lift = on * 0.55;
    // Gentle peel toward camera + slight offset per layer — orderly, not explode
    const side = idx % 2 === 0 ? -1 : 1;
    mesh.position.x = side * lift * 0.12 + open * (0.55 + idx * 0.28);
    mesh.position.y = lift * 0.08 + open * (0.35 - idx * 0.12);
    mesh.position.z = mesh.userData.baseZ + lift * 0.35 + open * (0.4 + idx * 0.08);
    mesh.rotation.z = side * lift * 0.04 + open * side * 0.06;
    mesh.rotation.y = open * side * 0.12;
  });

  // Cover settles into archivo fan
  if (layers.cover) {
    layers.cover.position.x = open * 0.25;
    layers.cover.position.y = open * 0.2;
    layers.cover.position.z = layers.cover.userData.baseZ + open * 0.25;
    layers.cover.rotation.y = open * 0.08;
  }

  const camZ = lerp(7.8, 6.5, faceOn) - peelZone * 0.12 + open * 0.45;
  const camX =
    lerp(0.12, -0.02, faceOn) + (reducedMotion ? 0 : Math.sin(t * 0.1) * 0.025) + open * 0.2;
  const camY = 0.05 + (reducedMotion ? 0 : Math.cos(t * 0.09) * 0.02) + open * 0.07;
  camera.position.set(camX, camY, camZ);
  camera.lookAt(vhsGroup.position.x * 0.2, vhsGroup.position.y * 0.1, open * 0.12);

  if (keyLight) keyLight.intensity = lerp(2.8, 2.2, open);
  if (rimLight) rimLight.intensity = lerp(48, 30, faceOn) + open * 12;

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
  if (idx !== activeBeat) {
    activeBeat = idx;
    beatEls.forEach((sec, i) => sec.classList.toggle('active', i === idx));
    const beat = metricsData.beats[idx];
    const actMeta = (metricsData.acts || []).find((a) => a.id === ['hero', 'face', 'peel', 'archivo'][beat.act - 1]) ||
      (metricsData.acts || []).find((a) => p >= a.range[0] && p < a.range[1]);
    el.beatLabel.textContent = `TRACK ${String(idx + 1).padStart(2, '0')} · ${beat.kicker}`;
    if (el.actLabel) {
      const act = metricsData.acts && metricsData.acts[beat.act - 1];
      el.actLabel.textContent = act ? act.label : `Acto ${beat.act}`;
    }
    const cov = usingMediaCover ? 'Media' : 'poster';
    el.tapeStamp.textContent = `${metricsData.title} · ${metricsData.year} · id ${metricsData.id} · ${cov}`;
  }
  const beat = metricsData.beats[activeBeat];
  updateOverlays(p, beat ? beat.id : null);
}

function tick() {
  const dt = Math.min(clock.getDelta(), 0.05);
  const lag = reducedMotion ? 1 : isMobile ? 0.2 : 0.11;
  scrollProgress = lerp(scrollProgress, targetProgress, 1 - Math.pow(1 - lag, dt * 60));
  updateScene(scrollProgress);
  if (dust) dust.rotation.y = clock.elapsedTime * 0.028;
  renderer.render(scene, camera);
}

function onResize() {
  if (!camera || !renderer) return;
  camera.aspect = window.innerWidth / window.innerHeight;
  camera.updateProjectionMatrix();
  renderer.setSize(window.innerWidth, window.innerHeight);
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, isMobile ? 1.4 : 2));
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

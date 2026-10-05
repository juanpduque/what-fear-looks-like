import { pct, num, creatureLabels, posterSrc } from '../shared/posters.js';
import { resolveFaces, faceLab } from './faces.js';

const t = (...args) =>
  typeof window.t === 'function' ? window.t(...args) : args[0];

export const BAND_COLORS = ['#e02430', '#e5a00d', '#8fb05a', '#5a9eb0', '#b08ad4', '#9a958a'];

export function hueBands() {
  if (window.HUEBANDS?.length) return window.HUEBANDS;
  return [
    { short: t('hue_reds'), c: BAND_COLORS[0] },
    { short: t('hue_warm_short'), c: BAND_COLORS[1] },
    { short: t('hue_greens'), c: BAND_COLORS[2] },
    { short: t('hue_blues'), c: BAND_COLORS[3] },
    { short: t('hue_purples'), c: BAND_COLORS[4] },
    { short: t('hue_dark_short'), c: BAND_COLORS[5] },
  ];
}

function bandBarHtml(bands) {
  const cols = hueBands();
  return (bands || [])
    .map((v, i) => {
      const name = cols[i]?.short || '';
      const c = cols[i]?.c || BAND_COLORS[i] || '#888';
      return `<i style="width:${(v || 0) * 100}%;background:${c}" title="${name} ${pct(v)}"></i>`;
    })
    .join('');
}

function boxStyle(x, y, w, h) {
  const L = Math.max(0, x * 100);
  const T = Math.max(0, y * 100);
  const W = Math.min(100 - L, Math.max(1, w * 100));
  const H = Math.min(100 - T, Math.max(1, h * 100));
  return `left:${L.toFixed(1)}%;top:${T.toFixed(1)}%;width:${W.toFixed(1)}%;height:${H.toFixed(1)}%`;
}

function dimSvg(maskId, boxes) {
  const holes = (boxes || [])
    .map(([x, y, w, h]) => {
      const X = Math.max(0, x * 100);
      const Y = Math.max(0, y * 100);
      const W = Math.min(100 - X, Math.max(0, w * 100));
      const H = Math.min(100 - Y, Math.max(0, h * 100));
      return `<rect x="${X.toFixed(2)}" y="${Y.toFixed(2)}" width="${W.toFixed(2)}" height="${H.toFixed(2)}" fill="black"/>`;
    })
    .join('');
  return `<svg class="lk-dimsvg" viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true"><defs><mask id="${maskId}"><rect width="100" height="100" fill="white"/>${holes}</mask></defs><rect width="100" height="100" fill="rgba(7,8,11,.72)" mask="url(#${maskId})"/></svg>`;
}

function massMarks(comp, { origin } = {}) {
  const mx = (comp.mx ?? 0.5) * 100;
  const my = (comp.my ?? 0.5) * 100;
  const ring = origin
    ? `<div class="lk-origin" title="${t('lab_geom_center')}"></div>`
    : '';
  return `${ring}<div class="lk-mass" style="left:${mx}%;top:${my}%"></div>`;
}

export function preferredCreatureBoxes(p, a) {
  const creature = a.creature || p[6];
  const src = (window.CREATURE_BOXES && window.CREATURE_BOXES[String(p[7])]) || a.cboxes || [];
  const cboxes = Array.isArray(src) ? src : [];
  if (!cboxes.length || !creature) return cboxes;
  const hit = cboxes.filter((b) => (b.label || '') === creature);
  return hit.length ? hit : cboxes;
}

export function creatureLabel(p, a) {
  const creature = a.creature || p[6];
  if (!creature || creature === 'uncertain') return t('none_detected');
  return creatureLabels()[creature] || creature.replace(/_/g, ' ');
}

/** Pipeline title boxes missing / wrong for a few specimens; coords match the corpus JPEG shown on the site. */
const TITLE_BOX_OVERRIDE = {
  948: { tx: 0.08, tt: 0.79, tw: 0.84, th: 0.1 },
  // OCR ran on alternate TMDB art ("DRACULA" bat banner); site shows "Horror of Dracula".
  11868: { tx: 0.05, tt: 0.855, tw: 0.9, th: 0.085 },
};

export function titleBox(comp, tmdbId) {
  const over = TITLE_BOX_OVERRIDE[Number(tmdbId)];
  const src = over ? { ...comp, ...over } : comp;
  const has =
    src.tt != null &&
    src.tt >= 0 &&
    src.tw > 0 &&
    src.th > 0 &&
    src.tx != null &&
    src.tx >= 0;
  if (!has) return null;
  const left = Math.max(0, src.tx * 100);
  const top = Math.max(0, src.tt * 100);
  const width = Math.min(100 - left, src.tw * 100);
  const height = Math.min(100 - top, src.th * 100);
  return { left, top, width, height, labTop: Math.min(92, top + height + 1.5) };
}

/** HTML for every analysis overlay. Layers stay off until setActiveLayers(). */
export function buildLayersHtml(p, a) {
  const bands = a.bands || [];
  const palArr = a.pal && a.pal.length ? a.pal : [p[1]];
  const palFloat = palArr
    .map((c) => `<span style="background:${c}" title="${c}"></span>`)
    .join('');
  const palHandles = palArr
    .map(
      (c, i) =>
        `<i class="lk-handle" data-i="${i}" style="left:${18 + (i % 5) * 16}%;top:88%;background:${c}"></i>`,
    )
    .join('');
  const creature = a.creature || p[6];
  const cLabel = creatureLabel(p, a);
  const comp = a.comp || {};
  const faces = resolveFaces(a, p);
  const darkPct = Math.round((a.dark || 0) * 100);
  const box = titleBox(comp, p[7]);
  const textBandStyle = box
    ? `left:${box.left.toFixed(1)}%;top:${box.top.toFixed(1)}%;width:${box.width.toFixed(1)}%;height:${box.height.toFixed(1)}%;right:auto`
    : 'display:none';
  const tLabTop = box ? box.labTop : 6;
  const tLabLeft = box ? Math.max(2, box.left) : 4;
  const faceLabText = faceLab(a, p);
  const fboxes = faces.fboxes;
  const faceBoxesHtml = fboxes
    .map(([x, y, w, h]) => `<div class="lk-facebox" style="${boxStyle(x, y, w, h)}"></div>`)
    .join('');
  let faceLabStyle = 'top:8%;left:50%;transform:translateX(-50%)';
  if (fboxes.length) {
    const [fx, fy, , fh] = fboxes[0];
    const labTop = Math.min(92, Math.max(2, (fy + fh) * 100 + 1.5));
    const labLeft = Math.max(2, Math.min(70, fx * 100));
    faceLabStyle = `top:${labTop.toFixed(1)}%;left:${labLeft.toFixed(1)}%`;
  } else if (faces.n > 0 && faces.source === 'rek') {
    faceLabStyle = 'top:8%;left:4%';
  }
  const cboxesPref = preferredCreatureBoxes(p, a);
  const creatureBoxesHtml = cboxesPref
    .slice(0, 3)
    .map((b) => {
      const raw = b.box || b;
      const [x, y, w, h] = Array.isArray(raw) ? raw : [0, 0, 0, 0];
      const L = Math.max(0, x * 100);
      const T = Math.max(0, y * 100);
      const lab = creatureLabels()[b.label] || (b.label || '').replace(/_/g, ' ');
      const sc = b.score != null ? ` ${pct(b.score)}` : '';
      const labClass = T < 8 ? ' topish' : '';
      return `<div class="lk-cbox" style="${boxStyle(x, y, w, h)}"><span class="lk-cbox-lab${labClass}">${lab}${sc}</span></div>`;
    })
    .join('');
  const creatureLabHtml = cboxesPref.length
    ? `<div class="lk-lab blood" style="top:6%;right:4%">${t('lab_creature', { c: cLabel })}${a.cscore != null ? ' · ' + pct(a.cscore) : ''} · OWL</div>`
    : `<div class="lk-lab amber" style="top:45%;left:50%;transform:translate(-50%,-50%)">${t('lab_creature', { c: cLabel })}${a.cscore != null ? ' · ' + pct(a.cscore) : ''}</div>`;
  const mediumLab =
    a.painted == null
      ? t('lab_medium_na')
      : (a.painted >= 0.5 ? t('lookup_painted') + ' ' : t('lookup_photo_mixed') + ' ') + pct(a.painted);
  const textLab = box
    ? t('lab_title_box_text', { v: pct(comp.txt) })
    : t('lab_textlike_pending', { v: pct(comp.txt) });
  const sem = a.sem || {};
  const semTags = Object.entries(sem)
    .filter(([, v]) => v > 0)
    .sort((a, b) => b[1] - a[1])
    .map(
      ([k, v], i) =>
        `<div class="lk-lab blood" style="top:${(8 + i * 7).toFixed(1)}%;left:4%">${k.replace(/_/g, ' ')} ${pct(v)}</div>`,
    )
    .join('');
  const pose = a.pose;
  let poseHtml;
  if (!pose) {
    poseHtml = `<div class="lk-lab amber" style="top:8%;left:4%">${t('lab_pose_skip')}</div>`;
  } else if (!pose.n) {
    poseHtml = `<div class="lk-lab amber" style="top:8%;left:4%">${t('lab_pose_none')}</div>`;
  } else {
    poseHtml = `<div class="lk-lab amber" style="top:8%;left:4%">${t('lab_pose_n', { n: pose.n })}</div>
          <div class="lk-lab" style="top:16%;left:4%">${t('lab_pose_spread', { v: pose.spread == null ? '—' : num(pose.spread, 2) })}</div>
          <div class="lk-lab" style="top:24%;left:4%">${t('lab_pose_asym', { v: pose.asym == null ? '—' : num(pose.asym, 2) })}</div>
          <div class="lk-lab" style="top:32%;left:4%">${t('lab_pose_conf', { v: pose.conf == null ? '—' : pct(pose.conf) })}</div>`;
  }

  const titleHole = box
    ? [[box.left / 100, box.top / 100, box.width / 100, box.height / 100]]
    : [];
  const creatureHoles = cboxesPref.slice(0, 3).map((b) => {
    const raw = b.box || b;
    return Array.isArray(raw) ? raw : [0, 0, 0, 0];
  });
  const poseHoles = pose?.n ? fboxes : [];

  return `<div class="lk-ov" id="lk-ov">
        <div class="lk-layer" data-layer="L"><div class="lk-lab" style="top:6%;left:4%">L* ${a.L ?? p[4]}</div></div>
        <div class="lk-layer" data-layer="palette">
          <canvas class="lk-heat lk-poster" data-heat="poster"></canvas>
          <div class="lk-handles">${palHandles}</div>
          <div class="lk-lab" style="top:6%;left:4%">${t('lab_palette_regions')}</div>
          <div class="lk-lab blood" style="top:6%;right:4%">${t('lab_near_black_pct', { n: darkPct })}</div>
        </div>
        <div class="lk-layer" data-layer="heat-dark">
          <canvas class="lk-heat" data-heat="dark"></canvas>
          <div class="lk-lab blood" style="top:6%;right:4%">${t('lab_heat_dark', { n: darkPct })}</div>
        </div>
        <div class="lk-layer" data-layer="heat-red">
          <canvas class="lk-heat" data-heat="red"></canvas>
          <div class="lk-lab blood" style="bottom:8%;left:4%">${t('lab_heat_red', { v: pct(a.red) })}</div>
        </div>
        <div class="lk-layer" data-layer="heat-L">
          <canvas class="lk-heat" data-heat="L"></canvas>
          <div class="lk-lab" style="top:6%;left:4%">${t('lab_heat_L', { L: a.L ?? p[4] })}</div>
        </div>
        <div class="lk-layer" data-layer="sat">
          <canvas class="lk-heat" data-heat="sat"></canvas>
          <div class="lk-lab" style="top:6%;left:4%">${t('lab_saturation', { v: pct(a.sat) })}</div></div>
        <div class="lk-layer" data-layer="bands">${dimSvg('lk-mask-bands', [])}<div class="lk-bandsov">${bandBarHtml(bands)}</div>
          <div class="lk-palfloat">${palFloat}</div>
          <div class="lk-lab" style="top:6%;left:4%">${t('lab_hue_families')}</div></div>
        <div class="lk-layer" data-layer="faces">${dimSvg('lk-mask-faces', fboxes)}${faceBoxesHtml}
          <div class="lk-lab${faces.source === 'rek' ? ' amber' : ''}" style="${faceLabStyle}">${faceLabText}</div></div>
        <div class="lk-layer" data-layer="creature">${dimSvg('lk-mask-creature', creatureHoles)}${creatureBoxesHtml}${creatureLabHtml}</div>
        <div class="lk-layer" data-layer="medium">${dimSvg('lk-mask-medium', [])}
          <div class="lk-lab" style="top:8%;left:4%">${mediumLab}</div></div>
        <div class="lk-layer" data-layer="text">${dimSvg('lk-mask-text', titleHole)}<div class="lk-textband" style="${textBandStyle}"></div>
          <div class="lk-lab blood" style="top:${tLabTop.toFixed(1)}%;left:${tLabLeft.toFixed(1)}%">${textLab}</div></div>
        <div class="lk-layer" data-layer="sym">
          <div class="lk-mirror"><img src="${posterSrc(p, 'm')}" alt=""></div>
          <div class="lk-fold"></div>
          <div class="lk-lab amber" style="top:6%;left:4%">${t('lab_symmetry', { v: pct(comp.sym) })}</div>
          <div class="lk-lab" style="top:6%;right:4%">${t('lab_symmetry_mirror')}</div></div>
        <div class="lk-layer" data-layer="neg">
          <canvas class="lk-heat" data-heat="neg"></canvas>
          <div class="lk-lab" style="top:6%;left:4%">${t('lab_negative_space', { v: pct(comp.neg) })}</div></div>
        <div class="lk-layer" data-layer="cx">
          <canvas class="lk-heat" data-heat="cx"></canvas>
          <div class="lk-lab" style="top:6%;left:4%">${t('lab_complexity', { v: num(comp.cx, 2) })}</div></div>
        <div class="lk-layer" data-layer="bal">${dimSvg('lk-mask-bal', [])}${massMarks(comp, { origin: true })}
          <div class="lk-lab amber" style="top:6%;left:4%">${t('lab_balance', { v: pct(comp.bal) })}</div>
          <div class="lk-lab" style="top:14%;left:4%">${t('lab_geom_center')}</div></div>
        <div class="lk-layer" data-layer="harm">${dimSvg('lk-mask-harm', [])}
          <div class="lk-lab" style="top:6%;left:4%">${t('lab_harmony', { v: pct(comp.harm) })}</div></div>
        <div class="lk-layer" data-layer="align">${dimSvg('lk-mask-align', [])}
          <div class="lk-lab" style="top:6%;left:4%">${t('lab_alignment', { v: pct(comp.align) })}</div></div>
        <div class="lk-layer" data-layer="thirds">${dimSvg('lk-mask-thirds', [])}<div class="lk-thirds"></div>
          <div class="lk-lab amber" style="bottom:8%;left:4%">${t('lab_thirds_dist', { v: num(comp.thirds, 2) })}</div></div>
        <div class="lk-layer" data-layer="diag">${dimSvg('lk-mask-diag', [])}<div class="lk-diag"></div>
          <div class="lk-lab blood" style="top:6%;left:4%">${t('lab_diagonal', { v: pct(comp.diag) })}</div></div>
        <div class="lk-layer" data-layer="pyr">${dimSvg('lk-mask-pyr', [])}
          <div class="lk-lab amber" style="top:6%;left:4%">${t('lab_pyramid', { v: num(comp.pyr, 2) })}</div></div>
        <div class="lk-layer" data-layer="mass">${dimSvg('lk-mask-mass', [])}${massMarks(comp)}
          <div class="lk-lab blood" style="top:6%;left:4%">${t('lab_mass_center')}</div></div>
        <div class="lk-layer" data-layer="blood"><div class="lk-wash"></div>
          <div class="lk-lab blood" style="bottom:8%;left:4%">${t('lab_clip_blood', { v: pct(sem.blood) })}</div></div>
        <div class="lk-layer" data-layer="sem">${dimSvg('lk-mask-sem', [])}${semTags || `<div class="lk-lab amber" style="top:8%;left:4%">${t('lab_semantic_none')}</div>`}</div>
        <div class="lk-layer" data-layer="pose">${dimSvg('lk-mask-pose', poseHoles)}${pose?.n ? faceBoxesHtml : ''}${poseHtml}</div>
      </div>`;
}

export const BEAT_LAYERS = {
  object: [],
  color: ['palette'],
  faces: ['faces'],
  letter: ['text'],
  creature: ['creature'],
  composition: [],
  comp_thirds: ['thirds'],
  comp_diag: ['diag'],
  comp_sym: ['sym'],
  comp_bal: ['bal'],
  comp_neg: ['neg'],
  pose: ['pose'],
};

/** Sub-views per beat. `heat` dims the bitmap under a pixel map.
 *  Only beats with real poster overlays get modes; label-only instruments are scroll beats. */
export const BEAT_MODES = {
  color: [
    { id: 'palette', layers: ['palette'] },
    { id: 'dark', layers: ['heat-dark'], heat: true },
    { id: 'red', layers: ['heat-red'], heat: true },
    { id: 'bright', layers: ['heat-L'], heat: true },
    { id: 'sat', layers: ['sat'], heat: true },
    { id: 'bands', layers: ['bands'] },
    { id: 'blood', layers: ['blood'], heat: true },
  ],
  creature: [
    { id: 'creature', layers: ['creature'] },
    { id: 'sem', layers: ['sem'] },
  ],
};

export const COLOR_MODE_LAYERS = Object.fromEntries(
  (BEAT_MODES.color || []).map((m) => [m.id, m.layers]),
);

export function beatMode(beatId, modeId) {
  const modes = BEAT_MODES[beatId] || [];
  if (!modes.length) return null;
  return modes.find((m) => m.id === modeId) || modes[0];
}

export function setActiveLayers(ov, names, a) {
  if (!ov) return;
  const want = new Set(names || []);
  ov.querySelectorAll('.lk-layer').forEach((el) => {
    el.classList.toggle('on', want.has(el.dataset.layer));
  });
  if (want.has('dark')) {
    const h = Math.max(8, Math.min(92, Math.round((a?.dark || 0) * 100)));
    const scrim = ov.querySelector('[data-layer="dark"] .lk-scrim');
    if (scrim) scrim.style.setProperty('--h', h + '%');
  }
}

export function applyArtFilter(art, view, a) {
  if (!art) return;
  if (view === 'L') {
    art.style.filter = `brightness(${Math.max(0.35, Math.min(1.35, (a.L || 50) / 50))})`;
    return;
  }
  art.style.removeProperty('filter');
}

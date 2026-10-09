import { pct, num, creatureLabels, posterSrc } from '../shared/posters.js';
import { titleInkFor } from './data.js';
import { resolveFaces, faceLab, novaFaceCount } from './faces.js';
import { formatNovaCreature, novaCreature, novaOcr, novaTitle, novaTypo } from './nova.js';
import { clipToJevSlot, formatJevCreature, jevCreature, showJevCreatureLab } from './jev.js';

const t = (...args) =>
  typeof window.t === 'function' ? window.t(...args) : args[0];

function esc(s) {
  return String(s ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

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

export function bandBarHtml(bands) {
  const cols = hueBands();
  return (bands || [])
    .map((v, i) => {
      const name = cols[i]?.short || '';
      const c = cols[i]?.c || BAND_COLORS[i] || '#888';
      return `<i style="width:${(v || 0) * 100}%;background:${c}" title="${name} ${pct(v)}"></i>`;
    })
    .join('');
}

/** Dominant Color River bin on this sheet (pixel share, not k-means). */
export function topHueFamily(a) {
  const bands = a?.bands || [];
  const cols = hueBands();
  const n = Math.min(bands.length, cols.length);
  let best = 0;
  for (let i = 1; i < n; i++) {
    if ((bands[i] || 0) > (bands[best] || 0)) best = i;
  }
  return {
    i: best,
    name: n ? cols[best].short : '—',
    v: n ? bands[best] || 0 : 0,
    n: cols.length,
  };
}

export function bandLegendHtml(bands) {
  const cols = hueBands();
  const top = topHueFamily({ bands });
  return `<div class="lk-bandleg">${(bands || [])
    .map((v, i) => {
      const name = cols[i]?.short || '';
      const c = cols[i]?.c || BAND_COLORS[i] || '#888';
      const on = i === top.i ? ' is-top' : '';
      return `<span class="${on}"><i style="background:${c}"></i>${esc(name)} ${pct(v)}</span>`;
    })
    .join('')}</div>`;
}

function boxStyle(x, y, w, h) {
  const L = Math.max(0, x * 100);
  const T = Math.max(0, y * 100);
  const W = Math.min(100 - L, Math.max(1, w * 100));
  const H = Math.min(100 - T, Math.max(1, h * 100));
  return `left:${L.toFixed(1)}%;top:${T.toFixed(1)}%;width:${W.toFixed(1)}%;height:${H.toFixed(1)}%`;
}

/** COCO-17 bones (ViTPose). Indices match pipeline/vitpose_dynamism_score.py. */
const COCO_BONES = [
  [0, 1],
  [0, 2],
  [1, 3],
  [2, 4],
  [5, 6],
  [5, 7],
  [7, 9],
  [6, 8],
  [8, 10],
  [5, 11],
  [6, 12],
  [11, 12],
  [11, 13],
  [13, 15],
  [12, 14],
  [14, 16],
];
const KPT_MIN = 0.45;
const KPT_MIN_COUNT = 5;
const POSE_MEAN_MIN = 0.3;
const POSE_SPREAD_MAX = 1.5;

function kptVisible(kpts, i) {
  const p = kpts[i];
  return Array.isArray(p) && p.length >= 3 && Number(p[2]) >= KPT_MIN;
}

/**
 * Largest YOLO box on a crowd sheet is often several people glued together
 * (Freaks 136). ViTPose then locks onto one figure inside that blob.
 */
export function isGroupPrimary(pose) {
  if (!pose || (pose.n || 0) < 3) return false;
  const box = pose.box;
  if (!Array.isArray(box) || box.length !== 4) return false;
  const area = box[2] * box[3];
  if (area < 0.18) return false;
  return pose.spread != null && pose.spread < 0.35;
}

/** Drop hallucinated figures (The Thing: mean 0.26, spread 4.6). */
export function usableSkeleton(kpts, pose) {
  if (!Array.isArray(kpts) || kpts.length < 5) return null;
  const mean = pose?.conf;
  const spread = pose?.spread;
  if (mean != null && mean < POSE_MEAN_MIN && spread != null && spread > POSE_SPREAD_MAX) {
    return null;
  }
  let n = 0;
  for (let i = 0; i < kpts.length; i++) {
    if (kptVisible(kpts, i)) n += 1;
  }
  return n >= KPT_MIN_COUNT ? kpts : null;
}

/** ViTPose sometimes remaps keypoints to the right of the YOLO person box (Exorcist 9552). */
export function alignKeypointsToBox(kpts, box) {
  if (!Array.isArray(kpts) || !box || box.length !== 4) return kpts;
  const [bx, by, bw, bh] = box;
  if (bw <= 0 || bh <= 0) return kpts;
  const vis = [];
  for (let i = 0; i < kpts.length; i++) {
    if (kptVisible(kpts, i)) vis.push(kpts[i]);
  }
  if (vis.length < 3) return kpts;
  const xs = vis.map((p) => p[0]).sort((a, b) => a - b);
  const ys = vis.map((p) => p[1]).sort((a, b) => a - b);
  const kcx = xs[Math.floor(xs.length / 2)];
  const kcy = ys[Math.floor(ys.length / 2)];
  if (kcx >= bx && kcx <= bx + bw && kcy >= by && kcy <= by + bh) return kpts;
  const dx = bx + bw / 2 - kcx;
  const dy = by + bh / 2 - kcy;
  return kpts.map((p) => [p[0] + dx, p[1] + dy, p[2]]);
}

function kptBox(kpts) {
  const xs = [];
  const ys = [];
  for (let i = 0; i < kpts.length; i++) {
    if (!kptVisible(kpts, i)) continue;
    xs.push(kpts[i][0]);
    ys.push(kpts[i][1]);
  }
  if (!xs.length) return null;
  const pad = 0.04;
  const x = Math.max(0, Math.min(...xs) - pad);
  const y = Math.max(0, Math.min(...ys) - pad);
  const x1 = Math.min(1, Math.max(...xs) + pad);
  const y1 = Math.min(1, Math.max(...ys) + pad);
  return [x, y, Math.max(0.02, x1 - x), Math.max(0.02, y1 - y)];
}

/** Stick figure over the poster. Joints stay circular (HTML); bones stretch with the sheet. */
export function skeletonHtml(kpts) {
  if (!Array.isArray(kpts) || kpts.length < 5) return '';
  const lines = COCO_BONES.filter(([a, b]) => kptVisible(kpts, a) && kptVisible(kpts, b))
    .map(([a, b]) => {
      const [x1, y1] = kpts[a];
      const [x2, y2] = kpts[b];
      return `<line x1="${(x1 * 100).toFixed(2)}" y1="${(y1 * 100).toFixed(2)}" x2="${(x2 * 100).toFixed(2)}" y2="${(y2 * 100).toFixed(2)}"/>`;
    })
    .join('');
  const joints = kpts
    .map((p, i) => {
      if (!kptVisible(kpts, i)) return '';
      return `<i class="lk-joint" style="left:${(p[0] * 100).toFixed(1)}%;top:${(p[1] * 100).toFixed(1)}%"></i>`;
    })
    .join('');
  if (!lines && !joints) return '';
  return `<svg class="lk-skeleton" viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true">${lines}</svg>${joints}`;
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

/** Min OWL box score; below this FP rate dominates (see docs/METRIC_AGREEMENTS.md). */
const CREATURE_BOX_MIN_SCORE = 0.3;
const WEAPON_BOX_MIN_SCORE = 0.3;

/**
 * OWL boxes only when they match CLIP census label.
 * Never fall back to all OWL boxes (unrelated FP overlays).
 * No match → empty; UI shows CLIP label without boxes.
 */
export function preferredCreatureBoxes(p, a) {
  const creature = a.creature || p[6];
  if (!creature || creature === 'uncertain' || creature === 'none') return [];
  const src = a.geomAlt
    ? a.cboxes || []
    : (window.CREATURE_BOXES && window.CREATURE_BOXES[String(p[7])]) || a.cboxes || [];
  const cboxes = Array.isArray(src) ? src : [];
  if (!cboxes.length) return [];
  return cboxes.filter((b) => {
    if ((b.label || '') !== creature) return false;
    const sc = b.score;
    return sc == null || Number(sc) >= CREATURE_BOX_MIN_SCORE;
  });
}

function formatWeaponLabel(label) {
  return String(label || '').replace(/_/g, ' ') || t('none_detected');
}

/** Rek presence flag (rek_weapon ≥ 0.5). CLIP clip_weapon is a second family score. */
export function rekWeaponPresent(a) {
  return Array.isArray(a?.rek?.flags) && a.rek.flags.includes('weapon');
}

/**
 * OWL weapon boxes at the same score floor as creatures.
 * Presence stays Rek/CLIP — these boxes are geometry, not a count.
 */
export function preferredWeaponBoxes(p, a) {
  const src = a.geomAlt
    ? a.wboxes || []
    : (window.WEAPON_BOXES && window.WEAPON_BOXES[String(p[7])]) || a.wboxes || [];
  const boxes = Array.isArray(src) ? src : [];
  return boxes.filter((b) => {
    const sc = b.score;
    return sc == null || Number(sc) >= WEAPON_BOX_MIN_SCORE;
  });
}

/** CLIP p_painted → three-way medium. Same cuts as pipeline clip_medium_slot. Rescue only. */
export function mediumSlot(painted) {
  if (painted == null) return null;
  const p = Number(painted);
  if (!Number.isFinite(p)) return null;
  if (p >= 0.6) return 'painted';
  if (p <= 0.4) return 'photo';
  return 'mixed';
}

/** Autopsy medium: Custom Labels owns the slot; CLIP p_painted is fallback. */
export function resolveMedium(a) {
  const cl = a?.medium_cl;
  if (cl?.pred === 'painted' || cl?.pred === 'photo' || cl?.pred === 'composite') {
    return { source: 'cl', pred: cl.pred, conf: cl.conf };
  }
  const slot = mediumSlot(a?.painted);
  if (!slot) return { source: null, pred: null, conf: null };
  return { source: 'clip', pred: slot, conf: a.painted };
}

export function mediumLabel(a) {
  const m = resolveMedium(a);
  if (!m.pred) return t('lab_medium_na');
  const score = m.conf == null ? '' : ` ${pct(m.conf)}`;
  return `${t(`lookup_${m.pred}`)}${score}`;
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
  // attributes/Rek title-box scored 0 (cursive around the shoe). Lines exist: Dance|or|Die.
  145850: { tx: 0.03, tt: 0.02, tw: 0.94, th: 0.40 },
  // Published box sat on the bottom band; site one-sheet has THE EXORCIST at the top.
  9552: { tx: 0.06, tt: 0.015, tw: 0.88, th: 0.22 },
  // EasyOCR/Rek kept only RETURN; HORROR HIGH is giant display type behind the figure.
  45878: { tx: 0.04, tt: 0.19, tw: 0.7, th: 0.56 },
};

export function titleBox(comp, tmdbId) {
  const over = tmdbId == null ? null : TITLE_BOX_OVERRIDE[Number(tmdbId)];
  const ink = over || tmdbId == null ? null : titleInkFor(tmdbId);
  const src = over ? { ...comp, ...over } : ink ? { ...comp, ...ink } : comp;
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
export function buildLayersHtml(p, a, opts = {}) {
  const sheetSrc = opts.sheetSrc || posterSrc(p, 'm');
  const bands = a.bands || [];
  const palArr = a.pal && a.pal.length ? a.pal : [p[1]];
  const topBand = topHueFamily(a);
  const palSwatch = palArr
    .map(
      (c, i) =>
        `<span title="${esc(c)}"><b>${i + 1}</b><i style="background:${c}"></i></span>`,
    )
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
  const box = titleBox(comp, a.geomAlt ? null : p[7]);
  const textBandStyle = box
    ? `left:${box.left.toFixed(1)}%;top:${box.top.toFixed(1)}%;width:${box.width.toFixed(1)}%;height:${box.height.toFixed(1)}%;right:auto`
    : 'display:none';
  const tLabTop = box ? box.labTop : 6;
  const tLabLeft = box ? Math.max(2, box.left) : 4;
  const faceLabText = faceLab(a, p);
  const novaN = novaFaceCount(a);
  const novaLabHtml =
    novaN == null
      ? ''
      : `<div class="lk-lab${novaN !== faces.yunet ? ' amber' : ''}" style="top:6%;right:4%">${t('lab_faces_nova', { n: novaN })}</div>`;
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
  const novaC = novaCreature(a);
  const clipSlot = !creature || creature === 'uncertain' || creature === 'none' ? 'none' : creature;
  const jevC = jevCreature(a);
  const jevSlot = clipToJevSlot(a, p);
  const showJev = showJevCreatureLab(a, p);
  const jevCreatureLabHtml = showJev
    ? `<div class="lk-lab${jevC !== jevSlot ? ' amber' : ''}" style="top:6%;left:4%">${t('lab_creature_jev', { c: formatJevCreature(jevC) })}</div>`
    : '';
  const novaCreatureLabHtml =
    novaC == null
      ? ''
      : `<div class="lk-lab${novaC !== clipSlot ? ' amber' : ''}" style="top:${showJev ? '11' : '6'}%;left:4%">${t('lab_creature_nova', { c: formatNovaCreature(novaC) })}</div>`;
  const creatureLabHtml = cboxesPref.length
    ? `<div class="lk-lab blood" style="top:6%;right:4%">${t('lab_creature', { c: cLabel })}${a.cscore != null ? ' · ' + pct(a.cscore) : ''} · OWL</div>`
    : `<div class="lk-lab amber" style="top:45%;left:50%;transform:translate(-50%,-50%)">${t('lab_creature', { c: cLabel })}${a.cscore != null ? ' · ' + pct(a.cscore) : ''}</div>`;
  const mediumLab = mediumLabel(a);
  const textLab = box
    ? t('lab_title_box_text', { v: pct(comp.txt) })
    : t('lab_textlike_pending', { v: pct(comp.txt) });
  const novaT = novaTypo(a);
  const novaTypoLabHtml =
    novaT == null
      ? ''
      : `<div class="lk-lab${novaT !== a.typo ? ' amber' : ''}" style="top:6%;left:4%">${t('lab_letter_nova', { typo: novaT })}</div>`;
  const novaTitleVal = novaTitle(a);
  const novaOcrVal = novaOcr(a);
  const novaOcrLabHtml =
    novaOcrVal == null
      ? ''
      : `<div class="lk-lab${novaOcrVal !== 'accurate' ? ' amber' : ''}" style="top:6%;right:4%">${
          novaTitleVal
            ? t('lab_letter_nova_ocr', { title: esc(novaTitleVal) })
            : t('lab_letter_nova_ocr_empty')
        }</div>`;
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
    const head = isGroupPrimary(pose)
      ? t('lab_pose_group', { n: pose.n })
      : pose.n > 1
        ? t('lab_pose_n_many', { n: pose.n })
        : t('lab_pose_n', { n: pose.n });
    poseHtml = `<div class="lk-lab amber" style="top:8%;left:4%">${head}</div>
          <div class="lk-lab" style="top:16%;left:4%">${t('lab_pose_spread', { v: pose.spread == null ? '—' : num(pose.spread, 2) })}</div>
          <div class="lk-lab" style="top:24%;left:4%">${t('lab_pose_asym', { v: pose.asym == null ? '—' : num(pose.asym, 2) })}</div>
          <div class="lk-lab" style="top:32%;left:4%">${t('lab_pose_conf', { v: pose.conf == null ? '—' : pct(pose.conf) })}</div>`;
    if (isGroupPrimary(pose)) {
      /* crowd blob — no extra low-conf line */
    } else if (!pose.kpts) {
      poseHtml += `<div class="lk-lab amber" style="top:40%;left:4%">${t('lab_pose_no_skel')}</div>`;
    } else if (!usableSkeleton(pose.kpts, pose)) {
      poseHtml += `<div class="lk-lab amber" style="top:40%;left:4%">${t('lab_pose_low_conf', {
        v: pose.conf == null ? '—' : pct(pose.conf),
      })}</div>`;
    }
  }

  const titleHole = box
    ? [[box.left / 100, box.top / 100, box.width / 100, box.height / 100]]
    : [];
  const creatureHoles = cboxesPref.slice(0, 3).map((b) => {
    const raw = b.box || b;
    return Array.isArray(raw) ? raw : [0, 0, 0, 0];
  });
  const wboxesPref = preferredWeaponBoxes(p, a);
  const weaponBoxesHtml = wboxesPref
    .slice(0, 3)
    .map((b) => {
      const raw = b.box || b;
      const [x, y, w, h] = Array.isArray(raw) ? raw : [0, 0, 0, 0];
      const T = Math.max(0, y * 100);
      const lab = formatWeaponLabel(b.label);
      const sc = b.score != null ? ` ${pct(b.score)}` : '';
      const labClass = T < 8 ? ' topish' : '';
      return `<div class="lk-cbox lk-wbox" style="${boxStyle(x, y, w, h)}"><span class="lk-cbox-lab${labClass}">${lab}${sc}</span></div>`;
    })
    .join('');
  const weaponHoles = wboxesPref.slice(0, 3).map((b) => {
    const raw = b.box || b;
    return Array.isArray(raw) ? raw : [0, 0, 0, 0];
  });
  const rekW = rekWeaponPresent(a);
  const clipW = a.sem?.weapon;
  const weaponLabHtml = wboxesPref.length
    ? `<div class="lk-lab blood" style="top:6%;right:4%">${t('lab_weapon_owl', { n: wboxesPref.length })}${rekW ? ' · Rek' : ''}</div>`
    : `<div class="lk-lab amber" style="top:45%;left:50%;transform:translate(-50%,-50%)">${
        rekW ? t('lab_weapon_rek_only') : t('lab_weapon_none')
      }${clipW != null ? ` · CLIP ${pct(clipW)}` : ''}</div>`;
  const poseKpts =
    pose?.kpts && !isGroupPrimary(pose)
      ? usableSkeleton(alignKeypointsToBox(pose.kpts, pose.box), pose)
      : null;
  const poseHoles = pose?.box
    ? [pose.box]
    : poseKpts
      ? [kptBox(poseKpts)].filter(Boolean)
      : [];
  const poseBoxHtml = pose?.box
    ? `<div class="lk-posebox" style="${boxStyle(pose.box[0], pose.box[1], pose.box[2], pose.box[3])}"></div>`
    : '';
  const poseSkel = poseKpts ? skeletonHtml(poseKpts) : '';

  return `<div class="lk-ov" id="lk-ov">
        <div class="lk-layer" data-layer="L"><div class="lk-lab" style="top:6%;left:4%">L* ${a.L ?? p[4]}</div></div>
        <div class="lk-layer" data-layer="palette">
          <canvas class="lk-heat lk-poster" data-heat="poster"></canvas>
          <div class="lk-handles">${palHandles}</div>
          <div class="lk-palswatch">${palSwatch}</div>
          <div class="lk-lab" style="top:6%;left:4%">${t('lab_palette_swatches', { n: palArr.length })}</div>
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
        <div class="lk-layer" data-layer="heat-saliency">
          <canvas class="lk-heat" data-heat="saliency"></canvas>
          <div class="lk-mass lk-salpeak" hidden></div>
          <div class="lk-lab" data-sal-lab style="top:6%;left:4%">${t('lab_saliency_pending')}</div>
        </div>
        <div class="lk-layer" data-layer="sat">
          <canvas class="lk-heat" data-heat="sat"></canvas>
          <div class="lk-lab" style="top:6%;left:4%">${t('lab_saturation', { v: pct(a.sat) })}</div></div>
        <div class="lk-layer" data-layer="bands">${dimSvg('lk-mask-bands', [])}<div class="lk-bandsov">${bandBarHtml(bands)}</div>
          ${bandLegendHtml(bands)}
          <div class="lk-lab" style="top:6%;left:4%">${t('lab_hue_families_top', { name: topBand.name, v: pct(topBand.v) })}</div>
          <div class="lk-lab" style="top:6%;right:4%">${t('lab_hue_families_bins')}</div></div>
        <div class="lk-layer" data-layer="faces">${dimSvg('lk-mask-faces', fboxes)}${faceBoxesHtml}
          ${novaLabHtml}
          <div class="lk-lab${faces.source === 'rek' ? ' amber' : ''}" style="${faceLabStyle}">${faceLabText}</div></div>
        <div class="lk-layer" data-layer="creature">${dimSvg('lk-mask-creature', creatureHoles)}${creatureBoxesHtml}${jevCreatureLabHtml}${novaCreatureLabHtml}${creatureLabHtml}</div>
        <div class="lk-layer" data-layer="weapon">${dimSvg('lk-mask-weapon', weaponHoles)}${weaponBoxesHtml}${weaponLabHtml}</div>
        <div class="lk-layer" data-layer="medium">${dimSvg('lk-mask-medium', [])}
          <div class="lk-lab" style="top:8%;left:4%">${mediumLab}</div></div>
        <div class="lk-layer" data-layer="text">${dimSvg('lk-mask-text', titleHole)}<div class="lk-textband" style="${textBandStyle}"></div>
          ${novaTypoLabHtml}${novaOcrLabHtml}
          <div class="lk-lab blood" style="top:${tLabTop.toFixed(1)}%;left:${tLabLeft.toFixed(1)}%">${textLab}</div></div>
        <div class="lk-layer" data-layer="sym">
          <div class="lk-mirror"><img src="${sheetSrc}" alt=""></div>
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
        <div class="lk-layer" data-layer="pose">${dimSvg('lk-mask-pose', poseHoles)}${poseBoxHtml}${poseSkel}${poseHtml}</div>
      </div>`;
}

export const BEAT_LAYERS = {
  object: ['medium'],
  color: ['palette'],
  faces: ['faces'],
  letter: ['text'],
  creature: ['creature'],
  weapon: ['weapon'],
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
    { id: 'saliency', layers: ['heat-saliency'], heat: true },
    { id: 'bands', layers: ['bands'] },
    { id: 'blood', layers: ['blood'], heat: true },
  ],
  creature: [
    { id: 'creature', layers: ['creature'] },
    { id: 'weapon', layers: ['weapon'] },
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

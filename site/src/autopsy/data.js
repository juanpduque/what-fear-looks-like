import { POSTER_BY_ID } from '../shared/posters.js';

function buildVer() {
  return document.querySelector('meta[name="aof-build"]')?.content || '';
}

export function assetUrl(path) {
  const v = buildVer();
  return v ? `${path}?v=${v}` : path;
}

export function tmdbStem(filePath) {
  const name = String(filePath || '').replace(/^\/+/, '');
  return name.toLowerCase().endsWith('.jpg') ? name.slice(0, -4) : name;
}

function siteAsset(rel) {
  const base = import.meta.env.BASE_URL || '/';
  const clean = String(rel || '').replace(/^\/+/, '');
  return assetUrl(`${base}${clean}`);
}

export function saliencyMapUrls(id, filePath) {
  const n = Number(id);
  if (!Number.isFinite(n)) return [];
  if (filePath) {
    const stem = tmdbStem(filePath);
    if (!stem) return [];
    return [siteAsset(`saliency_alts/${n}_${stem}.webp`)];
  }
  return [siteAsset(`saliency/${n}.webp`)];
}

let LOOKUP_P = null;
let CREATURE_BOXES_P = null;
let WEAPON_BOXES_P = null;
let POSE_P = null;
let SALIENCY_P = null;
let TITLE_INK_P = null;
let MEDIUM_CL_P = null;
let POSTER_ALTS_P = null;
let POSTER_ALTS_REK_P = null;
let POSTER_ALTS_POSE_P = null;
let POSTER_ALTS_SAL_P = null;
let POSTER_ALTS_COMP_P = null;
let POSTER_ALTS_FACES_P = null;
let POSTER_ALTS_OWL_P = null;
let POSTER_ALTS_TEXT_P = null;

export function ensureCreatureBoxes() {
  if (window.CREATURE_BOXES) return Promise.resolve(window.CREATURE_BOXES);
  if (CREATURE_BOXES_P) return CREATURE_BOXES_P;
  CREATURE_BOXES_P = new Promise((resolve, reject) => {
    const s = document.createElement('script');
    s.src = assetUrl('data/creature_boxes.js');
    s.onload = () => resolve(window.CREATURE_BOXES || {});
    s.onerror = () => {
      CREATURE_BOXES_P = null;
      reject(new Error('creature_boxes.js failed'));
    };
    document.head.appendChild(s);
  });
  return CREATURE_BOXES_P;
}

export function ensureWeaponBoxes() {
  if (window.WEAPON_BOXES) return Promise.resolve(window.WEAPON_BOXES);
  if (WEAPON_BOXES_P) return WEAPON_BOXES_P;
  WEAPON_BOXES_P = new Promise((resolve, reject) => {
    const s = document.createElement('script');
    s.src = assetUrl('data/weapon_boxes.js');
    s.onload = () => resolve(window.WEAPON_BOXES || {});
    s.onerror = () => {
      WEAPON_BOXES_P = null;
      reject(new Error('weapon_boxes.js failed'));
    };
    document.head.appendChild(s);
  });
  return WEAPON_BOXES_P;
}

export function ensureLookup() {
  if (window.LOOKUP) return Promise.resolve(window.LOOKUP);
  if (LOOKUP_P) return LOOKUP_P;
  LOOKUP_P = new Promise((resolve, reject) => {
    const s = document.createElement('script');
    s.src = assetUrl('data/lookup.js');
    s.onload = () => {
      if (!window.LOOKUP) {
        LOOKUP_P = null;
        reject(new Error('LOOKUP missing after load'));
        return;
      }
      resolve(window.LOOKUP);
    };
    s.onerror = () => {
      LOOKUP_P = null;
      reject(new Error('lookup.js failed'));
    };
    document.head.appendChild(s);
  });
  return LOOKUP_P;
}

export function ensurePose() {
  if (window.POSE) return Promise.resolve(window.POSE);
  if (POSE_P) return POSE_P;
  POSE_P = new Promise((resolve, reject) => {
    const s = document.createElement('script');
    s.src = assetUrl('data/pose.js');
    s.onload = () => resolve(window.POSE || {});
    s.onerror = () => {
      POSE_P = null;
      reject(new Error('pose.js failed'));
    };
    document.head.appendChild(s);
  });
  return POSE_P;
}

export function ensureSaliency() {
  if (window.SALIENCY) return Promise.resolve(window.SALIENCY);
  if (SALIENCY_P) return SALIENCY_P;
  SALIENCY_P = fetch(assetUrl('data/saliency.json'))
    .then((r) => (r.ok ? r.json() : {}))
    .then((d) => {
      window.SALIENCY = d || {};
      return window.SALIENCY;
    })
    .catch(() => {
      SALIENCY_P = null;
      window.SALIENCY = window.SALIENCY || {};
      return window.SALIENCY;
    });
  return SALIENCY_P;
}

export function ensureTitleInk() {
  if (window.TITLE_INK) return Promise.resolve(window.TITLE_INK);
  if (TITLE_INK_P) return TITLE_INK_P;
  TITLE_INK_P = fetch(assetUrl('data/title_ink.json'))
    .then((r) => (r.ok ? r.json() : {}))
    .then((d) => {
      window.TITLE_INK = d || {};
      return window.TITLE_INK;
    })
    .catch(() => {
      TITLE_INK_P = null;
      window.TITLE_INK = window.TITLE_INK || {};
      return window.TITLE_INK;
    });
  return TITLE_INK_P;
}

export function ensureMediumCl() {
  if (window.MEDIUM_CL) return Promise.resolve(window.MEDIUM_CL);
  if (MEDIUM_CL_P) return MEDIUM_CL_P;
  MEDIUM_CL_P = fetch(assetUrl('data/medium_cl.json'))
    .then((r) => (r.ok ? r.json() : {}))
    .then((d) => {
      window.MEDIUM_CL = d || {};
      return window.MEDIUM_CL;
    })
    .catch(() => {
      MEDIUM_CL_P = null;
      window.MEDIUM_CL = window.MEDIUM_CL || {};
      return window.MEDIUM_CL;
    });
  return MEDIUM_CL_P;
}

export function mediumClFor(id) {
  const row = window.MEDIUM_CL && window.MEDIUM_CL[String(id)];
  if (!Array.isArray(row) || row.length < 2) return null;
  const pred = row[0];
  const conf = Number(row[1]);
  if (pred !== 'painted' && pred !== 'photo' && pred !== 'composite') return null;
  if (!Number.isFinite(conf)) return null;
  return { pred, conf };
}

export function ensurePosterAlts() {
  if (window.POSTER_ALTS) return Promise.resolve(window.POSTER_ALTS);
  if (POSTER_ALTS_P) return POSTER_ALTS_P;
  POSTER_ALTS_P = fetch(assetUrl('data/poster_alts.json'))
    .then((r) => (r.ok ? r.json() : {}))
    .then((d) => {
      window.POSTER_ALTS = d || {};
      return window.POSTER_ALTS;
    })
    .catch(() => {
      POSTER_ALTS_P = null;
      window.POSTER_ALTS = window.POSTER_ALTS || {};
      return window.POSTER_ALTS;
    });
  return POSTER_ALTS_P;
}

export function ensurePosterAltsRek() {
  if (window.POSTER_ALTS_REK && Object.keys(window.POSTER_ALTS_REK).length)
    return Promise.resolve(window.POSTER_ALTS_REK);
  if (POSTER_ALTS_REK_P) return POSTER_ALTS_REK_P;
  POSTER_ALTS_REK_P = fetch(assetUrl('data/poster_alts_rek.json'))
    .then((r) => (r.ok ? r.json() : {}))
    .then((d) => {
      window.POSTER_ALTS_REK = d || {};
      if (!Object.keys(window.POSTER_ALTS_REK).length) POSTER_ALTS_REK_P = null;
      return window.POSTER_ALTS_REK;
    })
    .catch(() => {
      POSTER_ALTS_REK_P = null;
      window.POSTER_ALTS_REK = window.POSTER_ALTS_REK || {};
      return window.POSTER_ALTS_REK;
    });
  return POSTER_ALTS_REK_P;
}

export function ensurePosterAltsPose() {
  if (window.POSTER_ALTS_POSE && Object.keys(window.POSTER_ALTS_POSE).length)
    return Promise.resolve(window.POSTER_ALTS_POSE);
  if (POSTER_ALTS_POSE_P) return POSTER_ALTS_POSE_P;
  POSTER_ALTS_POSE_P = fetch(assetUrl('data/poster_alts_pose.json'))
    .then((r) => (r.ok ? r.json() : {}))
    .then((d) => {
      window.POSTER_ALTS_POSE = d || {};
      if (!Object.keys(window.POSTER_ALTS_POSE).length) POSTER_ALTS_POSE_P = null;
      return window.POSTER_ALTS_POSE;
    })
    .catch(() => {
      POSTER_ALTS_POSE_P = null;
      window.POSTER_ALTS_POSE = window.POSTER_ALTS_POSE || {};
      return window.POSTER_ALTS_POSE;
    });
  return POSTER_ALTS_POSE_P;
}

export function ensurePosterAltsSal() {
  if (window.POSTER_ALTS_SAL && Object.keys(window.POSTER_ALTS_SAL).length)
    return Promise.resolve(window.POSTER_ALTS_SAL);
  if (POSTER_ALTS_SAL_P) return POSTER_ALTS_SAL_P;
  POSTER_ALTS_SAL_P = fetch(assetUrl('data/poster_alts_sal.json'))
    .then((r) => (r.ok ? r.json() : {}))
    .then((d) => {
      window.POSTER_ALTS_SAL = d || {};
      if (!Object.keys(window.POSTER_ALTS_SAL).length) POSTER_ALTS_SAL_P = null;
      return window.POSTER_ALTS_SAL;
    })
    .catch(() => {
      POSTER_ALTS_SAL_P = null;
      window.POSTER_ALTS_SAL = window.POSTER_ALTS_SAL || {};
      return window.POSTER_ALTS_SAL;
    });
  return POSTER_ALTS_SAL_P;
}

export function ensurePosterAltsComp() {
  if (window.POSTER_ALTS_COMP && Object.keys(window.POSTER_ALTS_COMP).length)
    return Promise.resolve(window.POSTER_ALTS_COMP);
  if (POSTER_ALTS_COMP_P) return POSTER_ALTS_COMP_P;
  POSTER_ALTS_COMP_P = fetch(assetUrl('data/poster_alts_comp.json'))
    .then((r) => (r.ok ? r.json() : {}))
    .then((d) => {
      window.POSTER_ALTS_COMP = d || {};
      if (!Object.keys(window.POSTER_ALTS_COMP).length) POSTER_ALTS_COMP_P = null;
      return window.POSTER_ALTS_COMP;
    })
    .catch(() => {
      POSTER_ALTS_COMP_P = null;
      window.POSTER_ALTS_COMP = window.POSTER_ALTS_COMP || {};
      return window.POSTER_ALTS_COMP;
    });
  return POSTER_ALTS_COMP_P;
}

function ensureAltJson(flag, url, cacheKey) {
  if (window[flag] && Object.keys(window[flag]).length) return Promise.resolve(window[flag]);
  if (cacheKey.p) return cacheKey.p;
  cacheKey.p = fetch(assetUrl(url))
    .then((r) => (r.ok ? r.json() : {}))
    .then((d) => {
      window[flag] = d || {};
      if (!Object.keys(window[flag]).length) cacheKey.p = null;
      return window[flag];
    })
    .catch(() => {
      cacheKey.p = null;
      window[flag] = window[flag] || {};
      return window[flag];
    });
  return cacheKey.p;
}

const FACES_CACHE = { p: null };
const OWL_CACHE = { p: null };
const TEXT_CACHE = { p: null };

export function ensurePosterAltsFaces() {
  POSTER_ALTS_FACES_P = ensureAltJson('POSTER_ALTS_FACES', 'data/poster_alts_faces.json', FACES_CACHE);
  return POSTER_ALTS_FACES_P;
}

export function ensurePosterAltsOwl() {
  POSTER_ALTS_OWL_P = ensureAltJson('POSTER_ALTS_OWL', 'data/poster_alts_owl.json', OWL_CACHE);
  return POSTER_ALTS_OWL_P;
}

export function ensurePosterAltsText() {
  POSTER_ALTS_TEXT_P = ensureAltJson('POSTER_ALTS_TEXT', 'data/poster_alts_text.json', TEXT_CACHE);
  return POSTER_ALTS_TEXT_P;
}

export function poseAltFor(id, path) {
  const bag = window.POSTER_ALTS_POSE && window.POSTER_ALTS_POSE[String(id)];
  const row = bag && path ? bag[path] : null;
  if (!Array.isArray(row)) return null;
  const [n, spread, asym, conf, kpts, box] = row;
  return {
    n: n || 0,
    spread,
    asym,
    conf,
    kpts: Array.isArray(kpts) && kpts.length ? kpts : null,
    box: Array.isArray(box) && box.length === 4 ? box : null,
  };
}

export function salAltFor(id, path) {
  const bag = window.POSTER_ALTS_SAL && window.POSTER_ALTS_SAL[String(id)];
  const row = bag && path ? bag[path] : null;
  if (!Array.isArray(row) || row.length < 2) return null;
  return { x: row[0], y: row[1], m: row[2] };
}

export function compAltFor(id, path) {
  const bag = window.POSTER_ALTS_COMP && window.POSTER_ALTS_COMP[String(id)];
  const row = bag && path ? bag[path] : null;
  return row && typeof row === 'object' ? row : null;
}

export function rekAltFor(id, path) {
  const bag = window.POSTER_ALTS_REK && window.POSTER_ALTS_REK[String(id)];
  const row = bag && path ? bag[path] : null;
  if (!Array.isArray(row) || row.length < 8) return null;
  return {
    weapon: row[0],
    person: row[1],
    animal: row[2],
    fire: row[3],
    water: row[4],
    silhouette: row[5],
    bright: row[6],
    contrast: row[7],
  };
}

export function facesAltFor(id, path) {
  const bag = window.POSTER_ALTS_FACES && window.POSTER_ALTS_FACES[String(id)];
  const row = bag && path ? bag[path] : null;
  if (!Array.isArray(row) || row.length < 2) return null;
  const boxes = Array.isArray(row[2])
    ? row[2].filter((b) => Array.isArray(b) && b.length === 4)
    : [];
  return { n: Number(row[0]) || 0, area: Number(row[1]) || 0, boxes };
}

export function owlAltFor(id, path) {
  const bag = window.POSTER_ALTS_OWL && window.POSTER_ALTS_OWL[String(id)];
  const row = bag && path ? bag[path] : null;
  if (!row || typeof row !== 'object') return null;
  return {
    c: Array.isArray(row.c) ? row.c : [],
    w: Array.isArray(row.w) ? row.w : [],
  };
}

export function textAltFor(id, path) {
  const bag = window.POSTER_ALTS_TEXT && window.POSTER_ALTS_TEXT[String(id)];
  const row = bag && path ? bag[path] : null;
  if (!Array.isArray(row) || row.length !== 4) return null;
  const [tx, tt, tw, th] = row;
  if (!(tw > 0) || !(th > 0) || tx == null || tt == null || tx < 0 || tt < 0) return null;
  return [tx, tt, tw, th];
}

export function posterAltsFor(id) {
  const row = window.POSTER_ALTS && window.POSTER_ALTS[String(id)];
  if (!Array.isArray(row) || row.length < 2) return [];
  return row
    .map((item) => {
      if (!Array.isArray(item) || !item[0]) return null;
      return { path: item[0], iso: item[1] || '', measured: item[2] === 1 };
    })
    .filter(Boolean);
}

export function titleInkFor(id) {
  const row = window.TITLE_INK && window.TITLE_INK[String(id)];
  if (!Array.isArray(row) || row.length !== 4) return null;
  const [tx, tt, tw, th] = row;
  if (!(tw > 0) || !(th > 0) || tx == null || tt == null || tx < 0 || tt < 0) return null;
  return { tx, tt, tw, th };
}

export function saliencyFor(id) {
  const row = window.SALIENCY && window.SALIENCY[String(id)];
  if (!Array.isArray(row) || row.length < 2) return null;
  return { x: row[0], y: row[1], m: row[2] };
}

export function poseFor(id) {
  const row = window.POSE && window.POSE[String(id)];
  if (!Array.isArray(row)) return null;
  const [n, spread, asym, conf, kpts, box] = row;
  return {
    n: n || 0,
    spread,
    asym,
    conf,
    kpts: Array.isArray(kpts) && kpts.length ? kpts : null,
    box: Array.isArray(box) && box.length === 4 ? box : null,
  };
}

export function findPosterById(id) {
  const n = Number(id);
  if (!Number.isFinite(n)) return null;
  return POSTER_BY_ID[n] || POSTER_BY_ID[id] || null;
}

export function decadeLabel(year) {
  const y = Number(year);
  if (!Number.isFinite(y)) return '2020s';
  const d = Math.floor(y / 10) * 10;
  const clamped = Math.max(1920, Math.min(2020, d));
  return `${clamped}s`;
}

export function decadeIndex(year) {
  const decades = window.DECADES || [];
  const label = decadeLabel(year);
  const i = decades.indexOf(label);
  if (i >= 0) return i;
  return Number(year) < 1920 ? 0 : Math.max(0, decades.length - 1);
}

function nearestPoint(pts, year) {
  if (!pts || !pts.length) return null;
  let best = pts[0];
  let bd = Infinity;
  for (let i = 0; i < pts.length; i++) {
    const d = Math.abs(pts[i][0] - year);
    if (d < bd) {
      bd = d;
      best = pts[i];
    }
  }
  return best[1];
}

/** Decade / year-matched corpus means from series.js. */
export function decadeMeans(year) {
  const idx = decadeIndex(year);
  const decades = window.DECADES || [];
  const river = (window.RIVER && window.RIVER[idx]) || null;
  return {
    decade: decades[idx] || decadeLabel(year),
    idx,
    L: nearestPoint(window.DARK_PTS, year),
    red: nearestPoint(window.RED_PTS, year),
    faceShare: nearestPoint(window.FACE_PTS, year),
    text: nearestPoint(window.TEXT_PTS, year),
    sym: nearestPoint(window.SYM_PTS, year),
    diag: nearestPoint(window.DIAG_PTS, year),
    darkBand: river ? river[5] : null,
  };
}

export const PICK_IDS = [948, 653, 348, 1091, 694, 578, 310131, 882598];

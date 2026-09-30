import { POSTER_BY_ID } from '../shared/posters.js';

function buildVer() {
  return document.querySelector('meta[name="aof-build"]')?.content || '';
}

export function assetUrl(path) {
  const v = buildVer();
  return v ? `${path}?v=${v}` : path;
}

let LOOKUP_P = null;
let CREATURE_BOXES_P = null;
let POSE_P = null;

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

export function poseFor(id) {
  const row = window.POSE && window.POSE[String(id)];
  if (!Array.isArray(row)) return null;
  const [n, spread, asym, conf] = row;
  return { n: n || 0, spread, asym, conf };
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

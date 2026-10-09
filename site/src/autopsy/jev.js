import { formatNovaCreature } from './nova.js';

const t = (...args) =>
  typeof window.t === 'function' ? window.t(...args) : args[0];

const CLIP_ANIMALS = new Set(['shark', 'spider', 'snake', 'wolf_dog', 'bird', 'insect']);

export function jevStr(a, key) {
  if (a?.[key] == null || a[key] === '') return null;
  const s = String(a[key]).trim();
  return s || null;
}

export function jevCreature(a) {
  return jevStr(a, 'jev_creature');
}

export function jevPresent(a) {
  return jevStr(a, 'jev_present');
}

export function formatJevCreature(label) {
  return formatNovaCreature(label);
}

/** CLIP census slot collapsed onto JEV taxonomy (animals share one slot). */
export function clipToJevSlot(a, p) {
  const c = a?.creature || p?.[6];
  if (!c || c === 'uncertain' || c === 'none') return 'none';
  if (CLIP_ANIMALS.has(c)) return 'animal';
  return c;
}

export function jevCreatureNote(a, p) {
  const jev = jevCreature(a);
  if (!jev) return '';
  const clip = clipToJevSlot(a, p);
  const key = jev === clip ? 'autopsy_body_creature_jev_agree' : 'autopsy_body_creature_jev';
  return ` ${t(key, { c: formatJevCreature(jev) })}`;
}

/** Overlay when JEV names a type, or when it disagrees with the CLIP slot. */
export function showJevCreatureLab(a, p) {
  const jev = jevCreature(a);
  if (!jev) return false;
  if (jev !== 'none') return true;
  return jev !== clipToJevSlot(a, p);
}

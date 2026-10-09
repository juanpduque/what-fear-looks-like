import { creatureLabels } from '../shared/posters.js';

const t = (...args) => (typeof window.t === 'function' ? window.t(...args) : args[0]);

export function novaStr(a, key) {
  if (a?.[key] == null || a[key] === '') return null;
  const s = String(a[key]).trim();
  return s || null;
}

export function novaCreature(a) {
  return novaStr(a, 'nova_creature');
}

export function novaTypo(a) {
  return novaStr(a, 'nova_typo');
}

export function novaTitle(a) {
  return novaStr(a, 'nova_title');
}

export function novaOcr(a) {
  return novaStr(a, 'nova_ocr');
}

export function formatNovaCreature(label) {
  if (!label) return '';
  if (label === 'none' || label === 'uncertain') return t('lookup_none');
  return creatureLabels()[label] || label.replace(/_/g, ' ');
}

function clipCreatureSlot(a, p) {
  const c = a?.creature || p?.[6];
  if (!c || c === 'uncertain' || c === 'none') return 'none';
  return c;
}

export function novaCreatureNote(a, p) {
  const nova = novaCreature(a);
  if (!nova) return '';
  const clip = clipCreatureSlot(a, p);
  const key = nova === clip ? 'autopsy_body_creature_nova_agree' : 'autopsy_body_creature_nova';
  return ` ${t(key, { c: formatNovaCreature(nova) })}`;
}

export function novaLetterNote(a) {
  const typo = novaTypo(a);
  const title = novaTitle(a);
  const ocr = novaOcr(a);
  let out = '';
  if (typo) {
    const key = typo === a?.typo ? 'autopsy_body_letter_nova_agree' : 'autopsy_body_letter_nova';
    out += ` ${t(key, { typo })}`;
  }
  if (ocr) {
    const verdict = t(`nova_ocr_${ocr}`);
    out += title
      ? ` ${t('autopsy_body_letter_nova_ocr', { title, verdict })}`
      : ` ${t('autopsy_body_letter_nova_ocr_empty', { verdict })}`;
  }
  return out;
}

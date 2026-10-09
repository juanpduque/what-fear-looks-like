import { pct } from '../shared/format.js';

const t = (...args) => (typeof window.t === 'function' ? window.t(...args) : args[0]);

/**
 * Resolve YuNet vs Rekognition face counts for the autopsy.
 *
 * Rule:
 * - Agree → that count (YuNet boxes/area when present).
 * - YuNet > 0, Rek = 0 → keep YuNet (we have geometry).
 * - YuNet = 0, Rek > 0 → trust Rek for presence (classic false-negative);
 *   draw Rek boxes when the DetectFaces backfill has them.
 * - Both > 0 but differ → YuNet wins for count/geometry; flag disagreement.
 * - No Rek payload → YuNet alone.
 */
export function resolveFaces(a, p) {
  const yunet = Number(a?.faces ?? p?.[5] ?? 0) || 0;
  const hasRek = a?.rek != null && a.rek.faces != null && a.rek.faces !== '';
  const rek = hasRek ? Number(a.rek.faces) || 0 : null;
  const farea = a?.farea ?? 0;
  const fboxes = Array.isArray(a?.fboxes) ? a.fboxes : [];

  if (rek == null) {
    return {
      n: yunet,
      yunet,
      rek: null,
      source: 'yunet',
      agreed: true,
      farea,
      fboxes,
    };
  }
  if (yunet === rek) {
    return {
      n: yunet,
      yunet,
      rek,
      source: 'agree',
      agreed: true,
      farea,
      fboxes,
    };
  }
  if (yunet === 0 && rek > 0) {
    const rekBoxes = Array.isArray(a.rek.fboxes) ? a.rek.fboxes : [];
    const rekArea = rekBoxes.reduce((s, [, , w, h]) => s + w * h, 0);
    return {
      n: rek,
      yunet,
      rek,
      source: 'rek',
      agreed: false,
      farea: Math.min(1, rekArea),
      fboxes: rekBoxes,
    };
  }
  // YuNet positive, Rek zero or different → prefer YuNet geometry.
  return {
    n: yunet,
    yunet,
    rek,
    source: 'yunet',
    agreed: false,
    farea,
    fboxes,
  };
}

export function novaFaceCount(a) {
  if (a?.nova_faces == null || a.nova_faces === '') return null;
  const n = Number(a.nova_faces);
  return Number.isFinite(n) ? n : null;
}

function novaNote(a, yunet) {
  const nova = novaFaceCount(a);
  if (nova == null) return '';
  const key = nova === yunet ? 'autopsy_body_faces_nova_agree' : 'autopsy_body_faces_nova';
  return ` ${t(key, { nova })}`;
}

export function faceBody(a, p) {
  const r = resolveFaces(a, p);
  const vars = {
    n: r.n,
    a: pct(r.farea),
    yunet: r.yunet,
    rek: r.rek == null ? '—' : r.rek,
  };
  let body;
  if (r.n <= 0) {
    body = r.rek == null ? t('autopsy_body_faces_none') : t('autopsy_body_faces_none_agree', vars);
  } else if (r.source === 'rek') {
    body = t(r.fboxes.length ? 'autopsy_body_faces_rek_box' : 'autopsy_body_faces_rek', vars);
  } else if (!r.agreed) {
    body = t('autopsy_body_faces_disagree', vars);
  } else if (r.source === 'agree') {
    body = t('autopsy_body_faces_agree', vars);
  } else {
    body = t('autopsy_body_faces', vars);
  }
  return body + novaNote(a, r.yunet);
}

export function faceLab(a, p) {
  const r = resolveFaces(a, p);
  if (r.source === 'rek') {
    return r.n === 1 ? t('lab_faces_rek', { n: r.n }) : t('lab_faces_rek_pl', { n: r.n });
  }
  if (r.n === 1) return t('lab_faces_area', { n: r.n, a: pct(r.farea) });
  return t('lab_faces_area_pl', { n: r.n, a: pct(r.farea) });
}

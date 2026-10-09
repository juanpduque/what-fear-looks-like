import { pct, num } from '../shared/format.js';
import { posterAltsFor, rekAltFor } from './data.js';
import { BEAT_MODES, creatureLabel, isGroupPrimary, resolveMedium, preferredWeaponBoxes, rekWeaponPresent, topHueFamily } from './layers.js';
import { faceBody } from './faces.js';
import { novaCreatureNote, novaLetterNote } from './nova.js';
import { jevCreatureNote } from './jev.js';

const t = (...args) =>
  typeof window.t === 'function' ? window.t(...args) : args[0];

function escapeHtml(s) {
  return String(s ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

function mediumName(pred) {
  return pred ? t(`lookup_${pred}`) : t('lab_medium_na');
}

function objectBody(p, a) {
  const year = p[0];
  const id = p[7];
  const m = resolveMedium(a);
  const vars = {
    year,
    id,
    medium: mediumName(m.pred),
    conf: m.conf == null ? '—' : pct(m.conf),
    painted: a.painted == null ? '—' : pct(a.painted),
  };
  const alts = posterAltsFor(id);
  const base = m.source === 'cl' ? t('autopsy_body_object', vars) : t('autopsy_body_object_clip', vars);
  if (alts.length < 2) return base;
  const rekN = alts.filter((row) => rekAltFor(id, row.path)).length;
  const altsLine = t('autopsy_body_alts', { n: alts.length });
  if (rekN < 1) return `${base} ${altsLine}`;
  return `${base} ${altsLine} ${t('autopsy_body_alts_rek', { n: rekN })}`;
}

function poseBody(a) {
  const pose = a.pose;
  if (!pose?.n) return t('autopsy_body_pose_none');
  const vars = {
    n: pose.n,
    spread: pose.spread == null ? '—' : num(pose.spread, 2),
    asym: pose.asym == null ? '—' : num(pose.asym, 2),
    conf: pose.conf == null ? '—' : pct(pose.conf),
  };
  if (isGroupPrimary(pose)) return t('autopsy_body_pose_group', vars);
  if (pose.n > 1) return t('autopsy_body_pose_many', vars);
  return t('autopsy_body_pose', vars);
}

/** Chapter VI intro: interpretive findings, then scroll lights each instrument. */
function compositionBody(comp) {
  const thirds = comp.thirds;
  const diag = comp.diag;
  const sym = comp.sym;
  const bal = comp.bal;
  const neg = comp.neg;

  const thirdsRead =
    thirds == null
      ? t('autopsy_comp_read_na')
      : thirds <= 0.12
        ? t('autopsy_comp_read_thirds_near')
        : thirds <= 0.25
          ? t('autopsy_comp_read_thirds_mid')
          : t('autopsy_comp_read_thirds_far');
  const diagRead =
    diag == null
      ? t('autopsy_comp_read_na')
      : diag >= 0.45
        ? t('autopsy_comp_read_diag_high')
        : diag >= 0.25
          ? t('autopsy_comp_read_diag_mid')
          : t('autopsy_comp_read_diag_low');
  const symRead =
    sym == null
      ? t('autopsy_comp_read_na')
      : sym >= 0.75
        ? t('autopsy_comp_read_sym_high')
        : sym >= 0.5
          ? t('autopsy_comp_read_sym_mid')
          : t('autopsy_comp_read_sym_low');
  const balRead =
    bal == null
      ? t('autopsy_comp_read_na')
      : bal <= 0.08
        ? t('autopsy_comp_read_bal_center')
        : bal <= 0.2
          ? t('autopsy_comp_read_bal_soft')
          : t('autopsy_comp_read_bal_off');
  const negRead =
    neg == null
      ? t('autopsy_comp_read_na')
      : neg >= 0.45
        ? t('autopsy_comp_read_neg_high')
        : neg >= 0.25
          ? t('autopsy_comp_read_neg_mid')
          : t('autopsy_comp_read_neg_low');

  return t('autopsy_body_composition', {
    thirds: thirds == null ? '—' : num(thirds, 2),
    thirds_read: thirdsRead,
    diag: pct(diag),
    diag_read: diagRead,
    sym: pct(sym),
    sym_read: symRead,
    bal: pct(bal),
    bal_read: balRead,
    neg: pct(neg),
    neg_read: negRead,
  });
}

/** Short “what this tab measures” blurb for the active instrument. */
export function modeBlurb(beatId, modeId, p, a) {
  if (!modeId || !BEAT_MODES[beatId]?.some((m) => m.id === modeId)) return '';
  const comp = a?.comp || {};
  const sem = a?.sem || {};
  const topBand = topHueFamily(a);
  const medium = resolveMedium(a);
  const vars = {
    L: a?.L ?? p?.[4] ?? '—',
    dark: pct(a?.dark),
    red: pct(a?.red),
    sat: pct(a?.sat),
    pal_n: a?.pal?.length || 5,
    band: topBand.name,
    band_pct: pct(topBand.v),
    blood: pct(sem.blood),
    sal_m: a?.sal?.m != null ? pct(a.sal.m) : '—',
    typo: a?.typo || '—',
    taxis: a?.taxis == null ? '—' : num(a.taxis, 2),
    txt: pct(comp.txt),
    painted: a?.painted == null ? '—' : pct(a.painted),
    medium: mediumName(medium.pred),
    conf: medium.conf == null ? '—' : pct(medium.conf),
    creature: creatureLabel(p, a),
    cscore: a?.cscore != null ? pct(a.cscore) : '—',
    w_n: preferredWeaponBoxes(p, a).length,
    rek_w: rekWeaponPresent(a) ? t('yn_yes') : t('yn_no'),
    clip_w: a?.sem?.weapon != null ? pct(a.sem.weapon) : '—',
    sym: pct(comp.sym),
    neg: pct(comp.neg),
    diag: pct(comp.diag),
    thirds: num(comp.thirds, 2),
    bal: pct(comp.bal),
    pyr: num(comp.pyr, 2),
    align: pct(comp.align),
    harm: pct(comp.harm),
    cx: num(comp.cx, 2),
  };
  const key = `autopsy_cmode_blurb_${modeId}`;
  const out = t(key, vars);
  return out === key ? '' : out;
}

export function buildBeats(p, a) {
  const title = p[3];
  const cLabel = creatureLabel(p, a);
  const comp = a.comp || {};
  const sem = a.sem || {};
  const topBand = topHueFamily(a);

  const list = [
    {
      id: 'object',
      tilt: 1,
      kicker: t('autopsy_kicker_object'),
      title: title,
      body: objectBody(p, a),
    },
    {
      id: 'color',
      tilt: 0,
      kicker: t('autopsy_kicker_color'),
      title: t('autopsy_title_color'),
      body: t('autopsy_body_color', {
        L: a.L ?? p[4] ?? '—',
        dark: pct(a.dark),
        red: pct(a.red),
        sat: pct(a.sat),
        blood: pct(sem.blood),
        pal_n: a.pal?.length || 5,
        band: topBand.name,
        band_pct: pct(topBand.v),
      }),
    },
    {
      id: 'faces',
      tilt: 0,
      kicker: t('autopsy_kicker_faces'),
      title: t('autopsy_title_faces'),
      body: faceBody(a, p),
    },
    {
      id: 'letter',
      tilt: 0,
      kicker: t('autopsy_kicker_letter'),
      title: t('autopsy_title_letter'),
      body:
        t('autopsy_body_letter', {
          typo: a.typo || '—',
          taxis: a.taxis == null ? '—' : num(a.taxis, 2),
          txt: pct(comp.txt),
        }) + novaLetterNote(a),
    },
    {
      id: 'creature',
      tilt: 0,
      kicker: t('autopsy_kicker_creature'),
      title: t('autopsy_title_creature'),
      body:
        (cLabel && cLabel !== t('none_detected')
          ? t('autopsy_body_creature', {
              c: cLabel,
              score: a.cscore != null ? pct(a.cscore) : '—',
            })
          : t('autopsy_body_creature_none')) +
        jevCreatureNote(a, p) +
        novaCreatureNote(a, p) +
        ` ${t('autopsy_body_weapon', {
          n: preferredWeaponBoxes(p, a).length,
          rek: rekWeaponPresent(a) ? t('yn_yes') : t('yn_no'),
        })}`,
    },
    {
      id: 'composition',
      tilt: 0,
      kicker: t('autopsy_kicker_composition'),
      title: t('autopsy_title_composition'),
      body: compositionBody(comp),
    },
    {
      id: 'comp_thirds',
      tilt: 0,
      kicker: t('autopsy_kicker_comp_thirds'),
      title: t('autopsy_title_comp_thirds'),
      body: t('autopsy_cmode_blurb_thirds', { thirds: num(comp.thirds, 2) }),
    },
    {
      id: 'comp_diag',
      tilt: 0,
      kicker: t('autopsy_kicker_comp_diag'),
      title: t('autopsy_title_comp_diag'),
      body: t('autopsy_cmode_blurb_diag', { diag: pct(comp.diag) }),
    },
    {
      id: 'comp_sym',
      tilt: 0,
      kicker: t('autopsy_kicker_comp_sym'),
      title: t('autopsy_title_comp_sym'),
      body: t('autopsy_cmode_blurb_sym', { sym: pct(comp.sym) }),
    },
    {
      id: 'comp_bal',
      tilt: 0,
      kicker: t('autopsy_kicker_comp_bal'),
      title: t('autopsy_title_comp_bal'),
      body: t('autopsy_cmode_blurb_bal', { bal: pct(comp.bal) }),
    },
    {
      id: 'comp_neg',
      tilt: 0,
      kicker: t('autopsy_kicker_comp_neg'),
      title: t('autopsy_title_comp_neg'),
      body: t('autopsy_cmode_blurb_neg', { neg: pct(comp.neg) }),
      heat: true,
    },
  ];

  // Pose only when this sheet is in the ViTPose table.
  if (a.pose) {
    list.push({
      id: 'pose',
      tilt: 0,
      kicker: t('autopsy_kicker_pose'),
      title: t('autopsy_title_pose'),
      body: poseBody(a),
    });
  }

  return list.map((beat, i) => ({ ...beat, n: i + 1 }));
}

function modesHtml(beat) {
  const modes = BEAT_MODES[beat.id];
  if (!modes?.length) return '';
  const aria = escapeHtml(t('autopsy_views'));
  const btns = modes
    .map((m, i) => {
      const on = i === 0;
      return `<button type="button" role="tab" data-cmode="${escapeHtml(m.id)}" aria-selected="${on ? 'true' : 'false'}" class="${on ? 'is-on' : ''}">${escapeHtml(t(`autopsy_cmode_${m.id}`))}</button>`;
    })
    .join('');
  return `<div class="au-cmodes" role="tablist" aria-label="${aria}">${btns}</div>
      <p class="au-beat-mode-blurb" data-mode-blurb hidden></p>`;
}

export function beatsHtml(beats) {
  return beats
    .map((beat, i) => {
      return `<section class="au-beat" data-beat="${escapeHtml(beat.id)}" data-i="${i}" aria-label="${escapeHtml(beat.kicker)}: ${escapeHtml(beat.title)}">
        <div class="au-beat-inner">
          <div class="au-beat-kicker">${escapeHtml(beat.kicker)}</div>
          <h3 class="au-beat-title">${escapeHtml(beat.title)}</h3>
          <p class="au-beat-body">${escapeHtml(beat.body)}</p>
          ${modesHtml(beat)}
        </div>
      </section>`;
    })
    .join('');
}

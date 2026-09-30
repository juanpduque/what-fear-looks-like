import { pct, num } from '../shared/format.js';
import { BEAT_MODES, creatureLabel } from './layers.js';

const t = (...args) =>
  typeof window.t === 'function' ? window.t(...args) : args[0];

function escapeHtml(s) {
  return String(s ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

function poseBody(a, faces) {
  const pose = a.pose;
  if (!pose) {
    return faces > 0 ? t('autopsy_body_pose_pending') : t('autopsy_body_pose_skip');
  }
  if (!pose.n) return t('autopsy_body_pose_none');
  return t('autopsy_body_pose', {
    n: pose.n,
    spread: pose.spread == null ? '—' : num(pose.spread, 2),
    asym: pose.asym == null ? '—' : num(pose.asym, 2),
    conf: pose.conf == null ? '—' : pct(pose.conf),
  });
}

export function buildBeats(p, a) {
  const title = p[3];
  const year = p[0];
  const id = p[7];
  const faces = a.faces ?? p[5];
  const cLabel = creatureLabel(p, a);
  const comp = a.comp || {};
  const sem = a.sem || {};

  return [
    {
      id: 'object',
      tilt: 1,
      kicker: t('autopsy_kicker_object'),
      title: title,
      body: t('autopsy_body_object', { year, id }),
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
      }),
    },
    {
      id: 'faces',
      tilt: 0,
      kicker: t('autopsy_kicker_faces'),
      title: t('autopsy_title_faces'),
      body:
        faces > 0
          ? t('autopsy_body_faces', { n: faces, a: pct(a.farea) })
          : t('autopsy_body_faces_none'),
    },
    {
      id: 'letter',
      tilt: 0,
      kicker: t('autopsy_kicker_letter'),
      title: t('autopsy_title_letter'),
      body: t('autopsy_body_letter', {
        typo: a.typo || '—',
        taxis: a.taxis == null ? '—' : num(a.taxis, 2),
        txt: pct(comp.txt),
        painted: a.painted == null ? '—' : pct(a.painted),
      }),
    },
    {
      id: 'creature',
      tilt: 0,
      kicker: t('autopsy_kicker_creature'),
      title: t('autopsy_title_creature'),
      body:
        cLabel && cLabel !== t('none_detected')
          ? t('autopsy_body_creature', {
              c: cLabel,
              score: a.cscore != null ? pct(a.cscore) : '—',
            })
          : t('autopsy_body_creature_none'),
    },
    {
      id: 'composition',
      tilt: 0,
      kicker: t('autopsy_kicker_composition'),
      title: t('autopsy_title_composition'),
      body: t('autopsy_body_composition', {
        sym: pct(comp.sym),
        neg: pct(comp.neg),
        diag: pct(comp.diag),
        thirds: num(comp.thirds, 2),
        bal: pct(comp.bal),
        pyr: num(comp.pyr, 2),
        align: pct(comp.align),
        harm: pct(comp.harm),
        cx: num(comp.cx, 2),
      }),
    },
    {
      id: 'pose',
      tilt: 0,
      kicker: t('autopsy_kicker_pose'),
      title: t('autopsy_title_pose'),
      body: poseBody(a, faces),
    },
  ].map((beat, i) => ({ ...beat, n: i + 1 }));
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
  return `<div class="au-cmodes" role="tablist" aria-label="${aria}">${btns}</div>`;
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

/**
 * One autopsy row per film, from Supabase, when the Netlify build has
 * VITE_SUPABASE_URL and VITE_SUPABASE_ANON_KEY. Without them the page keeps
 * reading site/data/*.js|json.
 */

const URL = String(import.meta.env.VITE_SUPABASE_URL || '').replace(/\/$/, '');
const KEY = String(import.meta.env.VITE_SUPABASE_ANON_KEY || '');

/** Column on poster_autopsy → window bag the autopsy already reads. */
const COLUMNS = {
  lookup: 'LOOKUP',
  pose: 'POSE',
  creature_boxes: 'CREATURE_BOXES',
  weapon_boxes: 'WEAPON_BOXES',
  saliency: 'SALIENCY',
  title_ink: 'TITLE_INK',
  omdb: 'OMDB',
  medium_cl: 'MEDIUM_CL',
  key_art: 'KEY_ART',
  alts: 'POSTER_ALTS',
  alts_rek: 'POSTER_ALTS_REK',
  alts_pose: 'POSTER_ALTS_POSE',
  alts_sal: 'POSTER_ALTS_SAL',
  alts_comp: 'POSTER_ALTS_COMP',
  alts_faces: 'POSTER_ALTS_FACES',
  alts_owl: 'POSTER_ALTS_OWL',
  alts_text: 'POSTER_ALTS_TEXT',
  alts_clip: 'POSTER_ALTS_CLIP',
};

let fallback = false;
const inflight = new Map();
const FLAGS = [...new Set(Object.values(COLUMNS))];

export function supabaseConfigured() {
  return Boolean(URL && KEY);
}

/** True when this session should download the static autopsy files. */
export function useStaticData() {
  return !supabaseConfigured() || fallback;
}

export function markStaticFallback() {
  if (fallback) return;
  fallback = true;
  // Drop partial rows so the static loaders do not treat them as the full file.
  for (const flag of FLAGS) delete window[flag];
}

function stash(id, row) {
  const key = String(id);
  for (const [col, flag] of Object.entries(COLUMNS)) {
    if (row[col] == null) continue;
    window[flag] = window[flag] || {};
    window[flag][key] = row[col];
  }
}

/**
 * Fetch one film and merge it into the window bags.
 * Resolves 'hit' | 'miss'. Throws on a network or HTTP error so the caller
 * can fall back to the static files.
 */
export function ensureFilm(id) {
  const key = String(id);
  if (inflight.has(key)) return inflight.get(key);
  const pending = fetch(`${URL}/rest/v1/poster_autopsy?id=eq.${encodeURIComponent(key)}&select=*`, {
    headers: {
      apikey: KEY,
      Authorization: `Bearer ${KEY}`,
      Accept: 'application/json',
    },
  })
    .then(async (res) => {
      if (!res.ok) throw new Error(`supabase ${res.status}`);
      const rows = await res.json();
      if (!Array.isArray(rows) || !rows.length) return 'miss';
      stash(key, rows[0]);
      return 'hit';
    })
    .catch((err) => {
      inflight.delete(key);
      throw err;
    });
  inflight.set(key, pending);
  return pending;
}

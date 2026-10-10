/** Expose pipeline globals for ES modules (const in classic scripts is not on window). */
(function () {
  const g = typeof globalThis !== 'undefined' ? globalThis : window;
  if (typeof DECADES !== 'undefined') g.DECADES = DECADES;
  if (typeof RIVER !== 'undefined') g.RIVER = RIVER;
  if (typeof TYPO !== 'undefined') g.TYPO = TYPO;
  if (typeof BLOOD_PIXEL !== 'undefined') g.BLOOD_PIXEL = BLOOD_PIXEL;
  if (typeof BLOOD_SEMANTIC !== 'undefined') g.BLOOD_SEMANTIC = BLOOD_SEMANTIC;
  if (typeof MAIN_DEC !== 'undefined') g.MAIN_DEC = MAIN_DEC;
  if (typeof DARK_PTS !== 'undefined') g.DARK_PTS = DARK_PTS;
  if (typeof RED_PTS !== 'undefined') g.RED_PTS = RED_PTS;
  if (typeof FACE_PTS !== 'undefined') g.FACE_PTS = FACE_PTS;
  if (typeof TEXT_PTS !== 'undefined') g.TEXT_PTS = TEXT_PTS;
  if (typeof SYM_PTS !== 'undefined') g.SYM_PTS = SYM_PTS;
  if (typeof DIAG_PTS !== 'undefined') g.DIAG_PTS = DIAG_PTS;
  if (typeof SERIES_CI !== 'undefined') g.SERIES_CI = SERIES_CI;
  if (typeof CENSUS_SERIES !== 'undefined') g.CENSUS_SERIES = CENSUS_SERIES;
  if (typeof AOF_META !== 'undefined') g.AOF_META = AOF_META;
  if (typeof POSTERS !== 'undefined') g.POSTERS = POSTERS;
})();

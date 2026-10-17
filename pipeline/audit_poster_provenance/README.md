# Poster provenance audit

TMDB's current primary poster is often not the art from the film's release year. This folder
measures how much that matters, using IMPAwards release-year posters (903 films, 1930-1999)
as the reference. Run from `pipeline/`, with `data/` present.

1. `python3 audit_poster_provenance/compare_impawards.py results/impa_full.jsonl`
   Downloads each IMPAwards poster and records the pHash distance to the TMDB image
   (`dist` <= 10 is the same artwork).
2. `python3 audit_poster_provenance/measure_both.py <dir>`
   Reads `<dir>/impa_full.jsonl` and measures text, composition, diagonal, brightness,
   near-black share, saturation, red and faces on both images. Writes `<dir>/sens.jsonl`.
3. `python3 audit_poster_provenance/sens_summary.py results/sens.jsonl`
   Per-decade table plus the noise floor.

`results/` holds the output of the 2026-10-17 run.

Findings: same artwork 13%, different image 68% (flat across decades). On the originals the
sample is brighter (+8 brightness points on average), with fewer near-black pixels and,
before 1950, more faces. Text area is about equal. The noise floor (same-artwork pairs) is
-2.3 brightness, +5.8 pp near-black. So the published trends understate the dimming and
the shrinking of faces rather than invent them. pHash distance says "different image", not
"later art": LLM judges of that question disagreed too much to use (kappa 0.33).

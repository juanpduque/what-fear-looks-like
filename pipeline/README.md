# Pipeline

Python pipeline: dataset → posters → metrics → CSV/JSON that feed the site.

> **Scope of this file.** It maps the ~65 scripts here into a **canonical
> production path** (what rebuilds the published essay) vs. **exploratory /
> research** scripts (enrichment, QA review builders, cloud jobs, one-off
> probes). The top-level `README.md` has the full conceptual rationale for each
> metric; this file is the "what do I actually run, in what order" index.

## Install

```bash
pip install -r pipeline/requirements.txt         # core color pipeline
pip install -r pipeline/requirements-ml.txt      # CLIP / segmentation / AWS / scraping extras
```

Minimum interpreter: **Python 3.9**. Secrets (TMDB/OMDb keys, AWS creds) go in
`pipeline/.env` (gitignored); see `.env.example` if present.

Every script is **resumable** and writes into `pipeline/data/`. Raw per-poster
CSVs are never mutated in place — builders filter them by the canonical id list
at build time.

## Canonical production path

The single source of truth is `data/canonical_ids.txt` (read via `corpus.py`).
To rebuild the published site from computed metrics:

```bash
cd pipeline
python3 fetch_tmdb_details.py     # refresh current TMDB fichas (resumable)
python3 build_corpus.py           # → canonical_ids.txt + docs/CORPUS.md
python3 apply_exclusions.py       # apply data/excluded_*.csv, then rebuild corpus+site
python3 build_site.py             # series/explorer/lookup + invariants → site/data/*
python3 check_site_invariants.py  # gate: every published file matches the corpus
```

| Script | Role | Inputs | Outputs |
|--------|------|--------|---------|
| `corpus.py` | **Source of truth** (library, not a CLI) | `data/canonical_ids.txt` | `canonical_ids()`, `corpus_n()` |
| `fear_pipeline.py` | Step 1: per-poster **color** metrics | local posters, TMDB | `posters.csv`, `yearly.json`, `hue_river.json`, `darkness_curve.png` |
| `fetch_tmdb_details.py` | Current TMDB `/movie/{id}` metadata | `posters.csv` | TMDB detail cache |
| `build_corpus.py` | Build the canonical id list | metrics + exclusions | `data/canonical_ids.txt`, `docs/CORPUS.md` |
| `apply_exclusions.py` | Apply `data/excluded_*.csv`, rebuild aggregates + series | raw CSVs, exclusion lists | filtered aggregates, `site/data/series.js` |
| `build_site.py` | Rebuild every site data file from the corpus | canonical ids + all metric CSVs | `site/data/*` |
| `build_explorer.py` | Light per-poster grid for the essay | metrics + TMDB `poster_path` | `site/data/explorer.js` |
| `build_lookup.py` | Full per-poster analysis index (lazy-loaded, ~30 MB) | all metric CSVs | `site/data/lookup.js` |
| `export_site_series.py` | Chart series only (no re-filter) | aggregates | `site/data/series.js` |

### Validation gates

| Script | Checks |
|--------|--------|
| `check_site_invariants.py` | Every published `site/data/*` file matches `canonical_ids.txt` |
| `validate_corpus.py` | Corpus integrity; `--fix-front` aligns stale `n` in front/README |
| `sync_front_n.py` | `--fix` replaces the published `n` in `site/i18n` + `index.html` + `README` |

## Metrics (semantic chapters)

Run `clip_embed.py` first — the other `clip_*` scripts reuse its cached
embeddings. Needs `requirements-ml.txt`.

| Script | Metric | Reuses `clip_embeddings.npz`? | Outputs |
|--------|--------|:---:|---------|
| `clip_embed.py` | One-time CLIP image embeddings | — (produces it) | `clip_embeddings.npz` |
| `clip_census.py` | Monster/creature census | yes | `census.csv`, `census_decade.json` |
| `clip_medium.py` | Painted vs. photographic | yes | `medium.csv` |
| `clip_typography_axis.py` | Ornate↔minimal lettering axis | yes | `typography.csv`, `typography_decade.json` |
| `faces_v2.py` | **Canonical** face detection (YuNet) | no | `faces_v2.csv`, `faces_v2_decade.json` |
| `multi_analyze.py` | Plugin framework: composition / typography / grid / aesthetic / diagonal | no | `attributes.csv`, `attributes_decade.json` |
| `segmentation.py` | Material & scene segmentation (SegFormer / Minc / CLIP zero-shot) | no | `segmentation.csv`, `segmentation_decade.json` |

`multi_analyze.py` is the preferred pattern for adding a new metric group:
each group declares its own output columns, so `--metrics grid` adds a group
without recomputing finished ones.

## Exploratory / research (NOT on the production path)

These enrich coverage, build internal QA review pages, run cloud jobs, or were
one-off probes. They don't rebuild the published essay. Prefer the canonical
path above unless you're specifically extending data coverage.

- **Poster/metadata gap enrichment (TMDB → OMDb → IMDb):** `enrich_imdb_ids.py`,
  `enrich_imdb_wikidata.py`, `enrich_years_imdb.py`, `enrich_imdb_selenium_features.py`
  *(selenium)*, `probe_omdb_posters.py`, `pull_omdb_posters.py`,
  `pull_imdb_posters.py` *(suggestion API; `--browser` → playwright)*,
  `pull_en_poster_gap.py`, `fill_poster_paths.py`, `fill_runtime_imdb_basics.py`,
  `resolve_imdb_ambiguous_selenium.py` *(selenium)*,
  `match_imdb_suggest_features.py`, `match_imdb_title_basics_features.py`,
  `recheck_tmdb_external_ids_features.py`, `remap_tmdb_not_found.py`.
- **Corpus refresh / backfill:** `pull_2023_2025.py`, `pull_2026.py`,
  `pull_outside_dates.py`, `backfill_meta.py`, `backfill_meta` variants,
  `apply_year_backfill.py`, `apply_tmdb_remap_migrate.py`,
  `apply_poster_primary_drift.py`, `refetch_tmdb_runtime.py`,
  `reanalyze_poster_ids.py`, `analyze_color_ids.py`, `compare_tmdb_imdb_horror.py`.
- **Title boxes (choose one source):** `title_boxes.py` *(local EasyOCR, canonical
  local path)*, `title_boxes_rekognition.py` / `title_boxes_backfill_s3.py`
  *(AWS Rekognition)*, `title_boxes_vision_pilot.py` *(GCP Vision pilot)*.
- **AWS / cloud enrichment:** `rekognition_enrich.py`, `rekognition_backfill_s3.py`,
  `nova_lite_enrich.py`, `nova_poster_enrich.py`, `owlv2_creature_boxes.py`,
  `creature_detect_dryrun.py`, `multi_poster_pipeline.py`,
  `jobs_dashboard_poller.py`. Shell orchestrators live in `aws/`.
- **QA review-page builders (internal, excluded from Pages deploy):**
  `build_comedy_review.py`, `build_corpus_filter_qa.py`,
  `build_label_qa_medium_r2.py`, `build_label_qa_medium_r3.py`,
  `build_label_qa_typography.py`, `build_ocr_title_review.py`,
  `build_poster_drift_review.py`.

## Regenerating data

Heavy derived outputs are **not** stored in git (they ballooned the history —
`.git` had grown to ~1.4 GB from churned CSV/NPZ blobs). The published site
serves `site/data/*.js`, so the per-poster metric CSVs are build inputs, not
deploy artifacts. They are listed in `.gitignore`; regenerate locally:

| Want | Run |
|------|-----|
| Color metrics (`posters.csv`, `yearly.json`) | `python3 fear_pipeline.py --all` |
| CLIP embeddings cache (`clip_embeddings.npz`) | `python3 clip_embed.py` |
| Semantic metric CSVs (census/medium/typography/faces/segmentation/…) | run the matching `clip_*.py` / `faces_v2.py` / `multi_analyze.py` / `segmentation.py` (see tables above) |
| Site data (`site/data/lookup.js`, `explorer.js`, `creature_boxes.js`, `series.js`) | `python3 build_lookup.py && python3 build_explorer.py && python3 build_site.py` |

`site/data/*.js` and `pipeline/data/posters.csv` **are** committed (the
site/Pages deploy serves them). Everything else under `pipeline/data/` that is
a large derived output is gitignored — rebuild it from the pipeline rather than
committing it.

## Legacy

Superseded scripts kept for reference live in `legacy/` — see
`legacy/README.md`. They are not used by the current site or essay.

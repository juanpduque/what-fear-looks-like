# The Anatomy of Fear

**100 years of horror movie posters, one pixel at a time.**
A data-driven visual essay by [Pulp Analytics](https://medium.com/pulp-analytics), in the style of [The Pudding](https://pudding.cool).

We analyze **18,716** horror movie posters (1920–2022) to measure how the way we sell fear has changed: color (the Darkness Curve, the Rise of Red, the Color River), faces, monsters, medium (painted vs. photographic), typography, composition/layout, aesthetics, and material/scene makeup. From the full TMDB horror corpus we exclude titles genre-tagged `Animation` and `Music`, and films whose TMDB `original_language` is not English (~8,907) — non-English poster lettering skewed typography/OCR. **TV Movies (telefilms) are kept** — they are single films made for television, not series, and still sell fear on a one-sheet. Lists in `pipeline/data/excluded_*.csv`, applied via `python3 apply_exclusions.py`.

## Structure

```
pipeline/         Python pipeline: dataset -> posters -> metrics -> CSV/JSON
  data/           Pipeline outputs (posters/ and horror_movies.csv are gitignored)
  data/legacy/    Superseded outputs, kept for reference (see pipeline/legacy/README.md)
  models/         Face-detection ONNX model; CLIP weights are gitignored (auto-downloaded)
  legacy/         Superseded scripts, kept for reference
site/             The scrollytelling page (static HTML/CSS/JS, no backend)
docs/             Strategy, essay draft & poster shortlist (Spanish/English)
```

## Run the pipeline

Every script is resumable and writes into `pipeline/data/`.

### 1. Color metrics (core)

```bash
cd pipeline
pip3 install pandas numpy pillow scikit-learn matplotlib requests
python3 fear_pipeline.py                    # 1,000-poster validation sample
python3 fear_pipeline.py --all              # full dataset (~28.7k before exclusions, ~1GB)
# after a full run (or any metric recompute), drop Animation + Music + non-EN
# and rebuild aggregates + site chart series:
python3 apply_exclusions.py                 # uses data/excluded_*.csv → 18,716
#                                     also writes ../site/data/series.js
python3 fear_pipeline.py --refresh --api-key YOUR_TMDB_KEY   # add post-2022 films
python3 fear_pipeline.py --backfill         # fill in 1920-1949 metadata
```

Outputs: `posters.csv` (per-poster metrics), `yearly.json` + `hue_river.json`
(feed the site via `export_site_series.py` → `site/data/series.js`),
`darkness_curve.png` (validation chart).

Or export chart series alone (without re-filtering):

```bash
python3 export_site_series.py               # → ../site/data/series.js
```

`backfill_meta.py` persists 1920–1949 film metadata from TMDB Discover to CSV
(the in-pipeline backfill above only holds it in memory).

### 2. Semantic chapters (CLIP + face detection)

```bash
pip3 install torch open_clip_torch opencv-python shapely
python3 clip_embed.py              # embeddings cache -> clip_embeddings.npz (~20-40 min CPU)
python3 clip_census.py             # monster census -> census.csv, census_decade.json
python3 clip_medium.py             # painted vs. photographic -> medium.csv
python3 clip_typography_axis.py    # ornate<->minimal axis -> typography.csv, typography_decade.json
python3 faces_v2.py                # YuNet face detection -> faces_v2.csv, faces_v2_decade.json
python3 multi_analyze.py           # composition, typography, grid & alignment -> attributes.csv, attributes_decade.json
```

`clip_census.py`, `clip_medium.py`, and `clip_typography_axis.py` all reuse
the cached embeddings from `clip_embed.py`, so run that first.

`multi_analyze.py` is a small plugin framework (see its docstring): each
metric group (`composition`, `typography`, `grid`, `aesthetic`, `diagonal`)
declares its own output columns, so `python3 multi_analyze.py --metrics grid`
can add a new group later without recomputing or losing the ones already
finished. `grid` measures layout alignment and `aesthetic` measures visual
balance + color harmony, both with plain OpenCV/Shapely — no
LayoutParser/Detectron2, whose pretrained models are trained on document
layouts, not poster art, and whose Detectron2 backend has an unresolved
checkpoint-loading bug on macOS/Apple Silicon.

`diagonal` adds two more: **diagonal_score** (share of Hough-detected line
length running at a 25–65° angle — a blade, a slashed logo, a body thrown
off-axis) and **pyramid_shift** (energy-weighted horizontal spread of the
bottom third of the poster minus the top third — positive means a wider
"base" and narrower "apex", the classic pyramid; negative means the
opposite, an inverted funnel). Validated by eye against hand-inspected
artwork: King Kong's fanned crowd → pyramid_shift +0.06; Halloween's
black void swallowing the bottom two-thirds → -0.37, the most inverted
shape among the classics we checked. `diagonal_score` has a real,
clean century-level trend (peaks in the atomic-pulp mid-1950s around
~38% on the 5-year rolling series, ~36% as a 1950s decade mean; falls
to ~23% by the 2020s — posters stopped leaning, same direction as the
text-coverage and symmetry trends). `pyramid_shift`
does not: it averages out to roughly zero by decade (top-heavy and
bottom-heavy compositions cancel out) — it's a real per-poster
signature, not a population-level trend. Caveat: a real share of what
`diagonal_score` catches is stylized diagonal title lettering, not only
figure pose; and `pyramid_shift` can be moved by a wide title-text
block independent of the illustrated figure — treat both as coarse
proxies, not literal triangle-fitting.

### 3. Semantic segmentation (material & scene composition)

```bash
pip3 install transformers   # torch + open_clip already required above
python3 segmentation.py --validate       # sanity-check against known posters
python3 segmentation.py --sample 3000    # stratified sample, ~1h on CPU
python3 segmentation.py                  # full corpus before exclusions (~10-12h CPU)
python3 segmentation.py --budget 300     # stop after N seconds, rerun to resume
```

Three complementary %-of-area signals per poster (see the script's
docstring for the full rationale): **SegFormer-b0** (ADE20K, real pixel-level
segmentation, e.g. sky/water/tree/rock/building), **Minc-Materials-23**
(SigLIP2, material taxonomy: metal/fabric/stone/wood/skin...) applied per
grid patch, and **CLIP zero-shot** on the same grid against a horror-specific
open vocabulary (blood, smoke, bone) that neither of the above covers.
Outputs: `segmentation.csv` (per-poster), `segmentation_decade.json` (a
"material palette" by decade, same shape as `hue_river.json`).

Ran a stratified sample across all 11 decades; after exclusions the site
uses **n = 1,721** posters. Validated `--validate` against 5 posters with
manually-checked artwork (Jaws, Friday the 13th, The Blair Witch Project,
The Evil Dead, The Thing) before trusting any of it. Real, useful signal:
`clip_blood` enters the top classes starting in the 1970s and stays there
through 2020 — tracks the slasher era's shift toward explicit gore, and
`clip_*` (CLIP zero-shot) validated cleanly on every test case. **Known
bias, don't trust at face value:** `ade_wall` (SegFormer) and `minc_plastic`
(Minc-Materials-23) both fire as systematic false positives on
abstract/painted backgrounds that aren't walls or plastic at all — both
models were trained on real-world photos, not illustrated poster art, and
default to their closest "flat surface" class when the scene doesn't look
like a real photo. `ade_water`/`minc_water` can also be fooled by a
dominant blue color cast with no literal water. Treat those columns as
noise; `clip_*` and the other `ade_*`/`minc_*` columns that passed
validation (tree, sea, person, skin, forest, weapon, night_sky) are the
trustworthy part of this dataset.

No Detectron2 here either — all three models install via
`pip install transformers` with official arm64 wheels. Minc-Materials-23 is
the slowest of the three on CPU (~1s/poster even at a coarse 2×2 grid), so a
full run is a multi-hour unattended job; the stratified `--sample` is enough
to see decade-level trends without committing to that.

## View the site

Live essay (GitHub Pages): **https://juanpduque.github.io/anatomy-of-fear/**

Deploy: pushes to `main` that touch `site/` run `.github/workflows/pages.yml`.
Or trigger **Actions → Deploy GitHub Pages → Run workflow**.


Open `site/index.html` in a browser — it's fully static, no build step.
Prefer a local server so lazy-loaded assets resolve cleanly
(`python3 -m http.server` from the repo root, then open `/site/`).

Chart series (`RIVER`, `DARK_PTS`, census, …) live in `site/data/series.js`,
regenerated by `export_site_series.py` (also at the end of `apply_exclusions.py`).
`site/data/explorer.js` embeds the light per-poster grid (with TMDB `poster_path`
for CDN images) — rebuild with `python3 build_explorer.py`. The
**Dissect any poster** search UI also needs the full analysis index:

```bash
python3 pipeline/build_explorer.py  # writes site/data/explorer.js
python3 pipeline/build_lookup.py    # writes site/data/lookup.js (~12 MB)
```

That lookup file is lazy-loaded on first search (or when a grid tile is clicked).
Specimen images used in the essay live in `site/assets/posters/` (the full
`pipeline/data/posters/` tree stays gitignored).

## License

The pipeline and site code are MIT licensed (see `LICENSE`). This does not
extend to poster images, TMDB metadata, or third-party datasets — see credits
below.

## Data & credits

Film data and posters from [TMDB](https://www.themoviedb.org/) (this project uses the TMDB API but is not endorsed or certified by TMDB). Base dataset: [horror-movies](https://github.com/tashapiro/horror-movies) by Tanya Shapiro (TidyTuesday 2022-11-01). Palette method adapted from ["The Colour of Horror"](https://dl.acm.org/doi/10.1145/3565516.3565523) (ACM EVMP 2022). Industry context: [Stephen Follows' Horror Movie Report](https://stephenfollows.com/p/the-horror-movie-report). Face detection: [YuNet](https://github.com/opencv/opencv_zoo/tree/main/models/face_detection_yunet) (OpenCV Zoo). Semantic chapters: [OpenAI CLIP](https://github.com/openai/CLIP) via [open_clip](https://github.com/mlfoundations/open_clip). Scene segmentation: [SegFormer](https://huggingface.co/nvidia/segformer-b0-finetuned-ade-512-512) (NVIDIA, ADE20K). Material recognition: [Minc-Materials-23](https://huggingface.co/prithivMLmods/Minc-Materials-23), in the spirit of the original [MINC](http://opensurfaces.cs.cornell.edu/publications/minc/) dataset (Bell et al., CVPR 2015).

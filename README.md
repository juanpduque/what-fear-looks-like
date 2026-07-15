# The Anatomy of Fear

**100 years of horror movie posters, one pixel at a time.**
A data-driven visual essay by [Pulp Analytics](https://medium.com/pulp-analytics), in the style of [The Pudding](https://pudding.cool).

We analyze ~28,700 horror movie posters (1920–2022) to measure how the way we sell fear has changed: color (the Darkness Curve, the Rise of Red, the Color River), faces, monsters, medium (painted vs. photographic), typography, and composition.

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
python3 fear_pipeline.py --all              # full dataset (~28.7k posters, ~1GB)
python3 fear_pipeline.py --refresh --api-key YOUR_TMDB_KEY   # add post-2022 films
python3 fear_pipeline.py --backfill         # fill in 1920-1949 metadata
```

Outputs: `posters.csv` (per-poster metrics), `yearly.json` + `hue_river.json`
(feed the site), `darkness_curve.png` (validation chart).

`backfill_meta.py` persists 1920–1949 film metadata from TMDB Discover to CSV
(the in-pipeline backfill above only holds it in memory).

### 2. Semantic chapters (CLIP + face detection)

```bash
pip3 install torch open_clip_torch opencv-python
python3 clip_embed.py              # embeddings cache -> clip_embeddings.npz (~20-40 min CPU)
python3 clip_census.py             # monster census -> census.csv, census_decade.json
python3 clip_medium.py             # painted vs. photographic -> medium.csv
python3 clip_typography_axis.py    # ornate<->minimal axis -> typography.csv, typography_decade.json
python3 faces_v2.py                # YuNet face detection -> faces_v2.csv, faces_v2_decade.json
python3 multi_analyze.py           # composition + text coverage -> attributes.csv, attributes_decade.json
```

`clip_census.py`, `clip_medium.py`, and `clip_typography_axis.py` all reuse
the cached embeddings from `clip_embed.py`, so run that first.

## View the site

Open `site/index.html` in a browser — it's fully static, no build step, no
server. `site/data/explorer.js` embeds the per-poster data for the
interactive grid.

## License

The pipeline and site code are MIT licensed (see `LICENSE`). This does not
extend to poster images, TMDB metadata, or third-party datasets — see credits
below.

## Data & credits

Film data and posters from [TMDB](https://www.themoviedb.org/) (this project uses the TMDB API but is not endorsed or certified by TMDB). Base dataset: [horror-movies](https://github.com/tashapiro/horror-movies) by Tanya Shapiro (TidyTuesday 2022-11-01). Palette method adapted from ["The Colour of Horror"](https://dl.acm.org/doi/10.1145/3565516.3565523) (ACM EVMP 2022). Industry context: [Stephen Follows' Horror Movie Report](https://stephenfollows.com/p/the-horror-movie-report). Face detection: [YuNet](https://github.com/opencv/opencv_zoo/tree/main/models/face_detection_yunet) (OpenCV Zoo). Semantic chapters: [OpenAI CLIP](https://github.com/openai/CLIP) via [open_clip](https://github.com/mlfoundations/open_clip).

#!/usr/bin/env python3
"""
Reusable batch-analysis framework for The Anatomy of Fear.
============================================================
Register a per-poster metric function; the harness handles image decoding,
checkpointing/resume, time budgets, and per-decade aggregation.

Add a new analysis in 3 steps:
  1. Write a function  fn(bgr, gray) -> dict of scalar metrics
  2. Decorate it with  @metric("name", cols=[...])   # declare its output columns
  3. Run  python3 multi_analyze.py --metrics name

Declaring `cols` lets a metric be added later without re-running (or losing
the resumability of) metrics that already finished: a poster only counts as
"done" for a given run if the checkpoint already has non-null values in that
run's requested columns, not just because its id is present at all.

Usage:
  python3 multi_analyze.py                          # all metrics, full 28k (resumable)
  python3 multi_analyze.py --metrics composition    # one group
  python3 multi_analyze.py --sample 500             # quick validation
  python3 multi_analyze.py --budget 33              # stop after N seconds (rerun to resume)

Outputs: data/attributes.csv (per poster), data/attributes_decade.json
"""
import argparse, json, time
from pathlib import Path
import numpy as np
import pandas as pd
import cv2
from shapely.geometry import box as shp_box

DATA = Path(__file__).parent / "data"
CHECKPOINT = DATA / "attributes_partial.csv"
ANALYSIS_WIDTH = 180

REGISTRY = {}
METRIC_COLS = {}
def metric(name, cols):
    def deco(fn):
        REGISTRY[name] = fn
        METRIC_COLS[name] = list(cols)
        return fn
    return deco

# ============================= METRICS =====================================

def _mser_text_boxes(gray):
    """Filtered MSER glyph candidates: small-to-medium, wider than tall or
    roughly square. Heuristic, not OCR: trend-comparable across eras, not
    absolute truth. Shared by typography() and grid_alignment().

    Title *overlays* are NOT derived here — see title_boxes.py (EasyOCR +
    TMDB title match). Billboard glyphs often exceed these caps; mid-sheet
    texture fools MSER into false title boxes.
    """
    mser = cv2.MSER_create(delta=5, min_area=15, max_area=2000)
    regions, _ = mser.detectRegions(gray)
    H, W = gray.shape
    boxes = []
    for pts in regions:
        x, y, w, h = cv2.boundingRect(pts.reshape(-1, 1, 2))
        ar = w / max(h, 1)
        # text-ish: small-to-medium, wider than tall or roughly square glyphs
        if 0.1 < ar < 12 and 4 <= h <= H * 0.12 and w < W * 0.9:
            boxes.append((x, y, w, h))
    return boxes

@metric("composition", cols=["symmetry", "neg_space", "complexity", "mass_y", "mass_x"])
def composition(bgr, gray):
    """Symmetry, negative space, visual complexity, center of visual mass."""
    small = cv2.resize(gray, (64, 96))
    # horizontal symmetry: 1 = perfect mirror (elevated horror loves this)
    sym = 1.0 - float(np.abs(small.astype(int) - small[:, ::-1]).mean()) / 255.0
    gx = cv2.Sobel(gray, cv2.CV_32F, 1, 0); gy = cv2.Sobel(gray, cv2.CV_32F, 0, 1)
    mag = np.hypot(gx, gy)
    flat = float((mag < 8).mean())                      # negative-space proxy
    edges = float(cv2.Canny(gray, 60, 140).mean()) / 255  # visual complexity
    # center of visual mass (where the "stuff" is), normalized 0-1
    tot = mag.sum() + 1e-9
    ys, xs = np.indices(mag.shape)
    cy = float((ys * mag).sum() / tot) / mag.shape[0]
    cx = float((xs * mag).sum() / tot) / mag.shape[1]
    return dict(symmetry=round(sym, 4), neg_space=round(flat, 4),
                complexity=round(edges, 4), mass_y=round(cy, 4), mass_x=round(cx, 4))

@metric("typography", cols=["text_area", "text_y", "text_regions"])
def typography(bgr, gray):
    """Text coverage via MSER — decade trends only.

    Per-poster title boxes (text_x/top/w/h) come from title_boxes.py
    (EasyOCR). Re-running this metric must not overwrite those columns.
    """
    H, W = gray.shape
    boxes = _mser_text_boxes(gray)
    mask = np.zeros((H, W), np.uint8)
    for x, y, w, h in boxes:
        mask[y:y + h, x:x + w] = 1
    area = float(mask.mean())
    ys = np.where(mask.any(axis=1))[0]
    ty = float(ys.mean() / H) if len(ys) else -1.0   # 0=top, 1=bottom
    return dict(
        text_area=round(area, 4), text_y=round(ty, 4), text_regions=len(boxes),
    )

@metric("grid", cols=["align_score", "thirds_dist", "n_blocks"])
def grid_alignment(bgr, gray):
    """Grid & alignment: detects layout blocks (clustered text regions + the
    dominant visual mass) and measures how tightly their edges share
    alignment lines, plus how close the main visual sits to a rule-of-thirds
    grid.

    No LayoutParser/Detectron2: those models are trained on document layouts
    (PubLayNet academic papers, PRImA/HJDataset/NewspaperNavigator scanned
    periodicals), not illustrated/photographic poster art, and Detectron2
    has an unresolved checkpoint-loading bug on macOS/Apple Silicon. Cheap
    OpenCV heuristics + Shapely geometry instead -- same spirit, no heavy
    model dependency.
    """
    H, W = gray.shape

    # 1. text blocks: merge nearby MSER glyphs into a handful of blocks
    # (roughly title/tagline/credits) via dilation + connected components.
    txt_mask = np.zeros((H, W), np.uint8)
    for x, y, w, h in _mser_text_boxes(gray):
        txt_mask[y:y+h, x:x+w] = 1
    txt_mask = cv2.dilate(txt_mask, np.ones((5, 15), np.uint8))
    n_cc, _, stats, _ = cv2.connectedComponentsWithStats(txt_mask)
    boxes = [(x, y, x + w, y + h) for x, y, w, h, area in stats[1:] if area >= 25]

    # 2. dominant visual mass: same gradient-magnitude map as composition(),
    # thresholded + dilated, largest external contour by area.
    gx = cv2.Sobel(gray, cv2.CV_32F, 1, 0); gy = cv2.Sobel(gray, cv2.CV_32F, 0, 1)
    mag = np.hypot(gx, gy)
    busy = cv2.dilate((mag > 25).astype(np.uint8), np.ones((7, 7), np.uint8))
    contours, _ = cv2.findContours(busy, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    main_box = None
    if contours:
        c = max(contours, key=cv2.contourArea)
        if cv2.contourArea(c) >= 0.01 * H * W:
            x, y, w, h = cv2.boundingRect(c)
            main_box = (x, y, x + w, y + h)
            boxes.append(main_box)

    n_blocks = len(boxes)

    # 3. alignment score: for each block and each of 6 alignment lines
    # (left/center-x/right, top/center-y/bottom), the min distance to the
    # same line of any other block, normalized and averaged -- lower means
    # more edges/centers share an implicit grid line (Lee et al., "Neural
    # Design Network", ECCV 2020).
    align_score = -1.0
    if n_blocks >= 2:
        geoms = [shp_box(*b) for b in boxes]
        lx = [(g.bounds[0], (g.bounds[0] + g.bounds[2]) / 2, g.bounds[2]) for g in geoms]
        ly = [(g.bounds[1], (g.bounds[1] + g.bounds[3]) / 2, g.bounds[3]) for g in geoms]
        dists = []
        for axis_vals, norm in ((lx, W), (ly, H)):
            for k in range(3):  # edge/center/edge
                vals = [v[k] for v in axis_vals]
                for i, vi in enumerate(vals):
                    others = vals[:i] + vals[i + 1:]
                    dists.append(min(abs(vi - vj) for vj in others) / norm)
        align_score = round(float(np.mean(dists)), 4)

    # 4. rule of thirds: distance from the main visual mass's centroid to the
    # nearest of the 4 thirds-grid intersections.
    thirds_dist = -1.0
    if main_box:
        cx = (main_box[0] + main_box[2]) / 2 / W
        cy = (main_box[1] + main_box[3]) / 2 / H
        pts = [(px, py) for px in (1 / 3, 2 / 3) for py in (1 / 3, 2 / 3)]
        thirds_dist = round(min(np.hypot(cx - px, cy - py) for px, py in pts), 4)

    return dict(align_score=align_score, thirds_dist=thirds_dist, n_blocks=n_blocks)

@metric("aesthetic", cols=["balance", "harmony"])
def aesthetic(bgr, gray):
    """Visual balance and color harmony. Rule of thirds is already covered
    by grid_alignment()'s thirds_dist -- no need to duplicate it here.

    balance: distance from the geometric center to the centroid of a
    saliency map (proxy for "visual weight"), normalized. Lower = more
    balanced (same convention as align_score/thirds_dist).

    harmony: whether the poster's dominant hues fit a classic color-wheel
    scheme (analogous/tetradic/triadic/complementary). Higher = colors more
    closely follow one of those relationships (same convention as symmetry).
    """
    H, W = gray.shape

    balance = -1.0
    sal = cv2.saliency.StaticSaliencySpectralResidual_create()
    ok, smap = sal.computeSaliency(gray)
    if ok:
        tot = smap.sum() + 1e-9
        ys, xs = np.indices(smap.shape)
        cy = float((ys * smap).sum() / tot) / H
        cx = float((xs * smap).sum() / tot) / W
        balance = round(float(np.hypot(cx - 0.5, cy - 0.5)), 4)

    harmony = -1.0
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    hist = cv2.calcHist([hsv], [0], None, [36], [0, 180]).flatten()  # 10-degree bins
    peaks = np.argsort(hist)[-3:]
    peaks = peaks[hist[peaks] > hist.sum() * 0.03]  # drop near-empty peaks
    hues = sorted(peaks * 10.0)  # bin index -> degrees
    if len(hues) >= 2:
        scheme_angles = (30, 90, 120, 180)  # analogous, tetradic, triadic, complementary
        devs = []
        for i in range(len(hues)):
            for j in range(i + 1, len(hues)):
                d = abs(hues[i] - hues[j])
                d = min(d, 360 - d)  # circular distance
                nearest = min(scheme_angles, key=lambda a: abs(d - a))
                devs.append(abs(d - nearest) / 180)
        harmony = round(1.0 - float(np.mean(devs)), 4)

    return dict(balance=balance, harmony=harmony)

@metric("diagonal", cols=["diagonal_score", "pyramid_shift"])
def diagonal_pyramid(bgr, gray):
    """Diagonal composition and triangular/pyramid weight-shift.

    diagonal_score: share of detected line-segment length (Hough transform
    on Canny edges) that runs at a diagonal angle (25-65 deg from
    horizontal) rather than near-horizontal/near-vertical. Higher = more
    of the poster's linework reads as diagonal (a blade, a body pose, a
    slanted logo). Validated by eye against hand-inspected artwork
    (Creature from the Black Lagoon, Halloween's knife) -- see README; a
    real share of what it catches is stylized title lettering, not just
    figure composition, so treat it as "diagonal linework" broadly, not
    strictly "diagonal figure pose".

    pyramid_shift: energy-weighted horizontal spread of the bottom third of
    the poster minus the top third. Positive = wider "base" at the bottom,
    narrower "apex" at top -- the classic pyramid arrangement (King Kong's
    fanned crowd below, Kong's head above). Negative = the opposite, an
    inverted-pyramid/funnel shape (Halloween's black void swallowing the
    bottom two-thirds while all the activity crowds the top). This is a
    coarse proxy, not literal triangle-fitting -- a wide title-text block
    can shift it on its own, independent of the illustrated figure.
    """
    H, W = gray.shape

    edges = cv2.Canny(gray, 60, 140)
    min_len = int(min(H, W) * 0.12)
    lines = cv2.HoughLinesP(edges, 1, np.pi / 180, threshold=25,
                             minLineLength=min_len, maxLineGap=6)
    diag_len = total_len = 0.0
    if lines is not None:
        for x1, y1, x2, y2 in lines[:, 0]:
            length = float(np.hypot(x2 - x1, y2 - y1))
            ang = abs(np.degrees(np.arctan2(y2 - y1, x2 - x1))) % 180
            ang = min(ang, 180 - ang)  # 0=horizontal, 90=vertical
            total_len += length
            if 25 <= ang <= 65:
                diag_len += length
    diagonal_score = round(diag_len / total_len, 4) if total_len > 0 else 0.0

    gx = cv2.Sobel(gray, cv2.CV_32F, 1, 0); gy = cv2.Sobel(gray, cv2.CV_32F, 0, 1)
    mag = np.clip(np.hypot(gx, gy) - 15, 0, None)  # suppress low-level texture noise
    xs = np.arange(W)
    def band_spread(y0, y1):
        band = mag[y0:y1].sum(axis=0)
        tot = band.sum()
        if tot < 1e-6:
            return 0.0
        cx = (xs * band).sum() / tot
        var = ((xs - cx) ** 2 * band).sum() / tot
        return 2 * np.sqrt(var) / W
    pyramid_shift = round(band_spread(2 * H // 3, H) - band_spread(0, H // 3), 4)

    return dict(diagonal_score=diagonal_score, pyramid_shift=pyramid_shift)

# ============================ HARNESS ======================================

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--metrics", default=",".join(REGISTRY),
                    help=f"comma-separated: {','.join(REGISTRY)}")
    ap.add_argument("--sample", type=int, default=0, help="0 = all posters")
    ap.add_argument("--budget", type=float, default=0, help="seconds; 0 = no limit")
    args = ap.parse_args()
    fns = {k: REGISTRY[k] for k in args.metrics.split(",")}
    # Note: this only checks that ALL requested metrics' columns are present;
    # mixing an already-finished metric with a brand-new one recomputes the
    # finished one too (wasteful but harmless) rather than partially skipping.
    needed_cols = sorted({c for k in fns for c in METRIC_COLS[k]})

    meta = pd.read_csv(DATA / "posters.csv", usecols=["id", "year"])
    if args.sample:
        meta = meta.groupby(meta.year // 10 * 10, group_keys=False).apply(
            lambda g: g.sample(min(len(g), max(1, args.sample // 8)), random_state=42))

    # Seed the resumable checkpoint from the published attributes.csv when
    # missing, so a single-metric re-run merges into existing columns instead
    # of replacing the whole file with only that metric's outputs.
    final_path = DATA / "attributes.csv"
    if not CHECKPOINT.exists() and final_path.exists():
        pd.read_csv(final_path).to_csv(CHECKPOINT, index=False)

    done = set()
    if CHECKPOINT.exists():
        existing = pd.read_csv(CHECKPOINT)
        if all(c in existing.columns for c in needed_cols):
            done = set(existing.loc[existing[needed_cols].notna().all(axis=1), "id"])
    todo = meta[~meta.id.isin(done)]
    print(f"pending: {len(todo):,} / {len(meta):,}")

    t0, rows = time.time(), []
    for pid, yr in zip(todo.id, todo.year):
        if args.budget and time.time() - t0 > args.budget:
            break
        f = DATA / "posters" / f"{pid}.jpg"
        if not f.exists():
            continue
        try:
            bgr = cv2.imread(str(f))
            h, w = bgr.shape[:2]
            s = ANALYSIS_WIDTH / w
            bgr = cv2.resize(bgr, (ANALYSIS_WIDTH, int(h * s)))
            gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
            row = dict(id=pid, year=int(yr))
            for fn in fns.values():
                row.update(fn(bgr, gray))
            rows.append(row)
        except Exception:
            continue
    if rows:
        new_df = pd.DataFrame(rows).set_index("id")
        if CHECKPOINT.exists():
            merged = pd.read_csv(CHECKPOINT).set_index("id")
            for c in new_df.columns:
                if c not in merged.columns:
                    merged[c] = np.nan
            merged.update(new_df)  # overwrite/add columns for overlapping ids
            new_ids = new_df.loc[~new_df.index.isin(merged.index)]
            merged = pd.concat([merged, new_ids]) if len(new_ids) else merged
        else:
            merged = new_df
        merged.reset_index().to_csv(CHECKPOINT, index=False)
    total = len(done) + len(rows)
    rate = len(rows) / max(time.time() - t0, 1e-9)
    print(f"batch: {len(rows):,} | total: {total:,}/{len(meta):,} | {rate:.0f}/s")

    if total >= len(meta) or (args.sample and total >= len(meta)):
        d = pd.read_csv(CHECKPOINT).drop_duplicates("id")
        # Merge into the published table so --metrics typography (etc.) never
        # wipes composition/grid/aesthetic/diagonal columns that already exist.
        if final_path.exists():
            prev = pd.read_csv(final_path).set_index("id")
            d_idx = d.set_index("id")
            for c in d_idx.columns:
                if c not in prev.columns:
                    prev[c] = np.nan
            prev.update(d_idx)
            new_ids = d_idx.loc[~d_idx.index.isin(prev.index)]
            if len(new_ids):
                prev = pd.concat([prev, new_ids])
            d = prev.reset_index()
        d.to_csv(final_path, index=False)
        d["decade"] = (d.year // 10) * 10
        cols = [c for c in d.columns if c not in ("id", "year", "decade")]
        # -1.0 is a per-column "computation failed" sentinel for a subset of
        # metrics (e.g. harmony on near-monochrome posters) -- mask only
        # those columns to NaN before averaging. Metrics that are legitimately
        # signed (pyramid_shift) or non-negative-by-construction (n_blocks,
        # diagonal_score) must NOT be blanket-filtered on "value >= 0".
        SENTINEL_COLS = {"align_score", "thirds_dist", "balance", "harmony"}
        masked = d[cols].copy()
        for c in SENTINEL_COLS & set(cols):
            masked[c] = masked[c].where(masked[c] >= 0)
        agg = masked.groupby(d["decade"])[cols].mean().round(4)
        agg["n"] = d.groupby("decade").size()
        agg.reset_index().to_json(DATA / "attributes_decade.json", orient="records")
        print("\n=== BY DECADE ===")
        print(agg.to_string())

if __name__ == "__main__":
    main()

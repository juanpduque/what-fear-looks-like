#!/usr/bin/env python3
"""
Reusable batch-analysis framework for The Anatomy of Fear.
============================================================
Register a per-poster metric function; the harness handles image decoding,
checkpointing/resume, time budgets, and per-decade aggregation.

Add a new analysis in 3 steps:
  1. Write a function  fn(bgr, gray) -> dict of scalar metrics
  2. Decorate it with  @metric("name")
  3. Run  python3 multi_analyze.py --metrics name

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

DATA = Path(__file__).parent / "data"
CHECKPOINT = DATA / "attributes_partial.csv"
ANALYSIS_WIDTH = 180

REGISTRY = {}
def metric(name):
    def deco(fn):
        REGISTRY[name] = fn
        return fn
    return deco

# ============================= METRICS =====================================

@metric("composition")
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

@metric("typography")
def typography(bgr, gray):
    """Text coverage and placement via MSER text-region detection.
    Heuristic, not OCR: trend-comparable across eras, not absolute truth."""
    mser = cv2.MSER_create(delta=5, min_area=15, max_area=2000)
    regions, _ = mser.detectRegions(gray)
    H, W = gray.shape
    mask = np.zeros((H, W), np.uint8)
    n_txt = 0
    for pts in regions:
        x, y, w, h = cv2.boundingRect(pts.reshape(-1, 1, 2))
        ar = w / max(h, 1)
        # text-ish: small-to-medium, wider than tall or roughly square glyphs
        if 0.1 < ar < 12 and 4 <= h <= H * 0.12 and w < W * 0.9:
            mask[y:y+h, x:x+w] = 1
            n_txt += 1
    area = float(mask.mean())
    ys = np.where(mask.any(axis=1))[0]
    ty = float(ys.mean() / H) if len(ys) else -1.0   # 0=top, 1=bottom
    return dict(text_area=round(area, 4), text_y=round(ty, 4), text_regions=n_txt)

# ============================ HARNESS ======================================

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--metrics", default=",".join(REGISTRY),
                    help=f"comma-separated: {','.join(REGISTRY)}")
    ap.add_argument("--sample", type=int, default=0, help="0 = all posters")
    ap.add_argument("--budget", type=float, default=0, help="seconds; 0 = no limit")
    args = ap.parse_args()
    fns = {k: REGISTRY[k] for k in args.metrics.split(",")}

    meta = pd.read_csv(DATA / "posters.csv", usecols=["id", "year"])
    if args.sample:
        meta = meta.groupby(meta.year // 10 * 10, group_keys=False).apply(
            lambda g: g.sample(min(len(g), max(1, args.sample // 8)), random_state=42))
    done = set(pd.read_csv(CHECKPOINT).id) if CHECKPOINT.exists() else set()
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
        df = pd.DataFrame(rows)
        df.to_csv(CHECKPOINT, mode="a", header=not CHECKPOINT.exists(), index=False)
    total = len(done) + len(rows)
    rate = len(rows) / max(time.time() - t0, 1e-9)
    print(f"batch: {len(rows):,} | total: {total:,}/{len(meta):,} | {rate:.0f}/s")

    if total >= len(meta) or (args.sample and total >= len(meta)):
        d = pd.read_csv(CHECKPOINT).drop_duplicates("id")
        d.to_csv(DATA / "attributes.csv", index=False)
        d["decade"] = (d.year // 10) * 10
        cols = [c for c in d.columns if c not in ("id", "year", "decade")]
        agg = d[d[cols].min(axis=1) >= 0].groupby("decade")[cols].mean().round(4)
        agg["n"] = d.groupby("decade").size()
        agg.reset_index().to_json(DATA / "attributes_decade.json", orient="records")
        print("\n=== BY DECADE ===")
        print(agg.to_string())

if __name__ == "__main__":
    main()

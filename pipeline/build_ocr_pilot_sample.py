#!/usr/bin/env python3
"""Build stratified OCR pilot v2 sample (n≈100) for Medium-style exploratory eval.

Stratification:
  - decade from posters.csv year
  - high/low text_area (attributes.csv): median split within decade if possible,
    else global median
  - prefer English (horror_movies.csv original_language == 'en')
  - only ids with local JPG under data/posters/

Outputs:
  data/qa/ocr_pilot_v2/sample_ids.txt
  data/qa/ocr_pilot_v2/sample_meta.csv

  python3 build_ocr_pilot_sample.py
  python3 build_ocr_pilot_sample.py --n 100 --seed 42
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

DATA = Path(__file__).resolve().parent / "data"
POSTERS = DATA / "posters"
POSTERS_CSV = DATA / "posters.csv"
ATTR_CSV = DATA / "attributes.csv"
HORROR_CSV = DATA / "horror_movies.csv"
OUT_DIR = DATA / "qa" / "ocr_pilot_v2"


def decade_of(year) -> int:
    try:
        y = int(year)
    except (TypeError, ValueError):
        return -1
    if y < 1890 or y > 2035:
        return -1
    return (y // 10) * 10


def load_universe(prefer_english: bool = True) -> pd.DataFrame:
    posters = pd.read_csv(POSTERS_CSV, usecols=["id", "title", "year"])
    posters["id"] = posters["id"].astype(int)
    attr = pd.read_csv(ATTR_CSV, usecols=["id", "text_area"])
    attr["id"] = attr["id"].astype(int)
    m = posters.merge(attr, on="id", how="inner")

    if HORROR_CSV.exists():
        h = pd.read_csv(HORROR_CSV, usecols=["id", "original_language"])
        h["id"] = h["id"].astype(int)
        m = m.merge(h, on="id", how="left")
    else:
        m["original_language"] = None

    # local JPG only
    have = {int(p.stem) for p in POSTERS.glob("*.jpg") if p.stem.isdigit()}
    m = m[m["id"].isin(have)].copy()
    m["decade"] = m["year"].map(decade_of)
    m = m[m["decade"] >= 0].copy()

    if prefer_english and m["original_language"].notna().any():
        en = m[m["original_language"] == "en"].copy()
        if len(en) >= 50:
            m = en
        else:
            print(
                f"WARNING: only {len(en)} English rows; keeping full local universe",
                flush=True,
            )
    return m.reset_index(drop=True)


def assign_text_band(df: pd.DataFrame) -> pd.DataFrame:
    """Median-split text_area within decade; fall back to global median."""
    out = df.copy()
    global_med = float(out["text_area"].median())
    bands = []
    for dec, g in out.groupby("decade"):
        if len(g) >= 4 and g["text_area"].nunique() > 1:
            med = float(g["text_area"].median())
            src = "decade"
        else:
            med = global_med
            src = "global"
        for idx, row in g.iterrows():
            band = "high" if float(row["text_area"]) >= med else "low"
            bands.append((idx, band, med, src))
    band_df = pd.DataFrame(bands, columns=["_idx", "text_band", "text_median", "median_src"])
    band_df = band_df.set_index("_idx")
    out = out.join(band_df)
    return out


def stratified_sample(df: pd.DataFrame, n: int, seed: int) -> pd.DataFrame:
    """Allocate across decade × text_band strata, then sample within each."""
    df = assign_text_band(df)
    df["stratum"] = df["decade"].astype(str) + "_" + df["text_band"]
    strata = sorted(df["stratum"].unique())
    if not strata:
        raise SystemExit("empty universe after filters")

    # proportional allocation with at least 1 when stratum is large enough
    sizes = df.groupby("stratum").size()
    weights = sizes / sizes.sum()
    raw = (weights * n).to_dict()
    alloc = {k: int(np.floor(v)) for k, v in raw.items()}
    for k in list(alloc):
        if sizes[k] > 0 and alloc[k] == 0 and sizes[k] >= 2:
            alloc[k] = 1
    for k in alloc:
        alloc[k] = min(alloc[k], int(sizes[k]))
    total = sum(alloc.values())
    rem = n - total
    order = sorted(
        strata,
        key=lambda k: (sizes[k] - alloc[k], sizes[k]),
        reverse=True,
    )
    i = 0
    while rem > 0 and i < 10_000:
        k = order[i % len(order)]
        if alloc[k] < sizes[k]:
            alloc[k] += 1
            rem -= 1
        i += 1
        if all(alloc[s] >= sizes[s] for s in strata):
            break

    parts = []
    for j, k in enumerate(strata):
        take = alloc.get(k, 0)
        if take <= 0:
            continue
        g = df[df["stratum"] == k]
        take = min(take, len(g))
        parts.append(g.sample(n=take, random_state=seed + j))
    picked = pd.concat(parts, ignore_index=True).drop_duplicates("id")
    if len(picked) < n:
        rest = df[~df["id"].isin(picked["id"])]
        need = min(n - len(picked), len(rest))
        if need:
            picked = pd.concat(
                [picked, rest.sample(n=need, random_state=seed + 999)],
                ignore_index=True,
            )
    if len(picked) > n:
        picked = picked.sample(n=n, random_state=seed).reset_index(drop=True)
    return picked.sort_values(["decade", "text_band", "id"]).reset_index(drop=True)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--n", type=int, default=100)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--out-dir", default=str(OUT_DIR))
    ap.add_argument("--no-prefer-english", action="store_true")
    args = ap.parse_args()

    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)

    universe = load_universe(prefer_english=not args.no_prefer_english)
    print(
        f"universe n={len(universe)} decades={sorted(universe['decade'].unique().tolist())}",
        flush=True,
    )
    sample = stratified_sample(universe, args.n, args.seed)
    print(f"sample n={len(sample)}", flush=True)

    ids_path = out / "sample_ids.txt"
    ids_path.write_text(
        "\n".join(str(int(x)) for x in sample["id"].tolist()) + "\n",
        encoding="utf-8",
    )
    meta_cols = [
        "id",
        "title",
        "year",
        "decade",
        "text_area",
        "text_band",
        "text_median",
        "median_src",
        "original_language",
        "stratum",
    ]
    meta = sample[[c for c in meta_cols if c in sample.columns]].copy()
    meta.to_csv(out / "sample_meta.csv", index=False)

    # stratification report
    print("\nstratum counts:", flush=True)
    print(
        sample.groupby(["decade", "text_band"])
        .size()
        .unstack(fill_value=0)
        .to_string(),
        flush=True,
    )
    print(f"\nLISTO → {ids_path}", flush=True)
    print(f"LISTO → {out / 'sample_meta.csv'}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Color-analyze local posters for ids not yet in posters.csv and append.

Used to extend the corpus with 2023–2025 refreshes without a full re-download.

  python3 analyze_color_ids.py --ids-file data/new_2023_2025_ids.csv
"""
from __future__ import annotations

import argparse
import io
from pathlib import Path

import numpy as np
import pandas as pd

from fear_pipeline import analyze_poster

DATA = Path(__file__).resolve().parent / "data"
POSTERS = DATA / "posters"
OUT = DATA / "posters.csv"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ids-file", required=True, help="CSV with id,title,year")
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()

    ids = pd.read_csv(args.ids_file)
    for col in ("id", "title", "year"):
        if col not in ids.columns:
            raise SystemExit(f"ids-file needs columns id,title,year (missing {col})")
    ids["id"] = ids["id"].astype(int)
    ids["year"] = ids["year"].astype(int)

    existing = set()
    if OUT.exists():
        existing = set(pd.read_csv(OUT, usecols=["id"])["id"].astype(int))
    todo = ids[~ids["id"].isin(existing)].copy()
    print(f"color-analyze pending {len(todo)} / {len(ids)} (already {len(existing)})")

    rng = np.random.default_rng(args.seed)
    rows = []
    for i, r in enumerate(todo.itertuples(), 1):
        path = POSTERS / f"{int(r.id)}.jpg"
        if not path.exists():
            continue
        try:
            m = analyze_poster(path.read_bytes(), rng)
        except Exception as e:
            print(f"  FAIL {r.id}: {e}", flush=True)
            continue
        row = {
            "id": int(r.id),
            "title": r.title,
            "year": int(r.year),
            "brightness": m["brightness"],
            "dark_share": m["dark_share"],
            "saturation": m["saturation"],
            "red_share": m["red_share"],
            "band_red": m["band_red"],
            "band_warm": m["band_warm"],
            "band_green": m["band_green"],
            "band_blue": m["band_blue"],
            "band_purple": m["band_purple"],
            "band_dark": m["band_dark"],
            "palette": __import__("json").dumps(m["palette"]),
            "palette_share": __import__("json").dumps(m["palette_share"]),
        }
        rows.append(row)
        if i % 200 == 0 or i == len(todo):
            print(f"  {i}/{len(todo)}", flush=True)

    if not rows:
        print("nothing new")
        return
    new_df = pd.DataFrame(rows)
    if OUT.exists():
        prev = pd.read_csv(OUT)
        # align columns
        for c in new_df.columns:
            if c not in prev.columns:
                prev[c] = np.nan
        for c in prev.columns:
            if c not in new_df.columns:
                new_df[c] = np.nan
        out = pd.concat([prev, new_df[prev.columns]], ignore_index=True)
    else:
        out = new_df
    out = out.drop_duplicates("id", keep="last")
    out.to_csv(OUT, index=False)
    print(f"wrote {OUT} ({len(out)} rows, +{len(rows)} new)")


if __name__ == "__main__":
    main()

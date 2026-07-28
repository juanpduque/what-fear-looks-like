#!/usr/bin/env python3
"""Drop metric rows for given poster ids and re-run the analysis stack.

Use after swapping JPGs (e.g. apply_poster_primary_drift.py) so color / CLIP /
faces / segmentation match the new primary artwork.

  python3 reanalyze_poster_ids.py --ids-file data/qa/primary_drift_reanalyze_ids.csv --dry-run
  python3 reanalyze_poster_ids.py --ids-file data/qa/primary_drift_reanalyze_ids.csv
  python3 reanalyze_poster_ids.py --ids-file ... --skip-segmentation
  python3 reanalyze_poster_ids.py --ids-file ... --only drop   # solo limpiar filas
  python3 reanalyze_poster_ids.py --ids-file ... --only run    # asumir ya dropeados
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
DATA = HERE / "data"
POSTERS = DATA / "posters"

CSV_TARGETS = [
    "attributes.csv",
    "attributes_partial.csv",
    "faces_v2.csv",
    "faces_v2_partial.csv",
    "census.csv",
    "typography.csv",
    "medium.csv",
    "segmentation.csv",
    "segmentation_partial.csv",
]


def load_ids(path: Path) -> pd.DataFrame:
    d = pd.read_csv(path)
    if "id" not in d.columns:
        raise SystemExit(f"{path} necesita columna id")
    d["id"] = d["id"].astype(int)
    d = d.drop_duplicates("id")
    posters = pd.read_csv(DATA / "posters.csv", usecols=["id", "title", "year"])
    posters["id"] = posters["id"].astype(int)
    m = d[["id"]].merge(posters, on="id", how="left")
    m["year"] = pd.to_numeric(m["year"], errors="coerce").fillna(9999).astype(int)
    m["title"] = m["title"].fillna("").astype(str)
    missing = m[m["title"] == ""]
    if len(missing):
        raise SystemExit(f"{len(missing)} ids no estan en posters.csv: {missing['id'].head(8).tolist()}")
    return m[["id", "title", "year"]]


def drop_from_csvs(ids: set[int], dry_run: bool) -> None:
    for name in CSV_TARGETS:
        path = DATA / name
        if not path.exists():
            continue
        d = pd.read_csv(path)
        if "id" not in d.columns:
            continue
        before = len(d)
        d2 = d[~d["id"].astype(int).isin(ids)]
        removed = before - len(d2)
        print(f"  {name}: -{removed:,} ({before:,} → {len(d2):,})")
        if not dry_run and removed:
            d2.to_csv(path, index=False)


def drop_from_embeddings(ids: set[int], dry_run: bool) -> None:
    path = DATA / "clip_embeddings.npz"
    if not path.exists():
        return
    z = np.load(path)
    emb_ids = np.asarray(z["ids"])
    vecs = np.asarray(z["vecs"])
    keep = ~np.isin(emb_ids.astype(int), list(ids))
    removed = int((~keep).sum())
    print(f"  clip_embeddings.npz: -{removed:,} ({len(emb_ids):,} → {int(keep.sum()):,})")
    if not dry_run and removed:
        np.savez_compressed(path, ids=emb_ids[keep], vecs=vecs[keep])
    partial = DATA / "clip_embeddings_partial.npz"
    if partial.exists() and not dry_run:
        partial.unlink()
        print("  removed clip_embeddings_partial.npz")


def recolor(ids_df: pd.DataFrame, dry_run: bool) -> None:
    """Recompute color metrics in posters.csv for these ids (in place)."""
    from fear_pipeline import analyze_poster

    posters_path = DATA / "posters.csv"
    posters = pd.read_csv(posters_path)
    posters["id"] = posters["id"].astype(int)
    want = set(ids_df["id"])
    mask = posters["id"].isin(want)
    print(f"  recolor {int(mask.sum()):,} posters.csv rows", flush=True)
    if dry_run:
        return

    rng = np.random.default_rng(0)
    updates = []
    fail = 0
    for i, r in enumerate(ids_df.itertuples(index=False), 1):
        path = POSTERS / f"{int(r.id)}.jpg"
        if not path.exists():
            print(f"    miss jpg {r.id}", flush=True)
            fail += 1
            continue
        try:
            m = analyze_poster(path.read_bytes(), rng)
        except Exception as e:
            print(f"    FAIL color {r.id}: {e}", flush=True)
            fail += 1
            continue
        updates.append(
            {
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
                "palette": json.dumps(m["palette"]),
                "palette_share": json.dumps(m["palette_share"]),
            }
        )
        if i % 100 == 0 or i == len(ids_df):
            print(f"    color {i}/{len(ids_df)} ok={len(updates)} fail={fail}", flush=True)

    if not updates:
        print("  recolor: nothing updated", flush=True)
        return
    new_df = pd.DataFrame(updates).set_index("id")
    posters = posters.set_index("id")
    for col in new_df.columns:
        if col in posters.columns:
            posters.loc[new_df.index.intersection(posters.index), col] = new_df[col]
    posters = posters.reset_index()
    print(f"  writing posters.csv ({len(updates):,} refreshed)...", flush=True)
    posters.to_csv(posters_path, index=False)
    print(f"  posters.csv color refreshed for {len(updates):,} (fail={fail})", flush=True)


def run(cmd: list[str]) -> None:
    print(f"\n$ {' '.join(cmd)}", flush=True)
    subprocess.check_call(cmd, cwd=str(HERE))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ids-file", required=True)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--only", choices=["all", "drop", "run"], default="all")
    ap.add_argument("--skip-segmentation", action="store_true")
    ap.add_argument("--skip-export", action="store_true")
    args = ap.parse_args()

    ids_df = load_ids(Path(args.ids_file))
    ids = set(ids_df["id"])
    print(f"reanalyze {len(ids):,} ids from {args.ids_file}")

    if args.only in ("all", "drop"):
        print("\n=== DROP metric rows ===")
        drop_from_csvs(ids, args.dry_run)
        drop_from_embeddings(ids, args.dry_run)

    if args.dry_run:
        print("\ndry-run: stop before recolor/run")
        return

    if args.only in ("all", "run"):
        print("\n=== RECOLOR posters.csv ===")
        recolor(ids_df, dry_run=False)

        # write a temp ids file with title/year for any helper that needs it
        tmp = DATA / "qa" / "_reanalyze_ids_tmp.csv"
        tmp.parent.mkdir(parents=True, exist_ok=True)
        ids_df.to_csv(tmp, index=False)

        run([sys.executable, "-u", "multi_analyze.py"])
        run([sys.executable, "-u", "faces_v2.py"])
        run([sys.executable, "-u", "clip_embed.py"])
        run([sys.executable, "-u", "clip_medium.py"])
        run([sys.executable, "-u", "clip_census.py"])
        run([sys.executable, "-u", "clip_typography_axis.py"])
        if not args.skip_segmentation:
            run([sys.executable, "-u", "segmentation.py"])
        else:
            print("skip segmentation")

        if not args.skip_export:
            print("\n=== EXPORT site series / lookup / explorer ===")
            run([sys.executable, "-c", "from export_site_series import export; export()"])
            run([sys.executable, "build_lookup.py"])
            run(
                [
                    sys.executable,
                    "-c",
                    "from build_explorer import main; main()",
                ]
            )

    print("\nLISTO.")


if __name__ == "__main__":
    main()

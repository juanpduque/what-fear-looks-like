#!/usr/bin/env python3
"""Replace the year=9999 sentinel with recovered years across the data tables.

Every metric table carries its own year column, so a recovered date has to be
written to all of them or the decade aggregates disagree with posters.csv.
Rewrites are streamed with the csv module and only touch the year cell.

Usage:
  python3 apply_year_backfill.py --dry-run
  python3 apply_year_backfill.py
  python3 apply_year_backfill.py --backfill data/years_backfill_imdb.csv
"""
from __future__ import annotations

import argparse
import csv
from pathlib import Path

DATA = Path(__file__).resolve().parent / "data"
DEFAULT_BACKFILL = DATA / "years_backfill_imdb.csv"
UNDATED = 9999

TARGETS = [
    "posters.csv",
    "attributes.csv",
    "attributes_partial.csv",
    "census.csv",
    "faces_v2.csv",
    "faces_v2_partial.csv",
    "medium.csv",
    "segmentation.csv",
    "segmentation_partial.csv",
    "typography.csv",
]


def load_backfill(path: Path) -> dict[int, int]:
    out: dict[int, int] = {}
    with path.open(encoding="utf-8", errors="replace") as f:
        for r in csv.DictReader(f):
            try:
                out[int(r["id"])] = int(float(r["year"]))
            except (KeyError, TypeError, ValueError):
                continue
    return out


def patch(path: Path, years: dict[int, int], dry: bool) -> tuple[int, int]:
    """Return (rows_seen, rows_patched)."""
    with path.open(encoding="utf-8", errors="replace", newline="") as f:
        reader = csv.DictReader(f)
        fields = list(reader.fieldnames or [])
        if "id" not in fields or "year" not in fields:
            return 0, 0
        rows = list(reader)

    patched = 0
    for r in rows:
        try:
            pid, y = int(r["id"]), int(float(r["year"]))
        except (TypeError, ValueError):
            continue
        if y != UNDATED or pid not in years:
            continue
        r["year"] = str(years[pid])
        patched += 1

    if patched and not dry:
        tmp = path.with_suffix(".csv.tmp")
        with tmp.open("w", encoding="utf-8", newline="") as out:
            w = csv.DictWriter(out, fieldnames=fields, extrasaction="ignore")
            w.writeheader()
            w.writerows(rows)
        tmp.replace(path)
    return len(rows), patched


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--backfill", default=str(DEFAULT_BACKFILL))
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    years = load_backfill(Path(args.backfill))
    print(f"recovered years to apply: {len(years):,}")
    if not years:
        return

    total = 0
    for name in TARGETS:
        p = DATA / name
        if not p.exists():
            print(f"  {name:<28} (missing, skipped)")
            continue
        seen, patched = patch(p, years, args.dry_run)
        total += patched
        print(f"  {name:<28} rows={seen:>7,}  patched={patched:>4,}")

    # multi_analyze's resumable checkpoint, if a run left one behind
    for extra in DATA.glob("*checkpoint*.csv"):
        seen, patched = patch(extra, years, args.dry_run)
        if seen:
            print(f"  {extra.name:<28} rows={seen:>7,}  patched={patched:>4,}")

    print(f"\n{'DRY RUN — nothing written' if args.dry_run else 'done'}: "
          f"{total:,} cells patched")


if __name__ == "__main__":
    main()

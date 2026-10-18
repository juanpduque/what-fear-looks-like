#!/usr/bin/env python3
"""Resolve the 72 duplicate-TMDB-entry groups found by find_duplicate_tmdb_entries.py,
after removing the 38 ids confirmed dead (404) against the live TMDB API.

Categorizes each surviving group:
  - phantom: only 1 live id left -> not a real duplicate, the "match" was against
    a dead/stale id. Nothing to fix.
  - clean_swap: exactly 2 live ids, exactly 1 has pipeline metrics -> swap that
    one's poster_path to the live sibling's, flag for metric recompute.
  - both_analyzed: 2+ live ids, more than 1 already has pipeline metrics -> a
    real duplicate corpus entry (same film counted twice+), needs a human call
    on which id to keep as canonical.

  python3 resolve_duplicate_tmdb_entries.py

Writes: data/qa/duplicate_tmdb_resolution.csv
"""

from __future__ import annotations

import csv
from pathlib import Path

DATA = Path(__file__).parent / "data"

DEAD_IDS = {
    "283548",
    "299768",
    "368698",
    "461059",
    "467151",
    "477982",
    "538208",
    "629976",
    "633365",
    "636893",
    "664681",
    "672114",
    "675522",
    "683803",
    "762598",
    "804304",
    "837759",
    "887876",
    "890574",
    "921442",
    "926603",
    "928313",
    "938850",
    "954406",
    "959595",
    "960208",
    "961601",
    "967672",
    "970056",
    "978599",
    "997546",
    "1005337",
    "1012840",
    "1012847",
    "1012859",
    "1012953",
    "1015721",
    "1027665",
}


def main():
    with (DATA / "qa" / "duplicate_tmdb_entries.csv").open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    groups: dict[str, list[dict]] = {}
    for row in rows:
        groups.setdefault(row["group_ids"], []).append(row)

    out_rows = []
    counts = {"phantom": 0, "clean_swap": 0, "both_analyzed": 0}
    for _gid, items in groups.items():
        live = [r for r in items if r["id"] not in DEAD_IDS]
        analyzed_live = [r for r in live if r["has_pipeline_metrics"] == "1"]

        if len(live) <= 1:
            category = "phantom"
        elif len(analyzed_live) <= 1:
            category = "clean_swap"
        else:
            category = "both_analyzed"
        counts[category] += 1

        for r in items:
            out_rows.append(
                {
                    "group_key_title": r["group_key_title"],
                    "group_key_year": r["group_key_year"],
                    "id": r["id"],
                    "is_dead": int(r["id"] in DEAD_IDS),
                    "poster_path": r["poster_path"],
                    "has_pipeline_metrics": r["has_pipeline_metrics"],
                    "category": category,
                }
            )

    out_path = DATA / "qa" / "duplicate_tmdb_resolution.csv"
    with out_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(out_rows[0].keys()))
        w.writeheader()
        w.writerows(out_rows)

    print(f"Escrito {out_path}")
    print(f"grupos totales: {len(groups)}")
    for k, v in counts.items():
        print(f"  {k}: {v}")


if __name__ == "__main__":
    main()

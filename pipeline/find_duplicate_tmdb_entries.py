#!/usr/bin/env python3
"""Find TMDB duplicate-entry pairs: same title+year+overview, different id,
different poster_path -- the "Omegle" pattern (id 1009049 vs 1743173, a
cropped poster vs the full one under a second TMDB listing of the same film).

Cross-checks against master_dataset.csv to flag which id in each pair already
has the pipeline's metrics computed (the one to KEEP and swap the poster on)
vs which is just a raw, unanalyzed candidate (the one to treat as the
duplicate / poster-image donor).

  python3 find_duplicate_tmdb_entries.py

Writes: data/qa/duplicate_tmdb_entries.csv
"""

from __future__ import annotations

import csv
from collections import defaultdict
from pathlib import Path

DATA = Path(__file__).parent / "data"

SOURCES = [
    ("horror_movies.csv", "overview"),
    ("community/tmdb_horror_ids.csv", "overview_snip"),
    ("community_scifi/tmdb_scifi_ids.csv", "overview_snip"),
    ("community_mystery/tmdb_mystery_ids.csv", "overview_snip"),
    ("community_thriller/tmdb_thriller_ids.csv", "overview_snip"),
]


def norm(s: str) -> str:
    return (s or "").strip().lower()[:60]


def main():
    records: dict[str, dict] = {}
    for fname, ov_col in SOURCES:
        path = DATA / fname
        if not path.exists():
            continue
        with path.open(newline="", encoding="utf-8", errors="replace") as f:
            for row in csv.DictReader(f):
                i = row["id"]
                if i in records and records[i].get("overview"):
                    continue
                records[i] = {
                    "title": row.get("title", ""),
                    "year": row.get("year", "") or (row.get("release_date", "") or "")[:4],
                    "overview": row.get(ov_col, ""),
                    "poster_path": row.get("poster_path", ""),
                    "vote_count": row.get("vote_count", ""),
                }

    has_metrics: set[str] = set()
    master_path = DATA / "master_dataset.csv"
    if master_path.exists():
        with master_path.open(newline="", encoding="utf-8", errors="replace") as f:
            for row in csv.DictReader(f):
                if row.get("iqa_clipiqa") or row.get("color_brightness"):
                    has_metrics.add(row["id"])

    groups: dict[tuple, list[tuple[str, dict]]] = defaultdict(list)
    for i, rec in records.items():
        key = (norm(rec["title"]), rec["year"], norm(rec["overview"]))
        if not key[0] or not key[1] or not key[2]:
            continue
        groups[key].append((i, rec))

    rows_out = []
    for key, items in groups.items():
        posters = {rec["poster_path"].strip() for i, rec in items if rec["poster_path"].strip()}
        if len(posters) < 2:
            continue
        analyzed = [i for i, rec in items if i in has_metrics]
        for i, rec in items:
            rows_out.append(
                {
                    "group_key_title": key[0],
                    "group_key_year": key[1],
                    "id": i,
                    "poster_path": rec["poster_path"],
                    "vote_count": rec["vote_count"],
                    "has_pipeline_metrics": int(i in has_metrics),
                    "group_ids": "|".join(x for x, _ in items),
                    "group_analyzed_ids": "|".join(analyzed),
                    "n_analyzed_in_group": len(analyzed),
                }
            )

    out_path = DATA / "qa" / "duplicate_tmdb_entries.csv"
    with out_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows_out[0].keys()))
        w.writeheader()
        w.writerows(rows_out)

    n_groups = len({r["group_ids"] for r in rows_out})
    clean_swap = sum(1 for r in rows_out if r["n_analyzed_in_group"] == 1)
    print(f"Escrito {out_path}")
    print(f"grupos duplicados: {n_groups}, ids afectados: {len(rows_out)}")
    print(
        f"casos 'limpios' (exactamente 1 de los 2 ya tiene metricas -> swap directo de poster): {clean_swap}"
    )


if __name__ == "__main__":
    main()

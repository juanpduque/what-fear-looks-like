#!/usr/bin/env python3
"""Apply OCR-scored multi-poster variant swaps (propose=1).

Copies best variant → data/posters/{id}.jpg, keeps a backup of the previous
primary, updates poster_paths_backfill.csv + horror_movies.poster_path when
present, and realigns multi_poster_catalog is_primary.

  python3 apply_multi_poster_ocr_swaps.py --dry-run
  python3 apply_multi_poster_ocr_swaps.py
"""
from __future__ import annotations

import argparse
import csv
import shutil
from pathlib import Path

import pandas as pd

DATA = Path(__file__).resolve().parent / "data"
POSTERS = DATA / "posters"
BACKUP = DATA / "posters_pre_ocr_variant_swap"
SWAPS = DATA / "qa" / "multi_poster_variant_ocr_swaps.csv"
APPLIED = DATA / "qa" / "multi_poster_variant_ocr_swaps_applied.csv"
IDS_OUT = DATA / "qa" / "multi_poster_variant_ocr_swaps_reanalyze_ids.csv"
BACKFILL = DATA / "poster_paths_backfill.csv"
HORROR = DATA / "horror_movies.csv"
CATALOG = DATA / "multi_poster_catalog.csv"
CANONICAL = DATA / "multi_poster_canonical.csv"


def tmdb_path_from_stem(stem: str) -> str:
    s = (stem or "").strip()
    if not s:
        return ""
    if s.endswith(".jpg"):
        s = s[: -len(".jpg")]
    # primary baseline stems look like "7180.jpg" stored as stem in scores —
    # real variants are TMDB hashes without extension.
    if s.isdigit():
        return ""
    return f"/{s}.jpg"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--swaps", default=str(SWAPS))
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    rows = [
        r
        for r in csv.DictReader(Path(args.swaps).open(encoding="utf-8"))
        if str(r.get("propose") or "") == "1"
    ]
    print(f"proposed swaps: {len(rows)}")

    applied: list[dict] = []
    path_map: dict[int, str] = {}
    meta: dict[int, tuple[str, str]] = {}

    for r in rows:
        pid = int(r["id"])
        src = DATA / r["best_file_path"]
        dest = POSTERS / f"{pid}.jpg"
        tmdb_path = tmdb_path_from_stem(r.get("best_stem") or "")
        if not tmdb_path:
            # recover from file name
            tmdb_path = tmdb_path_from_stem(src.stem)
        status = "ok"
        err = ""
        if not src.exists():
            status = "missing_src"
            err = str(src)
        elif not tmdb_path:
            status = "bad_path"
            err = f"stem={r.get('best_stem')}"
        applied.append(
            {
                **{k: r.get(k, "") for k in r},
                "tmdb_poster_path": tmdb_path,
                "src": str(src.relative_to(DATA)) if src.exists() else str(src),
                "dest": f"posters/{pid}.jpg",
                "status": status,
                "error": err,
            }
        )
        if status == "ok":
            path_map[pid] = tmdb_path
            meta[pid] = (r.get("title") or "", r.get("year") or "")

    ok_n = sum(1 for a in applied if a["status"] == "ok")
    print(f"applyable: {ok_n}  skipped: {len(applied) - ok_n}")
    if args.dry_run:
        print("dry-run — no files written")
        for a in applied[:8]:
            print(f"  {a['id']} {a['status']} {a['src']} → {a['dest']} path={a['tmdb_poster_path']}")
        return 0

    BACKUP.mkdir(parents=True, exist_ok=True)
    copied = 0
    for a in applied:
        if a["status"] != "ok":
            continue
        pid = int(a["id"])
        src = DATA / a["src"]
        dest = POSTERS / f"{pid}.jpg"
        if dest.exists() and dest.stat().st_size > 500:
            bak = BACKUP / f"{pid}.jpg"
            if not bak.exists():
                shutil.copy2(dest, bak)
        shutil.copy2(src, dest)
        copied += 1
    print(f"copied {copied} posters → {POSTERS}/ (backups → {BACKUP.name}/)")

    # backfill upsert
    bf: dict[int, dict] = {}
    if BACKFILL.exists():
        for r in csv.DictReader(BACKFILL.open(encoding="utf-8")):
            try:
                bf[int(r["id"])] = r
            except Exception:
                pass
    for pid, path in path_map.items():
        title, year = meta.get(pid, ("", ""))
        prev = bf.get(pid, {})
        bf[pid] = {
            "id": pid,
            "poster_path": path,
            "title": prev.get("title") or title,
            "year": prev.get("year") or year,
        }
    fields = ["id", "poster_path", "title", "year"]
    with BACKFILL.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for pid in sorted(bf):
            w.writerow({k: bf[pid].get(k, "") for k in fields})
    print(f"poster_paths_backfill.csv upserted {len(path_map)}")

    if HORROR.exists():
        hm = pd.read_csv(HORROR, low_memory=False)
        hm["id"] = hm["id"].astype(int)
        mask = hm["id"].isin(path_map)
        n = int(mask.sum())
        hm.loc[mask, "poster_path"] = hm.loc[mask, "id"].map(path_map)
        hm.to_csv(HORROR, index=False)
        print(f"horror_movies.csv updated poster_path for {n}")

    if CATALOG.exists() and path_map:
        cat = pd.read_csv(CATALOG)
        cat["id"] = cat["id"].astype(int)
        touched = cat["id"].isin(path_map)
        cat.loc[touched, "is_primary"] = 0
        for pid, path in path_map.items():
            m = (cat["id"] == pid) & (cat["file_path"] == path)
            if m.any():
                cat.loc[m, "is_primary"] = 1
            else:
                title, year = meta.get(pid, ("", ""))
                cat = pd.concat(
                    [
                        cat,
                        pd.DataFrame(
                            [
                                {
                                    "id": pid,
                                    "title": title,
                                    "year": year,
                                    "file_path": path,
                                    "iso_639_1": "",
                                    "vote_average": 0,
                                    "vote_count": 0,
                                    "width": 0,
                                    "height": 0,
                                    "is_primary": 1,
                                }
                            ]
                        ),
                    ],
                    ignore_index=True,
                )
        cat.to_csv(CATALOG, index=False)
        print(f"multi_poster_catalog.csv realigned is_primary for {len(path_map)}")

    if CANONICAL.exists() and path_map:
        can = pd.read_csv(CANONICAL)
        can["id"] = can["id"].astype(int)
        mask = can["id"].isin(path_map)
        can.loc[mask, "canonical_path"] = can.loc[mask, "id"].map(path_map)
        can.loc[mask, "changed_from_primary"] = 0
        can.to_csv(CANONICAL, index=False)
        print(f"multi_poster_canonical.csv updated {int(mask.sum())}")

    APPLIED.parent.mkdir(parents=True, exist_ok=True)
    with APPLIED.open("w", newline="", encoding="utf-8") as f:
        fields_out = list(applied[0].keys()) if applied else ["id", "status"]
        w = csv.DictWriter(f, fieldnames=fields_out)
        w.writeheader()
        for a in sorted(applied, key=lambda x: int(x["id"])):
            w.writerow(a)

    with IDS_OUT.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["id"])
        w.writeheader()
        for pid in sorted(path_map):
            w.writerow({"id": pid})

    print(f"wrote {APPLIED}")
    print(f"wrote {IDS_OUT} ({len(path_map)} ids)")
    print("next: python3 reanalyze_poster_ids.py --ids-file data/qa/multi_poster_variant_ocr_swaps_reanalyze_ids.csv")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

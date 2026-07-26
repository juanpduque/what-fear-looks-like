#!/usr/bin/env python3
"""Ingest EN Horror titles with poster that are not yet in the corpus.

Filter criteria (analysis universe):
  - TMDB genre Horror
  - original_language = en
  - has poster_path
  - not Animation / Music

Uses a candidates CSV (default: gap_en_poster_candidates.csv).

  source ~/.zshrc && python3 pull_en_poster_gap.py
  source ~/.zshrc && python3 pull_en_poster_gap.py \\
      --candidates data/gap_en_remaining_with_poster.csv --tag en_remaining
"""
from __future__ import annotations

import argparse
import csv
import os
import time
from pathlib import Path

import pandas as pd
import pull_2023_2025 as base

DATA = Path(__file__).resolve().parent / "data"
BACKFILL = DATA / "poster_paths_backfill.csv"

ANIMATION, MUSIC = 16, 104


def _year_from_row(r: dict) -> str:
    rd = (r.get("release_date") or "").strip()
    if len(rd) >= 4 and rd[:4].isdigit():
        return rd[:4]
    return ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--api-key", default=os.environ.get("TMDB_API_KEY"))
    ap.add_argument("--candidates", default="data/gap_en_poster_candidates.csv",
                    help="CSV with at least id + poster_path (+ title/year optional)")
    ap.add_argument("--tag", default="en_poster_gap",
                    help="suffix for sidecar/progress/ids outputs")
    ap.add_argument("--skip-posters", action="store_true")
    ap.add_argument("--skip-details", action="store_true",
                    help="Use candidate rows as-is (faster); still filters Anim/Music on detail if fetched")
    ap.add_argument("--workers", type=int, default=24)
    ap.add_argument("--limit", type=int, default=0, help="optional cap for testing")
    args = ap.parse_args()
    if not args.api_key:
        raise SystemExit("Need TMDB_API_KEY or --api-key")

    candidates = Path(args.candidates)
    if not candidates.is_absolute():
        candidates = (Path(__file__).resolve().parent / candidates).resolve()
    if not candidates.exists():
        raise SystemExit(f"Missing {candidates} — run the discover gap script first")

    sidecar = DATA / f"horror_refresh_{args.tag}.csv"
    progress = DATA / f"horror_refresh_{args.tag}_progress.csv"
    ids_out = DATA / f"new_{args.tag}_ids.csv"
    ids_undated = DATA / f"new_{args.tag}_undated_ids.csv"

    base.SIDECAR = sidecar
    base.PROGRESS = progress
    base.ANIMATION, base.MUSIC = ANIMATION, MUSIC

    cand = pd.read_csv(candidates)
    cand["id"] = cand["id"].astype(int)
    if args.limit:
        cand = cand.head(args.limit).copy()
    print(f"candidates: {len(cand):,}")

    # Skip already analyzed
    analyzed = set()
    apath = DATA / "attributes.csv"
    if apath.exists():
        analyzed = set(pd.read_csv(apath, usecols=["id"])["id"].astype(int))
    cand = cand[~cand["id"].isin(analyzed)].copy()
    print(f"not in attributes yet: {len(cand):,}")

    session = __import__("requests").Session()
    done = base.load_progress()
    todo_ids = [int(x) for x in cand["id"] if int(x) not in done]

    if args.skip_details:
        # Seed progress from candidates
        by = cand.set_index("id").to_dict("index")
        for pid in cand["id"].astype(int):
            if pid in done:
                continue
            row = by[pid]
            done[pid] = {
                "id": pid,
                "imdb_id": "",
                "original_title": row.get("title") or "",
                "title": row.get("title") or "",
                "original_language": row.get("original_language") or "en",
                "overview": "",
                "tagline": "",
                "release_date": f"{int(row['year'])}-01-01" if pd.notna(row.get("year")) else "",
                "poster_path": row.get("poster_path") or "",
                "popularity": 0,
                "vote_count": 0,
                "vote_average": 0,
                "budget": 0,
                "revenue": 0,
                "runtime": 0,
                "status": "",
                "adult": False,
                "backdrop_path": "",
                "genre_names": "Horror",
                "collection": "",
                "collection_name": "",
            }
        base.save_progress(done)
        print(f"seeded progress from candidates: {len(done):,}")
    else:
        print(f"detail fetch todo: {len(todo_ids):,} (already {len(done):,})")
        t0 = time.time()
        by_cand = cand.set_index("id")
        for i, pid in enumerate(todo_ids, 1):
            row = base.fetch_movie(session, args.api_key, pid)
            if row is None:
                c = by_cand.loc[pid]
                row = {
                    "id": pid,
                    "imdb_id": "",
                    "original_title": c.get("title") or "",
                    "title": c.get("title") or "",
                    "original_language": c.get("original_language") or "en",
                    "overview": "",
                    "tagline": "",
                    "release_date": f"{int(c['year'])}-01-01" if pd.notna(c.get("year")) else "",
                    "poster_path": c.get("poster_path") or "",
                    "popularity": 0,
                    "vote_count": 0,
                    "vote_average": 0,
                    "budget": 0,
                    "revenue": 0,
                    "runtime": 0,
                    "status": "",
                    "adult": False,
                    "backdrop_path": "",
                    "genre_names": "Horror",
                    "collection": "",
                    "collection_name": "",
                }
            clean = {k: row.get(k, "") for k in base.HM_FIELDS}
            done[pid] = clean
            if i % 100 == 0 or i == len(todo_ids):
                base.save_progress(done)
                rate = i / max(time.time() - t0, 1e-6)
                print(f"  details {i}/{len(todo_ids)} ({rate:.1f}/s)", flush=True)
            time.sleep(0.035)
        base.save_progress(done)

    all_rows = [done[pid] for pid in sorted(done)]
    with sidecar.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=base.HM_FIELDS)
        w.writeheader()
        for r in all_rows:
            w.writerow({k: r.get(k, "") for k in base.HM_FIELDS})
    print(f"wrote {sidecar.name} ({len(all_rows):,})")

    anim, music = [], []
    for r in all_rows:
        names = {x.strip() for x in (r.get("genre_names") or "").split(",") if x.strip()}
        if "Animation" in names:
            anim.append(r)
        if "Music" in names:
            music.append(r)
    base.append_exclusions(anim, "animation")
    base.append_exclusions(music, "music")

    analyzable = []
    for r in all_rows:
        names = {x.strip() for x in (r.get("genre_names") or "").split(",") if x.strip()}
        if "Animation" in names or "Music" in names:
            continue
        if (r.get("original_language") or "") not in ("en", ""):
            continue
        if not str(r.get("poster_path") or "").startswith("/"):
            continue
        analyzable.append(r)
    print(f"analyzable: {len(analyzable):,}")

    # Paths backfill for explorer
    bf_rows = []
    if BACKFILL.exists():
        bf_rows = list(csv.DictReader(BACKFILL.open()))
    existing_bf = {int(r["id"]) for r in bf_rows if r.get("id")}
    add_bf = []
    for r in analyzable:
        pid = int(r["id"])
        if pid in existing_bf:
            continue
        add_bf.append({
            "id": pid,
            "poster_path": r.get("poster_path") or "",
            "title": r.get("title") or "",
            "year": (r.get("release_date") or "")[:4],
        })
    if add_bf:
        fields = ["id", "poster_path", "title", "year"]
        # normalize old rows
        with BACKFILL.open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=fields)
            w.writeheader()
            for r in bf_rows:
                w.writerow({k: r.get(k, "") for k in fields})
            for r in add_bf:
                w.writerow(r)
        print(f"poster_paths_backfill.csv: +{len(add_bf)}")

    if not args.skip_posters:
        ok, fail = base.download_posters(analyzable, workers=args.workers)
        print(f"posters downloaded: ok={ok} fail={fail}")

    new_vs, undated_vs = [], []
    for r in analyzable:
        pid = int(r["id"])
        if pid in analyzed:
            continue
        dest = DATA / "posters" / f"{pid}.jpg"
        if not (dest.exists() and dest.stat().st_size > 2000):
            continue
        y = _year_from_row(r)
        row = {"id": pid, "title": r.get("title") or "", "year": y}
        if y:
            new_vs.append({**row, "year": int(y)})
        else:
            undated_vs.append(row)

    with ids_out.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["id", "title", "year"])
        w.writeheader()
        for r in new_vs:
            w.writerow(r)

    with ids_undated.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["id", "title", "year"])
        w.writeheader()
        for r in undated_vs:
            w.writerow(r)

    print("\n=== EN POSTER GAP SUMMARY ===")
    print(f"analyzable rows: {len(analyzable):,}")
    print(f"new with local poster + year: {len(new_vs):,} → {ids_out.name}")
    print(f"new with local poster, undated: {len(undated_vs):,} → {ids_undated.name}")
    if new_vs:
        ys = sorted(r["year"] for r in new_vs)
        print(f"year range: {ys[0]}–{ys[-1]}")


if __name__ == "__main__":
    main()

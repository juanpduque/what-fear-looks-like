#!/usr/bin/env python3
"""Pull TMDB English horror films for 2026 into the local corpus.

Same filters as pull_2023_2025.py: EN + Horror, exclude Animation/Music
from the analyzable set, merge into horror_movies.csv, download posters.

  source ~/.zshrc && python3 pull_2026.py
"""
from __future__ import annotations

import argparse
import csv
import os
import time
from pathlib import Path

import pull_2023_2025 as base

DATA = Path(__file__).resolve().parent / "data"
SIDECAR = DATA / "horror_refresh_2026.csv"
PROGRESS = DATA / "horror_refresh_2026_progress.csv"
IDS_OUT = DATA / "new_2026_ids.csv"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--api-key", default=os.environ.get("TMDB_API_KEY"))
    ap.add_argument("--skip-posters", action="store_true")
    ap.add_argument("--workers", type=int, default=16)
    args = ap.parse_args()
    if not args.api_key:
        raise SystemExit("Need TMDB_API_KEY or --api-key")

    # Point the shared helpers at 2026 sidecars
    base.SIDECAR = SIDECAR
    base.PROGRESS = PROGRESS

    session = __import__("requests").Session()

    discovered = base.discover_year(session, args.api_key, 2026)
    print(f"discover 2026: {len(discovered):,}")
    by_id = {m["id"]: m for m in discovered}

    done = base.load_progress()
    todo_ids = [pid for pid in sorted(by_id) if pid not in done]
    print(f"detail fetch todo: {len(todo_ids):,} (already {len(done):,})")
    t0 = time.time()
    for i, pid in enumerate(todo_ids, 1):
        row = base.fetch_movie(session, args.api_key, pid)
        if row is None:
            m = by_id[pid]
            gids = m.get("genre_ids") or []
            names = []
            if base.ANIMATION in gids:
                names.append("Animation")
            if base.MUSIC in gids:
                names.append("Music")
            if base.HORROR in gids:
                names.append("Horror")
            row = {
                "id": pid,
                "imdb_id": "",
                "original_title": m.get("original_title") or m.get("title") or "",
                "title": m.get("title") or "",
                "original_language": m.get("original_language") or "en",
                "overview": m.get("overview") or "",
                "tagline": "",
                "release_date": m.get("release_date") or "",
                "poster_path": m.get("poster_path") or "",
                "popularity": m.get("popularity") or 0,
                "vote_count": m.get("vote_count") or 0,
                "vote_average": m.get("vote_average") or 0,
                "budget": 0,
                "revenue": 0,
                "runtime": 0,
                "status": "",
                "adult": bool(m.get("adult")),
                "backdrop_path": m.get("backdrop_path") or "",
                "genre_names": ", ".join(names),
                "collection": "",
                "collection_name": "",
                "_genre_ids": gids,
            }
        clean = {k: row.get(k, "") for k in base.HM_FIELDS}
        done[pid] = clean
        if i % 50 == 0 or i == len(todo_ids):
            base.save_progress(done)
            rate = i / max(time.time() - t0, 1e-6)
            print(f"  details {i}/{len(todo_ids)} ({rate:.1f}/s)", flush=True)
        time.sleep(0.04)
    base.save_progress(done)

    all_rows = [done[pid] for pid in sorted(done)]
    with SIDECAR.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=base.HM_FIELDS)
        w.writeheader()
        for r in all_rows:
            w.writerow({k: r.get(k, "") for k in base.HM_FIELDS})
    print(f"wrote {SIDECAR} ({len(all_rows):,})")

    anim, music = [], []
    for r in all_rows:
        names = {x.strip() for x in (r.get("genre_names") or "").split(",") if x.strip()}
        if "Animation" in names:
            anim.append(r)
        if "Music" in names:
            music.append(r)
    base.append_exclusions(anim, "animation")
    base.append_exclusions(music, "music")
    try:
        base.merge_horror_movies(all_rows)
    except Exception as e:
        print(f"WARN: skip horror_movies.csv merge ({type(e).__name__}: {e})")
        print("  continuing with sidecar + posters only")

    analyzable = []
    for r in all_rows:
        names = {x.strip() for x in (r.get("genre_names") or "").split(",") if x.strip()}
        if "Animation" in names or "Music" in names:
            continue
        if not str(r.get("poster_path") or "").startswith("/"):
            continue
        analyzable.append(r)
    print(f"analyzable 2026 (en+poster+no Anim/Music): {len(analyzable):,}")

    if not args.skip_posters:
        ok, fail = base.download_posters(analyzable, workers=args.workers)
        print(f"posters downloaded: ok={ok} fail={fail}")

    # ids list for metrics chain
    analyzed = set()
    ap = DATA / "attributes.csv"
    if ap.exists():
        analyzed = {int(r["id"]) for r in csv.DictReader(ap.open())}
    new_vs = [r for r in analyzable if int(r["id"]) not in analyzed]
    with IDS_OUT.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["id", "title", "year"])
        w.writeheader()
        for r in new_vs:
            y = (r.get("release_date") or "2026")[:4] or "2026"
            w.writerow({"id": int(r["id"]), "title": r.get("title") or "", "year": int(y)})

    print("\n=== PULL 2026 SUMMARY ===")
    print(f"EN horror 2026 pulled: {len(all_rows):,}")
    print(f"with poster, no Anim/Music: {len(analyzable):,}")
    print(f"not yet in attributes.csv: {len(new_vs):,} → {IDS_OUT.name}")


if __name__ == "__main__":
    main()

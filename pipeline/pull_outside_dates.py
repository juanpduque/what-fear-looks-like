#!/usr/bin/env python3
"""Pull TMDB horror films outside 1920–2026 (pre-1920 + 2027+) into the corpus.

No date-window exclusion: discover pre-1920 and 2027+, keep EN (or empty lang)
with usable poster, exclude Animation/Music from the analyzable set.

  source ~/.zshrc && python3 pull_outside_dates.py
  python3 pull_outside_dates.py --api-key YOUR_KEY --skip-posters
"""
from __future__ import annotations

import argparse
import csv
import os
import time
from pathlib import Path

import pull_2023_2025 as base

DATA = Path(__file__).resolve().parent / "data"
SIDECAR = DATA / "horror_refresh_outside_dates.csv"
PROGRESS = DATA / "horror_refresh_outside_dates_progress.csv"
IDS_OUT = DATA / "new_outside_dates_ids.csv"
CANDIDATES = DATA / "gap_outside_dates_candidates.csv"

# TMDB genre ids (Music is 104, not 10402)
ANIMATION, MUSIC, HORROR = 16, 104, 27


def discover_range(
    session,
    api_key: str,
    *,
    gte: str | None = None,
    lte: str | None = None,
    lang: str | None = "en",
) -> list[dict]:
    rows, page, total_pages = [], 1, 1
    while page <= min(total_pages, 500):
        params = {
            "api_key": api_key,
            "with_genres": HORROR,
            "sort_by": "primary_release_date.asc",
            "include_adult": "false",
            "page": page,
        }
        if lang:
            params["with_original_language"] = lang
        if gte:
            params["primary_release_date.gte"] = gte
        if lte:
            params["primary_release_date.lte"] = lte
        r = session.get(base.DISCOVER, params=params, headers=base.HEADERS, timeout=30)
        if r.status_code == 429:
            time.sleep(3)
            continue
        r.raise_for_status()
        j = r.json()
        total_pages = j.get("total_pages", 1)
        rows.extend(j.get("results") or [])
        page += 1
        time.sleep(0.03)
    return rows


def stub_from_discover(m: dict) -> dict:
    gids = m.get("genre_ids") or []
    names = []
    if ANIMATION in gids:
        names.append("Animation")
    if MUSIC in gids:
        names.append("Music")
    if HORROR in gids:
        names.append("Horror")
    return {
        "id": int(m["id"]),
        "imdb_id": "",
        "original_title": m.get("original_title") or m.get("title") or "",
        "title": m.get("title") or "",
        "original_language": m.get("original_language") or "",
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


def lang_ok(lang: str) -> bool:
    return lang in ("en", "")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--api-key", default=os.environ.get("TMDB_API_KEY"))
    ap.add_argument("--skip-posters", action="store_true")
    ap.add_argument("--workers", type=int, default=16)
    ap.add_argument(
        "--from-candidates",
        action="store_true",
        help="Seed discover ids from gap_outside_dates_candidates.csv",
    )
    args = ap.parse_args()
    if not args.api_key:
        raise SystemExit("Need TMDB_API_KEY or --api-key")

    base.SIDECAR = SIDECAR
    base.PROGRESS = PROGRESS
    base.ANIMATION, base.MUSIC, base.HORROR = ANIMATION, MUSIC, HORROR

    session = __import__("requests").Session()
    by_id: dict[int, dict] = {}

    print("discover pre-1920 (all langs)…")
    for m in discover_range(session, args.api_key, lte="1919-12-31", lang=None):
        by_id[int(m["id"])] = m
    print(f"  → {len(by_id):,}")
    print("discover pre-1920 (en)…")
    for m in discover_range(session, args.api_key, lte="1919-12-31", lang="en"):
        by_id[int(m["id"])] = m
    print(f"  → {len(by_id):,}")
    print("discover 2027+ (en)…")
    for m in discover_range(session, args.api_key, gte="2027-01-01", lang="en"):
        by_id[int(m["id"])] = m
    print(f"  → {len(by_id):,}")
    print("discover 2027+ (all langs)…")
    for m in discover_range(session, args.api_key, gte="2027-01-01", lang=None):
        by_id.setdefault(int(m["id"]), m)
    print(f"  unique discover: {len(by_id):,}")

    if args.from_candidates and CANDIDATES.exists():
        import pandas as pd
        extra = pd.read_csv(CANDIDATES)
        for _, row in extra.iterrows():
            pid = int(row["id"])
            if pid not in by_id:
                by_id[pid] = {
                    "id": pid,
                    "title": row.get("title") or "",
                    "original_title": row.get("title") or "",
                    "original_language": row.get("original_language") or "en",
                    "release_date": f"{int(row['year'])}-01-01" if pd.notna(row.get("year")) else "",
                    "poster_path": row.get("poster_path") or "",
                    "genre_ids": [
                        int(x) for x in str(row.get("genre_ids") or "").split(",") if x.strip().isdigit()
                    ],
                    "adult": False,
                }
        print(f"  after candidates seed: {len(by_id):,}")

    # Keep EN or empty language only for detail fetch (silent-era friendly)
    seed_ids = []
    for pid, m in by_id.items():
        lang = m.get("original_language") or ""
        if lang_ok(lang):
            seed_ids.append(pid)
    seed_ids = sorted(set(seed_ids))
    print(f"EN/empty-lang ids to detail: {len(seed_ids):,}")

    done = base.load_progress()
    todo_ids = [pid for pid in seed_ids if pid not in done]
    print(f"detail fetch todo: {len(todo_ids):,} (already {len(done):,})")
    t0 = time.time()
    for i, pid in enumerate(todo_ids, 1):
        row = base.fetch_movie(session, args.api_key, pid)
        if row is None:
            row = stub_from_discover(by_id[pid])
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

    analyzable = []
    for r in all_rows:
        names = {x.strip() for x in (r.get("genre_names") or "").split(",") if x.strip()}
        if "Animation" in names or "Music" in names:
            continue
        if not str(r.get("poster_path") or "").startswith("/"):
            continue
        if not lang_ok(r.get("original_language") or ""):
            continue
        analyzable.append(r)
    print(f"analyzable outside-dates (en/empty+poster+no Anim/Music): {len(analyzable):,}")

    if not args.skip_posters:
        ok, fail = base.download_posters(analyzable, workers=args.workers)
        print(f"posters downloaded: ok={ok} fail={fail}")

    analyzed = set()
    ap = DATA / "attributes.csv"
    if ap.exists():
        analyzed = {int(r["id"]) for r in csv.DictReader(ap.open())}
    new_vs = [r for r in analyzable if int(r["id"]) not in analyzed]
    # Only keep those with a local poster file
    with_file = []
    for r in new_vs:
        dest = DATA / "posters" / f"{int(r['id'])}.jpg"
        if dest.exists() and dest.stat().st_size > 2000:
            with_file.append(r)
        elif args.skip_posters:
            with_file.append(r)

    with IDS_OUT.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["id", "title", "year"])
        w.writeheader()
        for r in with_file:
            y = (r.get("release_date") or "")[:4]
            if not y.isdigit():
                continue
            w.writerow({"id": int(r["id"]), "title": r.get("title") or "", "year": int(y)})

    print("\n=== PULL OUTSIDE DATES SUMMARY ===")
    print(f"sidecar rows: {len(all_rows):,}")
    print(f"analyzable: {len(analyzable):,}")
    print(f"new vs attributes with poster: {len(with_file):,} → {IDS_OUT.name}")
    if with_file:
        years = sorted(int((r.get("release_date") or "0")[:4]) for r in with_file if (r.get("release_date") or "")[:4].isdigit())
        print(f"year range new: {years[0]}–{years[-1]}")


if __name__ == "__main__":
    main()

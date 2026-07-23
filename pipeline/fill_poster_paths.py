#!/usr/bin/env python3
"""Fetch missing TMDB metadata for corpus IDs absent from horror_movies.csv.

~629 early titles (mostly 1920–1949) were analyzed but never persisted with
poster_path / runtime / etc. This pulls /movie/{id} for each and writes:

  data/poster_paths_backfill.csv   (sidecar; safe to commit)
  data/horror_movies.csv           (local merge; gitignored)
  site/data/explorer.js            (rebuild)

  TMDB_API_KEY=... python3 fill_poster_paths.py
  python3 fill_poster_paths.py --api-key YOUR_KEY
"""
from __future__ import annotations

import argparse
import csv
import os
import time
from pathlib import Path

import pandas as pd
import requests

DATA = Path(__file__).resolve().parent / "data"
OUT = DATA / "poster_paths_backfill.csv"
HM = DATA / "horror_movies.csv"
POSTERS = DATA / "posters.csv"

FIELDS = [
    "id", "original_title", "title", "original_language", "overview", "tagline",
    "release_date", "poster_path", "popularity", "vote_count", "vote_average",
    "budget", "revenue", "runtime", "status", "adult", "backdrop_path",
    "genre_names", "collection", "collection_name",
]


def missing_ids() -> list[tuple[int, str, int]]:
    posts = {
        int(r["id"]): (r["title"], int(float(r["year"])))
        for r in csv.DictReader(POSTERS.open())
    }
    have = set()
    if HM.exists():
        for r in csv.DictReader(HM.open()):
            have.add(int(r["id"]))
    if OUT.exists():
        for r in csv.DictReader(OUT.open()):
            # treat as done only if we already have a path
            if str(r.get("poster_path") or "").startswith("/"):
                have.add(int(r["id"]))
    return sorted(
        (pid, title, year)
        for pid, (title, year) in posts.items()
        if pid not in have
    )


def fetch_movie(session: requests.Session, api_key: str, pid: int) -> dict | None:
    url = f"https://api.themoviedb.org/3/movie/{pid}"
    for attempt in range(6):
        r = session.get(
            url,
            params={"api_key": api_key, "language": "en-US"},
            timeout=30,
        )
        if r.status_code == 429:
            time.sleep(2 + attempt * 2)
            continue
        if r.status_code == 404:
            return None
        r.raise_for_status()
        m = r.json()
        genres = m.get("genres") or []
        coll = m.get("belongs_to_collection") or {}
        return {
            "id": int(m["id"]),
            "original_title": m.get("original_title") or m.get("title") or "",
            "title": m.get("title") or "",
            "original_language": m.get("original_language") or "",
            "overview": m.get("overview") or "",
            "tagline": m.get("tagline") or "",
            "release_date": m.get("release_date") or "",
            "poster_path": m.get("poster_path") or "",
            "popularity": m.get("popularity") or 0,
            "vote_count": m.get("vote_count") or 0,
            "vote_average": m.get("vote_average") or 0,
            "budget": m.get("budget") or 0,
            "revenue": m.get("revenue") or 0,
            "runtime": m.get("runtime") or 0,
            "status": m.get("status") or "",
            "adult": bool(m.get("adult")),
            "backdrop_path": m.get("backdrop_path") or "",
            "genre_names": ", ".join(g.get("name", "") for g in genres if g.get("name")),
            "collection": coll.get("id") or "",
            "collection_name": coll.get("name") or "",
        }
    return None


def write_sidecar(rows_by_id: dict[int, dict]):
    with OUT.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        for pid in sorted(rows_by_id):
            w.writerow(rows_by_id[pid])


def merge_into_horror_movies(rows: list[dict]):
    if not rows:
        return
    if HM.exists():
        base = pd.read_csv(HM)
    else:
        base = pd.DataFrame(columns=FIELDS)
    existing = set(base["id"].astype(int)) if len(base) else set()
    add = [r for r in rows if int(r["id"]) not in existing]
    if add:
        base = pd.concat([base, pd.DataFrame(add)], ignore_index=True)
        base.to_csv(HM, index=False)
    print(f"horror_movies.csv → {len(base):,} rows (+{len(add)} new)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--api-key", default=os.environ.get("TMDB_API_KEY"))
    ap.add_argument("--delay", type=float, default=0.05)
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()
    if not args.api_key:
        raise SystemExit(
            "Need TMDB_API_KEY or --api-key\n"
            "Get one free at https://www.themoviedb.org/settings/api\n"
            "Then: TMDB_API_KEY=... python3 fill_poster_paths.py"
        )

    todo = missing_ids()
    if args.limit:
        todo = todo[: args.limit]
    print(f"missing from horror_movies / backfill: {len(todo)}")
    if not todo:
        print("nothing to do — rebuilding explorer anyway")
        from build_explorer import main as build_explorer
        build_explorer()
        return

    session = requests.Session()
    done: dict[int, dict] = {}
    if OUT.exists():
        for r in csv.DictReader(OUT.open()):
            done[int(r["id"])] = r

    t0 = time.time()
    fetched = 0
    for i, (pid, title, year) in enumerate(todo, 1):
        prev = done.get(pid)
        if prev and str(prev.get("poster_path") or "").startswith("/"):
            continue
        row = fetch_movie(session, args.api_key, pid)
        if row is None:
            row = {
                "id": pid,
                "title": title,
                "original_title": title,
                "release_date": f"{year}-01-01",
                "poster_path": "",
                "runtime": 0,
                "genre_names": "",
            }
            for k in FIELDS:
                row.setdefault(k, "")
        done[pid] = row
        fetched += 1
        if fetched % 50 == 0 or i == len(todo):
            ok = sum(
                1 for r in done.values()
                if str(r.get("poster_path") or "").startswith("/")
            )
            rate = fetched / max(time.time() - t0, 1e-6)
            print(
                f"{i}/{len(todo)} fetched={fetched} with_path={ok} {rate:.1f}/s",
                flush=True,
            )
            write_sidecar(done)
        time.sleep(args.delay)

    write_sidecar(done)
    ok_rows = [
        r for r in done.values()
        if str(r.get("poster_path") or "").startswith("/")
    ]
    print(f"wrote {OUT} ({len(ok_rows)}/{len(done)} with poster_path)")
    merge_into_horror_movies(list(done.values()))

    from build_explorer import main as build_explorer
    build_explorer()

    # report residual nulls in explorer sense
    posts = {int(r["id"]) for r in csv.DictReader(POSTERS.open())}
    have = {
        int(r["id"]) for r in csv.DictReader(HM.open())
        if str(r.get("poster_path") or "").startswith("/")
    }
    print(f"corpus still missing poster_path: {len(posts - have)}")


if __name__ == "__main__":
    main()

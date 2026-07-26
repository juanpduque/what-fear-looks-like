#!/usr/bin/env python3
"""Pull TMDB English horror films 2023–2025 into the local corpus.

Dry-run counterpart: discover EN + Horror, keep those with poster_path,
exclude Animation/Music from the *analyzable* set, merge all EN horror
into horror_movies.csv (gitignored), append exclusion CSVs, download
posters for the analyzable newcomers.

  TMDB_API_KEY=... python3 pull_2023_2025.py
  python3 pull_2023_2025.py --api-key YOUR_KEY --skip-posters
"""
from __future__ import annotations

import argparse
import csv
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import pandas as pd
import requests

DATA = Path(__file__).resolve().parent / "data"
HM = DATA / "horror_movies.csv"
SIDECAR = DATA / "horror_refresh_2023_2025.csv"
PROGRESS = DATA / "horror_refresh_2023_2025_progress.csv"
POSTER_DIR = DATA / "posters"
IMG_BASE = "https://image.tmdb.org/t/p/w342"
DISCOVER = "https://api.themoviedb.org/3/discover/movie"
MOVIE = "https://api.themoviedb.org/3/movie/{pid}"

ANIMATION, MUSIC, HORROR = 16, 10402, 27
HEADERS = {"User-Agent": "PulpAnalytics-AnatomyOfFear/1.0-pull2023"}

HM_FIELDS = [
    "id", "imdb_id", "original_title", "title", "original_language", "overview",
    "tagline", "release_date", "poster_path", "popularity", "vote_count",
    "vote_average", "budget", "revenue", "runtime", "status", "adult",
    "backdrop_path", "genre_names", "collection", "collection_name",
]


def discover_year(session: requests.Session, api_key: str, year: int) -> list[dict]:
    rows, page, total_pages = [], 1, 1
    while page <= min(total_pages, 500):
        params = {
            "api_key": api_key,
            "with_genres": HORROR,
            "with_original_language": "en",
            "primary_release_date.gte": f"{year}-01-01",
            "primary_release_date.lte": f"{year}-12-31",
            "sort_by": "primary_release_date.asc",
            "include_adult": "false",
            "page": page,
        }
        r = session.get(DISCOVER, params=params, headers=HEADERS, timeout=30)
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


def fetch_movie(session: requests.Session, api_key: str, pid: int) -> dict | None:
    for attempt in range(6):
        r = session.get(
            MOVIE.format(pid=pid),
            params={
                "api_key": api_key,
                "language": "en-US",
                "append_to_response": "external_ids",
            },
            headers=HEADERS,
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
        ext = m.get("external_ids") or {}
        imdb = ext.get("imdb_id") or ""
        return {
            "id": int(m["id"]),
            "imdb_id": imdb if isinstance(imdb, str) else "",
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
            "_genre_ids": [g.get("id") for g in genres if g.get("id")],
        }
    return None


def load_progress() -> dict[int, dict]:
    done: dict[int, dict] = {}
    if PROGRESS.exists():
        for r in csv.DictReader(PROGRESS.open(encoding="utf-8")):
            done[int(r["id"])] = r
    return done


def save_progress(done: dict[int, dict]):
    with PROGRESS.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=HM_FIELDS)
        w.writeheader()
        for pid in sorted(done):
            row = {k: done[pid].get(k, "") for k in HM_FIELDS}
            w.writerow(row)


def append_exclusions(rows: list[dict], kind: str):
    """kind in {'animation','music'}."""
    path = DATA / f"excluded_{kind}.csv"
    existing = set()
    old = []
    if path.exists():
        with path.open(encoding="utf-8") as f:
            old = list(csv.DictReader(f))
            existing = {int(r["id"]) for r in old}
    add = []
    for r in rows:
        pid = int(r["id"])
        if pid in existing:
            continue
        y = (r.get("release_date") or "")[:4]
        add.append({
            "id": pid,
            "title": r.get("title") or "",
            "year": y,
            "genre_names": r.get("genre_names") or "",
        })
    if not add:
        print(f"excluded_{kind}.csv: no new rows")
        return
    fields = ["id", "title", "year", "genre_names"]
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in old + add:
            w.writerow({k: r.get(k, "") for k in fields})
    print(f"excluded_{kind}.csv: +{len(add)} → {len(old) + len(add)}")


def merge_horror_movies(new_rows: list[dict]):
    if HM.exists():
        base = pd.read_csv(HM, low_memory=False)
    else:
        base = pd.DataFrame(columns=HM_FIELDS)
    # ensure imdb_id column
    if "imdb_id" not in base.columns:
        base.insert(1, "imdb_id", "")
    # Drop corrupt / non-numeric id rows (legacy CSV has occasional junk lines).
    base["id"] = pd.to_numeric(base["id"], errors="coerce")
    bad = int(base["id"].isna().sum())
    if bad:
        print(f"  dropping {bad} corrupt horror_movies rows (non-numeric id)")
        base = base.dropna(subset=["id"])
    base["id"] = base["id"].astype(int)
    existing = set(base["id"])
    add = [r for r in new_rows if int(r["id"]) not in existing]
    updated = 0
    if add:
        base = pd.concat([base, pd.DataFrame(add)[HM_FIELDS]], ignore_index=True)
    # refresh poster_path / dates for ids we already had (release dates drift)
    by_id = {int(r["id"]): r for r in new_rows}
    if by_id and len(base):
        for i, row in base.iterrows():
            pid = int(row["id"])
            if pid not in by_id:
                continue
            src = by_id[pid]
            changed = False
            for col in ("poster_path", "release_date", "title", "genre_names",
                        "popularity", "vote_count", "vote_average", "imdb_id",
                        "runtime", "status"):
                new_v = src.get(col, "")
                if col == "imdb_id" and (not new_v or (isinstance(row.get(col), str) and str(row.get(col)).startswith("tt"))):
                    # keep existing tt if new empty
                    if not new_v:
                        continue
                old_v = row.get(col)
                if pd.isna(old_v):
                    old_v = ""
                if str(old_v) != str(new_v) and new_v != "":
                    base.at[i, col] = new_v
                    changed = True
            if changed:
                updated += 1
    base.to_csv(HM, index=False)
    print(f"horror_movies.csv → {len(base):,} rows (+{len(add)} new, ~{updated} refreshed)")


def download_posters(rows: list[dict], workers: int = 16) -> tuple[int, int]:
    POSTER_DIR.mkdir(parents=True, exist_ok=True)
    todo = []
    for r in rows:
        path = r.get("poster_path") or ""
        if not str(path).startswith("/"):
            continue
        dest = POSTER_DIR / f"{int(r['id'])}.jpg"
        if dest.exists() and dest.stat().st_size > 2000:
            continue
        todo.append((int(r["id"]), path))
    print(f"poster download queue: {len(todo):,}")
    if not todo:
        return 0, 0

    ok = fail = 0
    session_local = requests.Session()

    def one(item):
        pid, path = item
        dest = POSTER_DIR / f"{pid}.jpg"
        try:
            r = session_local.get(IMG_BASE + path, headers=HEADERS, timeout=30)
            if r.status_code == 200 and len(r.content) > 2000:
                dest.write_bytes(r.content)
                return True
        except Exception:
            pass
        return False

    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = [ex.submit(one, t) for t in todo]
        for i, fut in enumerate(as_completed(futs), 1):
            if fut.result():
                ok += 1
            else:
                fail += 1
            if i % 200 == 0 or i == len(futs):
                print(f"  posters {i}/{len(futs)} ok={ok} fail={fail}")
    return ok, fail


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--api-key", default=os.environ.get("TMDB_API_KEY"))
    ap.add_argument("--skip-posters", action="store_true")
    ap.add_argument("--workers", type=int, default=16)
    args = ap.parse_args()
    if not args.api_key:
        raise SystemExit("Need TMDB_API_KEY or --api-key")

    session = requests.Session()

    # 1) Discover
    discovered = []
    for year in (2023, 2024, 2025):
        rows = discover_year(session, args.api_key, year)
        print(f"discover {year}: {len(rows):,}")
        discovered.extend(rows)
    by_id = {m["id"]: m for m in discovered}
    print(f"unique discover: {len(by_id):,}")

    # 2) Detail fetch with resume
    done = load_progress()
    todo_ids = [pid for pid in sorted(by_id) if pid not in done]
    print(f"detail fetch todo: {len(todo_ids):,} (already {len(done):,})")
    t0 = time.time()
    for i, pid in enumerate(todo_ids, 1):
        row = fetch_movie(session, args.api_key, pid)
        if row is None:
            # fall back to discover stub
            m = by_id[pid]
            gids = m.get("genre_ids") or []
            names = []
            if ANIMATION in gids:
                names.append("Animation")
            if MUSIC in gids:
                names.append("Music")
            if HORROR in gids:
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
        # persist without private key
        clean = {k: row.get(k, "") for k in HM_FIELDS}
        done[pid] = clean
        # stash genre ids on discover for exclusion if detail lacked genres
        if i % 50 == 0 or i == len(todo_ids):
            save_progress(done)
            rate = i / max(time.time() - t0, 1e-6)
            print(f"  details {i}/{len(todo_ids)} ({rate:.1f}/s)")
        time.sleep(0.04)
    save_progress(done)

    all_rows = [done[pid] for pid in sorted(done)]
    # write sidecar (committable)
    with SIDECAR.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=HM_FIELDS)
        w.writeheader()
        for r in all_rows:
            w.writerow({k: r.get(k, "") for k in HM_FIELDS})
    print(f"wrote {SIDECAR} ({len(all_rows):,})")

    # 3) Exclusions from genre_names
    anim, music = [], []
    for r in all_rows:
        names = {x.strip() for x in (r.get("genre_names") or "").split(",") if x.strip()}
        if "Animation" in names:
            anim.append(r)
        if "Music" in names:
            music.append(r)
    append_exclusions(anim, "animation")
    append_exclusions(music, "music")

    # 4) Merge into horror_movies
    merge_horror_movies(all_rows)

    # 5) Analyzable set = poster + not anim/music + en (already)
    analyzable = []
    for r in all_rows:
        names = {x.strip() for x in (r.get("genre_names") or "").split(",") if x.strip()}
        if "Animation" in names or "Music" in names:
            continue
        if not str(r.get("poster_path") or "").startswith("/"):
            continue
        analyzable.append(r)
    print(f"analyzable newcomers (en+poster+no Anim/Music): {len(analyzable):,}")

    if not args.skip_posters:
        ok, fail = download_posters(analyzable, workers=args.workers)
        print(f"posters downloaded: ok={ok} fail={fail}")

    # summary vs current analyzed
    analyzed = set()
    ap = DATA / "attributes.csv"
    if ap.exists():
        analyzed = {int(r["id"]) for r in csv.DictReader(ap.open())}
    new_vs = [r for r in analyzable if int(r["id"]) not in analyzed]
    print("\n=== PULL SUMMARY ===")
    print(f"EN horror 2023–2025 pulled: {len(all_rows):,}")
    print(f"with poster, no Anim/Music: {len(analyzable):,}")
    print(f"not yet in attributes.csv: {len(new_vs):,}")
    print(f"horror_movies.csv rows: {sum(1 for _ in open(HM)) - 1:,}")


if __name__ == "__main__":
    main()

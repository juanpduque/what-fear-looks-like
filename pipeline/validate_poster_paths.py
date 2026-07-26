#!/usr/bin/env python3
"""Compare frozen horror_movies poster_path vs current TMDB primary poster.

Preferred (fast, accurate):
  TMDB_API_KEY=... python3 validate_poster_paths.py
  python3 validate_poster_paths.py --api-key YOUR_KEY

Fallback without key (slow, rate-limited HTML scrape):
  python3 validate_poster_paths.py --html --sample 500 --delay 2.0
"""
from __future__ import annotations

import argparse
import csv
import os
import random
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests

DATA = Path(__file__).resolve().parent / "data"
OUT = DATA / "poster_path_drift.csv"
FIELDS = ["id", "title", "year", "stored_path", "current_path", "match", "status"]

POSTER_IMG_RE = re.compile(
    r'class="[^"]*poster[^"]*"[^>]+src="https://(?:media|image)\.themoviedb\.org/t/p/[^"/]+(/[^"]+\.jpg)"'
)
OG_RE = re.compile(r'property="og:image" content="([^"]+)"')
PATH_RE = re.compile(r"/t/p/(?:w\d+|original|w\d+_and_h\d+_face)(/[^\"\s]+\.jpg)")
HTML_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}


def load_corpus():
    posts = {}
    with (DATA / "posters.csv").open(newline="", encoding="utf-8", errors="replace") as f:
        for r in csv.DictReader(f):
            try:
                pid = int(float(str(r["id"]).strip()))
            except (TypeError, ValueError):
                continue
            posts[pid] = {"title": r["title"], "year": r["year"]}
    paths = {}
    missing = 0
    with (DATA / "horror_movies.csv").open(newline="", encoding="utf-8", errors="replace") as f:
        for r in csv.DictReader(f):
            try:
                pid = int(float(str(r["id"]).strip()))
            except (TypeError, ValueError):
                continue
            p = (r.get("poster_path") or "").strip()
            if p.startswith("/"):
                paths[pid] = p
    for pid in posts:
        if pid not in paths:
            # fall back to backfill sidecar if present
            missing += 1
    # merge backfill for corpus ids still missing
    bf = DATA / "poster_paths_backfill.csv"
    if bf.exists():
        with bf.open(newline="", encoding="utf-8", errors="replace") as f:
            for r in csv.DictReader(f):
                try:
                    pid = int(float(str(r["id"]).strip()))
                except (TypeError, ValueError):
                    continue
                p = (r.get("poster_path") or "").strip()
                if pid in posts and pid not in paths and p.startswith("/"):
                    paths[pid] = p
                    missing -= 1
    # recount missing after merge
    missing = sum(1 for pid in posts if pid not in paths)
    # only validate ids that are in the analyzed corpus AND have a stored path
    paths = {pid: paths[pid] for pid in posts if pid in paths}
    return posts, paths, missing


def summarize(rows: list[dict]):
    m = mm = er = 0
    examples = []
    for r in rows:
        if r["status"] != "ok":
            er += 1
        elif r["match"] == "1":
            m += 1
        else:
            mm += 1
            if len(examples) < 12:
                examples.append(r)
    return m, mm, er, examples


def fetch_api(session: requests.Session, api_key: str, pid: int):
    url = f"https://api.themoviedb.org/3/movie/{pid}"
    try:
        r = session.get(url, params={"api_key": api_key}, timeout=30)
    except Exception as e:
        return None, f"err:{type(e).__name__}"
    if r.status_code == 404:
        return None, "not_found"
    if r.status_code == 429:
        return None, "http_429"
    if r.status_code != 200:
        return None, f"http_{r.status_code}"
    path = r.json().get("poster_path")
    if not path:
        return None, "no_poster"
    return path, "ok"


def fetch_html(session: requests.Session, pid: int):
    url = f"https://www.themoviedb.org/movie/{pid}"
    for attempt in range(5):
        try:
            r = session.get(url, headers=HTML_HEADERS, timeout=30)
        except Exception as e:
            time.sleep(1.5 * (attempt + 1))
            last = f"err:{type(e).__name__}"
            continue
        if r.status_code == 429:
            wait = 25 + attempt * 20
            time.sleep(wait)
            last = "http_429"
            continue
        if r.status_code == 404:
            return None, "not_found"
        if r.status_code != 200:
            time.sleep(2)
            last = f"http_{r.status_code}"
            continue
        m = POSTER_IMG_RE.search(r.text)
        if m:
            return m.group(1), "ok"
        og = OG_RE.search(r.text)
        if og:
            pm = PATH_RE.search(og.group(1))
            if pm:
                return pm.group(1), "ok"
        return None, "no_poster"
    return None, last


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--api-key", default=os.environ.get("TMDB_API_KEY"))
    ap.add_argument("--html", action="store_true", help="force HTML scrape")
    ap.add_argument("--sample", type=int, default=0)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--delay", type=float, default=0.0)
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    posts, paths, missing_path = load_corpus()
    ids = sorted(paths)
    if args.sample:
        rng = random.Random(args.seed)
        ids = sorted(rng.sample(ids, min(args.sample, len(ids))))
    if args.limit:
        ids = ids[: args.limit]

    use_api = bool(args.api_key) and not args.html
    mode = "api" if use_api else "html"
    print(f"mode={mode} check={len(ids)} corpus_with_path={len(paths)} missing_path={missing_path}")
    if not use_api:
        print("tip: pass --api-key or TMDB_API_KEY for a full reliable run")

    session = requests.Session()
    rows = []
    t0 = time.time()

    if use_api:
        def one(pid):
            cur, status = fetch_api(session, args.api_key, pid)
            # light throttle on 429
            if status == "http_429":
                time.sleep(2)
                cur, status = fetch_api(session, args.api_key, pid)
            stored = paths[pid]
            return {
                "id": pid,
                "title": posts[pid]["title"],
                "year": posts[pid]["year"],
                "stored_path": stored,
                "current_path": cur or "",
                "match": "1" if (stored and cur and stored == cur) else "0",
                "status": status,
            }

        with ThreadPoolExecutor(max_workers=args.workers) as ex:
            futs = [ex.submit(one, pid) for pid in ids]
            for i, fut in enumerate(as_completed(futs), 1):
                rows.append(fut.result())
                if i % 500 == 0 or i == len(ids):
                    rate = i / max(time.time() - t0, 1e-6)
                    print(f"{i}/{len(ids)} {rate:.1f}/s", flush=True)
    else:
        for i, pid in enumerate(ids, 1):
            cur, status = fetch_html(session, pid)
            stored = paths[pid]
            rows.append(
                {
                    "id": pid,
                    "title": posts[pid]["title"],
                    "year": posts[pid]["year"],
                    "stored_path": stored,
                    "current_path": cur or "",
                    "match": "1" if (stored and cur and stored == cur) else "0",
                    "status": status,
                }
            )
            if i % 50 == 0 or i == len(ids):
                rate = i / max(time.time() - t0, 1e-6)
                print(f"{i}/{len(ids)} {rate:.2f}/s", flush=True)
            if args.delay:
                time.sleep(args.delay)

    rows.sort(key=lambda r: int(r["id"]))
    with OUT.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)

    m, mm, er, examples = summarize(rows)
    print("=== FINAL ===")
    print(f"checked={len(rows)} match={m} mismatch={mm} errors={er}")
    if m + mm:
        print(f"mismatch among ok: {mm}/{m+mm} = {100*mm/(m+mm):.2f}%")
        print(f"extrapolated on {len(paths):,} with path: ~{int(round(len(paths)*mm/(m+mm))):,}")
    print(f"also missing frozen path in horror_movies: {missing_path}")
    print(f"wrote {OUT}")
    for r in examples:
        print(
            f"  {r['id']} {r['title']} ({r['year']}) "
            f"{r['stored_path']} -> {r['current_path']}"
        )


if __name__ == "__main__":
    main()

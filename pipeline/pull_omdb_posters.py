#!/usr/bin/env python3
"""Download OMDb/Amazon poster URLs for TMDB ids lacking TMDB artwork.

Reads data/gap_en_no_poster_omdb_hits.csv (id, title, year, omdb_poster).
Writes local JPGs + data/new_omdb_ids.csv for analyze_color_ids.py.

  python3 pull_omdb_posters.py
  python3 pull_omdb_posters.py --workers 16
"""
from __future__ import annotations

import argparse
import csv
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests

DATA = Path(__file__).resolve().parent / "data"
HITS = DATA / "gap_en_no_poster_omdb_hits.csv"
POSTER_DIR = DATA / "posters"
IDS_OUT = DATA / "new_omdb_ids.csv"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; PulpAnalytics-AnatomyOfFear/1.0)",
    "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
}


def _candidates(url: str) -> list[str]:
    url = (url or "").strip()
    if not url.startswith("http"):
        return []
    out = [url]
    if "._V1_" in url:
        base = url.split("._V1_")[0]
        out += [
            base + "._V1_SX300.jpg",
            base + "._V1_SY445.jpg",
            base + "._V1_UX182.jpg",
            base + "._V1_.jpg",
        ]
    # de-dupe, preserve order
    seen, uniq = set(), []
    for u in out:
        if u not in seen:
            seen.add(u)
            uniq.append(u)
    return uniq


def fetch_one(session: requests.Session, pid: int, url: str) -> tuple[int, bool, str]:
    dest = POSTER_DIR / f"{pid}.jpg"
    if dest.exists() and dest.stat().st_size > 2000:
        return pid, True, "exists"
    last = "no-url"
    for cand in _candidates(url):
        try:
            r = session.get(cand, headers=HEADERS, timeout=45, allow_redirects=True)
            if r.status_code != 200 or len(r.content) < 2000:
                last = f"http {r.status_code} len={len(r.content)}"
                continue
            if r.content[:3] not in (b"\xff\xd8\xff", b"\x89PN") and r.content[:4] != b"RIFF":
                last = "bad magic"
                continue
            dest.write_bytes(r.content)
            return pid, True, "ok"
        except Exception as e:
            last = f"{type(e).__name__}: {e}"
    return pid, False, last


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--hits", default=str(HITS))
    ap.add_argument("--workers", type=int, default=16)
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    hits_path = Path(args.hits)
    if not hits_path.exists():
        raise SystemExit(f"missing {hits_path}")

    rows = list(csv.DictReader(hits_path.open()))
    if args.limit:
        rows = rows[: args.limit]
    POSTER_DIR.mkdir(parents=True, exist_ok=True)

    session = requests.Session()
    ok = fail = 0
    fails = []
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {
            ex.submit(fetch_one, session, int(r["id"]), r["omdb_poster"]): r
            for r in rows
            if r.get("omdb_poster")
        }
        for i, fut in enumerate(as_completed(futs), 1):
            pid, good, msg = fut.result()
            if good:
                ok += 1
            else:
                fail += 1
                if len(fails) < 20:
                    fails.append((pid, msg))
            if i % 100 == 0 or i == len(futs):
                print(f"  download {i}/{len(futs)} ok={ok} fail={fail}", flush=True)

    ids = []
    for r in rows:
        pid = int(r["id"])
        dest = POSTER_DIR / f"{pid}.jpg"
        if not (dest.exists() and dest.stat().st_size > 2000):
            continue
        try:
            year = int(float(r["year"]))
        except (TypeError, ValueError):
            continue
        ids.append({"id": pid, "title": r.get("title") or "", "year": year})

    with IDS_OUT.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["id", "title", "year"])
        w.writeheader()
        for row in ids:
            w.writerow(row)

    print(f"\n=== OMDb POSTER INGEST ===")
    print(f"downloaded ok={ok} fail={fail}")
    print(f"ids with local poster+year: {len(ids):,} → {IDS_OUT.name}")
    if fails:
        print("fail samples:")
        for pid, msg in fails:
            print(f"  {pid}: {msg}")


if __name__ == "__main__":
    main()

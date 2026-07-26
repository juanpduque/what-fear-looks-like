#!/usr/bin/env python3
"""Recover release years for undated corpus entries (year=9999) via IMDb.

Uses the free suggestion endpoint behind imdb.com's search box, keyed by the
imdb_id already in data/imdb_ids.csv. No API key, no daily quota. Only exact
tconst matches are accepted, so no title-based guessing.

Writes:
  data/years_backfill_imdb.csv   (id, imdb_id, title, year — review before merge)

Usage:
  python3 enrich_years_imdb.py
  python3 enrich_years_imdb.py --limit 20 --workers 4
"""
from __future__ import annotations

import argparse
import csv
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests

DATA = Path(__file__).resolve().parent / "data"
SIDECAR = DATA / "imdb_ids.csv"
POSTERS = DATA / "posters.csv"
OUT = DATA / "years_backfill_imdb.csv"

SUGGEST = "https://v3.sg.media-imdb.com/suggestion/x/{tt}.json"
UA = "Mozilla/5.0 (compatible; AnatomyOfFear/1.0)"
UNDATED = 9999
MIN_YEAR, MAX_YEAR = 1897, 2030


def load_sidecar() -> dict[int, str]:
    out: dict[int, str] = {}
    with SIDECAR.open(encoding="utf-8", errors="replace") as f:
        for r in csv.DictReader(f):
            try:
                out[int(r["id"])] = (r.get("imdb_id") or "").strip()
            except (KeyError, TypeError, ValueError):
                continue
    return out


def load_undated() -> list[tuple[int, str]]:
    out = []
    with POSTERS.open(encoding="utf-8", errors="replace") as f:
        for r in csv.DictReader(f):
            try:
                if int(float(r["year"])) == UNDATED:
                    out.append((int(r["id"]), r.get("title") or ""))
            except (KeyError, TypeError, ValueError):
                continue
    return out


def fetch_year(session: requests.Session, tt: str) -> int | None:
    """Year for an exact tconst match, or None."""
    for attempt in range(4):
        try:
            r = session.get(SUGGEST.format(tt=tt), timeout=25)
        except requests.RequestException:
            time.sleep(1 + attempt)
            continue
        if r.status_code == 404:
            return None
        if not r.ok:
            time.sleep(1 + attempt)
            continue
        try:
            entries = r.json().get("d") or []
        except ValueError:
            return None
        for e in entries:
            if e.get("id") != tt:
                continue
            y = e.get("y")
            if isinstance(y, int) and MIN_YEAR <= y <= MAX_YEAR:
                return y
            return None
        return None
    return None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--delay", type=float, default=0.1)
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    sidecar = load_sidecar()
    undated = load_undated()
    todo = [(pid, t, sidecar[pid]) for pid, t in undated
            if sidecar.get(pid, "").startswith("tt")]
    if args.limit:
        todo = todo[: args.limit]
    print(f"undated: {len(undated):,}  with imdb_id: {len(todo):,}")
    if not todo:
        return

    session = requests.Session()
    session.headers["User-Agent"] = UA
    adapter = requests.adapters.HTTPAdapter(
        pool_connections=args.workers, pool_maxsize=args.workers
    )
    session.mount("https://", adapter)

    found: list[dict] = []
    lock = threading.Lock()
    done = 0

    def work(item):
        pid, title, tt = item
        y = fetch_year(session, tt)
        if args.delay:
            time.sleep(args.delay)
        return pid, title, tt, y

    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = [ex.submit(work, it) for it in todo]
        for fut in as_completed(futs):
            pid, title, tt, y = fut.result()
            with lock:
                done += 1
                if y:
                    found.append({"id": pid, "imdb_id": tt, "title": title, "year": y})
                if done % 50 == 0 or done == len(todo):
                    print(f"  {done}/{len(todo)} found={len(found):,}", flush=True)

    found.sort(key=lambda r: r["id"])
    with OUT.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["id", "imdb_id", "title", "year"])
        w.writeheader()
        w.writerows(found)

    print(f"\nrecovered {len(found):,} / {len(todo):,} "
          f"({100 * len(found) / len(todo):.1f}%) → {OUT.name}")
    if found:
        from collections import Counter
        hist = Counter(r["year"] for r in found)
        print("years:", ", ".join(f"{y}:{n}" for y, n in sorted(hist.items())))


if __name__ == "__main__":
    main()

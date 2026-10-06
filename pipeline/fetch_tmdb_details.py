#!/usr/bin/env python3
"""Fetch current TMDB /movie/{id} metadata for every id in posters.csv.

Writes a resumable JSONL cache (one object per id) used by build_corpus.py:
  data/qa/tmdb_details/tmdb_details.jsonl

Fields kept: id, http, status, release_date, adult, original_language,
genres (names), poster_path, title, fetched.

Usage:
  python3 fetch_tmdb_details.py            # resume, fetch missing ids
  python3 fetch_tmdb_details.py --refresh  # refetch all
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
DATA = Path(__file__).resolve().parent / "data"
POSTERS = DATA / "posters.csv"
OUT_DIR = DATA / "qa" / "tmdb_details"
CACHE = OUT_DIR / "tmdb_details.jsonl"
URL = "https://api.themoviedb.org/3/movie/{pid}"


def load_key() -> str:
    key = os.environ.get("TMDB_API_KEY", "")
    if key:
        return key
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            if line.startswith("TMDB_API_KEY="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    return ""


def load_cache() -> dict[int, dict]:
    out: dict[int, dict] = {}
    if CACHE.exists():
        for line in CACHE.open(encoding="utf-8"):
            line = line.strip()
            if line:
                rec = json.loads(line)
                out[int(rec["id"])] = rec
    return out


def fetch(session: requests.Session, key: str, pid: int) -> dict:
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    for attempt in range(6):
        try:
            r = session.get(URL.format(pid=pid), params={"api_key": key}, timeout=30)
        except requests.RequestException:
            time.sleep(1 + attempt)
            continue
        if r.status_code == 429:
            time.sleep(2 + attempt * 2)
            continue
        if r.status_code == 404:
            return {"id": pid, "http": 404, "fetched": now}
        if r.status_code != 200:
            time.sleep(1 + attempt)
            continue
        j = r.json()
        return {
            "id": pid,
            "http": 200,
            "status": j.get("status"),
            "release_date": j.get("release_date") or None,
            "adult": bool(j.get("adult")),
            "original_language": j.get("original_language"),
            "genres": [g.get("name") for g in j.get("genres") or []],
            "poster_path": j.get("poster_path"),
            "title": j.get("title"),
            "fetched": now,
        }
    return {"id": pid, "http": -1, "fetched": now}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--refresh", action="store_true")
    ap.add_argument("--workers", type=int, default=16)
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    key = load_key()
    if not key:
        raise SystemExit("TMDB_API_KEY missing")

    ids: list[int] = []
    seen: set[int] = set()
    with POSTERS.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            try:
                pid = int(row["id"])
            except (KeyError, ValueError):
                continue
            if pid not in seen:
                seen.add(pid)
                ids.append(pid)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    cache = {} if args.refresh else load_cache()
    if args.refresh and CACHE.exists():
        CACHE.unlink()
    todo = [i for i in ids if i not in cache or cache[i].get("http") == -1]
    if args.limit:
        todo = todo[: args.limit]
    print(f"ids={len(ids)} cached={len(cache)} todo={len(todo)}", flush=True)

    lock = threading.Lock()
    session = requests.Session()
    adapter = requests.adapters.HTTPAdapter(pool_maxsize=args.workers)
    session.mount("https://", adapter)
    done = 0
    t0 = time.time()
    with CACHE.open("a", encoding="utf-8") as out, ThreadPoolExecutor(args.workers) as ex:
        futs = [ex.submit(fetch, session, key, pid) for pid in todo]
        for fut in as_completed(futs):
            rec = fut.result()
            with lock:
                out.write(json.dumps(rec, ensure_ascii=False) + "\n")
                done += 1
                if done % 1000 == 0:
                    out.flush()
                    rate = done / max(time.time() - t0, 1e-6)
                    print(f"  {done}/{len(todo)}  {rate:.1f}/s", flush=True)
    print(f"done {done}", flush=True)


if __name__ == "__main__":
    main()

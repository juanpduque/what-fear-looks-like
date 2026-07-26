#!/usr/bin/env python3
"""Probe OMDb for posters among the English no-TMDB-poster gap.

Resumes from data/gap_en_no_poster_omdb_hits.csv. Uses imdb_ids.csv for the
current IMDb map (so new ids from enrich_imdb_ids.py are included).

  OMDB_API_KEY=... python3 probe_omdb_posters.py
  OMDB_API_KEY=... python3 probe_omdb_posters.py --limit 100 --refresh-stale
"""
from __future__ import annotations

import argparse
import csv
import os
import time
from pathlib import Path

import requests

DATA = Path(__file__).resolve().parent / "data"
GAP = DATA / "gap_en_remaining_no_poster.csv"
SIDECAR = DATA / "imdb_ids.csv"
HITS = DATA / "gap_en_no_poster_omdb_hits.csv"
MISS = DATA / "gap_en_no_poster_omdb_miss.csv"
POSTER_DIR = DATA / "posters"
OMDB_URL = "http://www.omdbapi.com/"


def load_imdb() -> dict[int, str]:
    out: dict[int, str] = {}
    with SIDECAR.open(encoding="utf-8", errors="replace") as f:
        for r in csv.DictReader(f):
            try:
                tt = (r.get("imdb_id") or "").strip()
                if tt.startswith("tt"):
                    out[int(r["id"])] = tt
            except (KeyError, TypeError, ValueError):
                continue
    return out


def has_local(pid: int) -> bool:
    p = POSTER_DIR / f"{pid}.jpg"
    return p.exists() and p.stat().st_size > 2000


def load_hits() -> dict[int, dict]:
    out: dict[int, dict] = {}
    if not HITS.exists():
        return out
    with HITS.open(encoding="utf-8", errors="replace") as f:
        for r in csv.DictReader(f):
            try:
                out[int(r["id"])] = r
            except (KeyError, TypeError, ValueError):
                continue
    return out


def load_miss() -> set[int]:
    out: set[int] = set()
    if not MISS.exists():
        return out
    with MISS.open(encoding="utf-8", errors="replace") as f:
        for r in csv.DictReader(f):
            try:
                out.add(int(r["id"]))
            except (KeyError, TypeError, ValueError):
                continue
    return out


def write_csv(path: Path, rows: list[dict], fields: list[str]) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--api-key", default=os.environ.get("OMDB_API_KEY"))
    ap.add_argument("--delay", type=float, default=0.25)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument(
        "--refresh-stale",
        action="store_true",
        help="re-query OMDb for prior hits that have no local poster",
    )
    ap.add_argument(
        "--recheck-miss",
        action="store_true",
        help="re-query ids previously recorded as OMDb misses",
    )
    args = ap.parse_args()
    if not args.api_key:
        raise SystemExit("Need OMDB_API_KEY or --api-key")

    imdb = load_imdb()
    hits = load_hits()
    miss = load_miss()

    gap_rows = list(csv.DictReader(GAP.open(encoding="utf-8", errors="replace")))
    candidates: list[dict] = []
    for r in gap_rows:
        try:
            pid = int(r["id"])
        except (TypeError, ValueError):
            continue
        if has_local(pid):
            continue
        tt = imdb.get(pid)
        if not tt:
            continue
        if pid in hits and not args.refresh_stale:
            continue
        if pid in miss and not args.recheck_miss and pid not in hits:
            continue
        # refresh-stale: only prior hits without local file
        if args.refresh_stale and pid in hits and not has_local(pid):
            candidates.append({**r, "id": pid, "imdb_id": tt})
            continue
        if pid not in hits and (pid not in miss or args.recheck_miss):
            candidates.append({**r, "id": pid, "imdb_id": tt})

    # Prefer never-probed first, then stale hits
    never = [c for c in candidates if c["id"] not in hits]
    stale = [c for c in candidates if c["id"] in hits]
    todo = never + stale
    if args.limit:
        todo = todo[: args.limit]

    print(
        f"gap={len(gap_rows):,} with_imdb_no_local={sum(1 for r in gap_rows if imdb.get(int(r['id'])) and not has_local(int(r['id']))):,} "
        f"todo={len(todo):,} (never={len(never):,} stale={len(stale):,})",
        flush=True,
    )
    if not todo:
        return

    session = requests.Session()
    new_hits = 0
    new_miss = 0
    limit_hit = False
    t0 = time.time()

    for i, r in enumerate(todo, 1):
        pid = int(r["id"])
        tt = r["imdb_id"]
        try:
            resp = session.get(
                OMDB_URL,
                params={"apikey": args.api_key, "i": tt},
                timeout=30,
            )
            data = resp.json() if resp.ok else {}
        except Exception as e:
            print(f"  {pid} network {type(e).__name__}", flush=True)
            time.sleep(1)
            continue

        err = (data.get("Error") or "").lower()
        if "limit" in err or resp.status_code == 401:
            print(f"\nOMDb daily limit hit at {i}/{len(todo)}", flush=True)
            limit_hit = True
            break

        poster = (data.get("Poster") or "").strip()
        if data.get("Response") == "True" and poster and poster.upper() != "N/A":
            row = {
                "id": pid,
                "imdb_id": tt,
                "title": r.get("title") or data.get("Title") or "",
                "year": r.get("year") or data.get("Year") or "",
                "vote_count": r.get("vote_count") or "",
                "omdb_poster": poster,
                "omdb_title": data.get("Title") or "",
            }
            hits[pid] = row
            miss.discard(pid)
            new_hits += 1
        else:
            miss.add(pid)
            hits.pop(pid, None)
            new_miss += 1

        if i % 50 == 0 or i == len(todo):
            rate = i / max(time.time() - t0, 1e-6)
            print(
                f"  {i}/{len(todo)} new_hits={new_hits} new_miss={new_miss} "
                f"total_hits={len(hits):,} {rate:.1f}/s",
                flush=True,
            )
            write_csv(
                HITS,
                [hits[k] for k in sorted(hits)],
                ["id", "imdb_id", "title", "year", "vote_count", "omdb_poster", "omdb_title"],
            )
            write_csv(
                MISS,
                [{"id": k, "imdb_id": imdb.get(k, "")} for k in sorted(miss)],
                ["id", "imdb_id"],
            )
        time.sleep(args.delay)

    write_csv(
        HITS,
        [hits[k] for k in sorted(hits)],
        ["id", "imdb_id", "title", "year", "vote_count", "omdb_poster", "omdb_title"],
    )
    write_csv(
        MISS,
        [{"id": k, "imdb_id": imdb.get(k, "")} for k in sorted(miss)],
        ["id", "imdb_id"],
    )
    print(
        f"\n=== OMDb PROBE ===\n"
        f"new_hits={new_hits} new_miss={new_miss} "
        f"total_hits={len(hits):,} → {HITS.name}"
        f"{' (LIMIT)' if limit_hit else ''}"
    )


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Enrich the corpus with OMDb data (MPAA rating, Rotten Tomatoes/Metacritic
scores, IMDb rating/votes, plot, an independent poster URL) for every row
with a real imdb_id in master_dataset.csv.

Not a re-port of prior methodology -- this data was never pulled before.
Requires OMDB_API_KEY in the top-level .env (100k req/day tier; the free
1k/day tier is impractical at this corpus's ~103k imdb_id rows).

Resumable: skips ids already in --out on re-run.
Concurrent: ThreadPoolExecutor, --workers at a time.

Usage:
  python3 enrich_omdb.py
  python3 enrich_omdb.py --limit 100 --workers 10   # quick smoke test
"""

from __future__ import annotations

import argparse
import csv
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from threading import Lock

import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT.parent / ".env")

MASTER = ROOT / "data" / "master_dataset.csv"
OUT = ROOT / "data" / "qa" / "omdb_enrichment.csv"

OMDB_URL = "http://www.omdbapi.com/"

FIELDS = [
    "id",
    "imdb_id",
    "title",
    "rated",
    "imdb_rating",
    "imdb_votes",
    "rotten_tomatoes",
    "metacritic",
    "genre_omdb",
    "type_omdb",
    "plot",
    "poster_omdb",
    "error",
]


def load_targets(limit: int | None) -> list[dict]:
    out = []
    with MASTER.open(newline="", encoding="utf-8", errors="replace") as f:
        for r in csv.DictReader(f):
            iid = (r.get("imdb_id") or "").strip()
            if iid.startswith("tt"):
                out.append({"id": r["id"], "imdb_id": iid, "title": r.get("title", "")})
    if limit:
        out = out[:limit]
    return out


def load_done_ids(path: Path) -> set[str]:
    if not path.exists():
        return set()
    with path.open(newline="", encoding="utf-8", errors="replace") as f:
        return {row["id"] for row in csv.DictReader(f) if row.get("id")}


def parse_ratings(ratings: list[dict]) -> tuple[str, str]:
    rt, meta = "", ""
    for r in ratings or []:
        src = r.get("Source", "")
        if src == "Rotten Tomatoes":
            rt = r.get("Value", "")
        elif src == "Metacritic":
            meta = r.get("Value", "")
    return rt, meta


def fetch_omdb(session: requests.Session, api_key: str, imdb_id: str, attempts: int = 4) -> dict:
    last_exc = None
    for attempt in range(attempts):
        try:
            resp = session.get(OMDB_URL, params={"i": imdb_id, "apikey": api_key}, timeout=15)
            try:
                data = resp.json()
            except requests.exceptions.JSONDecodeError as e:
                # Real example: OMDb returned a raw unescaped control
                # character inside a text field (likely Plot), producing
                # technically-invalid JSON requests.json() can't parse.
                # Not retryable -- the same malformed response comes back
                # every time -- so record it and move on instead of
                # crashing the whole (hours-long) run on one bad id.
                return {"error": f"malformed JSON response: {e}"[:200]}
            if data.get("Response") == "False":
                return {"error": data.get("Error", "OMDb: no data")[:200]}
            rt, meta = parse_ratings(data.get("Ratings"))
            return {
                "rated": data.get("Rated", ""),
                "imdb_rating": data.get("imdbRating", ""),
                "imdb_votes": data.get("imdbVotes", ""),
                "rotten_tomatoes": rt,
                "metacritic": meta,
                "genre_omdb": data.get("Genre", ""),
                "type_omdb": data.get("Type", ""),
                "plot": (data.get("Plot") or "").replace("\n", " ")[:500],
                "poster_omdb": data.get("Poster", "") if data.get("Poster") != "N/A" else "",
                "error": "",
            }
        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e:
            last_exc = e
            time.sleep(min(10, 1.5 * (2**attempt)))
    return {"error": str(last_exc)[:200]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--workers", type=int, default=20)
    ap.add_argument("--out", default=str(OUT))
    args = ap.parse_args()

    api_key = os.environ.get("OMDB_API_KEY", "").strip()
    if not api_key:
        raise SystemExit("OMDB_API_KEY not set -- check the top-level .env")

    targets = load_targets(args.limit)
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    done = load_done_ids(out_path)
    todo = [t for t in targets if t["id"] not in done]
    print(f"targets: {len(targets)}, already done: {len(done)}, remaining: {len(todo)}")

    file_exists = out_path.exists() and out_path.stat().st_size > 0
    out_f = out_path.open("a", newline="", encoding="utf-8")
    writer = csv.DictWriter(out_f, fieldnames=FIELDS)
    if not file_exists:
        writer.writeheader()
        out_f.flush()

    lock = Lock()
    n_done = 0
    n_error = 0

    def process(t: dict) -> dict:
        session = requests.Session()
        result = fetch_omdb(session, api_key, t["imdb_id"])
        row = {"id": t["id"], "imdb_id": t["imdb_id"], "title": t["title"]}
        for k in FIELDS:
            if k not in row:
                row[k] = result.get(k, "")
        return row

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(process, t): t for t in todo}
        for fut in as_completed(futures):
            row = fut.result()
            with lock:
                writer.writerow(row)
                out_f.flush()
                n_done += 1
                if row.get("error"):
                    n_error += 1
                if n_done % 250 == 0 or n_done == len(todo):
                    print(f"{n_done}/{len(todo)} (errors: {n_error})")

    out_f.close()
    print(f"wrote {out_path} ({n_done} this run, {n_error} errors)")


if __name__ == "__main__":
    main()

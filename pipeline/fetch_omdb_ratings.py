#!/usr/bin/env python3
"""OMDb records (IMDb rating, Metascore, Rotten Tomatoes) for corpus films.

Audience vs critics: IMDb rating is the audience score; Metascore and the
Rotten Tomatoes Tomatometer that OMDb returns are critics' scores. Critics'
scores exist mostly for films with a visible release, so this queries only
corpus films with an IMDb id and MIN_VOTES+ TMDB votes (in a random sample of
500 corpus films, that subset held 85% of the critics' scores).

Needs OMDB_API_KEY (paid; one request per film). Resumable: ids already in
the output are skipped, and the 500-film sample (data/qa/omdb_sample) is
reused instead of fetched again.

  set -a; . ../.env; set +a
  python3 fetch_omdb_ratings.py [--limit N] [--workers 4]

Writes data/qa/omdb/omdb.jsonl, one raw OMDb response per line plus "id".
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from corpus import canonical_ids

HERE = Path(__file__).resolve().parent
DATA = HERE / "data"
OUT = DATA / "qa" / "omdb" / "omdb.jsonl"
SAMPLE = DATA / "qa" / "omdb_sample" / "omdb.jsonl"
MIN_VOTES = 10


def fetch(pid: int, imdb_id: str, key: str) -> dict:
    url = "https://www.omdbapi.com/?" + urllib.parse.urlencode({"i": imdb_id, "apikey": key})
    err = ""
    for _ in range(3):
        try:
            with urllib.request.urlopen(url, timeout=30) as resp:
                return {"id": pid, **json.loads(resp.read())}
        except Exception as e:  # noqa: BLE001 - retry, then record
            err = str(e)[:100]
    return {"id": pid, "Response": "False", "Error": err}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--workers", type=int, default=4)
    args = ap.parse_args()
    key = os.environ["OMDB_API_KEY"]

    corpus = canonical_ids()
    imdb = {}
    with (DATA / "imdb_ids.csv").open(newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r["imdb_id"].startswith("tt"):
                imdb[int(r["id"])] = r["imdb_id"]
    want = []
    with (DATA / "horror_movies.csv").open(newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            pid = int(r["id"])
            if pid in corpus and pid in imdb and float(r.get("vote_count") or 0) >= MIN_VOTES:
                want.append(pid)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    done = set()
    if OUT.exists():
        done = {json.loads(line)["id"] for line in OUT.open(encoding="utf-8")}
    with OUT.open("a", encoding="utf-8") as out:
        if SAMPLE.exists():
            for line in SAMPLE.open(encoding="utf-8"):
                rec = json.loads(line)
                if rec["id"] in want and rec["id"] not in done and rec.get("Response") == "True":
                    out.write(json.dumps(rec, ensure_ascii=False) + "\n")
                    done.add(rec["id"])
        todo = sorted(set(want) - done)
        if args.limit:
            todo = todo[: args.limit]
        print(
            f"{len(want):,} films with {MIN_VOTES}+ votes, {len(done):,} done, {len(todo):,} to fetch"
        )
        with ThreadPoolExecutor(args.workers) as ex:
            for i, rec in enumerate(ex.map(lambda p: fetch(p, imdb[p], key), todo), 1):
                out.write(json.dumps(rec, ensure_ascii=False) + "\n")
                if i % 500 == 0 or i == len(todo):
                    out.flush()
                    print(f"  {i:,}/{len(todo):,}", flush=True)
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()

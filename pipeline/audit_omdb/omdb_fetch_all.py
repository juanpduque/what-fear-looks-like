"""Fetch OMDb for every corpus film that has an IMDb id (resumable, local only).

Writes one raw OMDb response per line to results/omdb_all.jsonl ({"id", "imdb_id", "r": response}).
OMDb data is CC BY-NC: the file is git-ignored and must not be committed or published per film.
Key: $OMDB_API_KEY or ~/.omdb_key. Run from pipeline/: python3 audit_omdb/omdb_fetch_all.py [--workers 8]
"""

from __future__ import annotations

import argparse
import json
import threading
from concurrent.futures import ThreadPoolExecutor

import pandas as pd
from omdb_pilot import DATA, HERE, api_key, fetch

OUT = HERE / "results" / "omdb_all.jsonl"
WORLD_OUT = HERE / "results" / "omdb_world.jsonl"


def world_ids() -> set[int]:
    js = (HERE.parent.parent / "site" / "data" / "world_lookup.js").read_text(encoding="utf-8")
    idx = json.JSONDecoder().raw_decode(js[js.index("WORLD_INDEX=") + 12 :])[0]
    return {i for v in idx.values() for i in v}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument(
        "--world", action="store_true", help="fetch the 12-language world set instead of the corpus"
    )
    args = ap.parse_args()
    key = api_key()
    out = WORLD_OUT if args.world else OUT
    ids = (
        world_ids()
        if args.world
        else set(map(int, (DATA / "canonical_ids.txt").read_text().split()))
    )
    imdb = pd.read_csv(DATA / "imdb_ids.csv").dropna().drop_duplicates("id")
    imdb = imdb[imdb["id"].isin(ids)]
    out.parent.mkdir(exist_ok=True)
    done = set()
    if out.exists():
        done = {json.loads(x)["id"] for x in out.read_text().splitlines()}
    todo = [(int(r.id), r.imdb_id) for r in imdb.itertuples() if int(r.id) not in done]
    print(f"{len(todo)} to fetch ({len(done)} already done)", flush=True)
    lock, stop, n = threading.Lock(), threading.Event(), [0]

    def work(item, f):
        if stop.is_set():
            return
        pid, tt = item
        try:
            r = fetch(tt, key)
        except Exception as e:  # network blips: leave for the next run
            print("skip", pid, e, flush=True)
            return
        if "limit" in str(r.get("Error", "")).lower():
            stop.set()
            print("OMDb limit reached:", r["Error"], flush=True)
            return
        with lock:
            f.write(json.dumps({"id": pid, "imdb_id": tt, "r": r}) + "\n")
            n[0] += 1
            if n[0] % 1000 == 0:
                f.flush()
                print(n[0], flush=True)

    with out.open("a") as f, ThreadPoolExecutor(args.workers) as ex:
        list(ex.map(lambda it: work(it, f), todo))
    print("done", n[0], "new")


if __name__ == "__main__":
    main()

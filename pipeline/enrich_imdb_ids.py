#!/usr/bin/env python3
"""Enrich horror_movies.csv with TMDB → IMDb ids via /movie/{id}/external_ids.

Writes:
  data/imdb_ids.csv          (sidecar id,imdb_id — safe to commit)
  data/horror_movies.csv     (adds imdb_id column; gitignored)

Usage:
  TMDB_API_KEY=... python3 enrich_imdb_ids.py
  python3 enrich_imdb_ids.py --api-key YOUR_KEY
  python3 enrich_imdb_ids.py --corpus-only   # only ids in posters.csv
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
HM = DATA / "horror_movies.csv"
SIDECAR = DATA / "imdb_ids.csv"
POSTERS = DATA / "posters.csv"

EXT_URL = "https://api.themoviedb.org/3/movie/{pid}/external_ids"


def auth_kwargs(api_key: str) -> dict:
    """TMDB accepts v3 api_key query param or v4 Bearer JWT."""
    key = (api_key or "").strip()
    if key.startswith("eyJ"):
        return {"headers": {"Authorization": f"Bearer {key}"}}
    return {"params": {"api_key": key}}


def load_sidecar() -> dict[int, str]:
    out: dict[int, str] = {}
    if not SIDECAR.exists():
        return out
    with SIDECAR.open(encoding="utf-8", errors="replace") as f:
        for r in csv.DictReader(f):
            try:
                pid = int(r["id"])
            except (KeyError, ValueError, TypeError):
                continue
            imdb = (r.get("imdb_id") or "").strip()
            out[pid] = imdb
    return out


def write_sidecar(mapping: dict[int, str]) -> None:
    with SIDECAR.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["id", "imdb_id"])
        w.writeheader()
        for pid in sorted(mapping):
            w.writerow({"id": pid, "imdb_id": mapping[pid]})


def fetch_imdb_id(session: requests.Session, api_key: str, pid: int) -> str | None:
    """Return imdb_id string, '' if TMDB has none, None on hard failure/404."""
    url = EXT_URL.format(pid=pid)
    kwargs = auth_kwargs(api_key)
    for attempt in range(6):
        r = session.get(url, timeout=30, **kwargs)
        if r.status_code == 429:
            time.sleep(2 + attempt * 2)
            continue
        if r.status_code == 404:
            return None
        if r.status_code == 401:
            raise SystemExit(
                "TMDB 401 Unauthorized — check TMDB_API_KEY "
                "(v3 api_key or v4 Bearer token)."
            )
        if not r.ok:
            raise SystemExit(f"TMDB HTTP {r.status_code} for movie/{pid}/external_ids")
        imdb = (r.json().get("imdb_id") or "").strip()
        return imdb
    return None


def merge_into_horror_movies(mapping: dict[int, str]) -> None:
    if not HM.exists():
        raise SystemExit(f"missing {HM}")
    df = pd.read_csv(HM, low_memory=False)
    df["id"] = df["id"].astype(int)
    df["imdb_id"] = df["id"].map(lambda x: mapping.get(int(x), ""))
    # keep imdb_id near id
    cols = list(df.columns)
    cols.remove("imdb_id")
    id_i = cols.index("id")
    cols.insert(id_i + 1, "imdb_id")
    df = df[cols]
    df.to_csv(HM, index=False)
    with_id = int((df["imdb_id"].astype(str).str.startswith("tt")).sum())
    print(f"horror_movies.csv → {len(df):,} rows, {with_id:,} with imdb_id")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--api-key", default=os.environ.get("TMDB_API_KEY"))
    ap.add_argument("--delay", type=float, default=0.04)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument(
        "--corpus-only",
        action="store_true",
        help="only enrich ids present in posters.csv",
    )
    ap.add_argument(
        "--merge-only",
        action="store_true",
        help="skip API; merge existing imdb_ids.csv into horror_movies.csv",
    )
    args = ap.parse_args()

    if args.merge_only:
        mapping = load_sidecar()
        if not mapping:
            raise SystemExit(f"no mapping in {SIDECAR}")
        merge_into_horror_movies(mapping)
        return

    if not args.api_key:
        raise SystemExit(
            "Need TMDB_API_KEY or --api-key\n"
            "Get one free at https://www.themoviedb.org/settings/api\n"
            "Then: TMDB_API_KEY=... python3 enrich_imdb_ids.py"
        )
    if not HM.exists():
        raise SystemExit(f"missing {HM}")

    ids = [int(r["id"]) for r in csv.DictReader(HM.open(encoding="utf-8"))]
    if args.corpus_only:
        if not POSTERS.exists():
            raise SystemExit(f"missing {POSTERS}")
        corpus = {int(r["id"]) for r in csv.DictReader(POSTERS.open())}
        ids = [i for i in ids if i in corpus]
        print(f"corpus-only: {len(ids):,} ids")

    mapping = load_sidecar()
    # also treat existing HM imdb_id hits as done
    hm_cols = pd.read_csv(HM, nrows=0).columns.tolist()
    if "imdb_id" in hm_cols:
        for r in csv.DictReader(HM.open(encoding="utf-8")):
            imdb = (r.get("imdb_id") or "").strip()
            if imdb.startswith("tt"):
                mapping[int(r["id"])] = imdb

    todo = [i for i in ids if i not in mapping]
    if args.limit:
        todo = todo[: args.limit]
    print(f"already have: {len(mapping):,}  to fetch: {len(todo):,}")

    if not todo:
        write_sidecar(mapping)
        merge_into_horror_movies(mapping)
        return

    session = requests.Session()
    t0 = time.time()
    fetched = 0
    with_tt = sum(1 for v in mapping.values() if str(v).startswith("tt"))

    for i, pid in enumerate(todo, 1):
        imdb = fetch_imdb_id(session, args.api_key, pid)
        mapping[pid] = imdb or ""
        fetched += 1
        if mapping[pid].startswith("tt"):
            with_tt += 1
        if fetched % 100 == 0 or i == len(todo):
            rate = fetched / max(time.time() - t0, 1e-6)
            print(
                f"{i}/{len(todo)} fetched={fetched} with_tt={with_tt} {rate:.1f}/s",
                flush=True,
            )
            write_sidecar(mapping)
        time.sleep(args.delay)

    write_sidecar(mapping)
    # if --limit, still merge whatever we have for those rows
    merge_into_horror_movies(mapping)
    empty = sum(1 for pid in ids if not str(mapping.get(pid, "")).startswith("tt"))
    print(f"done. corpus/list missing imdb_id: {empty:,} / {len(ids):,}")


if __name__ == "__main__":
    main()

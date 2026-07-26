#!/usr/bin/env python3
"""Enrich horror_movies.csv with TMDB → IMDb ids via /movie/{id}/external_ids.

Writes:
  data/imdb_ids.csv          (sidecar id,imdb_id — safe to commit)
  data/horror_movies.csv     (adds imdb_id column; gitignored)

Usage:
  TMDB_API_KEY=... python3 enrich_imdb_ids.py
  python3 enrich_imdb_ids.py --api-key YOUR_KEY
  python3 enrich_imdb_ids.py --corpus-only   # only ids in posters.csv
  python3 enrich_imdb_ids.py --corpus-only --workers 12 --recheck-empty
"""
from __future__ import annotations

import argparse
import csv
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
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
        try:
            r = session.get(url, timeout=30, **kwargs)
        except requests.RequestException:
            time.sleep(1 + attempt)
            continue
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
            time.sleep(1 + attempt)
            continue
        imdb = (r.json().get("imdb_id") or "").strip()
        return imdb
    return None


def load_ids(path: Path) -> list[int]:
    out, seen = [], set()
    with path.open(encoding="utf-8", errors="replace") as f:
        for r in csv.DictReader(f):
            try:
                pid = int(r["id"])
            except (KeyError, ValueError, TypeError):
                continue
            if pid not in seen:
                seen.add(pid)
                out.append(pid)
    return out


def merge_into_horror_movies(mapping: dict[int, str]) -> None:
    """Rewrite HM with a refreshed imdb_id column.

    Streamed with the csv module: HM holds free-text fields that break pandas'
    C parser, and a row-wise round-trip preserves them untouched.
    """
    if not HM.exists():
        raise SystemExit(f"missing {HM}")
    with HM.open(encoding="utf-8", errors="replace", newline="") as f:
        reader = csv.DictReader(f)
        fields = list(reader.fieldnames or [])
        if "id" not in fields:
            raise SystemExit(f"{HM} has no id column")
        if "imdb_id" not in fields:
            fields.insert(fields.index("id") + 1, "imdb_id")
        tmp = HM.with_suffix(".csv.tmp")
        rows = with_id = 0
        with tmp.open("w", encoding="utf-8", newline="") as out:
            w = csv.DictWriter(out, fieldnames=fields, extrasaction="ignore")
            w.writeheader()
            for r in reader:
                try:
                    pid = int(r["id"])
                except (TypeError, ValueError):
                    continue
                imdb = mapping.get(pid, "") or (r.get("imdb_id") or "")
                r["imdb_id"] = imdb
                w.writerow(r)
                rows += 1
                with_id += imdb.startswith("tt")
    tmp.replace(HM)
    print(f"horror_movies.csv → {rows:,} rows, {with_id:,} with imdb_id")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--api-key", default=os.environ.get("TMDB_API_KEY"))
    ap.add_argument("--delay", type=float, default=0.04)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--workers", type=int, default=1)
    ap.add_argument(
        "--corpus-only",
        action="store_true",
        help="only enrich ids present in posters.csv (the analyzed corpus)",
    )
    ap.add_argument("--ids", default="", help="CSV with an id column; overrides source")
    ap.add_argument(
        "--recheck-empty",
        action="store_true",
        help="re-probe ids the sidecar already recorded as having no IMDb id",
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

    if args.ids:
        ids = load_ids(Path(args.ids))
        print(f"ids from {args.ids}: {len(ids):,}")
    elif args.corpus_only:
        # posters.csv is the analyzed corpus; horror_movies.csv only covers part of it
        if not POSTERS.exists():
            raise SystemExit(f"missing {POSTERS}")
        ids = load_ids(POSTERS)
        print(f"corpus-only: {len(ids):,} ids")
    else:
        ids = load_ids(HM)

    mapping = load_sidecar()
    # also treat existing HM imdb_id hits as done
    hm_cols = pd.read_csv(HM, nrows=0).columns.tolist()
    if "imdb_id" in hm_cols:
        with HM.open(encoding="utf-8", errors="replace") as f:
            for r in csv.DictReader(f):
                imdb = (r.get("imdb_id") or "").strip()
                if not imdb.startswith("tt"):
                    continue
                try:
                    mapping[int(r["id"])] = imdb
                except (TypeError, ValueError):
                    continue

    if args.recheck_empty:
        todo = [i for i in ids if not str(mapping.get(i, "")).startswith("tt")]
    else:
        todo = [i for i in ids if i not in mapping]
    if args.limit:
        todo = todo[: args.limit]
    print(f"already have: {len(mapping):,}  to fetch: {len(todo):,}")

    if not todo:
        write_sidecar(mapping)
        merge_into_horror_movies(mapping)
        return

    workers = max(1, args.workers)
    session = requests.Session()
    adapter = requests.adapters.HTTPAdapter(
        pool_connections=workers, pool_maxsize=workers
    )
    session.mount("https://", adapter)
    t0 = time.time()
    fetched = 0
    with_tt = sum(1 for v in mapping.values() if str(v).startswith("tt"))
    lock = threading.Lock()

    def work(pid: int) -> tuple[int, str]:
        imdb = fetch_imdb_id(session, args.api_key, pid)
        if args.delay:
            time.sleep(args.delay)
        return pid, imdb or ""

    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = [ex.submit(work, pid) for pid in todo]
        for fut in as_completed(futs):
            pid, imdb = fut.result()
            with lock:
                mapping[pid] = imdb
                fetched += 1
                if imdb.startswith("tt"):
                    with_tt += 1
                if fetched % 200 == 0 or fetched == len(todo):
                    rate = fetched / max(time.time() - t0, 1e-6)
                    print(
                        f"{fetched}/{len(todo)} with_tt={with_tt} {rate:.1f}/s",
                        flush=True,
                    )
                    write_sidecar(mapping)

    write_sidecar(mapping)
    # if --limit, still merge whatever we have for those rows
    merge_into_horror_movies(mapping)
    empty = sum(1 for pid in ids if not str(mapping.get(pid, "")).startswith("tt"))
    print(f"done. corpus/list missing imdb_id: {empty:,} / {len(ids):,}")


if __name__ == "__main__":
    main()

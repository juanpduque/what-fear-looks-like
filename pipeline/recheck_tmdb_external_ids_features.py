#!/usr/bin/env python3
"""Re-query TMDB /movie/{id}/external_ids for corpus features without imdb_id.

Target set: posters.csv ids that lack tt… in imdb_ids.csv AND have
runtime > 40 in horror_movies.csv (features, not shorts).

Writes:
  data/tmdb_external_ids_recheck_features.csv  (id, imdb_id, status)
  data/imdb_ids.csv                            (merge any new tt hits)
  data/horror_movies.csv                       (imdb_id column if present)

Usage:
  TMDB_API_KEY=... python3 recheck_tmdb_external_ids_features.py
  python3 recheck_tmdb_external_ids_features.py --workers 8
"""
from __future__ import annotations

import argparse
import csv
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests

from enrich_imdb_ids import (
    DATA,
    HM,
    POSTERS,
    SIDECAR,
    auth_kwargs,
    load_sidecar,
    merge_into_horror_movies,
    write_sidecar,
)

EXT_URL = "https://api.themoviedb.org/3/movie/{pid}/external_ids"
IDS_OUT = DATA / "tmdb_external_ids_recheck_features_ids.csv"
REPORT = DATA / "tmdb_external_ids_recheck_features.csv"


def load_feature_ids() -> list[int]:
    """Corpus posters without tt, with runtime > 40 in horror_movies."""
    corpus: list[int] = []
    seen: set[int] = set()
    with POSTERS.open(encoding="utf-8", errors="replace") as f:
        for r in csv.DictReader(f):
            try:
                pid = int(r["id"])
            except (KeyError, ValueError, TypeError):
                continue
            if pid not in seen:
                seen.add(pid)
                corpus.append(pid)

    sidecar = load_sidecar()
    runtime: dict[int, int] = {}
    with HM.open(encoding="utf-8", errors="replace") as f:
        for r in csv.DictReader(f):
            try:
                pid = int(r["id"])
            except (TypeError, ValueError):
                continue
            try:
                rt = int(float(r.get("runtime") or 0))
            except (TypeError, ValueError):
                rt = 0
            runtime[pid] = rt

    features: list[int] = []
    for pid in corpus:
        if str(sidecar.get(pid, "")).startswith("tt"):
            continue
        rt = runtime.get(pid)
        if rt is None or rt <= 40:
            continue
        features.append(pid)
    return features


def fetch_status(
    session: requests.Session, api_key: str, pid: int
) -> tuple[str, str]:
    """Return (imdb_id, status) where status is found|empty|error."""
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
            return "", "error"
        if r.status_code == 401:
            raise SystemExit(
                "TMDB 401 Unauthorized — check TMDB_API_KEY "
                "(v3 api_key or v4 Bearer token)."
            )
        if not r.ok:
            time.sleep(1 + attempt)
            continue
        imdb = (r.json().get("imdb_id") or "").strip()
        if imdb.startswith("tt"):
            return imdb, "found"
        return "", "empty"
    return "", "error"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--api-key", default=os.environ.get("TMDB_API_KEY"))
    ap.add_argument("--delay", type=float, default=0.04)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()
    if not args.api_key:
        raise SystemExit("Need TMDB_API_KEY or --api-key")

    features = load_feature_ids()
    if args.limit:
        features = features[: args.limit]
    print(f"features to recheck: {len(features):,}")

    # persist id list for audit
    runtime: dict[int, int] = {}
    with HM.open(encoding="utf-8", errors="replace") as f:
        for r in csv.DictReader(f):
            try:
                pid = int(r["id"])
                runtime[pid] = int(float(r.get("runtime") or 0))
            except (TypeError, ValueError):
                continue
    with IDS_OUT.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["id", "runtime"])
        w.writeheader()
        for pid in features:
            w.writerow({"id": pid, "runtime": runtime.get(pid, "")})

    workers = max(1, args.workers)
    session = requests.Session()
    adapter = requests.adapters.HTTPAdapter(
        pool_connections=workers, pool_maxsize=workers
    )
    session.mount("https://", adapter)

    results: dict[int, tuple[str, str]] = {}
    lock = threading.Lock()
    t0 = time.time()
    done = 0

    def work(pid: int) -> tuple[int, str, str]:
        imdb, status = fetch_status(session, args.api_key, pid)
        if args.delay:
            time.sleep(args.delay)
        return pid, imdb, status

    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = [ex.submit(work, pid) for pid in features]
        for fut in as_completed(futs):
            pid, imdb, status = fut.result()
            with lock:
                results[pid] = (imdb, status)
                done += 1
                if done % 100 == 0 or done == len(features):
                    rate = done / max(time.time() - t0, 1e-6)
                    print(f"{done}/{len(features)} {rate:.1f}/s", flush=True)

    # report
    with REPORT.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["id", "imdb_id", "status"])
        w.writeheader()
        for pid in features:
            imdb, status = results[pid]
            w.writerow({"id": pid, "imdb_id": imdb, "status": status})

    n_found = sum(1 for _, s in results.values() if s == "found")
    n_empty = sum(1 for _, s in results.values() if s == "empty")
    n_error = sum(1 for _, s in results.values() if s == "error")
    print(f"found (tt): {n_found:,}")
    print(f"empty (truly missing on TMDB): {n_empty:,}")
    print(f"error/404: {n_error:,}")
    print(f"report → {REPORT}")

    if n_found:
        mapping = load_sidecar()
        for pid, (imdb, status) in results.items():
            if status == "found" and imdb.startswith("tt"):
                mapping[pid] = imdb
        write_sidecar(mapping)
        print(f"imdb_ids.csv updated (+{n_found} new tt)")
        if HM.exists():
            merge_into_horror_movies(mapping)
    else:
        print("no new tt to merge")


if __name__ == "__main__":
    main()

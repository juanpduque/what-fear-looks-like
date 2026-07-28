#!/usr/bin/env python3
"""Remap TMDB movie ids that 404 (drift not_found) via search/movie + search/tv.

Does NOT mutate the corpus. Writes a review CSV for manual/auto gate:

  data/qa/tmdb_not_found_remap.csv

Confidence (movie preferred over tv when both unique):
  high   — exact title + year match, unique movie candidate, new id ≠ old
  medium — exact title + year±1, or undated; or unique tv with year
  low    — exact title but weak year / thin metadata
  ambig  — 2+ exact candidates (movie and/or tv)
  miss   — no exact title candidate

Usage:
  TMDB_API_KEY=... python3 remap_tmdb_not_found.py
  python3 remap_tmdb_not_found.py --limit 40 --workers 8
  python3 remap_tmdb_not_found.py --ids-file data/qa/poster_path_drift_errors.csv
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

from enrich_imdb_ids import auth_kwargs
from match_imdb_title_basics_features import normalize_title

DATA = Path(__file__).resolve().parent / "data"
DEFAULT_IN = DATA / "qa" / "poster_path_drift_errors.csv"
DRIFT = DATA / "poster_path_drift.csv"
HM = DATA / "horror_movies.csv"
POSTERS = DATA / "posters.csv"
OUT = DATA / "qa" / "tmdb_not_found_remap.csv"

SEARCH_MOVIE = "https://api.themoviedb.org/3/search/movie"
SEARCH_TV = "https://api.themoviedb.org/3/search/tv"


def year_int(v) -> int | None:
    try:
        y = int(float(v))
    except (TypeError, ValueError):
        return None
    if y <= 0 or y >= 9000:
        return None
    return y


def load_targets(path: Path, limit: int = 0) -> list[dict]:
    rows: list[dict] = []
    src = path if path.exists() else DRIFT
    with src.open(encoding="utf-8", errors="replace") as f:
        for r in csv.DictReader(f):
            if str(r.get("status") or "") != "not_found":
                continue
            try:
                pid = int(r["id"])
            except (KeyError, TypeError, ValueError):
                continue
            rows.append(
                {
                    "old_id": pid,
                    "title": (r.get("title") or "").strip(),
                    "year": year_int(r.get("year")),
                    "stored_path": (r.get("stored_path") or "").strip(),
                }
            )
    # enrich original_title / runtime from horror_movies
    meta: dict[int, dict] = {}
    if HM.exists():
        with HM.open(encoding="utf-8", errors="replace") as f:
            for r in csv.DictReader(f):
                try:
                    pid = int(r["id"])
                except (TypeError, ValueError):
                    continue
                meta[pid] = r
    # corpus filter
    corpus: set[int] = set()
    if POSTERS.exists():
        with POSTERS.open(encoding="utf-8", errors="replace") as f:
            for r in csv.DictReader(f):
                try:
                    corpus.add(int(r["id"]))
                except (TypeError, ValueError):
                    continue
    out = []
    seen: set[int] = set()
    for r in rows:
        pid = r["old_id"]
        if pid in seen:
            continue
        if corpus and pid not in corpus:
            continue
        seen.add(pid)
        m = meta.get(pid, {})
        r["original_title"] = (m.get("original_title") or "").strip()
        try:
            r["runtime"] = int(float(m.get("runtime") or 0)) or ""
        except (TypeError, ValueError):
            r["runtime"] = ""
        if not r["title"]:
            r["title"] = (m.get("title") or "").strip()
        if r["year"] is None:
            r["year"] = year_int((m.get("release_date") or "")[:4])
        out.append(r)
    out.sort(key=lambda x: x["old_id"])
    if limit:
        out = out[:limit]
    return out


def _merge_auth(api_key: str, params: dict) -> dict:
    base = auth_kwargs(api_key)
    if "params" in base:
        return {"params": {**base["params"], **params}}
    return {**base, "params": params}


def search(
    session: requests.Session,
    api_key: str,
    kind: str,
    query: str,
    year: int | None,
) -> list[dict]:
    url = SEARCH_MOVIE if kind == "movie" else SEARCH_TV
    params: dict = {"query": query, "include_adult": "true"}
    if year is not None:
        if kind == "movie":
            params["year"] = year
            params["primary_release_year"] = year
        else:
            params["first_air_date_year"] = year
    kwargs = _merge_auth(api_key, params)
    for attempt in range(6):
        try:
            r = session.get(url, timeout=30, **kwargs)
        except requests.RequestException:
            time.sleep(1 + attempt)
            continue
        if r.status_code == 429:
            time.sleep(2 + attempt * 2)
            continue
        if not r.ok:
            time.sleep(1 + attempt)
            continue
        return list(r.json().get("results") or [])
    return []


def candidate_year(c: dict, kind: str) -> int | None:
    if kind == "movie":
        return year_int((c.get("release_date") or "")[:4])
    return year_int((c.get("first_air_date") or "")[:4])


def title_keys(row: dict) -> set[str]:
    keys = set()
    for raw in (row.get("title"), row.get("original_title")):
        n = normalize_title(raw or "")
        if n:
            keys.add(n)
    return keys


def exact_candidates(
    results: list[dict], kind: str, keys: set[str], old_id: int
) -> list[dict]:
    out = []
    seen: set[int] = set()
    for c in results:
        try:
            cid = int(c["id"])
        except (KeyError, TypeError, ValueError):
            continue
        if cid == old_id or cid in seen:
            continue
        if kind == "movie":
            names = {normalize_title(c.get("title") or ""), normalize_title(c.get("original_title") or "")}
        else:
            names = {normalize_title(c.get("name") or ""), normalize_title(c.get("original_name") or "")}
        names.discard("")
        if not (names & keys):
            continue
        seen.add(cid)
        out.append(c)
    return out


def score_row(
    row: dict,
    movies: list[dict],
    tvs: list[dict],
    corpus_ids: set[int],
) -> dict:
    old = row["old_id"]
    y = row["year"]
    keys = title_keys(row)
    base = {
        "old_id": old,
        "title": row["title"],
        "original_title": row.get("original_title") or "",
        "year": y if y is not None else "",
        "runtime": row.get("runtime") or "",
        "stored_path": row.get("stored_path") or "",
        "status": "miss",
        "new_kind": "",
        "new_id": "",
        "new_title": "",
        "new_year": "",
        "new_poster_path": "",
        "new_url": "",
        "candidates_n": 0,
        "in_corpus_already": "",
        "note": "",
    }
    if not keys:
        base["note"] = "empty_title"
        return base

    m_exact = exact_candidates(movies, "movie", keys, old)
    t_exact = exact_candidates(tvs, "tv", keys, old)

    def year_ok(c: dict, kind: str) -> str:
        cy = candidate_year(c, kind)
        if y is None:
            return "no_old_year"
        if cy is None:
            return "no_new_year"
        if cy == y:
            return "exact"
        if abs(cy - y) == 1:
            return "pm1"
        return "bad"

    # filter movies/tv by year when old year known: keep exact/pm1/no_new_year
    def filter_year(cands: list[dict], kind: str) -> tuple[list[dict], list[dict]]:
        """Return (strict, loose) where strict=exact year, loose=exact|pm1|missing new year."""
        if y is None:
            return cands, cands
        strict, loose = [], []
        for c in cands:
            q = year_ok(c, kind)
            if q == "exact":
                strict.append(c)
                loose.append(c)
            elif q in ("pm1", "no_new_year"):
                loose.append(c)
            # bad year dropped
        return strict, loose

    m_strict, m_loose = filter_year(m_exact, "movie")
    t_strict, t_loose = filter_year(t_exact, "tv")

    # Prefer unique strict movie
    pool_m = m_strict or m_loose
    pool_t = t_strict or t_loose
    n_cand = len(pool_m) + len(pool_t)
    base["candidates_n"] = n_cand

    if len(pool_m) + len(pool_t) == 0:
        base["note"] = (
            f"raw_movie={len(movies)} raw_tv={len(tvs)} "
            f"exact_m={len(m_exact)} exact_t={len(t_exact)} year_filtered=0"
        )
        return base

    if len(pool_m) > 1 or (len(pool_m) >= 1 and len(pool_t) >= 1) or (
        len(pool_m) == 0 and len(pool_t) > 1
    ):
        base["status"] = "ambig"
        bits = []
        for c in pool_m[:5]:
            bits.append(f"movie:{c['id']}")
        for c in pool_t[:5]:
            bits.append(f"tv:{c['id']}")
        base["note"] = ",".join(bits)
        return base

    if len(pool_m) == 1:
        c = pool_m[0]
        kind = "movie"
        yq = year_ok(c, kind)
        nid = int(c["id"])
        title = c.get("title") or c.get("original_title") or ""
        ny = candidate_year(c, kind)
        pp = c.get("poster_path") or ""
        if yq == "exact" and c in m_strict:
            status = "high"
        elif yq in ("exact", "pm1") or y is None:
            status = "medium"
        else:
            status = "low"
        note = f"year_{yq}"
        if not pp:
            note += ";no_poster"
            if status == "high":
                status = "medium"
    else:
        c = pool_t[0]
        kind = "tv"
        yq = year_ok(c, kind)
        nid = int(c["id"])
        title = c.get("name") or c.get("original_name") or ""
        ny = candidate_year(c, kind)
        pp = c.get("poster_path") or ""
        # TV remaps never auto-high (corpus is movie posters)
        status = "medium" if yq in ("exact", "pm1", "no_old_year") else "low"
        note = f"tv_year_{yq}"

    in_corpus = "1" if nid in corpus_ids and kind == "movie" else "0"
    if in_corpus == "1":
        note += ";new_id_already_in_corpus"
        if status == "high":
            status = "medium"

    if kind == "movie":
        url = f"https://www.themoviedb.org/movie/{nid}"
    else:
        url = f"https://www.themoviedb.org/tv/{nid}"

    base.update(
        {
            "status": status,
            "new_kind": kind,
            "new_id": nid,
            "new_title": title,
            "new_year": ny if ny is not None else "",
            "new_poster_path": pp,
            "new_url": url,
            "in_corpus_already": in_corpus,
            "note": note,
        }
    )
    return base


def gather_results(
    session: requests.Session, api_key: str, row: dict
) -> tuple[list[dict], list[dict]]:
    """Search movie+tv with year, then without year; merge unique by id."""
    q = row["title"] or row.get("original_title") or ""
    y = row["year"]
    movies: dict[int, dict] = {}
    tvs: dict[int, dict] = {}

    def add(dst: dict[int, dict], items: list[dict]):
        for c in items:
            try:
                dst[int(c["id"])] = c
            except (KeyError, TypeError, ValueError):
                pass

    if q:
        if y is not None:
            add(movies, search(session, api_key, "movie", q, y))
            add(tvs, search(session, api_key, "tv", q, y))
        add(movies, search(session, api_key, "movie", q, None))
        add(tvs, search(session, api_key, "tv", q, None))
        ot = row.get("original_title") or ""
        if ot and normalize_title(ot) != normalize_title(q):
            if y is not None:
                add(movies, search(session, api_key, "movie", ot, y))
                add(tvs, search(session, api_key, "tv", ot, y))
            add(movies, search(session, api_key, "movie", ot, None))
            add(tvs, search(session, api_key, "tv", ot, None))
    return list(movies.values()), list(tvs.values())


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--api-key", default=os.environ.get("TMDB_API_KEY"))
    ap.add_argument("--ids-file", type=Path, default=DEFAULT_IN)
    ap.add_argument("--out", type=Path, default=OUT)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--delay", type=float, default=0.05)
    args = ap.parse_args()
    if not args.api_key:
        raise SystemExit("Need TMDB_API_KEY or --api-key")

    targets = load_targets(args.ids_file, args.limit)
    print(f"not_found to remap: {len(targets):,}")
    if not targets:
        raise SystemExit("no targets")

    corpus_ids: set[int] = set()
    if POSTERS.exists():
        with POSTERS.open(encoding="utf-8", errors="replace") as f:
            for r in csv.DictReader(f):
                try:
                    corpus_ids.add(int(r["id"]))
                except (TypeError, ValueError):
                    continue

    session = requests.Session()
    adapter = requests.adapters.HTTPAdapter(
        pool_connections=args.workers, pool_maxsize=args.workers
    )
    session.mount("https://", adapter)

    results: dict[int, dict] = {}
    lock = threading.Lock()
    done = 0
    t0 = time.time()

    def work(row: dict) -> dict:
        movies, tvs = gather_results(session, args.api_key, row)
        if args.delay:
            time.sleep(args.delay)
        return score_row(row, movies, tvs, corpus_ids)

    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as ex:
        futs = [ex.submit(work, r) for r in targets]
        for fut in as_completed(futs):
            row = fut.result()
            with lock:
                results[int(row["old_id"])] = row
                done += 1
                if done % 25 == 0 or done == len(targets):
                    rate = done / max(time.time() - t0, 1e-6)
                    print(f"{done}/{len(targets)} {rate:.1f}/s", flush=True)

    fields = [
        "old_id",
        "title",
        "original_title",
        "year",
        "runtime",
        "stored_path",
        "status",
        "new_kind",
        "new_id",
        "new_title",
        "new_year",
        "new_poster_path",
        "new_url",
        "candidates_n",
        "in_corpus_already",
        "note",
    ]
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in targets:
            w.writerow(results[r["old_id"]])

    from collections import Counter

    counts = Counter(results[r["old_id"]]["status"] for r in targets)
    print("=== SUMMARY ===")
    for k in ("high", "medium", "low", "ambig", "miss"):
        print(f"  {k}: {counts.get(k, 0):,}")
    n_tv = sum(
        1
        for r in targets
        if results[r["old_id"]]["new_kind"] == "tv"
        and results[r["old_id"]]["status"] in ("high", "medium", "low")
    )
    n_collision = sum(
        1 for r in targets if results[r["old_id"]].get("in_corpus_already") == "1"
    )
    print(f"  tv remaps (any conf): {n_tv:,}")
    print(f"  new_id already in corpus: {n_collision:,}")
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()

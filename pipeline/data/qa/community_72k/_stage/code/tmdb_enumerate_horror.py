#!/usr/bin/env python3
"""Enumerate all TMDB horror (genre=27, non-adult) past Discover's 10k/page-500 cap.

Shards Discover by year; if a shard still has >10k results, splits by month,
then by vote_count bands, then by original_language.

  TMDB_API_KEY=... python3 tmdb_enumerate_horror.py
  python3 tmdb_enumerate_horror.py --out /tmp/tmdb_horror_ids.csv --progress /tmp/PROGRESS

Writes CSV columns:
  id,title,original_title,year,release_date,poster_path,original_language,
  popularity,vote_count,vote_average,adult,overview_snip,shard
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import time
from pathlib import Path

import requests

DISCOVER = "https://api.themoviedb.org/3/discover/movie"
HORROR = 27
HEADERS = {"User-Agent": "PulpAnalytics-WhatFearLooksLike/1.0-enumerate-horror"}
FIELDS = [
    "id",
    "title",
    "original_title",
    "year",
    "release_date",
    "poster_path",
    "original_language",
    "popularity",
    "vote_count",
    "vote_average",
    "adult",
    "overview_snip",
    "shard",
]
# Common langs to sub-shard hot years; residual = everything else via without_*
LANG_SHARDS = [
    "en", "ja", "ko", "zh", "es", "fr", "de", "it", "pt", "hi",
    "th", "id", "ru", "tr", "pl", "sv", "nl", "cs", "hu", "fi",
]
VOTE_BANDS = [
    (None, 0),       # vote_count.lte=0 (unvoted)
    (1, 10),
    (11, 50),
    (51, 200),
    (201, 1000),
    (1001, None),    # vote_count.gte=1001
]


def log(msg: str) -> None:
    print(msg, flush=True)


def get_api_key(explicit: str = "") -> str:
    if explicit.strip():
        return explicit.strip()
    env = (os.environ.get("TMDB_API_KEY") or "").strip()
    if env:
        return env
    for cand in (
        Path("data/qa/tmdb_api_key"),
        Path(__file__).resolve().parent / "data" / "qa" / "tmdb_api_key",
    ):
        if cand.exists():
            return cand.read_text(encoding="utf-8").strip()
    raise SystemExit("TMDB_API_KEY missing (env or data/qa/tmdb_api_key)")


def discover_page(
    session: requests.Session,
    api_key: str,
    page: int,
    extra: dict,
) -> dict:
    params = {
        "api_key": api_key,
        "with_genres": HORROR,
        "include_adult": "false",
        "sort_by": "primary_release_date.asc",
        "page": page,
        **extra,
    }
    for attempt in range(8):
        r = session.get(DISCOVER, params=params, headers=HEADERS, timeout=45)
        if r.status_code == 429:
            time.sleep(2 + attempt * 2)
            continue
        if r.status_code >= 500:
            time.sleep(1.5 * (attempt + 1))
            continue
        r.raise_for_status()
        return r.json()
    r.raise_for_status()
    return {}


def probe_total(session: requests.Session, api_key: str, extra: dict) -> int:
    j = discover_page(session, api_key, 1, extra)
    return int(j.get("total_results") or 0)


def row_from_result(m: dict, shard: str) -> dict:
    rd = (m.get("release_date") or "").strip()
    year = rd[:4] if len(rd) >= 4 and rd[:4].isdigit() else ""
    ov = (m.get("overview") or "").replace("\n", " ").strip()
    return {
        "id": int(m["id"]),
        "title": m.get("title") or "",
        "original_title": m.get("original_title") or "",
        "year": year,
        "release_date": rd,
        "poster_path": m.get("poster_path") or "",
        "original_language": m.get("original_language") or "",
        "popularity": m.get("popularity") or 0,
        "vote_count": m.get("vote_count") or 0,
        "vote_average": m.get("vote_average") or 0,
        "adult": bool(m.get("adult")),
        "overview_snip": ov[:160],
        "shard": shard,
    }


def fetch_all_pages(
    session: requests.Session,
    api_key: str,
    extra: dict,
    shard: str,
    seen: dict[int, dict],
    sleep_s: float = 0.025,
) -> tuple[int, int]:
    """Fetch up to 500 pages; return (n_added, total_results_reported)."""
    j = discover_page(session, api_key, 1, extra)
    total_results = int(j.get("total_results") or 0)
    total_pages = int(j.get("total_pages") or 1)
    added = 0

    def ingest(results: list) -> None:
        nonlocal added
        for m in results or []:
            try:
                pid = int(m["id"])
            except Exception:
                continue
            if pid in seen:
                continue
            seen[pid] = row_from_result(m, shard)
            added += 1

    ingest(j.get("results") or [])
    max_page = min(total_pages, 500)
    for page in range(2, max_page + 1):
        jj = discover_page(session, api_key, page, extra)
        ingest(jj.get("results") or [])
        if sleep_s:
            time.sleep(sleep_s)
        if page % 50 == 0:
            log(f"  {shard} page {page}/{max_page} unique={len(seen):,} (+{added})")
    if total_results > 10_000:
        log(f"  WARN {shard} total_results={total_results} > 10k — incomplete without sub-shards")
    return added, total_results


def vote_extra(lo: int | None, hi: int | None) -> dict:
    d: dict = {}
    if lo is not None:
        d["vote_count.gte"] = lo
    if hi is not None:
        d["vote_count.lte"] = hi
    return d


def enumerate_shard(
    session: requests.Session,
    api_key: str,
    base_extra: dict,
    shard_label: str,
    seen: dict[int, dict],
    depth: int = 0,
) -> None:
    total = probe_total(session, api_key, base_extra)
    log(f"shard {shard_label} total_results={total} depth={depth}")
    if total <= 0:
        return
    if total <= 10_000:
        fetch_all_pages(session, api_key, base_extra, shard_label, seen)
        return

    # Too big: try finer splits
    if depth == 0 and "primary_release_date.gte" in base_extra:
        # Split year into months
        gte = base_extra["primary_release_date.gte"]
        year = int(gte[:4])
        import calendar

        for month in range(1, 13):
            last = calendar.monthrange(year, month)[1]
            m_gte = f"{year}-{month:02d}-01"
            m_lte = f"{year}-{month:02d}-{last:02d}"
            extra = {
                **base_extra,
                "primary_release_date.gte": m_gte,
                "primary_release_date.lte": m_lte,
            }
            enumerate_shard(session, api_key, extra, f"{shard_label}/m{month:02d}", seen, depth=1)
        return

    if depth <= 1:
        # vote_count bands
        for lo, hi in VOTE_BANDS:
            label = f"{shard_label}/vc_{lo if lo is not None else 'min'}_{hi if hi is not None else 'max'}"
            extra = {**base_extra, **vote_extra(lo, hi)}
            enumerate_shard(session, api_key, extra, label, seen, depth=2)
        return

    # language shards + residual
    covered = 0
    for lang in LANG_SHARDS:
        extra = {**base_extra, "with_original_language": lang}
        t = probe_total(session, api_key, extra)
        if t <= 0:
            continue
        covered += t
        if t <= 10_000:
            fetch_all_pages(session, api_key, extra, f"{shard_label}/lang_{lang}", seen)
        else:
            # still huge — fetch what we can (first 10k) and warn
            log(f"  HARD CAP {shard_label}/lang_{lang} total={t} — fetching first 10k only")
            fetch_all_pages(session, api_key, extra, f"{shard_label}/lang_{lang}", seen)
    # residual: no language filter but we already got major langs; accept overlap via dedupe
    # Also fetch without lang filter if residual likely — but that re-hits 10k.
    # Instead rely on year/month/vote coverage; log gap estimate.
    log(f"  lang-shard covered≈{covered} of {total} for {shard_label} (dedupe handles overlap)")


def write_progress(path: Path | None, seen: dict[int, dict], extra: dict) -> None:
    if not path:
        return
    doc = {
        "unique_ids": len(seen),
        "with_poster_path": sum(1 for r in seen.values() if (r.get("poster_path") or "").startswith("/")),
        **extra,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--api-key", default="")
    ap.add_argument("--out", default="data/community/tmdb_horror_ids.csv")
    ap.add_argument("--progress", default="")
    ap.add_argument("--year-start", type=int, default=1870)
    ap.add_argument("--year-end", type=int, default=2030)
    ap.add_argument("--include-undated", action="store_true", default=True)
    ap.add_argument("--no-undated", action="store_true")
    ap.add_argument("--target", type=int, default=72531, help="expected TMDB total_results for logging")
    args = ap.parse_args()

    api_key = get_api_key(args.api_key)
    out = Path(args.out)
    progress = Path(args.progress) if args.progress else out.with_suffix(".progress.json")
    session = requests.Session()
    seen: dict[int, dict] = {}

    # Global probe
    global_total = probe_total(session, api_key, {})
    log(f"TMDB Discover genre=27 include_adult=false total_results={global_total} (target≈{args.target})")

    t0 = time.time()
    for year in range(args.year_start, args.year_end + 1):
        extra = {
            "primary_release_date.gte": f"{year}-01-01",
            "primary_release_date.lte": f"{year}-12-31",
        }
        enumerate_shard(session, api_key, extra, f"y{year}", seen, depth=0)
        if year % 5 == 0 or year == args.year_end:
            write_progress(
                progress,
                seen,
                {"phase": "years", "year": year, "elapsed_s": round(time.time() - t0, 1)},
            )
            log(f"checkpoint years through {year}: unique={len(seen):,}")

    gap = global_total - len(seen)
    if not args.no_undated and gap > 100:
        # Scoop undated / spillover only when year shards left a meaningful gap.
        log(f"--- residual sweep (gap≈{gap}) via vote bands without date filter ---")
        for lo, hi in VOTE_BANDS:
            label = f"nodate/vc_{lo if lo is not None else 'min'}_{hi if hi is not None else 'max'}"
            extra = vote_extra(lo, hi)
            enumerate_shard(session, api_key, extra, label, seen, depth=2)
    elif gap > 0:
        log(f"residual gap≈{gap} (skipping undated sweep; use --include-undated force via removing --no-undated)")

    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        for pid in sorted(seen):
            w.writerow(seen[pid])

    with_poster = sum(1 for r in seen.values() if (r.get("poster_path") or "").startswith("/"))
    write_progress(
        progress,
        seen,
        {
            "phase": "done",
            "out": str(out),
            "global_total_results": global_total,
            "target": args.target,
            "coverage_vs_global": round(len(seen) / max(global_total, 1), 4),
            "with_poster_path": with_poster,
            "elapsed_s": round(time.time() - t0, 1),
        },
    )
    log(
        f"DONE wrote {out} unique={len(seen):,} with_poster_path={with_poster:,} "
        f"global_total={global_total} coverage={len(seen)/max(global_total,1):.1%} "
        f"elapsed={time.time()-t0:.0f}s"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

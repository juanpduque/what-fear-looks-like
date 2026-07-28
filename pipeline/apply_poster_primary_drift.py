#!/usr/bin/env python3
"""Apply TMDB primary poster_path for drift mismatches.

For each corpus id where stored_path ≠ current API primary:
  1) archive current posters/{id}.jpg → posters_multi/{id}/{stem(stored)}.jpg
  2) download API primary → posters/{id}.jpg (+ copy into posters_multi)
  3) update horror_movies.csv + poster_paths_backfill.csv poster_path
  4) align multi_poster_catalog is_primary + multi_poster_canonical

Complementary variants stay under data/posters_multi/ for the multi-poster analysis.
Does NOT re-run vision metrics — see reanalyze_poster_ids.py.

  source ~/.zshrc
  python3 apply_poster_primary_drift.py --dry-run
  python3 apply_poster_primary_drift.py --limit 20
  python3 apply_poster_primary_drift.py              # all mismatches
  python3 apply_poster_primary_drift.py --live        # re-query TMDB before apply
"""
from __future__ import annotations

import argparse
import csv
import os
import shutil
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import pandas as pd
import requests

DATA = Path(__file__).resolve().parent / "data"
POSTERS = DATA / "posters"
MULTI = DATA / "posters_multi"
DRIFT = DATA / "poster_path_drift.csv"
BACKFILL = DATA / "poster_paths_backfill.csv"
HORROR = DATA / "horror_movies.csv"
CATALOG = DATA / "multi_poster_catalog.csv"
CANONICAL = DATA / "multi_poster_canonical.csv"
LOG = DATA / "qa" / "primary_drift_applied.csv"
IMG_BASE = "https://image.tmdb.org/t/p/w500"
HEADERS = {"User-Agent": "PulpAnalytics-WhatFearLooksLike/1.0-primary-drift"}


def _stem(file_path: str) -> str:
    return Path(str(file_path).lstrip("/")).stem


def _multi_path(pid: int, file_path: str) -> Path:
    return MULTI / str(pid) / f"{_stem(file_path)}.jpg"


def load_mismatches(limit: int = 0) -> pd.DataFrame:
    if not DRIFT.exists():
        raise SystemExit(f"falta {DRIFT} — corre validate_poster_paths.py primero")
    d = pd.read_csv(DRIFT)
    d["id"] = d["id"].astype(int)
    d = d[
        (d["status"].astype(str) == "ok")
        & (d["match"].astype(str).isin(["0", "0.0"]))
        & d["current_path"].astype(str).str.startswith("/")
        & d["stored_path"].astype(str).str.startswith("/")
    ].copy()
    # corpus only
    post_ids = set(pd.read_csv(DATA / "posters.csv", usecols=["id"])["id"].astype(int))
    d = d[d["id"].isin(post_ids)]
    d = d.drop_duplicates("id", keep="last").sort_values("id")
    if limit:
        d = d.head(limit)
    return d.reset_index(drop=True)


def refresh_live(df: pd.DataFrame, api_key: str, workers: int) -> pd.DataFrame:
    session = requests.Session()

    def one(pid: int):
        try:
            r = session.get(
                f"https://api.themoviedb.org/3/movie/{pid}",
                params={"api_key": api_key},
                timeout=30,
            )
        except Exception as e:
            return pid, None, f"err:{type(e).__name__}"
        if r.status_code == 429:
            time.sleep(2)
            return one(pid)
        if r.status_code != 200:
            return pid, None, f"http_{r.status_code}"
        path = r.json().get("poster_path") or ""
        if not path.startswith("/"):
            return pid, None, "no_poster"
        return pid, path, "ok"

    cur: dict[int, tuple[str, str]] = {}
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = [ex.submit(one, int(pid)) for pid in df["id"]]
        for i, fut in enumerate(as_completed(futs), 1):
            pid, path, status = fut.result()
            cur[pid] = (path or "", status)
            if i % 500 == 0 or i == len(futs):
                print(f"  live refresh {i}/{len(futs)}", flush=True)

    df = df.copy()
    df["current_path"] = df["id"].map(lambda i: cur.get(int(i), ("", ""))[0])
    df["live_status"] = df["id"].map(lambda i: cur.get(int(i), ("", ""))[1])
    before = len(df)
    df = df[
        (df["live_status"] == "ok")
        & df["current_path"].str.startswith("/")
        & (df["current_path"] != df["stored_path"])
    ]
    print(f"live: {before} → {len(df)} still mismatched vs stored")
    return df.reset_index(drop=True)


def download(session: requests.Session, file_path: str, dest: Path) -> bool:
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        r = session.get(IMG_BASE + file_path, headers=HEADERS, timeout=40)
        if r.status_code == 200 and len(r.content) > 2000:
            dest.write_bytes(r.content)
            return True
    except Exception:
        return False
    return False


def apply_one(
    row,
    session: requests.Session,
    dry_run: bool,
) -> dict:
    pid = int(row.id)
    stored = str(row.stored_path)
    current = str(row.current_path)
    primary = POSTERS / f"{pid}.jpg"
    multi_old = _multi_path(pid, stored)
    multi_new = _multi_path(pid, current)

    result = {
        "id": pid,
        "title": row.title,
        "year": row.year,
        "stored_path": stored,
        "current_path": current,
        "archived_old": 0,
        "downloaded": 0,
        "status": "ok",
        "detail": "",
    }

    if dry_run:
        result["status"] = "dry_run"
        result["detail"] = f"would archive→{multi_old.name} download→primary"
        return result

    # 1) archive old main into multi (complementary)
    if primary.exists() and primary.stat().st_size > 2000:
        if not multi_old.exists():
            multi_old.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(primary, multi_old)
            result["archived_old"] = 1
        elif multi_old.stat().st_size < 2000:
            shutil.copy2(primary, multi_old)
            result["archived_old"] = 1

    # 2) download API primary as new main (+ multi copy)
    ok_dl = download(session, current, primary)
    if not ok_dl:
        result["status"] = "download_fail"
        result["detail"] = current
        return result
    result["downloaded"] = 1
    # keep multi copy in sync with the new primary bytes
    multi_new.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(primary, multi_new)

    return result


def update_path_tables(applied: pd.DataFrame) -> None:
    """Point horror_movies + backfill at current_path for applied ids."""
    path_map = {
        int(r.id): str(r.current_path)
        for r in applied.itertuples(index=False)
        if r.status == "ok"
    }
    meta = {
        int(r.id): (r.title, r.year)
        for r in applied.itertuples(index=False)
    }
    if not path_map:
        return

    if HORROR.exists():
        hm = pd.read_csv(HORROR, low_memory=False)
        hm["id"] = hm["id"].astype(int)
        mask = hm["id"].isin(path_map)
        n = int(mask.sum())
        hm.loc[mask, "poster_path"] = hm.loc[mask, "id"].map(path_map)
        hm.to_csv(HORROR, index=False)
        print(f"horror_movies.csv: updated poster_path for {n:,} rows")

    bf: dict[int, dict] = {}
    if BACKFILL.exists():
        for r in csv.DictReader(BACKFILL.open(encoding="utf-8")):
            try:
                bf[int(r["id"])] = r
            except (TypeError, ValueError):
                pass
    for pid, path in path_map.items():
        title, year = meta.get(pid, ("", ""))
        prev = bf.get(pid, {})
        bf[pid] = {
            "id": pid,
            "poster_path": path,
            "title": prev.get("title") or title,
            "year": prev.get("year") or year,
        }
    fields = ["id", "poster_path", "title", "year"]
    with BACKFILL.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for pid in sorted(bf):
            w.writerow({k: bf[pid].get(k, "") for k in fields})
    print(f"poster_paths_backfill.csv: {len(bf):,} rows (upserted {len(path_map):,})")


def update_multi_tables(applied: pd.DataFrame) -> None:
    """Mark API primary as is_primary / canonical for applied ids."""
    path_map = {
        int(r.id): str(r.current_path)
        for r in applied.itertuples(index=False)
        if r.status == "ok"
    }
    if not path_map:
        return

    if CATALOG.exists():
        cat = pd.read_csv(CATALOG)
        cat["id"] = cat["id"].astype(int)
        touched = cat["id"].isin(path_map)
        # clear then set
        cat.loc[touched, "is_primary"] = 0
        for pid, path in path_map.items():
            m = (cat["id"] == pid) & (cat["file_path"] == path)
            if m.any():
                cat.loc[m, "is_primary"] = 1
            else:
                # primary not in catalog yet — append a row
                meta = applied[applied["id"] == pid].iloc[0]
                cat = pd.concat(
                    [
                        cat,
                        pd.DataFrame(
                            [
                                {
                                    "id": pid,
                                    "title": meta.title,
                                    "year": meta.year,
                                    "file_path": path,
                                    "iso_639_1": "",
                                    "vote_average": 0,
                                    "vote_count": 0,
                                    "width": 0,
                                    "height": 0,
                                    "is_primary": 1,
                                }
                            ]
                        ),
                    ],
                    ignore_index=True,
                )
        cat.to_csv(CATALOG, index=False)
        print(f"multi_poster_catalog.csv: realigned is_primary for {len(path_map):,} ids")

    if CANONICAL.exists():
        can = pd.read_csv(CANONICAL)
        can["id"] = can["id"].astype(int)
        mask = can["id"].isin(path_map)
        can.loc[mask, "canonical_path"] = can.loc[mask, "id"].map(path_map)
        can.loc[mask, "changed_from_primary"] = 0
        # ids in applied but not in canonical — skip (multi select incomplete)
        can.to_csv(CANONICAL, index=False)
        print(f"multi_poster_canonical.csv: set canonical=primary for {int(mask.sum()):,}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--live", action="store_true", help="re-query TMDB poster_path before apply")
    ap.add_argument("--api-key", default=os.environ.get("TMDB_API_KEY"))
    ap.add_argument("--workers", type=int, default=16)
    args = ap.parse_args()

    df = load_mismatches(args.limit)
    print(f"mismatches to apply: {len(df):,}")
    if not len(df):
        return

    if args.live:
        if not args.api_key:
            raise SystemExit("--live necesita TMDB_API_KEY o --api-key")
        df = refresh_live(df, args.api_key, args.workers)
        if not len(df):
            print("nada que aplicar tras refresh live")
            return

    session = requests.Session()
    rows = []
    t0 = time.time()

    def one(r):
        return apply_one(r, session, args.dry_run)

    with ThreadPoolExecutor(max_workers=1 if args.dry_run else args.workers) as ex:
        futs = [ex.submit(one, r) for r in df.itertuples(index=False)]
        for i, fut in enumerate(as_completed(futs), 1):
            rows.append(fut.result())
            if i % 200 == 0 or i == len(futs):
                rate = i / max(time.time() - t0, 1e-6)
                print(f"  apply {i}/{len(futs)} ({rate:.1f}/s)", flush=True)

    out = pd.DataFrame(rows).sort_values("id")
    LOG.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(LOG, index=False)

    ok = (out["status"] == "ok").sum()
    dry = (out["status"] == "dry_run").sum()
    fail = (out["status"] == "download_fail").sum()
    print(f"wrote {LOG}")
    print(f"ok={ok:,} dry_run={dry:,} download_fail={fail:,} archived={int(out.archived_old.sum()):,}")

    if args.dry_run:
        print("dry-run: no path tables updated")
        return

    applied_ok = out[out["status"] == "ok"]
    update_path_tables(applied_ok)
    update_multi_tables(applied_ok)

    ids_path = DATA / "qa" / "primary_drift_reanalyze_ids.csv"
    applied_ok[["id", "title", "year"]].to_csv(ids_path, index=False)
    print(f"reanalyze list → {ids_path} ({len(applied_ok):,} ids)")
    print("next: python3 reanalyze_poster_ids.py --ids-file data/qa/primary_drift_reanalyze_ids.csv")


if __name__ == "__main__":
    main()

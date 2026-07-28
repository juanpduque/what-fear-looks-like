#!/usr/bin/env python3
"""Migrate TMDB ids after remap gate ACCEPT (old 404 → new live movie id).

Reads data/qa/tmdb_remap_high_gate.csv (gate=ACCEPT*), for each row:
  - download new primary poster → posters/{new_id}.jpg
  - archive posters/{old_id}.jpg → posters_quarantine_tmdb_remap/
  - rewrite id old→new in per-poster CSVs + clip_embeddings.npz
  - upsert horror_movies / imdb_ids / poster_paths_backfill / drift

Does not re-analyze (JPG may change — run reanalyze_poster_ids.py after).

  python3 apply_tmdb_remap_migrate.py --dry-run
  python3 apply_tmdb_remap_migrate.py
"""
from __future__ import annotations

import argparse
import csv
import os
import shutil
import time
from pathlib import Path

import numpy as np
import pandas as pd
import requests

from enrich_imdb_ids import auth_kwargs, load_sidecar, write_sidecar

DATA = Path(__file__).resolve().parent / "data"
GATE = DATA / "qa" / "tmdb_remap_high_gate.csv"
POSTERS = DATA / "posters"
QUAR = DATA / "posters_quarantine_tmdb_remap"
IMG = "https://image.tmdb.org/t/p/w500"
HEADERS = {"User-Agent": "PulpAnalytics-WhatFearLooksLike/1.0-remap-migrate"}

CSV_ID_FILES = [
    "posters.csv",
    "attributes.csv",
    "attributes_partial.csv",
    "faces_v2.csv",
    "faces_v2_partial.csv",
    "census.csv",
    "typography.csv",
    "medium.csv",
    "segmentation.csv",
    "segmentation_partial.csv",
    "rekognition.csv",
    "title_boxes.csv",
    "title_boxes_rekognition.csv",
]


def load_accepts() -> list[dict]:
    if not GATE.exists():
        raise SystemExit(f"falta {GATE}")
    rows = []
    for r in csv.DictReader(GATE.open(encoding="utf-8")):
        if not str(r.get("gate") or "").startswith("ACCEPT"):
            continue
        if r.get("new_kind") and r["new_kind"] != "movie":
            continue
        if r.get("in_corpus_already") == "1":
            continue
        rows.append(
            {
                "old_id": int(r["old_id"]),
                "new_id": int(r["new_id"]),
                "title": r.get("title") or "",
                "new_poster_path": (r.get("live_new_poster") or r.get("new_poster_path") or "").strip(),
                "gate": r.get("gate") or "",
            }
        )
    # unique old, unique new
    by_old = {}
    for r in rows:
        by_old[r["old_id"]] = r
    rows = list(by_old.values())
    news = [r["new_id"] for r in rows]
    if len(news) != len(set(news)):
        raise SystemExit("new_id duplicado en accepts")
    return sorted(rows, key=lambda r: r["old_id"])


def download_poster(session: requests.Session, path: str, dest: Path) -> bool:
    if not path.startswith("/"):
        return False
    url = IMG + path
    for attempt in range(5):
        try:
            r = session.get(url, timeout=60, headers=HEADERS)
        except requests.RequestException:
            time.sleep(1 + attempt)
            continue
        if r.status_code == 429:
            time.sleep(2 + attempt * 2)
            continue
        if r.ok and r.content[:3] == b"\xff\xd8\xff":
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(r.content)
            return True
        if r.status_code == 404:
            return False
        time.sleep(1 + attempt)
    return False


def rewrite_csv_ids(path: Path, mapping: dict[int, int], dry: bool) -> int:
    if not path.exists():
        return 0
    d = pd.read_csv(path)
    if "id" not in d.columns:
        return 0
    d["id"] = d["id"].astype(int)
    mask = d["id"].isin(mapping)
    n = int(mask.sum())
    if n and not dry:
        d.loc[mask, "id"] = d.loc[mask, "id"].map(mapping)
        # if collision with existing new_id rows, drop old-mapped dup keep first
        d = d.drop_duplicates("id", keep="first")
        d.to_csv(path, index=False)
    return n


def rewrite_npz(path: Path, mapping: dict[int, int], dry: bool) -> int:
    if not path.exists():
        return 0
    z = np.load(path)
    ids = np.asarray(z["ids"]).astype(int)
    vecs = np.asarray(z["vecs"])
    n = 0
    new_ids = ids.copy()
    for i, pid in enumerate(ids):
        if pid in mapping:
            new_ids[i] = mapping[pid]
            n += 1
    if n and not dry:
        # drop duplicate ids if any (keep first)
        _, idx = np.unique(new_ids, return_index=True)
        idx = np.sort(idx)
        np.savez_compressed(path, ids=new_ids[idx], vecs=vecs[idx])
    return n


def update_horror_movies(mapping: dict[int, int], poster_paths: dict[int, str], dry: bool) -> None:
    path = DATA / "horror_movies.csv"
    if not path.exists():
        return
    d = pd.read_csv(path)
    d["id"] = d["id"].astype(int)
    # existing new ids
    existing_new = set(d["id"]) & set(mapping.values())
    rows_old = d[d["id"].isin(mapping)].copy()
    if dry:
        print(f"  horror_movies: would migrate {len(rows_old)} (skip {len(existing_new)} new already present)")
        return
    # drop rows that already have new_id
    d = d[~d["id"].isin(mapping.keys())]
    # re-add migrated rows with new id
    for _, r in rows_old.iterrows():
        old = int(r["id"])
        new = mapping[old]
        if new in set(d["id"].astype(int)):
            continue  # keep existing new row
        r = r.copy()
        r["id"] = new
        pp = poster_paths.get(new) or poster_paths.get(old) or r.get("poster_path")
        if pp:
            r["poster_path"] = pp
        d = pd.concat([d, pd.DataFrame([r])], ignore_index=True)
    d.to_csv(path, index=False)
    print(f"  horror_movies.csv: migrated {len(rows_old)} ids")


def update_sidecar(mapping: dict[int, int], dry: bool) -> None:
    m = load_sidecar()
    changed = 0
    for old, new in mapping.items():
        if old in m:
            if new not in m or not str(m.get(new) or "").startswith("tt"):
                m[new] = m[old]
            del m[old]
            changed += 1
    if changed and not dry:
        write_sidecar(m)
    print(f"  imdb_ids.csv: moved {changed}")


def update_backfill(mapping: dict[int, int], poster_paths: dict[int, str], dry: bool) -> None:
    path = DATA / "poster_paths_backfill.csv"
    if not path.exists():
        return
    rows = {}
    with path.open(encoding="utf-8") as f:
        for r in csv.DictReader(f):
            try:
                rows[int(r["id"])] = r
            except (TypeError, ValueError):
                pass
    for old, new in mapping.items():
        if old in rows:
            r = rows.pop(old)
            r["id"] = str(new)
            if poster_paths.get(new):
                r["poster_path"] = poster_paths[new]
            rows[new] = r
        elif new in poster_paths:
            rows[new] = {
                "id": str(new),
                "poster_path": poster_paths[new],
                "title": "",
                "year": "",
            }
    if not dry:
        with path.open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=["id", "poster_path", "title", "year"])
            w.writeheader()
            for pid in sorted(rows):
                w.writerow({k: rows[pid].get(k, "") for k in ["id", "poster_path", "title", "year"]})
    print(f"  poster_paths_backfill: upserted {len(mapping)}")


def update_drift(mapping: dict[int, int], poster_paths: dict[int, str], dry: bool) -> None:
    path = DATA / "poster_path_drift.csv"
    if not path.exists():
        return
    d = pd.read_csv(path)
    d["id"] = d["id"].astype(int)
    n = 0
    for old, new in mapping.items():
        mask = d["id"] == old
        if not mask.any():
            continue
        n += int(mask.sum())
        d.loc[mask, "id"] = new
        pp = poster_paths.get(new) or ""
        if pp:
            d.loc[mask, "stored_path"] = pp
            d.loc[mask, "current_path"] = pp
            d.loc[mask, "match"] = 1
            d.loc[mask, "status"] = "ok"
    if n and not dry:
        d = d.drop_duplicates("id", keep="last")
        d.to_csv(path, index=False)
    print(f"  poster_path_drift: migrated {n} rows")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--api-key", default=os.environ.get("TMDB_API_KEY"))
    ap.add_argument("--skip-download", action="store_true", help="reuse old JPG bytes under new id")
    args = ap.parse_args()

    accepts = load_accepts()
    print(f"ACCEPT to migrate: {len(accepts)}")
    if not accepts:
        return

    posts = set(pd.read_csv(DATA / "posters.csv", usecols=["id"])["id"].astype(int))
    mapping = {}
    for r in accepts:
        if r["old_id"] not in posts:
            print(f"  skip {r['old_id']}: not in posters")
            continue
        if r["new_id"] in posts:
            print(f"  skip {r['old_id']}→{r['new_id']}: new already in posters")
            continue
        mapping[r["old_id"]] = r["new_id"]
    print(f"will migrate: {len(mapping)}")
    if not mapping:
        return

    poster_paths = {
        r["new_id"]: r["new_poster_path"]
        for r in accepts
        if r["old_id"] in mapping and r["new_poster_path"].startswith("/")
    }

    session = requests.Session()
    QUAR.mkdir(exist_ok=True)
    ok_dl = 0
    reuse = 0
    fail = 0
    for old, new in mapping.items():
        src = POSTERS / f"{old}.jpg"
        dst = POSTERS / f"{new}.jpg"
        qdst = QUAR / f"{old}.jpg"
        pp = poster_paths.get(new, "")
        if args.dry_run:
            print(f"  dry {old}→{new} poster={pp or '(reuse local)'}")
            continue
        if src.exists() and not qdst.exists():
            shutil.copy2(src, qdst)
        got = False
        if not args.skip_download and pp:
            got = download_poster(session, pp, dst)
            if got:
                ok_dl += 1
        if not got:
            if src.exists():
                shutil.copy2(src, dst)
                reuse += 1
            else:
                fail += 1
                print(f"  FAIL no jpg for {old}→{new}")
                continue
        if src.exists():
            src.unlink()
    if not args.dry_run:
        print(f"posters: downloaded={ok_dl} reused_local={reuse} fail={fail}")

    print("rewriting CSV/NPZ ids…")
    for name in CSV_ID_FILES:
        n = rewrite_csv_ids(DATA / name, mapping, args.dry_run)
        if n:
            print(f"  {name}: {n}")
    n = rewrite_npz(DATA / "clip_embeddings.npz", mapping, args.dry_run)
    print(f"  clip_embeddings.npz: {n}")

    update_horror_movies(mapping, poster_paths, args.dry_run)
    update_sidecar(mapping, args.dry_run)
    update_backfill(mapping, poster_paths, args.dry_run)
    update_drift(mapping, poster_paths, args.dry_run)

    log = DATA / "qa" / "tmdb_remap_high_migrated.csv"
    if not args.dry_run:
        with log.open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=["old_id", "new_id", "title", "new_poster_path"])
            w.writeheader()
            for r in accepts:
                if r["old_id"] in mapping:
                    w.writerow(
                        {
                            "old_id": r["old_id"],
                            "new_id": r["new_id"],
                            "title": r["title"],
                            "new_poster_path": poster_paths.get(r["new_id"], ""),
                        }
                    )
        # drop migrated from remap backlog
        remap = DATA / "qa" / "tmdb_not_found_remap.csv"
        if remap.exists():
            rows = list(csv.DictReader(remap.open()))
            fields = list(rows[0].keys()) if rows else []
            keep = [r for r in rows if int(r["old_id"]) not in mapping]
            with remap.open("w", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=fields)
                w.writeheader()
                w.writerows(keep)
            print(f"pruned remap backlog −{len(rows)-len(keep)}")
        print(f"wrote {log}")
        print("next: python3 reanalyze_poster_ids.py --ids-file data/qa/tmdb_remap_high_migrated.csv")
        print("      (usa columna new_id — o regenera ids-file)")
    else:
        print("dry-run done")


if __name__ == "__main__":
    main()

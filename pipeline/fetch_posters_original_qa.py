#!/usr/bin/env python3
"""Download TMDB /original posters for corpus-filter QA ids and upload to S3.

Set: data/qa/corpus_filter_qa_ids.csv (~14k filtered EN horror under QA review).

  python3 fetch_posters_original_qa.py --limit 20          # smoke
  python3 fetch_posters_original_qa.py --workers 12        # full
  python3 fetch_posters_original_qa.py --skip-upload       # local only
  python3 fetch_posters_original_qa.py --upload-only       # sync existing local → S3

S3: s3://$BUCKET/posters_original/{id}.jpg
Local cache: data/posters_original/{id}.jpg
"""
from __future__ import annotations

import argparse
import csv
import os
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests

_thread_local = threading.local()


def _session() -> requests.Session:
    s = getattr(_thread_local, "session", None)
    if s is None:
        s = requests.Session()
        _thread_local.session = s
    return s

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
QA = DATA / "qa"
IDS = QA / "corpus_filter_qa_ids.csv"
OUT_DIR = DATA / "posters_original"
MANIFEST = QA / "posters_original_manifest.csv"
MISS = QA / "posters_original_miss.csv"
PRIMARY_OVR = QA / "corpus_filter_poster_primary_override.csv"

IMG_BASE = "https://image.tmdb.org/t/p/original"
HEADERS = {"User-Agent": "PulpAnalytics-WhatFearLooksLike/1.0-posters-original"}
BUCKET = os.environ.get("BUCKET", "aof-owlv2-102516364259")
S3_PREFIX = os.environ.get("S3_POSTERS_ORIGINAL_PREFIX", "posters_original")


def load_paths() -> dict[int, str]:
    paths: dict[int, str] = {}
    for src in (DATA / "horror_movies.csv", DATA / "poster_paths_backfill.csv"):
        if not src.exists():
            continue
        with src.open(encoding="utf-8", errors="replace") as f:
            for r in csv.DictReader(f):
                try:
                    pid = int(r["id"])
                except (KeyError, TypeError, ValueError):
                    continue
                p = (r.get("poster_path") or "").strip()
                if p.startswith("/") and pid not in paths:
                    paths[pid] = p
    if PRIMARY_OVR.exists():
        with PRIMARY_OVR.open(encoding="utf-8", errors="replace") as f:
            for r in csv.DictReader(f):
                try:
                    pid = int(r["id"])
                except (KeyError, TypeError, ValueError):
                    continue
                p = (r.get("primary_path") or "").strip()
                if p.startswith("/"):
                    paths[pid] = p
    return paths


def load_ids(ids_file: Path, limit: int | None) -> list[int]:
    ids: list[int] = []
    with ids_file.open(encoding="utf-8") as f:
        for r in csv.DictReader(f):
            ids.append(int(r["id"]))
            if limit and len(ids) >= limit:
                break
    return ids


def s3_uri(pid: int) -> str:
    return f"s3://{BUCKET}/{S3_PREFIX}/{pid}.jpg"


def upload_file(local: Path, pid: int) -> tuple[bool, str]:
    uri = s3_uri(pid)
    try:
        r = subprocess.run(
            ["aws", "s3", "cp", str(local), uri, "--only-show-errors"],
            capture_output=True,
            text=True,
            timeout=120,
        )
        if r.returncode != 0:
            return False, (r.stderr or r.stdout or "aws cp failed").strip()[:300]
        return True, uri
    except Exception as e:
        return False, str(e)[:300]


def download_one(
    pid: int,
    poster_path: str,
    *,
    force: bool,
) -> tuple[str, dict]:
    dest = OUT_DIR / f"{pid}.jpg"
    row = {
        "id": pid,
        "poster_path": poster_path,
        "bytes": 0,
        "status": "",
        "s3_uri": s3_uri(pid),
        "error": "",
    }
    if dest.exists() and dest.stat().st_size > 1000 and not force:
        row["bytes"] = dest.stat().st_size
        row["status"] = "exists"
        return "exists", row

    url = IMG_BASE + poster_path
    try:
        r = _session().get(url, headers=HEADERS, timeout=60)
        if r.status_code != 200 or not r.content or len(r.content) < 500:
            row["status"] = "http_error"
            row["error"] = f"status={r.status_code} bytes={len(r.content or b'')}"
            return "miss", row
        ctype = (r.headers.get("Content-Type") or "").lower()
        if "image" not in ctype and not poster_path.lower().endswith((".jpg", ".jpeg", ".png", ".webp")):
            # TMDB originals are usually jpeg; still accept opaque bodies
            pass
        tmp = dest.with_suffix(".partial")
        tmp.write_bytes(r.content)
        tmp.replace(dest)
        row["bytes"] = len(r.content)
        row["status"] = "downloaded"
        return "ok", row
    except Exception as e:
        row["status"] = "error"
        row["error"] = str(e)[:300]
        return "miss", row


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--workers", type=int, default=12)
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--skip-upload", action="store_true")
    ap.add_argument("--upload-only", action="store_true", help="upload local cache only")
    ap.add_argument("--ids-file", type=Path, default=IDS)
    args = ap.parse_args()

    ids_file = args.ids_file
    if not ids_file.exists():
        sys.exit(f"missing ids file: {ids_file}")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    ids = load_ids(ids_file, args.limit or None)
    paths = load_paths()
    print(f"ids={len(ids)} paths_lookup={len(paths)} out={OUT_DIR} s3=s3://{BUCKET}/{S3_PREFIX}/")

    manifest_rows: list[dict] = []
    miss_rows: list[dict] = []
    ok = exists = miss = uploaded = up_fail = 0

    if not args.upload_only:
        todo = []
        for pid in ids:
            pp = paths.get(pid)
            if not pp:
                miss += 1
                miss_rows.append(
                    {"id": pid, "poster_path": "", "status": "no_path", "error": "missing poster_path"}
                )
                continue
            todo.append((pid, pp))

        def work(item: tuple[int, str]):
            pid, pp = item
            return download_one(pid, pp, force=args.force)

        t0 = time.time()
        # Chunked so a killed process still leaves progress on disk (resume via exists).
        chunk = 500
        for start in range(0, len(todo), chunk):
            batch = todo[start : start + chunk]
            with ThreadPoolExecutor(max_workers=args.workers) as ex:
                futs = {ex.submit(work, it): it[0] for it in batch}
                done_batch = 0
                for fut in as_completed(futs):
                    done_batch += 1
                    kind, row = fut.result()
                    if kind == "ok":
                        ok += 1
                        manifest_rows.append(row)
                    elif kind == "exists":
                        exists += 1
                        manifest_rows.append(row)
                    else:
                        miss += 1
                        miss_rows.append(row)
            done = min(start + chunk, len(todo))
            print(
                f"  download {done}/{len(todo)} ok={ok} exists={exists} miss={miss} "
                f"{time.time()-t0:.0f}s",
                flush=True,
            )

    # Upload
    if not args.skip_upload:
        upload_ids = []
        if args.upload_only:
            upload_ids = [pid for pid in ids if (OUT_DIR / f"{pid}.jpg").exists()]
        else:
            upload_ids = [
                int(r["id"])
                for r in manifest_rows
                if r.get("status") in {"downloaded", "exists"}
            ]
            # also any previously downloaded for this id list
            for pid in ids:
                if (OUT_DIR / f"{pid}.jpg").exists() and pid not in upload_ids:
                    upload_ids.append(pid)

        print(f"upload n={len(upload_ids)} → s3://{BUCKET}/{S3_PREFIX}/", flush=True)
        t1 = time.time()

        def up(pid: int):
            local = OUT_DIR / f"{pid}.jpg"
            if not local.exists():
                return pid, False, "missing local"
            return pid, *upload_file(local, pid)

        with ThreadPoolExecutor(max_workers=max(4, args.workers // 2)) as ex:
            futs = [ex.submit(up, pid) for pid in upload_ids]
            done = 0
            for fut in as_completed(futs):
                done += 1
                pid, good, detail = fut.result()
                if good:
                    uploaded += 1
                else:
                    up_fail += 1
                    miss_rows.append(
                        {
                            "id": pid,
                            "poster_path": paths.get(pid, ""),
                            "status": "upload_fail",
                            "error": detail,
                        }
                    )
                if done % 200 == 0 or done == len(futs):
                    print(
                        f"  upload {done}/{len(futs)} ok={uploaded} fail={up_fail} "
                        f"{time.time()-t1:.0f}s",
                        flush=True,
                    )

    # Write manifests
    fields = ["id", "poster_path", "bytes", "status", "s3_uri", "error"]
    with MANIFEST.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for r in sorted(manifest_rows, key=lambda x: int(x["id"])):
            w.writerow(r)
    with MISS.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["id", "poster_path", "status", "error"], extrasaction="ignore")
        w.writeheader()
        for r in miss_rows:
            w.writerow(r)

    print(
        f"LISTO ok={ok} exists={exists} miss={miss} uploaded={uploaded} up_fail={up_fail}\n"
        f"  local={OUT_DIR}\n"
        f"  s3=s3://{BUCKET}/{S3_PREFIX}/\n"
        f"  manifest={MANIFEST}\n"
        f"  miss={MISS}"
    )


if __name__ == "__main__":
    main()

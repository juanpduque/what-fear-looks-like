#!/usr/bin/env python3
"""Build all-lang TMDB horror gap (with poster) for DetectText community set.

Universe: horror_movies.csv ids NOT already in poster_ocr_rek_text.csv.
Keep only titles that have a poster (local jpg OR TMDB poster_path).
Download missing jpgs into data/posters/{id}.jpg.

Writes:
  data/qa/rek_text_alllang_ids.txt
  data/qa/rek_text_alllang_manifest.csv

  python3 prepare_rek_text_alllang.py
  python3 prepare_rek_text_alllang.py --download-workers 16
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

DATA = Path(__file__).resolve().parent / "data"
QA = DATA / "qa"
POSTERS = DATA / "posters"
HM = DATA / "horror_movies.csv"
BACKFILL = DATA / "poster_paths_backfill.csv"
DONE = DATA / "poster_ocr_rek_text.csv"
IDS_OUT = QA / "rek_text_alllang_ids.txt"
MANIFEST = QA / "rek_text_alllang_manifest.csv"
IMG_BASE = "https://image.tmdb.org/t/p/original"
HEADERS = {"User-Agent": "PulpAnalytics-WhatFearLooksLike/1.0-rek-alllang"}

_thread_local = threading.local()
_print_lock = threading.Lock()


def log(msg: str) -> None:
    with _print_lock:
        print(msg, flush=True)


def session() -> requests.Session:
    s = getattr(_thread_local, "session", None)
    if s is None:
        s = requests.Session()
        _thread_local.session = s
    return s


def load_done() -> set[int]:
    out: set[int] = set()
    if not DONE.exists():
        return out
    with DONE.open(encoding="utf-8", errors="replace") as f:
        for r in csv.DictReader(f):
            try:
                out.add(int(r["id"]))
            except Exception:
                pass
    return out


def load_horror_ids() -> set[int]:
    ids: set[int] = set()
    with HM.open(encoding="utf-8", errors="replace") as f:
        for r in csv.DictReader(f):
            try:
                ids.add(int(float(r["id"])))
            except Exception:
                pass
    return ids


def load_paths() -> dict[int, str]:
    paths: dict[int, str] = {}
    for src in (HM, BACKFILL):
        if not src.exists():
            continue
        with src.open(encoding="utf-8", errors="replace") as f:
            for r in csv.DictReader(f):
                try:
                    pid = int(float(r["id"]))
                except Exception:
                    continue
                p = (r.get("poster_path") or "").strip()
                if p.startswith("/") and pid not in paths:
                    paths[pid] = p
    return paths


def local_poster(pid: int) -> Path | None:
    for ext in (".jpg", ".jpeg", ".png", ".webp"):
        p = POSTERS / f"{pid}{ext}"
        if p.exists() and p.stat().st_size > 0:
            return p
    return None


def fetch_path_from_tmdb(api_key: str, pid: int) -> str | None:
    url = f"https://api.themoviedb.org/3/movie/{pid}"
    try:
        r = session().get(url, params={"api_key": api_key}, headers=HEADERS, timeout=30)
        if r.status_code == 404:
            return None
        r.raise_for_status()
        p = (r.json() or {}).get("poster_path") or ""
        return p if isinstance(p, str) and p.startswith("/") else None
    except Exception:
        return None


def download_one(pid: int, poster_path: str) -> tuple[str, str]:
    dest = POSTERS / f"{pid}.jpg"
    if dest.exists() and dest.stat().st_size > 0:
        return "exists", ""
    url = IMG_BASE + poster_path
    try:
        r = session().get(url, headers=HEADERS, timeout=60)
        if r.status_code != 200:
            return "http_error", f"status={r.status_code}"
        ctype = (r.headers.get("Content-Type") or "").lower()
        if "image" not in ctype and not poster_path.lower().endswith((".jpg", ".jpeg", ".png", ".webp")):
            return "bad_ctype", ctype[:40]
        if len(r.content) < 500:
            return "too_small", str(len(r.content))
        POSTERS.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_suffix(".jpg.part")
        tmp.write_bytes(r.content)
        tmp.replace(dest)
        return "ok", ""
    except Exception as e:
        return "error", f"{type(e).__name__}: {e}"[:180]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--download-workers", type=int, default=16)
    ap.add_argument("--resolve-missing-path", action="store_true", help="TMDB API for ids without poster_path")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    api_key = (os.environ.get("TMDB_API_KEY") or "").strip()
    done = load_done()
    horror = load_horror_ids()
    paths = load_paths()
    gap = sorted(horror - done)
    if args.limit > 0:
        gap = gap[: args.limit]

    log(f"horror={len(horror):,} detecttext_done={len(done):,} gap={len(gap):,}")

    have_local: list[int] = []
    need_dl: list[tuple[int, str]] = []
    need_path: list[int] = []
    for pid in gap:
        if local_poster(pid):
            have_local.append(pid)
            continue
        p = paths.get(pid)
        if p:
            need_dl.append((pid, p))
        else:
            need_path.append(pid)

    log(f"local={len(have_local):,} need_download={len(need_dl):,} no_path={len(need_path):,}")

    if args.resolve_missing_path and need_path:
        if not api_key:
            raise SystemExit("TMDB_API_KEY required for --resolve-missing-path")
        log(f"resolving poster_path via TMDB API for {len(need_path):,}…")
        resolved = 0
        with ThreadPoolExecutor(max_workers=8) as ex:
            futs = {ex.submit(fetch_path_from_tmdb, api_key, pid): pid for pid in need_path}
            still: list[int] = []
            for i, fut in enumerate(as_completed(futs), 1):
                pid = futs[fut]
                p = fut.result()
                if p:
                    paths[pid] = p
                    need_dl.append((pid, p))
                    resolved += 1
                else:
                    still.append(pid)
                if i % 200 == 0 or i == len(futs):
                    log(f"  path resolve {i}/{len(futs)} resolved={resolved}")
            need_path = still
        log(f"path resolve done resolved={resolved} still_no_path={len(need_path):,}")

    manifest_rows: list[dict] = []
    for pid in have_local:
        manifest_rows.append(
            {"id": pid, "poster_path": paths.get(pid, ""), "status": "local", "error": ""}
        )

    if need_dl:
        log(f"downloading {len(need_dl):,} posters → {POSTERS} workers={args.download_workers}")
        t0 = time.time()
        ok = fail = 0
        with ThreadPoolExecutor(max_workers=max(1, args.download_workers)) as ex:
            futs = {ex.submit(download_one, pid, p): (pid, p) for pid, p in need_dl}
            for i, fut in enumerate(as_completed(futs), 1):
                pid, p = futs[fut]
                status, err = fut.result()
                if status in ("ok", "exists"):
                    ok += 1
                    have_local.append(pid)
                else:
                    fail += 1
                manifest_rows.append(
                    {"id": pid, "poster_path": p, "status": status, "error": err}
                )
                if i % 200 == 0 or i == len(futs):
                    rate = i / max(time.time() - t0, 1e-6)
                    log(f"  dl {i}/{len(futs)} ok={ok} fail={fail} {rate:.1f}/s")
        log(f"download done ok={ok} fail={fail}")

    for pid in need_path:
        manifest_rows.append(
            {"id": pid, "poster_path": "", "status": "no_path", "error": "missing poster_path"}
        )

    # Final OCR ids: gap ids that now have a local poster
    ocr_ids = sorted({pid for pid in gap if local_poster(pid)})
    QA.mkdir(parents=True, exist_ok=True)
    IDS_OUT.write_text("\n".join(str(i) for i in ocr_ids) + ("\n" if ocr_ids else ""), encoding="utf-8")
    with MANIFEST.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["id", "poster_path", "status", "error"])
        w.writeheader()
        for r in sorted(manifest_rows, key=lambda x: int(x["id"])):
            w.writerow(r)

    log(f"wrote {IDS_OUT} n={len(ocr_ids):,}")
    log(f"wrote {MANIFEST} n={len(manifest_rows):,}")
    log(f"skipped_no_poster={len(gap) - len(ocr_ids):,}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

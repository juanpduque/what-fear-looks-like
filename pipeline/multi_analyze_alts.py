#!/usr/bin/env python3
"""OpenCV composition stack on TMDB alternative sheets.

Fetches w500 by file_path, runs the same REGISTRY as multi_analyze.py
(composition, typography, grid, aesthetic, diagonal). Writes a sidecar
keyed by (id, file_path). Does not touch data/attributes.csv.

  python3 multi_analyze_alts.py --jobs-file data/qa/alts_comp_catalog/jobs.csv
  python3 multi_analyze_alts.py --jobs-file jobs.csv --out /data/out/attributes_multi_variants.csv
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import threading
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import cv2
import numpy as np
import requests

import multi_analyze as ma

TMDB = "https://image.tmdb.org/t/p/w500"
DATA = Path(__file__).resolve().parent / "data"
OUT = DATA / "qa" / "attributes_multi_variants.csv"
ANALYSIS_WIDTH = ma.ANALYSIS_WIDTH

METRIC_KEYS = list(ma.REGISTRY)
METRIC_COLS = [c for k in METRIC_KEYS for c in ma.METRIC_COLS[k]]

FIELDS = [
    "id",
    "year",
    "file_path",
    "tmdb_hash",
    "sha256",
    "bytes",
    "status",
    "error",
    *METRIC_COLS,
    "latency_s",
]

_print_lock = threading.Lock()
_write_lock = threading.Lock()
_tls = threading.local()


def log(msg: str) -> None:
    with _print_lock:
        print(msg, flush=True)


def tmdb_path(raw: str) -> str:
    raw = (raw or "").strip()
    if raw.startswith("/") and raw.lower().endswith(".jpg"):
        return raw
    name = Path(raw).name
    return f"/{name}" if name.lower().endswith(".jpg") else ""


def tmdb_hash(file_path: str) -> str:
    name = Path(str(file_path or "").lstrip("/")).name
    return name[:-4] if name.lower().endswith(".jpg") else name


def sess() -> requests.Session:
    if not hasattr(_tls, "s"):
        _tls.s = requests.Session()
        _tls.s.headers["User-Agent"] = "what-fear-looks-like/alts-comp"
    return _tls.s


def empty_row(pid: int, year: str, fp: str, **extra) -> dict:
    row = {k: "" for k in FIELDS}
    row.update(id=pid, year=year, file_path=fp, tmdb_hash=tmdb_hash(fp))
    row.update(extra)
    return row


def analyze_bytes(data: bytes) -> dict:
    arr = np.frombuffer(data, dtype=np.uint8)
    bgr = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if bgr is None:
        raise RuntimeError("cv2.imdecode returned None")
    h, w = bgr.shape[:2]
    if w <= 0:
        raise RuntimeError("empty image")
    s = ANALYSIS_WIDTH / w
    bgr = cv2.resize(bgr, (ANALYSIS_WIDTH, max(1, int(h * s))))
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    out = {}
    for k in METRIC_KEYS:
        out.update(ma.REGISTRY[k](bgr, gray))
    return out


def process_one(job: tuple[int, str, str]) -> dict:
    pid, year, fp = job
    t0 = time.perf_counter()
    cv2.setNumThreads(1)
    row = empty_row(pid, year, fp, status="", error="", bytes=0, sha256="")
    url = TMDB + fp
    try:
        r = sess().get(url, timeout=60)
        if r.status_code == 404:
            row.update(
                status="missing_404",
                error="missing_404",
                latency_s=round(time.perf_counter() - t0, 3),
            )
            return row
        r.raise_for_status()
        data = r.content
        if len(data) < 500:
            row.update(
                status="too_small",
                error="too_small",
                bytes=len(data),
                latency_s=round(time.perf_counter() - t0, 3),
            )
            return row
        sha = hashlib.sha256(data).hexdigest()
        metrics = analyze_bytes(data)
        row.update(metrics)
        row.update(
            sha256=sha,
            bytes=len(data),
            status="ok",
            error="",
            latency_s=round(time.perf_counter() - t0, 3),
        )
        return row
    except Exception as e:
        row.update(
            status="error",
            error=f"{type(e).__name__}: {e}"[:240],
            latency_s=round(time.perf_counter() - t0, 3),
        )
        return row


def load_jobs(path: Path, limit: int) -> list[tuple[int, str, str]]:
    jobs: list[tuple[int, str, str]] = []
    with path.open(encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            try:
                pid = int(r["id"])
            except (KeyError, TypeError, ValueError):
                continue
            fp = tmdb_path(r.get("file_path") or "")
            if not fp:
                continue
            year = str(r.get("year") or "").strip()
            jobs.append((pid, year, fp))
            if limit and len(jobs) >= limit:
                break
    return jobs


def load_done(path: Path, force: bool) -> dict[tuple[int, str], dict]:
    if force or not path.exists():
        return {}
    out: dict[tuple[int, str], dict] = {}
    with path.open(encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            try:
                pid = int(r["id"])
            except (KeyError, TypeError, ValueError):
                continue
            fp = tmdb_path(r.get("file_path") or "")
            if not fp:
                continue
            if r.get("status") in {"ok", "missing_404"}:
                out[(pid, fp)] = r
    return out


def write_rows(path: Path, rows: dict[tuple[int, str], dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".part")
    with _write_lock:
        with tmp.open("w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore")
            w.writeheader()
            for k in sorted(rows, key=lambda x: (x[0], x[1])):
                w.writerow(rows[k])
        tmp.replace(path)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--jobs-file", required=True)
    ap.add_argument("--out", default="")
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--flush-every", type=int, default=100)
    args = ap.parse_args()

    cv2.setNumThreads(1)
    out_path = Path(args.out) if args.out else OUT
    jobs = load_jobs(Path(args.jobs_file), args.limit)
    done = load_done(out_path, args.force)
    todo = [j for j in jobs if (j[0], j[2]) not in done]
    log(
        f"jobs={len(jobs)} todo={len(todo)} done={len(done)} "
        f"workers={args.workers} out={out_path} metrics={','.join(METRIC_KEYS)}"
    )
    if not todo:
        write_rows(out_path, done)
        log("nothing to do")
        return 0

    n_ok = n_404 = n_err = 0
    t0 = time.time()
    pending = 0
    with ProcessPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(process_one, j): j for j in todo}
        for fut in as_completed(futs):
            row = fut.result()
            key = (int(row["id"]), str(row["file_path"]))
            done[key] = row
            st = row.get("status")
            if st == "ok":
                n_ok += 1
            elif st == "missing_404":
                n_404 += 1
            else:
                n_err += 1
            pending += 1
            if pending >= args.flush_every:
                write_rows(out_path, done)
                rate = (n_ok + n_404 + n_err) / max(time.time() - t0, 1e-9)
                log(
                    f"  checkpoint +{pending} ok={n_ok} 404={n_404} err={n_err} "
                    f"have={len(done)}/{len(jobs)} {rate:.1f}/s"
                )
                pending = 0
    write_rows(out_path, done)
    rate = (n_ok + n_404 + n_err) / max(time.time() - t0, 1e-9)
    log(
        f"done ok={n_ok} 404={n_404} err={n_err} have={len(done)}/{len(jobs)} "
        f"{rate:.1f}/s out={out_path}"
    )
    if n_err >= 50 and n_err >= max(n_ok, 1) * 5:
        log(f"FATAL fail rate too high ok={n_ok} err={n_err}")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

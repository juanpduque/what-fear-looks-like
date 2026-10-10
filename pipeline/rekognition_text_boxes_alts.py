#!/usr/bin/env python3
"""Rekognition DetectText LINE boxes on TMDB alternative sheets.

Keyed by (id, file_path). Does not rewrite rekognition_text_boxes.csv of the
measured cover.

  python3 rekognition_text_boxes_alts.py --jobs-file data/qa/alts_comp_catalog/jobs.csv \\
      --out /tmp/rekognition_text_boxes_alts.csv
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import boto3
import requests
from botocore.config import Config
from botocore.exceptions import ClientError

from rekognition_utils import REKOGNITION_MAX_BYTES, load_image_bytes_for_rekognition

TMDB = "https://image.tmdb.org/t/p/w500"
REGION = "us-east-1"
FIELDS = [
    "id",
    "file_path",
    "tmdb_hash",
    "sha256",
    "n_lines",
    "lines",
    "full_text",
    "status",
    "error",
]

_print_lock = threading.Lock()
_rate_lock = threading.Lock()
_next_slot = 0.0


def log(msg: str) -> None:
    with _print_lock:
        print(msg, flush=True)


def acquire(min_interval: float) -> None:
    global _next_slot
    with _rate_lock:
        now = time.monotonic()
        slot = max(now, _next_slot)
        _next_slot = slot + min_interval
        wait = slot - now
    if wait > 0:
        time.sleep(wait)


def tmdb_path(raw: str) -> str:
    raw = (raw or "").strip()
    if raw.startswith("/") and raw.lower().endswith(".jpg"):
        return raw
    name = Path(raw).name
    return f"/{name}" if name.lower().endswith(".jpg") else ""


def tmdb_hash(file_path: str) -> str:
    name = Path(str(file_path or "").lstrip("/")).name
    return name[:-4] if name.lower().endswith(".jpg") else name


def load_jobs(path: Path, limit: int) -> list[tuple[int, str]]:
    jobs: list[tuple[int, str]] = []
    with path.open(encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            try:
                pid = int(r["id"])
            except (KeyError, TypeError, ValueError):
                continue
            fp = tmdb_path(r.get("file_path") or "")
            if not fp:
                continue
            jobs.append((pid, fp))
            if limit and len(jobs) >= limit:
                break
    return jobs


def load_done(path: Path) -> set[tuple[int, str]]:
    if not path.exists() or path.stat().st_size == 0:
        return set()
    out: set[tuple[int, str]] = set()
    with path.open(encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            try:
                pid = int(r["id"])
            except (KeyError, TypeError, ValueError):
                continue
            fp = tmdb_path(r.get("file_path") or "")
            if fp and (r.get("status") or "") in {"ok", "missing_404"}:
                out.add((pid, fp))
    return out


def empty_row(pid: int, fp: str, **extra) -> dict:
    row = {k: "" for k in FIELDS}
    row.update(id=pid, file_path=fp, tmdb_hash=tmdb_hash(fp), n_lines=0, lines="[]")
    row.update(extra)
    return row


def parse(resp: dict) -> list:
    lines = []
    for d in resp.get("TextDetections") or []:
        if d.get("Type") != "LINE":
            continue
        bb = (d.get("Geometry") or {}).get("BoundingBox") or {}
        x = max(0.0, min(1.0, float(bb.get("Left", 0))))
        y = max(0.0, min(1.0, float(bb.get("Top", 0))))
        w = max(0.0, min(1.0 - x, float(bb.get("Width", 0))))
        h = max(0.0, min(1.0 - y, float(bb.get("Height", 0))))
        if w <= 0 or h <= 0:
            continue
        lines.append(
            {
                "text": d.get("DetectedText", ""),
                "conf": round(float(d.get("Confidence") or 0), 1),
                "box": [round(x, 4), round(y, 4), round(w, 4), round(h, 4)],
            }
        )
    return lines


def detect_text(client, data: bytes, min_interval: float) -> list:
    if len(data) > REKOGNITION_MAX_BYTES:
        tmp = Path("/tmp/_rek_text_alts.jpg")
        tmp.write_bytes(data)
        data = load_image_bytes_for_rekognition(tmp)
        try:
            tmp.unlink()
        except OSError:
            pass
    last = None
    for attempt in range(6):
        acquire(min_interval)
        try:
            return parse(client.detect_text(Image={"Bytes": data}))
        except ClientError as e:
            last = e
            code = e.response.get("Error", {}).get("Code", "")
            if code in ("ThrottlingException", "ProvisionedThroughputExceededException") and attempt < 5:
                time.sleep(min(20, 1.5 * (2**attempt)))
                continue
            raise
    raise last  # type: ignore[misc]


def process(client, pid: int, fp: str, cache: Path, min_interval: float, keep_jpg: bool) -> dict:
    dest = cache / f"{pid}_{tmdb_hash(fp)}.jpg"
    try:
        if dest.exists() and dest.stat().st_size > 500:
            data = dest.read_bytes()
        else:
            r = requests.get(TMDB + fp, timeout=60)
            if r.status_code == 404:
                return empty_row(pid, fp, status="missing_404", error="missing_404")
            r.raise_for_status()
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(r.content)
            data = r.content
        lines = detect_text(client, data, min_interval)
        return empty_row(
            pid,
            fp,
            sha256=hashlib.sha256(data).hexdigest(),
            n_lines=len(lines),
            lines=json.dumps(lines, ensure_ascii=False, separators=(",", ":")),
            full_text=" ".join(l["text"] for l in lines)[:2000],
            status="ok",
            error="",
        )
    except Exception as e:
        return empty_row(pid, fp, status="error", error=f"{type(e).__name__}: {e}"[:240])
    finally:
        if not keep_jpg:
            try:
                dest.unlink(missing_ok=True)
            except OSError:
                pass


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--jobs-file", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--cache-dir", default="/tmp/alts_text")
    ap.add_argument("--checkpoint-every", type=int, default=25)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--min-interval", type=float, default=0.15)
    ap.add_argument("--region", default=REGION)
    ap.add_argument("--keep-jpg", action="store_true")
    args = ap.parse_args()

    jobs = load_jobs(Path(args.jobs_file), args.limit)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    cache = Path(args.cache_dir)
    cache.mkdir(parents=True, exist_ok=True)
    done = load_done(out)
    todo = [j for j in jobs if j not in done]
    log(f"jobs={len(jobs)} todo={len(todo)} done={len(done)} workers={args.workers}")

    client = boto3.client(
        "rekognition",
        region_name=args.region,
        config=Config(retries={"max_attempts": 8, "mode": "adaptive"}),
    )

    new_file = not out.exists() or out.stat().st_size == 0
    write_lock = threading.Lock()
    f_out = out.open("a", newline="", encoding="utf-8")
    writer = csv.DictWriter(f_out, fieldnames=FIELDS, extrasaction="ignore")
    if new_file:
        writer.writeheader()
        f_out.flush()

    t0 = time.time()
    n_ok = n_404 = n_err = n_done = 0

    def one(job: tuple[int, str]) -> dict:
        return process(client, job[0], job[1], cache, args.min_interval, args.keep_jpg)

    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as ex:
        futs = [ex.submit(one, j) for j in todo]
        for fut in as_completed(futs):
            row = fut.result()
            with write_lock:
                writer.writerow(row)
                n_done += 1
                st = row.get("status") or ""
                if st == "ok":
                    n_ok += 1
                elif st == "missing_404":
                    n_404 += 1
                else:
                    n_err += 1
                    if n_err <= 8:
                        log(f"  FAIL {row.get('id')} {row.get('file_path')}: {row.get('error')}")
                if n_done % args.checkpoint_every == 0 or n_done == len(todo):
                    f_out.flush()
                    rate = n_done / max(time.time() - t0, 1e-9)
                    log(
                        f"  {n_done:,}/{len(todo):,} ok={n_ok} 404={n_404} err={n_err} {rate:.2f}/s"
                    )
    f_out.close()
    log(f"LISTO ok={n_ok} 404={n_404} err={n_err}")
    if n_err >= 50 and n_err >= max(n_ok, 1) * 5:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

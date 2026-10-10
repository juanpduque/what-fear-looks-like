#!/usr/bin/env python3
"""YuNet face boxes on TMDB alternative sheets.

Keyed by (id, file_path). Does not rewrite faces_v2.csv of the measured cover.

  python3 yunet_alts.py --jobs-file data/qa/alts_comp_catalog/jobs.csv --out /tmp/faces_alts.csv
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import cv2
import numpy as np
import requests

TMDB = "https://image.tmdb.org/t/p/w500"
HERE = Path(__file__).resolve().parent
MODEL = HERE / "models" / "face_detection_yunet_2023mar.onnx"
W = 320
CONF = 0.6
FIELDS = [
    "id",
    "file_path",
    "tmdb_hash",
    "sha256",
    "n_faces",
    "face_area",
    "max_conf",
    "face_boxes",
    "status",
    "error",
]

_WORKER_DET = None


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
    row.update(id=pid, file_path=fp, tmdb_hash=tmdb_hash(fp), n_faces=0, face_area=0.0, max_conf=0.0)
    row.update(extra)
    return row


def make_detector():
    if not MODEL.exists():
        raise SystemExit(f"missing YuNet model: {MODEL}")
    return cv2.FaceDetectorYN.create(str(MODEL), "", (W, W), CONF, 0.3, 5000)


def _pool_init():
    global _WORKER_DET
    _WORKER_DET = make_detector()


def detect_bytes(det, data: bytes) -> dict:
    arr = np.frombuffer(data, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        return dict(n_faces=0, face_area=0.0, max_conf=0.0, face_boxes="", status="error", error="decode")
    h, w = img.shape[:2]
    s = W / w
    img = cv2.resize(img, (W, int(h * s)))
    ih, iw = img.shape[:2]
    det.setInputSize((iw, ih))
    _, faces = det.detect(img)
    if faces is None:
        return dict(n_faces=0, face_area=0.0, max_conf=0.0, face_boxes="", status="ok", error="")
    area = float(sum(f[2] * f[3] for f in faces) / (ih * iw))
    boxes = []
    for f in faces:
        boxes.append(
            [
                round(float(f[0]) / iw, 4),
                round(float(f[1]) / ih, 4),
                round(float(f[2]) / iw, 4),
                round(float(f[3]) / ih, 4),
            ]
        )
    boxes.sort(key=lambda b: b[2] * b[3], reverse=True)
    boxes_s = "|".join(f"{x},{y},{bw},{bh}" for x, y, bw, bh in boxes)
    return dict(
        n_faces=len(faces),
        face_area=round(area, 4),
        max_conf=round(float(faces[:, -1].max()), 3),
        face_boxes=boxes_s,
        status="ok",
        error="",
    )


def _worker(item: tuple[int, str]) -> dict:
    pid, fp = item
    try:
        r = requests.get(TMDB + fp, timeout=60)
        if r.status_code == 404:
            return empty_row(pid, fp, status="missing_404", error="missing_404")
        r.raise_for_status()
        data = r.content
        out = empty_row(pid, fp, sha256=hashlib.sha256(data).hexdigest())
        out.update(detect_bytes(_WORKER_DET, data))
        return out
    except Exception as e:
        return empty_row(pid, fp, status="error", error=f"{type(e).__name__}: {e}"[:240])


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--jobs-file", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--checkpoint-every", type=int, default=50)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--workers", type=int, default=6)
    args = ap.parse_args()

    jobs = load_jobs(Path(args.jobs_file), args.limit)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    done = load_done(out)
    todo = [j for j in jobs if j not in done]
    print(f"jobs={len(jobs)} todo={len(todo)} done={len(done)} workers={args.workers}", flush=True)

    new_file = not out.exists() or out.stat().st_size == 0
    f_out = out.open("a", newline="", encoding="utf-8")
    writer = csv.DictWriter(f_out, fieldnames=FIELDS, extrasaction="ignore")
    if new_file:
        writer.writeheader()
        f_out.flush()

    t0 = time.time()
    n_ok = n_404 = n_err = n_done = 0
    workers = max(1, int(args.workers))
    with ProcessPoolExecutor(max_workers=workers, initializer=_pool_init) as ex:
        futs = {ex.submit(_worker, j): j for j in todo}
        for fut in as_completed(futs):
            row = fut.result()
            writer.writerow(row)
            st = row.get("status") or ""
            if st == "ok":
                n_ok += 1
            elif st == "missing_404":
                n_404 += 1
            else:
                n_err += 1
            n_done += 1
            if n_done % args.checkpoint_every == 0 or n_done == len(todo):
                f_out.flush()
                rate = n_done / max(time.time() - t0, 1e-9)
                print(
                    f"  {n_done:,}/{len(todo):,} ok={n_ok} 404={n_404} err={n_err} {rate:.2f}/s",
                    flush=True,
                )
    f_out.close()
    print(f"LISTO ok={n_ok} 404={n_404} err={n_err}", flush=True)
    if n_err >= 50 and n_err >= max(n_ok, 1) * 5:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

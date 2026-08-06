#!/usr/bin/env python3
"""EasyOCR full-text extraction for corpus posters.

Reads every line/word EasyOCR finds on the poster (not just the title box)
and writes a resumable CSV:

  data/poster_ocr.csv
  data/poster_ocr_partial.csv   (checkpoint)

Columns:
  id, full_ocr, n_lines, n_boxes, mean_conf, error

Usage:
  python3 poster_ocr.py --limit 20                 # smoke
  python3 poster_ocr.py                            # resume full corpus
  python3 poster_ocr.py --gpu                      # CUDA if available
  python3 poster_ocr.py --ids 578,948
  python3 poster_ocr.py --force                    # redo existing rows

Designed for EC2 (see aws/poster_ocr_chain.sh): checkpoints every --save-every
rows so a halt/restart resumes from partial.
"""
from __future__ import annotations

import argparse
import csv
import sys
import time
from pathlib import Path

import cv2
import numpy as np
import pandas as pd

DATA = Path(__file__).resolve().parent / "data"
POSTERS = DATA / "posters"
OUT = DATA / "poster_ocr.csv"
PARTIAL = DATA / "poster_ocr_partial.csv"
POSTERS_CSV = DATA / "posters.csv"

_READER = None


def _cuda_ok() -> bool:
    try:
        import torch

        return bool(torch.cuda.is_available())
    except Exception:
        return False


def _reader(gpu: bool):
    global _READER
    if _READER is None:
        import easyocr

        use_gpu = bool(gpu and _cuda_ok())
        print(f"EasyOCR init gpu={use_gpu}", flush=True)
        _READER = easyocr.Reader(["en"], gpu=use_gpu, verbose=False)
    return _READER


def load_done(force: bool) -> dict[int, dict]:
    if force:
        return {}
    out: dict[int, dict] = {}
    for path in (OUT, PARTIAL):
        if not path.exists():
            continue
        with path.open(encoding="utf-8", errors="replace") as f:
            for r in csv.DictReader(f):
                try:
                    pid = int(r["id"])
                except (KeyError, TypeError, ValueError):
                    continue
                out[pid] = r
    return out


def write_rows(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = ["id", "full_ocr", "n_lines", "n_boxes", "mean_conf", "error"]
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for r in sorted(rows, key=lambda x: int(x["id"])):
            w.writerow(r)


def corpus_ids(ids_arg: str, limit: int) -> list[int]:
    if ids_arg:
        return [int(x) for x in ids_arg.split(",") if x.strip()]
    if not POSTERS_CSV.exists():
        raise SystemExit(f"falta {POSTERS_CSV}")
    ids = (
        pd.read_csv(POSTERS_CSV, usecols=["id"])["id"]
        .astype(int)
        .drop_duplicates()
        .tolist()
    )
    if limit > 0:
        ids = ids[:limit]
    return ids


def _s3_client():
    import boto3

    region = __import__("os").environ.get("AWS_DEFAULT_REGION", "us-east-1")
    return boto3.client("s3", region_name=region)


def fetch_poster(
    pid: int,
    posters_dir: Path,
    *,
    s3_bucket: str = "",
    s3_prefix: str = "",
) -> Path | None:
    """Return local jpg path; optionally download from S3 if missing."""
    path = posters_dir / f"{pid}.jpg"
    if path.exists():
        return path
    if not s3_bucket:
        return None
    key = f"{s3_prefix.rstrip('/')}/{pid}.jpg" if s3_prefix else f"{pid}.jpg"
    posters_dir.mkdir(parents=True, exist_ok=True)
    try:
        _s3_client().download_file(s3_bucket, key, str(path))
    except Exception:
        return None
    return path if path.exists() else None


def ocr_one(path: Path, gpu: bool) -> dict:
    img = cv2.imread(str(path))
    if img is None:
        return {
            "full_ocr": "",
            "n_lines": 0,
            "n_boxes": 0,
            "mean_conf": "",
            "error": "imread_fail",
        }
    reader = _reader(gpu)
    try:
        # detail=1 → (bbox, text, conf); paragraph=False keeps line tokens
        res = reader.readtext(str(path), detail=1, paragraph=False)
    except Exception as e:
        return {
            "full_ocr": "",
            "n_lines": 0,
            "n_boxes": 0,
            "mean_conf": "",
            "error": f"easyocr:{type(e).__name__}",
        }

    # Sort roughly reading-order: top→bottom, left→right
    ordered: list[tuple[float, float, str, float]] = []
    for item in res or []:
        if not item or len(item) < 3:
            continue
        text = (item[1] or "").strip()
        if not text:
            continue
        try:
            conf = float(item[2])
        except (TypeError, ValueError):
            conf = 0.0
        box = item[0]
        try:
            ys = [p[1] for p in box]
            xs = [p[0] for p in box]
            cy, cx = float(np.mean(ys)), float(np.mean(xs))
        except Exception:
            cy, cx = 0.0, 0.0
        ordered.append((cy, cx, text, conf))
    ordered.sort(key=lambda t: (round(t[0] / 12) * 12, t[1]))

    full = " ".join(t[2] for t in ordered)
    full = " ".join(full.split())
    if len(full) > 4000:
        full = full[:4000]

    confs = [t[3] for t in ordered]
    mean_conf = round(float(np.mean(confs)), 4) if confs else ""
    return {
        "full_ocr": full,
        "n_lines": len(ordered),
        "n_boxes": len(ordered),
        "mean_conf": mean_conf,
        "error": "",
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--ids", default="", help="comma-separated TMDB ids")
    ap.add_argument("--limit", type=int, default=0, help="first N corpus ids")
    ap.add_argument("--force", action="store_true", help="redo existing rows")
    ap.add_argument("--gpu", action="store_true", help="use CUDA if available")
    ap.add_argument("--save-every", type=int, default=50)
    ap.add_argument("--posters-dir", type=Path, default=POSTERS)
    ap.add_argument(
        "--s3-bucket",
        default="",
        help="if set, download missing jpgs from s3://bucket/prefix/{id}.jpg",
    )
    ap.add_argument(
        "--s3-prefix",
        default="poster_ocr/posters",
        help="S3 key prefix for posters (default: poster_ocr/posters)",
    )
    ap.add_argument(
        "--unlink-after",
        action="store_true",
        help="delete local jpg after OCR (keeps disk small on tiny EC2)",
    )
    args = ap.parse_args()

    ids = corpus_ids(args.ids, args.limit)
    done = load_done(args.force)
    rows: dict[int, dict] = {
        pid: {
            "id": pid,
            "full_ocr": r.get("full_ocr") or "",
            "n_lines": r.get("n_lines") or 0,
            "n_boxes": r.get("n_boxes") or 0,
            "mean_conf": r.get("mean_conf") or "",
            "error": r.get("error") or "",
        }
        for pid, r in done.items()
    }

    todo = [pid for pid in ids if pid not in rows]
    print(
        f"corpus={len(ids):,} done={len(rows):,} todo={len(todo):,} "
        f"gpu_flag={args.gpu} cuda={_cuda_ok()} "
        f"s3={args.s3_bucket or '-'}",
        flush=True,
    )

    t0 = time.time()
    n_ok = 0
    for i, pid in enumerate(todo, 1):
        path = fetch_poster(
            pid,
            args.posters_dir,
            s3_bucket=args.s3_bucket,
            s3_prefix=args.s3_prefix,
        )
        if path is None:
            row = {
                "id": pid,
                "full_ocr": "",
                "n_lines": 0,
                "n_boxes": 0,
                "mean_conf": "",
                "error": "missing_jpg",
            }
        else:
            out = ocr_one(path, args.gpu)
            row = {"id": pid, **out}
            if not out["error"]:
                n_ok += 1
            if args.unlink_after:
                try:
                    path.unlink(missing_ok=True)
                except TypeError:
                    if path.exists():
                        path.unlink()

        rows[pid] = row
        if i % 10 == 0 or i == len(todo):
            rate = i / max(time.time() - t0, 1e-6)
            eta = (len(todo) - i) / max(rate, 1e-6)
            preview = (row.get("full_ocr") or "")[:60]
            print(
                f"  {i}/{len(todo)} id={pid} lines={row.get('n_lines')} "
                f"err={row.get('error') or '-'} "
                f"{rate:.2f}/s eta={eta/3600:.1f}h | {preview!r}",
                flush=True,
            )
        if i % args.save_every == 0:
            write_rows(PARTIAL, list(rows.values()))
            print(f"  checkpoint → {PARTIAL} ({len(rows):,})", flush=True)

    write_rows(PARTIAL, list(rows.values()))
    write_rows(OUT, list(rows.values()))
    elapsed = time.time() - t0
    print(
        f"done: wrote {OUT} n={len(rows):,} new_ok={n_ok:,} "
        f"elapsed={elapsed/60:.1f}m",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())

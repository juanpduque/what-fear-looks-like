#!/usr/bin/env python3
"""Backfill Rekognition DetectFaces BoundingBoxes for YuNet-miss posters.

Reads poster images from S3 (preferred) or local disk, calls DetectFaces,
and writes face boxes in the same normalized format as faces_v2
(x,y,w,h normalized 0–1, pipe-separated).

Default id list: data/qa/gap_yunet0_rek_faces_ids.txt (~10.5k).

Usage:
  export AWS_PROFILE=sandbox_bedrock
  export AWS_DEFAULT_REGION=us-east-1
  export S3_BUCKET=wflike-workshop-posters-633183588025

  # dry-run sample
  python3 rekognition_face_boxes_backfill.py --sample 20 --dry-run

  # after posters are on S3
  python3 rekognition_face_boxes_backfill.py --workers 8

  # local files (USB) if S3 not ready
  python3 rekognition_face_boxes_backfill.py --local-dir "/Volumes/Adata Bituan/what-fear-looks-like-data/posters"

Cost: ~$0.001 / image DetectFaces → ~$10.5 for full gap.
"""
from __future__ import annotations

import argparse
import json
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import boto3
import pandas as pd
from botocore.exceptions import ClientError

HERE = Path(__file__).resolve().parent
DATA = HERE / "data"
QA = DATA / "qa"
OUT = DATA / "rekognition_face_boxes.csv"
CHECKPOINT = DATA / "rekognition_face_boxes_checkpoint.json"

REGION = os.environ.get("AWS_DEFAULT_REGION", "us-east-1")
BUCKET = os.environ.get("S3_BUCKET", "wflike-workshop-posters-633183588025")
PREFIX = os.environ.get("S3_PREFIX", "posters")


def _rek():
    return boto3.client("rekognition", region_name=REGION)


def _s3():
    return boto3.client("s3", region_name=REGION)


def boxes_from_details(details: list) -> tuple[int, str, float]:
    """Return n_faces, face_boxes string, max_conf."""
    if not details:
        return 0, "", 0.0
    parts = []
    max_conf = 0.0
    for f in details:
        bb = f.get("BoundingBox") or {}
        left = float(bb.get("Left", 0))
        top = float(bb.get("Top", 0))
        w = float(bb.get("Width", 0))
        h = float(bb.get("Height", 0))
        conf = float(f.get("Confidence") or 0) / 100.0
        max_conf = max(max_conf, conf)
        # clamp like YuNet export
        left = max(0.0, min(1.0, left))
        top = max(0.0, min(1.0, top))
        w = max(0.0, min(1.0 - left, w))
        h = max(0.0, min(1.0 - top, h))
        if w <= 0 or h <= 0:
            continue
        parts.append(f"{left:.4f},{top:.4f},{w:.4f},{h:.4f}")
    return len(parts), "|".join(parts), round(max_conf, 4)


def detect_one(pid: int, *, local_dir: Path | None, use_s3: bool) -> dict:
    rek = _rek()
    image = None
    src = ""
    if use_s3:
        try:
            image = {
                "S3Object": {
                    "Bucket": BUCKET,
                    "Name": f"{PREFIX}/{pid}.jpg",
                }
            }
            src = "s3"
            resp = rek.detect_faces(Image=image, Attributes=["DEFAULT"])
        except ClientError as e:
            # fall through to local if available
            if local_dir is None:
                return {
                    "id": pid,
                    "n_faces": 0,
                    "face_boxes": "",
                    "max_conf": 0.0,
                    "src": "s3_err",
                    "error": str(e),
                }
            image = None
    if image is None and local_dir is not None:
        path = local_dir / f"{pid}.jpg"
        if not path.is_file():
            return {
                "id": pid,
                "n_faces": 0,
                "face_boxes": "",
                "max_conf": 0.0,
                "src": "missing",
                "error": "file_not_found",
            }
        data = path.read_bytes()
        resp = rek.detect_faces(Image={"Bytes": data}, Attributes=["DEFAULT"])
        src = "local"
    elif image is None:
        return {
            "id": pid,
            "n_faces": 0,
            "face_boxes": "",
            "max_conf": 0.0,
            "src": "no_source",
            "error": "no_s3_or_local",
        }
    else:
        # already have resp from s3 branch success
        pass

    details = resp.get("FaceDetails") or []
    n, boxes, conf = boxes_from_details(details)
    return {
        "id": pid,
        "n_faces": n,
        "face_boxes": boxes,
        "max_conf": conf,
        "src": src,
        "error": "",
    }


def load_ids(path: Path) -> list[int]:
    return [int(x) for x in path.read_text().split() if x.strip().isdigit()]


def load_done() -> set[int]:
    if not OUT.exists():
        return set()
    df = pd.read_csv(OUT)
    if "id" not in df.columns:
        return set()
    # treat rows without error as done
    if "error" in df.columns:
        ok = df[df["error"].fillna("").astype(str) == ""]
        return set(ok["id"].astype(int))
    return set(df["id"].astype(int))


def append_rows(rows: list[dict]):
    df = pd.DataFrame(rows)
    if OUT.exists():
        df.to_csv(OUT, mode="a", header=False, index=False)
    else:
        df.to_csv(OUT, index=False)


def main():
    global OUT
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--ids-file",
        default=str(QA / "gap_yunet0_rek_faces_ids.txt"),
    )
    ap.add_argument("--sample", type=int, default=0)
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--local-dir", default="")
    ap.add_argument("--no-s3", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--save-every", type=int, default=50)
    ap.add_argument("--out", default=str(OUT))
    args = ap.parse_args()
    OUT = Path(args.out)

    ids = load_ids(Path(args.ids_file))
    done = load_done()
    todo = [i for i in ids if i not in done]
    if args.sample:
        todo = todo[: args.sample]
    local_dir = Path(args.local_dir) if args.local_dir else None
    use_s3 = not args.no_s3

    print(f"ids={len(ids)} done={len(done)} todo={len(todo)}")
    print(f"bucket={BUCKET} prefix={PREFIX} region={REGION}")
    print(f"use_s3={use_s3} local_dir={local_dir}")
    print(f"out={OUT}")
    if args.dry_run:
        print("dry-run sample:", todo[:10])
        return

    t0 = time.time()
    buf: list[dict] = []
    ok = err = 0
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {
            ex.submit(detect_one, pid, local_dir=local_dir, use_s3=use_s3): pid
            for pid in todo
        }
        for n, fut in enumerate(as_completed(futs), 1):
            row = fut.result()
            buf.append(row)
            if row.get("error"):
                err += 1
            else:
                ok += 1
            if len(buf) >= args.save_every:
                append_rows(buf)
                buf = []
                rate = n / max(1e-6, time.time() - t0)
                print(
                    f"[{n}/{len(todo)}] ok={ok} err={err} {rate:.1f}/s "
                    f"eta={(len(todo)-n)/max(rate,1e-6)/60:.1f}m",
                    flush=True,
                )
    if buf:
        append_rows(buf)
    print(f"DONE ok={ok} err={err} → {OUT}")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Rekognition DetectLabels with instance BoundingBoxes (person, weapon, animal, …).

The original rekognition_enrich.py kept only label scores; this run keeps every
label instance box so the autopsy can draw them.

Output: data/rekognition_label_boxes.csv
  id, n_instances, instances (JSON list of {label, conf, box:[x,y,w,h]}),
  labels (JSON list of {label, conf} without boxes), src, error

Each row is appended immediately. Resume skips only ids with an empty error,
so failed calls are retried on the next run. If the posters dir becomes
unreadable (USB drop), the run stops instead of recording false misses.

Usage:
  export AWS_PROFILE=sandbox_bedrock AWS_DEFAULT_REGION=us-east-1
  python3 rekognition_label_boxes.py --ids-file data/qa/site_ids.txt \
      --local-dir "/Volumes/Adata Bituan/what-fear-looks-like-data/posters" --workers 6

Cost: ~$0.001 / image.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import boto3
from botocore.exceptions import ClientError

from rekognition_utils import load_image_bytes_for_rekognition

HERE = Path(__file__).resolve().parent
DATA = HERE / "data"
OUT = DATA / "rekognition_label_boxes.csv"

REGION = os.environ.get("AWS_DEFAULT_REGION", "us-east-1")
BUCKET = os.environ.get("S3_BUCKET", "wflike-workshop-posters-633183588025")
PREFIX = os.environ.get("S3_PREFIX", "posters")

FIELDS = ["id", "n_instances", "instances", "labels", "src", "error"]
_lock = threading.Lock()
_local = threading.local()


def _rek():
    if not hasattr(_local, "rek"):
        _local.rek = boto3.client("rekognition", region_name=REGION)
    return _local.rek


def load_done(path: Path) -> set[int]:
    if not path.exists():
        return set()
    done = set()
    with path.open(encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if not r.get("error"):
                try:
                    done.add(int(r["id"]))
                except (KeyError, ValueError):
                    pass
    return done


def append_row(path: Path, row: dict) -> None:
    with _lock:
        new = not path.exists()
        with path.open("a", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=FIELDS)
            if new:
                w.writeheader()
            w.writerow(row)


def _call(image: dict) -> dict:
    for attempt in range(5):
        try:
            return _rek().detect_labels(Image=image, MaxLabels=50, MinConfidence=50)
        except ClientError as e:
            code = e.response.get("Error", {}).get("Code", "")
            if code in ("ThrottlingException", "ProvisionedThroughputExceededException") and attempt < 4:
                time.sleep(1.5 * (attempt + 1))
                continue
            raise


def parse(resp: dict) -> tuple[list, list]:
    instances, labels = [], []
    for lab in resp.get("Labels") or []:
        name = lab.get("Name", "")
        labels.append({"label": name, "conf": round(float(lab.get("Confidence") or 0), 1)})
        for inst in lab.get("Instances") or []:
            bb = inst.get("BoundingBox") or {}
            x = max(0.0, min(1.0, float(bb.get("Left", 0))))
            y = max(0.0, min(1.0, float(bb.get("Top", 0))))
            w = max(0.0, min(1.0 - x, float(bb.get("Width", 0))))
            h = max(0.0, min(1.0 - y, float(bb.get("Height", 0))))
            if w <= 0 or h <= 0:
                continue
            instances.append({
                "label": name,
                "conf": round(float(inst.get("Confidence") or 0), 1),
                "box": [round(x, 4), round(y, 4), round(w, 4), round(h, 4)],
            })
    return instances, labels


def process(pid: int, local_dir: Path | None, use_s3: bool) -> dict:
    row = {"id": pid, "n_instances": 0, "instances": "", "labels": "", "src": "", "error": ""}
    image = None
    if local_dir is not None:
        path = local_dir / f"{pid}.jpg"
        try:
            if path.is_file():
                image = {"Bytes": load_image_bytes_for_rekognition(path)}
                row["src"] = "local"
        except OSError as e:
            raise SystemExit(f"posters dir unreadable ({e}); stopping so resume can pick up")
    if image is None and use_s3:
        image = {"S3Object": {"Bucket": BUCKET, "Name": f"{PREFIX}/{pid}.jpg"}}
        row["src"] = "s3"
    if image is None:
        row["error"] = "no_source"
        return row
    try:
        resp = _call(image)
    except Exception as e:
        row["error"] = str(e)[:300]
        return row
    instances, labels = parse(resp)
    row["n_instances"] = len(instances)
    row["instances"] = json.dumps(instances, ensure_ascii=False, separators=(",", ":"))
    row["labels"] = json.dumps(labels, ensure_ascii=False, separators=(",", ":"))
    return row


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ids-file", required=True)
    ap.add_argument("--out", default=str(OUT))
    ap.add_argument("--local-dir", default="")
    ap.add_argument("--no-s3", action="store_true")
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    out = Path(args.out)
    local_dir = Path(args.local_dir) if args.local_dir else None
    if local_dir is not None and not local_dir.is_dir():
        raise SystemExit(f"posters dir missing: {local_dir}")

    ids = [int(x) for x in Path(args.ids_file).read_text().split() if x.strip().isdigit()]
    done = load_done(out)
    todo = [i for i in ids if i not in done]
    if args.limit:
        todo = todo[: args.limit]
    print(f"ids={len(ids)} done={len(done)} todo={len(todo)} out={out}", flush=True)

    t0 = time.time()
    ok = err = 0
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = [ex.submit(process, pid, local_dir, not args.no_s3) for pid in todo]
        for n, fut in enumerate(as_completed(futs), 1):
            row = fut.result()
            append_row(out, row)
            if row["error"]:
                err += 1
            else:
                ok += 1
            if n % 100 == 0 or n == len(todo):
                rate = n / max(1e-6, time.time() - t0)
                print(f"[{n}/{len(todo)}] ok={ok} err={err} {rate:.1f}/s "
                      f"eta={(len(todo) - n) / max(rate, 1e-6) / 60:.1f}m", flush=True)
    print(f"DONE ok={ok} err={err} -> {out}")


if __name__ == "__main__":
    main()

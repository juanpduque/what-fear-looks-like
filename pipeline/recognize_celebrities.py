#!/usr/bin/env python3
"""Celebrity recognition (AWS Rekognition RecognizeCelebrities) over posters with a detected face.

Reads local posters (pipeline/data/posters/{id}.jpg), targets ids with n_faces > 0
in faces_v2.csv. Writes each result to disk immediately (no batching) — designed
for a hard time limit where the process may be killed at any moment.

Usage:
  export AWS_PROFILE=sandbox
  python3 recognize_celebrities.py --workers 10
  python3 recognize_celebrities.py --resume   # skip ids already in OUT
"""
from __future__ import annotations

import argparse
import csv
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import boto3
import pandas as pd
from botocore.exceptions import ClientError

DATA = Path(__file__).parent / "data"
POSTERS = DATA / "posters"
FACES = DATA / "faces_v2.csv"
OUT = DATA / "celebrities.csv"
REGION = "us-east-1"

FIELDS = ["id", "n_celebs", "names", "max_match_conf", "urls", "boxes", "error"]

_write_lock = threading.Lock()


def _rek_client():
    return boto3.client("rekognition", region_name=REGION)


def load_done() -> set[int]:
    if not OUT.exists():
        return set()
    done = set()
    with OUT.open(encoding="utf-8", errors="replace") as f:
        for r in csv.DictReader(f):
            try:
                done.add(int(r["id"]))
            except (KeyError, TypeError, ValueError):
                continue
    return done


def append_row(row: dict) -> None:
    """Append one result immediately — no batching, safe under a hard deadline."""
    new_file = not OUT.exists()
    with _write_lock:
        with OUT.open("a", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=FIELDS)
            if new_file:
                w.writeheader()
            w.writerow(row)


def process_one(rek, pid: int) -> dict:
    img_path = POSTERS / f"{pid}.jpg"
    try:
        if not img_path.exists():
            return {"id": pid, "n_celebs": 0, "names": "", "max_match_conf": 0.0,
                    "urls": "", "error": "no_local_poster"}
        img_bytes = img_path.read_bytes()
    except OSError as e:
        raise SystemExit(f"posters dir unreadable ({e}); stopping so --resume can pick up")
    try:
        resp = rek.recognize_celebrities(Image={"Bytes": img_bytes})
    except ClientError as e:
        code = e.response.get("Error", {}).get("Code", "")
        if code in ("ThrottlingException", "ProvisionedThroughputExceededException"):
            time.sleep(2.0)
            try:
                resp = rek.recognize_celebrities(Image={"Bytes": img_bytes})
            except Exception as e2:
                return {"id": pid, "n_celebs": 0, "names": "", "max_match_conf": 0.0,
                        "urls": "", "error": f"retry_fail: {e2}"}
        else:
            return {"id": pid, "n_celebs": 0, "names": "", "max_match_conf": 0.0,
                    "urls": "", "error": str(e)}
    except Exception as e:
        return {"id": pid, "n_celebs": 0, "names": "", "max_match_conf": 0.0,
                "urls": "", "error": str(e)}

    celebs = resp.get("CelebrityFaces", []) or []
    names = [c.get("Name", "") for c in celebs]
    confs = [float(c.get("MatchConfidence") or 0) for c in celebs]
    urls = []
    boxes = []
    for c in celebs:
        u = c.get("Urls") or []
        urls.append(u[0] if u else "")
        bb = (c.get("Face") or {}).get("BoundingBox") or {}
        boxes.append(",".join(f"{float(bb.get(k, 0)):.4f}" for k in ("Left", "Top", "Width", "Height")))
    return {
        "id": pid,
        "n_celebs": len(celebs),
        "names": json.dumps(names, ensure_ascii=False),
        "max_match_conf": round(max(confs), 2) if confs else 0.0,
        "urls": json.dumps(urls, ensure_ascii=False),
        "boxes": "|".join(boxes),
        "error": "",
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=10)
    ap.add_argument("--resume", action="store_true", default=True,
                     help="skip ids already in celebrities.csv (default on)")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--ids-file", default="", help="newline id list; overrides faces_v2.csv n_faces>0 source")
    ap.add_argument("--out", default="", help="override output CSV path")
    ap.add_argument("--posters-dir", default="", help="override local posters dir (e.g. external drive)")
    args = ap.parse_args()

    global OUT, POSTERS
    if args.out:
        OUT = Path(args.out)
    if args.posters_dir:
        POSTERS = Path(args.posters_dir)

    if args.ids_file:
        target_ids = {int(x) for x in Path(args.ids_file).read_text().split() if x.strip()}
        print(f"target (--ids-file): {len(target_ids):,}")
    else:
        faces = pd.read_csv(FACES)
        target_ids = set(faces[faces["n_faces"] > 0]["id"].astype(int))
        print(f"target (n_faces>0): {len(target_ids):,}")

    if args.resume:
        done = load_done()
        target_ids -= done
        print(f"resume: {len(done):,} already done, {len(target_ids):,} remaining")

    ordered = sorted(target_ids)
    if args.limit:
        ordered = ordered[: args.limit]

    print(f"processing {len(ordered):,} posters, workers={args.workers}, saving each result immediately")

    rek = _rek_client()
    t0 = time.time()
    n_done = 0
    n_found = 0
    n_errors = 0

    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(process_one, rek, pid): pid for pid in ordered}
        for fut in as_completed(futs):
            row = fut.result()
            append_row(row)
            n_done += 1
            if row["error"] and row["error"] != "no_local_poster":
                n_errors += 1
            if row["n_celebs"] > 0:
                n_found += 1
            if n_done % 20 == 0:
                elapsed = time.time() - t0
                rate = n_done / max(elapsed, 0.001)
                remaining = len(ordered) - n_done
                eta = remaining / rate if rate > 0 else 0
                print(
                    f"✅ {n_done:,}/{len(ordered):,} | found={n_found} | "
                    f"errors={n_errors} | {rate:.1f}/s ETA:{eta/60:.0f}m",
                    flush=True,
                )

    elapsed = time.time() - t0
    print(f"\n=== DONE ===")
    print(f"processed={n_done:,} found_celebs={n_found:,} errors={n_errors:,} "
          f"time={elapsed:.1f}s ({n_done/max(elapsed,1):.1f}/s) -> {OUT}")


if __name__ == "__main__":
    main()

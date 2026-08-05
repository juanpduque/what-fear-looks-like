#!/usr/bin/env python3
"""Backfill title boxes for posters in S3 that are missing DetectText analysis.

Downloads posters from S3 Community bucket and processes with AWS Rekognition
DetectText to get title bounding boxes (text_x, text_top, text_w, text_h).

Usage:
  # See what would be processed (no cost)
  python3 title_boxes_backfill_s3.py --dry-run

  # Process all missing (~19k, ~$19, ~64 min)
  python3 title_boxes_backfill_s3.py

  # Process and merge into attributes.csv
  python3 title_boxes_backfill_s3.py --merge

  # Process specific IDs
  python3 title_boxes_backfill_s3.py --ids 12345,67890

  # Resume from checkpoint
  python3 title_boxes_backfill_s3.py --resume

Cost: ~$0.001/image (DetectText API)
"""
from __future__ import annotations

import argparse
import io
import json
import os
import re
import time
from difflib import SequenceMatcher
from pathlib import Path

import boto3
import pandas as pd
from botocore.exceptions import ClientError

# Paths
DATA = Path(__file__).parent / "data"
OUT = DATA / "title_boxes_backfill.csv"
CHECKPOINT = DATA / "title_boxes_backfill_checkpoint.json"
MERGED_OUT = DATA / "title_boxes_rekognition.csv"

# S3 config
S3_BUCKET = "sagemaker-studio-a5572760"
S3_PREFIX = "wflike-community-72k/posters"

# Region
REGION = os.environ.get("AWS_DEFAULT_REGION", "us-east-1")  # pragma: allowlist secret


def _norm(s: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", (s or "").upper())


def _fuzzy_title(text: str, title: str) -> float:
    a, b = _norm(text), _norm(title)
    if not a or not b:
        return 0.0
    r = SequenceMatcher(None, a, b).ratio()
    if len(a) >= 3 and (a in b or b in a):
        r = max(r, 0.90)
    for w in re.findall(r"[A-Z0-9]+", (title or "").upper()):
        if len(w) < 3:
            continue
        if len(a) >= 3 and (w in a or a in w):
            r = max(r, 0.82 if len(w) >= 4 else 0.65)
        tw = SequenceMatcher(None, a, w).ratio()
        if tw >= 0.72 and len(a) >= 3:
            r = max(r, tw * 0.95)
    if len(a) <= 2:
        r *= 0.25
    return float(min(1.0, r))


def _pos_bonus(cy: float) -> float:
    if cy < 0.28 or cy > 0.72:
        return 2.2
    if cy < 0.40 or cy > 0.60:
        return 1.2
    return 0.7


def _rek_client():
    return boto3.client("rekognition", region_name=REGION)


def _s3_client():
    return boto3.client("s3", region_name=REGION)


def download_poster_from_s3(s3, poster_id: int) -> bytes | None:
    """Download poster from S3 Community bucket."""
    key = f"{S3_PREFIX}/{poster_id}.jpg"
    try:
        response = s3.get_object(Bucket=S3_BUCKET, Key=key)
        return response["Body"].read()
    except ClientError as e:
        if e.response.get("Error", {}).get("Code") == "NoSuchKey":
            return None
        raise


def detect_lines(rek_client, image_bytes: bytes):
    """Return list of LINE detections with normalized boxes."""
    if len(image_bytes) > 5_000_000:
        raise ValueError("image >5MB")
    resp = rek_client.detect_text(Image={"Bytes": image_bytes})
    lines = []
    for d in resp.get("TextDetections", []):
        if d.get("Type") != "LINE":
            continue
        bb = d["Geometry"]["BoundingBox"]
        lines.append({
            "text": d.get("DetectedText", ""),
            "conf": float(d.get("Confidence", 0)) / 100.0,
            "x0": float(bb["Left"]),
            "y0": float(bb["Top"]),
            "x1": float(bb["Left"] + bb["Width"]),
            "y1": float(bb["Top"] + bb["Height"]),
        })
    return lines


def locate_title(rek_client, image_bytes: bytes, title: str):
    """Find the title text box in the poster."""
    try:
        lines = detect_lines(rek_client, image_bytes)
    except ClientError as e:
        return None
    if not lines:
        return None

    # Score each line
    cands = []
    for ln in lines:
        match = _fuzzy_title(ln["text"], title)
        w = ln["x1"] - ln["x0"]
        h = ln["y1"] - ln["y0"]
        cy = (ln["y0"] + ln["y1"]) * 0.5
        size = w * min(h * 3.2, 1.5)
        score = (0.25 + 0.75 * ln["conf"]) * (0.15 + 0.85 * match) * size * _pos_bonus(cy)
        score *= 1.0 + 0.08 * min(len(_norm(ln["text"])), 20)
        cands.append({**ln, "match": match, "score": score})

    if not cands:
        return None

    # Cluster nearby lines (stacked titles)
    cands.sort(key=lambda c: -c["score"])
    seed = cands[0]
    cluster = [seed]
    y_mid = (seed["y0"] + seed["y1"]) * 0.5
    for c in cands[1:]:
        cy = (c["y0"] + c["y1"]) * 0.5
        if abs(cy - y_mid) > 0.14:
            continue
        if c["match"] >= 0.45 or c["conf"] >= 0.80 or abs(cy - y_mid) <= 0.06:
            cluster.append(c)
            y_mid = sum((x["y0"] + x["y1"]) * 0.5 for x in cluster) / len(cluster)

    match = max(_fuzzy_title(
        " ".join(c["text"] for c in sorted(cluster, key=lambda c: (c["y0"], c["x0"]))),
        title,
    ), max(c["match"] for c in cluster))
    conf = sum(c["conf"] for c in cluster) / len(cluster)
    x0 = min(c["x0"] for c in cluster)
    y0 = min(c["y0"] for c in cluster)
    x1 = max(c["x1"] for c in cluster)
    y1 = max(c["y1"] for c in cluster)
    w, h = x1 - x0, y1 - y0
    cy = (y0 + y1) * 0.5
    score = (0.25 + 0.75 * conf) * (0.15 + 0.85 * match) * w * min(h * 3.2, 1.5) * _pos_bonus(cy)

    # Accept criteria
    rail = cy < 0.32 or cy > 0.68
    ok = (
        (match >= 0.55 and score >= 0.08)
        or (match >= 0.72)
        or (conf >= 0.85 and w >= 0.25 and rail)
        or (conf >= 0.90 and w >= 0.35)
    )
    if not ok:
        return None
    if h > 0.34 or w < 0.08:
        return None

    # Pad
    pad_x, pad_y = 0.02, 0.012
    x0 = max(0.0, x0 - pad_x)
    y0 = max(0.0, y0 - pad_y)
    x1 = min(1.0, x1 + pad_x)
    y1 = min(1.0, y1 + pad_y)
    ocr = " ".join(c["text"] for c in sorted(cluster, key=lambda c: (c["y0"], c["x0"])))
    return {
        "text_x": round(x0, 4),
        "text_top": round(y0, 4),
        "text_w": round(x1 - x0, 4),
        "text_h": round(y1 - y0, 4),
        "ocr": ocr[:80],
        "score": round(score, 4),
    }


def get_missing_ids() -> set[int]:
    """Get IDs that are in corpus but not in title_boxes_rekognition.csv."""
    posters = pd.read_csv(DATA / "posters.csv")
    corpus_ids = set(posters["id"])
    
    if MERGED_OUT.exists():
        existing = pd.read_csv(MERGED_OUT)
        existing_ids = set(existing["id"])
    else:
        existing_ids = set()
    
    return corpus_ids - existing_ids


def load_checkpoint() -> dict:
    if CHECKPOINT.exists():
        return json.loads(CHECKPOINT.read_text())
    return {"processed": [], "errors": []}


def save_checkpoint(checkpoint: dict):
    CHECKPOINT.write_text(json.dumps(checkpoint, indent=2))


def main():
    ap = argparse.ArgumentParser(description="Backfill title boxes from S3")
    ap.add_argument("--ids", default="", help="Comma-separated IDs to process")
    ap.add_argument("--sample", type=int, default=0, help="Process random sample of N")
    ap.add_argument("--save-every", type=int, default=50, help="Save checkpoint every N")
    ap.add_argument("--resume", action="store_true", help="Resume from checkpoint")
    ap.add_argument("--merge", action="store_true", help="Merge results into title_boxes_rekognition.csv")
    ap.add_argument("--dry-run", action="store_true", help="Show what would be processed")
    args = ap.parse_args()

    print("=" * 70)
    print("📦 TITLE BOXES BACKFILL FROM S3")
    print("=" * 70)

    # Determine which IDs to process
    if args.ids:
        target_ids = {int(x.strip()) for x in args.ids.split(",") if x.strip()}
        print(f"\n📋 Processing {len(target_ids)} specified IDs")
    else:
        print("\n📥 Fetching missing IDs...")
        target_ids = get_missing_ids()
        print(f"   Found {len(target_ids):,} IDs without title boxes")

    if args.sample and len(target_ids) > args.sample:
        import random
        target_ids = set(random.sample(list(target_ids), args.sample))
        print(f"   Sampling {len(target_ids)} IDs")

    # Load checkpoint if resuming
    checkpoint = load_checkpoint() if args.resume else {"processed": [], "errors": []}
    already_done = set(checkpoint["processed"])
    target_ids = target_ids - already_done
    
    if already_done:
        print(f"   Resuming: {len(already_done)} already processed, {len(target_ids)} remaining")

    if args.dry_run:
        print(f"\n🔍 DRY RUN: Would process {len(target_ids):,} posters")
        print(f"   Estimated cost: ${len(target_ids) * 0.001:.2f}")
        print(f"   Estimated time: {len(target_ids) / 5 / 60:.0f} minutes @ 5/sec")
        return

    if not target_ids:
        print("\n✅ Nothing to process!")
        return

    # Get metadata (titles)
    posters = pd.read_csv(DATA / "posters.csv", usecols=["id", "title", "year"])
    meta = posters[posters["id"].isin(target_ids)].set_index("id").to_dict("index")

    # Initialize clients
    s3 = _s3_client()
    rek = _rek_client()

    # Load existing results
    rows = {}
    if OUT.exists():
        existing = pd.read_csv(OUT)
        rows = {int(r["id"]): dict(r) for r in existing.to_dict("records")}

    # Process
    t0 = time.time()
    n_new = 0
    n_found = 0
    n_errors = 0
    n_skip = 0

    print(f"\n🚀 Processing {len(target_ids):,} posters...")
    print("-" * 70)

    for i, pid in enumerate(sorted(target_ids)):
        pid = int(pid)
        m = meta.get(pid, {})
        title = m.get("title", "")

        # Download from S3
        try:
            image_bytes = download_poster_from_s3(s3, pid)
            if image_bytes is None:
                n_skip += 1
                continue
        except Exception as e:
            checkpoint["errors"].append({"id": pid, "error": f"s3: {e}"})
            n_errors += 1
            continue

        # Locate title box
        try:
            box = locate_title(rek, image_bytes, title)
        except ClientError as e:
            code = e.response.get("Error", {}).get("Code", "")
            if code in ("ThrottlingException", "ProvisionedThroughputExceededException"):
                time.sleep(2.0)
                try:
                    box = locate_title(rek, image_bytes, title)
                except Exception:
                    box = None
            else:
                box = None
        except Exception:
            box = None

        # Store result
        if box is None:
            row = dict(id=pid, text_x=-1.0, text_top=-1.0, text_w=-1.0, text_h=-1.0,
                       ocr="", score=0.0)
        else:
            row = dict(id=pid, **box)
            n_found += 1

        rows[pid] = row
        checkpoint["processed"].append(pid)
        n_new += 1

        # Progress
        if n_new % 20 == 0:
            elapsed = time.time() - t0
            rate = n_new / max(elapsed, 0.001)
            remaining = len(target_ids) - i - 1
            eta = remaining / rate if rate > 0 else 0
            found_pct = 100 * n_found / n_new if n_new > 0 else 0
            print(
                f"✅ {n_new:,}/{len(target_ids):,} | {pid} {title[:20]!r} | "
                f"found={found_pct:.0f}% | {rate:.1f}/s ETA:{eta/60:.0f}m",
                flush=True,
            )

        # Checkpoint
        if n_new % args.save_every == 0:
            df = pd.DataFrame(rows.values())
            df.to_csv(OUT, index=False)
            save_checkpoint(checkpoint)

    # Final save
    df = pd.DataFrame(rows.values())
    df.to_csv(OUT, index=False)
    save_checkpoint(checkpoint)

    elapsed = time.time() - t0
    print("\n" + "=" * 70)
    print(f"✅ COMPLETADO")
    print(f"   Procesados:     {n_new:,}")
    print(f"   Con título:     {n_found:,} ({100*n_found/max(n_new,1):.1f}%)")
    print(f"   Sin título:     {n_new - n_found:,}")
    print(f"   Errores:        {n_errors:,}")
    print(f"   Omitidos:       {n_skip:,}")
    print(f"   Tiempo:         {elapsed:.1f}s ({n_new/max(elapsed,1):.1f}/s)")
    print(f"   Resultado:      {OUT}")
    print("=" * 70)

    # Merge if requested
    if args.merge and OUT.exists():
        print("\n🔄 Merging into title_boxes_rekognition.csv...")
        merge_results()


def merge_results():
    """Merge backfill results into main title_boxes_rekognition.csv."""
    if not OUT.exists():
        print("   No backfill results to merge")
        return

    backfill = pd.read_csv(OUT)

    if MERGED_OUT.exists():
        existing = pd.read_csv(MERGED_OUT)
        existing_ids = set(existing["id"])
        new_rows = backfill[~backfill["id"].isin(existing_ids)]

        if len(new_rows) > 0:
            merged = pd.concat([existing, new_rows], ignore_index=True)
            merged = merged.drop_duplicates(subset=["id"], keep="last")
            merged.to_csv(MERGED_OUT, index=False)
            print(f"   ✅ Merged {len(new_rows):,} new rows → {MERGED_OUT} ({len(merged):,} total)")
        else:
            print("   No new rows to merge")
    else:
        backfill.to_csv(MERGED_OUT, index=False)
        print(f"   ✅ Created {MERGED_OUT} ({len(backfill):,} rows)")


if __name__ == "__main__":
    main()

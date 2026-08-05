#!/usr/bin/env python3
"""Backfill Rekognition analysis for posters in S3 that are missing analysis.

Downloads posters from S3 Community bucket and processes with AWS Rekognition
to generate the same metrics as rekognition_enrich.py.

Usage:
  # Process all 10,596 missing IDs
  python3 rekognition_backfill_s3.py

  # Process specific IDs
  python3 rekognition_backfill_s3.py --ids 12345,67890

  # Process a sample
  python3 rekognition_backfill_s3.py --sample 100

  # Resume from checkpoint
  python3 rekognition_backfill_s3.py --resume

Cost estimate: ~3 API calls per poster × $0.001 = ~$0.003/poster
               10,596 posters × $0.003 = ~$32

Requires: AWS credentials with Rekognition and S3 access.
"""
from __future__ import annotations

import argparse
import io
import json
import os
import time
from pathlib import Path

import boto3
import pandas as pd
from botocore.exceptions import ClientError

# Paths
DATA = Path(__file__).parent / "data"
OUT = DATA / "rekognition_backfill.csv"
CHECKPOINT = DATA / "rekognition_backfill_checkpoint.json"
MERGED_OUT = DATA / "rekognition.csv"

# S3 config
S3_BUCKET = "sagemaker-studio-a5572760"
S3_PREFIX = "wflike-community-72k/posters"

# Region - use environment or default
REGION = os.environ.get("AWS_DEFAULT_REGION", "us-east-1")  # pragma: allowlist secret

# Vocabularies (same as rekognition_enrich.py)
WEAPON = {
    "weapon", "blade", "knife", "dagger", "sword", "gun", "handgun", "rifle",
    "axe", "hatchet", "bow", "arrow", "spear", "mace", "chainsaw",
}
ANIMAL = {
    "animal", "shark", "fish", "sea life", "insect", "bird", "dog", "cat",
    "wolf", "bear", "snake", "spider", "bat", "crow", "raven", "great white shark",
}
PERSON = {"person", "human", "man", "woman", "boy", "girl", "adult", "child", "face", "baby"}
WATER = {"water", "ocean", "sea", "lake", "beach", "wave", "underwater"}
FIRE = {"fire", "flame", "smoke", "explosion"}
SILHOUETTE = {"silhouette"}


def _rek_client():
    return boto3.client("rekognition", region_name=REGION)


def _s3_client():
    return boto3.client("s3", region_name=REGION)


def _flag(labels, vocab):
    """Return highest confidence for any label in vocabulary."""
    best = 0.0
    for name, conf in labels:
        if name.lower() in vocab:
            best = max(best, conf)
    return round(best, 4)


def _mod_score(mods, *names):
    """Return highest confidence for specified moderation labels."""
    want = {n.lower() for n in names}
    best = 0.0
    for name, conf in mods:
        if name.lower() in want:
            best = max(best, conf)
    return round(best, 4)


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


def analyze(rek_client, image_bytes: bytes) -> dict:
    """Analyze image with Rekognition (same logic as rekognition_enrich.py)."""
    if len(image_bytes) > 5_000_000:
        raise ValueError("image >5MB")

    # 1) Labels + image properties
    lab = rek_client.detect_labels(
        Image={"Bytes": image_bytes},
        MaxLabels=20,
        MinConfidence=50,
        Features=["GENERAL_LABELS", "IMAGE_PROPERTIES"],
        Settings={"ImageProperties": {"MaxDominantColors": 5}},
    )
    labels = [(l["Name"], float(l["Confidence"]) / 100.0) for l in lab.get("Labels", [])]
    n_boxes = sum(len(l.get("Instances") or []) for l in lab.get("Labels", []))
    ip = lab.get("ImageProperties") or {}
    q = ip.get("Quality") or {}
    colors = ip.get("DominantColors") or []
    color_s = "|".join(
        f"{c.get('HexCode', '')}:{round(float(c.get('PixelPercent', 0)), 1)}"
        for c in colors[:5]
    )
    label_s = "|".join(f"{n}:{c:.2f}" for n, c in labels[:10])

    # 2) Moderation
    mod = rek_client.detect_moderation_labels(Image={"Bytes": image_bytes}, MinConfidence=40)
    mods = [
        (m["Name"], float(m["Confidence"]) / 100.0)
        for m in mod.get("ModerationLabels", [])
    ]
    mod_s = "|".join(f"{n}:{c:.2f}" for n, c in mods[:8])

    # 3) Faces
    faces = rek_client.detect_faces(Image={"Bytes": image_bytes}, Attributes=["ALL"])
    details = faces.get("FaceDetails") or []
    emotion = gender = ""
    age_lo = age_hi = -1
    if details:
        details = sorted(
            details,
            key=lambda f: f["BoundingBox"]["Width"] * f["BoundingBox"]["Height"],
            reverse=True,
        )
        f0 = details[0]
        emos = sorted(f0.get("Emotions") or [], key=lambda e: -e["Confidence"])
        if emos:
            emotion = f"{emos[0]['Type']}:{emos[0]['Confidence']/100:.2f}"
        gender = (f0.get("Gender") or {}).get("Value") or ""
        ar = f0.get("AgeRange") or {}
        age_lo = int(ar.get("Low", -1))
        age_hi = int(ar.get("High", -1))

    top_n, top_c = (labels[0][0], labels[0][1]) if labels else ("", 0.0)
    return dict(
        rek_labels=label_s,
        rek_top=top_n,
        rek_top_conf=round(top_c, 4),
        rek_weapon=_flag(labels, WEAPON),
        rek_animal=_flag(labels, ANIMAL),
        rek_person=_flag(labels, PERSON),
        rek_water=_flag(labels, WATER),
        rek_fire=_flag(labels, FIRE),
        rek_silhouette=_flag(labels, SILHOUETTE),
        rek_n_boxes=int(n_boxes),
        rek_bright=round(float(q.get("Brightness") or 0), 2),
        rek_sharp=round(float(q.get("Sharpness") or 0), 2),
        rek_contrast=round(float(q.get("Contrast") or 0), 2),
        rek_colors=color_s,
        rek_mod=mod_s,
        rek_violence=_mod_score(mods, "Violence", "Graphic Violence"),
        rek_mod_weapons=_mod_score(mods, "Weapons"),
        rek_gore=_mod_score(
            mods, "Visually Disturbing", "Blood & Gore", "Gore",
            "Emaciated Bodies", "Corpses", "Hanging",
        ),
        rek_n_faces=len(details),
        rek_emotion=emotion,
        rek_gender=gender,
        rek_age_lo=age_lo,
        rek_age_hi=age_hi,
    )


def get_missing_ids() -> set[int]:
    """Get IDs that have posters in S3 but no Rekognition analysis."""
    s3 = _s3_client()
    
    # Download manifest from S3
    manifest_key = "wflike-community-72k/results/download_manifest.csv"
    obj = s3.get_object(Bucket=S3_BUCKET, Key=manifest_key)
    manifest = pd.read_csv(io.BytesIO(obj["Body"].read()))
    
    # IDs with successful downloads
    downloaded_ok = manifest[manifest["status"].isin(["ok", "exists"])]["id"]
    downloaded_ids = set(downloaded_ok)
    
    # IDs with Rekognition in S3 Community job
    rek_key = "wflike-community-72k/results/rekognition_community_72k.csv"
    obj = s3.get_object(Bucket=S3_BUCKET, Key=rek_key)
    rek_community = pd.read_csv(io.BytesIO(obj["Body"].read()))
    s3_rek_ids = set(rek_community["id"])
    
    # IDs with Rekognition locally
    if MERGED_OUT.exists():
        local_rek = pd.read_csv(MERGED_OUT)
        local_ids = set(local_rek["id"].unique())
    else:
        local_ids = set()
    
    # Missing = downloaded but no Rekognition anywhere
    missing = downloaded_ids - s3_rek_ids - local_ids
    return missing


def load_checkpoint() -> dict:
    """Load checkpoint if exists."""
    if CHECKPOINT.exists():
        return json.loads(CHECKPOINT.read_text())
    return {"processed": [], "errors": []}


def save_checkpoint(checkpoint: dict):
    """Save checkpoint."""
    CHECKPOINT.write_text(json.dumps(checkpoint, indent=2))


def get_metadata_for_ids(ids: set[int]) -> pd.DataFrame:
    """Get title/year metadata for IDs from TMDB list or posters.csv."""
    s3 = _s3_client()
    
    # Try to get from tmdb_horror_ids.csv in S3
    try:
        key = "wflike-community-72k/results/tmdb_horror_ids.csv"
        obj = s3.get_object(Bucket=S3_BUCKET, Key=key)
        tmdb = pd.read_csv(io.BytesIO(obj["Body"].read()))
        tmdb = tmdb[tmdb["id"].isin(ids)]
        if len(tmdb) > 0 and "title" in tmdb.columns and "year" in tmdb.columns:
            return tmdb[["id", "title", "year"]]
    except Exception:
        pass
    
    # Fallback: local posters.csv
    posters_path = DATA / "posters.csv"
    if posters_path.exists():
        posters = pd.read_csv(posters_path, usecols=["id", "title", "year"])
        posters = posters[posters["id"].isin(ids)]
        if len(posters) > 0:
            return posters
    
    # Last resort: just IDs with empty metadata
    return pd.DataFrame({"id": list(ids), "title": "", "year": 0})


def main():
    ap = argparse.ArgumentParser(description="Backfill Rekognition for missing S3 posters")
    ap.add_argument("--ids", default="", help="Comma-separated IDs to process")
    ap.add_argument("--sample", type=int, default=0, help="Process random sample of N")
    ap.add_argument("--save-every", type=int, default=25, help="Save checkpoint every N")
    ap.add_argument("--resume", action="store_true", help="Resume from checkpoint")
    ap.add_argument("--merge", action="store_true", help="Merge results into rekognition.csv at end")
    ap.add_argument("--dry-run", action="store_true", help="Show what would be processed")
    args = ap.parse_args()

    print("=" * 70)
    print("🔍 REKOGNITION BACKFILL FROM S3")
    print("=" * 70)

    # Determine which IDs to process
    if args.ids:
        target_ids = {int(x.strip()) for x in args.ids.split(",") if x.strip()}
        print(f"\n📋 Processing {len(target_ids)} specified IDs")
    else:
        print("\n📥 Fetching missing IDs from S3...")
        target_ids = get_missing_ids()
        print(f"   Found {len(target_ids):,} IDs without Rekognition analysis")

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
        print(f"   Estimated cost: ${len(target_ids) * 0.003:.2f}")
        print(f"   Estimated time: {len(target_ids) / 5:.0f} seconds @ 5/sec")
        return

    if not target_ids:
        print("\n✅ Nothing to process!")
        return

    # Get metadata
    print(f"\n📋 Getting metadata for {len(target_ids):,} IDs...")
    meta = get_metadata_for_ids(target_ids)
    
    # Initialize clients
    s3 = _s3_client()
    rek = _rek_client()
    
    # Load existing results if any
    rows = {}
    if OUT.exists():
        existing = pd.read_csv(OUT)
        rows = {int(r["id"]): dict(r) for r in existing.to_dict("records")}

    # Process
    t0 = time.time()
    n_new = 0
    n_errors = 0
    n_skip = 0
    
    print(f"\n🚀 Processing {len(target_ids):,} posters...")
    print("-" * 70)

    for i, pid in enumerate(sorted(target_ids)):
        pid = int(pid)
        
        # Get metadata
        meta_row = meta[meta["id"] == pid]
        title = str(meta_row["title"].iloc[0]) if len(meta_row) > 0 else ""
        year = int(meta_row["year"].iloc[0]) if len(meta_row) > 0 and pd.notna(meta_row["year"].iloc[0]) else 0
        
        # Download from S3
        try:
            image_bytes = download_poster_from_s3(s3, pid)
            if image_bytes is None:
                n_skip += 1
                continue
        except Exception as e:
            print(f"❌ S3 download {pid}: {e}", flush=True)
            checkpoint["errors"].append({"id": pid, "error": f"s3: {e}"})
            n_errors += 1
            continue

        # Analyze with Rekognition
        try:
            feats = analyze(rek, image_bytes)
        except ClientError as e:
            code = e.response.get("Error", {}).get("Code", "")
            print(f"⚠️ Rekognition {pid}: {code}", flush=True)
            
            if code in ("ThrottlingException", "ProvisionedThroughputExceededException"):
                time.sleep(2.0)
                try:
                    feats = analyze(rek, image_bytes)
                except Exception as e2:
                    checkpoint["errors"].append({"id": pid, "error": str(e2)})
                    n_errors += 1
                    continue
            else:
                checkpoint["errors"].append({"id": pid, "error": str(e)})
                n_errors += 1
                continue
        except Exception as e:
            print(f"❌ Analyze {pid}: {e}", flush=True)
            checkpoint["errors"].append({"id": pid, "error": str(e)})
            n_errors += 1
            continue

        # Store result
        row = dict(id=pid, year=year, title=title, **feats)
        rows[pid] = row
        checkpoint["processed"].append(pid)
        n_new += 1

        # Progress report
        if n_new % 10 == 0:
            elapsed = time.time() - t0
            rate = n_new / max(elapsed, 0.001)
            remaining = len(target_ids) - i - 1
            eta = remaining / rate if rate > 0 else 0
            print(
                f"✅ {n_new:,}/{len(target_ids):,} | {pid} {title[:25]!r} | "
                f"top={row['rek_top']!r} weap={row['rek_weapon']:.2f} "
                f"viol={row['rek_violence']:.2f} | {rate:.1f}/s ETA:{eta/60:.0f}m",
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
    print(f"   Procesados: {n_new:,}")
    print(f"   Errores:    {n_errors:,}")
    print(f"   Omitidos:   {n_skip:,}")
    print(f"   Tiempo:     {elapsed:.1f}s ({n_new/max(elapsed,1):.1f}/s)")
    print(f"   Resultado:  {OUT}")
    print("=" * 70)

    # Merge if requested
    if args.merge and OUT.exists():
        print("\n🔄 Merging into rekognition.csv...")
        merge_results()


def merge_results():
    """Merge backfill results into main rekognition.csv."""
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

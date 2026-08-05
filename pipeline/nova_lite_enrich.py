#!/usr/bin/env python3
"""Enrich posters with AWS Nova Lite signals (compatible with rekognition.csv).

Generates the same columns as rekognition_enrich.py but using Amazon Nova Lite
via Bedrock instead of Rekognition APIs. ~18x cheaper per image.

  python3 nova_lite_enrich.py --ids 578,948
  python3 nova_lite_enrich.py --missing          # process missing from corpus
  python3 nova_lite_enrich.py --tmdb-key KEY     # fetch poster_paths from TMDB

Requires: boto3, AWS credentials with Bedrock access.
Outputs: data/nova_lite_enrich.csv (merged into rekognition.csv with --merge)
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import re
import time
from pathlib import Path

import boto3
import pandas as pd
import requests
from botocore.exceptions import ClientError

DATA = Path(__file__).parent / "data"
OUT = DATA / "nova_lite_enrich.csv"
REK_OUT = DATA / "rekognition.csv"
REGION = os.environ.get("AWS_DEFAULT_REGION", "us-east-1")  # pragma: allowlist secret

WEAPON = {
    "weapon", "blade", "knife", "dagger", "sword", "gun", "handgun", "rifle",
    "axe", "hatchet", "bow", "arrow", "spear", "mace", "chainsaw", "machete",
}
ANIMAL = {
    "animal", "shark", "fish", "sea life", "insect", "bird", "dog", "cat",
    "wolf", "bear", "snake", "spider", "bat", "crow", "raven", "great white shark",
    "creature", "monster", "beast",
}
PERSON = {"person", "human", "man", "woman", "boy", "girl", "adult", "child", "face", "baby"}
WATER = {"water", "ocean", "sea", "lake", "beach", "wave", "underwater"}
FIRE = {"fire", "flame", "smoke", "explosion"}
SILHOUETTE = {"silhouette", "shadow", "dark figure"}

NOVA_PROMPT = """Analyze this movie poster image and extract detailed information.

Return ONLY a valid JSON object with this exact structure:
{
  "labels": [{"name": "label_name", "confidence": 0.95}],
  "dominant_colors": [{"hex": "#000000", "percent": 50.0}],
  "brightness": 50.0,
  "sharpness": 80.0,
  "contrast": 85.0,
  "faces": [{"emotion": "FEAR", "emotion_conf": 0.95, "gender": "Female", "age_low": 20, "age_high": 30}],
  "moderation": [{"name": "Violence", "confidence": 0.8}],
  "text_detected": ["TITLE", "OTHER TEXT"],
  "has_silhouette": false,
  "bounding_boxes_count": 5
}

Instructions:
1. labels: Detect objects, people, concepts. Include confidence 0-1. Max 20 labels.
2. dominant_colors: Top 5 colors as hex codes with percentage.
3. brightness: Image brightness 0-100 (0=dark, 100=bright).
4. sharpness: Image sharpness 0-100.
5. contrast: Image contrast 0-100.
6. faces: For each visible face, detect emotion (HAPPY, SAD, ANGRY, CONFUSED, DISGUSTED, SURPRISED, CALM, FEAR), gender, age range.
7. moderation: Flag violence, gore, weapons, disturbing content with confidence.
8. text_detected: Any visible text on the poster.
9. has_silhouette: true if dark silhouette figure is prominent.
10. bounding_boxes_count: Estimate of distinct object regions.

Return ONLY the JSON, no explanation."""


def get_bedrock_client():
    return boto3.client("bedrock-runtime", region_name=REGION)


def download_poster(poster_path: str, tmdb_id: int) -> bytes | None:
    """Download poster from TMDB CDN."""
    if not poster_path:
        return None
    url = f"https://image.tmdb.org/t/p/w500{poster_path}"
    try:
        resp = requests.get(url, timeout=30)
        if resp.status_code == 200:
            return resp.content
    except Exception as e:
        print(f"  download error {tmdb_id}: {e}")
    return None


def fetch_poster_path(session: requests.Session, api_key: str, tmdb_id: int) -> str | None:
    """Fetch poster_path from TMDB API."""
    url = f"https://api.themoviedb.org/3/movie/{tmdb_id}"
    try:
        resp = session.get(url, params={"api_key": api_key}, timeout=30)
        if resp.status_code == 200:
            data = resp.json()
            return data.get("poster_path")
    except Exception:
        pass
    return None


def analyze_with_nova(client, img_bytes: bytes) -> dict:
    """Analyze image with Nova Lite and return structured data."""
    body = {
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "image": {
                            "format": "jpeg",
                            "source": {"bytes": base64.b64encode(img_bytes).decode()}
                        }
                    },
                    {"text": NOVA_PROMPT}
                ]
            }
        ],
        "inferenceConfig": {"maxTokens": 2048}
    }
    
    response = client.invoke_model(
        modelId="amazon.nova-lite-v1:0",
        body=json.dumps(body)
    )
    result = json.loads(response["body"].read())
    output_text = result["output"]["message"]["content"][0]["text"]
    
    # Parse JSON from response
    try:
        # Try to extract JSON if wrapped in markdown
        json_match = re.search(r'\{[\s\S]*\}', output_text)
        if json_match:
            return json.loads(json_match.group())
    except json.JSONDecodeError:
        pass
    return {}


def _flag(labels: list[dict], vocab: set) -> float:
    """Find highest confidence for any label matching vocabulary."""
    best = 0.0
    for item in labels:
        name = item.get("name", "").lower()
        conf = float(item.get("confidence", 0))
        if name in vocab or any(v in name for v in vocab):
            best = max(best, conf)
    return round(best, 4)


def _mod_score(mods: list[dict], *names: str) -> float:
    """Find highest confidence for moderation labels."""
    want = {n.lower() for n in names}
    best = 0.0
    for item in mods:
        name = item.get("name", "").lower()
        conf = float(item.get("confidence", 0))
        if name in want or any(w in name for w in want):
            best = max(best, conf)
    return round(best, 4)


def nova_to_rekognition_format(nova_data: dict) -> dict:
    """Convert Nova Lite output to rekognition.csv format."""
    labels = nova_data.get("labels", [])
    colors = nova_data.get("dominant_colors", [])
    faces = nova_data.get("faces", [])
    mods = nova_data.get("moderation", [])
    
    # Labels string
    label_s = "|".join(
        f"{l.get('name', '')}:{l.get('confidence', 0):.2f}"
        for l in labels[:10]
    )
    
    # Top label
    top_n, top_c = ("", 0.0)
    if labels:
        top = labels[0]
        top_n = top.get("name", "")
        top_c = float(top.get("confidence", 0))
    
    # Colors string
    color_s = "|".join(
        f"{c.get('hex', '#000000')}:{c.get('percent', 0):.1f}"
        for c in colors[:5]
    )
    
    # Moderation string
    mod_s = "|".join(
        f"{m.get('name', '')}:{m.get('confidence', 0):.2f}"
        for m in mods[:8]
    )
    
    # Face info (largest/first face)
    emotion = gender = ""
    age_lo = age_hi = -1
    if faces:
        f0 = faces[0]
        emo = f0.get("emotion", "")
        emo_conf = f0.get("emotion_conf", 0)
        if emo:
            emotion = f"{emo}:{emo_conf:.2f}"
        gender = f0.get("gender", "")
        age_lo = int(f0.get("age_low", -1))
        age_hi = int(f0.get("age_high", -1))
    
    # Silhouette from labels or explicit flag
    sil_score = _flag(labels, SILHOUETTE)
    if nova_data.get("has_silhouette"):
        sil_score = max(sil_score, 0.8)
    
    return {
        "rek_labels": label_s,
        "rek_top": top_n,
        "rek_top_conf": round(top_c, 4),
        "rek_weapon": _flag(labels, WEAPON),
        "rek_animal": _flag(labels, ANIMAL),
        "rek_person": _flag(labels, PERSON),
        "rek_water": _flag(labels, WATER),
        "rek_fire": _flag(labels, FIRE),
        "rek_silhouette": sil_score,
        "rek_n_boxes": int(nova_data.get("bounding_boxes_count", 0)),
        "rek_bright": round(float(nova_data.get("brightness", 0)), 2),
        "rek_sharp": round(float(nova_data.get("sharpness", 0)), 2),
        "rek_contrast": round(float(nova_data.get("contrast", 0)), 2),
        "rek_colors": color_s,
        "rek_mod": mod_s,
        "rek_violence": _mod_score(mods, "Violence", "Graphic Violence"),
        "rek_mod_weapons": _mod_score(mods, "Weapons", "Weapon"),
        "rek_gore": _mod_score(mods, "Gore", "Blood", "Disturbing", "Corpse"),
        "rek_n_faces": len(faces),
        "rek_emotion": emotion,
        "rek_gender": gender,
        "rek_age_lo": age_lo,
        "rek_age_hi": age_hi,
    }


def process_poster(client, tmdb_id: int, title: str, year: int, 
                   poster_path: str | None, session: requests.Session = None,
                   tmdb_key: str = None) -> dict | None:
    """Process a single poster with Nova Lite."""
    # Get poster_path if not provided
    if not poster_path and session and tmdb_key:
        poster_path = fetch_poster_path(session, tmdb_key, tmdb_id)
    
    if not poster_path:
        return None
    
    # Download image
    img_bytes = download_poster(poster_path, tmdb_id)
    if not img_bytes:
        return None
    
    # Analyze with Nova
    try:
        nova_data = analyze_with_nova(client, img_bytes)
        if not nova_data:
            return None
        
        # Convert to rekognition format
        feats = nova_to_rekognition_format(nova_data)
        return {"id": tmdb_id, "year": int(year), "title": str(title), **feats}
    
    except ClientError as e:
        print(f"  Nova error {tmdb_id}: {e}")
        return None
    except Exception as e:
        print(f"  Error {tmdb_id}: {e}")
        return None


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--ids", default="", help="comma-separated TMDB ids")
    ap.add_argument("--missing", action="store_true", help="process missing from corpus")
    ap.add_argument("--tmdb-key", default=os.environ.get("TMDB_API_KEY"), 
                    help="TMDB API key for fetching poster_paths")
    ap.add_argument("--save-every", type=int, default=10)
    ap.add_argument("--merge", action="store_true", help="merge results into rekognition.csv")
    ap.add_argument("--limit", type=int, default=0, help="limit number to process")
    args = ap.parse_args()
    
    # Load metadata
    posters = pd.read_csv(DATA / "posters.csv", usecols=["id", "title", "year"])
    
    # Load existing poster_paths
    poster_paths = {}
    for pf in ["poster_paths_backfill.csv", "horror_refresh_2026.csv"]:
        path = DATA / pf
        if path.exists():
            df = pd.read_csv(path)
            if "poster_path" in df.columns:
                for _, row in df.iterrows():
                    if pd.notna(row.get("poster_path")):
                        poster_paths[int(row["id"])] = row["poster_path"]
    
    # Determine which IDs to process
    if args.ids:
        want = {int(x) for x in args.ids.split(",") if x.strip()}
        meta = posters[posters.id.isin(want)]
    elif args.missing:
        existing = pd.read_csv(REK_OUT) if REK_OUT.exists() else pd.DataFrame()
        done_ids = set(existing["id"].unique()) if len(existing) else set()
        missing_ids = set(posters["id"]) - done_ids
        meta = posters[posters.id.isin(missing_ids)]
        print(f"Found {len(meta)} missing posters")
    else:
        meta = posters
    
    if args.limit > 0:
        meta = meta.head(args.limit)
    
    # Load existing results
    existing = pd.read_csv(OUT) if OUT.exists() else pd.DataFrame()
    rows = {int(r["id"]): dict(r) for r in existing.to_dict("records")} if len(existing) else {}
    done = set(rows)
    
    # Setup clients
    bedrock = get_bedrock_client()
    session = requests.Session() if args.tmdb_key else None
    
    t0 = time.time()
    n_new = n_skip = 0
    
    for r in meta.itertuples(index=False):
        pid = int(r.id)
        if pid in done:
            continue
        
        poster_path = poster_paths.get(pid)
        
        # Skip if no poster_path and no TMDB key
        if not poster_path and not args.tmdb_key:
            n_skip += 1
            continue
        
        result = process_poster(
            bedrock, pid, r.title, r.year,
            poster_path, session, args.tmdb_key
        )
        
        if result:
            rows[pid] = result
            n_new += 1
            rate = n_new / max(time.time() - t0, 1e-6)
            print(
                f"[{n_new}] {pid} {str(r.title)[:30]!r} "
                f"top={result['rek_top']!r} faces={result['rek_n_faces']} "
                f"| {rate:.2f}/s",
                flush=True
            )
            
            if n_new % args.save_every == 0:
                df = pd.DataFrame(rows.values())
                df.to_csv(OUT, index=False)
                print(f"  [checkpoint] saved {len(df)} rows")
        else:
            n_skip += 1
    
    # Final save
    df = pd.DataFrame(rows.values())
    df.to_csv(OUT, index=False)
    print(f"\nWrote {OUT} ({len(df)} rows, {n_new} new, {n_skip} skipped, {time.time()-t0:.1f}s)")
    
    # Merge into rekognition.csv if requested
    if args.merge and len(df) > 0:
        rek = pd.read_csv(REK_OUT) if REK_OUT.exists() else pd.DataFrame()
        combined = pd.concat([rek, df], ignore_index=True)
        combined = combined.drop_duplicates(subset=["id"], keep="last")
        combined.to_csv(REK_OUT, index=False)
        print(f"Merged into {REK_OUT} ({len(combined)} total rows)")


if __name__ == "__main__":
    main()

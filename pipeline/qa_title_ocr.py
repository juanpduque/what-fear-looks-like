#!/usr/bin/env python3
"""Nova vision QA of Rekognition DetectText OCR readings on posters.

Cross-checks the aggregated OCR text Rekognition extracted per poster
(poster_ocr_rek_text*.csv, "full_ocr" column) against what Nova Pro reads
directly off the image, to estimate how often OCR mis-reads or misses the
title entirely (which would also explain some of the drift-review
"uncertain"/"mismatch" cases).

  export AWS_PROFILE=sandbox
  python3 qa_title_ocr.py --n 2000 --workers 12
  python3 qa_title_ocr.py --n 999999 --workers 30   # full coverage
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import os
import random
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import boto3
from botocore.config import Config
from PIL import Image

DATA = Path(__file__).resolve().parent / "data"
POSTERS = DATA / "posters"
SRC_FILES = [
    DATA / "poster_ocr_rek_text.csv",
    DATA / "poster_ocr_rek_text_scifi.csv",
    DATA / "poster_ocr_rek_text_thriller.csv",
    DATA / "poster_ocr_rek_text_mystery.csv",
]
OUT_CSV = DATA / "qa" / "qa_title_ocr.csv"
REGION = "us-east-1"
MODEL_ID = "us.amazon.nova-pro-v1:0"
MAX_SIDE = 1200

FIELDS = [
    "id", "rek_ocr", "rek_n_words",
    "model", "status", "nova_text", "verdict", "reason", "latency_s", "error",
]

PROMPT = """Read any title text visible on this movie poster (the main film title,
as printed on the artwork -- ignore tagline/credits/small print unless no title exists).

An OCR system (AWS Rekognition DetectText) extracted this text from the same poster:
---
{rek_ocr}
---

Judge whether that OCR text is an accurate reading of the actual title on the poster.

Return ONLY valid JSON (no markdown):
{{
  "text_you_read": "the title text you actually see on the poster, or empty if none",
  "verdict": "accurate" | "inaccurate" | "no_title_on_poster",
  "reason": "one short sentence"
}}

Rules:
- accurate: the OCR text matches what's really printed (minor case/spacing differences OK).
- inaccurate: OCR text is garbled, wrong, or missed real title text that IS visible.
- no_title_on_poster: there's no readable title text on this poster at all (matches empty OCR).
"""

_write_lock = threading.Lock()


def log(msg: str) -> None:
    print(msg, flush=True)


def load_ocr_rows() -> list[dict]:
    rows: list[dict] = []
    seen: set[int] = set()
    for src in SRC_FILES:
        if not src.exists():
            continue
        with src.open(encoding="utf-8", errors="replace") as f:
            for r in csv.DictReader(f):
                try:
                    pid = int(r["id"])
                except Exception:
                    continue
                if pid in seen:
                    continue
                seen.add(pid)
                rows.append({
                    "id": pid,
                    "rek_ocr": (r.get("full_ocr") or "").strip(),
                    "rek_n_words": r.get("n_words") or "0",
                })
    with ThreadPoolExecutor(max_workers=64) as ex:
        exists = list(ex.map(lambda r: (POSTERS / f"{r['id']}.jpg").exists(), rows))
    rows = [r for r, ok in zip(rows, exists) if ok]
    return rows


def pick_sample(rows: list[dict], n: int, seed: int) -> list[dict]:
    # prioritize rows where OCR found little/no text (most likely to be a
    # real miss) and rows with lots of text (most likely to have garbling),
    # keep a random middle slice for calibration
    def words(r):
        try:
            return int(float(r["rek_n_words"]))
        except Exception:
            return 0
    zero = [r for r in rows if words(r) == 0]
    heavy = [r for r in rows if words(r) >= 8]
    mid = [r for r in rows if 0 < words(r) < 8]
    rng = random.Random(seed)
    for bucket in (zero, heavy, mid):
        rng.shuffle(bucket)
    n0 = min(len(zero), int(round(n * 0.40)))
    n1 = min(len(heavy), int(round(n * 0.30)))
    n2 = min(len(mid), n - n0 - n1)
    picked = zero[:n0] + heavy[:n1] + mid[:n2]
    if len(picked) < n:
        used = {r["id"] for r in picked}
        remaining = [r for r in rows if r["id"] not in used]
        rng.shuffle(remaining)
        picked.extend(remaining[: n - len(picked)])
    rng.shuffle(picked)
    return picked[:n]


def load_done(path: Path) -> set[int]:
    done = set()
    if not path.exists():
        return done
    with path.open(encoding="utf-8", errors="replace") as f:
        for r in csv.DictReader(f):
            if r.get("status") == "ok":
                done.add(int(r["id"]))
    return done


def append_row(path: Path, row: dict) -> None:
    new_file = not path.exists()
    with _write_lock:
        with path.open("a", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=FIELDS)
            if new_file:
                w.writeheader()
            w.writerow(row)


def resize_jpeg(path: Path) -> bytes:
    im = Image.open(path).convert("RGB")
    w, h = im.size
    scale = min(1.0, MAX_SIDE / float(max(w, h)))
    if scale < 1.0:
        im = im.resize((max(1, int(w * scale)), max(1, int(h * scale))), Image.Resampling.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, format="JPEG", quality=90)
    return buf.getvalue()


def process_one(client, r: dict, out_csv: Path) -> None:
    base = {
        "id": r["id"], "rek_ocr": r["rek_ocr"], "rek_n_words": r["rek_n_words"],
        "model": "nova-pro", "status": "error",
        "nova_text": "", "verdict": "", "reason": "", "latency_s": 0.0, "error": "",
    }
    t0 = time.perf_counter()
    try:
        img = resize_jpeg(POSTERS / f"{r['id']}.jpg")
        prompt = PROMPT.format(rek_ocr=r["rek_ocr"] or "(empty -- no text detected)")
        resp = client.converse(
            modelId=MODEL_ID,
            messages=[{"role": "user", "content": [
                {"image": {"format": "jpeg", "source": {"bytes": img}}},
                {"text": prompt},
            ]}],
            inferenceConfig={"temperature": 0, "maxTokens": 250},
        )
        text = "".join(
            b.get("text", "") for b in resp.get("output", {}).get("message", {}).get("content", [])
            if "text" in b
        ).strip()
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
        obj = json.loads(text)
        base.update(
            status="ok",
            nova_text=obj.get("text_you_read", ""),
            verdict=obj.get("verdict", ""),
            reason=obj.get("reason", ""),
            latency_s=round(time.perf_counter() - t0, 3),
        )
    except Exception as e:
        base["error"] = f"{type(e).__name__}: {e}"[:400]
        base["latency_s"] = round(time.perf_counter() - t0, 3)
    append_row(out_csv, base)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=2000)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--workers", type=int, default=12)
    ap.add_argument("--out", default="")
    ap.add_argument("--region", default=REGION)
    args = ap.parse_args()

    out_csv = Path(args.out) if args.out else OUT_CSV

    rows = load_ocr_rows()
    log(f"ocr rows available (local poster exists): {len(rows):,}")
    sample = pick_sample(rows, args.n, args.seed)
    done = load_done(out_csv)
    todo = [r for r in sample if r["id"] not in done]
    log(f"sample={len(sample):,} done={len(done):,} todo={len(todo):,} workers={args.workers}")

    client = boto3.Session(profile_name=os.environ.get("AWS_PROFILE")).client(
        "bedrock-runtime", region_name=args.region,
        config=Config(retries={"max_attempts": 8, "mode": "adaptive"}),
    )

    t0 = time.time()
    n_done = 0
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(process_one, client, r, out_csv): r for r in todo}
        for fut in as_completed(futs):
            fut.result()
            n_done += 1
            if n_done % 50 == 0 or n_done == len(todo):
                rate = n_done / max(time.time() - t0, 1e-9)
                log(f"  {n_done:,}/{len(todo):,} rate={rate:.1f}/s")

    counts: dict[str, int] = {}
    with out_csv.open(encoding="utf-8", errors="replace") as f:
        for r in csv.DictReader(f):
            if r.get("status") == "ok":
                counts[r["verdict"]] = counts.get(r["verdict"], 0) + 1
    log(f"LISTO -> {out_csv} | {counts}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

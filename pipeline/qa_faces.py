#!/usr/bin/env python3
"""Nova vision QA of Rekognition DetectFaces counts (faces_v2_*.csv).

Cross-checks Rekognition's n_faces against an independent Nova Pro count on
the same poster. Illustrated/painted posters are the suspected weak spot --
stylized faces may be missed (false negatives) or ordinary imagery may be
misread (false positives).

  export AWS_PROFILE=sandbox
  python3 qa_faces.py --n 2000 --workers 12
  python3 qa_faces.py --n 999999 --workers 30   # full coverage
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
    DATA / "faces_v2.csv",
    DATA / "faces_v2_scifi.csv",
    DATA / "faces_v2_thriller.csv",
    DATA / "faces_v2_mystery.csv",
]
OUT_CSV = DATA / "qa" / "qa_faces.csv"
REGION = "us-east-1"
MODEL_ID = "us.amazon.nova-pro-v1:0"
MAX_SIDE = 1200

FIELDS = [
    "id", "rek_n_faces",
    "model", "status", "nova_n_faces", "agree_exact", "agree_bucket", "reason", "latency_s", "error",
]

PROMPT = """Count how many distinct human (or human-like, e.g. zombie/monster with a
clearly face-like visage) faces are visible on this movie poster -- count faces that
are recognizable as faces, even if partial, stylized, illustrated, or in shadow.
Do not count silhouettes with no facial features, or faces too tiny/abstract to make out.

AWS Rekognition's face detector counted {rek_n} face(s) on this poster.
Give your OWN independent count.

Return ONLY valid JSON (no markdown):
{{
  "n_faces": <integer count you see>,
  "reason": "one short sentence"
}}
"""

_write_lock = threading.Lock()


def log(msg: str) -> None:
    print(msg, flush=True)


def bucket(n: int) -> str:
    if n == 0:
        return "0"
    if n == 1:
        return "1"
    if n <= 3:
        return "2-3"
    return "4+"


def load_rows() -> list[dict]:
    rows: list[dict] = []
    seen: set[int] = set()
    for src in SRC_FILES:
        if not src.exists():
            continue
        with src.open(encoding="utf-8", errors="replace") as f:
            for r in csv.DictReader(f):
                try:
                    pid = int(r["id"])
                    n_faces = int(float(r.get("n_faces") or 0))
                except Exception:
                    continue
                if pid in seen:
                    continue
                seen.add(pid)
                rows.append({"id": pid, "rek_n_faces": n_faces})
    with ThreadPoolExecutor(max_workers=64) as ex:
        exists = list(ex.map(lambda r: (POSTERS / f"{r['id']}.jpg").exists(), rows))
    rows = [r for r, ok in zip(rows, exists) if ok]
    return rows


def pick_sample(rows: list[dict], n: int, seed: int) -> list[dict]:
    # stratify by bucket so the (large) zero-face pool doesn't dominate
    by_bucket: dict[str, list[dict]] = {}
    for r in rows:
        by_bucket.setdefault(bucket(r["rek_n_faces"]), []).append(r)
    rng = random.Random(seed)
    buckets = list(by_bucket)
    per_bucket = max(1, n // max(1, len(buckets)))
    picked: list[dict] = []
    for b in buckets:
        bk = by_bucket[b][:]
        rng.shuffle(bk)
        picked.extend(bk[:per_bucket])
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
        "id": r["id"], "rek_n_faces": r["rek_n_faces"],
        "model": "nova-pro", "status": "error",
        "nova_n_faces": "", "agree_exact": "", "agree_bucket": "", "reason": "", "latency_s": 0.0, "error": "",
    }
    t0 = time.perf_counter()
    try:
        img = resize_jpeg(POSTERS / f"{r['id']}.jpg")
        prompt = PROMPT.format(rek_n=r["rek_n_faces"])
        resp = client.converse(
            modelId=MODEL_ID,
            messages=[{"role": "user", "content": [
                {"image": {"format": "jpeg", "source": {"bytes": img}}},
                {"text": prompt},
            ]}],
            inferenceConfig={"temperature": 0, "maxTokens": 150},
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
        nova_n = int(obj.get("n_faces", -1))
        base.update(
            status="ok",
            nova_n_faces=nova_n,
            agree_exact=str(nova_n == r["rek_n_faces"]),
            agree_bucket=str(bucket(nova_n) == bucket(r["rek_n_faces"])),
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

    rows = load_rows()
    log(f"face rows available (local poster exists): {len(rows):,}")
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

    exact = bucket_agree = disagree = 0
    with out_csv.open(encoding="utf-8", errors="replace") as f:
        for r in csv.DictReader(f):
            if r.get("status") != "ok":
                continue
            if r["agree_exact"] == "True":
                exact += 1
            elif r["agree_bucket"] == "True":
                bucket_agree += 1
            else:
                disagree += 1
    total = exact + bucket_agree + disagree
    log(f"LISTO -> {out_csv} | exact={exact:,} ({exact/max(total,1):.1%}) bucket_ok={bucket_agree:,} disagree={disagree:,}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

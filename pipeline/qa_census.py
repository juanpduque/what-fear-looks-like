#!/usr/bin/env python3
"""Nova vision QA of the CLIP-based monster census (clip_census.py).

Cross-checks CLIP zero-shot embedding-similarity labels against an
independent Nova Pro judgment on the same poster.

  export AWS_PROFILE=sandbox
  python3 qa_census.py --n 2000 --workers 12
  python3 qa_census.py --n 999999 --workers 30   # full coverage
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
    DATA / "census.csv",
    DATA / "census_scifi.csv",
    DATA / "census_thriller.csv",
    DATA / "census_mystery.csv",
]
OUT_CSV = DATA / "qa" / "qa_census.csv"
REGION = "us-east-1"
MODEL_ID = "us.amazon.nova-pro-v1:0"
MAX_SIDE = 1200

CATEGORIES = [
    "vampire", "werewolf", "zombie", "ghost", "demon", "witch", "skeleton",
    "alien", "giant_monster", "masked_killer", "clown", "doll", "shark",
    "spider", "snake", "wolf_dog", "bird", "insect", "none",
]

FIELDS = [
    "id", "clip_label", "clip_score",
    "model", "status", "nova_label", "agree", "reason", "latency_s", "error",
]

PROMPT = """Classify the main creature/monster/threat shown on this movie poster into
EXACTLY ONE of these categories: {categories}

- Pick "none" if there's no monster/creature -- just ordinary people, a generic villain
  with no supernatural/creature element, or abstract imagery.
- "masked_killer" = a human-shaped masked/costumed killer with a weapon (slasher-style),
  not a supernatural creature.
- "wolf_dog" = a real/mundane dog or wolf, not a transformed werewolf.
- "giant_monster" = kaiju-scale monster (city-destroying size).

A CLIP zero-shot embedding classifier already predicted "{clip_label}"
(similarity score {clip_score}). Give your OWN independent judgment.

Return ONLY valid JSON (no markdown):
{{
  "label": "<one of the categories above, exact spelling>",
  "reason": "one short sentence"
}}
"""

_write_lock = threading.Lock()


def log(msg: str) -> None:
    print(msg, flush=True)


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
                except Exception:
                    continue
                if pid in seen:
                    continue
                seen.add(pid)
                rows.append({
                    "id": pid,
                    "clip_label": (r.get("label") or "").strip(),
                    "clip_score": r.get("score") or "0",
                })
    with ThreadPoolExecutor(max_workers=64) as ex:
        exists = list(ex.map(lambda r: (POSTERS / f"{r['id']}.jpg").exists(), rows))
    rows = [r for r, ok in zip(rows, exists) if ok]
    return rows


def pick_sample(rows: list[dict], n: int, seed: int) -> list[dict]:
    by_label: dict[str, list[dict]] = {}
    for r in rows:
        by_label.setdefault(r["clip_label"], []).append(r)
    rng = random.Random(seed)
    labels = list(by_label)
    per_label = max(1, n // max(1, len(labels)))
    picked: list[dict] = []
    for lab in labels:
        bucket = by_label[lab]
        bucket.sort(key=lambda r: float(r["clip_score"] or 0))  # low confidence first
        low = bucket[: int(per_label * 0.7)]
        rest = bucket[int(per_label * 0.7):]
        rng.shuffle(rest)
        picked.extend(low + rest[: per_label - len(low)])
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
        "id": r["id"], "clip_label": r["clip_label"], "clip_score": r["clip_score"],
        "model": "nova-pro", "status": "error",
        "nova_label": "", "agree": "", "reason": "", "latency_s": 0.0, "error": "",
    }
    t0 = time.perf_counter()
    try:
        img = resize_jpeg(POSTERS / f"{r['id']}.jpg")
        prompt = PROMPT.format(
            categories=", ".join(CATEGORIES),
            clip_label=r["clip_label"] or "uncertain",
            clip_score=r["clip_score"],
        )
        resp = client.converse(
            modelId=MODEL_ID,
            messages=[{"role": "user", "content": [
                {"image": {"format": "jpeg", "source": {"bytes": img}}},
                {"text": prompt},
            ]}],
            inferenceConfig={"temperature": 0, "maxTokens": 200},
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
        nova_label = obj.get("label", "")
        base.update(
            status="ok",
            nova_label=nova_label,
            agree=str(nova_label == r["clip_label"]),
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
    log(f"census rows available (local poster exists): {len(rows):,}")
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

    agree = disagree = 0
    with out_csv.open(encoding="utf-8", errors="replace") as f:
        for r in csv.DictReader(f):
            if r.get("status") != "ok":
                continue
            a = r["agree"] == "True"
            agree += a
            disagree += not a
    total = agree + disagree
    log(f"LISTO -> {out_csv} | agree={agree:,} ({agree/max(total,1):.1%}) disagree={disagree:,}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

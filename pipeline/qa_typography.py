#!/usr/bin/env python3
"""Nova vision QA of the CLIP-based typography register (clip_typography_axis.py).

Cross-checks CLIP zero-shot embedding-axis register (ornate<->clean, binned into
5 buckets) against an independent Nova Pro judgment on the same poster's title
lettering style.

  export AWS_PROFILE=sandbox
  python3 qa_typography.py --n 2000 --workers 12
  python3 qa_typography.py --n 999999 --workers 30   # full coverage
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
    DATA / "typography.csv",
    DATA / "typography_scifi.csv",
    DATA / "typography_thriller.csv",
    DATA / "typography_mystery.csv",
]
OUT_CSV = DATA / "qa" / "qa_typography.csv"
REGION = "us-east-1"
MODEL_ID = "us.amazon.nova-pro-v1:0"
MAX_SIDE = 1200

REGISTERS = ["ornate", "decorative", "standard", "clean", "minimal"]

FIELDS = [
    "id", "clip_register", "clip_axis",
    "model", "status", "nova_register", "agree", "agree_adjacent", "reason", "latency_s", "error",
]

PROMPT = """Look at the movie TITLE LETTERING on this poster (ignore tagline/credits/small
print). Classify its style into EXACTLY ONE of these 5 points on a spectrum:

- "ornate": heavily decorative, hand-drawn/painted, dripping/textured, elaborate flourishes
- "decorative": stylized display type with some flourish/texture, but not full illustration
- "standard": a normal bold display font, some character but not heavily stylized
- "clean": simple bold sans-serif or serif, minimal styling
- "minimal": plain, thin, minimal-impact typography, almost utilitarian

A CLIP zero-shot embedding classifier already predicted "{clip_register}"
(axis score {clip_axis}, where higher = more ornate). Give your OWN independent judgment.

Return ONLY valid JSON (no markdown):
{{
  "register": "ornate" | "decorative" | "standard" | "clean" | "minimal",
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
                    "clip_register": (r.get("register") or "").strip(),
                    "clip_axis": r.get("axis") or "0",
                })
    with ThreadPoolExecutor(max_workers=64) as ex:
        exists = list(ex.map(lambda r: (POSTERS / f"{r['id']}.jpg").exists(), rows))
    rows = [r for r, ok in zip(rows, exists) if ok]
    return rows


def pick_sample(rows: list[dict], n: int, seed: int) -> list[dict]:
    by_reg: dict[str, list[dict]] = {}
    for r in rows:
        by_reg.setdefault(r["clip_register"], []).append(r)
    rng = random.Random(seed)
    regs = list(by_reg)
    per_reg = max(1, n // max(1, len(regs)))
    picked: list[dict] = []
    for reg in regs:
        bucket = by_reg[reg][:]
        rng.shuffle(bucket)
        picked.extend(bucket[:per_reg])
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
        "id": r["id"], "clip_register": r["clip_register"], "clip_axis": r["clip_axis"],
        "model": "nova-pro", "status": "error",
        "nova_register": "", "agree": "", "agree_adjacent": "", "reason": "", "latency_s": 0.0, "error": "",
    }
    t0 = time.perf_counter()
    try:
        img = resize_jpeg(POSTERS / f"{r['id']}.jpg")
        prompt = PROMPT.format(clip_register=r["clip_register"] or "standard", clip_axis=r["clip_axis"])
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
        nova_reg = obj.get("register", "")
        clip_idx = REGISTERS.index(r["clip_register"]) if r["clip_register"] in REGISTERS else -99
        nova_idx = REGISTERS.index(nova_reg) if nova_reg in REGISTERS else -99
        base.update(
            status="ok",
            nova_register=nova_reg,
            agree=str(nova_reg == r["clip_register"]),
            agree_adjacent=str(abs(clip_idx - nova_idx) <= 1),
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
    log(f"typography rows available (local poster exists): {len(rows):,}")
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

    agree = adjacent = disagree = 0
    with out_csv.open(encoding="utf-8", errors="replace") as f:
        for r in csv.DictReader(f):
            if r.get("status") != "ok":
                continue
            if r["agree"] == "True":
                agree += 1
            elif r["agree_adjacent"] == "True":
                adjacent += 1
            else:
                disagree += 1
    total = agree + adjacent + disagree
    log(f"LISTO -> {out_csv} | exact={agree:,} ({agree/max(total,1):.1%}) adjacent={adjacent:,} disagree={disagree:,}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

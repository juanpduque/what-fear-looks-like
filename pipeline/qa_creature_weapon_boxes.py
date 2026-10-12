#!/usr/bin/env python3
"""Nova vision QA of OWLv2 creature/weapon box detections.

OWLv2 is zero-shot (open-vocabulary), run at --min-score 0.2 across the whole
corpus. That threshold is loose on purpose (better to over-detect and filter
later), but it means a large share of boxes are likely false positives --
53% of weapon detections and 40% of creature detections score under 0.3.
This draws the detected box on the poster and asks Nova Pro to judge whether
it's really there.

Samples are stratified toward low-confidence detections (where errors
concentrate), with some high-confidence ones kept for calibration.

  export AWS_PROFILE=sandbox
  python3 qa_creature_weapon_boxes.py --n 1000 --workers 12
  python3 qa_creature_weapon_boxes.py --kind weapon --n 500
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import random
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import boto3
from botocore.config import Config
from PIL import Image, ImageDraw

DATA = Path(__file__).resolve().parent / "data"
POSTERS = DATA / "posters"
CREATURE_JSON = DATA / "creature_boxes.json"
WEAPON_JSON = DATA / "weapon_boxes.json"
OUT_CSV = DATA / "qa" / "qa_creature_weapon_boxes.csv"
OUT_JSONL = DATA / "qa" / "qa_creature_weapon_boxes.jsonl"
REGION = "us-east-1"
MODEL_ID = "us.amazon.nova-pro-v1:0"
MAX_SIDE = 1200

FIELDS = [
    "id",
    "kind",
    "label",
    "score",
    "box",
    "model",
    "status",
    "verdict",
    "actual",
    "reason",
    "latency_s",
    "error",
]

PROMPT = """A computer vision model (OWLv2, zero-shot/open-vocabulary object detection)
found "{label}" inside the RED rectangle drawn on this movie poster, with confidence {score:.2f}.

Judge whether that red rectangle actually contains a "{label}" (or something close enough
to reasonably count -- e.g. "wolf" for a generic canine, "knife" for any bladed weapon).

Return ONLY valid JSON (no markdown):
{{
  "verdict": "correct" | "false_positive" | "uncertain",
  "actual": "what's actually in the box, in a few words",
  "reason": "one short sentence"
}}

Rules:
- correct: the label is a reasonable description of what's in the red box.
- false_positive: the red box contains something clearly different (background, a person's
  face, unrelated object, empty space, text, etc).
- uncertain: the box is too small/blurry/cropped-at-edge to tell confidently.
"""

_write_lock = threading.Lock()


def log(msg: str) -> None:
    print(msg, flush=True)


def load_detections(kind_filter: str) -> list[dict]:
    rows = []
    if kind_filter in ("all", "creature") and CREATURE_JSON.exists():
        data = json.loads(CREATURE_JSON.read_text())
        for pid, dets in data.items():
            for d in dets:
                rows.append({"id": int(pid), "kind": "creature", **d})
    if kind_filter in ("all", "weapon") and WEAPON_JSON.exists():
        data = json.loads(WEAPON_JSON.read_text())
        for pid, dets in data.items():
            for d in dets:
                rows.append({"id": int(pid), "kind": "weapon", **d})
    with ThreadPoolExecutor(max_workers=64) as ex:
        exists = list(ex.map(lambda r: (POSTERS / f"{r['id']}.jpg").exists(), rows))
    rows = [r for r, ok in zip(rows, exists) if ok]
    return rows


def pick_sample(rows: list[dict], n: int, seed: int) -> list[dict]:
    low = [r for r in rows if r["score"] < 0.3]
    mid = [r for r in rows if 0.3 <= r["score"] < 0.5]
    high = [r for r in rows if r["score"] >= 0.5]
    rng = random.Random(seed)
    for bucket in (low, mid, high):
        rng.shuffle(bucket)
    # 60% low-confidence (most likely wrong), 25% mid, 15% high (calibration)
    n0 = min(len(low), int(round(n * 0.60)))
    n1 = min(len(mid), int(round(n * 0.25)))
    n2 = min(len(high), n - n0 - n1)
    picked = low[:n0] + mid[:n1] + high[:n2]
    if len(picked) < n:
        used = {(r["id"], r["kind"], r["label"], tuple(r["box"])) for r in picked}
        for r in low + mid + high:
            key = (r["id"], r["kind"], r["label"], tuple(r["box"]))
            if key in used:
                continue
            picked.append(r)
            if len(picked) >= n:
                break
    rng.shuffle(picked)
    return picked[:n]


def draw_box(path: Path, box: list[float]) -> bytes:
    im = Image.open(path).convert("RGB")
    w, h = im.size
    scale = min(1.0, MAX_SIDE / float(max(w, h)))
    if scale < 1.0:
        im = im.resize((max(1, int(w * scale)), max(1, int(h * scale))), Image.Resampling.LANCZOS)
        w, h = im.size
    x, y, bw, bh = box
    x0, y0 = x * w, y * h
    x1, y1 = x0 + bw * w, y0 + bh * h
    draw = ImageDraw.Draw(im)
    lw = max(3, int(min(w, h) * 0.006))
    draw.rectangle([x0, y0, x1, y1], outline=(255, 0, 0), width=lw)
    import io

    buf = io.BytesIO()
    im.save(buf, format="JPEG", quality=90)
    return buf.getvalue()


def load_done(path: Path) -> set[tuple]:
    done = set()
    if not path.exists():
        return done
    with path.open(encoding="utf-8", errors="replace") as f:
        for r in csv.DictReader(f):
            if r.get("status") == "ok":
                done.add((int(r["id"]), r["kind"], r["label"], r["box"]))
    return done


def append_row(path: Path, row: dict) -> None:
    new_file = not path.exists()
    with _write_lock:
        with path.open("a", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=FIELDS)
            if new_file:
                w.writeheader()
            w.writerow(row)


def append_jsonl(path: Path, obj: dict) -> None:
    with _write_lock:
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(obj, ensure_ascii=False) + "\n")


def process_one(client, r: dict, out_csv: Path, out_jsonl: Path) -> None:
    box_str = json.dumps(r["box"])
    base = {
        "id": r["id"],
        "kind": r["kind"],
        "label": r["label"],
        "score": r["score"],
        "box": box_str,
        "model": "nova-pro",
        "status": "error",
        "verdict": "",
        "actual": "",
        "reason": "",
        "latency_s": 0.0,
        "error": "",
    }
    t0 = time.perf_counter()
    try:
        img = draw_box(POSTERS / f"{r['id']}.jpg", r["box"])
        prompt = PROMPT.format(label=r["label"], score=r["score"])
        resp = client.converse(
            modelId=MODEL_ID,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"image": {"format": "jpeg", "source": {"bytes": img}}},
                        {"text": prompt},
                    ],
                }
            ],
            inferenceConfig={"temperature": 0, "maxTokens": 300},
        )
        text = "".join(
            b.get("text", "")
            for b in resp.get("output", {}).get("message", {}).get("content", [])
            if "text" in b
        ).strip()
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
        obj = json.loads(text)
        base.update(
            status="ok",
            verdict=obj.get("verdict", ""),
            actual=obj.get("actual", ""),
            reason=obj.get("reason", ""),
            latency_s=round(time.perf_counter() - t0, 3),
        )
        append_jsonl(
            out_jsonl,
            {
                "id": r["id"],
                "kind": r["kind"],
                "label": r["label"],
                "raw": obj,
                "text": text[:2000],
            },
        )
    except Exception as e:
        base["error"] = f"{type(e).__name__}: {e}"[:400]
        base["latency_s"] = round(time.perf_counter() - t0, 3)
    append_row(out_csv, base)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--kind", choices=["all", "creature", "weapon"], default="all")
    ap.add_argument("--n", type=int, default=1000)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--workers", type=int, default=12)
    ap.add_argument("--min-interval", type=float, default=0.1)
    ap.add_argument("--out", default="")
    ap.add_argument("--region", default=REGION)
    args = ap.parse_args()

    out_csv = Path(args.out) if args.out else OUT_CSV
    out_jsonl = out_csv.with_suffix(".jsonl")

    rows = load_detections(args.kind)
    log(f"detections available (kind={args.kind}, local poster exists): {len(rows):,}")
    sample = pick_sample(rows, args.n, args.seed)
    done = load_done(out_csv)
    todo = [r for r in sample if (r["id"], r["kind"], r["label"], json.dumps(r["box"])) not in done]
    log(f"sample={len(sample):,} done={len(done):,} todo={len(todo):,} workers={args.workers}")

    client = boto3.Session(profile_name=os.environ.get("AWS_PROFILE")).client(
        "bedrock-runtime",
        region_name=args.region,
        config=Config(retries={"max_attempts": 8, "mode": "adaptive"}),
    )

    t0 = time.time()
    n_done = 0
    verdict_counts: dict[str, int] = {}
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(process_one, client, r, out_csv, out_jsonl): r for r in todo}
        for fut in as_completed(futs):
            fut.result()
            n_done += 1
            if args.min_interval:
                time.sleep(args.min_interval / args.workers)
            if n_done % 50 == 0 or n_done == len(todo):
                rate = n_done / max(time.time() - t0, 1e-9)
                log(f"  {n_done:,}/{len(todo):,} rate={rate:.1f}/s")

    with out_csv.open(encoding="utf-8", errors="replace") as f:
        for r in csv.DictReader(f):
            if r.get("status") == "ok":
                verdict_counts[r["verdict"]] = verdict_counts.get(r["verdict"], 0) + 1
    log(f"LISTO -> {out_csv} | {verdict_counts}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

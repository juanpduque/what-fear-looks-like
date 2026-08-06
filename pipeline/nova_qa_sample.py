#!/usr/bin/env python3
"""Stratified vision-LLM QA samples for article comparisons.

Does NOT overwrite nova_enrich.csv. Default small sample stays at:
  data/qa/nova_qa_sample.csv

Larger / other tiers use --out (never clobber unless you pass the same path):
  python3 nova_qa_sample.py --per-decade 30 --out data/qa/nova_qa_large.csv \\
      --models nova-pro,claude-haiku,pixtral,llama4-scout
  python3 nova_qa_sample.py --reuse-sample --reuse-from data/qa/nova_qa_large.csv \\
      --out data/qa/nova_qa_sonnet.csv --models claude-sonnet
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import random
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import boto3
import pandas as pd
from botocore.config import Config
from botocore.exceptions import ClientError
from PIL import Image

DATA = Path(__file__).resolve().parent / "data"
POSTERS = DATA / "posters"
OUT_DIR = DATA / "qa"
DEFAULT_OUT_CSV = OUT_DIR / "nova_qa_sample.csv"
DEFAULT_OUT_JSONL = OUT_DIR / "nova_qa_sample.jsonl"
REGION = "us-east-1"
MAX_SIDE = 1024
MAX_BYTES = 4_000_000

# Mutated in main() when --out is set
OUT_CSV = DEFAULT_OUT_CSV
OUT_JSONL = DEFAULT_OUT_JSONL

MODELS = {
    "nova-pro": "us.amazon.nova-pro-v1:0",
    "claude-haiku": "us.anthropic.claude-haiku-4-5-20251001-v1:0",
    "pixtral": "us.mistral.pixtral-large-2502-v1:0",
    "llama4-scout": "us.meta.llama4-scout-17b-instruct-v1:0",
    "claude-sonnet": "us.anthropic.claude-sonnet-4-5-20250929-v1:0",
    "llama4-maverick": "us.meta.llama4-maverick-17b-instruct-v1:0",
}

QA_PROMPT = """You analyze a horror movie poster for editorial QA.
Return ONLY valid JSON (no markdown) with this schema:
{
  "title_guess": "main title as printed, or empty",
  "typography": "ornate|mixed|minimal|block|script|other",
  "typography_notes": "one short sentence on lettering",
  "mood": ["up to 5 mood tags"],
  "caption_essay": "1-2 sentence vivid but factual caption for a visual essay (max 40 words)",
  "lite_risk": "json_break|hallucination|low_signal|ok",
  "notes": "optional short QA note"
}
"""

FIELDS = [
    "id",
    "title",
    "year",
    "decade",
    "model",
    "model_id",
    "status",
    "latency_s",
    "title_guess",
    "typography",
    "typography_notes",
    "mood",
    "caption_essay",
    "lite_risk",
    "notes",
    "raw_text",
    "error",
]

_print_lock = threading.Lock()
_write_lock = threading.Lock()


def log(msg: str) -> None:
    with _print_lock:
        print(msg, flush=True)


def resize_bytes(path: Path) -> tuple[bytes, str]:
    im = Image.open(path).convert("RGB")
    w, h = im.size
    scale = min(1.0, MAX_SIDE / float(max(w, h)))
    if scale < 1.0:
        im = im.resize((max(1, int(w * scale)), max(1, int(h * scale))), Image.Resampling.LANCZOS)
    q = 85
    buf = io.BytesIO()
    im.save(buf, format="JPEG", quality=q, optimize=True)
    data = buf.getvalue()
    while len(data) > MAX_BYTES and q > 40:
        q -= 10
        buf = io.BytesIO()
        im.save(buf, format="JPEG", quality=q, optimize=True)
        data = buf.getvalue()
    return data, "jpeg"


def strip_json(text: str) -> dict:
    import re

    t = (text or "").strip()
    if t.startswith("```"):
        t = re.sub(r"^```(?:json)?\s*", "", t)
        t = re.sub(r"\s*```$", "", t)
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", t, flags=re.S)
        if not m:
            raise
        blob = re.sub(r",\s*([}\]])", r"\1", m.group(0))
        return json.loads(blob)


def _meta_frame() -> pd.DataFrame:
    meta = pd.read_csv(DATA / "posters.csv", usecols=["id", "title", "year"])
    meta["id"] = meta["id"].astype(int)
    meta["year"] = pd.to_numeric(meta["year"], errors="coerce")
    meta = meta[meta["year"].notna()].copy()
    meta["year"] = meta["year"].astype(int)
    # drop bogus sentinel years
    meta = meta[(meta["year"] >= 1890) & (meta["year"] <= 2030)].copy()
    meta["decade"] = (meta["year"] // 10 * 10).astype(int)
    return meta[meta["id"].map(lambda i: (POSTERS / f"{i}.jpg").exists())].copy()


def sample_from_existing_csv(path: Path) -> pd.DataFrame:
    """Reuse exact poster ids already in a QA CSV (same 119 for new models)."""
    ids: list[int] = []
    seen: set[int] = set()
    with path.open(encoding="utf-8", errors="replace") as f:
        for r in csv.DictReader(f):
            try:
                pid = int(r["id"])
            except Exception:
                continue
            if pid not in seen:
                seen.add(pid)
                ids.append(pid)
    meta = _meta_frame().set_index("id")
    rows = []
    for pid in ids:
        if pid not in meta.index:
            continue
        rec = meta.loc[pid]
        rows.append(
            {
                "id": pid,
                "title": rec["title"],
                "year": rec["year"],
                "decade": int(rec["decade"]),
            }
        )
    return pd.DataFrame(rows)


def pick_sample(per_decade: int, seed: int, prefer_lite_errors: bool) -> pd.DataFrame:
    meta = _meta_frame()

    err_ids: set[int] = set()
    err_path = DATA / "qa" / "nova_enrich" / "nova_enrich_errors.csv"
    if prefer_lite_errors and err_path.exists():
        with err_path.open(encoding="utf-8", errors="replace") as f:
            for r in csv.DictReader(f):
                if "JSONDecodeError" in (r.get("error") or ""):
                    try:
                        err_ids.add(int(r["id"]))
                    except Exception:
                        pass

    rng = random.Random(seed)
    parts = []
    for decade, g in meta.groupby("decade"):
        g = g.copy()
        prefer = g[g["id"].isin(err_ids)]
        rest = g[~g["id"].isin(err_ids)]
        take = []
        n_pref = min(len(prefer), max(1, per_decade // 2)) if len(prefer) else 0
        if n_pref:
            take.extend(prefer.sample(n=n_pref, random_state=seed).to_dict("records"))
        need = per_decade - len(take)
        if need > 0 and len(rest):
            take.extend(rest.sample(n=min(need, len(rest)), random_state=seed + int(decade)).to_dict("records"))
        parts.extend(take)
    rng.shuffle(parts)
    return pd.DataFrame(parts)


def load_done(path: Path | None = None) -> set[tuple[int, str]]:
    done = set()
    p = path or OUT_CSV
    if not p.exists():
        return done
    with p.open(encoding="utf-8", errors="replace") as f:
        for r in csv.DictReader(f):
            if r.get("status") == "ok":
                try:
                    done.add((int(r["id"]), str(r["model"])))
                except Exception:
                    pass
    return done


def append_row(row: dict, out_csv: Path | None = None, out_jsonl: Path | None = None) -> None:
    csv_path = out_csv or OUT_CSV
    jsonl_path = out_jsonl or OUT_JSONL
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with _write_lock:
        write_header = not csv_path.exists() or csv_path.stat().st_size == 0
        with csv_path.open("a", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore")
            if write_header:
                w.writeheader()
            w.writerow(row)
        with jsonl_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def run_one(client, model: str, model_id: str, rec: dict) -> dict:
    pid = int(rec["id"])
    t0 = time.perf_counter()
    path = POSTERS / f"{pid}.jpg"
    base = {
        "id": pid,
        "title": rec.get("title") or "",
        "year": rec.get("year") or "",
        "decade": rec.get("decade") or "",
        "model": model,
        "model_id": model_id,
        "status": "error",
        "latency_s": 0.0,
        "title_guess": "",
        "typography": "",
        "typography_notes": "",
        "mood": "",
        "caption_essay": "",
        "lite_risk": "",
        "notes": "",
        "raw_text": "",
        "error": "",
    }
    try:
        raw, fmt = resize_bytes(path)
        last = None
        for attempt in range(5):
            try:
                resp = client.converse(
                    modelId=model_id,
                    messages=[
                        {
                            "role": "user",
                            "content": [
                                {"image": {"format": fmt, "source": {"bytes": raw}}},
                                {"text": QA_PROMPT},
                            ],
                        }
                    ],
                    inferenceConfig={"temperature": 0, "maxTokens": 500},
                )
                break
            except ClientError as e:
                last = e
                code = e.response.get("Error", {}).get("Code", "")
                if code in ("ThrottlingException", "TooManyRequestsException"):
                    time.sleep(min(16, 1.5 * (2**attempt)))
                    continue
                raise
        else:
            raise last  # type: ignore
        text = "".join(
            b.get("text", "")
            for b in resp.get("output", {}).get("message", {}).get("content", [])
            if "text" in b
        )
        data = strip_json(text)
        mood = data.get("mood")
        if isinstance(mood, list):
            mood = "|".join(str(x) for x in mood)
        base.update(
            {
                "status": "ok",
                "latency_s": round(time.perf_counter() - t0, 3),
                "title_guess": str(data.get("title_guess") or ""),
                "typography": str(data.get("typography") or ""),
                "typography_notes": str(data.get("typography_notes") or ""),
                "mood": str(mood or ""),
                "caption_essay": str(data.get("caption_essay") or ""),
                "lite_risk": str(data.get("lite_risk") or ""),
                "notes": str(data.get("notes") or ""),
                "raw_text": text[:2000],
            }
        )
        return base
    except Exception as e:
        base["latency_s"] = round(time.perf_counter() - t0, 3)
        base["error"] = f"{type(e).__name__}: {e}"[:300]
        return base


def main() -> int:
    global OUT_CSV, OUT_JSONL

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--per-decade", type=int, default=8)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--models", default="nova-pro,claude-haiku")
    ap.add_argument("--region", default=REGION)
    ap.add_argument("--no-prefer-errors", action="store_true")
    ap.add_argument(
        "--out",
        type=Path,
        default=None,
        help="output CSV path (default: data/qa/nova_qa_sample.csv). jsonl = same stem .jsonl",
    )
    ap.add_argument(
        "--reuse-sample",
        action="store_true",
        help="reuse poster ids from an existing QA CSV",
    )
    ap.add_argument(
        "--reuse-from",
        type=Path,
        default=None,
        help="CSV to read ids from when --reuse-sample (default: --out or nova_qa_sample.csv)",
    )
    args = ap.parse_args()

    if args.out is not None:
        OUT_CSV = args.out
        OUT_JSONL = args.out.with_suffix(".jsonl")
    else:
        OUT_CSV = DEFAULT_OUT_CSV
        OUT_JSONL = DEFAULT_OUT_JSONL

    # Safety: refuse to wipe by truncating; we only append. Still warn if targeting small sample path with large run.
    models = [m.strip() for m in args.models.split(",") if m.strip()]
    for m in models:
        if m not in MODELS:
            raise SystemExit(f"unknown model {m}; choose from {list(MODELS)}")

    if args.reuse_sample:
        src = args.reuse_from or OUT_CSV
        if not src.exists():
            raise SystemExit(f"--reuse-sample requires existing {src}")
        sample = sample_from_existing_csv(src)
    else:
        sample = pick_sample(args.per_decade, args.seed, prefer_lite_errors=not args.no_prefer_errors)
    done = load_done(OUT_CSV)
    jobs = []
    for rec in sample.to_dict("records"):
        for m in models:
            if (int(rec["id"]), m) not in done:
                jobs.append((m, MODELS[m], rec))

    log(
        f"QA sample n_posters={len(sample)} jobs={len(jobs)} models={models} "
        f"workers={args.workers} out={OUT_CSV}"
    )
    client = boto3.client(
        "bedrock-runtime",
        region_name=args.region,
        config=Config(read_timeout=120, retries={"max_attempts": 3}, max_pool_connections=max(args.workers + 4, 10)),
    )

    t0 = time.time()
    ok = err = 0
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as ex:
        futs = [ex.submit(run_one, client, m, mid, rec) for m, mid, rec in jobs]
        for i, fut in enumerate(as_completed(futs), 1):
            row = fut.result()
            append_row(row, OUT_CSV, OUT_JSONL)
            if row["status"] == "ok":
                ok += 1
            else:
                err += 1
            if i % 10 == 0 or i == len(jobs):
                log(
                    f"  {i}/{len(jobs)} ok={ok} err={err} "
                    f"id={row['id']} model={row['model']} "
                    f"risk={row.get('lite_risk') or '-'} "
                    f"{(time.time()-t0):.0f}s"
                )
    log(f"done → {OUT_CSV} ok={ok} err={err}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

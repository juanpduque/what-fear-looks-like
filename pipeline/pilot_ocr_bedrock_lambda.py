#!/usr/bin/env python3
"""OCR pilot via sandbox Bedrock Lambda bridge.

Workshop Studio blocks direct InvokeModel on inference profiles for
WSParticipantRole. This runner calls Lambda ``poster-ocr-bedrock`` which
uses the Strands travel-agent role (bedrock:InvokeModel *).

  export AWS_PROFILE=sandbox
  python3 pilot_ocr_bedrock_lambda.py --models claude-haiku --limit 5
  python3 pilot_ocr_bedrock_lambda.py --models claude,nova-2-lite

Merges into data/qa/ocr_pilot_v2/results.csv; skips status=ok by default.
"""
from __future__ import annotations

import argparse
import base64
import csv
import json
import re
import sys
import time
import traceback
from pathlib import Path

import boto3
import pandas as pd
from botocore.exceptions import BotoCoreError, ClientError

from ocr_metrics import title_overlap_score

DATA = Path(__file__).resolve().parent / "data"
POSTERS = DATA / "posters"
POSTERS_CSV = DATA / "posters.csv"
DEFAULT_OUT_DIR = DATA / "qa" / "ocr_pilot_v2"
OUT_DIR = DEFAULT_OUT_DIR
RESULTS_CSV = OUT_DIR / "results.csv"

RESULT_FIELDS = [
    "id",
    "title",
    "year",
    "model",
    "text",
    "chars",
    "title_overlap_score",
    "latency_s",
    "status",
]

DEFAULT_LAMBDA_NAME = "poster-ocr-bedrock"
DEFAULT_LAMBDA_REGION = "us-west-2"
OCR_PROMPT = (
    "Extract ALL visible text from this movie poster. "
    "Return plain text only, no commentary."
)

# tag -> (results model column, Bedrock modelId)
MODEL_CATALOG: dict[str, tuple[str, str]] = {
    "nova-lite": ("nova-lite", "us.amazon.nova-lite-v1:0"),
    "nova-pro": ("nova-pro", "us.amazon.nova-pro-v1:0"),
    "nova-2-lite": ("nova-2-lite", "us.amazon.nova-2-lite-v1:0"),
    "claude": ("claude", "us.anthropic.claude-sonnet-4-5-20250929-v1:0"),
    "claude-haiku": ("claude-haiku", "us.anthropic.claude-haiku-4-5-20251001-v1:0"),
    "claude-sonnet-4-6": ("claude-sonnet-4-6", "us.anthropic.claude-sonnet-4-6"),
}


def configure_out_dir(path: str | Path) -> None:
    global OUT_DIR, RESULTS_CSV
    OUT_DIR = Path(path)
    RESULTS_CSV = OUT_DIR / "results.csv"


def load_sample(ids_file: Path) -> pd.DataFrame:
    posters = pd.read_csv(POSTERS_CSV, usecols=["id", "title", "year"])
    posters["id"] = posters["id"].astype(int)
    raw = ids_file.read_text(encoding="utf-8")
    ids = [int(x) for x in re.split(r"[\s,]+", raw.strip()) if x.strip()]
    df = posters[posters["id"].isin(ids)].copy()
    order = {pid: i for i, pid in enumerate(ids)}
    df["_ord"] = df["id"].map(order)
    return df.sort_values("_ord").drop(columns=["_ord"]).reset_index(drop=True)


def write_results(rows: list[dict]) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with RESULTS_CSV.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=RESULT_FIELDS, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)


def append_result(rows: list[dict], row: dict) -> None:
    rows.append(row)
    write_results(rows)
    model_dir = OUT_DIR / row["model"]
    model_dir.mkdir(parents=True, exist_ok=True)
    if row.get("status") == "ok" and row.get("text"):
        raw = str(row["text"]).replace("\\n", "\n")
        (model_dir / f"{row['id']}.txt").write_text(raw, encoding="utf-8")


def make_row(
    pid: int,
    title: str,
    year,
    model: str,
    text: str,
    latency_s: float,
    status: str,
) -> dict:
    ok = status == "ok"
    score = title_overlap_score(text, title) if ok else 0.0
    return {
        "id": pid,
        "title": title,
        "year": year,
        "model": model,
        "text": (text or "").replace("\n", "\\n"),
        "chars": len(text or ""),
        "title_overlap_score": round(float(score), 4) if ok else 0.0,
        "latency_s": round(float(latency_s), 3),
        "status": status,
    }


def invoke_ocr(client, *, lambda_name: str, model_id: str, img: Path) -> str:
    payload = {
        "image_b64": base64.b64encode(img.read_bytes()).decode("ascii"),
        "image_format": "jpeg" if img.suffix.lower() in {".jpg", ".jpeg"} else "png",
        "model_id": model_id,
        "prompt": OCR_PROMPT,
        "max_tokens": 2048,
    }
    resp = client.invoke(
        FunctionName=lambda_name,
        Payload=json.dumps(payload).encode("utf-8"),
    )
    body = json.loads(resp["Payload"].read())
    if resp.get("FunctionError"):
        raise RuntimeError(
            f"lambda error: {body.get('errorType')}: {body.get('errorMessage')}"
        )
    if not isinstance(body, dict) or body.get("statusCode") != 200:
        raise RuntimeError(f"bad lambda response: {body!r}"[:500])
    return str(body.get("text") or "")


def run_model(
    sample: pd.DataFrame,
    rows: list[dict],
    *,
    model_name: str,
    model_id: str,
    skip_done: bool,
    client,
    lambda_name: str,
) -> None:
    print(
        f"\n=== model={model_name} bedrock={model_id} "
        f"via lambda={lambda_name} n={len(sample)} ===",
        flush=True,
    )

    done_ok: set[int] = set()
    if skip_done:
        for r in rows:
            if r.get("model") == model_name and str(r.get("status") or "") == "ok":
                try:
                    done_ok.add(int(r["id"]))
                except (TypeError, ValueError):
                    pass
        if done_ok:
            print(f"  skip {len(done_ok)} already-ok ids", flush=True)

    keep: list[dict] = []
    for r in rows:
        if r.get("model") != model_name:
            keep.append(r)
            continue
        try:
            pid = int(r["id"])
        except (TypeError, ValueError):
            keep.append(r)
            continue
        if skip_done and pid in done_ok:
            keep.append(r)
    rows.clear()
    rows.extend(keep)

    n_todo = sum(1 for _, r in sample.iterrows() if int(r["id"]) not in done_ok)
    if n_todo == 0:
        print(f"  nothing to do for {model_name}", flush=True)
        return

    done_n = 0
    for _, r in sample.iterrows():
        pid = int(r["id"])
        title = str(r.get("title") or "")
        year = r.get("year", "")
        if skip_done and pid in done_ok:
            continue
        done_n += 1
        img = POSTERS / f"{pid}.jpg"
        if not img.exists():
            alt = POSTERS / f"{pid}.png"
            img = alt if alt.exists() else img
        t0 = time.perf_counter()
        status = "ok"
        text = ""
        try:
            if not img.exists():
                raise FileNotFoundError(f"missing {img}")
            text = invoke_ocr(
                client, lambda_name=lambda_name, model_id=model_id, img=img
            )
        except (ClientError, BotoCoreError, OSError, ValueError, RuntimeError) as e:
            status = f"error: {e}"[:500]
            print(f"  [{done_n}/{n_todo}] id={pid} FAIL {status}", flush=True)
            traceback.print_exc()
        except Exception as e:
            status = f"error: {e}"[:500]
            print(f"  [{done_n}/{n_todo}] id={pid} FAIL {status}", flush=True)
            traceback.print_exc()
        lat = time.perf_counter() - t0
        row = make_row(pid, title, year, model_name, text, lat, status)
        append_result(rows, row)
        print(
            f"  [{done_n}/{n_todo}] id={pid} status={status[:40]} "
            f"chars={row['chars']} overlap={row['title_overlap_score']} "
            f"{row['latency_s']}s",
            flush=True,
        )


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument(
        "--models",
        required=True,
        help="comma-separated tags: " + ",".join(sorted(MODEL_CATALOG)),
    )
    ap.add_argument("--ids-file", default="")
    ap.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--no-skip-done", action="store_true")
    ap.add_argument("--lambda-name", default=DEFAULT_LAMBDA_NAME)
    ap.add_argument("--lambda-region", default=DEFAULT_LAMBDA_REGION)
    args = ap.parse_args()

    configure_out_dir(args.out_dir)
    ids_path = Path(args.ids_file) if args.ids_file else (OUT_DIR / "sample_ids.txt")
    if not ids_path.exists():
        raise SystemExit(f"missing ids file: {ids_path}")

    tags = [t.strip() for t in args.models.split(",") if t.strip()]
    models: list[tuple[str, str]] = []
    for tag in tags:
        if tag not in MODEL_CATALOG:
            raise SystemExit(
                f"unknown model {tag!r}; known: {', '.join(sorted(MODEL_CATALOG))}"
            )
        models.append(MODEL_CATALOG[tag])

    sample = load_sample(ids_path)
    if args.limit and args.limit > 0:
        sample = sample.head(args.limit).copy()

    rows: list[dict] = []
    if RESULTS_CSV.exists():
        with RESULTS_CSV.open(encoding="utf-8", errors="replace") as f:
            for r in csv.DictReader(f):
                rows.append(r)
        print(f"loaded {len(rows)} prior rows from {RESULTS_CSV}", flush=True)

    print(f"sample n={len(sample)} from {ids_path}", flush=True)
    print(f"models: {[m for m, _ in models]}", flush=True)

    client = boto3.client("lambda", region_name=args.lambda_region)
    for model_name, model_id in models:
        run_model(
            sample,
            rows,
            model_name=model_name,
            model_id=model_id,
            skip_done=not args.no_skip_done,
            client=client,
            lambda_name=args.lambda_name,
        )

    write_results(rows)
    for model_name, _ in models:
        n = sum(1 for r in rows if r.get("model") == model_name)
        n_ok = sum(
            1
            for r in rows
            if r.get("model") == model_name and str(r.get("status") or "") == "ok"
        )
        print(f"  {model_name}: {n_ok}/{n} ok", flush=True)
    print(f"\nLISTO → {RESULTS_CSV} ({len(rows)} rows)", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Pilot: Bedrock vision OCR (Converse) on ocr_pilot_v2 sample.

Generalized runner for non-Anthropic models that bill via normal Bedrock
(credits apply). Merges into data/qa/ocr_pilot_v2/results.csv; preserves
other model rows. Skips ids already present with status=ok.

  python3 pilot_ocr_bedrock.py --models nova-lite
  python3 pilot_ocr_bedrock.py --models nova-lite,pixtral,nova-pro --limit 5
  python3 pilot_ocr_bedrock.py --models llama4-scout,gemma3

Requires AWS credentials with Bedrock Runtime access in us-east-1.
Anthropic Claude is intentionally excluded (Marketplace payment instrument).
"""
from __future__ import annotations

import argparse
import csv
import re
import sys
import time
import traceback
from pathlib import Path

import pandas as pd

from ocr_metrics import title_overlap_score

DATA = Path(__file__).resolve().parent / "data"
POSTERS = DATA / "posters"
POSTERS_CSV = DATA / "posters.csv"
DEFAULT_OUT_DIR = DATA / "qa" / "ocr_pilot_v2"
OUT_DIR = DEFAULT_OUT_DIR
RESULTS_CSV = OUT_DIR / "results.csv"
SAMPLE_IDS = OUT_DIR / "sample_ids.txt"

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

REGION = "us-east-1"
OCR_PROMPT = (
    "Extract ALL visible text from this movie poster. "
    "Return plain text only, no commentary."
)
MAX_RETRIES = 8
BASE_BACKOFF_S = 2.0

# tag -> Bedrock modelId / inference profile
MODEL_CATALOG: dict[str, str] = {
    "nova-lite": "us.amazon.nova-lite-v1:0",
    "nova-pro": "us.amazon.nova-pro-v1:0",
    "nova-2-lite": "us.amazon.nova-2-lite-v1:0",
    "pixtral": "us.mistral.pixtral-large-2502-v1:0",
    "llama4-scout": "us.meta.llama4-scout-17b-instruct-v1:0",
    "gemma3": "google.gemma-3-4b-it",
}


def configure_out_dir(path: str | Path) -> None:
    global OUT_DIR, RESULTS_CSV, SAMPLE_IDS
    OUT_DIR = Path(path)
    RESULTS_CSV = OUT_DIR / "results.csv"
    SAMPLE_IDS = OUT_DIR / "sample_ids.txt"


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


def csv_text(text: str) -> str:
    return (text or "").replace("\n", "\\n")


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
        "text": csv_text(text) if ok else "",
        "chars": len(text) if ok else 0,
        "title_overlap_score": score,
        "latency_s": round(latency_s, 3),
        "status": status,
    }


def _image_format(path: Path) -> str:
    suf = path.suffix.lower()
    if suf in (".jpg", ".jpeg"):
        return "jpeg"
    if suf == ".png":
        return "png"
    if suf == ".webp":
        return "webp"
    if suf == ".gif":
        return "gif"
    return "jpeg"


def _extract_text(resp: dict) -> str:
    parts: list[str] = []
    msg = (resp.get("output") or {}).get("message") or {}
    for block in msg.get("content") or []:
        if isinstance(block, dict) and "text" in block:
            parts.append(block["text"] or "")
    return "\n".join(parts).strip()


def _is_throttle(err: Exception) -> bool:
    code = ""
    if hasattr(err, "response"):
        code = str((err.response or {}).get("Error", {}).get("Code") or "")
    msg = f"{code} {err}".lower()
    return any(
        k in msg
        for k in (
            "throttl",
            "too many requests",
            "rate exceeded",
            "serviceunavailable",
            "timeout",
            "model is getting throttled",
        )
    )


def _is_payment_block(err: Exception) -> bool:
    msg = str(err)
    return (
        "INVALID_PAYMENT_INSTRUMENT" in msg
        or "payment instrument" in msg.lower()
    )


def converse_ocr(client, model_id: str, path: Path) -> str:
    data = path.read_bytes()
    if not data:
        raise ValueError(f"empty image: {path}")
    fmt = _image_format(path)
    last_err: Exception | None = None
    for attempt in range(MAX_RETRIES):
        try:
            resp = client.converse(
                modelId=model_id,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "image": {
                                    "format": fmt,
                                    "source": {"bytes": data},
                                }
                            },
                            {"text": OCR_PROMPT},
                        ],
                    }
                ],
                inferenceConfig={
                    "temperature": 0,
                    "maxTokens": 2048,
                },
            )
            return _extract_text(resp)
        except Exception as e:
            last_err = e
            if _is_payment_block(e):
                raise
            if attempt + 1 < MAX_RETRIES and _is_throttle(e):
                sleep_s = BASE_BACKOFF_S * (2**attempt)
                print(
                    f"    throttle/backoff {sleep_s:.1f}s "
                    f"(attempt {attempt + 1}/{MAX_RETRIES}): {e}",
                    flush=True,
                )
                time.sleep(sleep_s)
                continue
            raise
    assert last_err is not None
    raise last_err


def run_model(
    sample: pd.DataFrame,
    rows: list[dict],
    *,
    model_id: str,
    model_name: str,
    skip_done: bool,
    client,
) -> None:
    from botocore.exceptions import BotoCoreError, ClientError

    print(
        f"\n=== model={model_name} bedrock={model_id} "
        f"region={REGION} n={len(sample)} ===",
        flush=True,
    )

    done_ok: set[int] = set()
    if skip_done:
        for r in rows:
            if (
                r.get("model") == model_name
                and str(r.get("status") or "") == "ok"
            ):
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
            text = converse_ocr(client, model_id, img)
        except (ClientError, BotoCoreError, OSError, ValueError) as e:
            status = f"error: {e}"[:500]
            print(f"  [{done_n}/{n_todo}] id={pid} FAIL {status}", flush=True)
            if _is_payment_block(e):
                print(
                    f"  PAYMENT BLOCK for {model_name} — aborting model run",
                    flush=True,
                )
                append_result(
                    rows, make_row(pid, title, year, model_name, "", time.perf_counter() - t0, status)
                )
                return
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


def parse_models(raw: str) -> list[tuple[str, str]]:
    tags = [t.strip() for t in raw.split(",") if t.strip()]
    if not tags:
        raise SystemExit("no models specified")
    out: list[tuple[str, str]] = []
    for tag in tags:
        if tag not in MODEL_CATALOG:
            known = ", ".join(sorted(MODEL_CATALOG))
            raise SystemExit(f"unknown model tag {tag!r}; known: {known}")
        out.append((tag, MODEL_CATALOG[tag]))
    return out


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument(
        "--models",
        required=True,
        help="comma-separated tags: " + ",".join(sorted(MODEL_CATALOG)),
    )
    ap.add_argument(
        "--ids-file",
        default="",
        help="sample id list (default: <out-dir>/sample_ids.txt)",
    )
    ap.add_argument(
        "--out-dir",
        default=str(DEFAULT_OUT_DIR),
        help="output dir (default: data/qa/ocr_pilot_v2)",
    )
    ap.add_argument(
        "--limit",
        type=int,
        default=0,
        help="optional cap on sample size (0 = all)",
    )
    ap.add_argument(
        "--no-skip-done",
        action="store_true",
        help="re-run even if status=ok already present for this model",
    )
    args = ap.parse_args()
    configure_out_dir(args.out_dir)
    ids_path = Path(args.ids_file) if args.ids_file else (OUT_DIR / "sample_ids.txt")
    if not ids_path.exists():
        raise SystemExit(f"missing ids file: {ids_path}")

    models = parse_models(args.models)
    sample = load_sample(ids_path)
    if args.limit and args.limit > 0:
        sample = sample.head(args.limit).copy()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    print(f"sample n={len(sample)} from {ids_path}", flush=True)
    print(f"models: {[t for t, _ in models]}", flush=True)

    rows: list[dict] = []
    if RESULTS_CSV.exists():
        with RESULTS_CSV.open(encoding="utf-8", errors="replace") as f:
            for r in csv.DictReader(f):
                rows.append(r)
        print(f"loaded {len(rows)} prior rows from {RESULTS_CSV}", flush=True)

    try:
        import boto3

        client = boto3.client("bedrock-runtime", region_name=REGION)
    except Exception as e:
        raise SystemExit(f"boto3 bedrock-runtime client failed: {e}") from e

    for tag, mid in models:
        run_model(
            sample,
            rows,
            model_id=mid,
            model_name=tag,
            skip_done=not args.no_skip_done,
            client=client,
        )

    write_results(rows)
    for tag, _ in models:
        n = sum(1 for r in rows if r.get("model") == tag)
        n_ok = sum(
            1
            for r in rows
            if r.get("model") == tag and str(r.get("status") or "") == "ok"
        )
        print(f"  {tag}: {n_ok}/{n} ok", flush=True)
    print(f"\nLISTO → {RESULTS_CSV} ({len(rows)} rows)", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Pilot: Claude Sonnet (Bedrock Converse) OCR on ocr_pilot_v2 sample.

Merges rows into data/qa/ocr_pilot_v2/results.csv for model ``claude``
(existing model rows are preserved). Skips ids already present with status=ok.

  python3 pilot_ocr_bedrock_claude.py
  python3 pilot_ocr_bedrock_claude.py --out-dir data/qa/ocr_pilot_v2 --limit 5
  python3 pilot_ocr_bedrock_claude.py --model-id us.anthropic.claude-sonnet-4-5-20250929-v1:0

Requires AWS credentials with Bedrock Runtime access in us-east-1.
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

MODEL_NAME = "claude"
REGION = "us-east-1"
# Prefer Sonnet 4.5; fall back to 4.6 if 4.5 is unavailable.
# Both need a valid AWS Marketplace payment instrument for Anthropic.
DEFAULT_MODEL_ID = "us.anthropic.claude-sonnet-4-5-20250929-v1:0"
FALLBACK_MODEL_IDS = (
    "us.anthropic.claude-sonnet-4-5-20250929-v1:0",
    "us.anthropic.claude-sonnet-4-6",
)
OCR_PROMPT = (
    "Extract ALL visible text from this movie poster. "
    "Return plain text only, no commentary."
)
MAX_RETRIES = 8
BASE_BACKOFF_S = 2.0


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


def resolve_model_id(client, preferred: str, probe_path: Path) -> str:
    """Pick first usable inference profile among preferred + fallbacks."""
    candidates: list[str] = []
    for mid in (preferred, *FALLBACK_MODEL_IDS):
        if mid and mid not in candidates:
            candidates.append(mid)

    data = probe_path.read_bytes()
    fmt = _image_format(probe_path)
    last_err: Exception | None = None
    for mid in candidates:
        try:
            client.converse(
                modelId=mid,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"image": {"format": fmt, "source": {"bytes": data}}},
                            {"text": "Reply with OK."},
                        ],
                    }
                ],
                inferenceConfig={"temperature": 0, "maxTokens": 8},
            )
            if mid != preferred:
                print(
                    f"  using fallback model-id={mid} (preferred={preferred})",
                    flush=True,
                )
            else:
                print(f"  probe ok model-id={mid}", flush=True)
            return mid
        except Exception as e:
            last_err = e
            print(f"  probe fail model-id={mid}: {e}", flush=True)
            continue
    assert last_err is not None
    raise last_err


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


def run_claude(
    sample: pd.DataFrame,
    rows: list[dict],
    *,
    model_id: str,
    model_name: str,
    skip_done: bool,
) -> None:
    print(
        f"\n=== model={model_name} bedrock preferred={model_id} "
        f"region={REGION} n={len(sample)} ===",
        flush=True,
    )
    try:
        import boto3
        from botocore.exceptions import BotoCoreError, ClientError

        client = boto3.client("bedrock-runtime", region_name=REGION)
    except Exception as e:
        msg = f"load_error: {e}"[:500]
        print(msg, flush=True)
        for _, r in sample.iterrows():
            append_result(
                rows,
                make_row(
                    int(r["id"]),
                    str(r.get("title") or ""),
                    r.get("year", ""),
                    model_name,
                    "",
                    0.0,
                    msg,
                ),
            )
        return

    # Resolve usable Claude profile before writing any result rows.
    probe_img = None
    for _, r in sample.iterrows():
        cand = POSTERS / f"{int(r['id'])}.jpg"
        if cand.exists():
            probe_img = cand
            break
    if probe_img is None:
        raise SystemExit(f"no local posters under {POSTERS} for sample")
    try:
        model_id = resolve_model_id(client, model_id, probe_img)
    except Exception as e:
        msg = str(e)
        hint = ""
        if "INVALID_PAYMENT_INSTRUMENT" in msg or "payment instrument" in msg.lower():
            hint = (
                "\nAnthropic en Bedrock exige instrumento de pago válido en "
                "AWS Marketplace (aunque haya créditos Bedrock). "
                "Acuerdos pueden quedar en PENDING hasta que Billing tenga tarjeta. "
                "Reintentar: python3 pilot_ocr_bedrock_claude.py"
            )
        raise SystemExit(f"Claude Bedrock no usable aún: {e}{hint}") from e

    print(f"  resolved model-id={model_id}", flush=True)

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

    # Drop prior rows for this model that we will re-evaluate
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
        # else drop — will be re-run
    rows.clear()
    rows.extend(keep)

    n_todo = sum(1 for _, r in sample.iterrows() if int(r["id"]) not in done_ok)
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
        "--model-id",
        default=DEFAULT_MODEL_ID,
        help=f"Bedrock inference profile / model id (default: {DEFAULT_MODEL_ID})",
    )
    ap.add_argument(
        "--model-name",
        default=MODEL_NAME,
        help="value written to results.csv model column (default: claude)",
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

    sample = load_sample(ids_path)
    if args.limit and args.limit > 0:
        sample = sample.head(args.limit).copy()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    print(f"sample n={len(sample)} from {ids_path}", flush=True)

    rows: list[dict] = []
    if RESULTS_CSV.exists():
        with RESULTS_CSV.open(encoding="utf-8", errors="replace") as f:
            for r in csv.DictReader(f):
                rows.append(r)
        print(f"loaded {len(rows)} prior rows from {RESULTS_CSV}", flush=True)

    run_claude(
        sample,
        rows,
        model_id=args.model_id,
        model_name=args.model_name,
        skip_done=not args.no_skip_done,
    )
    write_results(rows)
    n_claude = sum(1 for r in rows if r.get("model") == args.model_name)
    print(
        f"\nLISTO → {RESULTS_CSV} ({len(rows)} rows; {args.model_name}={n_claude})",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())

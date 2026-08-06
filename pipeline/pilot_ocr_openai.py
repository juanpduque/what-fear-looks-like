#!/usr/bin/env python3
"""Pilot: OpenAI GPT-4o vision OCR on ocr_pilot_v2 sample.

Uses OPENAI_API_KEY from the environment only (never hardcode / write to disk).
Writes per-id txt under gpt4o/ and a sidecar CSV, then merge-upserts into
results.csv by (model, id) so concurrent Bedrock/Gemini runs are not clobbered.
Skips ids already present with status=ok (in results, sidecar, or .txt).

  OPENAI_API_KEY=... python3 pilot_ocr_openai.py
  OPENAI_API_KEY=... python3 pilot_ocr_openai.py --limit 5
  OPENAI_API_KEY=... python3 pilot_ocr_openai.py --no-skip-done
"""
from __future__ import annotations

import argparse
import base64
import csv
import os
import re
import sys
import time
import traceback
from pathlib import Path

from ocr_metrics import title_overlap_score

DATA = Path(__file__).resolve().parent / "data"
POSTERS = DATA / "posters"
POSTERS_CSV = DATA / "posters.csv"
DEFAULT_OUT_DIR = DATA / "qa" / "ocr_pilot_v2"
OUT_DIR = DEFAULT_OUT_DIR
RESULTS_CSV = OUT_DIR / "results.csv"
SAMPLE_IDS = OUT_DIR / "sample_ids.txt"
SIDECAR_CSV = OUT_DIR / "gpt4o_sidecar.csv"
USAGE_CSV = OUT_DIR / "gpt4o_usage.csv"

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

USAGE_FIELDS = [
    "id",
    "model",
    "prompt_tokens",
    "completion_tokens",
    "total_tokens",
    "latency_s",
    "status",
]

OCR_PROMPT = (
    "Extract ALL visible text from this movie poster. "
    "Return plain text only, no commentary."
)
MAX_RETRIES = 8
BASE_BACKOFF_S = 2.0

MODEL_TAG = "gpt4o"
API_MODEL = "gpt-4o"

# GPT-4o list prices (USD / 1M tokens) — approximate; verify on OpenAI pricing.
PRICE_IN_PER_M = 2.50
PRICE_OUT_PER_M = 10.00


def configure_out_dir(path: str | Path) -> None:
    global OUT_DIR, RESULTS_CSV, SAMPLE_IDS, SIDECAR_CSV, USAGE_CSV
    OUT_DIR = Path(path)
    RESULTS_CSV = OUT_DIR / "results.csv"
    SAMPLE_IDS = OUT_DIR / "sample_ids.txt"
    SIDECAR_CSV = OUT_DIR / "gpt4o_sidecar.csv"
    USAGE_CSV = OUT_DIR / "gpt4o_usage.csv"


def _redact(msg: str) -> str:
    """Strip anything that looks like an OpenAI key from error text."""
    s = str(msg or "")
    s = re.sub(r"sk-[A-Za-z0-9_-]{10,}", "sk-[REDACTED]", s)
    key = os.environ.get("OPENAI_API_KEY") or ""
    if key and key in s:
        s = s.replace(key, "sk-[REDACTED]")
    return s


def load_sample(ids_file: Path) -> list[dict]:
    posters_by_id: dict[int, dict] = {}
    with POSTERS_CSV.open(encoding="utf-8", errors="replace") as f:
        for r in csv.DictReader(f):
            try:
                pid = int(r["id"])
            except (TypeError, ValueError, KeyError):
                continue
            posters_by_id[pid] = {
                "id": pid,
                "title": r.get("title") or "",
                "year": r.get("year") or "",
            }
    raw = ids_file.read_text(encoding="utf-8")
    ids = [int(x) for x in re.split(r"[\s,]+", raw.strip()) if x.strip()]
    out: list[dict] = []
    for pid in ids:
        if pid in posters_by_id:
            out.append(dict(posters_by_id[pid]))
        else:
            out.append({"id": pid, "title": "", "year": ""})
    return out


def read_csv_rows(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8", errors="replace") as f:
        return list(csv.DictReader(f))


def write_csv_rows(path: Path, rows: list[dict], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)


def upsert_rows(existing: list[dict], row: dict) -> list[dict]:
    model = str(row["model"])
    pid = str(row["id"])
    out: list[dict] = []
    replaced = False
    for r in existing:
        if str(r.get("model") or "") == model and str(r.get("id") or "") == pid:
            out.append(row)
            replaced = True
        else:
            out.append(r)
    if not replaced:
        out.append(row)
    return out


def write_model_txt(row: dict) -> None:
    if row.get("status") != "ok" or not row.get("text"):
        return
    model_dir = OUT_DIR / str(row["model"])
    model_dir.mkdir(parents=True, exist_ok=True)
    raw = str(row["text"]).replace("\\n", "\n")
    (model_dir / f"{row['id']}.txt").write_text(raw, encoding="utf-8")


def persist_row(row: dict) -> None:
    """Write txt + sidecar always; merge into shared results.csv best-effort."""
    write_model_txt(row)
    side = upsert_rows(read_csv_rows(SIDECAR_CSV), row)
    write_csv_rows(SIDECAR_CSV, side, RESULT_FIELDS)
    try:
        merged = upsert_rows(read_csv_rows(RESULTS_CSV), row)
        write_csv_rows(RESULTS_CSV, merged, RESULT_FIELDS)
    except OSError as e:
        print(f"  warn: results.csv merge failed (sidecar kept): {e}", flush=True)


def persist_usage(row: dict) -> None:
    usage = upsert_rows(read_csv_rows(USAGE_CSV), row)
    write_csv_rows(USAGE_CSV, usage, USAGE_FIELDS)


def final_merge_sidecar() -> int:
    side = read_csv_rows(SIDECAR_CSV)
    if not side:
        return 0
    merged = read_csv_rows(RESULTS_CSV)
    for row in side:
        merged = upsert_rows(merged, row)
    write_csv_rows(RESULTS_CSV, merged, RESULT_FIELDS)
    return len(side)


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


def _mime_for(path: Path) -> str:
    suf = path.suffix.lower()
    if suf in (".jpg", ".jpeg"):
        return "image/jpeg"
    if suf == ".png":
        return "image/png"
    if suf == ".webp":
        return "image/webp"
    if suf == ".gif":
        return "image/gif"
    return "image/jpeg"


def _is_throttle(err: Exception) -> bool:
    msg = _redact(str(err)).lower()
    status = getattr(err, "status_code", None) or getattr(err, "http_status", None)
    if status in (429, 500, 502, 503, 504):
        return True
    return any(
        k in msg
        for k in (
            "rate limit",
            "too many requests",
            "429",
            "timeout",
            "overloaded",
            "server_error",
            "temporarily unavailable",
        )
    )


def openai_ocr(client, path: Path) -> tuple[str, dict]:
    """Return (text, usage_dict)."""
    data = path.read_bytes()
    if not data:
        raise ValueError(f"empty image: {path}")
    if len(data) > 20_000_000:
        raise ValueError(f"image too large: {len(data)}")

    b64 = base64.b64encode(data).decode("ascii")
    mime = _mime_for(path)
    last_err: Exception | None = None
    for attempt in range(MAX_RETRIES):
        try:
            resp = client.chat.completions.create(
                model=API_MODEL,
                temperature=0,
                max_tokens=2048,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": OCR_PROMPT},
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:{mime};base64,{b64}",
                                    "detail": "high",
                                },
                            },
                        ],
                    }
                ],
            )
            choice = (resp.choices or [None])[0]
            text = ""
            if choice is not None and choice.message is not None:
                text = (choice.message.content or "").strip()
            usage = {
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0,
            }
            if getattr(resp, "usage", None) is not None:
                usage["prompt_tokens"] = int(resp.usage.prompt_tokens or 0)
                usage["completion_tokens"] = int(resp.usage.completion_tokens or 0)
                usage["total_tokens"] = int(
                    resp.usage.total_tokens
                    or (usage["prompt_tokens"] + usage["completion_tokens"])
                )
            return text, usage
        except Exception as e:
            last_err = e
            if attempt + 1 < MAX_RETRIES and _is_throttle(e):
                sleep_s = BASE_BACKOFF_S * (2**attempt)
                print(
                    f"    throttle/backoff {sleep_s:.1f}s "
                    f"(attempt {attempt + 1}/{MAX_RETRIES}): {_redact(e)}",
                    flush=True,
                )
                time.sleep(sleep_s)
                continue
            raise RuntimeError(_redact(e)) from None
    assert last_err is not None
    raise RuntimeError(_redact(last_err)) from None


def seed_sidecar_from_txt(model_name: str, sample: list[dict]) -> int:
    model_dir = OUT_DIR / model_name
    if not model_dir.is_dir():
        return 0
    by_id = {int(r["id"]): r for r in sample}
    side_ids = {
        int(r["id"])
        for r in read_csv_rows(SIDECAR_CSV)
        if r.get("model") == model_name
        and str(r.get("status") or "") == "ok"
        and str(r.get("id") or "").isdigit()
    }
    n = 0
    for p in sorted(model_dir.glob("*.txt")):
        try:
            pid = int(p.stem)
        except ValueError:
            continue
        if pid in side_ids:
            continue
        meta = by_id.get(pid) or {"id": pid, "title": "", "year": ""}
        text = p.read_text(encoding="utf-8")
        row = make_row(
            pid,
            str(meta.get("title") or ""),
            meta.get("year", ""),
            model_name,
            text,
            0.0,
            "ok",
        )
        persist_row(row)
        n += 1
    return n


def done_ok_ids(model_name: str) -> set[int]:
    done: set[int] = set()
    for path in (RESULTS_CSV, SIDECAR_CSV):
        for r in read_csv_rows(path):
            if r.get("model") != model_name:
                continue
            if str(r.get("status") or "") != "ok":
                continue
            try:
                done.add(int(r["id"]))
            except (TypeError, ValueError):
                pass
    model_dir = OUT_DIR / model_name
    if model_dir.is_dir():
        for p in model_dir.glob("*.txt"):
            try:
                done.add(int(p.stem))
            except ValueError:
                pass
    return done


def run_model(
    sample: list[dict],
    *,
    model_name: str,
    skip_done: bool,
    client,
) -> dict:
    print(
        f"\n=== model={model_name} api={API_MODEL} detail=high "
        f"n={len(sample)} ===",
        flush=True,
    )

    seeded = seed_sidecar_from_txt(model_name, sample)
    if seeded:
        print(f"  seeded {seeded} rows from existing .txt into sidecar", flush=True)

    done_ok = done_ok_ids(model_name) if skip_done else set()
    if done_ok:
        print(f"  skip {len(done_ok)} already-ok ids", flush=True)

    n_todo = sum(1 for r in sample if int(r["id"]) not in done_ok)
    totals = {
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
        "n_ok": 0,
        "n_err": 0,
    }
    if n_todo == 0:
        print(f"  nothing to do for {model_name}", flush=True)
        return totals

    done_n = 0
    for r in sample:
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
        usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        try:
            if not img.exists():
                raise FileNotFoundError(f"missing {img}")
            text, usage = openai_ocr(client, img)
        except Exception as e:
            status = f"error: {_redact(e)}"[:500]
            print(f"  [{done_n}/{n_todo}] id={pid} FAIL {status}", flush=True)
            traceback.print_exc()
            totals["n_err"] += 1
        lat = time.perf_counter() - t0
        row = make_row(pid, title, year, model_name, text, lat, status)
        persist_row(row)
        persist_usage(
            {
                "id": pid,
                "model": model_name,
                "prompt_tokens": usage["prompt_tokens"],
                "completion_tokens": usage["completion_tokens"],
                "total_tokens": usage["total_tokens"],
                "latency_s": round(lat, 3),
                "status": status if status == "ok" else status[:80],
            }
        )
        if status == "ok":
            totals["n_ok"] += 1
            totals["prompt_tokens"] += usage["prompt_tokens"]
            totals["completion_tokens"] += usage["completion_tokens"]
            totals["total_tokens"] += usage["total_tokens"]
        print(
            f"  [{done_n}/{n_todo}] id={pid} status={status[:40]} "
            f"chars={row['chars']} overlap={row['title_overlap_score']} "
            f"{row['latency_s']}s tok={usage['total_tokens']}",
            flush=True,
        )
    return totals


def approx_cost_usd(prompt_tokens: int, completion_tokens: int) -> float:
    return (
        prompt_tokens / 1_000_000 * PRICE_IN_PER_M
        + completion_tokens / 1_000_000 * PRICE_OUT_PER_M
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

    if not (os.environ.get("OPENAI_API_KEY") or "").strip():
        raise SystemExit("OPENAI_API_KEY not set in environment")

    sample = load_sample(ids_path)
    if args.limit and args.limit > 0:
        sample = sample[: args.limit]

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    print(f"sample n={len(sample)} from {ids_path}", flush=True)
    print(f"model={MODEL_TAG} api={API_MODEL} detail=high temperature=0", flush=True)
    print("OPENAI_API_KEY=set (value not logged)", flush=True)

    try:
        from openai import OpenAI
    except ImportError as e:
        raise SystemExit(f"openai package required: {e}") from e

    client = OpenAI()  # reads OPENAI_API_KEY from env

    totals = run_model(
        sample,
        model_name=MODEL_TAG,
        skip_done=not args.no_skip_done,
        client=client,
    )

    n_side = final_merge_sidecar()
    print(f"final sidecar merge → {n_side} gpt4o rows into {RESULTS_CSV}", flush=True)

    # Sum usage from sidecar file (covers skip-done residuals + this run)
    prompt_sum = 0
    completion_sum = 0
    for u in read_csv_rows(USAGE_CSV):
        if u.get("model") != MODEL_TAG:
            continue
        if str(u.get("status") or "") != "ok":
            continue
        try:
            prompt_sum += int(float(u.get("prompt_tokens") or 0))
            completion_sum += int(float(u.get("completion_tokens") or 0))
        except (TypeError, ValueError):
            pass
    cost = approx_cost_usd(prompt_sum, completion_sum)
    print(
        f"usage tokens in={prompt_sum} out={completion_sum} "
        f"approx_usd=${cost:.4f} "
        f"(list ${PRICE_IN_PER_M}/1M in + ${PRICE_OUT_PER_M}/1M out)",
        flush=True,
    )
    print(
        f"this_run ok={totals['n_ok']} err={totals['n_err']} "
        f"tok={totals['total_tokens']}",
        flush=True,
    )

    rows = read_csv_rows(RESULTS_CSV)
    n = sum(1 for r in rows if r.get("model") == MODEL_TAG)
    n_ok = sum(
        1
        for r in rows
        if r.get("model") == MODEL_TAG and str(r.get("status") or "") == "ok"
    )
    print(f"  {MODEL_TAG}: {n_ok}/{n} ok", flush=True)
    print(f"\nLISTO → {RESULTS_CSV} ({len(rows)} rows)", flush=True)
    print(f"sidecar → {SIDECAR_CSV}", flush=True)
    print(f"usage → {USAGE_CSV}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())

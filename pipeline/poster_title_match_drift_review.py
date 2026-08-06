#!/usr/bin/env python3
"""Nova vision review of title-match suspects: does the poster match the film?

Writes SEPARATE outputs (does not touch poster_title_match.csv):
  data/qa/poster_title_match_drift_review.csv
  data/qa/poster_title_match_drift_review.jsonl
  data/qa/poster_title_match_drift_sample_ids.csv

  export AWS_PROFILE=sandbox
  python3 poster_title_match_drift_review.py --n 400 --min-chars 20
  python3 poster_title_match_drift_review.py --model nova-pro --n 200
"""
from __future__ import annotations

import argparse
import csv
import json
import random
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from nova_poster_enrich import resize_jpeg, strip_json

DATA = Path(__file__).resolve().parent / "data"
POSTERS = DATA / "posters"
SUSPECTS = DATA / "qa" / "poster_title_match_suspects.csv"
MATCH = DATA / "qa" / "poster_title_match.csv"
HM = DATA / "horror_movies.csv"
OUT_CSV = DATA / "qa" / "poster_title_match_drift_review.csv"
OUT_JSONL = DATA / "qa" / "poster_title_match_drift_review.jsonl"
OUT_IDS = DATA / "qa" / "poster_title_match_drift_sample_ids.csv"
REGION = "us-east-1"

MODELS = {
    "nova-lite": "us.amazon.nova-2-lite-v1:0",
    "nova-pro": "us.amazon.nova-pro-v1:0",
    "claude-haiku": "us.anthropic.claude-haiku-4-5-20251001-v1:0",
    "claude-sonnet": "us.anthropic.claude-sonnet-4-5-20250929-v1:0",
}

PROMPT = """You verify whether a horror movie poster image matches a catalog film entry.
Return ONLY valid JSON (no markdown):
{{
  "verdict": "match" | "mismatch" | "uncertain",
  "confidence": 0.0,
  "poster_title_guess": "title text visible on poster, or empty",
  "reason": "one short sentence"
}}

Rules:
- match: artwork clearly belongs to this film (title, iconic imagery, or unambiguous branding).
- mismatch: poster is clearly for a different film / wrong artwork.
- uncertain: ambiguous remake/art variant, unreadable title, or insufficient signal.
- confidence in 0..1.
- Do not invent cast/plot beyond what the poster shows.

Catalog film:
- title: {title}
- original_title: {original_title}
- year: {year}
- original_language: {original_language}
- OCR hint (may be noisy): {ocr_hint}
"""

FIELDS = [
    "id",
    "title",
    "original_title",
    "year",
    "original_language",
    "ocr_lang",
    "ocr_chars",
    "overlap_max",
    "overlap_max_local",
    "model",
    "model_id",
    "status",
    "verdict",
    "confidence",
    "poster_title_guess",
    "reason",
    "latency_s",
    "error",
]

_print_lock = threading.Lock()
_write_lock = threading.Lock()
_rate_lock = threading.Lock()
_next_slot = 0.0


def log(msg: str) -> None:
    with _print_lock:
        print(msg, flush=True)


def acquire(min_interval: float) -> None:
    global _next_slot
    with _rate_lock:
        now = time.monotonic()
        slot = max(now, _next_slot)
        _next_slot = slot + min_interval
        wait = slot - now
    if wait > 0:
        time.sleep(wait)


def load_meta() -> dict[int, dict]:
    out: dict[int, dict] = {}
    if not HM.exists():
        return out
    with HM.open(encoding="utf-8", errors="replace") as f:
        for r in csv.DictReader(f):
            try:
                pid = int(float(r["id"]))
            except Exception:
                continue
            rd = (r.get("release_date") or "")[:4]
            out[pid] = {
                "title": (r.get("title") or "").strip(),
                "original_title": (r.get("original_title") or "").strip(),
                "original_language": (r.get("original_language") or "").strip(),
                "year": int(rd) if rd.isdigit() else "",
            }
    return out


def load_suspects(path: Path, min_chars: int) -> list[dict]:
    rows: list[dict] = []
    src = path if path.exists() else MATCH
    with src.open(encoding="utf-8", errors="replace") as f:
        for r in csv.DictReader(f):
            if path == SUSPECTS or str(r.get("suspect")) == "1":
                try:
                    chars = int(float(r.get("ocr_chars") or 0))
                except Exception:
                    chars = 0
                if chars < min_chars:
                    continue
                try:
                    pid = int(r["id"])
                except Exception:
                    continue
                if not (POSTERS / f"{pid}.jpg").exists():
                    continue
                rows.append(r)
    return rows


def pick_sample(rows: list[dict], n: int, seed: int) -> list[dict]:
    def ov(r):
        try:
            return float(r.get("overlap_max") or 0)
        except Exception:
            return 0.0

    def chars(r):
        try:
            return int(float(r.get("ocr_chars") or 0))
        except Exception:
            return 0

    # Prefer zero/low overlap, then more OCR text
    ranked = sorted(rows, key=lambda r: (ov(r), -chars(r), int(r["id"])))
    # Take a pool larger than n from the worst scores, then stratified shuffle
    pool = ranked[: max(n * 3, n)]
    zeros = [r for r in pool if ov(r) == 0.0]
    low = [r for r in pool if 0.0 < ov(r) < 0.2]
    rest = [r for r in pool if ov(r) >= 0.2]
    rng = random.Random(seed)
    for bucket in (zeros, low, rest):
        rng.shuffle(bucket)
    # ~70% zero, 20% low, 10% rest
    n0 = min(len(zeros), int(round(n * 0.70)))
    n1 = min(len(low), int(round(n * 0.20)))
    n2 = min(len(rest), n - n0 - n1)
    picked = zeros[:n0] + low[:n1] + rest[:n2]
    if len(picked) < n:
        used = {int(r["id"]) for r in picked}
        for r in ranked:
            if int(r["id"]) in used:
                continue
            picked.append(r)
            if len(picked) >= n:
                break
    rng.shuffle(picked)
    return picked[:n]


def load_done(
    path: Path,
    force: bool,
    *,
    rerun_verdicts: set[str] | None = None,
) -> dict[int, dict]:
    if force or not path.exists():
        return {}
    skip = {v.strip().lower() for v in (rerun_verdicts or set()) if v.strip()}
    out: dict[int, dict] = {}
    with path.open(encoding="utf-8", errors="replace") as f:
        for r in csv.DictReader(f):
            if str(r.get("status")) != "ok":
                continue
            try:
                pid = int(r["id"])
            except Exception:
                continue
            if skip and str(r.get("verdict") or "").strip().lower() in skip:
                continue  # force re-review
            out[pid] = r
    return out


def write_csv(path: Path, rows: dict[int, dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with _write_lock:
        with path.open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore")
            w.writeheader()
            for pid in sorted(rows):
                w.writerow(rows[pid])


def append_jsonl(path: Path, obj: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with _write_lock:
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(obj, ensure_ascii=False) + "\n")


def invoke(client, model_id: str, img: bytes, fmt: str, prompt: str, max_tokens: int) -> dict:
    resp = client.converse(
        modelId=model_id,
        messages=[
            {
                "role": "user",
                "content": [
                    {"image": {"format": fmt, "source": {"bytes": img}}},
                    {"text": prompt},
                ],
            }
        ],
        inferenceConfig={"temperature": 0, "maxTokens": max_tokens},
    )
    text = "".join(
        b.get("text", "")
        for b in resp.get("output", {}).get("message", {}).get("content", [])
        if "text" in b
    )
    return {"text": text, "usage": resp.get("usage") or {}}


def process_one(
    client,
    *,
    row: dict,
    meta: dict,
    model_key: str,
    model_id: str,
    min_interval: float,
    out_jsonl: Path = OUT_JSONL,
) -> dict:
    pid = int(row["id"])
    t0 = time.perf_counter()
    title = meta.get("title") or row.get("title") or ""
    orig = meta.get("original_title") or row.get("original_title") or ""
    year = meta.get("year") or ""
    ol = meta.get("original_language") or row.get("original_language") or ""
    # short OCR hint from match file if present — not stored; use empty
    ocr_hint = f"chars={row.get('ocr_chars')}, lang={row.get('ocr_lang')}, overlap={row.get('overlap_max')}"
    prompt = PROMPT.format(
        title=title,
        original_title=orig,
        year=year,
        original_language=ol,
        ocr_hint=ocr_hint,
    )
    base = {
        "id": pid,
        "title": title,
        "original_title": orig,
        "year": year,
        "original_language": ol,
        "ocr_lang": row.get("ocr_lang") or "",
        "ocr_chars": row.get("ocr_chars") or "",
        "overlap_max": row.get("overlap_max") or "",
        "overlap_max_local": row.get("overlap_max_local") or "",
        "model": model_key,
        "model_id": model_id,
        "status": "error",
        "verdict": "",
        "confidence": "",
        "poster_title_guess": "",
        "reason": "",
        "latency_s": "",
        "error": "",
    }
    try:
        raw, fmt = resize_jpeg(POSTERS / f"{pid}.jpg")
        last_err = None
        data = None
        text = ""
        for attempt in range(4):
            try:
                acquire(min_interval)
                body = invoke(
                    client,
                    model_id,
                    raw,
                    fmt,
                    prompt,
                    max_tokens=400 if attempt == 0 else 700,
                )
                text = body.get("text") or ""
                data = strip_json(text)
                break
            except Exception as e:
                last_err = e
                if attempt + 1 < 4 and (
                    "Throttling" in str(e)
                    or "JSONDecode" in type(e).__name__
                    or "JSONDecode" in str(e)
                ):
                    time.sleep(min(12.0, 1.2 * (2**attempt)))
                    continue
                raise
        if data is None:
            raise last_err or RuntimeError("no parse")
        verdict = str(data.get("verdict") or "").strip().lower()
        if verdict not in ("match", "mismatch", "uncertain"):
            # soft normalize
            if "mismatch" in verdict or "wrong" in verdict:
                verdict = "mismatch"
            elif "uncertain" in verdict or "unsure" in verdict:
                verdict = "uncertain"
            elif "match" in verdict:
                verdict = "match"
            else:
                verdict = "uncertain"
        try:
            conf = float(data.get("confidence") or 0)
        except Exception:
            conf = 0.0
        conf = round(max(0.0, min(1.0, conf)), 4)
        base.update(
            {
                "status": "ok",
                "verdict": verdict,
                "confidence": conf,
                "poster_title_guess": str(data.get("poster_title_guess") or "")
                .replace("\n", " ")
                .strip()[:200],
                "reason": str(data.get("reason") or "").replace("\n", " ").strip()[:300],
                "latency_s": round(time.perf_counter() - t0, 3),
                "error": "",
            }
        )
        append_jsonl(
            out_jsonl,
            {
                "id": pid,
                "model": model_key,
                "verdict": verdict,
                "confidence": conf,
                "raw": data,
                "text": text[:4000],
            },
        )
        return base
    except Exception as e:
        base["latency_s"] = round(time.perf_counter() - t0, 3)
        base["error"] = f"{type(e).__name__}: {e}"[:400]
        base["status"] = "error"
        return base


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--n", type=int, default=400)
    ap.add_argument(
        "--extra",
        type=int,
        default=0,
        help="Add N more suspects beyond rows already in the review CSV (keeps prior results)",
    )
    ap.add_argument(
        "--rerun-verdicts",
        default="",
        help="Comma list of prior verdicts to re-review (e.g. mismatch,uncertain); keeps other rows",
    )
    ap.add_argument(
        "--from-csv",
        default="",
        help="Source CSV for --rerun-verdicts (default: main drift review CSV)",
    )
    ap.add_argument(
        "--out-tag",
        default="",
        help="Write to poster_title_match_drift_review_<tag>.csv/.jsonl (does not touch main CSV)",
    )
    ap.add_argument("--min-chars", type=int, default=20)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--model", choices=sorted(MODELS), default="nova-lite")
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--min-interval", type=float, default=0.25)
    ap.add_argument("--region", default=REGION)
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--limit", type=int, default=0, help="cap todo after sample")
    args = ap.parse_args()

    model_id = MODELS[args.model]
    meta = load_meta()
    suspects = load_suspects(SUSPECTS, args.min_chars)
    log(f"suspects_pool min_chars>={args.min_chars}: {len(suspects)}")

    tag = (args.out_tag or "").strip()
    out_csv = (
        DATA / "qa" / f"poster_title_match_drift_review_{tag}.csv" if tag else OUT_CSV
    )
    out_jsonl = (
        DATA / "qa" / f"poster_title_match_drift_review_{tag}.jsonl" if tag else OUT_JSONL
    )
    from_csv = Path(args.from_csv) if args.from_csv else OUT_CSV

    rerun = {v.strip().lower() for v in args.rerun_verdicts.split(",") if v.strip()}
    # When writing to a tagged file, resume from that file; don't merge the full main corpus.
    done_src = out_csv if tag else OUT_CSV
    done = load_done(
        done_src,
        args.force,
        rerun_verdicts=rerun if not tag else None,
    )
    if args.force and out_jsonl.exists():
        out_jsonl.write_text("", encoding="utf-8")

    if rerun and args.extra == 0:
        by_id = {int(r["id"]): r for r in suspects}
        todo = []
        src = from_csv if from_csv.exists() else OUT_CSV
        if src.exists():
            with src.open(encoding="utf-8", errors="replace") as f:
                for r in csv.DictReader(f):
                    if str(r.get("status")) != "ok":
                        continue
                    if str(r.get("verdict") or "").strip().lower() not in rerun:
                        continue
                    try:
                        pid = int(r["id"])
                    except Exception:
                        continue
                    if pid in done:
                        continue
                    todo.append(by_id.get(pid, r))
        log(
            f"rerun verdicts={sorted(rerun)} from={src.name} out={out_csv.name} "
            f"todo={len(todo)} kept={len(done)} model={args.model} workers={args.workers}"
        )
    elif args.extra > 0:
        if args.force:
            raise SystemExit("--extra is incompatible with --force")
        remaining = [r for r in suspects if int(r["id"]) not in done]
        sample = pick_sample(remaining, args.extra, args.seed + len(done))
        # keep prior ids file entries + new
        prior_ids: list[dict] = []
        if OUT_IDS.exists():
            with OUT_IDS.open(encoding="utf-8", errors="replace") as f:
                prior_ids = list(csv.DictReader(f))
        with OUT_IDS.open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(
                f,
                fieldnames=[
                    "id",
                    "title",
                    "ocr_chars",
                    "overlap_max",
                    "ocr_lang",
                    "original_language",
                ],
            )
            w.writeheader()
            seen = set()
            for r in prior_ids + sample:
                pid = str(r.get("id"))
                if pid in seen:
                    continue
                seen.add(pid)
                w.writerow(
                    {
                        "id": r.get("id"),
                        "title": r.get("title") or "",
                        "ocr_chars": r.get("ocr_chars") or "",
                        "overlap_max": r.get("overlap_max") or "",
                        "ocr_lang": r.get("ocr_lang") or "",
                        "original_language": r.get("original_language") or "",
                    }
                )
        todo = sample
        log(f"extend extra={args.extra} prior_done={len(done)} new_sample={len(todo)}")
    else:
        sample = pick_sample(suspects, args.n, args.seed)
        OUT_IDS.parent.mkdir(parents=True, exist_ok=True)
        with OUT_IDS.open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(
                f,
                fieldnames=[
                    "id",
                    "title",
                    "ocr_chars",
                    "overlap_max",
                    "ocr_lang",
                    "original_language",
                ],
            )
            w.writeheader()
            for r in sample:
                w.writerow(
                    {
                        "id": r["id"],
                        "title": r.get("title") or "",
                        "ocr_chars": r.get("ocr_chars") or "",
                        "overlap_max": r.get("overlap_max") or "",
                        "ocr_lang": r.get("ocr_lang") or "",
                        "original_language": r.get("original_language") or "",
                    }
                )
        todo = [r for r in sample if int(r["id"]) not in done]
        log(
            f"start sample={len(sample)} todo={len(todo)} done={len(done)} "
            f"model={args.model} workers={args.workers}"
        )

    if args.limit:
        todo = todo[: args.limit]

    if args.extra > 0 or rerun:
        log(f"model={args.model} workers={args.workers} todo={len(todo)}")

    client = boto3.client(
        "bedrock-runtime",
        region_name=args.region,
        config=Config(retries={"max_attempts": 8, "mode": "adaptive"}),
    )

    rows: dict[int, dict] = dict(done)
    t0 = time.time()
    ok = err = 0
    completed = 0

    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as ex:
        futs = {
            ex.submit(
                process_one,
                client,
                row=r,
                meta=meta.get(int(r["id"]), {}),
                model_key=args.model,
                model_id=model_id,
                min_interval=args.min_interval,
                out_jsonl=out_jsonl,
            ): int(r["id"])
            for r in todo
        }
        for fut in as_completed(futs):
            pid = futs[fut]
            row = fut.result()
            rows[pid] = row
            completed += 1
            if row.get("status") == "ok":
                ok += 1
            else:
                err += 1
            if completed % 25 == 0 or completed == len(todo):
                write_csv(out_csv, rows)
                rate = completed / max(1e-6, time.time() - t0)
                log(
                    f"[{completed}/{len(todo)}] ok={ok} err={err} rate={rate:.2f}/s "
                    f"id={pid} verdict={row.get('verdict')}"
                )

    write_csv(out_csv, rows)
    # summary
    from collections import Counter

    verdicts = Counter(
        (r.get("verdict") or "error")
        for r in rows.values()
        if r.get("status") == "ok"
    )
    log(
        f"LISTO n_ok={sum(1 for r in rows.values() if r.get('status')=='ok')} "
        f"err={sum(1 for r in rows.values() if r.get('status')!='ok')} "
        f"verdicts={dict(verdicts)} elapsed={(time.time()-t0)/60:.1f}m → {out_csv}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

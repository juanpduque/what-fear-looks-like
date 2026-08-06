#!/usr/bin/env python3
"""Comprehend over OCR text (EasyOCR + Textract when available).

Writes data/ocr_comprehend.csv (does not modify OCR sources).

  export AWS_PROFILE=sandbox
  python3 ocr_comprehend.py --workers 8
  python3 ocr_comprehend.py --empty-easyocr-only
"""
from __future__ import annotations

import argparse
import csv
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import boto3
import pandas as pd
from botocore.config import Config
from botocore.exceptions import ClientError

DATA = Path(__file__).resolve().parent / "data"
DEFAULT_OUT = DATA / "ocr_comprehend.csv"
DEFAULT_PARTIAL = DATA / "ocr_comprehend_partial.csv"
REGION = "us-east-1"

FIELDS = [
    "id",
    "source",
    "text_chars",
    "lang_code",
    "lang_score",
    "sentiment",
    "sent_positive",
    "sent_negative",
    "sent_neutral",
    "sent_mixed",
    "entities",
    "key_phrases",
    "error",
]

_print_lock = threading.Lock()
_write_lock = threading.Lock()


def log(msg: str) -> None:
    with _print_lock:
        print(msg, flush=True)


def load_done(force: bool, *paths: Path) -> set[tuple[int, str]]:
    if force:
        return set()
    done = set()
    for path in paths:
        if not path.exists():
            continue
        with path.open(encoding="utf-8", errors="replace") as f:
            for r in csv.DictReader(f):
                try:
                    done.add((int(r["id"]), str(r.get("source") or "")))
                except Exception:
                    pass
    return done


def write_all(path: Path, rows: dict[tuple[int, str], dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with _write_lock:
        with path.open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore")
            w.writeheader()
            for k in sorted(rows, key=lambda x: (x[0], x[1])):
                w.writerow(rows[k])


def truncate(text: str, n: int = 4500) -> str:
    t = (text or "").strip()
    if len(t) <= n:
        return t
    return t[:n]


def analyze(client, pid: int, source: str, text: str) -> dict:
    base = {
        "id": pid,
        "source": source,
        "text_chars": len(text or ""),
        "lang_code": "",
        "lang_score": "",
        "sentiment": "",
        "sent_positive": "",
        "sent_negative": "",
        "sent_neutral": "",
        "sent_mixed": "",
        "entities": "",
        "key_phrases": "",
        "error": "",
    }
    text = truncate(text)
    if not text:
        base["error"] = "empty_text"
        return base
    try:
        # language
        langs = client.detect_dominant_language(Text=text).get("Languages") or []
        if langs:
            base["lang_code"] = langs[0].get("LanguageCode") or ""
            base["lang_score"] = round(float(langs[0].get("Score") or 0), 4)
        lang = base["lang_code"] if base["lang_code"] in {"en", "es", "fr", "de", "it", "pt"} else "en"

        sent = client.detect_sentiment(Text=text, LanguageCode=lang)
        base["sentiment"] = sent.get("Sentiment") or ""
        scores = sent.get("SentimentScore") or {}
        base["sent_positive"] = round(float(scores.get("Positive") or 0), 4)
        base["sent_negative"] = round(float(scores.get("Negative") or 0), 4)
        base["sent_neutral"] = round(float(scores.get("Neutral") or 0), 4)
        base["sent_mixed"] = round(float(scores.get("Mixed") or 0), 4)

        ents = client.detect_entities(Text=text, LanguageCode=lang).get("Entities") or []
        base["entities"] = "|".join(
            f"{e.get('Type')}:{e.get('Text')}:{round(float(e.get('Score') or 0),2)}"
            for e in ents[:20]
        )
        phrases = client.detect_key_phrases(Text=text, LanguageCode=lang).get("KeyPhrases") or []
        base["key_phrases"] = "|".join(
            f"{p.get('Text')}:{round(float(p.get('Score') or 0),2)}" for p in phrases[:15]
        )
        return base
    except Exception as e:
        base["error"] = f"{type(e).__name__}: {e}"[:240]
        return base


def build_jobs(empty_easyocr_only: bool) -> list[tuple[int, str, str]]:
    easy = pd.read_csv(DATA / "poster_ocr.csv", usecols=["id", "full_ocr"])
    easy["id"] = easy["id"].astype(int)
    easy["full_ocr"] = easy["full_ocr"].fillna("").astype(str)
    tex_path = DATA / "poster_ocr_textract_partial.csv"
    if not tex_path.exists():
        tex_path = DATA / "poster_ocr_textract.csv"
    tex = None
    if tex_path.exists():
        tex = pd.read_csv(tex_path, usecols=["id", "full_ocr"])
        tex["id"] = tex["id"].astype(int)
        tex["full_ocr"] = tex["full_ocr"].fillna("").astype(str)

    jobs = []
    if empty_easyocr_only:
        empty_ids = set(easy.loc[easy["full_ocr"].str.strip() == "", "id"])
        # prefer textract text for those ids; also mark easy empty
        if tex is not None:
            for r in tex.itertuples(index=False):
                if int(r.id) in empty_ids and str(r.full_ocr).strip():
                    jobs.append((int(r.id), "textract", str(r.full_ocr)))
        for r in easy.itertuples(index=False):
            if int(r.id) in empty_ids:
                jobs.append((int(r.id), "easyocr", str(r.full_ocr)))
        return jobs

    for r in easy.itertuples(index=False):
        jobs.append((int(r.id), "easyocr", str(r.full_ocr)))
    if tex is not None:
        for r in tex.itertuples(index=False):
            jobs.append((int(r.id), "textract", str(r.full_ocr)))
    return jobs


def build_jobs_from_ocr_file(path: Path, source: str) -> list[tuple[int, str, str]]:
    jobs: list[tuple[int, str, str]] = []
    with path.open(encoding="utf-8", errors="replace") as f:
        for r in csv.DictReader(f):
            try:
                pid = int(r["id"])
            except Exception:
                continue
            text = r.get("full_ocr") or r.get("text") or ""
            jobs.append((pid, source, str(text)))
    return jobs


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--save-every", type=int, default=100)
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--empty-easyocr-only", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--region", default=REGION)
    ap.add_argument("--ocr-file", type=Path, default=None, help="OCR CSV with id,full_ocr")
    ap.add_argument("--source", default="", help="source label when using --ocr-file")
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--partial", type=Path, default=None)
    args = ap.parse_args()

    out_path = args.out
    partial_path = args.partial or out_path.with_name(out_path.stem + "_partial.csv")

    if args.ocr_file:
        source = args.source or args.ocr_file.stem
        jobs = build_jobs_from_ocr_file(args.ocr_file, source)
    else:
        jobs = build_jobs(args.empty_easyocr_only)
    done = load_done(args.force, out_path, partial_path)
    todo = [(i, s, t) for i, s, t in jobs if (i, s) not in done]
    if args.limit > 0:
        todo = todo[: args.limit]
    log(
        f"comprehend start todo={len(todo):,} workers={args.workers} "
        f"empty_only={args.empty_easyocr_only} out={out_path.name}"
    )

    client = boto3.client(
        "comprehend",
        region_name=args.region,
        config=Config(retries={"max_attempts": 5}, max_pool_connections=max(args.workers + 4, 16)),
    )

    rows: dict[tuple[int, str], dict] = {}
    for path in (out_path, partial_path):
        if path.exists():
            with path.open(encoding="utf-8", errors="replace") as f:
                for r in csv.DictReader(f):
                    try:
                        rows[(int(r["id"]), str(r.get("source") or ""))] = r
                    except Exception:
                        pass

    t0 = time.time()
    n = 0
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as ex:
        futs = {ex.submit(analyze, client, i, s, t): (i, s) for i, s, t in todo}
        for fut in as_completed(futs):
            row = fut.result()
            rows[(int(row["id"]), str(row["source"]))] = row
            n += 1
            if n % 50 == 0 or n == len(todo):
                rate = n / max(time.time() - t0, 1e-6)
                log(f"  {n}/{len(todo)} id={row['id']} src={row['source']} sent={row.get('sentiment') or '-'} {rate:.1f}/s")
            if n % args.save_every == 0:
                write_all(partial_path, rows)
                log(f"  checkpoint → {partial_path.name} ({len(rows):,})")

    write_all(partial_path, rows)
    write_all(out_path, rows)
    log(f"done → {out_path} n={len(rows):,}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
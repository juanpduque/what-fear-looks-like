#!/usr/bin/env python3
"""AWS Textract OCR for corpus posters — separate from EasyOCR.

Writes ONLY:
  data/poster_ocr_textract.csv
  data/poster_ocr_textract_partial.csv

Does NOT touch data/poster_ocr.csv (EasyOCR baseline for comparison).

  export AWS_PROFILE=sandbox
  python3 poster_ocr_textract.py --limit 20 --workers 8
  python3 poster_ocr_textract.py --workers 12          # full corpus, resume

Region: us-east-1 (workshop allows Textract there).
"""
from __future__ import annotations

import argparse
import csv
import io
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
POSTERS_CSV = DATA / "posters.csv"
DEFAULT_OUT = DATA / "poster_ocr_textract.csv"
DEFAULT_PARTIAL = DATA / "poster_ocr_textract_partial.csv"
REGION = "us-east-1"
MAX_BYTES = 4_500_000
MAX_SIDE = 1280

FIELDS = ["id", "full_ocr", "n_lines", "n_words", "mean_conf", "latency_s", "error"]

_print_lock = threading.Lock()
_write_lock = threading.Lock()


def log(msg: str) -> None:
    with _print_lock:
        print(msg, flush=True)


def load_done(force: bool, *paths: Path) -> dict[int, dict]:
    if force:
        return {}
    out: dict[int, dict] = {}
    for path in paths:
        if not path.exists():
            continue
        with path.open(encoding="utf-8", errors="replace") as f:
            for r in csv.DictReader(f):
                try:
                    pid = int(r["id"])
                except (KeyError, TypeError, ValueError):
                    continue
                out[pid] = r
    return out


def write_rows(path: Path, rows: dict[int, dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with _write_lock:
        with path.open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore")
            w.writeheader()
            for pid in sorted(rows):
                w.writerow(rows[pid])


def load_ids_file(path: Path) -> list[int]:
    ids: list[int] = []
    seen: set[int] = set()
    with path.open(encoding="utf-8", errors="replace") as f:
        first = f.readline()
        if not first:
            return []
        if "id" in first.lower() and ("," in first or "\t" in first):
            f.seek(0)
            for r in csv.DictReader(f):
                try:
                    pid = int(float(r["id"]))
                except Exception:
                    continue
                if pid not in seen:
                    seen.add(pid)
                    ids.append(pid)
            return ids

        def _add(tok: str) -> None:
            tok = tok.strip().split(",")[0]
            if not tok:
                return
            try:
                pid = int(float(tok))
            except Exception:
                return
            if pid not in seen:
                seen.add(pid)
                ids.append(pid)

        _add(first)
        for line in f:
            _add(line)
    return ids


def corpus_ids(ids_arg: str, limit: int, ids_file: Path | None) -> list[int]:
    if ids_file:
        ids = load_ids_file(ids_file)
    elif ids_arg:
        ids = [int(x) for x in ids_arg.split(",") if x.strip()]
    else:
        ids = (
            pd.read_csv(POSTERS_CSV, usecols=["id"])["id"]
            .astype(int)
            .drop_duplicates()
            .tolist()
        )
    if limit > 0:
        ids = ids[:limit]
    return ids


def prepare_bytes(path: Path) -> bytes:
    raw = path.read_bytes()
    need = len(raw) > MAX_BYTES
    if not need:
        try:
            im = Image.open(io.BytesIO(raw))
            im.load()
            if max(im.size) <= MAX_SIDE and path.suffix.lower() in {".jpg", ".jpeg"}:
                return raw
        except Exception:
            need = True
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
    if len(data) > MAX_BYTES:
        raise ValueError(f"still >{MAX_BYTES} after compress")
    return data


def ocr_one(client, pid: int) -> dict:
    t0 = time.perf_counter()
    path = POSTERS / f"{pid}.jpg"
    if not path.exists():
        alt = POSTERS / f"{pid}.png"
        path = alt if alt.exists() else path
    if not path.exists():
        return {
            "id": pid,
            "full_ocr": "",
            "n_lines": 0,
            "n_words": 0,
            "mean_conf": "",
            "latency_s": round(time.perf_counter() - t0, 3),
            "error": "missing_jpg",
        }
    try:
        data = prepare_bytes(path)
        last_err: Exception | None = None
        for attempt in range(5):
            try:
                resp = client.detect_document_text(Document={"Bytes": data})
                break
            except ClientError as e:
                last_err = e
                code = e.response.get("Error", {}).get("Code", "")
                if code in (
                    "ThrottlingException",
                    "ProvisionedThroughputExceededException",
                    "LimitExceededException",
                ):
                    time.sleep(min(20.0, 1.2 * (2**attempt)))
                    continue
                raise
        else:
            assert last_err is not None
            raise last_err

        lines: list[str] = []
        confs: list[float] = []
        n_words = 0
        for b in resp.get("Blocks") or []:
            bt = b.get("BlockType")
            if bt == "LINE":
                t = (b.get("Text") or "").strip()
                if t:
                    lines.append(t)
                if "Confidence" in b:
                    confs.append(float(b["Confidence"]) / 100.0)
            elif bt == "WORD":
                n_words += 1
                if "Confidence" in b:
                    confs.append(float(b["Confidence"]) / 100.0)
        mean_conf = round(sum(confs) / len(confs), 4) if confs else ""
        return {
            "id": pid,
            "full_ocr": "\n".join(lines),
            "n_lines": len(lines),
            "n_words": n_words,
            "mean_conf": mean_conf,
            "latency_s": round(time.perf_counter() - t0, 3),
            "error": "",
        }
    except Exception as e:
        return {
            "id": pid,
            "full_ocr": "",
            "n_lines": 0,
            "n_words": 0,
            "mean_conf": "",
            "latency_s": round(time.perf_counter() - t0, 3),
            "error": f"{type(e).__name__}: {e}"[:240],
        }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--ids", default="")
    ap.add_argument("--ids-file", type=Path, default=None)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--workers", type=int, default=12)
    ap.add_argument("--save-every", type=int, default=50)
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--region", default=REGION)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--partial", type=Path, default=None)
    args = ap.parse_args()

    out_path = args.out
    partial_path = args.partial or out_path.with_name(out_path.stem + "_partial.csv")

    ids = corpus_ids(args.ids, args.limit, args.ids_file)
    rows = load_done(args.force, out_path, partial_path)
    todo = [pid for pid in ids if pid not in rows]
    log(
        f"textract OCR start ids={len(ids):,} done={len(rows):,} "
        f"todo={len(todo):,} workers={args.workers} region={args.region} "
        f"out={out_path.name}"
    )

    session = boto3.Session(profile_name=__import__("os").environ.get("AWS_PROFILE") or None)
    client = session.client(
        "textract",
        region_name=args.region,
        config=Config(
            read_timeout=60,
            connect_timeout=10,
            retries={"max_attempts": 3},
            max_pool_connections=max(args.workers + 4, 20),
        ),
    )

    t0 = time.time()
    n_done = 0
    n_ok = 0
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as ex:
        futs = {ex.submit(ocr_one, client, pid): pid for pid in todo}
        for fut in as_completed(futs):
            row = fut.result()
            rows[int(row["id"])] = row
            n_done += 1
            if not row.get("error"):
                n_ok += 1
            if n_done % 20 == 0 or n_done == len(todo):
                rate = n_done / max(time.time() - t0, 1e-6)
                eta = (len(todo) - n_done) / max(rate, 1e-6)
                preview = (row.get("full_ocr") or "").replace("\n", " ")[:50]
                log(
                    f"  {n_done}/{len(todo)} id={row['id']} lines={row.get('n_lines')} "
                    f"err={row.get('error') or '-'} {rate:.2f}/s eta={eta/3600:.2f}h | {preview!r}"
                )
            if n_done % args.save_every == 0:
                write_rows(partial_path, rows)
                log(f"  checkpoint → {partial_path.name} ({len(rows):,})")

    write_rows(partial_path, rows)
    write_rows(out_path, rows)
    log(
        f"done wrote {out_path} n={len(rows):,} new={n_done:,} ok={n_ok:,} "
        f"elapsed={(time.time()-t0)/60:.1f}m"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())

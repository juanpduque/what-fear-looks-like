#!/usr/bin/env python3
"""Rekognition DetectText OCR — third OCR track for comparison.

Writes ONLY:
  data/poster_ocr_rek_text.csv
  data/poster_ocr_rek_text_partial.csv

Does not touch EasyOCR or Textract CSVs.

  export AWS_PROFILE=sandbox
  python3 poster_ocr_rek_text.py --workers 12
  python3 poster_ocr_rek_text.py --ids-file data/qa/rek_text_alllang_ids.txt \\
      --out data/poster_ocr_rek_text_alllang.csv --workers 12
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
DEFAULT_OUT = DATA / "poster_ocr_rek_text.csv"
DEFAULT_PARTIAL = DATA / "poster_ocr_rek_text_partial.csv"
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
                    out[int(r["id"])] = r
                except Exception:
                    pass
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
        # CSV with id header, or one id per line
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
            tok = tok.strip()
            if not tok:
                return
            try:
                pid = int(float(tok))
            except Exception:
                return
            if pid not in seen:
                seen.add(pid)
                ids.append(pid)

        _add(first.strip().split(",")[0])
        for line in f:
            _add(line.strip().split(",")[0])
    return ids


def prepare_bytes(path: Path) -> bytes:
    raw = path.read_bytes()
    try:
        im = Image.open(io.BytesIO(raw))
        im.load()
        if len(raw) <= MAX_BYTES and max(im.size) <= MAX_SIDE and path.suffix.lower() in {".jpg", ".jpeg"}:
            return raw
    except Exception:
        pass
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
        last = None
        for attempt in range(5):
            try:
                resp = client.detect_text(Image={"Bytes": data})
                break
            except ClientError as e:
                last = e
                code = e.response.get("Error", {}).get("Code", "")
                if code in ("ThrottlingException", "ProvisionedThroughputExceededException"):
                    time.sleep(min(16, 1.2 * (2**attempt)))
                    continue
                raise
        else:
            raise last  # type: ignore

        lines, words, confs = [], 0, []
        # DetectText returns detections; prefer LINE for full_ocr order by top
        dets = resp.get("TextDetections") or []
        line_items = []
        for d in dets:
            t = (d.get("DetectedText") or "").strip()
            if not t:
                continue
            conf = float(d.get("Confidence") or 0) / 100.0
            confs.append(conf)
            if d.get("Type") == "LINE":
                geo = ((d.get("Geometry") or {}).get("BoundingBox") or {})
                top = float(geo.get("Top") or 0)
                left = float(geo.get("Left") or 0)
                line_items.append((top, left, t))
            elif d.get("Type") == "WORD":
                words += 1
        line_items.sort(key=lambda x: (round(x[0] * 40) / 40, x[1]))
        lines = [t for _, _, t in line_items]
        return {
            "id": pid,
            "full_ocr": "\n".join(lines),
            "n_lines": len(lines),
            "n_words": words,
            "mean_conf": round(sum(confs) / len(confs), 4) if confs else "",
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
    ap.add_argument("--save-every", type=int, default=100)
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--region", default=REGION)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--partial", type=Path, default=None)
    args = ap.parse_args()

    out_path = args.out
    partial_path = args.partial or out_path.with_name(out_path.stem + "_partial.csv")

    if args.ids_file:
        ids = load_ids_file(args.ids_file)
    elif args.ids:
        ids = [int(x) for x in args.ids.split(",") if x.strip()]
    else:
        ids = pd.read_csv(POSTERS_CSV, usecols=["id"])["id"].astype(int).drop_duplicates().tolist()
    if args.limit > 0:
        ids = ids[: args.limit]

    rows = load_done(args.force, out_path, partial_path)
    todo = [i for i in ids if i not in rows]
    log(
        f"rek DetectText start ids={len(ids):,} done={len(rows):,} todo={len(todo):,} "
        f"workers={args.workers} out={out_path.name}"
    )

    client = boto3.client(
        "rekognition",
        region_name=args.region,
        config=Config(retries={"max_attempts": 4}, max_pool_connections=max(args.workers + 4, 20)),
    )

    t0 = time.time()
    n = n_ok = 0
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as ex:
        futs = {ex.submit(ocr_one, client, pid): pid for pid in todo}
        for fut in as_completed(futs):
            row = fut.result()
            rows[int(row["id"])] = row
            n += 1
            if not row.get("error"):
                n_ok += 1
            if n % 40 == 0 or n == len(todo):
                rate = n / max(time.time() - t0, 1e-6)
                eta = (len(todo) - n) / max(rate, 1e-6)
                prev = (row.get("full_ocr") or "").replace("\n", " ")[:45]
                log(
                    f"  {n}/{len(todo)} id={row['id']} lines={row.get('n_lines')} "
                    f"err={row.get('error') or '-'} {rate:.2f}/s eta={eta/3600:.2f}h | {prev!r}"
                )
            if n % args.save_every == 0:
                write_rows(partial_path, rows)
                log(f"  checkpoint → {partial_path.name} ({len(rows):,})")

    write_rows(partial_path, rows)
    write_rows(out_path, rows)
    log(f"done → {out_path} n={len(rows):,} new_ok={n_ok:,} elapsed={(time.time()-t0)/60:.1f}m")
    return 0


if __name__ == "__main__":
    sys.exit(main())

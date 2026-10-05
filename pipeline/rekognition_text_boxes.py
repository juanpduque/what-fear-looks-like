#!/usr/bin/env python3
"""Rekognition DetectText keeping every LINE with its BoundingBox.

title_boxes_rekognition.py keeps only the best title box; this run keeps all
lines (title, tagline, credits) so the title box can be re-derived offline and
the full text layer can be drawn.

Output: data/rekognition_text_boxes.csv
  id, n_lines, lines (JSON list of {text, conf, box:[x,y,w,h]}), full_text, src, error

Same safety rules as rekognition_label_boxes.py: one row appended per poster,
resume skips only rows without error, USB drop stops the run.

  export AWS_PROFILE=sandbox_bedrock AWS_DEFAULT_REGION=us-east-1
  python3 rekognition_text_boxes.py --ids-file data/qa/text_gap_site_ids.txt \
      --local-dir "/Volumes/Adata Bituan/what-fear-looks-like-data/posters" --workers 6

Cost: ~$0.001 / image.
"""
from __future__ import annotations

import argparse
import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from botocore.exceptions import ClientError

import rekognition_label_boxes as base
from rekognition_utils import load_image_bytes_for_rekognition

OUT = base.DATA / "rekognition_text_boxes.csv"
FIELDS = ["id", "n_lines", "lines", "full_text", "src", "error"]


def _call(image: dict) -> dict:
    for attempt in range(5):
        try:
            return base._rek().detect_text(Image=image)
        except ClientError as e:
            code = e.response.get("Error", {}).get("Code", "")
            if code in ("ThrottlingException", "ProvisionedThroughputExceededException") and attempt < 4:
                time.sleep(1.5 * (attempt + 1))
                continue
            raise


def parse(resp: dict) -> list:
    lines = []
    for d in resp.get("TextDetections") or []:
        if d.get("Type") != "LINE":
            continue
        bb = (d.get("Geometry") or {}).get("BoundingBox") or {}
        x = max(0.0, min(1.0, float(bb.get("Left", 0))))
        y = max(0.0, min(1.0, float(bb.get("Top", 0))))
        w = max(0.0, min(1.0 - x, float(bb.get("Width", 0))))
        h = max(0.0, min(1.0 - y, float(bb.get("Height", 0))))
        if w <= 0 or h <= 0:
            continue
        lines.append({
            "text": d.get("DetectedText", ""),
            "conf": round(float(d.get("Confidence") or 0), 1),
            "box": [round(x, 4), round(y, 4), round(w, 4), round(h, 4)],
        })
    return lines


def process(pid: int, local_dir: Path | None, use_s3: bool) -> dict:
    row = {"id": pid, "n_lines": 0, "lines": "", "full_text": "", "src": "", "error": ""}
    image = None
    if local_dir is not None:
        path = local_dir / f"{pid}.jpg"
        try:
            if path.is_file():
                image = {"Bytes": load_image_bytes_for_rekognition(path)}
                row["src"] = "local"
        except OSError as e:
            raise SystemExit(f"posters dir unreadable ({e}); stopping so resume can pick up")
    if image is None and use_s3:
        image = {"S3Object": {"Bucket": base.BUCKET, "Name": f"{base.PREFIX}/{pid}.jpg"}}
        row["src"] = "s3"
    if image is None:
        row["error"] = "no_source"
        return row
    try:
        lines = parse(_call(image))
    except Exception as e:
        row["error"] = str(e)[:300]
        return row
    row["n_lines"] = len(lines)
    row["lines"] = json.dumps(lines, ensure_ascii=False, separators=(",", ":"))
    row["full_text"] = " ".join(l["text"] for l in lines)[:2000]
    return row


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ids-file", required=True)
    ap.add_argument("--out", default=str(OUT))
    ap.add_argument("--local-dir", default="")
    ap.add_argument("--no-s3", action="store_true")
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    base.FIELDS = FIELDS
    out = Path(args.out)
    local_dir = Path(args.local_dir) if args.local_dir else None
    if local_dir is not None and not local_dir.is_dir():
        raise SystemExit(f"posters dir missing: {local_dir}")

    ids = [int(x) for x in Path(args.ids_file).read_text().split() if x.strip().isdigit()]
    done = base.load_done(out)
    todo = [i for i in ids if i not in done]
    if args.limit:
        todo = todo[: args.limit]
    print(f"ids={len(ids)} done={len(done)} todo={len(todo)} out={out}", flush=True)

    t0 = time.time()
    ok = err = 0
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = [ex.submit(process, pid, local_dir, not args.no_s3) for pid in todo]
        for n, fut in enumerate(as_completed(futs), 1):
            row = fut.result()
            base.append_row(out, row)
            if row["error"]:
                err += 1
            else:
                ok += 1
            if n % 100 == 0 or n == len(todo):
                rate = n / max(1e-6, time.time() - t0)
                print(f"[{n}/{len(todo)}] ok={ok} err={err} {rate:.1f}/s "
                      f"eta={(len(todo) - n) / max(rate, 1e-6) / 60:.1f}m", flush=True)
    print(f"DONE ok={ok} err={err} -> {out}")


if __name__ == "__main__":
    main()

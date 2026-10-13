#!/usr/bin/env python3
"""PaddleOCR on Japanese, Chinese, Korean and Thai horror posters.

Rekognition DetectText (title_boxes_rekognition.csv) only reads Latin script,
so on these posters it boxes an English subtitle or credits, or nothing. This
runs PaddleOCR with a recognizer for each script on the sheet the pipeline
measured (horror_movies.csv poster_path) and keeps every text line with its box.

Detection: PP-OCRv6 medium. Recognition: PP-OCRv6 medium (Chinese/Japanese)
or PP-OCRv5 mobile (Korean, Thai). Runs on CPU; no AWS.

  python3 paddleocr_world_titles.py [--limit N] [--english N]

--english N adds a random sample of N English-language corpus posters from
2000–2026 (seed 7), so title sizes compare within one OCR engine.

Writes data/qa/paddleocr_world/lines.jsonl, one poster per line:
  {id, lang, poster_path, w, h, status, lines: [{text, score, box: [x, y, w, h]}]}
Boxes are fractions of the poster. Resumable: ids already written are skipped.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import random
import time
from pathlib import Path

os.environ.setdefault("FLAGS_use_mkldnn", "0")
os.environ.setdefault("FLAGS_onednn", "0")
os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")

import requests  # noqa: E402
from PIL import Image  # noqa: E402

from corpus import canonical_ids  # noqa: E402
from export_world_faces import comparable_non_english  # noqa: E402

HERE = Path(__file__).resolve().parent
DATA = HERE / "data"
OUT_DIR = DATA / "qa" / "paddleocr_world"
OUT = OUT_DIR / "lines.jsonl"
IMG_BASE = "https://image.tmdb.org/t/p/w500"
REC_MODEL = {
    "ja": "PP-OCRv6_medium_rec",
    "zh": "PP-OCRv6_medium_rec",
    "ko": "korean_PP-OCRv5_mobile_rec",
    "th": "th_PP-OCRv5_mobile_rec",
    "en": "PP-OCRv6_medium_rec",
}
RECENT = (2000, 2026)


def fetch(poster_path: str, cache: Path) -> Path:
    path = cache / poster_path.lstrip("/")
    if not path.exists():
        resp = requests.get(f"{IMG_BASE}{poster_path}", timeout=30)
        resp.raise_for_status()
        path.write_bytes(resp.content)
    return path


def lines_of(result, w: int, h: int) -> list[dict]:
    out = []
    for page in result if isinstance(result, list) else [result]:
        texts = page.get("rec_texts") or []
        scores = page.get("rec_scores") or []
        polys = page.get("rec_polys")
        polys = [] if polys is None else polys
        for text, score, poly in zip(texts, scores, polys):
            xs = [float(p[0]) for p in poly]
            ys = [float(p[1]) for p in poly]
            x0, y0 = max(0.0, min(xs)), max(0.0, min(ys))
            out.append(
                {
                    "text": str(text),
                    "score": round(float(score), 3),
                    "box": [
                        round(x0 / w, 4),
                        round(y0 / h, 4),
                        round((min(w, max(xs)) - x0) / w, 4),
                        round((min(h, max(ys)) - y0) / h, 4),
                    ],
                }
            )
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="posters per language (0 = all)")
    ap.add_argument("--english", type=int, default=0, help="English-corpus control sample size")
    ap.add_argument("--cache", type=Path, default=OUT_DIR / "posters")
    args = ap.parse_args()

    langs = {pid: lang for pid, lang in comparable_non_english().items() if lang in REC_MODEL}
    rows = {}
    with (DATA / "horror_movies.csv").open(newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if (r.get("poster_path") or "").startswith("/"):
                rows[int(r["id"])] = r
    if args.english:
        recent = []
        for pid in canonical_ids():
            year = (rows.get(pid, {}).get("release_date") or "")[:4]
            if year.isdigit() and RECENT[0] <= int(year) <= RECENT[1]:
                recent.append(pid)
        for pid in random.Random(7).sample(sorted(recent), args.english):
            langs[pid] = "en"
    paths = {pid: rows[pid]["poster_path"] for pid in langs if pid in rows}
    done = set()
    if OUT.exists():
        done = {json.loads(line)["id"] for line in OUT.open(encoding="utf-8")}
    args.cache.mkdir(parents=True, exist_ok=True)

    from paddleocr import PaddleOCR

    with OUT.open("a", encoding="utf-8") as out:
        for lang, rec_model in REC_MODEL.items():
            ids = sorted(pid for pid in paths if langs[pid] == lang and pid not in done)
            if args.limit:
                ids = ids[: args.limit]
            if not ids:
                continue
            ocr = PaddleOCR(
                text_detection_model_name="PP-OCRv6_medium_det",
                text_recognition_model_name=rec_model,
                use_doc_orientation_classify=False,
                use_doc_unwarping=False,
                use_textline_orientation=True,
                device="cpu",
            )
            t0 = time.perf_counter()
            for i, pid in enumerate(ids, 1):
                rec = {"id": pid, "lang": lang, "poster_path": paths[pid]}
                try:
                    img = fetch(paths[pid], args.cache)
                    with Image.open(img) as im:
                        w, h = im.size
                    rec.update(w=w, h=h, status="ok", lines=lines_of(ocr.predict(str(img)), w, h))
                except Exception as e:  # noqa: BLE001 - keep going, record the failure
                    rec.update(status="error", error=str(e)[:300], lines=[])
                out.write(json.dumps(rec, ensure_ascii=False) + "\n")
                out.flush()
                if i % 50 == 0 or i == len(ids):
                    rate = (time.perf_counter() - t0) / i
                    print(
                        f"{lang} {i}/{len(ids)}  {rate:.1f}s/img  eta {rate * (len(ids) - i) / 60:.0f} min",
                        flush=True,
                    )
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""PP-OCRv6 medium (classic det+rec, NOT PaddleOCR-VL) on hard OCR ids.

Uses the same 12-id hard sample / poster sources as ocr_qwen_hard.
Result model tag: ppocrv6-medium.

  python3 pilot_ppocrv6_hard.py
  python3 pilot_ppocrv6_hard.py --device cpu
"""
from __future__ import annotations

import argparse
import csv
import os
import shutil
import sys
import time
import traceback
from pathlib import Path

import pandas as pd

from ocr_metrics import title_overlap_score

# OneDNN / MKLDNN PIR bugs broke TextDetection on some AMI paddle builds.
os.environ.setdefault("FLAGS_use_mkldnn", "0")
os.environ.setdefault("FLAGS_onednn", "0")
os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")

PIPE = Path(__file__).resolve().parent
DATA = PIPE / "data"
HARD_QA = DATA / "qa" / "ocr_qwen_hard"
OUT_DIR = DATA / "qa" / "ocr_ppocrv6_hard"
DEFAULT_POSTERS = DATA / "qa" / "_ocr_qwen_hard_stage" / "posters"
POSTERS_CSV = DATA / "posters.csv"

RESULT_MODEL = "ppocrv6-medium"
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


def _ppocr_item_texts(item) -> list[str]:
    texts: list[str] = []
    if item is None:
        return texts
    rec = None
    if isinstance(item, dict) or hasattr(item, "get"):
        try:
            rec = item.get("rec_texts")  # type: ignore[union-attr]
        except Exception:
            rec = None
        if rec is None and hasattr(item, "get"):
            try:
                rec = item.get("rec_text")
            except Exception:
                rec = None
    if rec is not None:
        if isinstance(rec, (list, tuple)):
            texts.extend(str(t) for t in rec if t)
        elif rec:
            texts.append(str(rec))
        return texts
    if isinstance(item, (list, tuple)):
        for line in item:
            if line is None:
                continue
            try:
                if isinstance(line, (list, tuple)) and len(line) >= 2:
                    info = line[1]
                    if isinstance(info, (list, tuple)) and info:
                        texts.append(str(info[0]))
                    elif isinstance(info, str):
                        texts.append(info)
            except Exception:
                continue
    return texts


def _ppocr_texts(result) -> list[str]:
    if result is None:
        return []
    pages = result if isinstance(result, list) else [result]
    texts: list[str] = []
    for page in pages:
        texts.extend(_ppocr_item_texts(page))
    return texts


def _init_ppocrv6(device: str):
    from paddleocr import PaddleOCR

    kwargs = dict(
        text_detection_model_name="PP-OCRv6_medium_det",
        text_recognition_model_name="PP-OCRv6_medium_rec",
        use_doc_orientation_classify=False,
        use_doc_unwarping=False,
        use_textline_orientation=True,
        device=device,
    )
    print(f"  init PaddleOCR PP-OCRv6 medium device={device}", flush=True)
    return PaddleOCR(**kwargs)


def load_sample(ids_file: Path) -> pd.DataFrame:
    posters = pd.read_csv(POSTERS_CSV, usecols=["id", "title", "year"])
    posters["id"] = posters["id"].astype(int)
    ids = [int(x) for x in ids_file.read_text(encoding="utf-8").split() if x.strip()]
    df = posters[posters["id"].isin(ids)].copy()
    order = {pid: i for i, pid in enumerate(ids)}
    df["_ord"] = df["id"].map(order)
    return df.sort_values("_ord").drop(columns=["_ord"]).reset_index(drop=True)


def write_results(rows: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=RESULT_FIELDS, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)


def make_row(pid, title, year, text, latency_s, status) -> dict:
    ok = status == "ok"
    score = title_overlap_score(text, title) if ok else 0.0
    return {
        "id": pid,
        "title": title,
        "year": year,
        "model": RESULT_MODEL,
        "text": (text or "").replace("\n", "\\n"),
        "chars": len(text or "") if ok else 0,
        "title_overlap_score": score,
        "latency_s": round(float(latency_s), 3),
        "status": status,
    }


def stage_meta(out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    for name in ("sample_ids.txt", "sample_meta.csv", "poster_sources.csv"):
        src = HARD_QA / name
        if src.exists():
            shutil.copy2(src, out / name)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--ids-file", default=str(HARD_QA / "sample_ids.txt"))
    ap.add_argument("--posters-dir", default=str(DEFAULT_POSTERS))
    ap.add_argument("--out-dir", default=str(OUT_DIR))
    ap.add_argument("--device", default="cpu", help="cpu | gpu | gpu:0 (paddle device)")
    args = ap.parse_args()

    out = Path(args.out_dir)
    posters_dir = Path(args.posters_dir)
    ids_path = Path(args.ids_file)
    if not ids_path.exists():
        raise SystemExit(f"missing ids: {ids_path}")
    if not posters_dir.is_dir():
        raise SystemExit(f"missing posters dir: {posters_dir}")

    stage_meta(out)
    sample = load_sample(ids_path)
    print(f"sample n={len(sample)} posters={posters_dir}", flush=True)
    print(sample[["id", "title", "year"]].to_string(index=False), flush=True)

    t_load = time.perf_counter()
    try:
        ocr = _init_ppocrv6(args.device)
    except Exception as e:
        print(f"INIT FAIL: {e}", flush=True)
        traceback.print_exc()
        return 1
    print(f"  load_s={time.perf_counter() - t_load:.2f}", flush=True)

    rows: list[dict] = []
    results_csv = out / "results.csv"
    model_dir = out / RESULT_MODEL
    model_dir.mkdir(parents=True, exist_ok=True)

    for _, r in sample.iterrows():
        pid = int(r["id"])
        title = str(r.get("title") or "")
        year = r.get("year", "")
        img = posters_dir / f"{pid}.jpg"
        t0 = time.perf_counter()
        status = "ok"
        text = ""
        try:
            if not img.exists():
                raise FileNotFoundError(f"missing {img}")
            result = None
            if hasattr(ocr, "predict"):
                try:
                    result = ocr.predict(str(img))
                except Exception:
                    result = None
            if result is None:
                try:
                    result = ocr.ocr(str(img), cls=True)
                except TypeError:
                    result = ocr.ocr(str(img))
            parts = _ppocr_texts(result)
            text = "\n".join(p.strip() for p in parts if p and str(p).strip())
        except Exception as e:
            status = f"error: {e}"[:500]
            print(f"  id={pid} FAIL {status}", flush=True)
            traceback.print_exc()
        lat = time.perf_counter() - t0
        row = make_row(pid, title, year, text, lat, status)
        rows.append(row)
        write_results(rows, results_csv)
        if status == "ok" and text:
            (model_dir / f"{pid}.txt").write_text(text, encoding="utf-8")
        print(
            f"  id={pid} status={status[:40]} chars={row['chars']} "
            f"overlap={row['title_overlap_score']} {row['latency_s']}s",
            flush=True,
        )

    print(f"\nLISTO → {results_csv} ({len(rows)} rows)", flush=True)
    ov = [float(r["title_overlap_score"]) for r in rows]
    print(
        f"ppocrv6-medium mean={sum(ov)/len(ov):.4f} median={sorted(ov)[len(ov)//2]:.4f}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())

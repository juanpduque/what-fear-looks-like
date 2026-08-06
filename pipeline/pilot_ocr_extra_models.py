#!/usr/bin/env python3
"""Pilot extras: Florence-2 + classic PaddleOCR (PP-OCR) on the OCR pilot sample.

Runs on the SAME sample as pilot_ocr_models.py (sample_ids.txt) and merges
rows into data/qa/ocr_pilot/results.csv for models florence / ppocr only
(existing model rows are preserved).

  python3 pilot_ocr_extra_models.py
  python3 pilot_ocr_extra_models.py --models florence,ppocr
  python3 pilot_ocr_extra_models.py --models ppocr          # CPU classic OCR
  python3 pilot_ocr_extra_models.py --models florence --device mps

Models:
  florence → microsoft/Florence-2-base (or -base-ft) with task prompt <OCR>
  ppocr    → classic paddleocr PP-OCR (NOT PaddleOCR-VL)

Install:
  pip install -U transformers accelerate pillow pandas
  pip install paddlepaddle paddleocr   # CPU; or paddlepaddle-gpu on CUDA
"""
from __future__ import annotations

import argparse
import csv
import gc
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
DEFAULT_OUT_DIR = DATA / "qa" / "ocr_pilot"
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

EXTRA_MODELS = ("florence", "ppocr")

# Prefer florence-community (native transformers Florence2*). microsoft/*
# remote-code breaks on transformers>=5 (forced_bos_token_id / image_token).
FLORENCE_IDS = (
    "florence-community/Florence-2-base",
    "microsoft/Florence-2-base",
    "microsoft/Florence-2-base-ft",
)
FLORENCE_TASK = "<OCR>"


def configure_out_dir(path: str | Path) -> None:
    global OUT_DIR, RESULTS_CSV, SAMPLE_IDS
    OUT_DIR = Path(path)
    RESULTS_CSV = OUT_DIR / "results.csv"
    SAMPLE_IDS = OUT_DIR / "sample_ids.txt"


def pick_device() -> str:
    try:
        import torch

        if torch.cuda.is_available():
            return "cuda"
        if getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
            return "mps"
    except Exception:
        pass
    return "cpu"


def unload_device() -> None:
    gc.collect()
    try:
        import torch

        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            torch.cuda.ipc_collect()
        if getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
            torch.mps.empty_cache()
    except Exception:
        pass


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


# ── Florence-2 ───────────────────────────────────────────────────────────────


class FlorenceRunner:
    def __init__(self, device: str, model_id: str | None = None):
        import torch

        self.device = device
        self.task = FLORENCE_TASK
        # MPS: float32 is more stable; CUDA: float16
        if device == "cuda":
            self.dtype = torch.float16
        else:
            self.dtype = torch.float32

        last_err: Exception | None = None
        candidates = [model_id] if model_id else list(FLORENCE_IDS)
        self.model = None
        self.processor = None
        self.model_id = ""
        for mid in candidates:
            if not mid:
                continue
            try:
                print(f"  loading Florence-2 {mid} on {device} dtype={self.dtype}", flush=True)
                processor, model = self._load_pair(mid, device, self.dtype)
                self.processor = processor
                self.model = model
                self.model_id = mid
                print(f"  loaded {mid}", flush=True)
                return
            except Exception as e:
                last_err = e
                print(f"  Florence load failed for {mid}: {e}", flush=True)
                traceback.print_exc()
                unload_device()
        raise RuntimeError(f"Florence-2 load failed (tried {candidates}): {last_err}")

    @staticmethod
    def _load_pair(mid: str, device: str, dtype):
        """Native Florence2* first; fall back to microsoft remote-code CausalLM."""
        from transformers import AutoProcessor

        # 1) Native transformers Florence2 (works with florence-community/*)
        try:
            from transformers import Florence2ForConditionalGeneration

            processor = AutoProcessor.from_pretrained(mid, trust_remote_code=False)
            model = Florence2ForConditionalGeneration.from_pretrained(
                mid,
                torch_dtype=dtype,
                trust_remote_code=False,
            )
            return processor, model.to(device).eval()
        except Exception as native_err:
            print(f"  native Florence2 path failed ({native_err}); trying remote code", flush=True)

        # 2) microsoft/* remote code (transformers 4.x era)
        from transformers import AutoModelForCausalLM

        processor = AutoProcessor.from_pretrained(mid, trust_remote_code=True)
        model = AutoModelForCausalLM.from_pretrained(
            mid,
            torch_dtype=dtype,
            trust_remote_code=True,
            attn_implementation="eager",
        )
        return processor, model.to(device).eval()

    def run(self, image_path: Path) -> str:
        import torch
        from PIL import Image

        image = Image.open(image_path).convert("RGB")
        inputs = self.processor(text=self.task, images=image, return_tensors="pt")
        moved = {}
        for k, v in inputs.items():
            if hasattr(v, "to"):
                if k == "pixel_values":
                    moved[k] = v.to(self.device, dtype=self.dtype)
                else:
                    moved[k] = v.to(self.device)
            else:
                moved[k] = v

        with torch.no_grad():
            # Prefer full **moved (native may add extra keys); fall back to classic pair
            try:
                generated_ids = self.model.generate(
                    **moved,
                    max_new_tokens=1024,
                    num_beams=3,
                    do_sample=False,
                )
            except TypeError:
                generated_ids = self.model.generate(
                    input_ids=moved["input_ids"],
                    pixel_values=moved["pixel_values"],
                    max_new_tokens=1024,
                    num_beams=3,
                    do_sample=False,
                )

        if hasattr(self.processor, "batch_decode"):
            generated_text = self.processor.batch_decode(
                generated_ids, skip_special_tokens=False
            )[0]
        else:
            generated_text = self.processor.tokenizer.batch_decode(
                generated_ids, skip_special_tokens=False
            )[0]

        if hasattr(self.processor, "post_process_generation"):
            parsed = self.processor.post_process_generation(
                generated_text,
                task=self.task,
                image_size=(image.width, image.height),
            )
        else:
            parsed = generated_text

        # OCR → plain string; OCR_WITH_REGION → dict with labels
        if isinstance(parsed, dict):
            val = parsed.get(self.task, parsed)
            if isinstance(val, dict) and "labels" in val:
                text = "\n".join(str(x) for x in val["labels"])
            else:
                text = str(val)
        else:
            text = str(parsed)
        return (text or "").strip()

    def close(self) -> None:
        try:
            del self.model, self.processor
        except Exception:
            pass
        unload_device()


def run_florence(sample: pd.DataFrame, rows: list[dict], device: str) -> None:
    print(f"\n=== model=florence device={device} n={len(sample)} ===", flush=True)
    try:
        runner = FlorenceRunner(device)
    except Exception as e:
        msg = f"load_error: {e}"
        print(msg, flush=True)
        traceback.print_exc()
        for _, r in sample.iterrows():
            append_result(
                rows,
                make_row(
                    int(r["id"]),
                    str(r.get("title") or ""),
                    r.get("year", ""),
                    "florence",
                    "",
                    0.0,
                    msg[:500],
                ),
            )
        unload_device()
        return

    try:
        for _, r in sample.iterrows():
            pid = int(r["id"])
            title = str(r.get("title") or "")
            year = r.get("year", "")
            img = POSTERS / f"{pid}.jpg"
            t0 = time.perf_counter()
            status = "ok"
            text = ""
            try:
                if not img.exists():
                    raise FileNotFoundError(f"missing {img}")
                text = runner.run(img) or ""
            except Exception as e:
                status = f"error: {e}"[:500]
                print(f"  id={pid} FAIL {status}", flush=True)
                traceback.print_exc()
                if "out of memory" in str(e).lower() or "oom" in str(e).lower():
                    unload_device()
            lat = time.perf_counter() - t0
            row = make_row(pid, title, year, "florence", text, lat, status)
            append_result(rows, row)
            print(
                f"  id={pid} status={status[:40]} chars={row['chars']} "
                f"overlap={row['title_overlap_score']} {row['latency_s']}s",
                flush=True,
            )
    finally:
        try:
            runner.close()
        except Exception:
            unload_device()


# ── Classic PaddleOCR (PP-OCR) ───────────────────────────────────────────────


def _ppocr_item_texts(item) -> list[str]:
    """Extract recognized strings from one page/result object."""
    texts: list[str] = []
    if item is None:
        return texts

    # PaddleOCR 3.x / paddlex OCRResult (dict-like) with rec_texts
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

    # Classic PP-OCR: page = [ [box, (text, conf)], ... ]
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
    """Normalize paddleocr output across API versions to a list of strings."""
    if result is None:
        return []
    pages = result if isinstance(result, list) else [result]
    texts: list[str] = []
    for page in pages:
        texts.extend(_ppocr_item_texts(page))
    return texts


def _init_ppocr(use_gpu: bool | None):
    """Init classic PP-OCR; paddleocr 3.x dropped use_gpu / show_log kwargs."""
    import os

    from paddleocr import PaddleOCR

    os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")

    if use_gpu is None:
        try:
            import paddle

            use_gpu = bool(paddle.device.is_compiled_with_cuda()) and paddle.device.cuda.device_count() > 0
        except Exception:
            use_gpu = False

    print(
        f"  init PaddleOCR lang=en use_angle_cls/textline_ori use_gpu={use_gpu}",
        flush=True,
    )

    # paddleocr 3.x: no use_gpu/show_log; prefer use_textline_orientation
    attempts = [
        dict(use_textline_orientation=True, lang="en"),
        dict(lang="en"),
        dict(use_angle_cls=True, lang="en", use_gpu=use_gpu, show_log=False),
        dict(use_angle_cls=True, lang="en", use_gpu=use_gpu),
        dict(use_angle_cls=True, lang="en"),
        dict(),
    ]
    last_err: Exception | None = None
    for kwargs in attempts:
        try:
            return PaddleOCR(**kwargs)
        except (TypeError, ValueError) as e:
            last_err = e
            continue
    raise RuntimeError(f"PaddleOCR init failed: {last_err}")


def run_ppocr(sample: pd.DataFrame, rows: list[dict], use_gpu: bool | None) -> None:
    print(f"\n=== model=ppocr (classic PaddleOCR) n={len(sample)} ===", flush=True)
    try:
        ocr = _init_ppocr(use_gpu)
    except Exception as e:
        msg = f"load_error: {e}"
        print(msg, flush=True)
        traceback.print_exc()
        for _, r in sample.iterrows():
            append_result(
                rows,
                make_row(
                    int(r["id"]),
                    str(r.get("title") or ""),
                    r.get("year", ""),
                    "ppocr",
                    "",
                    0.0,
                    msg[:500],
                ),
            )
        return

    for _, r in sample.iterrows():
        pid = int(r["id"])
        title = str(r.get("title") or "")
        year = r.get("year", "")
        img = POSTERS / f"{pid}.jpg"
        t0 = time.perf_counter()
        status = "ok"
        text = ""
        try:
            if not img.exists():
                raise FileNotFoundError(f"missing {img}")
            # paddleocr 3.x prefers predict(); older uses ocr()
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
        row = make_row(pid, title, year, "ppocr", text, lat, status)
        append_result(rows, row)
        print(
            f"  id={pid} status={status[:40]} chars={row['chars']} "
            f"overlap={row['title_overlap_score']} {row['latency_s']}s",
            flush=True,
        )


# ── Ranking ──────────────────────────────────────────────────────────────────


def print_comparison(rows: list[dict]) -> None:
    df = pd.DataFrame(rows)
    if df.empty:
        print("\n(no results)", flush=True)
        return

    df["title_overlap_score"] = pd.to_numeric(df["title_overlap_score"], errors="coerce")
    df["chars"] = pd.to_numeric(df["chars"], errors="coerce")
    df["latency_s"] = pd.to_numeric(df["latency_s"], errors="coerce")

    preferred = [
        "got",
        "deepseek",
        "paddle",
        "qianfan",
        "qwen",
        "easyocr",
        "rekognition",
        "google",
        "florence",
        "ppocr",
    ]
    models = [m for m in preferred if m in set(df["model"])] + [
        m for m in sorted(df["model"].unique()) if m not in preferred
    ]

    print("\n=== comparison (mean title_overlap / chars / latency; ok rate) ===", flush=True)
    lines = []
    for m in models:
        g = df[df["model"] == m]
        ok = g["status"].astype(str).eq("ok")
        n_ok = int(ok.sum())
        n = len(g)
        ov = g.loc[ok, "title_overlap_score"].mean() if n_ok else float("nan")
        ch = g.loc[ok, "chars"].mean() if n_ok else float("nan")
        lat = g.loc[ok, "latency_s"].mean() if n_ok else float("nan")
        ov_all = g["title_overlap_score"].mean()
        lines.append(
            {
                "model": m,
                "n": n,
                "ok": n_ok,
                "ok_pct": round(100.0 * n_ok / n, 1) if n else 0.0,
                "mean_overlap": round(float(ov), 4) if n_ok else None,
                "mean_overlap_all": round(float(ov_all), 4),
                "mean_chars": round(float(ch), 1) if n_ok else None,
                "mean_latency_s": round(float(lat), 3) if n_ok else None,
            }
        )

    summary = pd.DataFrame(lines).sort_values(
        "mean_overlap_all", ascending=False, na_position="last"
    )
    print(summary.to_string(index=False), flush=True)
    print("\nRanking by mean title_overlap (all rows):", flush=True)
    for i, r in enumerate(summary.itertuples(index=False), 1):
        ov = r.mean_overlap_all
        print(
            f"  {i:2d}. {r.model:12s}  overlap={ov:.4f}  "
            f"ok={r.ok}/{r.n}  chars≈{r.mean_chars}  latency≈{r.mean_latency_s}s",
            flush=True,
        )


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument(
        "--ids-file",
        default=str(SAMPLE_IDS),
        help="sample id list (default: data/qa/ocr_pilot/sample_ids.txt)",
    )
    ap.add_argument(
        "--models",
        default="florence,ppocr",
        help="comma-separated: florence,ppocr",
    )
    ap.add_argument("--device", default="", help="force cuda|mps|cpu for Florence")
    ap.add_argument(
        "--ppocr-gpu",
        action="store_true",
        help="force PaddleOCR use_gpu=True",
    )
    ap.add_argument(
        "--ppocr-cpu",
        action="store_true",
        help="force PaddleOCR use_gpu=False",
    )
    ap.add_argument(
        "--out-dir",
        default=str(DEFAULT_OUT_DIR),
        help="output dir (default: data/qa/ocr_pilot)",
    )
    args = ap.parse_args()
    configure_out_dir(args.out_dir)
    if args.ids_file == str(DEFAULT_OUT_DIR / "sample_ids.txt") and OUT_DIR != DEFAULT_OUT_DIR:
        args.ids_file = str(OUT_DIR / "sample_ids.txt")

    keys = [k.strip().lower() for k in args.models.split(",") if k.strip()]
    for k in keys:
        if k not in EXTRA_MODELS:
            raise SystemExit(f"unknown model '{k}'; choose from {list(EXTRA_MODELS)}")

    ids_path = Path(args.ids_file)
    if not ids_path.exists():
        raise SystemExit(f"missing ids file: {ids_path}")

    sample = load_sample(ids_path)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    print(f"sample n={len(sample)} from {ids_path}", flush=True)
    print(sample[["id", "title", "year"]].to_string(index=False), flush=True)

    rows: list[dict] = []
    if RESULTS_CSV.exists():
        with RESULTS_CSV.open(encoding="utf-8", errors="replace") as f:
            for r in csv.DictReader(f):
                if r.get("model") not in keys:
                    rows.append(r)
        print(
            f"kept {len(rows)} prior rows for models outside {keys}",
            flush=True,
        )

    device = args.device or pick_device()
    ppocr_gpu: bool | None
    if args.ppocr_gpu:
        ppocr_gpu = True
    elif args.ppocr_cpu:
        ppocr_gpu = False
    else:
        ppocr_gpu = None

    for key in keys:
        rows = [r for r in rows if r.get("model") != key]
        if key == "florence":
            run_florence(sample, rows, device)
        elif key == "ppocr":
            run_ppocr(sample, rows, ppocr_gpu)

    write_results(rows)
    print(f"\nLISTO → {RESULTS_CSV} ({len(rows)} rows)", flush=True)
    print_comparison(rows)
    return 0


if __name__ == "__main__":
    sys.exit(main())

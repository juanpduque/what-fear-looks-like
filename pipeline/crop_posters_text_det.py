#!/usr/bin/env python3
"""Detect text regions on posters and write crops for Qwen OCR.

Prefers classic PaddleOCR / PP-OCR detection (DBNet). Falls back to Surya
detection if Paddle init fails. Per-id fallback: full image copy when no boxes.

Usage:
  python3 crop_posters_text_det.py \\
    --ids-file data/qa/ocr_qwen_hard_crop/sample_ids.txt \\
    --posters-dir data/posters_hard \\
    --out-dir data/qa/ocr_qwen_hard_crop
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import shutil
import sys
import traceback
from pathlib import Path

import numpy as np
from PIL import Image


def _box_xyxy(pts) -> tuple[float, float, float, float] | None:
    """Normalize a polygon / xyxy / dict box to (x0,y0,x1,y1)."""
    if pts is None:
        return None
    if isinstance(pts, dict):
        if all(k in pts for k in ("x0", "y0", "x1", "y1")):
            return float(pts["x0"]), float(pts["y0"]), float(pts["x1"]), float(pts["y1"])
        if "bbox" in pts:
            return _box_xyxy(pts["bbox"])
        return None
    arr = np.asarray(pts, dtype=float)
    if arr.size < 4:
        return None
    if arr.ndim == 1 and arr.size == 4:
        x0, y0, x1, y1 = arr.tolist()
        return float(min(x0, x1)), float(min(y0, y1)), float(max(x0, x1)), float(max(y0, y1))
    if arr.ndim == 2 and arr.shape[1] >= 2:
        xs, ys = arr[:, 0], arr[:, 1]
        return float(xs.min()), float(ys.min()), float(xs.max()), float(ys.max())
    flat = arr.ravel()
    if flat.size >= 8:
        xs = flat[0::2]
        ys = flat[1::2]
        return float(xs.min()), float(ys.min()), float(xs.max()), float(ys.max())
    return None


def _extract_boxes_from_ppocr(result) -> list[tuple[float, float, float, float]]:
    boxes: list[tuple[float, float, float, float]] = []
    if result is None:
        return boxes
    pages = result if isinstance(result, list) else [result]
    for page in pages:
        if page is None:
            continue
        # paddlex / 3.x dict-like
        if isinstance(page, dict) or hasattr(page, "get"):
            for key in ("dt_polys", "rec_polys", "boxes", "dt_boxes"):
                try:
                    polys = page.get(key)  # type: ignore[union-attr]
                except Exception:
                    polys = None
                if polys is None:
                    continue
                for p in polys:
                    b = _box_xyxy(p)
                    if b:
                        boxes.append(b)
            if boxes:
                continue
        # classic: [[box, (text, conf)], ...]
        if isinstance(page, (list, tuple)):
            for line in page:
                if line is None:
                    continue
                try:
                    if isinstance(line, (list, tuple)) and line:
                        b = _box_xyxy(line[0])
                        if b:
                            boxes.append(b)
                    else:
                        b = _box_xyxy(line)
                        if b:
                            boxes.append(b)
                except Exception:
                    continue
    return boxes


def _init_paddle_det():
    """Return (engine, mode) where mode in {det_only, full, text_detection}.

    Prefer classic PaddleOCR first — TextDetection/PP-OCRv6 hits OneDNN PIR
    bugs on some DLAMI paddle builds (ConvertPirAttribute2RuntimeAttribute).
    """
    os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")
    # Avoid OneDNN path that breaks TextDetection on some paddle wheels
    os.environ.setdefault("FLAGS_use_mkldnn", "0")
    os.environ.setdefault("FLAGS_onednn", "0")

    from paddleocr import PaddleOCR

    attempts = [
        dict(use_textline_orientation=True, lang="en"),
        dict(lang="en"),
        dict(use_angle_cls=True, lang="en", show_log=False),
        dict(use_angle_cls=True, lang="en"),
        dict(),
    ]
    last = None
    for kwargs in attempts:
        try:
            ocr = PaddleOCR(**kwargs)
            print(f"  paddle: PaddleOCR({kwargs}) OK", flush=True)
            return ocr, "full"
        except (TypeError, ValueError) as e:
            last = e
            continue
        except Exception as e:
            last = e
            print(f"  paddle: PaddleOCR({kwargs}) failed: {e}", flush=True)
            continue

    # paddleocr 3.x TextDetection (may OneDNN-fail at predict time)
    try:
        from paddleocr import TextDetection

        eng = TextDetection()
        print("  paddle: TextDetection() OK (init only)", flush=True)
        return eng, "text_detection"
    except Exception as e:
        print(f"  paddle: TextDetection unavailable: {e}", flush=True)

    raise RuntimeError(f"PaddleOCR init failed: {last}")


def _detect_paddle(eng, mode: str, img_path: Path) -> list[tuple[float, float, float, float]]:
    path = str(img_path)
    result = None
    if mode == "text_detection":
        if hasattr(eng, "predict"):
            result = eng.predict(path)
        elif hasattr(eng, "__call__"):
            result = eng(path)
        else:
            result = eng.detect(path)
        return _extract_boxes_from_ppocr(result)

    # Prefer det-only on classic API
    if hasattr(eng, "ocr"):
        for kwargs in (
            dict(det=True, rec=False, cls=False),
            dict(det=True, rec=False),
            dict(cls=True),
            {},
        ):
            try:
                result = eng.ocr(path, **kwargs) if kwargs else eng.ocr(path)
                boxes = _extract_boxes_from_ppocr(result)
                if boxes or kwargs == {}:
                    return boxes
            except TypeError:
                continue
            except Exception:
                continue
    if hasattr(eng, "predict"):
        try:
            result = eng.predict(path)
            return _extract_boxes_from_ppocr(result)
        except Exception:
            pass
    return []


def _init_surya():
    from surya.detection import DetectionPredictor

    print("  surya: DetectionPredictor() OK", flush=True)
    return DetectionPredictor()


def _detect_surya(pred, img: Image.Image) -> list[tuple[float, float, float, float]]:
    # surya API variants
    try:
        outs = pred([img])
    except TypeError:
        outs = pred(img)
    boxes: list[tuple[float, float, float, float]] = []
    pages = outs if isinstance(outs, list) else [outs]
    for page in pages:
        bboxes = getattr(page, "bboxes", None) or getattr(page, "boxes", None)
        if bboxes is None and isinstance(page, dict):
            bboxes = page.get("bboxes") or page.get("boxes")
        if not bboxes:
            continue
        for bb in bboxes:
            if hasattr(bb, "bbox"):
                b = _box_xyxy(bb.bbox)
            elif isinstance(bb, dict) and "bbox" in bb:
                b = _box_xyxy(bb["bbox"])
            else:
                b = _box_xyxy(bb)
            if b:
                boxes.append(b)
    return boxes


def _area(b: tuple[float, float, float, float]) -> float:
    return max(0.0, b[2] - b[0]) * max(0.0, b[3] - b[1])


def _choose_crop_box(
    boxes: list[tuple[float, float, float, float]],
    w: int,
    h: int,
    margin: float = 0.10,
) -> tuple[int, int, int, int, str]:
    """Union of significant boxes, else top/largest cluster, with margin."""
    if not boxes:
        return 0, 0, w, h, "full_fallback"

    # Filter tiny noise (<0.05% of image)
    img_a = float(w * h) or 1.0
    sig = [b for b in boxes if _area(b) / img_a >= 0.0005]
    if not sig:
        sig = list(boxes)

    areas = [_area(b) for b in sig]
    thr = float(np.percentile(areas, 40)) if len(areas) >= 3 else 0.0
    significant = [b for b, a in zip(sig, areas) if a >= thr] or sig

    # Prefer top half clusters (titles); if empty, use all significant
    top = [b for b in significant if (b[1] + b[3]) / 2.0 <= h * 0.55]
    use = top if top else significant

    x0 = min(b[0] for b in use)
    y0 = min(b[1] for b in use)
    x1 = max(b[2] for b in use)
    y1 = max(b[3] for b in use)

    # If union is tiny vertically, expand with largest box cluster
    if (y1 - y0) < 0.08 * h and significant:
        largest = max(significant, key=_area)
        x0 = min(x0, largest[0])
        y0 = min(y0, largest[1])
        x1 = max(x1, largest[2])
        y1 = max(y1, largest[3])

    bw = max(1.0, x1 - x0)
    bh = max(1.0, y1 - y0)
    mx = bw * margin
    my = bh * margin
    x0 = max(0, int(x0 - mx))
    y0 = max(0, int(y0 - my))
    x1 = min(w, int(x1 + mx))
    y1 = min(h, int(y1 + my))

    # Degenerate → full
    if x1 - x0 < 8 or y1 - y0 < 8:
        return 0, 0, w, h, "full_fallback_degenerate"

    strategy = "union_top" if top else "union_significant"
    # If crop covers almost whole image, still label as crop but note
    cov = ((x1 - x0) * (y1 - y0)) / img_a
    if cov >= 0.92:
        strategy = strategy + "_near_full"
    return x0, y0, x1, y1, strategy


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--ids-file", type=Path, required=True)
    ap.add_argument("--posters-dir", type=Path, required=True)
    ap.add_argument("--out-dir", type=Path, required=True)
    ap.add_argument("--margin", type=float, default=0.10)
    ap.add_argument("--prefer", choices=("paddle", "surya"), default="paddle")
    args = ap.parse_args()

    ids = [int(x) for x in args.ids_file.read_text().split() if x.strip()]
    if not ids:
        print("ERROR: empty ids", flush=True)
        return 1
    if len(ids) > 120:
        print(f"ERROR: refuse n={len(ids)} > 120", flush=True)
        return 1

    crops_dir = args.out_dir / "crops"
    crops_dir.mkdir(parents=True, exist_ok=True)
    bbox_path = args.out_dir / "bboxes.csv"
    meta_path = args.out_dir / "det_meta.json"

    detector = None
    backend = None
    surya_pred = None

    if args.prefer == "paddle":
        try:
            detector, mode = _init_paddle_det()
            backend = f"paddle:{mode}"
        except Exception as e:
            print(f"Paddle det failed, trying Surya: {e}", flush=True)
            traceback.print_exc()
            try:
                surya_pred = _init_surya()
                backend = "surya"
            except Exception as e2:
                print(f"Surya also failed: {e2}", flush=True)
                traceback.print_exc()
                backend = "none"
    else:
        try:
            surya_pred = _init_surya()
            backend = "surya"
        except Exception as e:
            print(f"Surya failed, trying Paddle: {e}", flush=True)
            try:
                detector, mode = _init_paddle_det()
                backend = f"paddle:{mode}"
            except Exception as e2:
                print(f"Paddle also failed: {e2}", flush=True)
                backend = "none"

    rows = []
    n_real = 0
    n_full = 0

    for pid in ids:
        src = args.posters_dir / f"{pid}.jpg"
        dst = crops_dir / f"{pid}.jpg"
        row = {
            "id": pid,
            "backend": backend or "none",
            "n_boxes": 0,
            "x0": 0,
            "y0": 0,
            "x1": 0,
            "y1": 0,
            "img_w": 0,
            "img_h": 0,
            "strategy": "missing",
            "status": "ok",
        }
        try:
            if not src.exists():
                raise FileNotFoundError(str(src))
            im = Image.open(src).convert("RGB")
            w, h = im.size
            row["img_w"], row["img_h"] = w, h

            boxes: list[tuple[float, float, float, float]] = []
            if backend and backend.startswith("paddle") and detector is not None:
                mode = backend.split(":", 1)[1]
                boxes = _detect_paddle(detector, mode, src)
            elif backend == "surya" and surya_pred is not None:
                boxes = _detect_surya(surya_pred, im)

            row["n_boxes"] = len(boxes)
            x0, y0, x1, y1, strategy = _choose_crop_box(boxes, w, h, margin=args.margin)
            row.update({"x0": x0, "y0": y0, "x1": x1, "y1": y1, "strategy": strategy})

            if strategy.startswith("full_fallback") or not boxes:
                shutil.copy2(src, dst)
                n_full += 1
                if not boxes:
                    row["strategy"] = "full_fallback_no_boxes"
            else:
                crop = im.crop((x0, y0, x1, y1))
                crop.save(dst, quality=95)
                n_real += 1
            print(
                f"  id={pid} boxes={row['n_boxes']} strategy={row['strategy']} "
                f"crop=({x0},{y0})-({x1},{y1}) src={w}x{h}",
                flush=True,
            )
        except Exception as e:
            row["status"] = f"error: {e}"[:400]
            row["strategy"] = "full_fallback_error"
            print(f"  id={pid} FAIL {row['status']}", flush=True)
            traceback.print_exc()
            try:
                if src.exists():
                    shutil.copy2(src, dst)
                    n_full += 1
            except Exception:
                pass
        rows.append(row)

    with bbox_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(
            f,
            fieldnames=[
                "id",
                "backend",
                "n_boxes",
                "x0",
                "y0",
                "x1",
                "y1",
                "img_w",
                "img_h",
                "strategy",
                "status",
            ],
        )
        w.writeheader()
        w.writerows(rows)

    meta = {
        "backend": backend,
        "n_ids": len(ids),
        "n_real_crops": n_real,
        "n_full_fallback": n_full,
        "margin": args.margin,
    }
    meta_path.write_text(json.dumps(meta, indent=2) + "\n")
    print(json.dumps(meta), flush=True)
    print(f"wrote {bbox_path} crops→{crops_dir}", flush=True)
    # Non-zero if no real crops — chain should try Surya / another backend
    if n_real == 0:
        print("ERROR: zero real crops (all full fallback)", flush=True)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())

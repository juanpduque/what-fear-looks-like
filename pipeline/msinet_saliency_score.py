#!/usr/bin/env python3
"""MSI-Net visual saliency over movie posters -- where does the eye go first?
alexanderkroner/MSI-Net, a contextual encoder-decoder CNN trained on real human
eye-tracking fixation data (25M params, CPU-friendly). New dimension, not tied
to any single "horror" heuristic -- general-purpose attention prediction.

Per-poster metrics (all from the predicted saliency heatmap, normalized 0-1):
  peak_x, peak_y     - normalized location of the single most salient point
                       (where the eye is predicted to land first)
  top10pct_mass      - fraction of total saliency concentrated in the hottest
                       10% of pixels (higher = focused attention on one spot,
                       e.g. a face or monster; lower = attention spread across
                       a busy/cluttered composition)
  mean_saliency      - average saliency (mostly a sanity/normalization check,
                       should hover near a similar value across posters since
                       the map is a probability-like distribution)

Optional (--save-maps): write grayscale uint8 PNG heatmaps under --maps-dir
(maps/{id}.png), normalize 0-255. Also appends map_w, map_h, map_path columns.

Requires: tensorflow, huggingface_hub, pillow. Uses TFSMLayer (Keras 3) since
the model ships as a legacy TF SavedModel -- see load_midas-style note below.

Usage (local smoke test):
  python3 msinet_saliency_score.py --ids-file data/qa/some_ids.txt --out /tmp/test.csv

With maps:
  python3 msinet_saliency_score.py --ids-file ids.txt --out saliency.csv \\
    --save-maps --maps-dir maps --checkpoint-every 25

EC2 shard (metrics-only, legacy):
  python3 msinet_saliency_score.py --ids-file data/qa/shard.txt --out data/qa/saliency_score.csv
"""
from __future__ import annotations

import argparse
import csv
import time
from pathlib import Path

import numpy as np
import tensorflow as tf
from huggingface_hub import snapshot_download
from PIL import Image

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
POSTERS = DATA / "posters"

METRIC_FIELDS = ["id", "peak_x", "peak_y", "top10pct_mass", "mean_saliency"]
MAP_FIELDS = ["map_w", "map_h", "map_path"]


def load_msinet():
    hf_dir = snapshot_download(repo_id="alexanderkroner/MSI-Net")
    # Keras 3 dropped tf.keras.models.load_model() support for legacy
    # TF SavedModel dirs -- TFSMLayer is the documented replacement.
    layer = tf.keras.layers.TFSMLayer(hf_dir, call_endpoint="serving_default")
    return layer


def predict_saliency(model, img_path: Path) -> np.ndarray:
    img = tf.keras.utils.load_img(str(img_path))
    arr = np.array(img, dtype=np.float32)
    inp = tf.expand_dims(arr, axis=0)
    inp = tf.image.resize(inp, (320, 320), preserve_aspect_ratio=True)
    result = model(inp)
    out = result[list(result.keys())[0]]  # key is "layer_from_saved_model", not "output"
    return out.numpy().squeeze()


def saliency_to_uint8_png(sal: np.ndarray) -> Image.Image:
    """Normalize saliency map to grayscale uint8 PNG (0-255)."""
    sal = np.asarray(sal, dtype=np.float64)
    lo = float(sal.min())
    hi = float(sal.max())
    if hi > lo:
        norm = (sal - lo) / (hi - lo)
    else:
        norm = np.zeros_like(sal, dtype=np.float64)
    u8 = np.clip(np.round(norm * 255.0), 0, 255).astype(np.uint8)
    return Image.fromarray(u8, mode="L")


def load_done_ids(out: Path, maps_dir: Path | None, save_maps: bool) -> set[int]:
    """Resume: ids already in CSV; if --save-maps, also require existing PNG."""
    if not out.exists() or out.stat().st_size == 0:
        return set()
    done: set[int] = set()
    try:
        with out.open(newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                try:
                    pid = int(row["id"])
                except (KeyError, ValueError, TypeError):
                    continue
                if save_maps and maps_dir is not None:
                    png = maps_dir / f"{pid}.png"
                    if not png.is_file() or png.stat().st_size < 10:
                        continue
                done.add(pid)
    except Exception:
        return set()
    return done


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ids-file", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--checkpoint-every", type=int, default=50)
    ap.add_argument("--posters-dir", default=str(POSTERS))
    ap.add_argument(
        "--save-maps",
        action="store_true",
        help="Save grayscale uint8 PNG saliency maps under --maps-dir",
    )
    ap.add_argument(
        "--maps-dir",
        default="",
        help="Directory for maps/{id}.png (default: <out.parent>/maps)",
    )
    args = ap.parse_args()

    posters_dir = Path(args.posters_dir)
    out = Path(args.out)
    maps_dir: Path | None = None
    if args.save_maps:
        maps_dir = Path(args.maps_dir) if args.maps_dir else (out.parent / "maps")
        maps_dir.mkdir(parents=True, exist_ok=True)

    print("loading MSI-Net...", flush=True)
    model = load_msinet()
    print("MSI-Net loaded", flush=True)

    ids = [int(x) for x in Path(args.ids_file).read_text().split() if x.strip()]
    ids = [i for i in ids if (posters_dir / f"{i}.jpg").exists()]
    print(f"todo (with poster): {len(ids):,}", flush=True)

    out.parent.mkdir(parents=True, exist_ok=True)
    done_ids = load_done_ids(out, maps_dir, args.save_maps)
    if done_ids:
        ids = [i for i in ids if i not in done_ids]
        print(f"resume: {len(done_ids):,} already done, {len(ids):,} remaining", flush=True)

    fields = list(METRIC_FIELDS)
    if args.save_maps:
        fields = fields + MAP_FIELDS

    new_file = not out.exists() or out.stat().st_size == 0
    # If resuming an old metrics-only CSV with --save-maps, keep writing compatible rows
    # only when header already has map columns; otherwise write metric+map fields to a
    # fresh file (caller should use a new --out for full map runs).
    if not new_file and args.save_maps:
        with out.open(encoding="utf-8") as fh:
            header = fh.readline().strip().split(",")
        if "map_path" not in header:
            print(
                "WARNING: existing CSV lacks map columns; appending metric+map rows "
                "may confuse parsers. Prefer a fresh --out for --save-maps runs.",
                flush=True,
            )

    f_out = out.open("a", newline="", encoding="utf-8")
    writer = csv.DictWriter(f_out, fieldnames=fields, extrasaction="ignore")
    if new_file:
        writer.writeheader()
        f_out.flush()

    t0 = time.time()
    n_done = 0
    n_err = 0
    for pid in ids:
        try:
            sal = predict_saliency(model, posters_dir / f"{pid}.jpg")
            total = float(sal.sum())
            flat = sal.flatten()
            k = max(1, int(0.10 * flat.size))
            top10_mass = float(np.sort(flat)[-k:].sum() / total) if total > 0 else 0.0
            peak_y, peak_x = np.unravel_index(np.argmax(sal), sal.shape)
            row = {
                "id": pid,
                "peak_x": round(float(peak_x / sal.shape[1]), 4),
                "peak_y": round(float(peak_y / sal.shape[0]), 4),
                "top10pct_mass": round(top10_mass, 4),
                "mean_saliency": round(float(sal.mean()), 4),
            }
            if args.save_maps and maps_dir is not None:
                png_path = maps_dir / f"{pid}.png"
                saliency_to_uint8_png(sal).save(png_path, format="PNG", optimize=True)
                row["map_w"] = int(sal.shape[1])
                row["map_h"] = int(sal.shape[0])
                row["map_path"] = f"maps/{pid}.png"
            writer.writerow(row)
            f_out.flush()
        except Exception as e:
            n_err += 1
            if n_err <= 5:
                print(f"  FAIL {pid}: {e}", flush=True)
            continue
        n_done += 1
        if n_done % args.checkpoint_every == 0 or n_done == len(ids):
            f_out.flush()
            rate = n_done / max(time.time() - t0, 1e-9)
            eta_s = (len(ids) - n_done) / rate if rate > 0 else 0
            print(
                f"  {n_done:,}/{len(ids):,} rate={rate:.2f}/s err={n_err} "
                f"eta_h={eta_s/3600:.2f}",
                flush=True,
            )

    f_out.close()
    print(f"LISTO {len(done_ids) + n_done:,} total, err={n_err}", flush=True)


if __name__ == "__main__":
    main()

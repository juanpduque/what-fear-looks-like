#!/usr/bin/env python3
"""MiDaS monocular depth over movie posters -- how close/'in your face' is the
foreground threat, vs a distant/landscape composition. New dimension, not yet
tried this project; ties directly to visceral immediacy of the poster's fear.

MiDaS depth is RELATIVE and scale-ambiguous per image (no absolute units), so
every metric below is computed after per-image min-max normalization to [0,1]:
  mean_depth       - average closeness across the whole frame
  p95_depth        - closeness of the nearest major foreground mass (robust
                     proxy for "how close is the biggest threat", avoids
                     single-pixel noise that plain max() would pick up)
  depth_std        - compositional depth contrast (flat graphic design poster
                     vs. photographic foreground/background separation)
  close_area_frac  - fraction of pixels above 0.7 normalized closeness
                     ("how much of the frame is close-up foreground")

Usage (local smoke test):
  python3 midas_depth_score.py --ids-file data/qa/some_ids.txt --out /tmp/test.csv

EC2 shard:
  python3 midas_depth_score.py --ids-file data/qa/shard.txt --out data/qa/depth_score.csv
"""

from __future__ import annotations

import argparse
import csv
import time
from pathlib import Path

import numpy as np
import torch
from PIL import Image

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
POSTERS = DATA / "posters"


def load_midas(device):
    import torch.hub as hub

    # MiDaS's hubconf makes nested torch.hub.load() calls (e.g. to
    # rwightman/gen-efficientnet-pytorch) that don't forward trust_repo=True,
    # so those prompt via input() and crash with EOFError on a non-interactive
    # boot. Neutralize the trust check outright rather than chase every nested
    # repo through trust_repo plumbing.
    hub._check_repo_is_trusted = lambda *a, **k: None
    model = hub.load("intel-isl/MiDaS", "MiDaS_small", trust_repo=True)
    model.to(device).eval()
    transforms = hub.load("intel-isl/MiDaS", "transforms", trust_repo=True)
    return model, transforms.small_transform


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ids-file", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--checkpoint-every", type=int, default=50)
    ap.add_argument("--posters-dir", default=str(POSTERS))
    args = ap.parse_args()

    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"device={device}", flush=True)
    model, transform = load_midas(device)
    print("MiDaS_small loaded", flush=True)

    posters_dir = Path(args.posters_dir)
    ids = [int(x) for x in Path(args.ids_file).read_text().split() if x.strip()]
    ids = [i for i in ids if (posters_dir / f"{i}.jpg").exists()]
    print(f"todo: {len(ids):,}", flush=True)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    done_ids: set[int] = set()
    if out.exists() and out.stat().st_size > 0:
        import pandas as pd

        try:
            done_ids = set(pd.read_csv(out)["id"])
        except Exception:
            done_ids = set()
        ids = [i for i in ids if i not in done_ids]
        print(f"resume: {len(done_ids):,} already done, {len(ids):,} remaining", flush=True)

    new_file = not out.exists()
    f_out = out.open("a", newline="", encoding="utf-8")
    fields = ["id", "mean_depth", "p95_depth", "depth_std", "close_area_frac"]
    writer = csv.DictWriter(f_out, fieldnames=fields)
    if new_file:
        writer.writeheader()
        f_out.flush()

    t0 = time.time()
    n_done = 0
    n_err = 0
    for pid in ids:
        try:
            img = Image.open(posters_dir / f"{pid}.jpg").convert("RGB")
            arr = np.array(img)
            inp = transform(arr).to(device)
            with torch.no_grad():
                pred = model(inp)
                pred = torch.nn.functional.interpolate(
                    pred.unsqueeze(1), size=arr.shape[:2], mode="bicubic", align_corners=False
                ).squeeze()
            depth = pred.cpu().numpy()
            dmin, dmax = depth.min(), depth.max()
            if dmax - dmin < 1e-6:
                norm = np.zeros_like(depth)
            else:
                norm = (depth - dmin) / (dmax - dmin)
            row = {
                "id": pid,
                "mean_depth": round(float(norm.mean()), 4),
                "p95_depth": round(float(np.percentile(norm, 95)), 4),
                "depth_std": round(float(norm.std()), 4),
                "close_area_frac": round(float((norm > 0.7).mean()), 4),
            }
            writer.writerow(row)
        except Exception as e:
            n_err += 1
            if n_err <= 5:
                print(f"  FAIL {pid}: {e}", flush=True)
            continue
        n_done += 1
        if n_done % args.checkpoint_every == 0 or n_done == len(ids):
            f_out.flush()
            rate = n_done / max(time.time() - t0, 1e-9)
            print(f"  {n_done:,}/{len(ids):,} rate={rate:.1f}/s err={n_err}", flush=True)

    f_out.close()
    print(f"LISTO {len(done_ids) + n_done:,} total, err={n_err}", flush=True)


if __name__ == "__main__":
    main()

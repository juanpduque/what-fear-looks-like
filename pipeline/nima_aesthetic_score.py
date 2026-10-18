#!/usr/bin/env python3
# ruff: noqa: E402  # thread env vars must be set before importing torch
"""NIMA (Neural Image Assessment, InceptionV2 backbone trained on AVA) aesthetic
score over movie posters, via the pyiqa toolbox.

Second, independent aesthetic model -- cross-checks against the LAION/CLIP-ViT-L14
aesthetic scorer (clip_aesthetic_score.py) to see if "poster quality" trends agree
across two differently-trained models.

  python3 nima_aesthetic_score.py --ids-file data/qa/some_ids.txt --out data/qa/nima_test.csv
"""

from __future__ import annotations

import argparse
import csv
import os
import time
from pathlib import Path

_THREADS = os.environ.get("THREADS", "8")
os.environ.setdefault("OMP_NUM_THREADS", _THREADS)
os.environ.setdefault("MKL_NUM_THREADS", _THREADS)

import pandas as pd
import pyiqa
import torch
from PIL import Image

torch.set_num_threads(int(os.environ.get("TORCH_NUM_THREADS", _THREADS)))

DATA = Path(__file__).resolve().parent / "data"
POSTERS = DATA / "posters"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ids-file", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"device={device}", flush=True)

    metric = pyiqa.create_metric("nima", device=device)
    print("NIMA model loaded", flush=True)

    ids = [int(x) for x in Path(args.ids_file).read_text().split() if x.strip()]
    ids = [i for i in ids if (POSTERS / f"{i}.jpg").exists()]
    print(f"ids with local poster: {len(ids):,}", flush=True)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    done_ids: set[int] = set()
    if out.exists() and out.stat().st_size > 0:
        try:
            done_ids = set(pd.read_csv(out)["id"])
        except Exception:
            done_ids = set()
        ids = [i for i in ids if i not in done_ids]
        print(f"resume: {len(done_ids):,} already done, {len(ids):,} remaining", flush=True)

    new_file = not out.exists()
    f_out = out.open("a", newline="", encoding="utf-8")
    writer = csv.DictWriter(f_out, fieldnames=["id", "nima_score"])
    if new_file:
        writer.writeheader()
        f_out.flush()

    t0 = time.time()
    n_done = 0
    n_err = 0
    for pid in ids:
        try:
            img = Image.open(POSTERS / f"{pid}.jpg").convert("RGB")
            with torch.inference_mode():
                score = float(metric(img).item())
            writer.writerow({"id": pid, "nima_score": round(score, 4)})
        except Exception as e:
            n_err += 1
            if n_err <= 5:
                print(f"err id={pid}: {e}", flush=True)
            continue
        n_done += 1
        if n_done % 50 == 0 or n_done == len(ids):
            f_out.flush()
            rate = n_done / max(time.time() - t0, 1e-9)
            print(f"  {n_done:,}/{len(ids):,} rate={rate:.1f}/s err={n_err}", flush=True)

    f_out.close()
    n_total = len(done_ids) + n_done
    print(
        f"LISTO -> {out} ({n_total:,} total rows, {n_done:,} new this run, err={n_err})", flush=True
    )


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Three more no-reference image-quality metrics over movie posters, via pyiqa --
complements LAION aesthetic + NIMA (both already run this session) with methods
that use genuinely different signal:
  clipiqa  - CLIP-based quality/naturalness score (0-1, higher = better)
  musiq    - multi-scale transformer quality score, trained on KonIQ (general
             photographic quality, not aesthetic-preference like NIMA/AVA)
  brisque  - classic statistical no-reference IQA, no deep learning at all
             (lower = better) -- a genuinely different method as a sanity check
             against the two learned metrics agreeing/disagreeing with each other

Usage (local smoke test):
  python3 pyiqa_multi_score.py --ids-file data/qa/some_ids.txt --out /tmp/test.csv

EC2 shard:
  python3 pyiqa_multi_score.py --ids-file data/qa/shard.txt --out data/qa/iqa_multi.csv
"""

from __future__ import annotations

import argparse
import csv
import time
from pathlib import Path

import pandas as pd
import pyiqa
import torch

# No thread limiting: this session's own aesthetic-scorer benchmarks (LAION/NIMA)
# showed capping threads only helps when several processes share one instance --
# for one process per instance (the deployment here), it's a pure regression
# (measured 10x+ slowdown in that earlier test).

DATA = Path(__file__).resolve().parent / "data"
POSTERS = DATA / "posters"

METRIC_NAMES = ["clipiqa", "musiq", "brisque"]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ids-file", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--checkpoint-every", type=int, default=50)
    ap.add_argument("--posters-dir", default=str(POSTERS))
    args = ap.parse_args()

    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"device={device}", flush=True)
    metrics = {}
    for name in METRIC_NAMES:
        metrics[name] = pyiqa.create_metric(name, device=device)
        print(f"{name} loaded", flush=True)

    posters_dir = Path(args.posters_dir)
    ids = [int(x) for x in Path(args.ids_file).read_text().split() if x.strip()]
    ids = [i for i in ids if (posters_dir / f"{i}.jpg").exists()]
    print(f"todo: {len(ids):,}", flush=True)

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
    fields = ["id", *METRIC_NAMES]
    writer = csv.DictWriter(f_out, fieldnames=fields)
    if new_file:
        writer.writeheader()
        f_out.flush()

    t0 = time.time()
    n_done = 0
    n_err = 0
    for pid in ids:
        row = {"id": pid}
        try:
            p = str(posters_dir / f"{pid}.jpg")
            with torch.inference_mode():
                for name, m in metrics.items():
                    row[name] = round(float(m(p).item()), 4)
            writer.writerow(row)
        except Exception as e:
            n_err += 1
            if n_err <= 5:
                print(f"err id={pid}: {e}", flush=True)
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

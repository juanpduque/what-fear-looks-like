#!/usr/bin/env python3
# ruff: noqa: E402  # thread env vars must be set before importing torch
"""LAION aesthetic predictor (CLIP ViT-L/14 + linear MLP head trained on
human aesthetic ratings, originally used to filter LAION-5B for Stable
Diffusion training) scored over movie posters.

Needs fresh image embeddings (ViT-L/14, 768-dim) -- our cached
clip_embeddings*.npz are ViT-B/32 (512-dim), incompatible with this head.

  python3 clip_aesthetic_score.py --ids-file data/qa/some_ids.txt --out data/qa/aesthetic_test.csv
"""

from __future__ import annotations

import argparse
import os
import time
from pathlib import Path

# dedicated single-process-per-instance: pin threads to the instance's
# physical core count (set THREADS env var to match -- e.g. 8 for
# c7i.4xlarge's 16 vCPU / 8 physical cores via hyperthreading). Set before
# importing torch, and again after (some torch builds re-read env at import
# time, others need the explicit call).
_THREADS = os.environ.get("THREADS", "8")
os.environ.setdefault("OMP_NUM_THREADS", _THREADS)
os.environ.setdefault("MKL_NUM_THREADS", _THREADS)

import open_clip
import pandas as pd
import torch
import torch.nn as nn

torch.set_num_threads(int(os.environ.get("TORCH_NUM_THREADS", _THREADS)))
from huggingface_hub import hf_hub_download
from PIL import Image

DATA = Path(__file__).resolve().parent / "data"
POSTERS = DATA / "posters"


class MLP(nn.Module):
    def __init__(self, input_size):
        super().__init__()
        self.layers = nn.Sequential(
            nn.Linear(input_size, 1024),
            nn.Dropout(0.2),
            nn.Linear(1024, 128),
            nn.Dropout(0.2),
            nn.Linear(128, 64),
            nn.Dropout(0.1),
            nn.Linear(64, 16),
            nn.Linear(16, 1),
        )

    def forward(self, x):
        return self.layers(x)


def load_aesthetic_head(device):
    path = hf_hub_download(
        repo_id="camenduru/improved-aesthetic-predictor",
        filename="sac+logos+ava1-l14-linearMSE.pth",
    )
    m = MLP(768)
    sd = torch.load(path, map_location="cpu", weights_only=True)
    m.load_state_dict(sd)
    return m.to(device).eval()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ids-file", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--batch-size", type=int, default=32)
    args = ap.parse_args()

    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"device={device}", flush=True)

    clip_model, _, preprocess = open_clip.create_model_and_transforms(
        "ViT-L-14", pretrained="openai"
    )
    clip_model = clip_model.to(device).eval()
    head = load_aesthetic_head(device)
    print("models loaded", flush=True)

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
    import csv as _csv

    writer = _csv.DictWriter(f_out, fieldnames=["id", "aesthetic_score"])
    if new_file:
        writer.writeheader()
        f_out.flush()

    rows = []
    t0 = time.time()
    for i in range(0, len(ids), args.batch_size):
        batch_ids = ids[i : i + args.batch_size]
        imgs = []
        ok_ids = []
        for pid in batch_ids:
            try:
                im = Image.open(POSTERS / f"{pid}.jpg").convert("RGB")
                imgs.append(preprocess(im))
                ok_ids.append(pid)
            except Exception:
                continue
        if not imgs:
            continue
        batch = torch.stack(imgs).to(device)
        with torch.inference_mode():
            if device == "cpu":
                with torch.autocast(device_type="cpu", dtype=torch.bfloat16):
                    emb = clip_model.encode_image(batch)
            else:
                emb = clip_model.encode_image(batch)
            emb = emb.float()
            emb = emb / emb.norm(dim=-1, keepdim=True)
            scores = head(emb).squeeze(-1).cpu().numpy()
        for pid, score in zip(ok_ids, scores):
            row = {"id": pid, "aesthetic_score": round(float(score), 4)}
            rows.append(row)
            writer.writerow(row)
        f_out.flush()
        done = i + len(batch_ids)
        if done % (args.batch_size * 10) == 0 or done >= len(ids):
            rate = done / max(time.time() - t0, 1e-9)
            print(f"  {done:,}/{len(ids):,} rate={rate:.1f}/s", flush=True)

    f_out.close()
    n_total = len(done_ids) + len(rows)
    mean_new = (sum(r["aesthetic_score"] for r in rows) / len(rows)) if rows else float("nan")
    print(
        f"LISTO -> {out} ({n_total:,} total rows, {len(rows):,} new this run) mean_new={mean_new:.3f}",
        flush=True,
    )


if __name__ == "__main__":
    main()

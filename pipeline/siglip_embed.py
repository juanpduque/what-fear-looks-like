#!/usr/bin/env python3
"""One-time SigLIP image embeddings for all posters -- upgrade over CLIP ViT-B-32
(clip_embed.py). SigLIP's sigmoid loss gives measurably better zero-shot accuracy
than plain CLIP (Google's own benchmarks: ~85% ImageNet zero-shot for SigLIP2 vs
~68-75% typical for CLIP ViT-B-32), which should make the zero-shot analyses
built on top (fear_axis, census, typography, genre_classifier) sharper.

Same resumable batching pattern as clip_embed.py. NOT interchangeable with the
existing clip_embeddings*.npz -- different embedding space/dimensionality,
downstream scripts need their own SigLIP prototypes re-derived from this.

  python3 siglip_embed.py --ids-file data/qa/shard.txt --out data/qa/siglip_shard.npz

Output: ids + L2-normalized vectors (768-d for siglip-base-patch16-224).
"""

from __future__ import annotations

import argparse
import time
from pathlib import Path

import numpy as np
import torch
from PIL import Image
from transformers import AutoModel, AutoProcessor

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
POSTERS = DATA / "posters"
MODEL_ID = "google/siglip-base-patch16-224"
BATCH = 32


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ids-file", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--posters-dir", default=str(POSTERS))
    args = ap.parse_args()

    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"device={device}", flush=True)
    processor = AutoProcessor.from_pretrained(MODEL_ID)
    model = AutoModel.from_pretrained(MODEL_ID).to(device).eval()
    print(f"{MODEL_ID} loaded", flush=True)

    posters_dir = Path(args.posters_dir)
    ids = [int(x) for x in Path(args.ids_file).read_text().split() if x.strip()]
    ids = [i for i in ids if (posters_dir / f"{i}.jpg").exists()]
    print(f"todo: {len(ids):,}", flush=True)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    partial = out.parent / (out.stem + "_partial.npz")
    ids_done: list[int] = []
    vecs: list[np.ndarray] = []
    src = partial if partial.exists() else (out if out.exists() else None)
    if src is not None:
        z = np.load(src)
        ids_done, vecs = list(z["ids"]), list(z["vecs"])
        print(f"resume: {len(ids_done):,} already embedded (from {src.name})", flush=True)
    done = set(int(x) for x in ids_done)
    todo = [i for i in ids if i not in done]
    print(f"pending: {len(todo):,}", flush=True)

    t0 = time.time()
    n0 = len(ids_done)
    imgs, batch_ids = [], []

    def flush():
        nonlocal imgs, batch_ids
        if not imgs:
            return
        inputs = processor(images=imgs, return_tensors="pt").to(device)
        with torch.inference_mode():
            out = model.get_image_features(**inputs)
            feats = out.pooler_output if hasattr(out, "pooler_output") else out
            feats = feats / feats.norm(dim=-1, keepdim=True)
        vecs.extend(feats.cpu().numpy().astype(np.float16))
        ids_done.extend(batch_ids)
        imgs, batch_ids = [], []

    for pid in todo:
        p = posters_dir / f"{pid}.jpg"
        try:
            imgs.append(Image.open(p).convert("RGB"))
            batch_ids.append(pid)
        except Exception:
            continue
        if len(imgs) >= BATCH:
            flush()
            if (len(ids_done) - n0) % (BATCH * 8) < BATCH:
                rate = (len(ids_done) - n0) / max(time.time() - t0, 1e-9)
                print(f"  {len(ids_done):,}/{len(ids):,} rate={rate:.1f}/s", flush=True)
                np.savez_compressed(partial, ids=np.array(ids_done), vecs=np.array(vecs))
    flush()

    np.savez_compressed(out, ids=np.array(ids_done), vecs=np.array(vecs))
    partial.unlink(missing_ok=True)
    print(f"LISTO: {len(ids_done):,} embeddings -> {out}", flush=True)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
One-time CLIP image embeddings for all posters.
Embed once -> every future semantic question (monsters, animals, painted-vs-photo,
similarity search) runs in seconds against the cache, no image reprocessing.

Setup + run (your machine; ~600MB model download on first run):
  pip3 install torch open_clip_torch pillow pandas numpy
  python3 clip_embed.py            # full run, resumable (~20-40 min CPU)

Output: data/clip_embeddings.npz  (ids + L2-normalized 512-d vectors, ~57MB)
"""
import time
from pathlib import Path
import numpy as np
import pandas as pd
import torch
from PIL import Image
import open_clip


def load_clip(device):
    """HF con fallback a checkpoint local: export CLIP_CKPT=/ruta/ViT-B-32.pt"""
    import os
    ckpt = os.environ.get("CLIP_CKPT")
    if ckpt:
        model = open_clip.load_openai_model(ckpt, device=device)
        pre = open_clip.image_transform(224, is_train=False)
        return model.eval(), pre
    m, _, pre = open_clip.create_model_and_transforms("ViT-B-32", pretrained="openai")
    return m.to(device).eval(), pre

DATA = Path(__file__).parent / "data"
OUT = DATA / "clip_embeddings.npz"
PARTIAL = DATA / "clip_embeddings_partial.npz"
BATCH = 64

def main():
    device = "cuda" if torch.cuda.is_available() else "cpu"
    print("device:", device)
    model, preprocess = load_clip(device)

    meta = pd.read_csv(DATA / "posters.csv", usecols=["id", "year"])
    ids_done, vecs = [], []
    if PARTIAL.exists():
        z = np.load(PARTIAL)
        ids_done, vecs = list(z["ids"]), list(z["vecs"])
        print(f"resumiendo: {len(ids_done):,} ya embebidos")
    done = set(ids_done)
    todo = meta[~meta.id.isin(done)]

    t0, imgs, batch_ids, n0 = time.time(), [], [], len(ids_done)
    def flush():
        nonlocal imgs, batch_ids
        if not imgs: return
        with torch.no_grad():
            f = model.encode_image(torch.stack(imgs).to(device))
            f = f / f.norm(dim=-1, keepdim=True)
        vecs.extend(f.cpu().numpy().astype(np.float16))
        ids_done.extend(batch_ids)
        imgs, batch_ids = [], []

    for i, r in enumerate(todo.itertuples()):
        f = DATA / "posters" / f"{r.id}.jpg"
        if not f.exists(): continue
        try:
            imgs.append(preprocess(Image.open(f).convert("RGB")))
            batch_ids.append(r.id)
        except Exception:
            continue
        if len(imgs) >= BATCH:
            flush()
            if len(ids_done) % 1280 < BATCH:
                rate = (len(ids_done) - n0) / (time.time() - t0)
                print(f"  {len(ids_done):,}/{len(meta):,} ({rate:.0f}/s)", flush=True)
                np.savez_compressed(PARTIAL, ids=np.array(ids_done),
                                    vecs=np.array(vecs))
    flush()
    np.savez_compressed(OUT, ids=np.array(ids_done), vecs=np.array(vecs))
    PARTIAL.unlink(missing_ok=True)
    print(f"LISTO: {len(ids_done):,} embeddings -> {OUT}")

if __name__ == "__main__":
    main()

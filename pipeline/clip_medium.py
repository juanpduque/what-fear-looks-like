#!/usr/bin/env python3
"""
Painted vs. photographic poster classification via CLIP zero-shot.
Dates the death of the illustrated horror poster.

Run on your machine (downloads ~600MB model on first run):
  pip3 install torch open_clip_torch pillow pandas
  python3 clip_medium.py            # full 28k run (~15-25 min on CPU)
  python3 clip_medium.py --n 500    # quick validation sample

Outputs: data/medium.csv (per-poster), data/medium_yearly.json,
and the 50% crossover year printed to console.
"""
import argparse, json
from pathlib import Path
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

# prompt ensembles — averaged for robustness
PAINTED = [
    "a hand-painted illustrated movie poster, drawn artwork",
    "a vintage movie poster with painted illustration art",
    "an illustrated poster, painting, brush strokes, drawn characters",
]
PHOTO = [
    "a movie poster made from a photograph of real actors",
    "a photographic movie poster, photo of a person or scene",
    "a poster with photographic imagery, camera photograph",
]

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=0, help="sample size (0 = all)")
    ap.add_argument("--batch", type=int, default=64)
    args = ap.parse_args()

    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"device: {device}")
    model, preprocess = load_clip(device)
    tok = open_clip.get_tokenizer("ViT-B-32")

    with torch.no_grad():
        t = tok(PAINTED + PHOTO).to(device)
        tf = model.encode_text(t)
        tf = tf / tf.norm(dim=-1, keepdim=True)
        t_painted = tf[:len(PAINTED)].mean(0)
        t_photo = tf[len(PAINTED):].mean(0)
        t_painted /= t_painted.norm(); t_photo /= t_photo.norm()

    meta = pd.read_csv(DATA / "posters.csv", usecols=["id", "year", "title"])
    if args.n:
        meta = meta.groupby(meta.year // 10 * 10, group_keys=False).apply(
            lambda g: g.sample(min(len(g), args.n // 8), random_state=42))
    rows, batch_imgs, batch_meta = [], [], []

    def flush():
        if not batch_imgs: return
        with torch.no_grad():
            im = torch.stack(batch_imgs).to(device)
            f = model.encode_image(im)
            f = f / f.norm(dim=-1, keepdim=True)
            # softmax over the two class prototypes
            logits = torch.stack([f @ t_painted, f @ t_photo], dim=1) * 100
            p = logits.softmax(dim=1)[:, 0].cpu().numpy()
        for (pid, yr, title), pp in zip(batch_meta, p):
            rows.append(dict(id=pid, year=int(yr), title=title,
                             p_painted=round(float(pp), 4)))
        batch_imgs.clear(); batch_meta.clear()

    for i, r in enumerate(meta.itertuples()):
        f = DATA / "posters" / f"{r.id}.jpg"
        if not f.exists(): continue
        try:
            batch_imgs.append(preprocess(Image.open(f).convert("RGB")))
            batch_meta.append((r.id, r.year, r.title))
        except Exception:
            continue
        if len(batch_imgs) >= args.batch:
            flush()
            if len(rows) % 1280 < args.batch:
                print(f"  {len(rows)}/{len(meta)}")
    flush()

    d = pd.DataFrame(rows)
    d["painted"] = (d.p_painted > 0.5).astype(int)
    d.to_csv(DATA / "medium.csv", index=False)

    yearly = d.groupby("year").agg(n=("id", "count"),
                                   pct_painted=("painted", "mean")).round(4)
    yearly.reset_index().to_json(DATA / "medium_yearly.json", orient="records")

    roll = yearly.pct_painted.rolling(5, min_periods=3, center=True).mean()
    print("\n% ilustrado por lustro (5yr rolling):")
    print((roll[roll.index % 5 == 0] * 100).round(1).to_string())
    below = roll[roll < 0.5]
    print(f"\nCRUCE 50% (muerte del póster pintado): {below.index.min() if len(below) else 'no cruza'}")

    # sanity checks — deben salir pintados: Creepshow, The Evil Dead;
    # fotográficos: Scream, Hereditary
    for t in ["Creepshow", "The Evil Dead", "Scream", "Hereditary"]:
        m = d[d.title == t]
        if len(m):
            r0 = m.sort_values("year").iloc[0]
            print(f"check {t} ({int(r0.year)}): p_painted={r0.p_painted:.2f}")

if __name__ == "__main__":
    main()

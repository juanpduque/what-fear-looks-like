#!/usr/bin/env python3
"""Zero-shot CLIP expression classifier over Rekognition face crops (faces_v2*.csv).

For every detected face box, crops the region (with padding), encodes it with
CLIP ViT-B/32 (fresh embeddings -- faces_v2 boxes were never embedded, only
full-poster clip_embeddings*.npz exists), and classifies against fear-oriented
expression prototypes. Same prompt-ensemble + cosine-softmax method as
clip_census.py / clip_typography_axis.py, applied to face crops instead of
whole posters.

Input: data/faces_v2.csv (+ _scifi/_thriller/_mystery), column face_boxes is
"x,y,w,h|x,y,w,h|..." normalized to poster width/height.

Usage (local smoke test):
  python3 clip_face_expression.py --ids-file data/qa/some_ids.txt --out /tmp/test.csv

EC2 shard:
  python3 clip_face_expression.py --ids-file data/qa/shard.txt \\
    --out data/qa/face_expression.csv
"""

from __future__ import annotations

import argparse
import csv
import time
from pathlib import Path

import numpy as np
import pandas as pd
import torch
from PIL import Image

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
POSTERS = DATA / "posters"

PROTOTYPES = {
    "terrified": [
        "a close-up of a terrified human face, eyes wide with fear",
        "a person's face frozen in fear and dread",
    ],
    "screaming": [
        "a person screaming in horror, mouth wide open",
        "a human face mid-scream, terror",
    ],
    "shocked": [
        "a shocked, startled human face, wide eyes, surprise",
        "a face reacting in sudden shock",
    ],
    "menacing": [
        "a menacing, evil human face, threatening stare",
        "a villain's face with a sinister, predatory expression",
    ],
    "angry": ["an angry, enraged human face, gritted teeth"],
    "sad": ["a sad, sorrowful, or crying human face"],
    "in_pain": ["a human face in physical pain or agony"],
    "calm": [
        "a calm, neutral human face, no strong emotion",
        "an ordinary relaxed human face, plain expression",
    ],
}


def load_clip(device):
    import os

    import open_clip

    ckpt = os.environ.get("CLIP_CKPT")
    if ckpt:
        model = open_clip.load_openai_model(ckpt, device=device)
        pre = open_clip.image_transform(224, is_train=False)
        return model.eval(), pre
    m, _, pre = open_clip.create_model_and_transforms("ViT-B-32", pretrained="openai")
    return m.to(device).eval(), pre


def build_prototypes(model, device):
    import open_clip

    tok = open_clip.get_tokenizer("ViT-B-32")
    protos = {}
    with torch.no_grad():
        for label, prompts in PROTOTYPES.items():
            t = model.encode_text(tok(prompts).to(device))
            t = t / t.norm(dim=-1, keepdim=True)
            p = t.mean(0)
            protos[label] = (p / p.norm()).cpu().numpy()
    return protos


def load_faces() -> dict[int, list[tuple[float, float, float, float]]]:
    """Union of data/faces_v2.csv + _scifi/_thriller/_mystery (non-partial files),
    id -> list of (x,y,w,h) normalized boxes."""
    out: dict[int, list[tuple[float, float, float, float]]] = {}
    files = [
        DATA / "faces_v2.csv",
        DATA / "faces_v2_scifi.csv",
        DATA / "faces_v2_thriller.csv",
        DATA / "faces_v2_mystery.csv",
    ]
    for f in files:
        if not f.exists():
            continue
        df = pd.read_csv(f, usecols=["id", "n_faces", "face_boxes"])
        for _, r in df.iterrows():
            if int(r["n_faces"]) <= 0 or not isinstance(r["face_boxes"], str):
                continue
            pid = int(r["id"])
            if pid in out:
                continue
            boxes = []
            for chunk in r["face_boxes"].split("|"):
                parts = chunk.split(",")
                if len(parts) != 4:
                    continue
                boxes.append(tuple(float(p) for p in parts))
            if boxes:
                out[pid] = boxes
    return out


def crop_face(
    img: Image.Image, box: tuple[float, float, float, float], pad: float = 0.25
) -> Image.Image:
    W, H = img.size
    x, y, w, h = box
    px, py = w * pad, h * pad
    x0 = max(0.0, x - px) * W
    y0 = max(0.0, y - py) * H
    x1 = min(1.0, x + w + px) * W
    y1 = min(1.0, y + h + py) * H
    if x1 <= x0 or y1 <= y0:
        return img
    return img.crop((x0, y0, x1, y1))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ids-file", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--min-score", type=float, default=0.35)
    ap.add_argument("--temp", type=float, default=100.0)
    ap.add_argument("--checkpoint-every", type=int, default=100)
    ap.add_argument("--posters-dir", default=str(POSTERS))
    args = ap.parse_args()

    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"device={device}", flush=True)
    model, preprocess = load_clip(device)
    print("CLIP ViT-B-32 loaded", flush=True)
    protos = build_prototypes(model, device)
    labels = list(protos)
    P = np.stack([protos[l] for l in labels])  # L x 512

    faces = load_faces()
    print(f"posters with faces (union of 4 genres): {len(faces):,}", flush=True)

    posters_dir = Path(args.posters_dir)
    want_ids = [int(x) for x in Path(args.ids_file).read_text().split() if x.strip()]
    want_ids = [i for i in want_ids if i in faces and (posters_dir / f"{i}.jpg").exists()]
    print(f"todo: {len(want_ids):,} posters", flush=True)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    done_ids: set[int] = set()
    if out.exists() and out.stat().st_size > 0:
        try:
            done_ids = set(pd.read_csv(out)["id"])
        except Exception:
            done_ids = set()
        want_ids = [i for i in want_ids if i not in done_ids]
        print(
            f"resume: {len(done_ids):,} posters already done, {len(want_ids):,} remaining",
            flush=True,
        )

    new_file = not out.exists()
    f_out = out.open("a", newline="", encoding="utf-8")
    writer = csv.DictWriter(f_out, fieldnames=["id", "face_idx", "box", "label", "score"])
    if new_file:
        writer.writeheader()
        f_out.flush()

    t0 = time.time()
    n_done_posters = 0
    n_faces_done = 0
    n_err = 0
    for pid in want_ids:
        try:
            img = Image.open(posters_dir / f"{pid}.jpg").convert("RGB")
            boxes = faces[pid]
            crops = [preprocess(crop_face(img, b)) for b in boxes]
            batch = torch.stack(crops).to(device)
            with torch.no_grad():
                emb = model.encode_image(batch)
                emb = emb / emb.norm(dim=-1, keepdim=True)
            sims = emb.cpu().numpy() @ P.T
            probs = torch.softmax(torch.tensor(sims * args.temp), dim=1).numpy()
            top = probs.argmax(1)
            for face_idx, (b, ti, sc) in enumerate(zip(boxes, top, probs.max(1))):
                label = labels[ti] if sc >= args.min_score else "uncertain"
                writer.writerow(
                    {
                        "id": pid,
                        "face_idx": face_idx,
                        "box": ",".join(f"{v:.4f}" for v in b),
                        "label": label,
                        "score": round(float(sc), 3),
                    }
                )
                n_faces_done += 1
        except Exception as e:
            n_err += 1
            if n_err <= 5:
                print(f"  FAIL {pid}: {e}", flush=True)
            continue
        n_done_posters += 1
        if n_done_posters % args.checkpoint_every == 0 or n_done_posters == len(want_ids):
            f_out.flush()
            rate = n_done_posters / max(time.time() - t0, 1e-9)
            print(
                f"  {n_done_posters:,}/{len(want_ids):,} posters "
                f"({n_faces_done:,} faces) rate={rate:.1f} posters/s err={n_err}",
                flush=True,
            )

    f_out.close()
    print(
        f"LISTO posters={len(done_ids) + n_done_posters:,} faces={n_faces_done:,} err={n_err}",
        flush=True,
    )


if __name__ == "__main__":
    main()

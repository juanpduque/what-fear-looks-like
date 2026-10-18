#!/usr/bin/env python3
"""CLIP zero-shot genre classifier: does this poster "look like" its genre?

Reuses existing clip_embeddings*.npz (no re-embedding of images -- runs in
seconds). Encodes a handful of text prototypes per genre, cosine-similarity
against each poster's cached image embedding, and compares the predicted
genre against the poster's actual TMDB genre.

  python3 clip_genre_classifier.py
  python3 clip_genre_classifier.py --out data/qa/genre_classifier.csv
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import open_clip
import pandas as pd
import torch

DATA = Path(__file__).resolve().parent / "data"

GENRE_PROMPTS = {
    "horror": [
        "a horror movie poster, scary and menacing imagery",
        "a horror film poster with blood, monsters, or a masked killer",
        "a dark scary movie poster meant to frighten",
    ],
    "scifi": [
        "a science fiction movie poster with futuristic technology or space",
        "a sci-fi film poster featuring spaceships, aliens, or robots",
        "a science fiction poster with a futuristic or otherworldly setting",
    ],
    "thriller": [
        "a thriller movie poster, tense and suspenseful imagery",
        "a crime thriller poster with a gun, chase, or shadowy figure",
        "a suspense thriller film poster, dramatic and tense",
    ],
    "mystery": [
        "a mystery movie poster with a detective or an unsolved puzzle",
        "a mystery film poster, intriguing and enigmatic imagery",
        "a whodunit mystery poster with clues or investigation themes",
    ],
}

GENRE_FILES = {
    "horror": ("data/clip_embeddings.npz", "data/posters.csv"),
    "scifi": ("data/clip_embeddings_scifi.npz", "data/posters_scifi.csv"),
    "thriller": ("data/clip_embeddings_thriller.npz", "data/posters_thriller.csv"),
    "mystery": ("data/clip_embeddings_mystery.npz", "data/posters_mystery.csv"),
}


def load_clip(device):
    m, _, _ = open_clip.create_model_and_transforms("ViT-B-32", pretrained="openai")
    return m.to(device).eval()


def proto(model, tok, prompts, device):
    with torch.no_grad():
        t = model.encode_text(tok(prompts).to(device))
        t = t / t.norm(dim=-1, keepdim=True)
        p = t.mean(0)
        return (p / p.norm()).cpu().numpy()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(DATA / "qa" / "genre_classifier.csv"))
    args = ap.parse_args()

    device = "cuda" if torch.cuda.is_available() else "cpu"
    model = load_clip(device)
    tok = open_clip.get_tokenizer("ViT-B-32")

    protos = {g: proto(model, tok, prompts, device) for g, prompts in GENRE_PROMPTS.items()}
    genres = list(protos)
    proto_mat = np.stack([protos[g] for g in genres])  # (4, 512)

    rows = []
    for true_genre, (emb_path, meta_path) in GENRE_FILES.items():
        emb_path, meta_path = Path(emb_path), Path(meta_path)
        if not emb_path.exists():
            print(f"skip {true_genre}: missing {emb_path}")
            continue
        d = np.load(emb_path)
        ids, vecs = d["ids"], d["vecs"]
        vecs = vecs / np.linalg.norm(vecs, axis=1, keepdims=True)
        sims = vecs @ proto_mat.T  # (n, 4)
        pred_idx = sims.argmax(1)
        pred_genre = [genres[i] for i in pred_idx]
        for pid, pg, sim_row in zip(ids, pred_genre, sims):
            rows.append(
                {
                    "id": int(pid),
                    "true_genre": true_genre,
                    "pred_genre": pg,
                    "agree": pg == true_genre,
                    "sim_horror": round(float(sim_row[genres.index("horror")]), 4),
                    "sim_scifi": round(float(sim_row[genres.index("scifi")]), 4),
                    "sim_thriller": round(float(sim_row[genres.index("thriller")]), 4),
                    "sim_mystery": round(float(sim_row[genres.index("mystery")]), 4),
                }
            )
        n = len(ids)
        agree = sum(1 for r in rows[-n:] if r["agree"])
        print(
            f"{true_genre}: {n:,} posters, CLIP predicted same genre for {agree:,} ({agree / n:.1%})"
        )

    df = pd.DataFrame(rows)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out, index=False)
    print("\n=== confusion matrix (rows=true, cols=pred) ===")
    print(pd.crosstab(df["true_genre"], df["pred_genre"]))
    print(f"\nLISTO -> {out} ({len(df):,} rows)")


if __name__ == "__main__":
    main()

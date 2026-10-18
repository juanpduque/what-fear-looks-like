#!/usr/bin/env python3
"""Census + typography + genre_classifier, version SigLIP -- same prototype
prompts as the CLIP originals (clip_census.py, clip_typography_axis.py,
clip_genre_classifier.py), re-run on data/siglip_embeddings.npz. Model loaded
once and reused across all three (avoids 3x the ~3min SigLIP load cost).

  python3 siglip_reanalysis.py
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import torch
from transformers import AutoModel, AutoProcessor

DATA = Path(__file__).parent / "data"
MODEL_ID = "google/siglip-base-patch16-224"

CENSUS_TAXONOMY = {
    "vampire": [
        "a horror movie poster featuring a vampire with fangs",
        "a dracula movie poster, vampire, cape, fangs",
    ],
    "werewolf": ["a horror poster featuring a werewolf", "a wolf-man creature on a movie poster"],
    "zombie": [
        "a horror poster featuring zombies, undead corpses",
        "rotting undead zombie faces on a movie poster",
    ],
    "ghost": [
        "a horror poster featuring a ghost or spectral figure",
        "a pale spectral apparition on a movie poster",
    ],
    "demon": [
        "a horror poster featuring a demon or the devil",
        "a demonic possessed figure on a movie poster",
    ],
    "witch": ["a horror poster featuring a witch", "occult witchcraft imagery on a movie poster"],
    "skeleton": [
        "a horror poster featuring a skull or skeleton",
        "a large skull on a movie poster",
    ],
    "alien": [
        "a horror poster featuring an alien creature",
        "an extraterrestrial monster on a movie poster",
    ],
    "giant_monster": [
        "a poster featuring a giant monster attacking, kaiju",
        "a giant creature destroying a city on a movie poster",
    ],
    "masked_killer": [
        "a horror poster featuring a masked killer with a weapon",
        "a slasher villain in a mask on a movie poster",
    ],
    "clown": ["a horror poster featuring an evil clown"],
    "doll": ["a horror poster featuring a creepy doll or puppet"],
    "shark": ["a poster featuring a shark attacking"],
    "spider": ["a poster featuring a giant spider"],
    "snake": ["a poster featuring a snake or serpent attacking"],
    "wolf_dog": ["a poster featuring a menacing dog or wolf (real animal)"],
    "bird": ["a poster featuring attacking birds"],
    "insect": ["a poster featuring insects or bugs swarming"],
    "none": [
        "a movie poster with only ordinary people, no monster or creature",
        "a movie poster showing a house or landscape, no creature",
        "a movie poster with plain typography, no monster",
    ],
}

ORNATE_PROMPTS = [
    "a movie poster with ornate decorative hand-drawn display title lettering",
    "a poster title in elaborate vintage painted show-card letters",
    "a movie title in fancy ornamental custom 3D lettering",
    "a poster with a heavily stylized illustrated logo title",
]
CLEAN_PROMPTS = [
    "a movie poster title in clean minimal sans-serif type",
    "a poster title in plain simple modern typography",
    "a movie title in a restrained understated typeface",
    "a poster with small tidy unadorned lettering",
]
REGISTERS = ["ornate", "decorative", "standard", "clean", "minimal"]

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


def text_proto(model, processor, prompts):
    inputs = processor(text=prompts, padding="max_length", return_tensors="pt")
    with torch.inference_mode():
        out = model.get_text_features(**inputs)
        feats = out.pooler_output if hasattr(out, "pooler_output") else out
        feats = feats / feats.norm(dim=-1, keepdim=True)
    p = feats.mean(0)
    return (p / p.norm()).numpy()


def load_meta() -> pd.DataFrame:
    frames = []
    for f, g in [
        ("posters.csv", "horror"),
        ("posters_scifi.csv", "scifi"),
        ("posters_thriller.csv", "thriller"),
        ("posters_mystery.csv", "mystery"),
    ]:
        m = pd.read_csv(DATA / f, usecols=["id", "year", "title"])
        m["genre"] = g
        frames.append(m)
    meta = pd.concat(frames, ignore_index=True)
    return meta.drop_duplicates(subset=["id"])


def run_census(model, processor, ids, vecs, meta):
    protos = {
        label: text_proto(model, processor, prompts) for label, prompts in CENSUS_TAXONOMY.items()
    }
    labels = list(protos)
    P = np.stack([protos[l] for l in labels])
    sims = vecs @ P.T
    probs = torch.softmax(torch.tensor(sims * 100.0), dim=1).numpy()
    top = probs.argmax(1)
    df = pd.DataFrame(dict(id=ids, label=[labels[i] for i in top], score=probs.max(1).round(3)))
    df.loc[df.score < 0.5, "label"] = "uncertain"
    df = df.merge(meta[["id", "year", "title"]], on="id")
    df.to_csv(DATA / "siglip_census.csv", index=False)
    print(f"census -> {DATA / 'siglip_census.csv'} ({len(df):,} rows)")
    print(df["label"].value_counts().head(10))


def run_typography(model, processor, ids, vecs, meta):
    ORNATE = text_proto(model, processor, ORNATE_PROMPTS)
    CLEAN = text_proto(model, processor, CLEAN_PROMPTS)
    axis = (vecs @ ORNATE) - (vecs @ CLEAN)
    df = pd.DataFrame(dict(id=ids, axis=axis))
    df = df.merge(meta[["id", "year", "title"]], on="id")
    edges = np.quantile(df["axis"], np.linspace(0, 1, 6))
    edges[0], edges[-1] = -np.inf, np.inf
    b = np.digitize(df["axis"], edges[1:-1])
    df["register"] = [REGISTERS[::-1][k] for k in b]
    df.to_csv(DATA / "siglip_typography.csv", index=False)
    print(f"typography -> {DATA / 'siglip_typography.csv'} ({len(df):,} rows)")
    print(df["register"].value_counts())


def run_genre(model, processor, ids, vecs, meta):
    protos = {g: text_proto(model, processor, prompts) for g, prompts in GENRE_PROMPTS.items()}
    genres = list(protos)
    P = np.stack([protos[g] for g in genres])
    sims = vecs @ P.T
    pred_idx = sims.argmax(1)
    pred_genre = [genres[i] for i in pred_idx]
    df = pd.DataFrame({"id": ids, "pred_genre": pred_genre})
    df = df.merge(meta[["id", "genre"]].rename(columns={"genre": "true_genre"}), on="id")
    df["agree"] = df["pred_genre"] == df["true_genre"]
    df.to_csv(DATA / "siglip_genre_classifier.csv", index=False)
    print(f"genre -> {DATA / 'siglip_genre_classifier.csv'} ({len(df):,} rows)")
    print(df.groupby("true_genre")["agree"].mean().round(3))
    print(pd.crosstab(df["true_genre"], df["pred_genre"]))


def main():
    print("loading SigLIP...", flush=True)
    model = AutoModel.from_pretrained(MODEL_ID).eval()
    processor = AutoProcessor.from_pretrained(MODEL_ID)
    print("model ready", flush=True)

    z = np.load(DATA / "siglip_embeddings.npz")
    ids = z["ids"].astype(int)
    vecs = z["vecs"].astype(np.float32)
    meta = load_meta()

    print("\n=== CENSUS ===", flush=True)
    run_census(model, processor, ids, vecs, meta)
    print("\n=== TYPOGRAPHY ===", flush=True)
    run_typography(model, processor, ids, vecs, meta)
    print("\n=== GENRE ===", flush=True)
    run_genre(model, processor, ids, vecs, meta)


if __name__ == "__main__":
    main()

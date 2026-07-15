#!/usr/bin/env python3
"""
THE MONSTER CENSUS — creature/animal taxonomy over CLIP embeddings.
What is each decade afraid of? Runs in seconds against data/clip_embeddings.npz
(build that first with clip_embed.py).

  python3 clip_census.py --validate    # sanity-check on famous posters first
  python3 clip_census.py               # full census

Outputs: data/census.csv (per-poster top label + score),
         data/census_decade.json (label share per decade)
Method: prompt-ensemble text prototypes per label; a poster gets a label if its
cosine-similarity softmax for that label beats the 'no creature' baseline.
Per-poster labels are noisy; decade-level shares are the deliverable.
"""
import argparse
from pathlib import Path
import numpy as np
import pandas as pd
import torch
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

TAXONOMY = {
  "vampire":      ["a horror movie poster featuring a vampire with fangs",
                   "a dracula movie poster, vampire, cape, fangs"],
  "werewolf":     ["a horror poster featuring a werewolf",
                   "a wolf-man creature on a movie poster"],
  "zombie":       ["a horror poster featuring zombies, undead corpses",
                   "rotting undead zombie faces on a movie poster"],
  "ghost":        ["a horror poster featuring a ghost or spectral figure",
                   "a pale spectral apparition on a movie poster"],
  "demon":        ["a horror poster featuring a demon or the devil",
                   "a demonic possessed figure on a movie poster"],
  "witch":        ["a horror poster featuring a witch",
                   "occult witchcraft imagery on a movie poster"],
  "skeleton":     ["a horror poster featuring a skull or skeleton",
                   "a large skull on a movie poster"],
  "alien":        ["a horror poster featuring an alien creature",
                   "an extraterrestrial monster on a movie poster"],
  "giant_monster":["a poster featuring a giant monster attacking, kaiju",
                   "a giant creature destroying a city on a movie poster"],
  "masked_killer":["a horror poster featuring a masked killer with a weapon",
                   "a slasher villain in a mask on a movie poster"],
  "clown":        ["a horror poster featuring an evil clown"],
  "doll":         ["a horror poster featuring a creepy doll or puppet"],
  "shark":        ["a poster featuring a shark attacking"],
  "spider":       ["a poster featuring a giant spider"],
  "snake":        ["a poster featuring a snake or serpent attacking"],
  "wolf_dog":     ["a poster featuring a menacing dog or wolf (real animal)"],
  "bird":         ["a poster featuring attacking birds"],
  "insect":       ["a poster featuring insects or bugs swarming"],
  "none":         ["a movie poster with only ordinary people, no monster or creature",
                   "a movie poster showing a house or landscape, no creature",
                   "a movie poster with plain typography, no monster"],
}
ANIMALS = {"shark", "spider", "snake", "wolf_dog", "bird", "insect"}

VALIDATION = [  # (title, year, acceptable labels — ground truth verificada MIRANDO el artwork)
    ("Godzilla", 1954, {"giant_monster"}),
    ("Jaws", 1975, {"shark"}),
    ("An American Werewolf in London", 1981, {"werewolf"}),
    ("Night of the Living Dead", 1968, {"zombie"}),
    # araña diminuta contra la luna en un paisaje: 'none' de baja confianza es aceptable
    ("Arachnophobia", 1990, {"spider", "none"}),
    # el artwork es un niño de impermeable + globo; Pennywise es una sombra
    ("It", 2017, {"clown", "doll", "none"}),
    ("Annabelle", 2014, {"doll"}),
    # el artwork es cuchillo + jack-o'-lantern, sin asesino visible
    ("Halloween", 1978, {"skeleton", "masked_killer", "none"}),
    ("The Birds", 1963, {"bird"}),
    ("Get Out", 2017, {"none"}),
]

def prototypes(device):
    model, _ = load_clip(device)
    tok = open_clip.get_tokenizer("ViT-B-32")
    protos = {}
    with torch.no_grad():
        for label, prompts in TAXONOMY.items():
            t = model.encode_text(tok(prompts).to(device))
            t = t / t.norm(dim=-1, keepdim=True)
            p = t.mean(0); protos[label] = (p / p.norm()).cpu().numpy()
    return protos

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--validate", action="store_true")
    ap.add_argument("--temp", type=float, default=100.0, help="softmax temperature")
    ap.add_argument("--min-score", type=float, default=0.5,
                    help="por debajo -> 'uncertain' (los scores bajos marcan artwork ambiguo)")
    args = ap.parse_args()
    device = "cuda" if torch.cuda.is_available() else "cpu"

    z = np.load(DATA / "clip_embeddings.npz")
    ids, vecs = z["ids"], z["vecs"].astype(np.float32)
    meta = pd.read_csv(DATA / "posters.csv", usecols=["id", "year", "title"])
    protos = prototypes(device)
    labels = list(protos)
    P = np.stack([protos[l] for l in labels])          # L x 512
    sims = vecs @ P.T                                   # N x L
    probs = torch.softmax(torch.tensor(sims * args.temp), dim=1).numpy()
    top = probs.argmax(1)

    df = pd.DataFrame(dict(id=ids, label=[labels[i] for i in top],
                           score=probs.max(1).round(3)))
    df.loc[df.score < args.min_score, "label"] = "uncertain"
    df = df.merge(meta, on="id")
    df["is_animal"] = df.label.isin(ANIMALS)
    df["is_creature"] = ~df.label.isin(["none", "uncertain"])

    if args.validate:
        print(f'{"titulo":38} esperado -> detectado (score)')
        ok = 0
        for t, y, exp in VALIDATION:
            m = df[(df.title == t) & (df.year == y)]
            if not len(m):
                print(f"{t:38} NO ENCONTRADO"); continue
            r = m.iloc[0]
            hit = "OK" if (r.label in exp or (r.label == "uncertain" and "none" in exp)) else "FAIL"
            ok += hit == "OK"
            print(f"{t:38} {'/'.join(sorted(exp)):28} -> {r.label:14} ({r.score:.2f}) {hit}")
        print(f"VALIDACION: {ok}/{len(VALIDATION)}")
        return

    df.to_csv(DATA / "census.csv", index=False)
    df["decade"] = (df.year // 10) * 10
    shares = (df.groupby(["decade", "label"]).size()
                .unstack(fill_value=0)
                .pipe(lambda x: x.div(x.sum(1), axis=0)).round(4))
    shares.reset_index().to_json(DATA / "census_decade.json", orient="records")
    print("=== TOP CRIATURA POR DECADA (excl. none/uncertain) ===")
    for dec, row in shares.drop(columns=[c for c in ("none","uncertain") if c in shares]).iterrows():
        top3 = row.nlargest(3)
        print(f"{dec}: " + " · ".join(f"{l} {v*100:.1f}%" for l, v in top3.items()))
    print("\n=== % con criatura / % con animal ===")
    agg = df.groupby("decade").agg(creature=("is_creature", "mean"),
                                   animal=("is_animal", "mean")).round(3)
    print(agg.to_string())

if __name__ == "__main__":
    main()

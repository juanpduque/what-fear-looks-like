#!/usr/bin/env python3
"""EL EJE DEL MIEDO, version SigLIP -- mismo metodo que clip_fear_axis.py
(eje continuo dread<->calm por proyeccion coseno) pero sobre data/siglip_embeddings.npz
en vez de CLIP ViT-B-32, para comparar si el modelo con mejor accuracy zero-shot
da una senal mas limpia.

Corre en segundos (reutiliza data/siglip_embeddings.npz, ya consolidado).

  python3 siglip_fear_axis.py --validate
  python3 siglip_fear_axis.py

Output: data/siglip_fear_axis.csv, data/siglip_fear_axis_decade.json
"""

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd
import torch
from transformers import AutoModel, AutoProcessor

DATA = Path(__file__).parent / "data"
MODEL_ID = "google/siglip-base-patch16-224"

DREAD_PROMPTS = [
    "a deeply unsettling, ominous movie poster that fills the viewer with dread and unease",
    "a horror movie poster with a dark, foreboding, nightmarish atmosphere",
    "a movie poster conveying an unmistakable sense of impending doom and terror",
    "a disturbing movie poster designed to frighten and horrify the viewer",
]
CALM_PROMPTS = [
    "a bright, cheerful, reassuring movie poster with no sense of danger",
    "an upbeat, lighthearted movie poster with a safe, pleasant mood",
    "a movie poster showing a peaceful, comforting, everyday scene",
    "a movie poster with a calm, serene, unthreatening atmosphere",
]

REGISTERS = ["nightmarish", "dreadful", "unsettling", "mild", "calm"]

VALIDATION = [
    ("Hereditary", 2018, +1),
    ("The Exorcist", 1973, +1),
    ("Sinister", 2012, +1),
    ("The Conjuring", 2013, +1),
    ("Terrifier", 2016, +1),
    ("Get Out", 2017, +1),
    ("Knives Out", 2019, -1),
    ("Clue", 1985, -1),
    ("A Simple Favor", 2018, 0),
]


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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--validate", action="store_true")
    ap.add_argument("--nbins", type=int, default=5)
    args = ap.parse_args()

    print("loading SigLIP text tower...", flush=True)
    model = AutoModel.from_pretrained(MODEL_ID).eval()
    processor = AutoProcessor.from_pretrained(MODEL_ID)
    DREAD = text_proto(model, processor, DREAD_PROMPTS)
    CALM = text_proto(model, processor, CALM_PROMPTS)
    print("prototypes ready", flush=True)

    z = np.load(DATA / "siglip_embeddings.npz")
    ids = z["ids"].astype(int)
    vecs = z["vecs"].astype(np.float32)
    axis = (vecs @ DREAD) - (vecs @ CALM)
    df = pd.DataFrame(dict(id=ids, axis=axis))
    meta = load_meta()
    df = df.merge(meta, on="id")

    if args.validate:
        want = {}
        for name, year, w in VALIDATION:
            m = df[(df.title == name) & (df.year == year)]
            if len(m):
                want[name] = (float(m.iloc[0]["axis"]), w)
        print(f"{'film':18}{'want':6}{'axis':>10}")
        wants, axes = [], []
        for name, _year, w in VALIDATION:
            if name not in want:
                print(f"{name:18} NO ENCONTRADO")
                continue
            a, w2 = want[name]
            tag = "dread" if w > 0 else "calm" if w < 0 else "mid"
            print(f"{name:18}{tag:6}{a:+10.4f}")
            wants.append(w)
            axes.append(a)
        r = np.corrcoef(wants, axes)[0, 1] if len(set(wants)) > 1 else float("nan")
        print(f"\ncorr(want, axis) = {r:+.3f}  (comparar contra 0.611 de la version CLIP)")
        return

    edges = np.quantile(df["axis"], np.linspace(0, 1, args.nbins + 1))
    edges[0], edges[-1] = -np.inf, np.inf
    b = np.digitize(df["axis"], edges[1:-1])
    df["register"] = [REGISTERS[::-1][k] for k in b]
    df.to_csv(DATA / "siglip_fear_axis.csv", index=False)
    print(f"wrote {DATA / 'siglip_fear_axis.csv'} ({len(df):,} rows)")

    d = df[(df.year >= 1920) & (df.year <= 2029)].copy()
    d["decade"] = (d.year // 10) * 10
    sh = (
        d.groupby(["decade", "register"])
        .size()
        .unstack(fill_value=0)
        .reindex(columns=REGISTERS, fill_value=0)
    )
    share = sh.div(sh.sum(1), axis=0).round(4)
    mean_axis = d.groupby("decade")["axis"].mean().round(5)
    n = sh.sum(1)
    out = []
    for dec in share.index:
        row = {"decade": int(dec), "n": int(n[dec]), "mean_axis": float(mean_axis[dec])}
        for reg in REGISTERS:
            row[reg] = float(share.loc[dec, reg])
        out.append(row)
    (DATA / "siglip_fear_axis_decade.json").write_text(json.dumps(out))

    print("\n=== por genero (SigLIP) ===")
    print(df.groupby("genre")["axis"].agg(["mean", "std", "count"]).round(4))


if __name__ == "__main__":
    main()

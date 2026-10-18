#!/usr/bin/env python3
"""
EL EJE DEL MIEDO — dread/nightmarish <-> calmo/mundano, sobre el poster completo.

Mismo metodo que clip_typography_axis.py: eje continuo por proyeccion coseno
entre dos polos de prototipos de texto, en vez de categorias discretas (evita el
problema de que categorias como "gore" se conviertan en atractores que miden otra
cosa). Reutiliza los clip_embeddings*.npz ya cacheados -- corre en segundos, sin
EC2, sin re-embeber nada.

Metrica por poster:  axis = cos(emb, DREAD_proto) - cos(emb, CALM_proto)
  (mayor = mas terrorifico/pesadillesco; menor = mas calmo/mundano)

  python3 clip_fear_axis.py --validate   # ranking de especimenes conocidos
  python3 clip_fear_axis.py --genre all  # censo completo, las 4 corpora -> csv + json

Outputs: data/fear_axis.csv (+ _scifi/_thriller/_mystery), data/fear_axis_decade.json
"""

import argparse
import json
import os
from pathlib import Path

import numpy as np
import open_clip
import pandas as pd
import torch

DATA = Path(__file__).parent / "data"

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

GENRE_FILES = {
    "horror": ("clip_embeddings.npz", "posters.csv", "fear_axis.csv"),
    "scifi": ("clip_embeddings_scifi.npz", "posters_scifi.csv", "fear_axis_scifi.csv"),
    "thriller": ("clip_embeddings_thriller.npz", "posters_thriller.csv", "fear_axis_thriller.csv"),
    "mystery": ("clip_embeddings_mystery.npz", "posters_mystery.csv", "fear_axis_mystery.csv"),
}

# ground truth a ojo: +1 aterrador/dread extremo, -1 calmo/liviano, 0 intermedio
VALIDATION = [
    ("Hereditary", 2018, +1),
    ("The Exorcist", 1973, +1),
    ("Sinister", 2012, +1),
    ("The Conjuring", 2013, +1),
    ("Terrifier", 2016, +1),
    ("Knives Out", 2019, -1),
    ("Clue", 1985, -1),
    ("The Nice Guys", 2016, -1),
    ("A Simple Favor", 2018, 0),
    ("Get Out", 2017, +1),
]


def load_clip(device):
    ckpt = os.environ.get("CLIP_CKPT")
    if ckpt:
        return open_clip.load_openai_model(ckpt, device=device).eval()
    m, _, _ = open_clip.create_model_and_transforms("ViT-B-32", pretrained="openai")
    return m.to(device).eval()


def proto(model, tok, prompts, device):
    with torch.no_grad():
        t = model.encode_text(tok(prompts).to(device))
        t = t / t.norm(dim=-1, keepdim=True)
        p = t.mean(0)
        return (p / p.norm()).cpu().numpy()


def run_genre(genre: str, DREAD: np.ndarray, CALM: np.ndarray, nbins: int) -> pd.DataFrame:
    emb_file, meta_file, out_name = GENRE_FILES[genre]
    z = np.load(DATA / emb_file)
    ids = z["ids"].astype(int)
    vecs = z["vecs"].astype(np.float32)
    axis = (vecs @ DREAD) - (vecs @ CALM)
    df = pd.DataFrame(dict(id=ids, axis=axis))
    meta = pd.read_csv(DATA / meta_file, usecols=["id", "year", "title"])
    df = df.merge(meta, on="id")

    edges = np.quantile(df["axis"], np.linspace(0, 1, nbins + 1))
    edges[0], edges[-1] = -np.inf, np.inf
    b = np.digitize(df["axis"], edges[1:-1])  # 0..nbins-1, 0=calm
    df["register"] = [REGISTERS[::-1][k] for k in b]  # reversed -> 0=nightmarish
    df["genre"] = genre
    df.to_csv(DATA / out_name, index=False)
    print(f"[{genre}] wrote {DATA / out_name} ({len(df):,} rows)")
    return df


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--validate", action="store_true")
    ap.add_argument("--genre", default="all", choices=["all", *GENRE_FILES])
    ap.add_argument("--nbins", type=int, default=5)
    args = ap.parse_args()
    device = "cuda" if torch.cuda.is_available() else "cpu"

    model = load_clip(device)
    tok = open_clip.get_tokenizer("ViT-B-32")
    DREAD = proto(model, tok, DREAD_PROMPTS, device)
    CALM = proto(model, tok, CALM_PROMPTS, device)

    if args.validate:
        found = {}
        for genre, (emb_file, meta_file, _) in GENRE_FILES.items():
            z = np.load(DATA / emb_file)
            ids = z["ids"].astype(int)
            vecs = z["vecs"].astype(np.float32)
            axis = (vecs @ DREAD) - (vecs @ CALM)
            dfv = pd.DataFrame(dict(id=ids, axis=axis))
            meta = pd.read_csv(DATA / meta_file, usecols=["id", "year", "title"])
            dfv = dfv.merge(meta, on="id")
            for name, year, w in VALIDATION:
                if name in found:
                    continue
                m = dfv[(dfv.title == name) & (dfv.year == year)]
                if len(m):
                    found[name] = (float(m.iloc[0]["axis"]), w, genre)

        print(f"{'film':18}{'want':6}{'axis':>10}  genre")
        wants, axes = [], []
        for name, _year, w in VALIDATION:
            if name not in found:
                print(f"{name:18} NO ENCONTRADO")
                continue
            a, w2, genre = found[name]
            tag = "dread" if w > 0 else "calm" if w < 0 else "mid"
            print(f"{name:18}{tag:6}{a:+10.4f}  {genre}")
            wants.append(w)
            axes.append(a)
        r = np.corrcoef(wants, axes)[0, 1] if len(set(wants)) > 1 else float("nan")
        print(
            f"\ncorr(want, axis) = {r:+.3f}  (>=0.6 para confiar, encontrados {len(found)}/{len(VALIDATION)})"
        )
        return

    genres = list(GENRE_FILES) if args.genre == "all" else [args.genre]
    frames = []
    for g in genres:
        frames.append(run_genre(g, DREAD, CALM, args.nbins))
    df = pd.concat(frames, ignore_index=True)

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
    (DATA / "fear_axis_decade.json").write_text(json.dumps(out))

    print("\n=== SHARE DE REGISTRO DE MIEDO POR DECADA (todas las corpora) ===")
    print(f"{'dec':6}" + "".join(f"{r:>13}" for r in REGISTERS) + f"{'mean':>10}{'n':>7}")
    for row in out:
        print(
            f"{row['decade']:<6}"
            + "".join(f"{row[r] * 100:>12.1f}%" for r in REGISTERS)
            + f"{row['mean_axis']:>+10.4f}{row['n']:>7}"
        )
    print(
        f"\nPearson(decada, mean_axis) = "
        f"{np.corrcoef(share.index.astype(float), mean_axis.values)[0, 1]:+.3f}"
    )

    print("\n=== por genero ===")
    print(df.groupby("genre")["axis"].agg(["mean", "std", "count"]).round(4))


if __name__ == "__main__":
    main()

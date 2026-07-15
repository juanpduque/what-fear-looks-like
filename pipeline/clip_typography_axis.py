#!/usr/bin/env python3
"""
THE LETTERING OF FEAR (v2) — el eje ORNAMENTADO <-> MINIMAL de los titulos.

Por que este script y no clip_typography.py:
  La clasificacion en 8 estilos discretos NO paso validacion (6/10) porque, sobre
  el poster COMPLETO, clases como "dripping" se convierten en atractores que en
  realidad miden oscuridad, no letras. Probamos ademas:
    - recortar el titulo con OCR (tesseract)      -> 4/10  (el OCR no lee fuentes
      ornamentadas y termina recortando la linea mas legible: sesgo hacia "clean")
    - recorte por MSER + realce de contraste CLAHE -> corr 0.72-0.78
    - poster completo, eje continuo ornate<->clean -> corr 0.81, r(decada)=-0.93  <-- GANADOR

  Conclusion empirica: la senal tipografica robusta que CLIP puede leer sobre el
  poster completo es un EJE CONTINUO de ornamentacion (display pintado/ilustrado
  <-> tipo limpio/minimal), no 8 categorias. Es exactamente la tesis del ensayo de
  Nightingale sobre tipografia en portadas de discos, medida honestamente.

Metrica por poster:  axis = cos(emb, ORNATE_proto) - cos(emb, CLEAN_proto)
  (mayor = mas ornamentado/decorativo; menor = mas limpio/minimal)

Los posters se binean en 5 REGISTROS por cuantiles GLOBALES fijos, y se agrega el
share de cada registro por decada -> streamgraph.

  export CLIP_CKPT=$HOME/Documents/anatomy-of-fear/pipeline/models/ViT-B-32.pt
  python3 clip_typography_axis.py --validate   # ranking de especimenes (corr esperada ~0.81)
  python3 clip_typography_axis.py              # censo completo -> csv + json

Outputs: data/typography.csv, data/typography_decade.json
Corre en segundos: reutiliza data/clip_embeddings.npz (no re-embebe nada).
"""
import argparse, os
from pathlib import Path
import numpy as np
import pandas as pd
import torch
import open_clip

DATA = Path(__file__).parent / "data"

# prototipos centrados en la LETRA, despojados de "mood" de horror (que sesgaba)
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

# 5 registros ordinales (de mas ornamentado a mas minimal)
REGISTERS = ["ornate", "decorative", "standard", "clean", "minimal"]

# ground truth verificado a ojo: intencion en el eje (+1 ornamentado, -1 minimal, 0 medio)
VALIDATION = [
    (244,    "King Kong",      +1),
    (57283,  "Haxan",          +1),
    (3053,   "Fearless Vamp.", +1),
    (21588,  "Cemetery Man",   +1),
    (377,    "Nightmare Elm",   0),
    (948,    "Halloween",      -1),
    (48171,  "The Rite",       -1),
    (4232,   "Scream",         -1),
    (8461,   "Funny Games",    -1),
    (493922, "Hereditary",     -1),
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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--validate", action="store_true")
    ap.add_argument("--nbins", type=int, default=5)
    args = ap.parse_args()
    device = "cuda" if torch.cuda.is_available() else "cpu"

    model = load_clip(device)
    tok = open_clip.get_tokenizer("ViT-B-32")
    ORNATE = proto(model, tok, ORNATE_PROMPTS, device)
    CLEAN = proto(model, tok, CLEAN_PROMPTS, device)

    z = np.load(DATA / "clip_embeddings.npz")
    ids = z["ids"].astype(int)
    vecs = z["vecs"].astype(np.float32)
    axis = (vecs @ ORNATE) - (vecs @ CLEAN)
    df = pd.DataFrame(dict(id=ids, axis=axis))
    meta = pd.read_csv(DATA / "posters.csv", usecols=["id", "year", "title"])
    df = df.merge(meta, on="id")

    if args.validate:
        want = {i: w for i, _, w in VALIDATION}
        sub = df[df.id.isin(want)].copy()
        sub["want"] = sub.id.map(want)
        r = np.corrcoef(sub["want"], sub["axis"])[0, 1]
        print(f'{"film":16}{"want":6}{"axis":>10}')
        for i, name, w in VALIDATION:
            a = df[df.id == i]["axis"]
            a = float(a.iloc[0]) if len(a) else float("nan")
            tag = "orn" if w > 0 else "min" if w < 0 else "mid"
            print(f"{name:16}{tag:6}{a:+10.4f}")
        print(f"\ncorr(want, axis) = {r:+.3f}   (>=0.75 para confiar; full-poster baseline 0.81)")
        return

    # binea por cuantiles GLOBALES fijos -> registros ordinales
    edges = np.quantile(df["axis"], np.linspace(0, 1, args.nbins + 1))
    edges[0], edges[-1] = -np.inf, np.inf
    # bin 0 = mas minimal (axis bajo) ... bin n-1 = mas ornamentado (axis alto)
    # invertimos para que REGISTERS[0]="ornate" corresponda al axis mas alto
    b = np.digitize(df["axis"], edges[1:-1])           # 0..nbins-1, 0=minimal
    df["register"] = [REGISTERS[::-1][k] for k in b]    # reversed -> 0=ornate
    df.to_csv(DATA / "typography.csv", index=False)

    d = df[(df.year >= 1920) & (df.year <= 2029)].copy()
    d["decade"] = (d.year // 10) * 10
    sh = (d.groupby(["decade", "register"]).size().unstack(fill_value=0)
            .reindex(columns=REGISTERS, fill_value=0))
    share = sh.div(sh.sum(1), axis=0).round(4)
    mean_axis = d.groupby("decade")["axis"].mean().round(5)
    n = sh.sum(1)
    out = []
    for dec in share.index:
        row = {"decade": int(dec), "n": int(n[dec]),
               "mean_axis": float(mean_axis[dec])}
        for reg in REGISTERS:
            row[reg] = float(share.loc[dec, reg])
        out.append(row)
    pd.Series(out).to_json(DATA / "typography_decade.json", orient="values")
    import json
    (DATA / "typography_decade.json").write_text(json.dumps(out))

    print("=== SHARE DE REGISTRO TIPOGRAFICO POR DECADA ===")
    print(f'{"dec":6}' + "".join(f"{r:>12}" for r in REGISTERS) + f'{"mean":>10}{"n":>7}')
    for row in out:
        print(f'{row["decade"]:<6}' +
              "".join(f"{row[r]*100:>11.1f}%" for r in REGISTERS) +
              f'{row["mean_axis"]:>+10.4f}{row["n"]:>7}')
    print(f"\nPearson(decada, mean_axis) = "
          f'{np.corrcoef(share.index.astype(float), mean_axis.values)[0,1]:+.3f}')


if __name__ == "__main__":
    main()

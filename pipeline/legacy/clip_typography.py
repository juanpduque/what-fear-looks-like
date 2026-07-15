#!/usr/bin/env python3
"""
THE LETTERING OF FEAR — title-typography styles over CLIP embeddings.
Como el ensayo de Nightingale sobre tipografía en portadas de discos,
pero para un siglo de terror. Corre en segundos contra data/clip_embeddings.npz.

  export CLIP_CKPT=$HOME/Documents/anatomy-of-fear/pipeline/models/ViT-B-32.pt
  python3 clip_typography.py --validate    # primero: ground truth verificada a ojo
  python3 clip_typography.py               # censo tipográfico completo

CAVEAT (en el docstring porque importa): el embedding es del póster COMPLETO;
la señal tipográfica compite con la imagen. Si la validación no pasa 7/10,
el plan B es re-embeber recortes del bloque de título (script aparte).
Outputs: data/typography.csv, data/typography_decade.json
"""
import argparse
from pathlib import Path
import numpy as np
import pandas as pd
import torch
import open_clip


def load_clip(device):
    import os
    ckpt = os.environ.get("CLIP_CKPT")
    if ckpt:
        model = open_clip.load_openai_model(ckpt, device=device)
        return model.eval()
    m, _, _ = open_clip.create_model_and_transforms("ViT-B-32", pretrained="openai")
    return m.to(device).eval()

DATA = Path(__file__).parent / "data"

TYPE_TAXONOMY = {
  "painted_pulp":  ["a vintage movie poster with ornate hand-painted 3D display lettering",
                    "old pulp movie poster title with dimensional painted letters"],
  "dripping":      ["a horror poster title in dripping blood lettering",
                    "a movie poster with melting oozing horror letters"],
  "scrawl":        ["a movie poster title in rough handwritten scratchy lettering",
                    "a poster with scrawled brush-stroke title letters"],
  "chrome_80s":    ["a movie poster title in shiny chrome metallic 3D letters",
                    "an 80s poster with beveled metallic logo lettering"],
  "gothic":        ["a movie poster title in gothic blackletter typeface",
                    "a poster with medieval gothic calligraphy title"],
  "classic_serif": ["a movie poster title in elegant classic serif capitals",
                    "a poster with clean traditional serif typography"],
  "bold_sans":     ["a movie poster title in bold condensed sans-serif capitals",
                    "a poster with heavy modern grotesque block letters"],
  "minimal_thin":  ["a movie poster with small thin minimal typography",
                    "a poster with tiny understated lightweight type"],
}

# ground truth verificada MIRANDO cada artwork (ids de nuestros especímenes)
VALIDATION = [  # (title, year, acceptable styles)
    ("King Kong", 1933, {"painted_pulp"}),                    # letras 3D pintadas doradas
    ("The Fearless Vampire Killers", 1967, {"painted_pulp", "dripping"}),  # rojo dibujado a mano
    ("Halloween", 1978, {"classic_serif", "bold_sans"}),      # caps serif blancas limpias
    ("A Nightmare on Elm Street", 1984, {"scrawl", "dripping"}),  # brochazo rojo áspero
    ("Cemetery Man", 1994, {"dripping", "painted_pulp"}),     # goteo verde/rojo
    ("Scream", 1996, {"classic_serif", "minimal_thin"}),      # serif blanca fina
    ("Funny Games", 2008, {"bold_sans", "minimal_thin"}),     # sans blanca limpia
    ("The Rite", 2011, {"classic_serif", "chrome_80s"}),      # serif grabada metálica
    ("Hereditary", 2018, {"minimal_thin", "classic_serif"}),  # serif pequeña elegante
    ("Häxan", 1922, {"classic_serif", "painted_pulp"}),       # caps serif blancas
]

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--validate", action="store_true")
    ap.add_argument("--temp", type=float, default=100.0)
    ap.add_argument("--min-score", type=float, default=0.35)
    args = ap.parse_args()
    device = "cuda" if torch.cuda.is_available() else "cpu"

    model = load_clip(device)
    tok = open_clip.get_tokenizer("ViT-B-32")
    protos, labels = [], list(TYPE_TAXONOMY)
    with torch.no_grad():
        for lab in labels:
            t = model.encode_text(tok(TYPE_TAXONOMY[lab]).to(device))
            t = t / t.norm(dim=-1, keepdim=True)
            p = t.mean(0); protos.append((p / p.norm()).cpu().numpy())
    P = np.stack(protos)

    z = np.load(DATA / "clip_embeddings.npz")
    ids, vecs = z["ids"], z["vecs"].astype(np.float32)
    probs = torch.softmax(torch.tensor((vecs @ P.T) * args.temp), dim=1).numpy()
    top = probs.argmax(1)
    df = pd.DataFrame(dict(id=ids.astype(int), style=[labels[i] for i in top],
                           score=probs.max(1).round(3)))
    df.loc[df.score < args.min_score, "style"] = "uncertain"
    meta = pd.read_csv(DATA / "posters.csv", usecols=["id", "year", "title"])
    df = df.merge(meta, on="id")

    if args.validate:
        ok = 0
        print(f'{"titulo":34} aceptables{"":22} -> detectado (score)')
        for t, y, exp in VALIDATION:
            m = df[(df.title == t) & (df.year == y)]
            if not len(m):
                print(f"{t:34} NO ENCONTRADO"); continue
            r = m.iloc[0]
            hit = "OK" if r.style in exp else "FAIL"
            ok += hit == "OK"
            print(f'{t:34} {"/".join(sorted(exp)):32} -> {r.style:14} ({r.score:.2f}) {hit}')
        print(f"VALIDACION: {ok}/{len(VALIDATION)}  (7+ para confiar; si no, plan B: recortes de título)")
        return

    df.to_csv(DATA / "typography.csv", index=False)
    df["decade"] = (df.year // 10) * 10
    sh = (df.groupby(["decade", "style"]).size().unstack(fill_value=0)
            .pipe(lambda x: x.div(x.sum(1), axis=0)).round(4))
    sh.reset_index().to_json(DATA / "typography_decade.json", orient="records")
    print("=== ESTILO TIPOGRAFICO DOMINANTE POR DECADA (excl. uncertain) ===")
    drop = [c for c in ("uncertain",) if c in sh]
    for dec, row in sh.drop(columns=drop).iterrows():
        top3 = row.nlargest(3)
        print(f"{dec}: " + " · ".join(f"{k} {v*100:.1f}%" for k, v in top3.items()))

if __name__ == "__main__":
    main()

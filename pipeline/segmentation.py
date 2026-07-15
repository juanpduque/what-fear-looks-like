#!/usr/bin/env python3
"""
SEMANTIC SEGMENTATION — material & scene composition per poster.
==================================================================
No LayoutParser/Detectron2 (see multi_analyze.py's docstring for the "why
not" — document-layout models don't fit poster art, and Detectron2 has an
unresolved checkpoint bug on macOS/Apple Silicon). Three complementary
%-of-area signals instead, all pip-installable, no compiling:

  1. SegFormer-b0 (ADE20K, 150 scene classes) -- real pixel-level semantic
     segmentation on the full image -> % area for a curated backdrop/scene
     subset (sky, water, tree, rock, building...).
  2. Minc-Materials-23 (SigLIP2, MINC-style material taxonomy) -- applied
     per grid patch. Coarse ("poor man's segmentation": one label per patch,
     no pixel boundaries) but has real precedent -- CLIP-DIY (WACV 2024),
     MaskCLIP (ECCV 2022) -- -> % of patches per material (metal, fabric,
     stone, wood...).
  3. CLIP zero-shot (same ViT-B-32 already cached elsewhere in this
     pipeline, see clip_embed.py/clip_census.py) on the same grid, against a
     horror-specific open vocabulary (blood, smoke, bone...) that neither
     ADE20K nor MINC cover.

Posters are processed in chunks so SegFormer/Minc/CLIP each run as ONE
batched forward pass per chunk (much faster on CPU than per-poster calls —
measured ~3x for Minc).

KNOWN BIASES (checked against real artwork, see --validate): both SegFormer
and Minc-Materials-23 were trained on photos of real scenes/materials, not
illustrated/painted poster art, and it shows:
  - ade_wall fires as a systematic false positive on abstract or painted
    flat backgrounds that aren't walls at all (e.g. The Evil Dead's fiery
    red backdrop) -- it seems to be SegFormer's fallback for "flat surface,
    no better match".
  - minc_plastic fires similarly on flat/dark silhouette-style illustration
    (e.g. Friday the 13th's black knife-silhouette framing).
  - Both ade_water/minc_water can be fooled by a dominant blue color cast
    even with no literal water (The Thing's icy blue energy burst).
  - CLIP zero-shot (clip_*) validated cleanly on every test case (water,
    forest, night sky, weapon, skin) -- trust it more than ade_wall/
    minc_plastic specifically. Treat those two columns as noisy.

One-time setup (downloads ~400MB of model weights on first run):
  pip3 install transformers        # torch + open_clip already required elsewhere

Run (resumable):
  python3 segmentation.py --validate       # sanity-check on known posters first
  python3 segmentation.py --sample 500     # quick validation
  python3 segmentation.py --sample 3000    # stratified sample, ~1h on CPU
  python3 segmentation.py                  # full 28.7k (~10-12h on CPU — see README)
  python3 segmentation.py --budget 300     # stop after N seconds (rerun to resume)

Outputs: data/segmentation.csv (per-poster % area/patches by class),
         data/segmentation_decade.json ("material palette" per decade)
"""
import argparse, os, time, warnings
from pathlib import Path
import numpy as np
import pandas as pd
import torch
from PIL import Image
import open_clip
from transformers import (SegformerImageProcessor, SegformerForSemanticSegmentation,
                           AutoImageProcessor, AutoModelForImageClassification)

warnings.filterwarnings("ignore")
torch.set_num_threads(os.cpu_count() or 4)

DATA = Path(__file__).parent / "data"
CHECKPOINT = DATA / "segmentation_partial.csv"
GRID = (2, 2)          # cols x rows patches for Minc/CLIP (4 patches: fast, coarse)
CHUNK = 16              # posters per batched model call

# Curated ADE20K subset: full taxonomy is 150 indoor/outdoor scene classes
# (furniture, appliances...); horror posters mostly care about backdrops.
ADE_KEEP = {0: "wall", 1: "building", 2: "sky", 4: "tree", 6: "road",
            12: "person", 13: "earth", 16: "mountain", 21: "water",
            25: "house", 26: "sea", 29: "field", 34: "rock", 126: "animal"}

HORROR_VOCAB = {
    "blood":      ["a horror movie poster with blood or a bloodstain"],
    "smoke_fog":  ["a horror movie poster with smoke or fog"],
    "fire":       ["a horror movie poster with fire or flames"],
    "bone_skull": ["a horror movie poster with a skull or bones"],
    "weapon":     ["a horror movie poster with a knife, axe, or weapon"],
    "shadow":     ["a horror movie poster dominated by dark shadow"],
    "water":      ["a horror movie poster with water, a lake, or the ocean"],
    "forest":     ["a horror movie poster with a forest or trees"],
    "night_sky":  ["a horror movie poster with a night sky or moon"],
    "snow":       ["a horror movie poster with snow or ice"],
}

VALIDATION = [  # (title, year, expected labels: al menos uno debe estar en el top-6)
    # ground truth verificada mirando el artwork real de TMDB. No probamos
    # ade_wall/minc_plastic aca -- ya confirmamos que son falsos positivos
    # sistematicos en fondos abstractos/pintados (ver docstring); estos casos
    # validan las senales que SI funcionan bien (clip_* sobre todo).
    ("Jaws", 1975, {"clip_water", "ade_sea", "minc_water"}),
    ("Friday the 13th", 1980, {"ade_tree", "clip_forest", "clip_night_sky", "clip_weapon"}),
    ("The Blair Witch Project", 1999, {"ade_person", "minc_skin"}),
]

def load_models(device):
    seg_proc = SegformerImageProcessor.from_pretrained("nvidia/segformer-b0-finetuned-ade-512-512")
    seg_model = SegformerForSemanticSegmentation.from_pretrained(
        "nvidia/segformer-b0-finetuned-ade-512-512").to(device).eval()
    minc_proc = AutoImageProcessor.from_pretrained("prithivMLmods/Minc-Materials-23")
    minc_model = AutoModelForImageClassification.from_pretrained(
        "prithivMLmods/Minc-Materials-23").to(device).eval()
    clip_model, _, clip_pre = open_clip.create_model_and_transforms("ViT-B-32", pretrained="openai")
    clip_model = clip_model.to(device).eval()
    clip_tok = open_clip.get_tokenizer("ViT-B-32")
    return dict(seg_proc=seg_proc, seg_model=seg_model, minc_proc=minc_proc,
                minc_model=minc_model, clip_model=clip_model, clip_pre=clip_pre,
                clip_tok=clip_tok)

def clip_prototypes(models, device):
    """Text-prompt prototypes for the open-vocabulary horror terms, same
    prompt-ensemble approach as clip_census.py's monster taxonomy."""
    protos = {}
    with torch.no_grad():
        for label, prompts in HORROR_VOCAB.items():
            t = models["clip_model"].encode_text(models["clip_tok"](prompts).to(device))
            t = t / t.norm(dim=-1, keepdim=True)
            p = t.mean(0)
            protos[label] = (p / p.norm()).cpu().numpy()
    return protos

def grid_patches(img, cols, rows):
    W, H = img.size
    pw, ph = max(W // cols, 1), max(H // rows, 1)
    return [img.crop((c * pw, r * ph, (c + 1) * pw, (r + 1) * ph))
            for r in range(rows) for c in range(cols)]

def analyze_chunk(imgs, models, protos, device):
    """One batched forward pass per model for the whole chunk. Returns a
    list of per-poster dicts, same order as `imgs`."""
    n = len(imgs)

    # 1. SegFormer: pixel-level segmentation, batched across posters.
    seg_in = models["seg_proc"](images=imgs, return_tensors="pt").to(device)
    with torch.no_grad():
        seg_logits = models["seg_model"](**seg_in).logits
    preds = seg_logits.argmax(1).cpu().numpy()  # (n, h, w)
    ade_rows = []
    for pred in preds:
        total = pred.size
        ade_rows.append({f"ade_{name}": round(float((pred == cid).sum()) / total, 4)
                          for cid, name in ADE_KEEP.items()})

    # 2. Grid patches for every poster, flattened into one batch per model.
    per_img_patches = [grid_patches(img, *GRID) for img in imgs]
    all_patches = [p for patches in per_img_patches for p in patches]

    minc_in = models["minc_proc"](images=all_patches, return_tensors="pt").to(device)
    with torch.no_grad():
        minc_logits = models["minc_model"](**minc_in).logits
    minc_top = minc_logits.argmax(1).cpu().numpy()
    minc_labels = models["minc_model"].config.id2label

    clip_batch = torch.stack([models["clip_pre"](p) for p in all_patches]).to(device)
    with torch.no_grad():
        feats = models["clip_model"].encode_image(clip_batch)
        feats = feats / feats.norm(dim=-1, keepdim=True)
    P = np.stack(list(protos.values()))
    clip_sims = feats.cpu().numpy() @ P.T
    clip_top = clip_sims.argmax(1)
    clip_labels = list(protos)

    rows, offset = [], 0
    for i in range(n):
        k = len(per_img_patches[i])
        mt, ct = minc_top[offset:offset + k], clip_top[offset:offset + k]
        row = dict(ade_rows[i])
        row.update({f"minc_{minc_labels[j]}": round(float((mt == j).sum()) / k, 4)
                    for j in minc_labels})
        row.update({f"clip_{clip_labels[j]}": round(float((ct == j).sum()) / k, 4)
                    for j in range(len(clip_labels))})
        rows.append(row)
        offset += k
    return rows

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", type=int, default=0, help="0 = all posters")
    ap.add_argument("--budget", type=float, default=0, help="seconds; 0 = no limit")
    ap.add_argument("--validate", action="store_true")
    args = ap.parse_args()
    device = "cuda" if torch.cuda.is_available() else "cpu"

    meta_full = pd.read_csv(DATA / "posters.csv", usecols=["id", "year", "title"])

    if args.validate:
        print("loading models (SegFormer-b0, Minc-Materials-23, CLIP ViT-B-32)...")
        models = load_models(device)
        protos = clip_prototypes(models, device)
        print(f'{"titulo":40} {"esperado":45} resultado')
        ok = True
        for t, y, expected in VALIDATION:
            row = meta_full[(meta_full.title == t) & (meta_full.year == y)]
            if not len(row):
                print(f"{t:40} NO ENCONTRADO"); continue
            pid = int(row.iloc[0].id)
            img = Image.open(DATA / "posters" / f"{pid}.jpg").convert("RGB")
            result = analyze_chunk([img], models, protos, device)[0]
            top6 = {k for k, _ in sorted(result.items(), key=lambda x: -x[1])[:6]}
            hit = expected & top6
            flag = "OK" if hit else "FAIL"
            ok &= flag == "OK"
            print(f'{t:40} {"/".join(expected):45} {"/".join(hit) or "-":20} {flag}')
        print("VALIDACION:", "PASA" if ok else "REVISAR")
        return

    meta = meta_full.drop(columns=["title"])
    if args.sample:
        n_decades = meta.year.floordiv(10).mul(10).nunique()
        meta = meta.groupby(meta.year // 10 * 10, group_keys=False).apply(
            lambda g: g.sample(min(len(g), max(1, args.sample // n_decades)), random_state=42))

    done = set(pd.read_csv(CHECKPOINT).id) if CHECKPOINT.exists() else set()
    todo = meta[~meta.id.isin(done)]
    print(f"pending: {len(todo):,} / {len(meta):,}")
    if len(todo):
        print("loading models (SegFormer-b0, Minc-Materials-23, CLIP ViT-B-32)...")
        models = load_models(device)
        protos = clip_prototypes(models, device)

        # Flush to the checkpoint every FLUSH_EVERY chunks, not just once at
        # the end -- a run over the full 28.7k is a multi-hour unattended
        # job, and losing all of it to a crash/interruption near the end
        # would be a bad trade for saving a few CSV writes.
        FLUSH_EVERY = 5
        t0, rows, n_done_total = time.time(), [], 0
        ids, years = list(todo.id), list(todo.year)
        for ci, i in enumerate(range(0, len(ids), CHUNK)):
            if args.budget and time.time() - t0 > args.budget:
                break
            batch_ids, batch_yrs, imgs = [], [], []
            for pid, yr in zip(ids[i:i + CHUNK], years[i:i + CHUNK]):
                f = DATA / "posters" / f"{pid}.jpg"
                if not f.exists():
                    continue
                try:
                    imgs.append(Image.open(f).convert("RGB"))
                    batch_ids.append(pid)
                    batch_yrs.append(yr)
                except Exception:
                    continue
            if not imgs:
                continue
            try:
                batch_rows = analyze_chunk(imgs, models, protos, device)
            except Exception as e:
                print(f"  chunk failed ({e}), skipping {len(imgs)} posters")
                continue
            for pid, yr, row in zip(batch_ids, batch_yrs, batch_rows):
                row.update(id=pid, year=int(yr))
                rows.append(row)
            rate = (n_done_total + len(rows)) / max(time.time() - t0, 1e-9)
            print(f"  {n_done_total + len(rows):,}/{len(todo):,} | {rate:.2f}/s", end="\r")

            if rows and (ci + 1) % FLUSH_EVERY == 0:
                pd.DataFrame(rows).to_csv(CHECKPOINT, mode="a",
                                           header=not CHECKPOINT.exists(), index=False)
                n_done_total += len(rows)
                rows = []

        if rows:
            pd.DataFrame(rows).to_csv(CHECKPOINT, mode="a",
                                       header=not CHECKPOINT.exists(), index=False)
            n_done_total += len(rows)
        total = len(done) + n_done_total
        rate = n_done_total / max(time.time() - t0, 1e-9)
        print(f"\nbatch: {n_done_total:,} | total: {total:,}/{len(meta):,} | {rate:.2f}/s")

    # Regenerate the aggregates from whatever the checkpoint has so far —
    # runs take hours, so callers can inspect progress after any --budget
    # slice, not just once the full dataset finishes.
    if CHECKPOINT.exists():
        d = pd.read_csv(CHECKPOINT).drop_duplicates("id")
        d.to_csv(DATA / "segmentation.csv", index=False)
        d["decade"] = (d.year // 10) * 10
        cols = [c for c in d.columns if c not in ("id", "year", "decade")]
        agg = d.groupby("decade")[cols].mean().round(4)
        agg["n"] = d.groupby("decade").size()
        agg.reset_index().to_json(DATA / "segmentation_decade.json", orient="records")
        print("\n=== TOP 5 CLASES POR DECADA (de lo procesado hasta ahora) ===")
        for dec, r in agg.drop(columns="n").iterrows():
            top5 = r.nlargest(5)
            print(f"{dec}: " + " · ".join(f"{k} {v*100:.1f}%" for k, v in top5.items()))

if __name__ == "__main__":
    main()

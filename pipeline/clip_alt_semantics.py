#!/usr/bin/env python3
"""CLIP zero-shot horror vocabulary (clip_blood, clip_weapon...) for alternate sheets.

segmentation.py scored the measured sheet of every film; alternates were never
scored, so the autopsy showed "CLIP blood —" for them and kept the measured
sheet's other clip_* values. This runs only the CLIP part of segmentation.py
(same ViT-B-32, prompts and 2x2 grid; SegFormer/Minc are not published per
alternate) over the alternates in site/data/poster_alts.json, streaming each
sheet from the TMDB CDN.

  python3 clip_alt_semantics.py --validate 200  # re-score measured sheets, compare to segmentation.csv
  python3 clip_alt_semantics.py                  # all alternates (resumable checkpoint)

Writes:
  data/qa/clip_sem_alts.csv          id,file_path,clip_* (every vocabulary term)
  site/data/poster_alts_clip.json    {id: {path: {blood: .25, ...}}} -- only the
                                     terms build_lookup.py publishes, zeros dropped
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import open_clip
import torch
from PIL import Image

from build_lookup import SEG_KEYS
from segmentation import GRID, HORROR_VOCAB, grid_patches

HERE = Path(__file__).resolve().parent
DATA = HERE / "data"
SITE = HERE.parent / "site"
ALTS = SITE / "data" / "poster_alts.json"
CKPT = DATA / "qa" / "clip_sem_alts.csv"
OUT = SITE / "data" / "poster_alts_clip.json"
TMDB = "https://image.tmdb.org/t/p/w500"
LABELS = list(HORROR_VOCAB)
COLS = ["id", "file_path"] + [f"clip_{k}" for k in LABELS]
CHUNK = 32


def load(device):
    model, _, pre = open_clip.create_model_and_transforms("ViT-B-32", pretrained="openai")
    model = model.to(device).eval()
    tok = open_clip.get_tokenizer("ViT-B-32")
    protos = []
    with torch.no_grad():
        for prompts in HORROR_VOCAB.values():
            t = model.encode_text(tok(prompts).to(device))
            t = t / t.norm(dim=-1, keepdim=True)
            p = t.mean(0)
            protos.append((p / p.norm()).cpu().numpy())
    return model, pre, np.stack(protos)


def score(imgs, model, pre, protos, device):
    """Share of grid patches whose nearest prototype is each label (segmentation.analyze_chunk)."""
    patches = [p for img in imgs for p in grid_patches(img, *GRID)]
    with torch.no_grad():
        f = model.encode_image(torch.stack([pre(p) for p in patches]).to(device))
        f = f / f.norm(dim=-1, keepdim=True)
    top = (f.cpu().numpy() @ protos.T).argmax(1)
    k = GRID[0] * GRID[1]
    return [
        [round(float((top[i : i + k] == j).sum()) / k, 4) for j in range(len(LABELS))]
        for i in range(0, len(top), k)
    ]


def fetch(path: str):
    for _ in range(3):
        try:
            with urllib.request.urlopen(TMDB + path, timeout=30) as r:
                return Image.open(io.BytesIO(r.read())).convert("RGB")
        except Exception:
            time.sleep(1)
    return None


def validate(n: int, device) -> None:
    """Re-score measured sheets from the same CDN size; 2x2 argmax flips on tiny pixel changes."""
    import pandas as pd

    seg = pd.read_csv(DATA / "segmentation.csv").set_index("id")
    alts = json.loads(ALTS.read_text(encoding="utf-8"))
    measured = {int(pid): row[0] for pid, rows in alts.items() for row in rows if row[2]}
    ids = [i for i in sorted(measured) if i in seg.index][:n]
    model, pre, protos = load(device)
    with ThreadPoolExecutor(16) as ex:
        imgs = list(ex.map(lambda i: fetch(measured[i]), ids))
    ids, imgs = zip(*[(i, im) for i, im in zip(ids, imgs) if im])
    got = np.array(score(list(imgs), model, pre, protos, device))
    ref = seg.loc[list(ids), [f"clip_{k}" for k in LABELS]].to_numpy()
    same = np.abs(ref - got) < 1e-6
    print(
        f"{len(ids)} measured sheets vs segmentation.csv: all terms identical on {same.all(1).mean():.0%}; "
        + ", ".join(f"{k} {same[:, j].mean():.0%}" for j, k in enumerate(LABELS))
    )


def run(device) -> None:
    alts = json.loads(ALTS.read_text(encoding="utf-8"))
    todo = [(pid, row[0]) for pid, rows in alts.items() for row in rows if not row[2]]
    done = set()
    if CKPT.exists():
        with CKPT.open(encoding="utf-8") as f:
            done = {(r["id"], r["file_path"]) for r in csv.DictReader(f)}
    todo = [k for k in todo if k not in done]
    print(f"pending {len(todo):,} alternate sheets ({len(done):,} done)", flush=True)
    if todo:
        model, pre, protos = load(device)
        CKPT.parent.mkdir(parents=True, exist_ok=True)
        new = not CKPT.exists()
        t0, failed = time.time(), 0
        with CKPT.open("a", newline="", encoding="utf-8") as f, ThreadPoolExecutor(16) as ex:
            w = csv.writer(f)
            if new:
                w.writerow(COLS)
            for i in range(0, len(todo), CHUNK):
                keys = todo[i : i + CHUNK]
                got = [(k, im) for k, im in zip(keys, ex.map(lambda k: fetch(k[1]), keys)) if im]
                failed += len(keys) - len(got)
                if got:
                    for (pid, path), vals in zip(
                        (k for k, _ in got),
                        score([im for _, im in got], model, pre, protos, device),
                    ):
                        w.writerow([pid, path, *vals])
                    f.flush()
                n = i + len(keys)
                print(
                    f"  {n:,}/{len(todo):,} | {n / (time.time() - t0):.1f}/s | failed {failed}",
                    flush=True,
                )
    export()


def export() -> None:
    keep = [k.replace("clip_", "") for k in SEG_KEYS]
    out: dict[str, dict[str, dict]] = {}
    with CKPT.open(encoding="utf-8") as f:
        for r in csv.DictReader(f):
            vals = {k: float(r[f"clip_{k}"]) for k in keep if float(r[f"clip_{k}"]) > 0}
            out.setdefault(r["id"], {})[r["file_path"]] = vals
    OUT.write_text(json.dumps(out, separators=(",", ":"), sort_keys=True), encoding="utf-8")
    print(f"wrote {OUT} sheets={sum(map(len, out.values())):,}")


def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--validate", type=int, default=0, metavar="N")
    ap.add_argument("--export-only", action="store_true")
    ap.add_argument("--device", default="cpu")
    args = ap.parse_args()
    torch.set_num_threads(4)
    if args.validate:
        validate(args.validate, args.device)
    elif args.export_only:
        export()
    else:
        run(args.device)


if __name__ == "__main__":
    main()

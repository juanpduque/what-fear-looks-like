#!/usr/bin/env python3
"""CLIP zero-shot sanity check on recovered posters (OMDb / IMDb-art fallback).

Flags images that are more likely a logo/placeholder/broken-image than real
poster artwork, using the same CLIP model as clip_embed.py.

Usage:
  python3 curate_recovered_posters.py --ids-file data/qa/recovered_ids_to_check.txt
"""

from __future__ import annotations

import argparse
from pathlib import Path

import open_clip
import pandas as pd
import torch
from PIL import Image

DATA = Path(__file__).parent / "data"
POSTERS = DATA / "posters"

POS_PROMPTS = [
    "a movie poster with a title and artwork",
    "poster art for a horror film",
    "a film poster with actors and dramatic imagery",
]
NEG_PROMPTS = [
    "a website or app logo on a plain background",
    "a generic placeholder image with no photo",
    "a blank or solid color image",
    "a broken image icon",
    "a company brand logo",
]


def load_clip(device):
    m, _, pre = open_clip.create_model_and_transforms("ViT-B-32", pretrained="openai")
    tok = open_clip.get_tokenizer("ViT-B-32")
    m.eval().to(device)
    return m, pre, tok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--ids-file",
        default="",
        help="newline list of ids; default = all imdb_poster_hits + new_omdb_ids",
    )
    ap.add_argument("--out", default=str(DATA / "qa" / "recovered_poster_curation.csv"))
    ap.add_argument(
        "--margin",
        type=float,
        default=0.02,
        help="flag when neg_score is within this margin of (or above) pos_score",
    )
    args = ap.parse_args()

    device = "cpu"
    model, preprocess, tokenizer = load_clip(device)

    if args.ids_file:
        ids = [int(x) for x in Path(args.ids_file).read_text().split() if x.strip()]
    else:
        hits = pd.read_csv(DATA / "imdb_poster_hits.csv")
        omdb = (
            pd.read_csv(DATA / "new_omdb_ids.csv")
            if (DATA / "new_omdb_ids.csv").exists()
            else pd.DataFrame(columns=["id"])
        )
        ids = sorted(set(hits["id"]) | set(omdb["id"]))

    print(f"checking {len(ids):,} recovered posters...")

    with torch.no_grad():
        pos_tok = tokenizer(POS_PROMPTS).to(device)
        neg_tok = tokenizer(NEG_PROMPTS).to(device)
        pos_feat = model.encode_text(pos_tok)
        neg_feat = model.encode_text(neg_tok)
        pos_feat /= pos_feat.norm(dim=-1, keepdim=True)
        neg_feat /= neg_feat.norm(dim=-1, keepdim=True)

    rows = []
    flagged = 0
    for i, pid in enumerate(ids, 1):
        p = POSTERS / f"{pid}.jpg"
        if not p.exists():
            continue
        try:
            img = preprocess(Image.open(p).convert("RGB")).unsqueeze(0).to(device)
        except Exception as e:
            rows.append(
                {"id": pid, "pos_score": 0.0, "neg_score": 0.0, "flagged": True, "error": str(e)}
            )
            flagged += 1
            continue
        with torch.no_grad():
            img_feat = model.encode_image(img)
            img_feat /= img_feat.norm(dim=-1, keepdim=True)
            pos_sim = (img_feat @ pos_feat.T).mean().item()
            neg_sim = (img_feat @ neg_feat.T).mean().item()

        is_flagged = (pos_sim - neg_sim) < args.margin
        if is_flagged:
            flagged += 1
        rows.append(
            {
                "id": pid,
                "pos_score": round(pos_sim, 4),
                "neg_score": round(neg_sim, 4),
                "flagged": is_flagged,
                "error": "",
            }
        )

        if i % 100 == 0:
            print(f"  {i}/{len(ids)} flagged={flagged}", flush=True)

    df = pd.DataFrame(rows)
    df.to_csv(args.out, index=False)
    print("\n=== CURATION DONE ===")
    print(
        f"checked={len(df):,} flagged={flagged:,} ({100 * flagged / max(len(df), 1):.1f}%) -> {args.out}"
    )


if __name__ == "__main__":
    main()

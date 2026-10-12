#!/usr/bin/env python3
"""Grounding DINO creature/weapon boxes -- second, independent zero-shot detector,
run on the SAME id universe and SAME text vocabulary as owlv2_creature_boxes.py,
to cross-check OWLv2 (Nova Pro QA found 64% false_positive on OWLv2's own boxes:
qa_creature_weapon_boxes.py / data/qa/qa_creature_weapon_boxes.csv).

Writes separate output files (does NOT touch creature_boxes.json/weapon_boxes.json):
  data/creature_boxes_dino.json
  data/weapon_boxes_dino.json

Usage (resumable, incremental checkpoint like the other EC2 shard scripts this
session):
  python3 grounding_dino_boxes.py --ids-file data/qa/some_ids.txt \\
    --creature-out data/creature_boxes_dino.json \\
    --weapon-out data/weapon_boxes_dino.json
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import torch
from PIL import Image

from owlv2_creature_boxes import CREATURE_QUERIES, WEAPON_QUERIES, load_box_cache, dump_boxes_json

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
POSTERS = DATA / "posters"

MODEL_ID = "IDEA-Research/grounding-dino-tiny"


def build_prompt(query_map: dict[str, str]) -> tuple[str, list[str], dict[str, str]]:
    """Grounding DINO expects a single caption, lowercase, phrases separated by '. '.
    Returns (caption, phrase_list_in_order, phrase->label lookup)."""
    phrase_to_label = {}
    phrases = []
    for label, phrase in query_map.items():
        p = phrase.lower().strip()
        phrase_to_label[p] = label
        phrases.append(p)
    caption = ". ".join(phrases) + "."
    return caption, phrases, phrase_to_label


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ids-file", required=True)
    ap.add_argument("--creature-out", default=str(DATA / "creature_boxes_dino.json"))
    ap.add_argument("--weapon-out", default=str(DATA / "weapon_boxes_dino.json"))
    ap.add_argument("--min-score", type=float, default=0.25, help="box_threshold")
    ap.add_argument("--text-threshold", type=float, default=0.2)
    ap.add_argument("--checkpoint-every", type=int, default=25)
    ap.add_argument("--posters-dir", default=str(POSTERS))
    ap.add_argument(
        "--device", default="", help="cuda / mps / cpu (default: cuda if available, else cpu)"
    )
    args = ap.parse_args()

    from transformers import AutoProcessor, AutoModelForZeroShotObjectDetection

    device = args.device or ("cuda" if torch.cuda.is_available() else "cpu")
    print(f"loading {MODEL_ID} on {device}…", flush=True)
    processor = AutoProcessor.from_pretrained(MODEL_ID)
    model = AutoModelForZeroShotObjectDetection.from_pretrained(MODEL_ID).to(device).eval()

    creature_caption, creature_phrases, creature_lookup = build_prompt(CREATURE_QUERIES)
    weapon_caption, weapon_phrases, weapon_lookup = build_prompt(WEAPON_QUERIES)
    all_lookup = {**creature_lookup, **weapon_lookup}
    caption = creature_caption[:-1] + ". " + weapon_caption  # merge into one pass
    print(f"caption ({len(all_lookup)} phrases): {caption[:200]}…", flush=True)

    posters_dir = Path(args.posters_dir)
    creature_out = Path(args.creature_out)
    weapon_out = Path(args.weapon_out)
    creature_cache = load_box_cache(creature_out)
    weapon_cache = load_box_cache(weapon_out)

    ids = [int(x) for x in Path(args.ids_file).read_text().split() if x.strip()]
    ids = [i for i in ids if i not in creature_cache or i not in weapon_cache]
    ids = [i for i in ids if (posters_dir / f"{i}.jpg").exists()]
    print(f"todo: {len(ids):,}", flush=True)

    def checkpoint():
        dump_boxes_json(creature_out, creature_cache)
        dump_boxes_json(weapon_out, weapon_cache)

    t0 = time.time()
    n_err = 0
    for n, pid in enumerate(ids, 1):
        try:
            img = Image.open(posters_dir / f"{pid}.jpg").convert("RGB")
            w, h = img.size
            inputs = processor(images=img, text=caption, return_tensors="pt").to(device)
            with torch.no_grad():
                outputs = model(**inputs)
            results = processor.post_process_grounded_object_detection(
                outputs,
                threshold=args.min_score,
                text_threshold=args.text_threshold,
                target_sizes=[(h, w)],
            )[0]
            boxes = results["boxes"].detach().cpu().tolist()
            scores = results["scores"].detach().cpu().tolist()
            phrases = [
                str(x).strip().lower()
                for x in results.get("text_labels", results.get("labels", []))
            ]

            c_rows, w_rows = [], []
            for box, score, phr in zip(boxes, scores, phrases):
                label = all_lookup.get(phr)
                if label is None:
                    # partial/merged phrase match -- fall back to substring lookup
                    for cand_phr, cand_label in all_lookup.items():
                        if cand_phr in phr or phr in cand_phr:
                            label = cand_label
                            break
                if label is None:
                    continue
                x0, y0, x1, y1 = box
                xywh = [
                    round(max(0.0, x0 / w), 4),
                    round(max(0.0, y0 / h), 4),
                    round(max(0.0, (x1 - x0) / w), 4),
                    round(max(0.0, (y1 - y0) / h), 4),
                ]
                area = xywh[2] * xywh[3]
                if area < 0.002 or area > 0.95:
                    continue
                row = {"label": label, "score": round(float(score), 3), "box": xywh}
                (c_rows if label in CREATURE_QUERIES else w_rows).append(row)

            c_rows.sort(key=lambda r: r["score"], reverse=True)
            w_rows.sort(key=lambda r: r["score"], reverse=True)
            creature_cache[pid] = c_rows[:3]
            weapon_cache[pid] = w_rows[:3]
        except Exception as e:
            n_err += 1
            creature_cache.setdefault(pid, [])
            weapon_cache.setdefault(pid, [])
            if n_err <= 5:
                print(f"  FAIL {pid}: {e}", flush=True)

        if n % args.checkpoint_every == 0 or n == len(ids):
            checkpoint()
            rate = n / max(time.time() - t0, 1e-9)
            print(f"  {n:,}/{len(ids):,} rate={rate:.2f}/s err={n_err}", flush=True)

    checkpoint()
    print(
        f"LISTO creature={len(creature_cache):,} weapon={len(weapon_cache):,} err={n_err}",
        flush=True,
    )


if __name__ == "__main__":
    main()

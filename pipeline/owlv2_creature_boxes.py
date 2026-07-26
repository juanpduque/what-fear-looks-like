#!/usr/bin/env python3
"""OWLv2 creature boxes for the lookup overlay (prototype).

Writes:
  data/creature_boxes.json          — {id: [{label,score,box:[x,y,w,h]}, ...]}
  site/data/creature_boxes.js       — window.CREATURE_BOXES=...

Seed from the dry-run cache (no GPU):
  python3 owlv2_creature_boxes.py --from-dryrun

Run OWLv2 on more ids (MPS/CPU, resumable):
  python3 owlv2_creature_boxes.py --ids 244,1091,694
  python3 owlv2_creature_boxes.py --n 200 --seed 42
"""
from __future__ import annotations

import argparse
import json
import random
import time
from collections import defaultdict
from pathlib import Path

import pandas as pd
import torch
from PIL import Image

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
POSTERS = DATA / "posters"
OUT_JSON = DATA / "creature_boxes.json"
OUT_JS = ROOT.parent / "site" / "data" / "creature_boxes.js"
DRY_OWL = DATA / "creature_detect_dryrun_owl.json"

QUERIES = {
    "vampire": "vampire",
    "werewolf": "werewolf",
    "zombie": "zombie",
    "ghost": "ghost",
    "demon": "demon",
    "witch": "witch",
    "skeleton": "skull",
    "alien": "alien",
    "giant_monster": "giant monster",
    "masked_killer": "masked killer",
    "clown": "evil clown",
    "doll": "creepy doll",
    "shark": "shark",
    "spider": "spider",
    "snake": "snake",
    "wolf_dog": "wolf",
    "bird": "bird",
    "insect": "insect",
}
LABELS = list(QUERIES)


def load_cache() -> dict[int, list]:
    if not OUT_JSON.exists():
        return {}
    raw = json.loads(OUT_JSON.read_text(encoding="utf-8"))
    return {int(k): v for k, v in raw.items()}


def save_cache(boxes: dict[int, list]):
    OUT_JSON.write_text(
        json.dumps({str(k): v for k, v in sorted(boxes.items())}, ensure_ascii=False),
        encoding="utf-8",
    )
    OUT_JS.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps({str(k): v for k, v in sorted(boxes.items())}, ensure_ascii=False)
    OUT_JS.write_text(
        "/* OWLv2 creature boxes — pipeline/owlv2_creature_boxes.py */\n"
        f"window.CREATURE_BOXES={payload};\n",
        encoding="utf-8",
    )
    print(f"wrote {OUT_JSON} ({len(boxes)} ids)")
    print(f"wrote {OUT_JS}")


def import_dryrun() -> dict[int, list]:
    if not DRY_OWL.exists():
        raise SystemExit(f"missing {DRY_OWL} — run creature_detect_dryrun.py first")
    raw = json.loads(DRY_OWL.read_text(encoding="utf-8")).get("boxes") or {}
    out = {}
    for k, boxes in raw.items():
        # keep top 3; normalize schema
        clean = []
        for b in boxes[:3]:
            if not isinstance(b, dict) or "box" not in b:
                continue
            clean.append({
                "label": str(b.get("label") or ""),
                "score": float(b.get("score") or 0),
                "box": [float(x) for x in b["box"][:4]],
            })
        out[int(k)] = clean
    return out


def pick_device(name: str) -> str:
    if name != "auto":
        return name
    # Prefer CUDA (EC2 GPU) over MPS for full-corpus runs.
    if torch.cuda.is_available():
        return "cuda"
    if torch.backends.mps.is_available():
        return "mps"
    return "cpu"


def all_corpus_ids() -> list[int]:
    """Analyzed corpus ids that have a local poster jpg."""
    attr = DATA / "attributes.csv"
    src = attr if attr.exists() else DATA / "posters.csv"
    ids = []
    for pid in pd.read_csv(src, usecols=["id"])["id"].astype(int):
        if (POSTERS / f"{pid}.jpg").exists():
            ids.append(int(pid))
    return ids


def filter_boxes(boxes, scores, labels, w, h, min_score=0.2, max_boxes=3):
    rows = []
    for box, score, lab in zip(boxes, scores, labels):
        if float(score) < min_score:
            continue
        x0, y0, x1, y1 = [float(v) for v in box]
        x0, x1 = sorted([x0, x1])
        y0, y1 = sorted([y0, y1])
        xywh = [
            round(max(0.0, x0 / w), 4),
            round(max(0.0, y0 / h), 4),
            round(max(0.0, (x1 - x0) / w), 4),
            round(max(0.0, (y1 - y0) / h), 4),
        ]
        area = xywh[2] * xywh[3]
        if area < 0.002 or area > 0.95:
            continue
        rows.append({"label": str(lab), "score": round(float(score), 3), "box": xywh})
    rows.sort(key=lambda r: r["score"], reverse=True)
    return rows[:max_boxes]


def run_owl(ids: list[int], device: str, min_score: float, cache: dict[int, list]):
    from transformers import Owlv2ForObjectDetection, Owlv2Processor

    model_id = "google/owlv2-base-patch16"
    print(f"loading {model_id} on {device}…", flush=True)
    processor = Owlv2Processor.from_pretrained(model_id)
    model = Owlv2ForObjectDetection.from_pretrained(model_id).to(device).eval()
    text = [[QUERIES[l] for l in LABELS]]
    # Resume: skip ids already present in cache (including empty = no box found).
    todo = [i for i in ids if i not in cache]
    print(f"todo {len(todo)} / requested {len(ids)} (cache {len(cache)})", flush=True)
    print(f"device={device} cuda={torch.cuda.is_available()} "
          f"gpu={torch.cuda.get_device_name(0) if torch.cuda.is_available() else '—'}",
          flush=True)
    t0 = time.time()
    for n, pid in enumerate(todo, 1):
        path = POSTERS / f"{pid}.jpg"
        if not path.exists():
            cache[pid] = []
            continue
        try:
            img = Image.open(path).convert("RGB")
            w, h = img.size
            inputs = processor(text=text, images=img, return_tensors="pt")
            inputs = {k: v.to(device) for k, v in inputs.items()}
            with torch.no_grad():
                outputs = model(**inputs)
            results = processor.post_process_grounded_object_detection(
                outputs=outputs,
                threshold=min_score,
                target_sizes=torch.tensor([[h, w]], device=device),
                text_labels=[LABELS],
            )[0]
            boxes = results["boxes"].detach().cpu().tolist()
            scores = results["scores"].detach().cpu().tolist()
            if results.get("text_labels") is not None:
                labs = [str(x) for x in results["text_labels"]]
            else:
                labs = [LABELS[int(i)] for i in results["labels"].detach().cpu().tolist()]
            cache[pid] = filter_boxes(boxes, scores, labs, w, h, min_score=min_score)
        except Exception as e:
            print(f"  FAIL {pid}: {e}", flush=True)
            cache[pid] = []
        if n % 5 == 0 or n == len(todo):
            save_cache(cache)
            print(f"  {n}/{len(todo)} ({(time.time()-t0)/max(n,1):.1f}s/img)", flush=True)
    del model
    if device == "mps":
        torch.mps.empty_cache()
    return cache


def sample_ids(n: int, seed: int) -> list[int]:
    census = pd.read_csv(DATA / "census.csv")
    census = census[census["id"].map(lambda i: (POSTERS / f"{int(i)}.jpg").exists())]
    by = defaultdict(list)
    for _, r in census.iterrows():
        by[str(r["label"])].append(int(r["id"]))
    rng = random.Random(seed)
    out, seen = [], set()
    labs = [l for l in LABELS if by[l]]
    per = max(1, n // max(1, len(labs)))
    for lab in labs:
        pool = by[lab][: max(per * 3, per)]
        rng.shuffle(pool)
        for pid in pool[:per]:
            if pid not in seen:
                out.append(pid)
                seen.add(pid)
            if len(out) >= n:
                return out
    rest = [int(i) for i in census["id"] if int(i) not in seen]
    rng.shuffle(rest)
    for pid in rest:
        out.append(pid)
        if len(out) >= n:
            break
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--from-dryrun", action="store_true",
                    help="seed site cache from creature_detect_dryrun_owl.json")
    ap.add_argument("--ids", default="", help="comma-separated TMDB ids")
    ap.add_argument("--n", type=int, default=0, help="stratified sample size to run")
    ap.add_argument("--all", action="store_true",
                    help="full analyzed corpus with local posters (~18k)")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--device", default="auto")
    ap.add_argument("--min-score", type=float, default=0.2)
    ap.add_argument("--export-only", action="store_true",
                    help="rewrite .js from existing creature_boxes.json")
    args = ap.parse_args()

    cache = load_cache()
    if args.from_dryrun:
        dry = import_dryrun()
        cache.update(dry)
        save_cache(cache)
        print(f"seeded {len(dry)} ids from dry-run")
    if args.export_only:
        save_cache(cache)
        return

    ids = []
    if args.all:
        ids.extend(all_corpus_ids())
        print(f"--all: {len(ids)} corpus posters on disk", flush=True)
    if args.ids.strip():
        ids.extend(int(x) for x in args.ids.split(",") if x.strip())
    if args.n > 0:
        ids.extend(sample_ids(args.n, args.seed))
    # unique preserve order
    seen, uniq = set(), []
    for i in ids:
        if i not in seen:
            uniq.append(i)
            seen.add(i)
    if uniq:
        device = pick_device(args.device)
        if device == "mps" and len(uniq) > 500:
            print("WARNING: MPS full-run is ~15s/img (~days). Prefer CUDA on EC2 GPU.",
                  flush=True)
        cache = run_owl(uniq, device, args.min_score, cache)
        save_cache(cache)
    elif not args.from_dryrun:
        raise SystemExit("nothing to do — use --from-dryrun / --all / --ids / --n")


if __name__ == "__main__":
    main()

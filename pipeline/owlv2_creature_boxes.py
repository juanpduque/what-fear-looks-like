#!/usr/bin/env python3
"""OWLv2 creature (+ optional weapon) boxes for the lookup overlay.

Writes:
  data/creature_boxes.json          — {id: [{label,score,box:[x,y,w,h]}, ...]}
  site/data/creature_boxes.js       — window.CREATURE_BOXES=...
  data/weapon_boxes.json            — same schema (when --with-weapons)
  site/data/weapon_boxes.js         — window.WEAPON_BOXES=... (when --with-weapons)

Seed from the dry-run cache (no GPU):
  python3 owlv2_creature_boxes.py --from-dryrun

Run OWLv2 on more ids (MPS/CPU/CUDA, resumable):
  python3 owlv2_creature_boxes.py --ids 244,1091,694
  python3 owlv2_creature_boxes.py --n 200 --seed 42
  python3 owlv2_creature_boxes.py --ids-file data/qa/owlv2_backfill_ids.txt --with-weapons

Backfill on EC2 (append-only creature cache; weapons sidecar):
  python3 owlv2_creature_boxes.py --ids-file ids.txt --with-weapons \\
    --device cuda --creature-out data/creature_boxes_delta.json \\
    --weapon-out data/weapon_boxes.json --no-site-js
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
WEAPON_JSON = DATA / "weapon_boxes.json"
WEAPON_JS = ROOT.parent / "site" / "data" / "weapon_boxes.js"
DRY_OWL = DATA / "creature_detect_dryrun_owl.json"

CREATURE_QUERIES = {
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

# Sensible horror-poster weapon vocabulary (OWLv2 open-vocab phrases).
WEAPON_QUERIES = {
    "knife": "knife",
    "gun": "handgun",
    "rifle": "rifle",
    "axe": "axe",
    "sword": "sword",
    "machete": "machete",
    "chainsaw": "chainsaw",
    "scissors": "scissors",
    "syringe": "syringe",
    "hammer": "hammer",
    "baseball_bat": "baseball bat",
    "arrow": "arrow",
}

# Back-compat aliases used by sample_ids / census stratification
QUERIES = CREATURE_QUERIES
LABELS = list(CREATURE_QUERIES)


def load_box_cache(path: Path) -> dict[int, list]:
    if not path.exists():
        return {}
    raw = json.loads(path.read_text(encoding="utf-8"))
    return {int(k): v for k, v in raw.items()}


def load_cache() -> dict[int, list]:
    return load_box_cache(OUT_JSON)


def dump_boxes_json(path: Path, boxes: dict[int, list]):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({str(k): v for k, v in sorted(boxes.items())}, ensure_ascii=False),
        encoding="utf-8",
    )


def write_site_js(path: Path, global_name: str, boxes: dict[int, list], banner: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps({str(k): v for k, v in sorted(boxes.items())}, ensure_ascii=False)
    path.write_text(f"{banner}\nwindow.{global_name}={payload};\n", encoding="utf-8")


def save_cache(boxes: dict[int, list], *, write_js: bool = True):
    dump_boxes_json(OUT_JSON, boxes)
    print(f"wrote {OUT_JSON} ({len(boxes)} ids)")
    if write_js:
        write_site_js(
            OUT_JS,
            "CREATURE_BOXES",
            boxes,
            "/* OWLv2 creature boxes — pipeline/owlv2_creature_boxes.py */",
        )
        print(f"wrote {OUT_JS}")


def save_weapon_cache(boxes: dict[int, list], path: Path = WEAPON_JSON, *, write_js: bool = True):
    dump_boxes_json(path, boxes)
    print(f"wrote {path} ({len(boxes)} ids)")
    if write_js:
        write_site_js(
            WEAPON_JS,
            "WEAPON_BOXES",
            boxes,
            "/* OWLv2 weapon boxes — pipeline/owlv2_creature_boxes.py */",
        )
        print(f"wrote {WEAPON_JS}")


def import_dryrun() -> dict[int, list]:
    if not DRY_OWL.exists():
        raise SystemExit(f"missing {DRY_OWL} — run creature_detect_dryrun.py first")
    raw = json.loads(DRY_OWL.read_text(encoding="utf-8")).get("boxes") or {}
    out = {}
    for k, boxes in raw.items():
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


def read_ids_file(path: Path) -> list[int]:
    ids = []
    for line in path.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        # allow csv first-column
        s = s.split(",")[0].strip()
        ids.append(int(s))
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


def run_owl(
    ids: list[int],
    device: str,
    min_score: float,
    creature_cache: dict[int, list],
    weapon_cache: dict[int, list] | None,
    *,
    creature_labels: list[str],
    weapon_labels: list[str],
    creature_queries: dict[str, str],
    weapon_queries: dict[str, str],
    protect_creature: set[int],
    creature_out: Path,
    weapon_out: Path | None,
    write_js: bool,
    checkpoint_every: int,
    posters_dir: Path,
):
    from transformers import Owlv2ForObjectDetection, Owlv2Processor

    model_id = "google/owlv2-base-patch16"
    print(f"loading {model_id} on {device}…", flush=True)
    processor = Owlv2Processor.from_pretrained(model_id)
    model = Owlv2ForObjectDetection.from_pretrained(model_id).to(device).eval()

    do_weapons = weapon_cache is not None and weapon_labels
    all_labels = list(creature_labels) + (list(weapon_labels) if do_weapons else [])
    query_map = dict(creature_queries)
    if do_weapons:
        query_map.update(weapon_queries)
    text = [[query_map[l] for l in all_labels]]
    creature_set = set(creature_labels)
    weapon_set = set(weapon_labels) if do_weapons else set()

    # Resume: skip ids already present in BOTH requested caches.
    # Creature ids in protect_creature are never rewritten; we still run them if weapons needed.
    todo = []
    for i in ids:
        need_c = (i not in creature_cache) and (i not in protect_creature)
        need_w = do_weapons and (i not in weapon_cache)
        if need_c or need_w:
            todo.append(i)

    print(
        f"todo {len(todo)} / requested {len(ids)} "
        f"(creature_cache {len(creature_cache)} protect {len(protect_creature)} "
        f"weapon_cache {len(weapon_cache or {})} weapons={do_weapons})",
        flush=True,
    )
    print(
        f"queries creature={len(creature_labels)} weapon={len(weapon_labels) if do_weapons else 0} "
        f"total={len(all_labels)}",
        flush=True,
    )
    print(
        f"device={device} cuda={torch.cuda.is_available()} "
        f"gpu={torch.cuda.get_device_name(0) if torch.cuda.is_available() else '—'}",
        flush=True,
    )

    def checkpoint():
        dump_boxes_json(creature_out, creature_cache)
        if write_js and creature_out.resolve() == OUT_JSON.resolve():
            write_site_js(
                OUT_JS,
                "CREATURE_BOXES",
                creature_cache,
                "/* OWLv2 creature boxes — pipeline/owlv2_creature_boxes.py */",
            )
        if do_weapons and weapon_out is not None:
            dump_boxes_json(weapon_out, weapon_cache)
            if write_js and weapon_out.resolve() == WEAPON_JSON.resolve():
                write_site_js(
                    WEAPON_JS,
                    "WEAPON_BOXES",
                    weapon_cache,
                    "/* OWLv2 weapon boxes — pipeline/owlv2_creature_boxes.py */",
                )

    t0 = time.time()
    for n, pid in enumerate(todo, 1):
        path = posters_dir / f"{pid}.jpg"
        if not path.exists():
            if pid not in protect_creature and pid not in creature_cache:
                creature_cache[pid] = []
            if do_weapons and pid not in weapon_cache:
                weapon_cache[pid] = []
        else:
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
                    text_labels=[all_labels],
                )[0]
                boxes = results["boxes"].detach().cpu().tolist()
                scores = results["scores"].detach().cpu().tolist()
                if results.get("text_labels") is not None:
                    labs = [str(x) for x in results["text_labels"]]
                else:
                    labs = [all_labels[int(i)] for i in results["labels"].detach().cpu().tolist()]

                c_idx = [i for i, lab in enumerate(labs) if lab in creature_set]
                if pid not in protect_creature:
                    creature_cache[pid] = filter_boxes(
                        [boxes[i] for i in c_idx],
                        [scores[i] for i in c_idx],
                        [labs[i] for i in c_idx],
                        w, h, min_score=min_score,
                    )
                if do_weapons:
                    w_idx = [i for i, lab in enumerate(labs) if lab in weapon_set]
                    weapon_cache[pid] = filter_boxes(
                        [boxes[i] for i in w_idx],
                        [scores[i] for i in w_idx],
                        [labs[i] for i in w_idx],
                        w, h, min_score=min_score,
                    )
            except Exception as e:
                print(f"  FAIL {pid}: {e}", flush=True)
                if pid not in protect_creature and pid not in creature_cache:
                    creature_cache[pid] = []
                if do_weapons and pid not in weapon_cache:
                    weapon_cache[pid] = []

        if n % max(1, checkpoint_every) == 0 or n == len(todo):
            checkpoint()
            print(f"  {n}/{len(todo)} ({(time.time() - t0) / max(n, 1):.1f}s/img)", flush=True)

    del model
    if device == "mps":
        torch.mps.empty_cache()
    return creature_cache, weapon_cache


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
    ap.add_argument("--ids-file", default="", help="newline / csv-first-col list of ids")
    ap.add_argument("--n", type=int, default=0, help="stratified sample size to run")
    ap.add_argument("--all", action="store_true",
                    help="full analyzed corpus with local posters")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--device", default="auto")
    ap.add_argument("--min-score", type=float, default=0.2)
    ap.add_argument("--export-only", action="store_true",
                    help="rewrite .js from existing creature_boxes.json (+ weapons if present)")
    ap.add_argument("--with-weapons", action="store_true",
                    help="also run weapon queries; write weapon_boxes sidecar")
    ap.add_argument("--creature-out", default=str(OUT_JSON),
                    help="creature boxes JSON path (default data/creature_boxes.json)")
    ap.add_argument("--weapon-out", default=str(WEAPON_JSON),
                    help="weapon boxes JSON path (default data/weapon_boxes.json)")
    ap.add_argument("--protect-creature-from", default="",
                    help="JSON of existing creature boxes — never overwrite those keys")
    ap.add_argument("--no-site-js", action="store_true",
                    help="skip writing site/data/*.js (EC2 delta runs)")
    ap.add_argument("--checkpoint-every", type=int, default=5)
    ap.add_argument("--posters-dir", default=str(POSTERS))
    args = ap.parse_args()

    creature_out = Path(args.creature_out)
    weapon_out = Path(args.weapon_out)
    posters_dir = Path(args.posters_dir)
    write_js = not args.no_site_js

    creature_cache = load_box_cache(creature_out)
    # Also load default OUT_JSON if writing a delta file and cache is empty
    if not creature_cache and creature_out.resolve() != OUT_JSON.resolve() and OUT_JSON.exists():
        # delta mode: start empty (append-only merge happens on pull)
        pass

    protect: set[int] = set()
    if args.protect_creature_from:
        protect = set(load_box_cache(Path(args.protect_creature_from)).keys())
        print(f"protect_creature keys={len(protect)} from {args.protect_creature_from}", flush=True)

    if args.from_dryrun:
        dry = import_dryrun()
        creature_cache.update(dry)
        dump_boxes_json(creature_out, creature_cache)
        if write_js:
            save_cache(creature_cache, write_js=True)
        print(f"seeded {len(dry)} ids from dry-run")

    if args.export_only:
        dump_boxes_json(creature_out, creature_cache)
        if write_js:
            save_cache(load_box_cache(creature_out) if creature_out != OUT_JSON else creature_cache)
            if weapon_out.exists():
                save_weapon_cache(load_box_cache(weapon_out), path=weapon_out, write_js=True)
        return

    ids: list[int] = []
    if args.all:
        ids.extend(all_corpus_ids())
        print(f"--all: {len(ids)} corpus posters on disk", flush=True)
    if args.ids_file.strip():
        ids.extend(read_ids_file(Path(args.ids_file.strip())))
    if args.ids.strip():
        ids.extend(int(x) for x in args.ids.split(",") if x.strip())
    if args.n > 0:
        ids.extend(sample_ids(args.n, args.seed))

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
        weapon_cache = load_box_cache(weapon_out) if args.with_weapons else None
        creature_cache, weapon_cache = run_owl(
            uniq,
            device,
            args.min_score,
            creature_cache,
            weapon_cache,
            creature_labels=list(CREATURE_QUERIES),
            weapon_labels=list(WEAPON_QUERIES),
            creature_queries=CREATURE_QUERIES,
            weapon_queries=WEAPON_QUERIES,
            protect_creature=protect,
            creature_out=creature_out,
            weapon_out=weapon_out if args.with_weapons else None,
            write_js=write_js,
            checkpoint_every=args.checkpoint_every,
            posters_dir=posters_dir,
        )
        dump_boxes_json(creature_out, creature_cache)
        print(f"final creature {creature_out} ({len(creature_cache)} ids)")
        if write_js and creature_out.resolve() == OUT_JSON.resolve():
            save_cache(creature_cache, write_js=True)
        if args.with_weapons and weapon_cache is not None:
            dump_boxes_json(weapon_out, weapon_cache)
            print(f"final weapon {weapon_out} ({len(weapon_cache)} ids)")
            if write_js and weapon_out.resolve() == WEAPON_JSON.resolve():
                save_weapon_cache(weapon_cache, path=weapon_out, write_js=True)
    elif not args.from_dryrun:
        raise SystemExit("nothing to do — use --from-dryrun / --all / --ids / --ids-file / --n")


if __name__ == "__main__":
    main()

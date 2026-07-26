#!/usr/bin/env python3
"""Dry-run: OWLv2 vs Grounding DINO for creature boxes on 100 horror posters.

Uses the Monster Census taxonomy as open-vocab queries. Saves:
  data/creature_detect_dryrun.csv
  data/creature_detect_dryrun.json
  qa/creature-detect-dryrun.html

  python3 creature_detect_dryrun.py
  python3 creature_detect_dryrun.py --n 100 --device mps
"""
from __future__ import annotations

import argparse
import csv
import json
import random
import time
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
import pandas as pd
import torch
from PIL import Image, ImageDraw, ImageFont

DATA = Path(__file__).resolve().parent / "data"
POSTERS = DATA / "posters"
OUT_CSV = DATA / "creature_detect_dryrun.csv"
OUT_JSON = DATA / "creature_detect_dryrun.json"
OUT_OWL = DATA / "creature_detect_dryrun_owl.json"
OUT_DINO = DATA / "creature_detect_dryrun_dino.json"
OUT_HTML = Path(__file__).resolve().parent / "qa" / "creature-detect-dryrun.html"
PREVIEW = DATA / "creature_detect_preview"

# Open-vocab queries — short noun phrases work better than long CLIP captions
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
# Hand-checked artwork from clip_census VALIDATION
SEED_IDS = {
    # filled from census/posters by title+year below if present
}


def pick_device(name: str) -> str:
    if name != "auto":
        return name
    if torch.backends.mps.is_available():
        return "mps"
    if torch.cuda.is_available():
        return "cuda"
    return "cpu"


def sample_ids(n: int, seed: int = 42) -> list[dict]:
    census = pd.read_csv(DATA / "census.csv")
    posts = pd.read_csv(DATA / "posters.csv", usecols=["id", "title", "year"])
    df = census.merge(posts, on="id", how="left", suffixes=("", "_p"))
    if "title" not in df.columns and "title_p" in df.columns:
        df["title"] = df["title_p"]
    df["id"] = df["id"].astype(int)
    df = df[df["id"].map(lambda i: (POSTERS / f"{i}.jpg").exists())].copy()

    # Prefer known validation titles when present
    wanted = [
        ("Godzilla", 1954), ("Jaws", 1975), ("An American Werewolf in London", 1981),
        ("Night of the Living Dead", 1968), ("Arachnophobia", 1990), ("It", 2017),
        ("Annabelle", 2014), ("Halloween", 1978), ("The Birds", 1963), ("Get Out", 2017),
        ("Nosferatu", 1922), ("Dracula", 1931), ("Alien", 1979), ("The Exorcist", 1973),
        ("A Nightmare on Elm Street", 1984), ("Scream", 1996), ("The Ring", 2002),
        ("Hereditary", 2018), ("Midsommar", 2019), ("The Witch", 2015),
    ]
    picked = []
    seen = set()
    for title, year in wanted:
        hit = df[(df["title"].astype(str).str.lower() == title.lower()) & (df["year"] == year)]
        if hit.empty:
            hit = df[df["title"].astype(str).str.contains(title, case=False, na=False)]
            hit = hit[hit["year"] == year] if year and len(hit) else hit
        if len(hit):
            r = hit.iloc[0]
            picked.append(r)
            seen.add(int(r["id"]))

    # Stratify by census label (skip uncertain/none until end)
    rng = random.Random(seed)
    by_lab = defaultdict(list)
    for _, r in df.iterrows():
        if int(r["id"]) in seen:
            continue
        by_lab[str(r["label"])].append(r)

    creature_labs = [l for l in LABELS if l in by_lab]
    per = max(2, (n - len(picked)) // max(1, len(creature_labs)))
    for lab in creature_labs:
        pool = by_lab[lab]
        # prefer higher census score
        pool = sorted(pool, key=lambda r: float(r.get("score") or 0), reverse=True)
        take = pool[: max(per, 3)]
        rng.shuffle(take)
        for r in take[:per]:
            if len(picked) >= n:
                break
            pid = int(r["id"])
            if pid in seen:
                continue
            picked.append(r)
            seen.add(pid)
        if len(picked) >= n:
            break

    # fill remainder with high-score creatures then uncertain
    if len(picked) < n:
        rest = df[~df["id"].isin(seen)].sort_values("score", ascending=False)
        for _, r in rest.iterrows():
            if len(picked) >= n:
                break
            picked.append(r)
            seen.add(int(r["id"]))

    out = []
    for r in picked[:n]:
        out.append({
            "id": int(r["id"]),
            "title": str(r.get("title") or ""),
            "year": int(r.get("year") or 0),
            "census_label": str(r.get("label") or ""),
            "census_score": float(r.get("score") or 0),
        })
    return out


def xyxy_to_xywh_norm(box, w, h):
    x0, y0, x1, y1 = [float(v) for v in box]
    x0, x1 = sorted([x0, x1])
    y0, y1 = sorted([y0, y1])
    return [
        round(max(0.0, x0 / w), 4),
        round(max(0.0, y0 / h), 4),
        round(max(0.0, (x1 - x0) / w), 4),
        round(max(0.0, (y1 - y0) / h), 4),
    ]


def filter_boxes(boxes, scores, labels, w, h, min_score=0.15, max_boxes=5):
    rows = []
    for box, score, lab in zip(boxes, scores, labels):
        if float(score) < min_score:
            continue
        xywh = xyxy_to_xywh_norm(box, w, h)
        area = xywh[2] * xywh[3]
        if area < 0.002 or area > 0.95:
            continue
        rows.append({
            "label": str(lab),
            "score": round(float(score), 3),
            "box": xywh,  # x,y,w,h normalized
        })
    rows.sort(key=lambda r: r["score"], reverse=True)
    return rows[:max_boxes]


def run_owlv2(paths: list[Path], device: str, min_score: float):
    from transformers import Owlv2ForObjectDetection, Owlv2Processor

    model_id = "google/owlv2-base-patch16"
    print(f"loading OWLv2 {model_id} on {device}…", flush=True)
    processor = Owlv2Processor.from_pretrained(model_id)
    model = Owlv2ForObjectDetection.from_pretrained(model_id).to(device).eval()
    text = [[QUERIES[l] for l in LABELS]]  # one shared query list

    out = {}
    if OUT_OWL.exists():
        try:
            out = {int(k): v for k, v in json.loads(OUT_OWL.read_text()).get("boxes", {}).items()}
            print(f"  owl resume: {len(out)} already done", flush=True)
        except Exception:
            out = {}
    t0 = time.time()
    todo = [p for p in paths if int(p.stem) not in out]
    for i, path in enumerate(todo, 1):
        try:
            img = Image.open(path).convert("RGB")
            w, h = img.size
            inputs = processor(text=text, images=img, return_tensors="pt")
            inputs = {k: v.to(device) for k, v in inputs.items()}
            with torch.no_grad():
                outputs = model(**inputs)
            target = torch.tensor([[h, w]], device=device)
            text_labels = [LABELS]
            results = processor.post_process_grounded_object_detection(
                outputs=outputs,
                threshold=min_score,
                target_sizes=target,
                text_labels=text_labels,
            )[0]
            boxes = results["boxes"].detach().cpu().tolist()
            scores = results["scores"].detach().cpu().tolist()
            if "text_labels" in results and results["text_labels"] is not None:
                labs = [str(x) for x in results["text_labels"]]
            else:
                labs = [LABELS[int(i)] for i in results["labels"].detach().cpu().tolist()]
            out[int(path.stem)] = filter_boxes(boxes, scores, labs, w, h, min_score=min_score)
        except Exception as e:
            print(f"  owl FAIL {path.stem}: {e}", flush=True)
            out[int(path.stem)] = []
        if i % 5 == 0 or i == len(todo):
            OUT_OWL.write_text(json.dumps({"boxes": out}, ensure_ascii=False), encoding="utf-8")
            print(f"  owl {len(out)}/{len(paths)} (+{i}/{len(todo)}) ({(time.time()-t0)/max(i,1):.2f}s/img)", flush=True)
    elapsed = time.time() - t0
    OUT_OWL.write_text(json.dumps({"boxes": out}, ensure_ascii=False), encoding="utf-8")
    del model
    if device == "mps":
        torch.mps.empty_cache()
    return out, elapsed


def run_grounding_dino(paths: list[Path], device: str, min_score: float):
    from transformers import AutoModelForZeroShotObjectDetection, AutoProcessor

    # Grounding DINO hits unimplemented MPS ops (cummax); run on CPU on Apple Silicon.
    dino_device = "cpu" if device == "mps" else device
    model_id = "IDEA-Research/grounding-dino-tiny"
    print(f"loading Grounding DINO {model_id} on {dino_device}…", flush=True)
    processor = AutoProcessor.from_pretrained(model_id)
    model = AutoModelForZeroShotObjectDetection.from_pretrained(model_id).to(dino_device).eval()
    # Grounding DINO expects lowercase + trailing dot, categories separated by periods
    caption = " . ".join(QUERIES[l] for l in LABELS) + " ."

    out = {}
    if OUT_DINO.exists():
        try:
            out = {int(k): v for k, v in json.loads(OUT_DINO.read_text()).get("boxes", {}).items()}
            print(f"  dino resume: {len(out)} already done", flush=True)
        except Exception:
            out = {}
    t0 = time.time()
    todo = [p for p in paths if int(p.stem) not in out]
    for i, path in enumerate(todo, 1):
        try:
            img = Image.open(path).convert("RGB")
            w, h = img.size
            inputs = processor(images=img, text=caption, return_tensors="pt")
            inputs = {k: v.to(dino_device) for k, v in inputs.items()}
            with torch.no_grad():
                outputs = model(**inputs)
            results = processor.post_process_grounded_object_detection(
                outputs,
                input_ids=inputs["input_ids"],
                threshold=min_score,
                text_threshold=max(0.15, min_score - 0.05),
                target_sizes=[(h, w)],
                text_labels=[[QUERIES[l] for l in LABELS]],
            )[0]
            boxes = results["boxes"].detach().cpu().tolist()
            scores = results["scores"].detach().cpu().tolist()
            raw_labs = results.get("text_labels") or results.get("labels") or []
            labs = []
            for raw in raw_labs:
                raw_s = str(raw).strip().lower()
                mapped = None
                for lab, q in QUERIES.items():
                    if q == raw_s or q in raw_s or raw_s in q:
                        mapped = lab
                        break
                labs.append(mapped or raw_s.replace(" ", "_"))
            out[int(path.stem)] = filter_boxes(boxes, scores, labs, w, h, min_score=min_score)
        except Exception as e:
            print(f"  dino FAIL {path.stem}: {e}", flush=True)
            out[int(path.stem)] = []
        if i % 5 == 0 or i == len(todo):
            OUT_DINO.write_text(json.dumps({"boxes": out}, ensure_ascii=False), encoding="utf-8")
            print(f"  dino {len(out)}/{len(paths)} (+{i}/{len(todo)}) ({(time.time()-t0)/max(i,1):.2f}s/img)", flush=True)
    elapsed = time.time() - t0
    OUT_DINO.write_text(json.dumps({"boxes": out}, ensure_ascii=False), encoding="utf-8")
    del model
    return out, elapsed


def iou(a, b):
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    ax2, ay2 = ax + aw, ay + ah
    bx2, by2 = bx + bw, by + bh
    ix0, iy0 = max(ax, bx), max(ay, by)
    ix1, iy1 = min(ax2, bx2), min(ay2, by2)
    iw, ih = max(0.0, ix1 - ix0), max(0.0, iy1 - iy0)
    inter = iw * ih
    union = aw * ah + bw * bh - inter
    return inter / union if union > 0 else 0.0


def summarize(sample, owl, dino):
    rows = []
    agree_top = 0
    both_empty = 0
    owl_only = 0
    dino_only = 0
    box_iou_hits = 0
    pair_n = 0
    for s in sample:
        pid = s["id"]
        o = owl.get(pid) or []
        d = dino.get(pid) or []
        o_top = o[0]["label"] if o else None
        d_top = d[0]["label"] if d else None
        if not o and not d:
            both_empty += 1
        elif o and not d:
            owl_only += 1
        elif d and not o:
            dino_only += 1
        if o_top and d_top and o_top == d_top:
            agree_top += 1
        # best IoU between same-label boxes
        best = 0.0
        for ob in o:
            for db in d:
                if ob["label"] != db["label"]:
                    continue
                best = max(best, iou(ob["box"], db["box"]))
        if o and d:
            pair_n += 1
            if best >= 0.3:
                box_iou_hits += 1
        census_match_owl = bool(o_top and o_top == s["census_label"])
        census_match_dino = bool(d_top and d_top == s["census_label"])
        rows.append({
            **s,
            "owl_n": len(o),
            "dino_n": len(d),
            "owl_top": o_top or "",
            "dino_top": d_top or "",
            "owl_top_score": o[0]["score"] if o else "",
            "dino_top_score": d[0]["score"] if d else "",
            "top_agree": int(bool(o_top and d_top and o_top == d_top)),
            "best_same_label_iou": round(best, 3) if best else "",
            "census_match_owl": int(census_match_owl),
            "census_match_dino": int(census_match_dino),
            "owl_boxes": json.dumps(o),
            "dino_boxes": json.dumps(d),
        })
    n = len(sample)
    summary = {
        "n": n,
        "owl_any_box_pct": round(100 * sum(1 for r in rows if r["owl_n"] > 0) / n, 1),
        "dino_any_box_pct": round(100 * sum(1 for r in rows if r["dino_n"] > 0) / n, 1),
        "top_label_agree_pct": round(100 * agree_top / n, 1),
        "both_empty_pct": round(100 * both_empty / n, 1),
        "owl_only_pct": round(100 * owl_only / n, 1),
        "dino_only_pct": round(100 * dino_only / n, 1),
        "same_label_iou>=0.3_pct_of_pairs": round(100 * box_iou_hits / pair_n, 1) if pair_n else 0,
        "census_match_owl_pct": round(100 * sum(r["census_match_owl"] for r in rows) / n, 1),
        "census_match_dino_pct": round(100 * sum(r["census_match_dino"] for r in rows) / n, 1),
        "owl_label_counts": Counter(r["owl_top"] for r in rows if r["owl_top"]),
        "dino_label_counts": Counter(r["dino_top"] for r in rows if r["dino_top"]),
    }
    return rows, summary


def draw_preview(sample, owl, dino, limit=24):
    PREVIEW.mkdir(parents=True, exist_ok=True)
    paths = []
    for s in sample[:limit]:
        pid = s["id"]
        src = POSTERS / f"{pid}.jpg"
        img = Image.open(src).convert("RGB")
        w, h = img.size
        canvas = Image.new("RGB", (w * 2 + 20, h + 40), (20, 20, 24))
        left, right = img.copy(), img.copy()
        for boxes, im, color in (
            (owl.get(pid) or [], left, (229, 160, 13)),
            (dino.get(pid) or [], right, (193, 18, 31)),
        ):
            dr = ImageDraw.Draw(im)
            for b in boxes[:3]:
                x, y, bw, bh = b["box"]
                x0, y0, x1, y1 = x * w, y * h, (x + bw) * w, (y + bh) * h
                dr.rectangle([x0, y0, x1, y1], outline=color, width=3)
                dr.text((x0 + 3, max(0, y0 - 12)), f"{b['label']} {b['score']}", fill=color)
        canvas.paste(left, (0, 30))
        canvas.paste(right, (w + 20, 30))
        dr = ImageDraw.Draw(canvas)
        title = f"{s['title']} ({s['year']})  census={s['census_label']}"
        dr.text((8, 8), "OWLv2  |  " + title, fill=(230, 230, 220))
        dr.text((w + 28, 8), "Grounding DINO", fill=(230, 230, 220))
        out = PREVIEW / f"{pid}.jpg"
        canvas.save(out, quality=85)
        paths.append(out)
    return paths


def write_html(rows, summary, owl_s, dino_s):
    OUT_HTML.parent.mkdir(parents=True, exist_ok=True)
    cards = []
    for r in rows[:40]:
        pid = r["id"]
        prev = PREVIEW / f"{pid}.jpg"
        img = f'<img src="../data/creature_detect_preview/{pid}.jpg" loading="lazy">' if prev.exists() else ""
        cards.append(
            f"<article><h3>{r['title']} ({r['year']})</h3>"
            f"<p>census: <b>{r['census_label']}</b> ({r['census_score']}) · "
            f"owl: <b>{r['owl_top'] or '—'}</b> · dino: <b>{r['dino_top'] or '—'}</b></p>"
            f"{img}</article>"
        )
    html = f"""<!doctype html>
<meta charset="utf-8">
<title>Creature detect dry-run — OWLv2 vs Grounding DINO</title>
<style>
body{{font-family:Georgia,serif;background:#0a0a0c;color:#e8e4da;margin:24px;max-width:1100px}}
code,b{{color:#e5a00d}}
.grid{{display:grid;gap:18px}}
article{{border:1px solid #2a2a30;padding:12px;border-radius:4px}}
img{{width:100%;height:auto;display:block;margin-top:8px}}
.k{{font-family:ui-monospace,monospace;font-size:13px;line-height:1.55}}
</style>
<h1>OWLv2 vs Grounding DINO — dry-run n={summary['n']}</h1>
<pre class="k">{json.dumps({k:v for k,v in summary.items() if not isinstance(v, Counter)}, indent=2)}
owl_time_s={owl_s:.1f}
dino_time_s={dino_s:.1f}
owl_labels={dict(summary['owl_label_counts'])}
dino_labels={dict(summary['dino_label_counts'])}
</pre>
<p>Amber boxes = OWLv2 · Red boxes = Grounding DINO (tiny). Queries = Monster Census taxonomy nouns.</p>
<div class="grid">{''.join(cards)}</div>
"""
    OUT_HTML.write_text(html, encoding="utf-8")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=100)
    ap.add_argument("--device", default="auto")
    ap.add_argument("--min-score", type=float, default=0.2)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--skip-dino", action="store_true")
    ap.add_argument("--skip-owl", action="store_true")
    args = ap.parse_args()
    device = pick_device(args.device)
    print(f"device={device} n={args.n} min_score={args.min_score}", flush=True)

    sample = sample_ids(args.n, seed=args.seed)
    paths = [POSTERS / f"{s['id']}.jpg" for s in sample]
    print(f"sample labels: {Counter(s['census_label'] for s in sample)}", flush=True)

    owl, owl_s = ({}, 0.0)
    dino, dino_s = ({}, 0.0)
    if not args.skip_owl:
        owl, owl_s = run_owlv2(paths, device, args.min_score)
    if not args.skip_dino:
        dino, dino_s = run_grounding_dino(paths, device, args.min_score)

    rows, summary = summarize(sample, owl, dino)
    summary["owl_seconds"] = round(owl_s, 1)
    summary["dino_seconds"] = round(dino_s, 1)
    summary["owl_sec_per_img"] = round(owl_s / max(len(sample), 1), 2)
    summary["dino_sec_per_img"] = round(dino_s / max(len(sample), 1), 2)

    pd.DataFrame(rows).to_csv(OUT_CSV, index=False)
    payload = {
        "summary": {
            **{k: (dict(v) if isinstance(v, Counter) else v) for k, v in summary.items()},
        },
        "queries": QUERIES,
        "models": {
            "owl": "google/owlv2-base-patch16",
            "dino": "IDEA-Research/grounding-dino-tiny",
        },
        "rows": rows,
    }
    OUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    draw_preview(sample, owl, dino, limit=30)
    write_html(rows, summary, owl_s, dino_s)

    print("\n=== SUMMARY ===", flush=True)
    for k, v in summary.items():
        if isinstance(v, Counter):
            print(f"  {k}: {dict(v)}", flush=True)
        else:
            print(f"  {k}: {v}", flush=True)
    print(f"wrote {OUT_CSV}", flush=True)
    print(f"wrote {OUT_JSON}", flush=True)
    print(f"wrote {OUT_HTML}", flush=True)


if __name__ == "__main__":
    main()
